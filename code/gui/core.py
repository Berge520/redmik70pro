# -*- coding: utf-8 -*-
"""
RootTool 核心逻辑层
封装 adb / fastboot / ksud 的调用，向上提供线程安全的执行接口。

设计要点：
- 所有外部命令通过 run() 统一执行，保证 CWD 固定为工具根目录，
  避免"双击能跑、管理员跑找不到 adb"的经典问题。
- 输出逐行回调给 UI，实现实时日志。
- 不依赖任何第三方库，仅用 Python 标准库。
"""

import os
import re
import sys
import shutil
import subprocess
import threading
import time
from datetime import datetime


# ---------------------------------------------------------------
#  路径解析
# ---------------------------------------------------------------
def _bundle_dir():
    """只读资源目录：adb / fastboot / ksud 等随程序分发的文件所在处。

    - 打包成单文件 exe：PyInstaller 会把数据解包到 sys._MEIPASS，
      二进制即位于该目录（--add-data 打入），故指向它。
    - 源码运行：本文件位于 <root>/gui/core.py，向上一级即为仓库根目录。
    """
    mei = getattr(sys, '_MEIPASS', None)
    if mei:
        return mei
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _writable_dir():
    """可写目录：日志等需要持久化的数据写在这里。

    - 打包成 exe：exe 自身所在目录（与程序同级，便于用户查看）。
      临时解包目录 _MEIPASS 退出即删，不能用于写日志。
    - 源码运行：与 _bundle_dir() 一致，即仓库根目录。
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return _bundle_dir()


def get_root_dir():
    """工具根目录（即 adb.exe / fastboot.exe / ksud 所在目录）。"""
    return _bundle_dir()


ROOT_DIR = get_root_dir()
LOG_DIR = os.path.join(_writable_dir(), 'logs')

# 二进制可能直接放在资源目录，也可能放在 tools/ 子目录（本仓库的布局）。
# 两者都纳入查找范围，避免源码运行时"开箱即挂"。
_TOOL_DIRS = (ROOT_DIR, os.path.join(ROOT_DIR, 'tools'))

# 应用的显示名称 / 版本，集中定义避免各处漂移。
APP_NAME = '小米/红米 临时Root 专业工具'
APP_VERSION = 'v0.0.2'
APP_TITLE = '%s %s' % (APP_NAME, APP_VERSION)

# 隐藏子进程黑窗（Windows）
_CREATE_NO_WINDOW = 0x08000000


def _popen_kwargs():
    kw = {
        'cwd': ROOT_DIR,
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.PIPE,
        'stderr': subprocess.STDOUT,
        'shell': False,
    }
    if sys.platform == 'win32':
        kw['creationflags'] = _CREATE_NO_WINDOW
    return kw


def _decode(data):
    """adb/fastboot 在 Windows 上输出为 GBK，优先按 GBK 解码。"""
    if data is None:
        return ''
    if isinstance(data, str):
        return data
    for enc in ('gbk', 'utf-8'):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode('utf-8', errors='replace')


def find_tool(name):
    """在根目录、tools/ 子目录和 PATH 中查找可执行文件，返回绝对路径或 None。

    查找顺序：根目录 → tools/ → PATH。
    这样无论二进制放在根目录（打包后的常见布局）还是 tools/（本仓库布局），
    都能被找到，源码运行无需手工移动文件或改 PATH。
    """
    candidates = [name]
    if sys.platform == 'win32' and not name.lower().endswith('.exe'):
        candidates.insert(0, name + '.exe')
    for base in _TOOL_DIRS:
        for cand in candidates:
            local = os.path.join(base, cand)
            if os.path.isfile(local):
                return local
    for cand in candidates:
        found = shutil.which(cand)
        if found:
            return found
    return None


# ---------------------------------------------------------------
#  日志
# ---------------------------------------------------------------
# 日志保留数量：仅保留最近的若干份，超出的在启动时自动清理，避免无限增长。
LOG_KEEP = 30


def prune_logs(keep=LOG_KEEP):
    """清理 logs/ 下过期的会话日志，仅保留最近 keep 份。

    按文件名（含时间戳）倒序排列，删除多余项。任何异常都静默忽略，
    清理失败不应影响主流程。
    """
    try:
        names = [n for n in os.listdir(LOG_DIR)
                 if n.startswith('root_') and n.endswith('.log')]
    except OSError:
        return
    if len(names) <= keep:
        return
    names.sort(reverse=True)
    for name in names[keep:]:
        try:
            os.remove(os.path.join(LOG_DIR, name))
        except OSError:
            pass


class Logger:
    """按会话写入 logs/root_YYYYmmdd_HHMMSS.log，并转发到 UI 回调。"""

    def __init__(self, sink=None):
        self.sink = sink
        os.makedirs(LOG_DIR, exist_ok=True)
        prune_logs()
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.path = os.path.join(LOG_DIR, 'root_%s.log' % stamp)
        self._lock = threading.Lock()

    def write(self, text):
        line = '[%s] %s' % (datetime.now().strftime('%H:%M:%S'), text)
        with self._lock:
            try:
                with open(self.path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except OSError:
                pass
        if self.sink:
            self.sink(line)


# ---------------------------------------------------------------
#  进程执行
# ---------------------------------------------------------------
class CmdResult:
    def __init__(self, code, lines):
        self.code = code
        self.lines = lines

    @property
    def text(self):
        return '\n'.join(self.lines)

    @property
    def ok(self):
        return self.code == 0

    def first(self):
        return self.lines[0].strip() if self.lines else ''


class Runner:
    """统一命令执行器。

    run() 会实时把每一行输出喂给 emit 回调，方便 UI 显示进度。
    支持通过 cancel_check 回调实现取消：执行期间轮询该回调，
    一旦返回 True 立即终止子进程。
    """

    def __init__(self, logger=None, emit=None):
        self.logger = logger
        self.emit = emit
        # 当前正在运行的子进程；取消时由 run() 内部 kill。
        self._proc = None
        self._proc_lock = threading.Lock()
        # 串行化 run()：run 内部用单一 self._proc 槽位记录当前子进程，
        # 若两个命令并发执行，后启动的会覆盖前者的槽位，导致前者被
        # cancel_current() 误杀并打印「命令已取消」。加锁后同一时刻只有
        # 一条命令在跑，从根本上消除这类误报（adb/fastboot 本身也不宜并发）。
        self._run_lock = threading.Lock()
        # 全局取消判据：由上层（如 UI 的任务层）设置一个无参回调，
        # 返回 True 表示请求取消。run() 在每个命令执行期间轮询它，
        # 因此无需每个调用点都显式传 cancel_check。
        self.cancel_check = None

    def _log(self, msg):
        if self.logger:
            self.logger.write(msg)

    def _out(self, msg):
        if self.emit:
            self.emit(msg)

    def cancel_current(self):
        """强制终止当前正在执行的子进程（若有）。

        由取消流程调用，配合 run() 的轮询实现"立即停下"。
        """
        with self._proc_lock:
            proc = self._proc
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass

    def run(self, args, timeout=60, quiet=False, check_cwd=True,
            cancel_check=None):
        """执行命令（进程级串行，见 _run_lock）。"""
        # 整个执行过程持锁，保证同一时刻只有一条命令在跑，
        # 避免并发命令互相覆盖 self._proc 造成误杀/误报取消。
        with self._run_lock:
            return self._run_once(args, timeout, quiet, cancel_check)

    def _run_once(self, args, timeout, quiet, cancel_check):
        """run() 的实际实现，需在 _run_lock 保护下调用。

        args: 列表形式的命令，如 ['adb', 'devices']
        quiet: 不向 emit 输出原始行，且不把命令行/取消/超时写入日志
               （轮询类命令用 quiet=True，避免日志被刷屏）
        cancel_check: 无参回调，返回 True 表示请求取消，子进程将被终止
        """
        if isinstance(args, str):
            args = [args]

        exe = find_tool(args[0])
        if not exe:
            msg = '[错误] 未找到命令 %s，请确认已安装并放入工具目录或加入 PATH。' % args[0]
            self._log(msg)
            if not quiet:
                self._out(msg)
            return CmdResult(127, [msg])

        argv = [exe] + list(args[1:])
        # quiet 命令多为设备轮询，写日志只会刷屏，故只在非 quiet 时记录。
        if not quiet:
            self._log('执行: ' + ' '.join(argv))

        try:
            proc = subprocess.Popen(argv, **_popen_kwargs())
        except OSError as exc:
            msg = '[错误] 无法启动 %s：%s' % (args[0], exc)
            self._log(msg)
            if not quiet:
                self._out(msg)
            return CmdResult(126, [msg])

        with self._proc_lock:
            self._proc = proc

        # 边执行边轮询：
        #  - 到达超时 → kill 并标记超时
        #  - cancel_check 返回 True → kill 并标记已取消
        # 不能直接用 communicate(timeout=...) 一把梭，否则无法在运行中途响应取消。
        deadline = time.time() + timeout
        cancelled = False
        timed_out = False
        # 未显式传入时使用全局取消判据，使所有命令默认支持取消。
        probe = cancel_check if cancel_check is not None else self.cancel_check
        try:
            while True:
                try:
                    out, _ = proc.communicate(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    if probe is not None and probe():
                        cancelled = True
                        proc.kill()
                        out, _ = proc.communicate()
                        break
                    if time.time() >= deadline:
                        timed_out = True
                        proc.kill()
                        out, _ = proc.communicate()
                        break
        finally:
            with self._proc_lock:
                self._proc = None

        lines = []
        for raw in _decode(out).splitlines():
            line = raw.rstrip('\r\n')
            if line:
                lines.append(line)
                if not quiet:
                    self._out(line)

        if cancelled:
            msg = '[已取消] 命令已被用户中断。'
            lines.append(msg)
            if not quiet:
                self._log('命令已取消: %s' % ' '.join(argv))
        elif timed_out:
            msg = '[超时] 命令执行超过 %d 秒已终止。' % timeout
            lines.append(msg)
            if not quiet:
                self._log('命令超时: %s' % ' '.join(argv))

        return CmdResult(proc.returncode, lines)

    def shell(self, cmd, **kw):
        """执行 adb shell <cmd>（cmd 为单个字符串）。"""
        return self.run(['adb', 'shell', cmd], **kw)

    def su(self, cmd, **kw):
        """以 root 执行 adb shell su -c <cmd>。"""
        return self.run(['adb', 'shell', 'su', '-c', cmd], **kw)


# ---------------------------------------------------------------
#  设备检测
# ---------------------------------------------------------------
class DeviceState:
    def __init__(self):
        self.adb = False
        self.fastboot = False
        # 处于 recovery / sideload 状态的设备：第三方 Recovery（TWRP 等）
        # 会启动 adbd 且自带 root shell，此时 adb 命令仍可用，但状态
        # 不是 'device'。单独标记，供重启等功能区分对待。
        self.adb_recovery = False
        # 明细：ADB 侧每台设备的 (序列号, 状态)，状态可能是
        # device / unauthorized / offline / recovery / sideload 等；
        # Fastboot 侧为序列号列表。
        # 保留明细是为了在"手机已插上但未授权/离线"时给出可读提示，
        # 而不是笼统地判定为"未检测到设备"。
        self.adb_devices = []
        self.fastboot_devices = []

    @property
    def any(self):
        return self.adb or self.fastboot or self.adb_recovery

    @property
    def adb_usable(self):
        """ADB 是否可用（普通 device 状态或 recovery/sideload 状态）。"""
        return self.adb or self.adb_recovery

    def recovery_targets(self):
        """返回处于 recovery / sideload 状态的设备 (序列号, 状态) 列表。"""
        return [(sn, s) for sn, s in self.adb_devices
                if s.lower() in ('recovery', 'sideload')]

    def describe(self):
        """返回一句可读的连接状态描述，用于日志与按钮反馈。"""
        if self.adb and self.fastboot:
            return 'ADB 与 Fastboot 均已连接'
        if self.adb:
            if self.fastboot:
                return 'ADB 与 Fastboot 均已连接'
            return 'ADB 已连接'
        if self.adb_recovery:
            rec = self.recovery_targets()
            parts = ['%s(%s)' % (sn, s) for sn, s in rec]
            return 'ADB 已连接（Recovery 模式）：' + '、'.join(parts)
        if self.fastboot:
            return 'Fastboot 已连接'
        # 有设备但未就绪：把真实状态（unauthorized/offline）透出，
        # 这是"明明连了手机却检测不到"最常见的原因。
        if self.adb_devices:
            parts = ['%s(%s)' % (sn, state) for sn, state in self.adb_devices]
            return '检测到 ADB 设备但未就绪：' + '、'.join(parts)
        if self.fastboot_devices:
            return '检测到 Fastboot 设备但未就绪：' + '、'.join(self.fastboot_devices)
        return '未检测到设备'


def start_adb_server(runner):
    """确保 adb server 正在运行，返回是否成功。

    adb devices 在 server 未启动时虽然会自动拉起，但首次拉起需要数秒，
    且偶发因端口占用/旧进程残留而失败，导致"手机已连接却列出空表"。
    这里显式 start-server 并等待，可显著降低这类漏检。
    """
    # -a 让 server 监听所有接口；仅本机使用可去掉，这里保持默认行为。
    res = runner.run(['adb', 'start-server'], quiet=True, timeout=30)
    return res.ok


def _parse_adb_devices(lines):
    """解析 adb devices 输出，返回 [(序列号, 状态)]。

    跳过 "List of devices attached" 等表头行；只保留形如
    "abcdef\tdevice" 的有效行。状态可能是 device / unauthorized /
    offline / recovery / sideload 等。
    """
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] != 'List':
            out.append((parts[0], parts[1]))
    return out


def detect_devices(runner):
    """检测 ADB / Fastboot 连接状态，返回 DeviceState。"""
    st = DeviceState()

    res = runner.run(['adb', 'devices'], quiet=True, timeout=20)
    st.adb_devices = _parse_adb_devices(res.lines)
    st.adb = any(state == 'device' for _, state in st.adb_devices)
    # recovery / sideload 状态的设备：第三方 Recovery 下 adb 仍可用，
    # 区别于 unauthorized / offline（真正不可用），单独标记。
    st.adb_recovery = any(
        state.lower() in ('recovery', 'sideload') for _, state in st.adb_devices)

    res = runner.run(['fastboot', 'devices'], quiet=True, timeout=20)
    for line in res.lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1].lower() in ('fastboot', 'fastbootd'):
            st.fastboot_devices.append(parts[0])
    st.fastboot = bool(st.fastboot_devices)

    return st


def find_ksud():
    """返回 ksud 载荷的绝对路径（根目录或 tools/），找不到返回 None。"""
    for base in _TOOL_DIRS:
        path = os.path.join(base, 'ksud')
        if os.path.isfile(path):
            return path
    return None


# MIUI mqsas 服务漏洞的提权命令（供模式 2 / 模式 6 共用）。
# 放在 core 中以免 UI 模块之间互相 import 造成耦合。
EXPLOIT_CMD = ('service call miui.mqsas.IMQSNative 21 i32 1 '
               's16 /data/local/tmp/ksud i32 1 s16 late-load '
               's16 /sdcard/ksulog.txt i32 60')


def is_root(runner):
    """判断是否已获得真实 Root 权限。

    只认真实证据：su 执行 id 后输出 uid=0，或当前 shell 本身 uid=0。
    不再使用 /data/adb/ksud 是否存在、内核模块是否加载之类的旁证——
    这些在"推送了载荷但提权尚未成功"时也会成立，会造成误判。
    """
    res = runner.su('id', quiet=True, timeout=15)
    if res.ok and 'uid=0' in res.text:
        return True
    res = runner.shell('id', quiet=True, timeout=15)
    if 'uid=0' in res.text:
        return True
    return False


def is_admin():
    """当前进程是否以管理员权限运行。"""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# 提权重启时传给新实例的命令行标记：新实例据此跳过单实例询问，
# 因为旧实例会在提权成功后自行退出，不需要（也不应该）被强制结束。
ELEVATED_FLAG = '--elevated'


def relaunch_as_admin():
    """以管理员权限重新启动当前程序（触发 UAC 提权）。

    返回 (是否已发起, 说明)：
      - 成功发起：返回 (True, '')，调用方应随后彻底退出当前实例。
      - 用户取消 UAC 或失败：返回 (False, 原因)。

    打包为 exe 时用 sys.executable；开发态（python 运行 .py）时用
    ShellExecuteW 重新以管理员身份拉起 python 并带上原脚本参数。

    开发态务必使用【绝对路径】的脚本并显式指定工作目录，否则提权后
    新进程的工作目录会变（继承系统目录），相对路径的 main.py 找不到，
    导致新实例启动失败。

    额外附带 ELEVATED_FLAG 参数：新实例据此跳过"是否结束旧实例"的单实例
    询问。提权是"旧实例主动让位"的场景——旧实例会在本函数成功后自行退出，
    若新实例仍去询问并强杀旧实例，就会出现新旧互相打断、"关了又开"的错乱。
    """
    if sys.platform != 'win32':
        return False, '仅支持 Windows 平台提权。'
    if is_admin():
        return False, '当前已是管理员权限。'
    import ctypes
    try:
        if getattr(sys, 'frozen', False):
            # 已打包：直接提权重启 exe，工作目录设为 exe 所在目录
            exe = os.path.abspath(sys.executable)
            params = ELEVATED_FLAG
            workdir = os.path.dirname(exe)
        else:
            # 开发态：提权重启 python 并传入原脚本（转为绝对路径）
            exe = os.path.abspath(sys.executable)
            script = os.path.abspath(sys.argv[0])
            rest = ' '.join('"%s"' % a for a in sys.argv[1:])
            params = ' '.join(p for p in ('"%s"' % script, rest, ELEVATED_FLAG) if p)
            workdir = os.path.dirname(script)
        # SW_SHOWNORMAL = 1；lpOperation = 'runas' 触发 UAC；
        # lpDirectory 显式指定新进程的工作目录，避免继承系统目录。
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, 'runas', exe, params, workdir, 1)
        # 返回值 > 32 表示成功发起；<= 32 为错误码（如用户取消为 5）
        if ret > 32:
            return True, ''
        return False, '提权请求被取消或失败（错误码 %d）。' % ret
    except Exception as exc:
        return False, '提权失败：%s' % exc


# 单实例互斥由 gui/single_instance.py 统一负责（启动器 roottool.pyw 调用），
# 此处不再重复实现，避免两套互斥机制互相干扰。


_KSU_PKG = 'me.weishu.kernelsu'


def probe_root(runner):
    """多方式探测 Root 状态。

    返回 (状态, 依据, tag, 明细列表)：
      - 状态：'已获取' / '疑似已获取（未确认）' / '未获取'
      - 依据：一句话说明
      - tag：'ok' / 'warn' / 'bad'
      - 明细：[(方式, 结果描述, 是否命中布尔值)]

    权威口径与 is_root 保持一致：只有真实 uid=0 证据才判"已获取"，
    其余（su 二进制存在、内核模块加载、SELinux 宽松）均只作旁证。
    """
    detail = []
    # 方式 1：su -c id（最权威）
    res = runner.su('id', quiet=True, timeout=15)
    su_uid = res.ok and 'uid=0' in res.text
    detail.append(('su -c id', '返回 uid=0' if su_uid else '未返回 uid=0', su_uid))
    # 方式 2：当前 shell 自身 uid（部分开发版/root shell 下直接即为 0）
    res2 = runner.shell('id', quiet=True, timeout=15)
    shell_uid = 'uid=0' in res2.text
    detail.append(('adb shell id', '返回 uid=0' if shell_uid else '未返回 uid=0', shell_uid))
    if su_uid or shell_uid:
        return '已获取', 'su/shell 返回 uid=0', 'ok', detail

    # 方式 3：su 二进制是否存在（旁证）
    su_path = runner.shell(
        'which su || command -v su || ls /system/bin/su /system/xbin/su /sbin/su 2>/dev/null',
        quiet=True, timeout=15).first()
    has_su = bool(su_path)
    detail.append(('su 二进制', su_path or '未找到', has_su))

    # 方式 4：KernelSU 载荷（旁证）
    has_ksud = runner.shell('test -x /data/adb/ksud', quiet=True, timeout=15).ok
    detail.append(('KernelSU 载荷', '/data/adb/ksud 存在' if has_ksud else '不存在', has_ksud))

    # 方式 5：内核模块（旁证）
    mods = runner.shell('ls /sys/module/', quiet=True, timeout=15).text.lower()
    has_kmod = 'kernelsu' in mods
    detail.append(('内核模块', 'kernelsu 已加载' if has_kmod else '未发现 kernelsu', has_kmod))

    # 方式 6：SELinux 是否宽松（旁证）
    sel = runner.shell('getenforce', quiet=True, timeout=15).first().strip()
    is_perm = sel.lower() == 'permissive'
    detail.append(('SELinux', '%s' % (sel or '未知'), is_perm))

    if has_ksud:
        return '疑似已获取（未确认）', '/data/adb/ksud 存在（旁证，不代表已提权）', 'warn', detail
    if has_kmod:
        return '疑似已获取（未确认）', '内核模块 kernelsu 已加载（旁证）', 'warn', detail
    if is_perm:
        return '疑似已获取（未确认）', 'SELinux 处于 Permissive（旁证）', 'warn', detail
    return '未获取', 'su 与 shell 均未返回 uid=0', 'bad', detail


def probe_ksu(runner):
    """多方式探测 KernelSU 是否已加载。

    返回 (状态, 依据, tag, 明细列表)，明细同 probe_root。
    只要管理器包存在即认为"已安装"；载荷/内核模块存在即认为"已加载"。
    """
    detail = []
    # 方式 1：管理器包
    pkgs = runner.shell('pm list packages', quiet=True, timeout=25).text
    has_pkg = _KSU_PKG in pkgs
    detail.append(('管理器包', _KSU_PKG if has_pkg else '未安装', has_pkg))
    if has_pkg:
        return '已安装（管理器存在）', '检测到包 %s' % _KSU_PKG, 'ok', detail

    # 方式 2：内核模块
    mods = runner.shell('ls /sys/module/', quiet=True, timeout=15).text.lower()
    has_kmod = 'kernelsu' in mods
    detail.append(('内核模块', 'kernelsu 已加载' if has_kmod else '未发现 kernelsu', has_kmod))
    if has_kmod:
        return '已加载（内核模块）', '内核模块 kernelsu 已加载', 'ok', detail

    # 方式 3：ksud 载荷
    has_ksud = runner.shell('test -x /data/adb/ksud', quiet=True, timeout=15).ok
    detail.append(('ksud 载荷', '/data/adb/ksud 存在' if has_ksud else '不存在', has_ksud))
    if has_ksud:
        return '已加载（LKM 模式）', '/data/adb/ksud 存在', 'ok', detail

    # 方式 4：/data/adb 目录（弱旁证）
    has_dir = runner.shell('test -d /data/adb', quiet=True, timeout=15).ok
    detail.append(('/data/adb 目录', '存在' if has_dir else '不存在', has_dir))
    if has_dir:
        return '疑似已加载（目录存在）', '/data/adb 目录存在', 'warn', detail

    return '未检测到', '未发现管理器包 / 内核模块 / ksud 载荷', 'bad', detail


def preflight():
    """启动自检：返回 (ok, 问题列表)。"""
    problems = []
    for name in ('adb', 'fastboot'):
        if not find_tool(name):
            problems.append('未找到 %s.exe，请放入工具目录或加入 PATH。' % name)
    if not find_ksud():
        problems.append('工具目录（或 tools/）下缺少 ksud 文件。')
    return (not problems), problems


# ---------------------------------------------------------------
#  Android 信息读取
# ---------------------------------------------------------------
def getprop(runner, key, timeout=15):
    return runner.shell('getprop ' + key, quiet=True, timeout=timeout).first()


def get_sdk(runner):
    val = getprop(runner, 'ro.build.version.sdk')
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def list_modules(runner):
    """返回已安装模块的目录名列表。

    仅保留通过白名单校验的目录名——这些名字随后会被拼入 su 命令，
    若放任 `ls` 输出直接透传，恶意模块可借助特殊目录名实现命令注入。
    """
    res = runner.su('ls /data/adb/modules/', quiet=True, timeout=20)
    if not res.ok:
        return []
    out = []
    for line in res.lines:
        name = line.strip()
        if name and valid_module_name(name):
            out.append(name)
    return out


def read_module_name(runner, folder):
    """读取模块的显示名（module.prop 中的 name）。"""
    if not valid_module_name(folder):
        return ''
    res = runner.su('cat /data/adb/modules/%s/module.prop' % folder,
                    quiet=True, timeout=15)
    for line in res.lines:
        if line.startswith('name='):
            return line[5:].strip()
    return ''


def module_state(runner, folder):
    """读取模块状态，返回 'enabled' / 'disabled' / 'removed'。

    KernelSU / Magisk 约定：
      /data/adb/modules/<模块>/disable  —— 存在则被禁用（重启后不加载，文件保留）
      /data/adb/modules/<模块>/remove   —— 存在则标记为待删除（重启后由管理器清理）
    """
    if not valid_module_name(folder):
        return 'enabled'
    base = '/data/adb/modules/%s' % folder
    if runner.su('test -f %s/remove' % base, quiet=True, timeout=15).ok:
        return 'removed'
    if runner.su('test -f %s/disable' % base, quiet=True, timeout=15).ok:
        return 'disabled'
    return 'enabled'


def list_module_states(runner):
    """返回 [(folder, name, state)]，一次读取全部模块名与状态。

    仅为被禁用的模块额外发一次 su 探测 remove 标记，避免禁用状态下
    误判为待删除。"""
    out = []
    for folder in list_modules(runner):
        name = read_module_name(runner, folder)
        state = module_state(runner, folder)
        out.append((folder, name, state))
    return out


# 模块名安全校验：只允许字母、数字、下划线、连字符、点，且不含 ..
_MODULE_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def valid_module_name(name):
    if not name or '..' in name:
        return False
    return bool(_MODULE_RE.match(name))


# Xposed 模块标识：包名（含点）或模块目录名，允许字母/数字/下划线/连字符/点，
# 但不能以点开头或结尾，且不含连续的 ".."（避免路径穿越）。
# 该值会被拼入 root 命令，故必须严格白名单，杜绝 shell 元字符注入。
_XP_ID_RE = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$')


def valid_xposed_id(name):
    if not name:
        return False
    return bool(_XP_ID_RE.match(name))


# ---------------------------------------------------------------
#  重启控制
# ---------------------------------------------------------------
def soft_reboot(runner):
    """软重启：只重启 Android 用户空间框架，不切断电源。

    依次尝试多种方式，任一成功即返回 (True, 命中的命令, 尝试明细)：
      1. setprop ctl.restart zygote —— 重启 zygote，系统框架整体重启
      2. svc power reboot userspace —— Android 官方软重启入口
    该操作不清缓存、不断电，通常 10~30 秒恢复，可让模块 / Root 服务重新加载。
    全部失败时返回 (False, '', 尝试明细)，供调用方把"试过哪些方式"透出给用户。
    """
    methods = (
        "setprop ctl.restart zygote",
        "svc power reboot userspace",
    )
    tried = []
    for cmd in methods:
        r = runner.su(cmd, quiet=True, timeout=30)
        tried.append((cmd, r.ok))
        if r.ok:
            return True, cmd, tried
    return False, '', tried


def _reboot_cmd(runner, target):
    """下发重启到指定目标，兼容普通系统与第三方 Recovery。

    普通系统：adb reboot <target> 直接生效。
    第三方 Recovery（TWRP 等）：adbd 以 root 运行，状态为 recovery，
    直接 reboot 同样可用，但偶发需要 shell 形式，故加兜底。
    """
    args = ['adb', 'reboot'] + ([target] if target else [])
    if runner.run(args, quiet=True, timeout=20).ok:
        return True
    cmd = 'reboot ' + target if target else 'reboot'
    return runner.shell(cmd, quiet=True, timeout=20).ok


def full_reboot(runner):
    """完整重启手机（等价于手动关机再开机）。"""
    return _reboot_cmd(runner, '')


def reboot_recovery(runner):
    """重启到 Recovery 模式。"""
    return _reboot_cmd(runner, 'recovery')


def reboot_bootloader(runner):
    """重启到 Fastboot / bootloader 模式。"""
    return _reboot_cmd(runner, 'bootloader')


def reboot_edl(runner):
    """重启到 EDL（高通 9008 深度刷机模式）。

    小米 / 红米机型常见：进入后窗口将无法识别设备（无 adb / fastboot），
    需借助特定工具与 9008 驱动进行底层刷写。部分机型/固件会忽略该指令。
    """
    if _reboot_cmd(runner, 'edl'):
        return True
    # 部分机型的 EDL 入口是 /sys 节点或专用属性。
    return runner.shell('echo 1 > /sys/kernel/reboot/reason', quiet=True,
                        timeout=15).ok


def power_off(runner):
    """关机（断开电源），recovery 下用 shell 兜底。"""
    if runner.run(['adb', 'shell', 'reboot', '-p'], quiet=True, timeout=20).ok:
        return True
    return runner.shell('reboot -p', quiet=True, timeout=20).ok


# ---------------------------------------------------------------
#  Zygisk 框架探测与激活（兼容 NeoZygisk 与 Zygisk Next）
# ---------------------------------------------------------------
# 具体实现已拆分到同目录 zygisk_core.py（便于单文件维护），此处仅做转发，
# 使既有 `core.xxx` 调用保持零改动。模块内常量与函数清单见 zygisk_core.py。
from zygisk_core import *  # noqa: F401,F403
from zygisk_core import (  # noqa: F401 - 显式列出以便静态检查与 IDE 补全
    ZYGISK_MODULE,
    ZYGISK_MODULE_DIR,
    ZYGISK_NEO_BIN,
    ZYGISK_NEO_TMP,
    ZYGISK_NEO_PROP,
    ZYGISK_NEXT_BIN,
    ZYGISK_NEXT_BIN64,
    ZYGISK_NEXT_PROC,
    ZYGISK_MONITOR_LOG,
    ZY_NONE,
    ZY_NEO,
    ZY_NEXT,
    ZY_LABEL,
    detect_zygisk,
    zygisk_monitor_running,
    zygisk_read_prop,
    zygisk_status,
    zygisk_zygote_count,
    start_zygisk_daemon,
    zygote64_pid,
    zygote_injected,
    restart_zygote,
)



# ---------------------------------------------------------------
#  Xposed 框架检测
# ---------------------------------------------------------------
# 具体实现已拆分到同目录 xposed_core.py（便于单文件维护），此处仅做转发，
# 使既有 `core.xxx` 调用保持零改动。模块内常量与函数清单见 xposed_core.py。
from xposed_core import *  # noqa: F401,F403
from xposed_core import (  # noqa: F401 - 显式列出以便静态检查与 IDE 补全
    XP_NONE,
    XP_VECTOR,
    XP_LSPOSED,
    XP_ORIGINAL,
    XP_ORIGINAL_INSTALLED,
    XP_CLI,
    VECTOR_MODULE_DIR,
    XP_VECTOR_CLI_PATHS,
    XP_LOG_DIR,
    valid_xposed_id,
    valid_scope_target,
    detect_xposed,
    xposed_fd_attached,
    xposed_module_list,
    xposed_hook_evidence,
    xposed_module_scope,
    xposed_scope_list,
    xposed_scope_add,
    xposed_scope_remove,
    xposed_vectord_running,
)


# ---------------------------------------------------------------
#  异步任务
# ---------------------------------------------------------------
class Task:
    """把一段耗时逻辑放到后台线程，避免界面卡死。

    用法：
        Task(fn).start()          # fn(ctl) 在后台执行
        Task(fn, on_done=cb)      # 完成后在主线程由 UI 自行调度
    ctl.cancelled 可被 UI 置位以实现中断。
    """

    def __init__(self, fn, on_done=None, on_error=None):
        self.fn = fn
        self.on_done = on_done
        self.on_error = on_error
        self.cancelled = False
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._wrap, daemon=True)
        self.thread.start()

    def _wrap(self):
        try:
            result = self.fn(self)
            if self.on_done:
                self.on_done(result)
        except Exception as exc:  # noqa: BLE001 - 后台线程需兜底
            if self.on_error:
                self.on_error(exc)

    def cancel(self):
        self.cancelled = True


def sleep_cancellable(ctl, seconds, step=0.2):
    """可中断的等待：按 step 轮询多次，一旦 ctl.cancelled 就立即返回。

    返回 True 表示等待被取消提前结束，False 表示完整睡满 seconds。
    ctl 为 None 或无 cancelled 属性时退化为 time.sleep。
    供各模式模块共享，避免在 UI 模块之间互相 import。
    """
    if ctl is None or not hasattr(ctl, 'cancelled'):
        time.sleep(seconds)
        return False
    remain = float(seconds)
    while remain > 0:
        if ctl.cancelled:
            return True
        chunk = step if remain > step else remain
        time.sleep(chunk)
        remain -= chunk
    return ctl.cancelled
