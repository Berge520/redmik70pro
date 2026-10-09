# -*- coding: utf-8 -*-
"""模式4：SELinux 模式切换（ADB / Fastboot）"""

import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui


class SelinuxFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'SELinux 模式切换',
                  'Permissive（宽松）会放宽强制访问控制，便于调试但存在安全风险；\n'
                  'Enforcing（强制）为正常安全状态。Fastboot 下发的参数仅本次启动有效。')

        # 当前状态卡
        self.state_box, inner_card = ui.stat(
            inner, '当前 SELinux 状态', value='—', color=ui.C_TEXT)
        self.state_box.pack(fill='x', pady=(0, 6))
        self.lbl_how = tk.Label(inner_card, text='', bg=ui.C_CARD, fg=ui.C_MUTED,
                                font=ui.FONT_SMALL)
        self.lbl_how.pack(anchor='w', padx=12, pady=(0, 8))
        # 数值标签直接用 stat 返回的 Label，字体放大
        self.lbl_state = self.state_box.winfo_children()[1]
        self.lbl_state.configure(font=('Microsoft YaHei UI', 20, 'bold'))

        ui.button(inner, '读取当前状态', self.refresh_state)

        # 操作区
        ui.section(inner, '切换操作', 'Fastboot 下发的参数仅本次启动有效')
        op = tk.Frame(inner, bg=ui.C_PANEL)
        op.pack(fill='x')

        left, lb = ui.card(op, accent=ui.C_WARN)
        left.pack(side='left', fill='both', expand=True, padx=(0, 6))
        tk.Label(lb, text='切换到宽松模式 (Permissive)', bg=ui.C_PANEL,
                 fg=ui.C_WARN, font=ui.FONT_BOLD).pack(anchor='w')
        tk.Label(lb, text='setenforce 0：放宽访问控制，便于调试与排查。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED,
                 font=ui.FONT_SMALL, wraplength=300,
                 justify='left').pack(anchor='w', pady=(2, 6))
        ui.button(lb, '切换为 Permissive', lambda: self.set_mode(False))

        right, rb = ui.card(op, accent=ui.C_OK)
        right.pack(side='left', fill='both', expand=True, padx=(6, 0))
        tk.Label(rb, text='切换到强制模式 (Enforcing)', bg=ui.C_PANEL,
                 fg=ui.C_OK, font=ui.FONT_BOLD).pack(anchor='w')
        tk.Label(rb, text='setenforce 1：恢复正常安全策略（推荐）。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED,
                 font=ui.FONT_SMALL, wraplength=300,
                 justify='left').pack(anchor='w', pady=(2, 6))
        ui.button(rb, '切换为 Enforcing', lambda: self.set_mode(True))

    def on_device_change(self, st):
        if st.adb:
            cached = self.app.mode_cache.get('selinux')
            if cached:
                self._apply_state(cached)
                return
            self.refresh_state()
        else:
            self.lbl_state.configure(text='—', fg=ui.C_MUTED)
            self.lbl_how.configure(text='ADB 未连接，无法直接读取状态')

    def _apply_state(self, val):
        """根据 getenforce 返回值渲染状态卡（主线程调用）。"""
        # 任务结束时可能已切换模式，控件被销毁则直接放弃本次渲染。
        if not ui.widget_alive(self.lbl_state):
            return
        if not val:
            self.lbl_state.configure(text='读取失败', fg=ui.C_MUTED)
            self.lbl_how.configure(text='请确认设备已授权调试')
            return
        if val.lower() == 'permissive':
            self.lbl_state.configure(text='Permissive（宽松）', fg=ui.C_WARN)
            self.lbl_how.configure(text='当前已放宽访问控制，建议调试完成后切回 Enforcing')
        elif val.lower() == 'enforcing':
            self.lbl_state.configure(text='Enforcing（强制）', fg=ui.C_OK)
            self.lbl_how.configure(text='当前为正常的安全策略状态')
        else:
            self.lbl_state.configure(text=val, fg=ui.C_TEXT)
            self.lbl_how.configure(text='')

    # -----------------------------------------------------------
    def refresh_state(self):
        if not self.app.device.adb:
            self.lbl_state.configure(text='—', fg=ui.C_MUTED)
            self.lbl_how.configure(text='ADB 未连接，无法读取 SELinux 状态')
            return

        def job(_ctl):
            return self.app.runner.shell('getenforce', quiet=True, timeout=15).first()

        def done(val):
            if val:
                self.app.mode_cache['selinux'] = val
            self._apply_state(val)
            self.app.log_out('[SELinux] 当前状态：%s' % (val or '读取失败'))

        self.app.run_task(job, on_done=done, busy_text='正在读取 SELinux 状态...',
                          done_text='读取完成')

    # -----------------------------------------------------------
    def set_mode(self, enforcing):
        app = self.app
        st = app.device

        if not st.any:
            messagebox.showwarning('未检测到设备', '请连接手机并进入 ADB 或 Fastboot 模式。')
            return

        target = 'Enforcing（强制）' if enforcing else 'Permissive（宽松）'
        if not messagebox.askyesno('确认切换', '确定要切换 SELinux 为 %s 吗？' % target):
            return

        def job(_ctl):
            r = app.runner
            app.log_out('---------- SELinux 切换为 %s ----------' % target)

            if st.adb:
                arg = '1' if enforcing else '0'
                app.log_out('通过 ADB 执行 setenforce %s...' % arg)
                res = r.su('setenforce ' + arg, quiet=True, timeout=20)
                if res.ok:
                    app.log_out('[成功] 已切换为 %s。' % target)
                    return ('adb', True)
                app.log_out('[错误] 切换失败，请确认已获取 Root（setenforce 需要 root 权限）。')
                return ('adb', False)

            # Fastboot 分支
            value = 'enforcing' if enforcing else 'permissive'
            app.log_out('通过 Fastboot 下发 androidboot.selinux=%s ...' % value)
            res = r.run(['fastboot', 'oem', 'set-gpu-preemption', '0',
                         'androidboot.selinux=' + value], quiet=True, timeout=30)
            if not res.ok:
                app.log_out('[错误] Fastboot 命令执行失败。')
                return ('fastboot', False)
            app.log_out('[成功] 参数已下发。注意：需继续启动系统后生效。')
            return ('fastboot', True)

        def done(result):
            # 弹窗必须在主线程执行（Tk 非线程安全）
            if not ui.widget_alive(self.lbl_state):
                return
            mode, ok = result if result else ('adb', False)
            if mode == 'fastboot' and ok:
                if messagebox.askyesno(
                        '继续启动',
                        'SELinux 参数已下发，是否现在执行 fastboot continue 启动系统？'):
                    def cont(_ctl):
                        app.runner.run(['fastboot', 'continue'],
                                       quiet=True, timeout=30)
                        app.log_out('已发送启动命令，手机正在启动。')
                    app.run_task(cont, busy_text='正在启动系统...',
                                 done_text='启动命令已发送')
                    return
            if ok:
                self.refresh_state()

        app.run_task(job, on_done=done, busy_text='正在切换 SELinux...',
                     done_text='切换操作完成')
