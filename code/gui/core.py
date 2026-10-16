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
APP_VERSION = 'v0.0.1'
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

    @property
    def any(self):
        return self.adb or self.fastboot


def detect_devices(runner):
    """检测 ADB / Fastboot 连接状态，返回 DeviceState。"""
    st = DeviceState()

    res = runner.run(['adb', 'devices'], quiet=True, timeout=15)
    for line in res.lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            st.adb = True
            break

    res = runner.run(['fastboot', 'devices'], quiet=True, timeout=15)
    for line in res.lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1].lower() == 'fastboot':
            st.fastboot = True
            break

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

    依次尝试多种方式，任一成功即返回：
      1. setprop ctl.restart zygote —— 重启 zygote，系统框架整体重启
      2. svc power reboot userspace —— Android 官方软重启入口
    该操作不清缓存、不断电，通常 10~30 秒恢复，可让模块 / Root 服务重新加载。
    """
    methods = (
        "setprop ctl.restart zygote",
        "svc power reboot userspace",
    )
    for cmd in methods:
        r = runner.su(cmd, quiet=True, timeout=30)
        if r.ok:
            return True, cmd
    return False, methods[0]


def full_reboot(runner):
    """完整重启手机（等价于手动关机再开机）。"""
    return runner.run(['adb', 'reboot'], quiet=True, timeout=20).ok


def reboot_recovery(runner):
    """重启到 Recovery 模式。"""
    return runner.run(['adb', 'reboot', 'recovery'], quiet=True, timeout=20).ok


def reboot_bootloader(runner):
    """重启到 Fastboot / bootloader 模式。"""
    return runner.run(['adb', 'reboot', 'bootloader'], quiet=True, timeout=20).ok


def power_off(runner):
    """关机（断开电源）。"""
    return runner.run(['adb', 'shell', 'reboot', '-p'], quiet=True, timeout=20).ok


# ---------------------------------------------------------------
#  Zygisk 框架探测与激活（兼容 NeoZygisk 与 Zygisk Next）
# ---------------------------------------------------------------
# ⚠️ 二者模块 ID **同为 `zygisksu`**（历史上都沿用 Magisk 的 zygisksu 目录），
#    无法靠目录名区分，必须靠「入口可执行文件 / 常驻进程名」判定：
#      · NeoZygisk (JingMatrix)：bin/zygisk-ptrace64，常驻 zygisk-ptrace64，
#        运行时目录 /data/adb/neozygisk，状态写在 $TMP/module.prop（键值文本）。
#      · Zygisk Next (LSPosed Developers)：bin/zygiskd（软链→zygiskd64）、
#        bin/zygiskd32、bin/zygiskd64。注入完成后会为每个 zygote 派生一个名为
#        `zn-nsdaemon-zygote` / `zn-nsdaemon-zygote_secondary` 的守护进程，并建立
#        `@zn_zygote_*` / `@zn_init_*` 系列 unix socket；zygiskd 自身的「管理器」
#        进程 comm 名不可见（ps 的 NAME 列看不到），只能靠 /proc/<pid>/exe 软链识别。
#        状态查询：在 $MODDIR 下执行 `./bin/zygiskd status`，输出 `zygote_states: N`
#        （N=已注入的 zygote 数）与 `zygote_state_i:...` 明细。
# ⚠️ **注入判据不可通用**：NeoZygisk 把 libzygisk.so 常驻映射在 zygote 里，可用
#    `grep -c libzygisk /proc/<zygote64>/maps` 判定；但 Zygisk Next 注入后会**把
#    自身 loader（libzn_loader.so 等）从 zygote 的 maps 中 unmap 掉**（反检测），
#    实测该 grep 恒为 0。故 Zygisk Next 必须改用 `zygiskd status` 的 `zygote_states`。
#    详见 docs/troubleshooting.md「七、GUI 工具的框架自动识别」。
ZYGISK_MODULE = 'zygisksu'
ZYGISK_MODULE_DIR = '/data/adb/modules/%s' % ZYGISK_MODULE

# NeoZygisk 专属
ZYGISK_NEO_BIN = ZYGISK_MODULE_DIR + '/bin/zygisk-ptrace64'
ZYGISK_NEO_TMP = '/data/adb/neozygisk'
ZYGISK_NEO_PROP = ZYGISK_NEO_TMP + '/module.prop'

# Zygisk Next 专属
ZYGISK_NEXT_BIN = ZYGISK_MODULE_DIR + '/bin/zygiskd'   # 兼容不分 ABI 子目录的旧版
ZYGISK_NEXT_BIN64 = ZYGISK_MODULE_DIR + '/bin/zygiskd64'
ZYGISK_NEXT_PROC = 'zn-nsdaemon-zygote'                # 注入后派生的 zygote 守护进程

ZYGISK_MONITOR_LOG = '/data/local/tmp/monitor.log'

# 探测结果类型
ZY_NONE = 'none'
ZY_NEO = 'neo'          # NeoZygisk
ZY_NEXT = 'next'        # Zygisk Next
ZY_LABEL = {
    ZY_NEO: 'NeoZygisk',
    ZY_NEXT: 'Zygisk Next',
    ZY_NONE: '未检测到 Zygisk 框架',
}


def detect_zygisk(runner):
    """探测本机安装的 Zygisk 实现，返回 ZY_* 常量之一。

    判据（按可靠性排序）：
      1. 入口文件：bin/zygisk-ptrace64 → NeoZygisk；bin/**/zygiskd → Zygisk Next。
         （Zygisk Next 的 zygiskd 按 ABI 分目录，故用通配匹配任意一层。）
      2. 常驻进程：zygisk-ptrace64 / zn-nsdaemon-zygote（运行时兜底）。
      3. 运行时目录：/data/adb/neozygisk 存在 → NeoZygisk。
    均不命中返回 ZY_NONE。
    """
    # 1. 入口文件（最可靠，模块未运行时也可判定）
    if runner.su('test -x ' + ZYGISK_NEO_BIN, quiet=True, timeout=15).ok:
        return ZY_NEO
    # Zygisk Next 的 zygiskd 位于 bin/<abi>/zygiskd
    if runner.su('ls %s/bin/*/zygiskd %s/bin/zygiskd 2>/dev/null'
                 % (ZYGISK_MODULE_DIR, ZYGISK_MODULE_DIR),
                 quiet=True, timeout=15).text.strip():
        return ZY_NEXT
    # 2. 常驻进程兜底
    if runner.shell('pgrep -f zygisk-ptrace64', quiet=True, timeout=15).text.strip():
        return ZY_NEO
    # Zygisk Next 注入后会派生 zn-nsdaemon-zygote（未注入时不存在）；
    # zygiskd 管理器进程 comm 名不可见，故再兜一个 exe 软链判定。
    if runner.shell('pgrep -f %s' % ZYGISK_NEXT_PROC,
                    quiet=True, timeout=15).text.strip():
        return ZY_NEXT
    if runner.su('for p in /proc/[0-9]*; do '
                 'e=$(readlink $p/exe 2>/dev/null); '
                 'case "$e" in *zygiskd*) exit 0;; esac; done; exit 1',
                 quiet=True, timeout=20).ok:
        return ZY_NEXT
    # 3. 运行时目录兜底
    if runner.su('test -d ' + ZYGISK_NEO_TMP, quiet=True, timeout=15).ok:
        return ZY_NEO
    return ZY_NONE


def zygisk_monitor_running(runner, kind=None):
    """Zygisk 注入服务是否在运行（按框架分派）。

    · NeoZygisk：常驻进程名 zygisk-ptrace64（monitor）。
    · Zygisk Next：zygiskd 管理器进程（comm 名不可见），用 /proc/<pid>/exe
      软链是否指向 bin/zygiskd* 判定；注入后还会派生 zn-nsdaemon-zygote。
    kind 为空时自动探测，避免重复探测可显式传入。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        return bool(runner.shell('pgrep -f zygisk-ptrace64',
                                 quiet=True, timeout=15).text.strip())
    if kind == ZY_NEXT:
        # 管理器进程在 → daemon 已拉起（这是「服务在跑」的可靠判据）。
        if runner.su('for p in /proc/[0-9]*; do '
                     'e=$(readlink $p/exe 2>/dev/null); '
                     'case "$e" in *zygiskd*) exit 0;; esac; done; exit 1',
                     quiet=True, timeout=20).ok:
            return True
        # 兜底：已注入时必有 zn-nsdaemon-zygote。
        return bool(runner.shell('pgrep -f %s' % ZYGISK_NEXT_PROC,
                                 quiet=True, timeout=15).text.strip())
    return False


