# -*- coding: utf-8 -*-
"""模式11：重启控制（软重启 / 完整重启 / Recovery / Fastboot / 关机）"""

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
        self._card(grid, '关机', '彻底关闭手机电源。\n'
                                 '关机后需手动按电源键开机。',
                   '关闭手机', self.poweroff, ui.C_MUTED, 1, 1)

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
    def on_device_change(self, st):
        pass

    def _confirm(self, title, text):
        return messagebox.askyesno(title, text)

    def soft(self):
        if not ui.require_adb(self.app):
            return
        if not self._confirm(
                '确认软重启',
                '即将软重启系统框架，手机将短暂黑屏 / 卡顿约 10~30 秒。\n\n'
                '不会清除数据，但请先保存正在编辑的内容。\n是否继续？'):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 软重启系统框架 ----------')
            if not core.is_root(app.runner):
                app.log_out('[错误] 软重启需要 Root 权限，请先执行模式 2 或模式 3 提权。')
                return False
            ok, cmd = core.soft_reboot(app.runner)
            if ok:
                app.log_out('[成功] 已下发软重启指令（%s）。' % cmd)
                app.log_out('手机将在数秒后开始重启框架，请稍候等待桌面恢复。')
            else:
                app.log_out('[失败] 软重启未成功，你的设备可能不支持。')
                app.log_out('       可改用「完整重启」，效果等同但耗时更长。')
            return ok

        self.app.run_task(job, busy_text='正在软重启系统框架...',
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

    def poweroff(self):
        self._simple(
            '确认关机',
            '即将关闭手机电源。\n\n'
            '关机后设备将完全断开，需手动按电源键开机。\n是否继续？',
            core.power_off, '正在关机...', '关机指令已下发',
            '手机正在关机，稍后需手动开机。')

    def _simple(self, title, ask, fn, busy, done_text, tail):
        """共通的重启操作流程。"""
        if not ui.require_adb(self.app):
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

        self.app.run_task(job, busy_text=busy, done_text=done_text)
