# -*- coding: utf-8 -*-
"""单实例检测：启动新实例时提示是否结束旧实例。

设计要点（仅针对 Windows，纯标准库）：

- **命名互斥体做权威判定**。互斥体是内核对象，进程退出（含被强杀）时由
  系统自动释放，不像锁文件会留残留，判定最可靠。

- **不使用 Global\\ 前缀**。Global\\ 命名对象需要 SeCreateGlobalPrivilege，
  普通权限进程创建会失败，于是会出现"普通权限实例退化为会话内互斥体、
  管理员实例持有 Global 互斥体"两者名字不同、互相看不见的错乱——这正是
  "提权后又开一个、且关不掉提权实例"的根因。这里统一使用会话内名称，
  并在注释中记录该取舍。

- **跨权限关闭**。低权限进程无法向高权限进程窗口 PostMessage(WM_CLOSE)
  （UIPI 拦截），也无法 taskkill 高权限进程（拒绝访问）。因此：
    * 优先按窗口发 WM_CLOSE（同权限时最优雅）；
    * 失败则按 pid taskkill /F；
    * 仍失败（对方权限更高）时不再死等，返回未关闭的实例信息，
      由调用方给出明确提示（引导用户手动关闭或用管理员身份重启）。

非 Windows 平台直接放行，不做限制。
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402

_IS_WIN = (os.name == 'nt')

# 窗口标题统一取自 core，避免与主程序版本号漂移。
WINDOW_TITLE = core.APP_TITLE

# 会话内命名互斥体。
#
# 为什么不带 Global\ 前缀：Global\ 需要 SeCreateGlobalPrivilege，普通权限
# 进程创建会失败并退化到会话内名称，导致普通实例与管理员实例各自持有
# "同名但不同对象"的互斥体，互相检测不到。统一用会话内名称后，无论是否
# 提权，同一登录会话内的所有实例都争抢同一个内核对象，判定才可靠。
MUTEX_NAME = 'RedmiK70Pro_RootTool_SingleInstance'
ERROR_ALREADY_EXISTS = 183

# 持有互斥体句柄，进程存活期间不能释放（否则判定失效）。
_mutex_handle = None

# 实例信息登记文件：记录当前实例 pid 与是否提权，供新实例判断能否关闭。
_REGISTRY = os.path.join(
    os.environ.get('TEMP') or os.environ.get('TMP') or os.path.expanduser('~'),
    'RedmiK70Pro_RootTool_instance.json')


def acquire_mutex():
    """尝试创建/打开命名互斥体。

    返回 True 表示没有其他实例（互斥体为本进程首次创建）；
    返回 False 表示已有实例正在运行。
    非 Windows 平台一律返回 True。
    """
    global _mutex_handle
    if not _IS_WIN:
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                      wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        # 极端情况下创建失败，保守放行，避免误挡用户启动。
        return True
    _mutex_handle = handle
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def write_registry():
    """登记当前实例的 pid 与提权状态，供后续启动的实例判断如何关闭。"""
    try:
        import json
        with open(_REGISTRY, 'w', encoding='utf-8') as f:
            json.dump({'pid': os.getpid(), 'admin': bool(core.is_admin())}, f)
    except Exception:
        pass


def read_registry():
    """读取上一实例登记的信息；不存在或损坏时返回 None。"""
    try:
        import json
        with open(_REGISTRY, 'r', encoding='utf-8') as f:
            data = json.load(f)
        pid = int(data.get('pid') or 0)
        if pid <= 0:
            return None
        return {'pid': pid, 'admin': bool(data.get('admin'))}
    except Exception:
        return None


def clear_registry():
    """清除实例登记文件（正常退出时调用）。"""
    try:
        if os.path.exists(_REGISTRY):
            os.remove(_REGISTRY)
    except Exception:
        pass


def pid_alive(pid):
    """判断给定 pid 是否仍存活。"""
    if not _IS_WIN:
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        # WAIT_TIMEOUT(258) 表示仍在运行；WAIT_OBJECT_0(0) 表示已退出。
        return kernel32.WaitForSingleObject(handle, 0) == 258
    finally:
        kernel32.CloseHandle(handle)


def _user32():
    if not _IS_WIN:
        return None
    import ctypes
    return ctypes.windll.user32


def find_windows(title):
    """返回所有标题等于 title 的可见顶层窗口句柄列表。"""
    user32 = _user32()
    if user32 is None:
        return []

    from ctypes import wintypes, create_unicode_buffer, WINFUNCTYPE

    GetWindowTextW = user32.GetWindowTextW
    GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
    GetWindowTextW.restype = wintypes.INT

    IsWindowVisible = user32.IsWindowVisible
    IsWindowVisible.argtypes = [wintypes.HWND]
    IsWindowVisible.restype = wintypes.BOOL

    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextLengthW.argtypes = [wintypes.HWND]
    GetWindowTextLengthW.restype = wintypes.INT

    found = []

    def _enum_proc(hwnd, _lparam):
        if not IsWindowVisible(hwnd):
            return True
        length = GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == title:
            found.append(hwnd)
        return True

    WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    EnumWindows = user32.EnumWindows
    EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    EnumWindows.restype = wintypes.BOOL
    EnumWindows(WNDENUMPROC(_enum_proc), 0)
    return found


def close_windows(handles, wait=3.0):
    """向窗口发送关闭消息，并等待其消失。

    返回 (已关闭数, 仍在存活的 pid 列表)。
    对高权限进程的窗口，PostMessage 会被 UIPI 拒绝、taskkill 会拒绝访问，
    此时不无限等待，直接把未关闭的 pid 返回给调用方处理。
    """
    user32 = _user32()
    if user32 is None or not handles:
        return 0, []

    from ctypes import wintypes

    # 64 位下句柄是 8 字节，未声明 argtypes 会被截断成 32 位，导致消息发错窗口。
    PostMessageW = user32.PostMessageW
    PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM]
    PostMessageW.restype = wintypes.BOOL

    IsWindow = user32.IsWindow
    IsWindow.argtypes = [wintypes.HWND]
    IsWindow.restype = wintypes.BOOL

    # 先记录每个窗口的宿主 pid，供后续按 pid 关闭。
    hwnd_pids = [(h, _window_pid(user32, h)) for h in handles]

    for hwnd, _pid in hwnd_pids:
        try:
            PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:
            pass

    deadline = time.time() + wait
    alive = list(hwnd_pids)
    while time.time() < deadline and alive:
        time.sleep(0.2)
        alive = [(h, p) for (h, p) in alive if IsWindow(h)]

    # 仍未退出的，按 pid 结束其进程（同权限时可成功；高权限时会被拒绝）。
    remaining_pids = []
    for hwnd, pid in alive:
        if not pid:
            continue
        _kill_pid(pid)
        if pid_alive(pid):
            remaining_pids.append(pid)

    time.sleep(0.3)
    closed = sum(1 for h, _p in hwnd_pids if not IsWindow(h))
    remaining_pids = [p for p in remaining_pids if pid_alive(p)]
    return closed, remaining_pids


def _window_pid(user32, hwnd):
    import ctypes
    from ctypes import wintypes, byref
    GetWindowThreadProcessId = user32.GetWindowThreadProcessId
    GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    GetWindowThreadProcessId.restype = wintypes.DWORD
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


def _kill_pid(pid):
    import subprocess
    CREATE_NO_WINDOW = 0x08000000
    try:
        subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                       capture_output=True, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def wait_for_release(timeout=5.0):
    """提权重启专用：等待旧实例释放互斥体，再抢占互斥体。

    返回 True 表示已成功取得互斥体（旧实例已退出或本来就是空的）；
    返回 False 表示超时仍未取得（旧实例可能卡住，但不应阻断新实例启动）。

    与 confirm_replace 的区别：本函数【不询问、不杀进程】。提权场景下
    旧实例会主动退出，若此处再去 PostMessage / taskkill，反而会打断正在
    收尾的旧实例，出现"关了又开""越开越多"的现象。
    """
    if not _IS_WIN:
        return True
    deadline = time.time() + max(0.0, timeout)
    while True:
        # acquire_mutex：首次创建即拿到互斥体；若已存在则说明旧实例尚未
        # 退出，返回 False。循环重试直到旧实例释放或超时。
        if acquire_mutex():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def confirm_replace():
    """检测已有实例并询问用户是否结束。

    返回值：
      True  —— 可以继续启动（无旧实例，或旧实例已被结束）
      False —— 用户选择保留旧实例，或旧实例无法关闭，本次启动应当中止
    """
    # 先抢占互斥体：这是判定"是否已有实例"的权威依据。
    if acquire_mutex():
        return True

    # 已有实例在运行。结合 pid 登记与窗口句柄，判断旧实例情况。
    reg = read_registry()
    old_pid = reg['pid'] if reg else 0
    old_admin = bool(reg.get('admin')) if reg else False
    # 登记文件可能过期（旧实例异常退出未清除），用 pid 存活二次确认。
    if old_pid and not pid_alive(old_pid) and not find_windows(WINDOW_TITLE):
        return True

    handles = find_windows(WINDOW_TITLE)

    import tkinter as tk
    from tkinter import messagebox

    # 若旧实例是管理员权限、而当前是普通权限，则无法关闭它（UIPI + 拒绝访问），
    # 直接给出明确说明，避免"点了是却关不掉"的困惑。
    i_am_admin = core.is_admin()
    cannot_close = old_admin and not i_am_admin

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    if cannot_close:
        answer = False
        messagebox.showwarning(
            '程序已在运行（管理员权限）',
            '检测到「%s」已有一个【管理员权限】实例正在运行。\n\n'
            '当前程序为普通权限，Windows 不允许普通权限程序关闭管理员程序，'
            '因此无法自动结束旧实例。\n\n'
            '请任选一种方式：\n'
            '  · 手动切换到旧窗口，点击右上角关闭；\n'
            '  · 或右键本程序/启动脚本，选择「以管理员身份运行」，'
            '这样新实例就能正常接管。' % WINDOW_TITLE)
    else:
        answer = messagebox.askyesno(
            '程序已在运行',
            '检测到「%s」已有一个实例正在运行。\n\n'
            '是否结束旧实例并启动新的？\n\n'
            '· 是 —— 关闭旧窗口，启动新实例\n'
            '· 否 —— 保留旧窗口，本次不启动' % WINDOW_TITLE)
    root.destroy()

    if not answer:
        return False

    # 关闭旧实例：先按窗口发 WM_CLOSE，再按 pid 关；高权限时可能失败。
    closed, remaining = close_windows(handles)
    if not handles and old_pid:
        _kill_pid(old_pid)
        time.sleep(0.5)
        remaining = [old_pid] if pid_alive(old_pid) else []

    if remaining:
        # 还有实例没关掉：不能再启动，否则就会"越开越多"。
        root2 = tk.Tk()
        root2.withdraw()
        root2.attributes('-topmost', True)
        messagebox.showerror(
            '无法结束旧实例',
            '旧实例（pid: %s）未能关闭，可能因为它以管理员权限运行。\n\n'
            '为避免出现多个实例，本次启动已取消。\n'
            '请手动关闭旧窗口，或以管理员身份重新运行本程序。'
            % ', '.join(str(p) for p in remaining))
        root2.destroy()
        return False

    # 旧实例关闭后会释放互斥体，此处再次尝试抢占。
    time.sleep(0.3)
    acquire_mutex()
    return True