def zygisk_read_prop(runner):
    """读取 NeoZygisk 运行时状态文件，返回 {key: value}。

    monitor 运行时会实时重写 $ZYGISK_NEO_TMP/module.prop，内容形如：
        monitor: 😋 tracing
        zygote64: 😋 injected
        daemon64: 😋 running
        Modules (2): hma_oss_zygisk, zygisk_vector
    monitor 未运行时该文件可能不存在或为空，此时返回空字典。
    （Zygisk Next 无此文件，调用前请先用 detect_zygisk 判定。）
    """
    res = runner.su('cat %s' % ZYGISK_NEO_PROP, quiet=True, timeout=15)
    info = {}
    if not res.ok:
        return info
    for line in res.lines:
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        info[key.strip()] = value.strip()
    return info


def zygisk_status(runner, kind=None):
    """返回 Zygisk 状态摘要文本（按框架分派），失败返回空串。

    · NeoZygisk：读 $ZYGISK_NEO_TMP/module.prop（键值文本）。
    · Zygisk Next：执行 `./bin/zygiskd status`（含 zygote_states 字段）。
      必须以 $MODDIR 为 CWD 执行（zygiskd 内部走相对路径）。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        return runner.su('cat %s' % ZYGISK_NEO_PROP, quiet=True, timeout=15).text
    if kind == ZY_NEXT:
        res = runner.su(
            'cd %(d)s && ./bin/zygiskd status 2>&1' % {'d': ZYGISK_MODULE_DIR},
            quiet=True, timeout=20)
        return res.text
    return ''


def zygisk_zygote_count(runner, kind=None):
    """返回已接管的 zygote 数量，无法解析返回 -1。

    · NeoZygisk：统计 module.prop 中值为 "injected" 的键（如 zygote64）。
    · Zygisk Next：解析 `zygiskd status` 输出里的 `zygote_states: N`。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        info = zygisk_read_prop(runner)
        return sum(1 for v in info.values() if 'injected' in v.lower())
    if kind == ZY_NEXT:
        text = zygisk_status(runner, ZY_NEXT)
        m = re.search(r'zygote_states\s*:\s*(\d+)', text)
        return int(m.group(1)) if m else -1
    return -1


