# -*- coding: utf-8 -*-
"""模式12：相关链接（本项目 / KernelSU / Zygisk / Vector 的 GitHub 地址）"""

import webbrowser

import tkinter as tk

import main as ui

# (名称, 版本/说明, 链接, 标签色)
LINKS = [
    ('本项目：redmik70pro', '红米 K70 Pro 免解锁临时 Root 工具',
     'https://github.com/Berge520/redmik70pro', ui.C_ACCENT),
    ('KernelSU', '内核级 Root 方案（本工具依赖其 late-load 模式）',
     'https://github.com/tiann/KernelSU', ui.C_SIDE_ACTIVE),
    ('Zygisk-Next', 'Zygisk 实现（模块 id：zygisksu）',
     'https://github.com/Dr-TSNG/ZygiskNext', ui.C_WARN),
    ('Vector', 'LSPosed 现代复刻（模块 id：zygisk_vector）',
     'https://github.com/JingMatrix/Vector', ui.C_OK),
]

# 本项目自身仓库地址（LINKS 首项），供「打开本项目仓库」按钮使用。
# 单独命名，避免依赖 LINKS 的下标顺序，列表调整时不会静默指错链接。
PROJECT_URL = LINKS[0][2]


class LinksFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, '相关链接',
                  '本项目及其核心依赖的开源仓库地址。点击「打开链接」将用系统默认浏览器打开对应页面。')

        # 顶部操作：一键打开全部
        top = tk.Frame(inner, bg=ui.C_PANEL)
        top.pack(fill='x', pady=(0, 10))
        ui.button(top, '★ 打开本项目仓库', self.open_project, accent=True)
        ui.button(top, '打开全部依赖仓库', self.open_all)

        # 链接卡片列表
        for name, desc, url, color in LINKS:
            self._card(inner, name, desc, url, color)

        # 底部提示
        tk.Label(inner,
                 text='提示：若网络无法访问 GitHub，可自行为浏览器配置代理，或使用镜像加速站点。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL,
                 justify='left').pack(anchor='w', pady=(8, 0))

    def _card(self, parent, name, desc, url, color):
        """构建单条链接卡片。"""
        card, body = ui.card(parent, accent=color, pad=(12, 10))
        card.pack(fill='x', pady=(0, 8))

        tk.Label(body, text=name, bg=ui.C_PANEL, fg=color,
                 font=ui.FONT_BOLD).pack(anchor='w')
        tk.Label(body, text=desc, bg=ui.C_PANEL, fg=ui.C_MUTED,
                 font=ui.FONT_SMALL, justify='left').pack(anchor='w', pady=(2, 0))
        tk.Label(body, text=url, bg=ui.C_PANEL, fg=ui.C_ACCENT,
                 font=ui.FONT_MONO, justify='left').pack(anchor='w', pady=(2, 0))

        ui.button(card, '打开链接', lambda u=url: self._open(u)).pack(
            side='right', padx=12, pady=10)

    # -----------------------------------------------------------
    def on_device_change(self, st):
        pass

    def _open(self, url):
        try:
            webbrowser.open(url)
            self.app.log_out('[链接] 已在浏览器中打开：%s' % url)
        except Exception as e:
            self.app.log_out('[错误] 无法打开链接：%s（%s）' % (url, e))

    def open_project(self):
        self._open(PROJECT_URL)

    def open_all(self):
        for _name, _desc, url, _color in LINKS:
            self._open(url)
