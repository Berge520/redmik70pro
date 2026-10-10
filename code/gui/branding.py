# -*- coding: utf-8 -*-
"""品牌视觉：应用图标（.ico）生成与窗口图标注入。

设计要点：
- 纯标准库实现（struct / zlib），不依赖 Pillow。打包配置已 exclude PIL，
  且本模块需要在"未安装任何第三方库"的机器上也能运行。
- 图标以 3 倍超采样手工光栅化，再逐级降采样，边缘平滑无锯齿。
- 生成的多尺寸 ico 同时供打包（spec 的 icon=）与运行时（窗口左上角）使用。
"""

import os
import struct
import sys
import zlib

# brand.ico 与窗口标题栏图标使用的图形语言：圆角方块 + 系统蓝 + 白色 "R"
ICO_NAME = 'brand.ico'

# 图标中使用的颜色（RGBA），与界面系统蓝 #007aff 同源
_BG_TOP = (10, 132, 255, 255)    # #0a84ff
_BG_BOTTOM = (0, 105, 217, 255)   # #0069d9
_GLYPH = (255, 255, 255, 255)

# 图标内嵌尺寸，覆盖 Windows 任务栏 / 资源管理器 / Alt+Tab 各种场景
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# 字形点阵：7 宽 × 9 高，'R'（1=前景）
_GLYPH_R = (
    '1111100',
    '1000110',
    '1000110',
    '1000110',
    '1111100',
    '1011000',
    '1001100',
    '1000110',
    '1000011',
)


# ---------------------------------------------------------------
#  光栅化
# ---------------------------------------------------------------
def _blank(size):
    return bytearray(size * size * 4)


def _put(buf, size, x, y, rgba):
    if 0 <= x < size and 0 <= y < size:
        i = (y * size + x) * 4
        buf[i:i + 4] = bytes(rgba)


def _rounded_mask(size):
    """圆角方块覆盖掩码（3× 超采样求平均，得到抗锯齿的 0~255 覆盖率）。"""
    scale = 3
    n = size * scale
    radius = n * 0.22
    cx0, cy0 = radius, radius
    cx1, cy1 = n - radius, n - radius
    mask = bytearray(size * size)
    for y in range(size):
        for x in range(size):
            cov = 0
            for sy in range(scale):
                py = y * scale + sy + 0.5
                for sx in range(scale):
                    px = x * scale + sx + 0.5
                    if radius <= px <= n - radius or radius <= py <= n - radius:
                        inside = True
                    else:
                        dx = cx0 - px if px < cx0 else (px - cx1 if px > cx1 else 0)
                        dy = cy0 - py if py < cy0 else (py - cy1 if py > cy1 else 0)
                        inside = (dx * dx + dy * dy) <= radius * radius
                    if inside:
                        cov += 1
            mask[y * size + x] = (cov * 255) // (scale * scale)
    return mask


def _glyph_hits(size):
    """把字形点阵映射到像素坐标，返回落在字形内的像素集合。"""
    gw, gh = len(_GLYPH_R[0]), len(_GLYPH_R)
    # 字形占图标边长的 54%，并居中
    span = size * 0.54
    cw = span / gw
    ch = span / gh
    off_x = (size - span) / 2.0
    off_y = (size - span) / 2.0
    hits = set()
    for gy in range(size):
        for gx in range(size):
            mx = int((gx + 0.5 - off_x) / cw)
            my = int((gy + 0.5 - off_y) / ch)
            if 0 <= mx < gw and 0 <= my < gh and _GLYPH_R[my][mx] == '1':
                hits.add((gx, gy))
    return hits