def start_zygisk_daemon(runner, kind=None):
    """以正确的 CWD 启动 Zygisk 注入服务（重越狱后手动补启动）。

    ⚠️ 关键：NeoZygisk 的 zygisk-ptrace64 内部全部使用相对路径
    （./bin/zygiskd64、./module.prop、./lib64/libzygisk.so），
    因此**必须以模块目录 $MODDIR 为工作目录启动**，否则会因找不到
    ./module.prop 而立刻 exit=1，注入阶段也会因找不到 ./bin/zygiskd64 中断。
    这正是官方 post-fs-data.sh 里 `cd "$MODDIR"` 那一步的作用。

    · NeoZygisk：`cd $MODDIR && ./bin/zygisk-ptrace64 monitor &`
    · Zygisk Next：`cd $MODDIR && ./bin/zygiskd daemon &`（等价于官方
      post-fs-data.sh 最后那一步；daemon 会自行常驻并派生子进程）。

    ⚠️ 两者都**不能直接执行官方脚本**：NeoZygisk 没有前台脚本；Zygisk Next
    的 post-fs-data.sh 末行 `./bin/zygiskd daemon` 会**前台常驻不返回**，
    经 `su -c 'sh ./post-fs-data.sh'` 调用会让整个 su 会话永久挂起。
    因此这里统一改为「后台化 daemon + 短超时放行 + 复查进程」。

    late-load 模式下 ksud 是后注入的，不会自动重放 post-fs-data 事件，
    故重越狱后必须手动补启动。返回 (ok, 说明)。
    """
    kind = kind or detect_zygisk(runner)

    if kind == ZY_NEO:
        if not runner.su('test -x ' + ZYGISK_NEO_BIN, quiet=True, timeout=15).ok:
            return False, '未找到 %s，请确认已安装 NeoZygisk 模块（%s）。' % (
                ZYGISK_NEO_BIN, ZYGISK_MODULE)
        # 先清理可能存在的旧 monitor / 脏 socket，再以正确 CWD 启动，避免重复实例。
        # ⚠️ 清理必须用 `pkill -x zygisk-ptrace64`（按精确进程名匹配），
        #    不能用 `pkill -f zygisk-ptrace64`：后者按完整命令行匹配，会命中
        #    执行本命令的 `su -c '...zygisk-ptrace64...'` 自身（命令行里含该字样），
        #    导致 su 会话被 SIGTERM 自杀（rc=143），后续 cd/nohup 永不执行 → monitor 起不来。
        # ⚠️ 关于返回码：KernelSU 的 `su -c` 会 wait 全部子进程，只要 monitor
        #    是活的，这条命令就**永远不会主动返回**（实测带 `sleep 30 &` 也要等满 30s）。
        #    这是 su 的语义，无法靠 setsid / 子 shell / 重定向规避。因此这里
        #    **不依赖命令返回码**：给一个短超时快速放行，随后用「monitor 是否在跑」
        #    作为真正的成功判据（见下方复检）。
        cmd = (
            'pkill -x zygisk-ptrace64 2>/dev/null; sleep 1; '
            'rm -f %(tmp)s/init_monitor; '
            'cd %(dir)s && export TMP_PATH=%(tmp)s && '
            'nohup ./bin/zygisk-ptrace64 monitor '
            '> %(log)s 2>&1 < /dev/null &'
        ) % {
            'tmp': ZYGISK_NEO_TMP,
            'dir': ZYGISK_MODULE_DIR,
            'log': ZYGISK_MONITOR_LOG,
        }
        # 短超时：等 monitor 完成启动即可，不等命令「返回」（它不会返回）。
        runner.su(cmd, quiet=True, timeout=8)
        time.sleep(2)
        if zygisk_monitor_running(runner, ZY_NEO):
            return True, 'NeoZygisk monitor 已启动。'
        return False, ('monitor 未启动，请确认已安装 NeoZygisk 模块（%s）且具备 Root。'
                       % ZYGISK_MODULE)

    if kind == ZY_NEXT:
        # 定位可执行入口：优先 bin/zygiskd（软链），退回 bin/zygiskd64。
        if not runner.su('test -x %s || test -x %s'
                         % (ZYGISK_NEXT_BIN, ZYGISK_NEXT_BIN64),
                         quiet=True, timeout=15).ok:
            return False, ('未找到 %s 或 %s，请确认已安装 Zygisk Next 模块（%s）。'
                           % (ZYGISK_NEXT_BIN, ZYGISK_NEXT_BIN64, ZYGISK_MODULE))
        # 准备运行时目录 + 归档上一轮的 znctx / modules_info（照搬官方
        # post-fs-data.sh 的前置动作），再后台化启动 daemon。
        cmd = (
            'mkdir -p /data/adb/zygisksu; '
            'cd %(dir)s || exit 1; '
            '[ -f /data/adb/zygisksu/znctx ] && '
            'mv /data/adb/zygisksu/znctx /data/adb/zygisksu/znctx.old; '
            '[ -f /data/adb/zygisksu/modules_info ] && '
            'mv /data/adb/zygisksu/modules_info /data/adb/zygisksu/modules_info.old; '
            'nohup ./bin/zygiskd daemon '
            '> %(log)s 2>&1 < /dev/null &'
        ) % {'dir': ZYGISK_MODULE_DIR, 'log': ZYGISK_MONITOR_LOG}
        # 短超时：只等 daemon 完成拉起，不等命令「返回」（常驻不返回）。
        runner.su(cmd, quiet=True, timeout=10)
        time.sleep(3)
        if zygisk_monitor_running(runner, ZY_NEXT):
            return True, 'Zygisk Next daemon 已启动。'
        return False, ('daemon 未启动，请确认已安装 Zygisk Next 模块（%s）且具备 Root。'
                       % ZYGISK_MODULE)

    return False, ('未检测到 Zygisk 框架（既无 %s，也无 %s/bin/*/zygiskd）。'
                   % (ZYGISK_NEO_BIN, ZYGISK_MODULE_DIR))


