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

    # 提权重启场景：旧实例（非管理员）会在发起提权后自行退出，并已通过
    # ELEVATED_FLAG 告知本实例。此时若仍走单实例询问，会去强杀尚在退出的
    # 旧实例，导致新旧互相打断、"关了又开"。故带此标记时直接跳过询问，
    # 改为短暂等待旧实例释放互斥体，随后正常启动。
    elevated = '--elevated' in sys.argv
    try:
        import single_instance
        if elevated:
            # 等待旧实例让位。若超时仍未释放（旧实例卡住），仍允许启动，
            # 否则用户会陷入"提权后打不开"的死局。
            single_instance.wait_for_release(timeout=5.0)
        elif not single_instance.confirm_replace():
            return 0
        # 本实例成为当前实例：登记 pid 与提权状态，供后续启动判断。
        single_instance.write_registry()
    except Exception:
        # 单实例检测失败不应阻塞启动（例如非 Windows 环境）
        pass

    app = App()
    app.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
