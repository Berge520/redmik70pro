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
APP_VERSION = 'v0.1'
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
        """执行命令。

        args: 列表形式的命令，如 ['adb', 'devices']
        quiet: 不向 emit 输出原始行（仅记日志）
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
            self._log('命令已取消: %s' % ' '.join(argv))
        elif timed_out:
            msg = '[超时] 命令执行超过 %d 秒已终止。' % timeout
            lines.append(msg)
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
    """返回已安装模块的目录名列表。"""
    res = runner.su('ls /data/adb/modules/', quiet=True, timeout=20)
    if not res.ok:
        return []
    out = []
    for line in res.lines:
        name = line.strip()
        if name:
            out.append(name)
    return out


def read_module_name(runner, folder):
    """读取模块的显示名（module.prop 中的 name）。"""
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
#  Zygisk / Vector 激活（临时 Root late-load 恢复流程）
# ---------------------------------------------------------------
ZYGISK_MODULE = 'zygisksu'
ZYGISK_POST_FS_DATA = '/data/adb/modules/%s/post-fs-data.sh' % ZYGISK_MODULE
ZYGISK_DAEMON_STATUS = '/data/adb/modules/%s/bin/zygiskd' % ZYGISK_MODULE
VECTOR_CLI = '/data/adb/modules/zygisk_vector/cli'


def zygisk_daemon_running(runner):
    """Zygisk 守护进程（zn-daemon）是否在运行。

    注意：真实进程名是 zn-daemon，不是 zygiskd，早期误用 zygiskd
    匹配会导致「服务未运行」的错误判断。
    """
    res = runner.shell('ps -A -o NAME', quiet=True, timeout=15)
    for line in res.lines:
        if line.strip() == 'zn-daemon':
            return True
    return False


def zygisk_status(runner):
    """读取 zygiskd status，返回原始文本（失败返回空串）。"""
    res = runner.su('%s status' % ZYGISK_DAEMON_STATUS, quiet=True, timeout=20)
    return res.text if res.ok else ''


def zygisk_zygote_count(runner):
    """从 status 文本解析已接管的 zygote 数量，无法解析返回 -1。"""
    text = zygisk_status(runner)
    m = re.search(r'zygote_states\s*:\s*(\d+)', text)
    if m:
        return int(m.group(1))
    return -1


def vector_fd_attached(runner):
    """Vector 的 isFdAttached 状态：True/False/None（无法判断）。"""
    res = runner.su('sh %s --json status' % VECTOR_CLI, quiet=True, timeout=20)
    if not res.ok:
        return None
    m = re.search(r'"isFdAttached"\s*:\s*(true|false)', res.text, re.I)
    if m:
        return m.group(1).lower() == 'true'
    return None


def start_zygisk_daemon(runner):
    """重越狱后手动补触发 post-fs-data，拉起 zn-daemon。

    late-load 模式下 ksud 是后注入的，不会自动重放 post-fs-data 事件，
    而 Zygisk Next 依赖该事件启动 zn-daemon，故必须手动补执行。
    返回 (ok, 说明)。
    """
    if not runner.su('test -f ' + ZYGISK_POST_FS_DATA, quiet=True, timeout=15).ok:
        return False, '未找到 %s，请确认已安装 Zygisk Next 模块（%s）。' % (
            ZYGISK_POST_FS_DATA, ZYGISK_MODULE)
    res = runner.su('sh ' + ZYGISK_POST_FS_DATA, timeout=60)
    return res.ok, res.text


def restart_zygote(runner, service):
    """通过 setprop ctl.restart 重启指定的 zygote init 服务。

    Android 已移除 ctl 可执行文件，故用 setprop 触发 init 重启服务。
    service：'zygote'（64 位）或 'zygote_mi_secondary'（小米 32 位转译层）。
    """
    return runner.su('setprop ctl.restart %s' % service, quiet=True, timeout=30).ok


# 小米机型两个 zygote 的 init 服务名（详见排查记录）
ZYGOTE_SVC_64 = 'zygote'
ZYGOTE_SVC_32 = 'zygote_mi_secondary'



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


def detect_xposed(runner):
    """返回 (type, cli_path)。type 为 XP_* 常量之一。"""
    if runner.su('test -x ' + XP_CLI[XP_VECTOR], quiet=True, timeout=15).ok:
        return XP_VECTOR, XP_CLI[XP_VECTOR]
    if runner.su('test -x ' + XP_CLI[XP_LSPOSED], quiet=True, timeout=15).ok:
        return XP_LSPOSED, XP_CLI[XP_LSPOSED]

    conf = '/data/data/de.robv.android.xposed.installer/conf/modules.list'
    if runner.su('test -f ' + conf, quiet=True, timeout=15).ok:
        return XP_ORIGINAL, ''

    res = runner.shell('pm list packages', quiet=True, timeout=20)
    if 'de.robv.android.xposed.installer' in res.text:
        return XP_ORIGINAL_INSTALLED, ''

    return XP_NONE, ''


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
