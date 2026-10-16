# -*- coding: utf-8 -*-
"""模式11：重启控制（软重启 / 完整重启 / Recovery / Fastboot / EDL / 关机）"""

import tkinter as tk
from tkinter import messagebox

import core
import main as ui


class RebootFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, '重启控制',
                  '软重启只重启 Android 系统框架与 Root 服务，不切断电源、不清缓存，'
                  '通常 10~30 秒恢复，可用于让刚禁用 / 启用的模块生效。')

        # 软重启主卡片（推荐操作，突出显示）
        soft, sb = ui.card(inner, accent=ui.C_ACCENT, fill=ui.C_ACCENT_LIGHT,
                           pad=(12, 12))
        soft.pack(fill='x', pady=(0, 12))
        tk.Label(sb, text='软重启系统框架（推荐）', bg=ui.C_ACCENT_LIGHT,
                 fg=ui.C_ACCENT, font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w')
        tk.Label(sb,
                 text='重启 zygote 与系统服务，让模块 / Root 服务重新加载。\n'
                      '不切断电源、不清除数据，比完整重启快得多。\n'
                      '执行期间手机可能短暂黑屏或卡顿，属正常现象。',
                 bg=ui.C_ACCENT_LIGHT, fg=ui.C_TEXT, font=ui.FONT_SMALL,
                 justify='left').pack(anchor='w', pady=(2, 0))
        ui.button(sb, '立即软重启', self.soft, accent=True).pack(anchor='w',
                                                                pady=(8, 0))

        # 其它重启方式
        ui.section(inner, '其它重启方式')

        grid = tk.Frame(inner, bg=ui.C_PANEL)
        grid.pack(fill='x')

        self._card(grid, '完整重启', '等同手动关机再开机，约 1~2 分钟。\n'
                                    '模块 / 系统改动均会生效。',
                   '执行完整重启', self.full, ui.C_ERR, 0, 0)
        self._card(grid, '重启到 Recovery', '进入 Recovery 模式，\n可用于刷机、双清等操作。',
                   '进入 Recovery', self.recovery, ui.C_WARN, 0, 1)
        self._card(grid, '重启到 Fastboot', '进入 bootloader 模式，\n'
                                            '可搭配模式 3 做分区提权。',
                   '进入 Fastboot', self.bootloader, ui.C_ACCENT, 1, 0)
        self._card(grid, '重启到 EDL', '进入 9008 深度刷机模式（小米常见）。\n'
                                       '进入后本工具将无法识别设备。',
                   '进入 EDL', self.edl, ui.C_ACCENT, 1, 1)
        self._card(grid, '关机', '彻底关闭手机电源。\n'
                                 '关机后需手动按电源键开机。',
                   '关闭手机', self.poweroff, ui.C_MUTED, 2, 0)

    def _card(self, parent, title, desc, btn, cmd, color, row, col):
        """构建一个重启选项卡片。"""
        card, body = ui.card(parent, accent=color)
        card.grid(row=row, column=col, sticky='nsew',
                  padx=(0, 8) if col == 0 else (8, 0), pady=(0, 8))
        parent.grid_columnconfigure(col, weight=1)
        tk.Label(body, text=title, bg=ui.C_PANEL, fg=color,
                 font=ui.FONT_BOLD).pack(anchor='w')
        tk.Label(body, text=desc, bg=ui.C_PANEL, fg=ui.C_MUTED,
                 font=ui.FONT_SMALL, justify='left').pack(anchor='w', pady=(2, 6))
        ui.button(body, btn, cmd)

    # -----------------------------------------------------------
    def _ensure_adb(self):
        """确认 ADB 可用：直接跑一次实时检测，避免用到陈旧的 device.adb。

        require_adb 读的是 self.app.device，而该值是上次刷新时的快照；
        用户刚插上手机还未刷新时会被误判为"未连接"。这里改为主动探测一次。

        处于 recovery / sideload 状态（第三方 Recovery）时 adb 仍可用，
        允许继续操作；unauthorized / offline 才是真正不可用的状态。
        """
        st = core.detect_devices(self.app.runner)
        self.app.device = st
        if st.adb:
            return True
        if st.adb_recovery:
            rec = '、'.join('%s(%s)' % (sn, s) for sn, s in st.recovery_targets())
            self.app.log_out('[提示] 设备处于 Recovery 模式：%s' % rec)
            if not core.is_root(self.app.runner):
                messagebox.showwarning(
                    'Recovery 下无法执行',
                    '设备当前处于 Recovery 模式：%s\n\n'
                    '官方 Recovery 不提供可用的 adb shell，无法下发重启指令，\n'
                    '请在手机上手动操作 Recovery 菜单。\n\n'
                    '（若是 TWRP 等第三方 Recovery，应可直接操作；\n'
                    '此提示出现说明当前 Recovery 未提供 shell 权限。）' % rec)
                return False
            return True
        if st.adb_devices:
            states = '、'.join('%s(%s)' % (sn, s) for sn, s in st.adb_devices)
            messagebox.showwarning(
                '设备未就绪',
                '已检测到设备但尚未就绪：%s\n\n'
                '请在手机上点击「允许 USB 调试」后重试。' % states)
            return False
        messagebox.showwarning('未连接设备',
                               '未检测到 ADB 设备。\n请连接手机、开启 USB 调试并授权后重试。')
        return False

    def _refresh_after(self):
        """重启指令下发后刷新设备连接，让界面指示灯与真实状态同步。

        重启会让设备短暂离线 / 切换模式，稍作延迟再刷新，结果更准确。
        App 本身即 tk.Tk，可直接用 after 调度。
        """
        self.app.after(2500, self.app.refresh_devices)

    def _confirm(self, title, text):
        return ui.confirm(title, text)

    def soft(self):
        if not self._ensure_adb():
            return
        # 软重启依赖 Root：先在主线程弹窗提示，而不是丢到后台任务里默默失败。
        if not core.is_root(self.app.runner):
            messagebox.showwarning(
                '需要 Root 权限',
                '软重启系统框架需要 Root 权限。\n\n'
                '请先执行「模式 2 临时 Root」或「模式 3 分区提权」后再试。\n'
                '（若只是想重启手机，可改用「完整重启」。）')
            self.app.log_out('[提示] 软重启已取消：当前未获取 Root 权限。')
            return
        if not self._confirm(
                '确认软重启',
                '即将软重启系统框架，手机将短暂黑屏 / 卡顿约 10~30 秒。\n\n'
                '不会清除数据，但请先保存正在编辑的内容。\n是否继续？'):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 软重启系统框架 ----------')
            ok, cmd, tried = core.soft_reboot(app.runner)
            if ok:
                app.log_out('[成功] 已下发软重启指令（%s）。' % cmd)
                app.log_out('手机将在数秒后开始重启框架，请稍候等待桌面恢复。')
            else:
                app.log_out('[失败] 软重启未成功，你的设备可能不支持。')
                for name, hit in tried:
                    app.log_out('       已尝试：%s（%s）' % (name, '成功' if hit else '失败'))
                app.log_out('       可改用「完整重启」，效果等同但耗时更长。')
            return ok

        def done(ok):
            self._refresh_after()
            if not ok:
                messagebox.showwarning(
                    '软重启未成功',
                    '设备可能不支持软重启。\n\n'
                    '已尝试多种方式均失败（详见实时日志），\n'
                    '建议改用「完整重启」。')

        self.app.run_task(job, on_done=done, busy_text='正在软重启系统框架...',
                          done_text='软重启指令已下发')

    def full(self):
        self._simple(
            '完整重启',
            '即将完整重启手机，约 1~2 分钟。\n\n是否继续？',
            core.full_reboot, '正在完整重启...', '完整重启指令已下发',
            '手机将断开 ADB 连接并重新启动。')

    def recovery(self):
        self._simple(
            '重启到 Recovery',
            '即将重启进入 Recovery 模式。\n\n'
            '部分机型 Recovery 下无法使用 ADB，需手动操作。\n是否继续？',
            core.reboot_recovery, '正在重启到 Recovery...', 'Recovery 指令已下发',
            '手机将重启进入 Recovery 模式。')

    def bootloader(self):
        self._simple(
            '重启到 Fastboot',
            '即将重启进入 Fastboot（bootloader）模式。\n\n'
            '进入后可用模式 3 做分区提权。\n是否继续？',
            core.reboot_bootloader, '正在重启到 Fastboot...', 'Fastboot 指令已下发',
            '手机将重启进入 Fastboot，可用「fastboot devices」确认。')

    def edl(self):
        self._simple(
            '重启到 EDL',
            '即将重启进入 EDL（9008 深度刷机模式）。\n\n'
            '进入后本工具将无法识别设备，需用专用工具与 9008 驱动操作。\n'
            '部分机型 / 固件会忽略此指令。\n是否继续？',
            core.reboot_edl, '正在重启到 EDL...', 'EDL 指令已下发',
            '手机将进入 9008 模式，此时本工具不再识别设备，如需刷写请使用专用工具。')

    def poweroff(self):
        self._simple(
            '确认关机',
            '即将关闭手机电源。\n\n'
            '关机后设备将完全断开，需手动按电源键开机。\n是否继续？',
            core.power_off, '正在关机...', '关机指令已下发',
            '手机正在关机，稍后需手动开机。')

    def _simple(self, title, ask, fn, busy, done_text, tail):
        """共通的重启操作流程。"""
        if not self._ensure_adb():
            return
        if not self._confirm(title, ask):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- %s ----------' % title)
            if fn(app.runner):
                app.log_out('[成功] %s' % done_text)
                app.log_out(tail)
                return True
            app.log_out('[失败] 指令下发失败，请确认设备已连接且处于 ADB 模式。')
            return False

        def done(_ok):
            # 重启 / 关机后连接状态必然变化，刷新一次让指示灯同步。
            self._refresh_after()

        self.app.run_task(job, on_done=done, busy_text=busy, done_text=done_text)
