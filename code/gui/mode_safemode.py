# -*- coding: utf-8 -*-
"""模式7：KernelSU 安全模式自救"""

import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui

# KernelSU 常见安全模式标记路径（按优先级尝试）。
# 第一项是官方/主流版本使用的路径；其余为部分旧版或分支的路径，
# 这些非官方路径能否被识别取决于具体 KernelSU 版本，写入成功也不代表一定生效。
OFFICIAL_MARKER = '/data/adb/ksu/safe_mode'
SAFE_MARKERS = [
    OFFICIAL_MARKER,
    '/data/adb/ksu_safe_mode',
    '/data/adb/modules/safe_mode',
]


class SafeModeFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'KernelSU 安全模式自救',
                  '写入安全模式标记后重启，KernelSU 会跳过模块加载，'
                  '用于抢救因模块导致的无法开机 / 无限重启。')

        # 状态卡
        outer, card = ui.card(inner, accent=ui.C_ACCENT, fill=ui.C_CARD, pad=(12, 10))
        outer.pack(fill='x', pady=(0, 4))
        self.lbl_marker = tk.Label(card, text='安全模式标记：未检查', bg=ui.C_CARD,
                                   fg=ui.C_TEXT, font=ui.FONT_BOLD, anchor='w')
        self.lbl_marker.pack(anchor='w', pady=(0, 2))
        self.lbl_hint = tk.Label(card, text='', bg=ui.C_CARD, fg=ui.C_MUTED,
                                 font=ui.FONT_SMALL, anchor='w',
                                 justify='left', wraplength=700)
        self.lbl_hint.pack(anchor='w')

        # 操作按钮
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x')
        ui.button(bar, '检查标记状态', self.check_marker)
        self.btn_enter = ttk.Button(bar, text='进入安全模式（写入标记）',
                                    command=self.enter_safe_mode)
        self.btn_enter.pack(side='left', padx=(0, 8), pady=4)
        self.btn_exit = ttk.Button(bar, text='退出安全模式（清除标记）',
                                   command=self.exit_safe_mode)
        self.btn_exit.pack(side='left', padx=(0, 8), pady=4)

        # 手动指南
        ui.section(inner, '自动写入失败时的手动指南', 'Recovery 下手动删除标记目录同样有效')
        man_outer, man = ui.card(inner, fill=ui.C_CARD, pad=(12, 10))
        man_outer.pack(fill='both', expand=True)
        guide = [
            '1. 让手机重启。',
            '2. 在开机出现品牌 Logo 时长按音量下键进入安全模式。',
            '3. 进入桌面后，此时 KernelSU 已禁用所有模块。',
            '4. 打开 KernelSU Manager，卸载导致异常的模块。',
            '5. 重启手机退出安全模式。',
            '6. 回到模式 1 确认 Root 已恢复，再逐步排查模块。',
            '',
            '备选：若无法进入安全模式，可在 Recovery 下手动删除',
            '     /data/adb/modules/<问题模块>/ 目录。',
        ]
        for line in guide:
            tk.Label(man, text=line, bg=ui.C_CARD, fg=ui.C_MUTED,
                     font=ui.FONT_SMALL, anchor='w',
                     justify='left').pack(anchor='w')

    def on_device_change(self, st):
        if st.adb:
            self.check_marker()

    # -----------------------------------------------------------
    def check_marker(self):
        if not self.app.device.adb:
            self.lbl_marker.configure(text='安全模式标记：ADB 未连接', fg=ui.C_MUTED)
            self.lbl_hint.configure(text='请连接手机并开启 USB 调试后重试。')
            return

        def job(_ctl):
            r = self.app.runner
            found = []
            for path in SAFE_MARKERS:
                if r.shell('test -f ' + path, quiet=True, timeout=15).ok:
                    found.append(path)
            return found

        def done(found):
            if not ui.widget_alive(self.lbl_marker):
                return
            if found is None:
                return
            if found:
                self.lbl_marker.configure(text='安全模式标记：已存在', fg=ui.C_WARN)
                self.lbl_hint.configure(
                    text='检测到标记文件：%s\n'
                         '下次重启将跳过全部模块。请先卸载问题模块，再点击「退出安全模式」。'
                         % '、'.join(found))
            else:
                self.lbl_marker.configure(text='安全模式标记：不存在', fg=ui.C_OK)
                self.lbl_hint.configure(
                    text='当前为正常启动状态。若手机无法开机，可点击「进入安全模式」写入标记。')

        self.app.run_task(job, on_done=done, busy_text='正在检查标记...',
                          done_text='检查完成')

    # -----------------------------------------------------------
    def enter_safe_mode(self):
        if not ui.require_adb(self.app):
            return
        if not messagebox.askyesno(
                '确认写入安全模式标记',
                '将向设备写入 KernelSU 安全模式标记。\n'
                '重启后所有模块都不会加载，便于卸载问题模块。\n\n是否继续？'):
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 写入安全模式标记 ----------')

            if not core.is_root(r):
                app.log_out('[错误] 未获取 Root，请先执行模式 2 或模式 3 提权。')
                return None

            for path in SAFE_MARKERS:
                folder = path.rsplit('/', 1)[0]
                app.log_out('尝试写入 %s ...' % path)
                r.su('mkdir -p ' + folder, quiet=True, timeout=20)
                r.su('touch ' + path, quiet=True, timeout=20)
                if r.shell('test -f ' + path, quiet=True, timeout=15).ok:
                    if path == OFFICIAL_MARKER:
                        app.log_out('[成功] 安全模式标记已写入：%s' % path)
                        app.log_out('请重启手机，重启后问题模块将不会加载。')
                        app.log_out('重启后到模式 5 卸载问题模块，再回来点击「退出安全模式」。')
                    else:
                        app.log_out('[警告] 仅写入了非官方路径：%s' % path)
                        app.log_out('该路径不一定被当前 KernelSU 版本识别，'
                                    '若重启后模块仍加载，请参考下方手动指南进入安全模式。')
                    return path
            app.log_out('[失败] 全部路径写入均失败，请参考下方手动指南。')
            return None

        def done(path):
            if not ui.widget_alive(self.lbl_marker):
                return
            self.check_marker()
            if path == OFFICIAL_MARKER:
                messagebox.showinfo(
                    '写入成功',
                    '安全模式标记已写入：\n%s\n\n'
                    '请重启手机，重启后到模式 5 卸载问题模块。' % path)
            elif path:
                messagebox.showwarning(
                    '已写入（非官方路径）',
                    '未能写入官方路径，仅写入了：\n%s\n\n'
                    '该路径不一定被当前 KernelSU 版本识别。若重启后模块仍'
                    '加载，请参考界面下方的手动指南进入安全模式。' % path)
            else:
                messagebox.showerror('写入失败', '自动写入失败，请参考界面下方的手动指南。')

        self.app.run_task(job, on_done=done, busy_text='正在写入标记...',
                          done_text='写入操作完成')

    def exit_safe_mode(self):
        if not ui.require_adb(self.app):
            return
        if not messagebox.askyesno(
                '确认退出安全模式',
                '将删除所有安全模式标记，恢复正常模块加载。\n\n'
                '请确认问题模块已卸载，否则可能导致再次无法开机。\n是否继续？'):
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 清除安全模式标记 ----------')

            if not core.is_root(r):
                app.log_out('[错误] 未获取 Root，无法清除标记。')
                return False

            removed = 0
            for path in SAFE_MARKERS:
                if r.shell('test -f ' + path, quiet=True, timeout=15).ok:
                    r.su('rm -f ' + path, quiet=True, timeout=20)
                    if not r.shell('test -f ' + path, quiet=True, timeout=15).ok:
                        app.log_out('[成功] 已删除 %s' % path)
                        removed += 1
                    else:
                        app.log_out('[错误] 删除失败：%s' % path)
            if removed == 0:
                app.log_out('[提示] 未发现需要清除的标记文件。')
            else:
                app.log_out('[完成] 已清除 %d 个标记，重启后恢复正常加载。' % removed)
            return removed > 0

        def done(_ok):
            if not ui.widget_alive(self.lbl_marker):
                return
            self.check_marker()

        self.app.run_task(job, on_done=done, busy_text='正在清除标记...',
                          done_text='清除完成')