def render_rgba(size):
    """渲染指定边长的 RGBA 像素缓冲（bytes）。"""
    buf = _blank(size)
    mask = _rounded_mask(size)
    glyph = _glyph_hits(size)
    span_lo = size * 0.23
    span_hi = size * 0.77
    for y in range(size):
        t = (y - span_lo) / (span_hi - span_lo)
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        base = tuple(int(_BG_TOP[i] + (_BG_BOTTOM[i] - _BG_TOP[i]) * t)
                     for i in range(4))
        for x in range(size):
            cov = mask[y * size + x]
            if cov == 0:
                continue
            rgba = _GLYPH if (x, y) in glyph else base
            if cov == 255:
                _put(buf, size, x, y, rgba)
            else:
                # 背景透明，按覆盖率预乘 alpha 混合到全透明底
                _put(buf, size, x, y,
                     (rgba[0], rgba[1], rgba[2], (rgba[3] * cov) // 255))
    return bytes(buf)


def _downsample(buf, size, factor):
    """整数倍降采样（盒式滤波），用于从超采样底图得到目标尺寸。"""
    out_size = size // factor
    out = _blank(out_size)
    area = factor * factor
    for oy in range(out_size):
        for ox in range(out_size):
            r = g = b = a = 0
            for dy in range(factor):
                for dx in range(factor):
                    i = ((oy * factor + dy) * size + (ox * factor + dx)) * 4
                    r += buf[i]
                    g += buf[i + 1]
                    b += buf[i + 2]
                    a += buf[i + 3]
            _put(out, out_size, ox, oy,
                 (r // area, g // area, b // area, a // area))
    return bytes(out)


# ---------------------------------------------------------------
#  BMP / ICO 封装
# ---------------------------------------------------------------
def _bmp_payload(size, supersample=4):
    """生成 ICO 内嵌的 BMP（BITMAPINFOHEADER + XOR 位图 + AND 掩码）。

    高度写为目标尺寸的 2 倍以携带 alpha；AND 掩码置 0（alpha 已表达透明）。
    """
    if supersample > 1:
        big = render_rgba(size * supersample)
        rgba = _downsample(big, size * supersample, supersample)
    else:
        rgba = render_rgba(size)

    header = struct.pack(
        '<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0,
        len(rgba), 0, 0, 0, 0)
    # BMP 像素自底向上、BGRA 顺序
    lines = []
    for y in range(size - 1, -1, -1):
        row = bytearray()
        for x in range(size):
            i = (y * size + x) * 4
            row += bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
        lines.append(bytes(row))
    xor = b''.join(lines)
    and_row = ((size + 31) // 32) * 4      # 32bpp 掩码按 4 字节对齐
    and_mask = b'\x00' * (and_row * size)
    return header + xor + and_mask


def build_ico(sizes=ICO_SIZES):
    """构建多尺寸 Windows .ico 的完整字节流。"""
    images = [(s, _bmp_payload(s)) for s in sizes]
    count = len(images)
    entries = bytearray()
    blobs = bytearray()
    offset = 6 + 16 * count
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', dim, dim, 0, 0, 1, 32,
                               len(data), offset)
        blobs += data
        offset += len(data)
    return struct.pack('<HHH', 0, 1, count) + bytes(entries) + bytes(blobs)


# ---------------------------------------------------------------
#  对外接口
# ---------------------------------------------------------------
def ico_bytes():
    return build_ico()


def icon_path():
    """返回仓库内预生成的 brand.ico 路径（不存在则返回 None）。

    打包成 exe 后，brand.ico 由 spec 的 datas 放在解包根目录（_MEIPASS），
    而本模块文件位于 _MEIPASS/gui/ 下，因此需要一并检查上两级目录。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    bases = [
        os.path.join(here, 'assets'),
        here,
        os.path.join(os.path.dirname(here), 'packaging'),
    ]
    # PyInstaller 解包目录（brand.ico 由 datas 复制到该目录根部）
    bundle = getattr(sys, '_MEIPASS', None)
    if bundle:
        bases.append(os.path.join(bundle, 'packaging'))
        bases.append(bundle)
    for base in bases:
        cand = os.path.join(base, ICO_NAME)
        if os.path.isfile(cand):
            return cand
    return None


def apply_window_icon(window):
    """尽力为 Tk 窗口设置图标；任何失败都静默忽略（不影响启动）。"""
    path = icon_path()
    if path and sys.platform == 'win32':
        try:
            window.iconbitmap(default=path)
            return
        except Exception:
            pass
    # 源码运行时未预置文件：现场渲染最小位图（Tk 需要 PNG，此处改用 iconbitmap 兜底）
    try:
        from tkinter import PhotoImage
        png = _render_png(64)
        img = PhotoImage(data=png)
        window.iconphoto(True, img)
        window._icon_ref = img          # 防止被 GC 回收导致图标消失
    except Exception:
        pass


def _render_png(size):
    """把 RGBA 缓冲编码为 PNG（base64 文本，供 PhotoImage(data=) 使用）。"""
    import base64
    rgba = render_rgba(size)
    raw = bytearray()
    for y in range(size):
        raw.append(0)                   # 每行过滤器类型 0
        raw += rgba[y * size * 4:(y + 1) * size * 4]

    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body +
                struct.pack('>I', zlib.crc32(body) & 0xffffffff))

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    return base64.b64encode(png).decode('ascii')


if __name__ == '__main__':
    # 手动执行本模块即可重新生成仓库内的图标文件
    targets = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'packaging'),
    ]
    data = ico_bytes()
    for d in targets:
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, ICO_NAME)
        with open(out, 'wb') as fh:
            fh.write(data)
        print('已生成 %s（%d 字节）' % (out, len(data)))