def zygote64_pid(runner):
    """返回当前 64 位 zygote 的 PID（字符串），未运行返回空串。

    实机进程名就是 zygote64（另有 32 位 zygote、以及 zygote 派生的
    webview_zygote）。先用 pidof（精确匹配进程名，不会误伤
    webview_zygote），失败再退回 ps 过滤。
    """
    res = runner.su('pidof zygote64', quiet=True, timeout=15)
    pid = res.text.strip().split()
    if pid:
        return pid[0]
    res = runner.shell(
        "ps -A -o PID,NAME | awk '$2==\"zygote64\"{print $1}'",
        quiet=True, timeout=15)
    return res.text.strip().split()[0] if res.text.strip() else ''


def zygote_injected(runner, kind=None):
    """zygote 是否已被 Zygisk 注入（按框架分派，判据不可通用）。

    · NeoZygisk：检查 64 位 zygote 的 /proc/<pid>/maps 是否映射了
      libzygisk.so（NeoZygisk 会把它常驻映射在 zygote 里）。

    · Zygisk Next：**不能用 libzygisk/maps 判据** —— 实测 Zygisk Next 注入
      完成会把自身 loader 从 zygote 的 maps 中 unmap 掉（反检测），该 grep
      恒为 0。必须改用 `./bin/zygiskd status` 输出的 `zygote_states: N`
      （N≥1 表示已有 zygote 被成功注入）。

    返回 True/False；无法判定返回 None。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEXT:
        count = zygisk_zygote_count(runner, ZY_NEXT)
        if count < 0:
            return None
        return count > 0
    # NeoZygisk（及未知框架兜底）：查 zygote64 的 maps。
    pid = zygote64_pid(runner)
    if not pid:
        return None
    res = runner.su('grep -c libzygisk /proc/%s/maps' % pid, quiet=True, timeout=15)
    text = res.text.strip()
    return text.isdigit() and int(text) > 0


def restart_zygote(runner, service=None):
    """触发 zygote 重建，让 monitor 捕获新 zygote 并注入。

    NeoZygisk 的 monitor 以 PTRACE_SEIZE 接管**新出现**的 zygote，故需先
    杀掉现有 zygote，由 init 重新拉起后 monitor 才能注入。

    ⚠️ 不能用 kill/pkill 的返回码判断成败：pkill 在「没有匹配到进程」时
    返回 1，而 zygote 被 -9 杀掉后 init 会立刻重建、新旧 PID 交替，
    返回码无法反映真实结果。因此这里改用「zygote64 PID 是否变化」
    作为判据：杀掉前记录 PID，重建后 PID 必然不同。

    实机 64 位 zygote 名即 zygote64，32 位为 zygote；两者都要杀才能
    触发完整重建（只杀 64 位时 system_server 可能仍挂旧进程）。
    service 参数保留以兼容旧调用，忽略之。
    """
    before = zygote64_pid(runner)
    # ⚠️ 不能用 `pkill -f zygote64`：本命令命令行里含 "zygote64" 字样，
    #    pkill -f（按完整命令行匹配）会命中执行它的 `su -c '...zygote64...'`
    #    自身，把 su 会话一起杀掉（虽然侥幸仍能杀掉 zygote，但行为脆弱）。
    # ⚠️ 也不能用 `pkill -x zygote64`：实机 zygote64 的进程名(comm)是 "main"，
    #    精确名匹配不到，而 `-x main` 会误杀大量同名进程。
    # ✅ 正确做法：按 PID 精确 kill —— 先用 pidof 取到真实 PID 再 kill。
    pids = []
    p64 = zygote64_pid(runner)
    if p64:
        pids.append(p64)
    res32 = runner.su('pidof zygote', quiet=True, timeout=15)
    if res32.text.strip():
        pids.extend(res32.text.strip().split())
    if pids:
        runner.su('kill -9 ' + ' '.join(pids), quiet=True, timeout=30)

    # 轮询等待新 zygote 出现且 PID 与旧值不同（init 重建通常在数秒内）。
    for _ in range(30):
        time.sleep(1)
        now = zygote64_pid(runner)
        if now and now != before:
            return True
    return False



# ---------------------------------------------------------------
#  Xposed 框架检测
# ---------------------------------------------------------------
XP_NONE = 'none'
XP_VECTOR = 'vector'
XP_LSPOSED = 'lsposed'
XP_ORIGINAL = 'original'
XP_ORIGINAL_INSTALLED = 'original_installed'

XP_CLI = {
    XP_VECTOR: '/data/adb/vector/bin/cli',
    XP_LSPOSED: '/data/adb/lspd/bin/cli',
}

# Vector 的 CLI 可能出现在两个位置，探测时按序尝试。
VECTOR_MODULE_DIR = '/data/adb/modules/zygisk_vector'
XP_VECTOR_CLI_PATHS = (
    VECTOR_MODULE_DIR + '/cli',
    XP_CLI[XP_VECTOR],
)


def detect_xposed(runner):
    """返回 (type, cli_path)。type 为 XP_* 常量之一。

    · Vector：CLI 有两个位置 —— 模块目录内 `zygisk_vector/cli`，以及
      /data/adb/vector/bin/cli（安装脚本软链/副本）。两者都探测。
    · LSPosed：CLI 固定在 /data/adb/lspd/bin/cli（主类 org.lsposed.lspd.cli.Main）。
    """
    for path in (XP_VECTOR_CLI_PATHS):
        if runner.su('test -x ' + path, quiet=True, timeout=15).ok:
            return XP_VECTOR, path
    if runner.su('test -x ' + XP_CLI[XP_LSPOSED], quiet=True, timeout=15).ok:
        return XP_LSPOSED, XP_CLI[XP_LSPOSED]

    conf = '/data/data/de.robv.android.xposed.installer/conf/modules.list'
    if runner.su('test -f ' + conf, quiet=True, timeout=15).ok:
        return XP_ORIGINAL, ''

    res = runner.shell('pm list packages', quiet=True, timeout=20)
    if 'de.robv.android.xposed.installer' in res.text:
        return XP_ORIGINAL_INSTALLED, ''

    return XP_NONE, ''


def xposed_fd_attached(runner, cli):
    """查询 Vector / LSPosed 的 isFdAttached 状态：True/False/None。

    ⚠️ 该字段反映的是 CLI 这个短命进程**自身**的 fd 视角，实测在
    system_server 已注入时仍可能报 false，**不可作为激活判据**，
    仅作参考输出。真正的判据是 zygote 是否映射 libzygisk.so。
    cli 为空（未安装/无 CLI）时返回 None。
    """
    if not cli:
        return None
    res = runner.su('sh %s --json status' % cli, quiet=True, timeout=20)
    if not res.ok:
        return None
    m = re.search(r'"isFdAttached"\s*:\s*(true|false)', res.text, re.I)
    if m:
        return m.group(1).lower() == 'true'
    return None


# Vector / LSPosed 的框架日志目录（cli log cat 读取的就是这里的 modules_*.log）。
XP_LOG_DIR = '/data/adb/lspd/log'


def xposed_module_list(runner, cli):
    """列出 Vector / LSPosed 已注册模块：返回 [(包名, 状态), ...]。

    ★ CLI 的正确子命令是 `modules ls`，**不是 `modules list`**
      （实机验证：`modules list` 报 `Unmatched argument at index 1: 'list'` 且不返回数据）。
    cli 为空或命令失败时返回 []。
    """
    if not cli:
        return []
    res = runner.su('sh %s modules ls' % cli, quiet=True, timeout=25)
    rows = []
    for line in res.lines:
        line = line.strip()
        if not line or line.lower().startswith(('package', '---')):
            continue
        parts = line.split()
        token = parts[0]
        if not valid_xposed_id(token):
            continue
        # 实机列格式：PACKAGE  UID  STATUS（如 `com.x  10688  enabled`）。
        # 只取末列 STATUS 作显示，避免把中间 UID 一并带入。
        status = parts[-1] if len(parts) >= 2 else 'enabled'
        rows.append((token, status))
    return rows


def xposed_hook_evidence(runner, cli):
    """从框架日志中提取「模块 hook 实证」：返回 [(模块Tag, 次数), ...]（按次数降序）。

    原理：`cli log cat` dump 模块日志，形如
        [ 时间 PID:UID:TID I/VectorLegacyBridge ] [模块Tag] process=xxx
    其中 `[模块Tag]` 是模块在 hook 代码里主动打出的，出现即证明该模块已在目标进程执行。

    ⚠️ 重要局限（实机核实）：日志只记录**模块主动打 log** 的行为。
       静默工作的模块（如 HyperCeiler）不会留痕，故结果为空 ≠ 该模块未生效。
       判定静默模块请看 xposed_module_scope() 或直接功能实测。
    """
    if not cli:
        return []
    res = runner.su('sh %s log cat' % cli, quiet=True, timeout=25)
    counts = {}
    for line in res.lines:
        # 只取行尾那组 [Tag]（模块自己的标签），避开 I/VectorLegacyBridge 这类框架标签。
        tags = re.findall(r'\]\s*\[([A-Za-z0-9_.]+)\]', line)
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def xposed_module_scope(runner, cli, module_id):
    """查询某模块的注入作用域条目数（= 它会注入多少个 App）。失败返回 -1。

    作用域是「框架会不会向 App 注入该模块」的依据：条目>0 表示已配置注入范围；
    条目=0 表示该模块不会 hook 任何 App。这是静默模块（无 log）生效的间接证据。
    """
    if not cli or not valid_xposed_id(module_id):
        return -1
    res = runner.su('sh %s scope ls %s' % (cli, module_id), quiet=True, timeout=25)
    if not res.ok:
        return -1
    n = 0
    for line in res.lines:
        line = line.strip()
        if not line or line.upper().startswith(('APP_PACKAGE', '---')):
            continue
        n += 1
    return n


def xposed_vectord_running(runner):
    """Vector 守护进程 vectord 是否在运行（框架活着的最粗判据）。"""
    return runner.su('pgrep -f vectord', quiet=True, timeout=15).ok


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
