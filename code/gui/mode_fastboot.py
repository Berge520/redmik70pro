# -*- coding: utf-8 -*-
"""模式3：Fastboot 分区提权流程"""

import time
import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui

_sleep_cancellable = core.sleep_cancellable


class FastbootFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'Fastboot 分区提权流程',
                  '通过 Fastboot 下发 androidboot.selinux=permissive 参数，'
                  '使系统以宽松模式启动后完成提权。\n'
                  '新版 KernelSU 通常只需 [1]→[3]，之后在管理器点「越狱」即可。')

        # 顶部一键流程
        top = tk.Frame(inner, bg=ui.C_PANEL)
        top.pack(fill='x', pady=(0, 10))
        self.btn_all = ui.button(top, '★ 一键完整流程', self.do_all, accent=True)
        ui.button(top, '刷新设备连接', app.refresh_devices)
        ui.button(top, '检查 Fastboot 连接', self.check_fb)
        ui.button(top, '检查 Root 状态', self.check_root)

        # 设备状态徽章
        badge = tk.Frame(inner, bg=ui.C_BG, highlightbackground=ui.C_BORDER,
                         highlightthickness=1)
        badge.pack(anchor='w', pady=(0, 12))
        self.badge_dev = badge
        self.lbl_dev = tk.Label(badge, text='设备状态：检测中...', bg=ui.C_BG,
                                fg=ui.C_MUTED, font=ui.FONT_SMALL,
                                padx=10, pady=4)
        self.lbl_dev.pack()

        # ── 常用步骤（新版 KernelSU）──
        ui.section(inner, '常用流程（新版 KernelSU）', '通常只需执行 [1]→[3]')
        grid = tk.Frame(inner, bg=ui.C_PANEL)
        grid.pack(fill='x')

        common_steps = [
            ('1. 重启进入 Fastboot', '重启设备到 bootloader', self.step1),
            ('2. 设置 SELinux 宽松', '下发 permissive 启动参数', self.step2),
            ('3. 继续启动系统', 'fastboot continue', self.step3),
        ]
        self._render_steps(grid, common_steps)

        tk.Label(inner, text='完成 [3] 后，打开 KernelSU 管理器点「越狱」即可；'
                             '若需手动提权，再展开下方旧版流程。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL,
                 anchor='w', wraplength=720, justify='left').pack(anchor='w',
                                                                  pady=(2, 0))

        # ── 旧版 KernelSU 补充流程（默认折叠）──
        fold = ui.collapsible(inner, '旧版 KernelSU 流程（步骤 4~7）',
                              expanded=False, hint='新版通常无需')
        leg = tk.Frame(fold, bg=ui.C_PANEL)
        leg.pack(fill='x', padx=2, pady=(6, 0))

        tk.Label(leg, text='以下步骤用于较早版本的 KernelSU（需手动推送 ksud 并执行漏洞提权）：',
                 bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL,
                 anchor='w', wraplength=680, justify='left').pack(anchor='w', pady=(0, 4))

        leg_grid = tk.Frame(leg, bg=ui.C_PANEL)
        leg_grid.pack(fill='x')
        legacy_steps = [
            ('4. 等待系统启动完成', '轮询 sys.boot_completed', self.step4),
            ('5. 推送 ksud', 'adb push + chmod', self.step5),
            ('6. 执行漏洞提权', 'service call late-load', self.step6),
            ('7. 恢复 SELinux 强制', 'setenforce 1', self.step7),
        ]
        self._render_steps(leg_grid, legacy_steps)

    def _render_steps(self, grid, steps):
        """把步骤列表渲染成两列卡片网格。"""
        for i, (title, desc, cmd) in enumerate(steps):
            row, col = divmod(i, 2)
            card, txt = ui.card(grid, accent=ui.C_ACCENT, fill=ui.C_CARD,
                                pad=(12, 10))
            card.grid(row=row, column=col, sticky='nsew',
                      padx=(0, 10), pady=(0, 10))
            grid.columnconfigure(col, weight=1, uniform='stepcol')

            tk.Label(txt, text=title, bg=ui.C_CARD, fg=ui.C_TEXT,
                     font=ui.FONT_BOLD, anchor='w').pack(anchor='w')
            tk.Label(txt, text=desc, bg=ui.C_CARD, fg=ui.C_MUTED,
                     font=ui.FONT_SMALL, anchor='w').pack(
                anchor='w', pady=(2, 0))

            ttk.Button(card, text='执行', command=cmd, width=6).pack(
                side='right', padx=12)

    def on_device_change(self, st):
        self.lbl_dev.configure(
            text='设备状态：%s' % ('Fastboot 已连接' if st.fastboot else
                                  ('ADB 已连接' if st.adb else '未检测到设备')),
            foreground=ui.C_OK if st.any else ui.C_ERR)
        self.badge_dev.configure(
            highlightbackground=ui.C_OK if st.any else ui.C_BORDER)

    # -----------------------------------------------------------
    def check_fb(self):
        def job(_ctl):
            res = self.app.runner.run(['fastboot', 'getvar', 'product'], quiet=True, timeout=20)
            ok = 'product' in res.text.lower()
            self.app.log_out('[Fastboot 检查] %s' % ('已连接' if ok else '未检测到设备'))
            return ok

        self.app.run_task(job, busy_text='正在检查 Fastboot...', done_text='检查完毕')

    def check_root(self):
        def job(_ctl):
            ok = core.is_root(self.app.runner)
            self.app.log_out('[Root 检查] %s' % ('已获取' if ok else '未获取'))
            return ok

        self.app.run_task(job, busy_text='正在检查 Root...', done_text='检查完毕')

    # -----------------------------------------------------------
    def step1(self):
        self.app.run_task(self._wait_fastboot, busy_text='正在重启到 Fastboot...',
                          done_text='Fastboot 就绪')

    def _wait_fastboot(self, ctl, timeout=45):
        app = self.app
        r = app.runner
        app.log_out('[步骤1] 重启进入 Fastboot...')
        r.run(['adb', 'reboot', 'bootloader'], quiet=True, timeout=20)

        app.log_out('等待设备进入 Fastboot（最长 %d 秒）...' % timeout)
        waited = 0
        while waited < timeout:
            if ctl.cancelled:
                app.log_out('[已取消] 停止等待 Fastboot。')
                return False
            # 单次探测设短超时：设备未就绪时命令很快返回错误，无需长阻塞。
            # quiet=True 让轮询过程中的命令行/超时不再写入日志，避免刷屏。
            res = r.run(['fastboot', 'getvar', 'product'], quiet=True, timeout=6)
            if 'product' in res.text.lower():
                app.log_out('[成功] 已进入 Fastboot。')
                app.device.fastboot = True
                app.device.adb = False
                app.refresh_devices()
                return True
            _sleep_cancellable(ctl, 1)
            waited += 1
            if waited % 15 == 0:
                app.log_out('等待中... %d 秒' % waited)
        app.log_out('[超时] 未检测到 Fastboot 设备，请确认驱动已安装或换用 USB 2.0 接口。')
        return False

    def step2(self):
        def job(_ctl):
            app = self.app
            app.log_out('[步骤2] 设置 SELinux 宽松模式（permissive）...')
            res = app.runner.run(
                ['fastboot', 'oem', 'set-gpu-preemption', '0',
                 'androidboot.selinux=permissive'],
                quiet=True, timeout=30)
            if res.ok:
                app.log_out('[成功] 启动参数已下发（需继续启动系统后生效）。')
                app.log_out('说明：该参数仅本次启动有效，属临时修改。')
            else:
                app.log_out('[警告] 命令返回非 0，部分机型不支持该 OEM 命令。')
            return res.ok

        self.app.run_task(job, busy_text='正在下发 SELinux 参数...', done_text='参数已下发')

    def step3(self):
        def job(_ctl):
            app = self.app
            app.log_out('[步骤3] 继续启动系统（fastboot continue）...')
            res = app.runner.run(['fastboot', 'continue'], quiet=True, timeout=30)
            if res.ok:
                app.log_out('手机正在启动，请等待完全启动完成，再执行步骤 4。')
            else:
                app.log_out('[警告] fastboot continue 返回非 0，请确认设备处于 Fastboot 模式。')
            return res.ok

        self.app.run_task(job, busy_text='正在继续启动...', done_text='已发送启动命令')

    def step4(self):
        self.app.run_task(lambda ctl: self._wait_boot(ctl),
                          busy_text='正在等待系统启动完成...', done_text='系统已启动')

    def _wait_boot(self, ctl, timeout=180):
        app = self.app
        r = app.runner
        app.log_out('[步骤4] 等待系统启动完成（最长 %d 秒）...' % timeout)
        waited = 0
        while waited < timeout:
            if ctl.cancelled:
                app.log_out('[已取消] 停止等待。')
                return False
            r.run(['adb', 'wait-for-device'], quiet=True, timeout=20)
            boot = core.getprop(r, 'sys.boot_completed', timeout=15)
            if boot == '1':
                app.log_out('[成功] 系统已完全启动（耗时 %d 秒）。' % waited)
                app.refresh_devices()
                return True
            _sleep_cancellable(ctl, 2)
            waited += 2
            if waited % 20 == 0:
                app.log_out('等待中... %d 秒' % waited)
        app.log_out('[超时] 等待超时，请确认手机是否已进入桌面。')
        return False

    def step5(self):
        def job(_ctl):
            app = self.app
            r = app.runner
            ksud = core.find_ksud()
            app.log_out('[步骤5] 推送 ksud...')
            if not ksud:
                app.log_out('[错误] 工具目录（或 tools/）下找不到 ksud 文件。')
                return False
            if not r.run(['adb', 'push', ksud, '/data/local/tmp/'],
                         quiet=True, timeout=90).ok:
                app.log_out('[错误] adb push 失败，请确认设备已启动并连接。')
                return False
            if not r.shell('chmod 777 /data/local/tmp/ksud', quiet=True, timeout=20).ok:
                app.log_out('[错误] chmod 失败。')
                return False
            app.log_out('[成功] ksud 已推送并赋权。')
            return True

        self.app.run_task(job, busy_text='正在推送 ksud...', done_text='推送完成')

    def step6(self):
        def job(ctl):
            app = self.app
            r = app.runner
            app.log_out('[步骤6] 执行 service call 漏洞...')
            res = r.run(['adb', 'shell', core.EXPLOIT_CMD], quiet=True, timeout=40)
            if not res.ok:
                app.log_out('[错误] service call 执行失败。')
                return False
            app.log_out('[提示] 命令已发送，等待 3 秒...')
            _sleep_cancellable(ctl, 3)
            if core.is_root(r):
                app.log_out('[成功] Root 已获取。')
            else:
                app.log_out('[!] 尚未获得 Root，请查看 /sdcard/ksulog.txt。')
                self._dump_ksulog(app)
            return True

        self.app.run_task(job, busy_text='正在执行提权...', done_text='提权流程结束')

    @staticmethod
    def _dump_ksulog(app):
        res = app.runner.shell('cat /sdcard/ksulog.txt', quiet=True, timeout=15)
        if res.lines:
            app.log_out('---------- /sdcard/ksulog.txt ----------')
            for line in res.lines[-25:]:
                app.log_out(line)
            app.log_out('----------------------------------------')

    def step7(self):
        def job(_ctl):
            app = self.app
            app.log_out('[步骤7] 恢复 SELinux 强制模式...')
            if app.runner.su('setenforce 1', quiet=True, timeout=20).ok:
                app.log_out('[成功] 已恢复 Enforcing 模式。')
                return True
            app.log_out('[错误] 恢复失败，请检查 Root 权限。')
            return False

        self.app.run_task(job, busy_text='正在恢复 SELinux...', done_text='操作完成')

    # -----------------------------------------------------------
    def do_all(self):
        if not messagebox.askyesno(
                '确认一键流程',
                '将依次执行：\n'
                '  1. 重启进入 Fastboot\n'
                '  2. 设置 SELinux 宽松\n'
                '  3. 继续启动系统\n'
                '  4. 等待系统启动完成\n'
                '  5. 推送 ksud\n'
                '  6. 执行漏洞提权（旧版 KernelSU）\n\n'
                '新版 KernelSU 执行到 [3] 后，在管理器点「越狱」即可。\n'
                '全程需要数分钟，期间请勿断开 USB。是否开始？'):
            return
        # 流程长达数分钟，期间禁用入口按钮，避免用户重复点击。
        # （run_task 的 _busy 也会拦截并发任务，这里只是给出更直观的反馈。）
        try:
            self.btn_all.state(['disabled'])
        except tk.TclError:
            pass
        self.app.run_task(self._work_all, on_done=self._restore_all_btn,
                          busy_text='正在执行一键流程...', done_text='一键流程结束')

    def _restore_all_btn(self, _result=None):
        """一键流程结束（成功/失败/取消）后恢复入口按钮。"""
        try:
            self.btn_all.state(['!disabled'])
        except tk.TclError:
            pass

    def _work_all(self, ctl):
        app = self.app
        r = app.runner

        if not self._wait_fastboot(ctl):
            app.log_out('[中止] 未进入 Fastboot，一键流程结束。')
            return False

        if ctl.cancelled:
            app.log_out('[已取消] 一键流程已中断。')
            return False

        app.log_out('[步骤2] 设置 SELinux 宽松模式...')
        res = r.run(['fastboot', 'oem', 'set-gpu-preemption', '0',
                     'androidboot.selinux=permissive'], quiet=True, timeout=30)
        if not res.ok:
            app.log_out('[警告] SELinux 参数下发返回非 0，部分机型不支持该 OEM 命令，继续尝试。')

        if ctl.cancelled:
            app.log_out('[已取消] 一键流程已中断。')
            return False

        app.log_out('[步骤3] 继续启动系统...')
        res = r.run(['fastboot', 'continue'], quiet=True, timeout=30)
        if not res.ok:
            app.log_out('[中止] fastboot continue 失败，请确认设备处于 Fastboot 模式。')
            return False

        if not self._wait_boot(ctl):
            app.log_out('[中止] 等待系统启动超时或被取消，一键流程结束。')
            return False

        if ctl.cancelled:
            app.log_out('[已取消] 一键流程已中断。')
            return False

        ksud = core.find_ksud()
        app.log_out('[步骤5] 推送 ksud...')
        if not ksud:
            app.log_out('[错误] 找不到 ksud 文件。')
            return False
        if not r.run(['adb', 'push', ksud, '/data/local/tmp/'],
                     quiet=True, timeout=90).ok:
            app.log_out('[错误] adb push 失败。')
            return False
        if not r.shell('chmod 777 /data/local/tmp/ksud', quiet=True, timeout=20).ok:
            app.log_out('[警告] chmod 未成功，后续提权可能失败。')
        app.log_out('[成功] ksud 已推送。')

        if ctl.cancelled:
            app.log_out('[已取消] 一键流程已中断。')
            return False

        app.log_out('[步骤6] 执行漏洞提权...')
        r.run(['adb', 'shell', core.EXPLOIT_CMD], quiet=True, timeout=40)
        _sleep_cancellable(ctl, 3)
        if core.is_root(r):
            app.log_out('[成功] Root 已获取。')
        else:
            app.log_out('[!] 尚未获得 Root，请查看 /sdcard/ksulog.txt。')
            self._dump_ksulog(app)

        app.log_out('')
        app.log_out('提示：当前 SELinux 为宽松模式，建议执行 [7. 恢复 SELinux 强制] 提升安全性。')
        return True
