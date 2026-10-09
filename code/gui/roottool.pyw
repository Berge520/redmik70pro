# -*- coding: utf-8 -*-
"""
RootTool 图形界面启动器
双击本文件（.pyw 不显示控制台窗口）即可运行。
"""

import os
import sys

# 确保能导入同目录模块，并让 CWD 固定在本目录，
# 避免通过快捷方式/管理员方式启动时工作目录漂移导致找不到 adb。
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(os.path.dirname(HERE))


def main():
    try:
        from main import App
    except ImportError as exc:
        import tkinter.messagebox as mb
        mb.showerror('启动失败', '缺少依赖或文件：%s' % exc)
        return 1

    # 单实例：若已有本工具在运行，询问用户是否结束旧实例。
    # 用户选择保留旧实例时，本次启动直接中止。
    try:
        import single_instance
        if not single_instance.confirm_replace():
            return 0
    except Exception:
        # 单实例检测失败不应阻塞启动（例如非 Windows 环境）
        pass

    app = App()
    app.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
