# -*- coding: utf-8 -*-
"""单实例检测：启动新实例时提示是否结束旧实例。

实现方式（仅 Windows，纯标准库）：
- 用命名互斥体（CreateMutexW）判断是否已有实例在运行。相比遍历窗口标题，
  互斥体不受窗口标题变化、字体缩放、标题被截断等因素影响，判定更可靠；
- 若互斥体已存在，说明有旧实例。此时按窗口标题定位旧窗口，询问用户是否结束；
- 结束后等待旧窗口消失，避免新旧窗口短暂并存。

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

# 全局命名互斥体名称（Global\ 前缀保证跨会话可见）。
MUTEX_NAME = 'Global\\RedmiK70Pro_RootTool_SingleInstance'

WM_CLOSE = 0x0010
ERROR_ALREADY_EXISTS = 183

# 持有互斥体句柄，进程存活期间不能释放（否则判定失效）。
_mutex_handle = None


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
        # 创建失败时保守放行，避免因权限等问题误挡用户。
        return True
    _mutex_handle = handle
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS


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

    found = []

    def _enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = create_unicode_buffer(length + 1)
        GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == title:
            found.append(hwnd)
        return True

    WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(_enum_proc), 0)
    return found


def close_windows(handles, wait=3.0):
    """向窗口发送关闭消息，并等待其消失。

    返回实际关闭的窗口数。超时未消失的窗口会被强制结束宿主进程。
    """
    user32 = _user32()
    if user32 is None or not handles:
        return 0

    for hwnd in handles:
        try:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass

    deadline = time.time() + wait
    alive = list(handles)
    while time.time() < deadline and alive:
        time.sleep(0.2)
        alive = [h for h in alive if user32.IsWindow(h)]

    # 仍未退出的，直接结束其进程（等价于任务管理器结束任务）
    for hwnd in alive:
        try:
            pid = _window_pid(user32, hwnd)
            if pid:
                _kill_pid(pid)
        except Exception:
            pass

    # 再等一小会确认
    time.sleep(0.5)
    return sum(1 for h in handles if not user32.IsWindow(h))


def _window_pid(user32, hwnd):
    from ctypes import wintypes, byref
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


def _kill_pid(pid):
    import subprocess
    CREATE_NO_WINDOW = 0x08000000
    subprocess.run(['taskkill', '/PID', str(pid), '/F'],
                   capture_output=True, creationflags=CREATE_NO_WINDOW)


def confirm_replace():
    """检测已有实例并询问用户是否结束。

    返回值：
      True  —— 可以继续启动（无旧实例，或旧实例已被结束）
      False —— 用户选择保留旧实例，本次启动应当中止
    """
    # 先抢占互斥体：这是判定"是否已有实例"的权威依据。
    if acquire_mutex():
        return True

    # 已有实例在运行。按标题定位旧窗口，供用户选择是否结束。
    handles = find_windows(WINDOW_TITLE)

    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    answer = messagebox.askyesno(
        '程序已在运行',
        '检测到「%s」已有一个实例正在运行。\n\n'
        '是否结束旧实例并启动新的？\n\n'
        '· 是 —— 关闭旧窗口，启动新实例\n'
        '· 否 —— 保留旧窗口，本次不启动' % WINDOW_TITLE)
    root.destroy()

    if not answer:
        return False

    if handles:
        close_windows(handles)
        # 旧实例关闭后会释放互斥体，此处再次尝试抢占。
        time.sleep(0.5)
        acquire_mutex()
    return True
