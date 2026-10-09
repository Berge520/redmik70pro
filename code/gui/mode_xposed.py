# -*- coding: utf-8 -*-
"""模式10：Xposed 模块管理（Vector / LSPosed / 原始 Xposed）"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

import core
import main as ui

ORIG_CONF = '/data/data/de.robv.android.xposed.installer/conf'
ORIG_LIST = ORIG_CONF + '/modules.list'
ORIG_DISABLED = ORIG_CONF + '/disabled'

TYPE_LABEL = {
    core.XP_VECTOR: 'Vector',
    core.XP_LSPOSED: 'LSPosed',
    core.XP_ORIGINAL: '原始 Xposed',
    core.XP_ORIGINAL_INSTALLED: '原始 Xposed（未激活）',
    core.XP_NONE: '未检测到',
}


class XposedFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app
        self.xp_type = core.XP_NONE
        self.cli_path = ''

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'Xposed 模块管理',
                  '自动识别设备上的 Vector / LSPosed / 原始 Xposed 框架，'
                  '列出模块并支持启用、禁用操作（重启后生效）。')

        # 框架状态
        outer, card = ui.card(inner, accent=ui.C_ACCENT, fill=ui.C_CARD, pad=(12, 10))
        outer.pack(fill='x', pady=(0, 4))
        self.lbl_type = tk.Label(card, text='框架：未检测', bg=ui.C_CARD,
                                 fg=ui.C_TEXT, font=ui.FONT_BOLD, anchor='w')
        self.lbl_type.pack(anchor='w', pady=(0, 2))
        self.lbl_cli = tk.Label(card, text='', bg=ui.C_CARD, fg=ui.C_MUTED,
                                font=ui.FONT_SMALL, anchor='w')
        self.lbl_cli.pack(anchor='w')

        # 工具条
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x')
        ui.button(bar, '重新检测框架', self.detect, accent=True)
        self.btn_list = ttk.Button(bar, text='刷新模块列表', command=self.load_modules)
        self.btn_list.pack(side='left', padx=(0, 8), pady=4)
        ui.button(bar, '检测 Root', self.check_root_btn)

        # 模块列表
        self.tree = ttk.Treeview(inner, columns=('mod', 'state'), show='headings',
                                 height=8)
        self.tree.heading('mod', text='模块（包名 / 标识）')
        self.tree.heading('state', text='状态')
        self.tree.column('mod', width=520, minwidth=200, anchor='w', stretch=True)
        self.tree.column('state', width=140, minwidth=100, anchor='w', stretch=False)
        self.tree.pack(fill='both', expand=True, pady=(10, 0))

        # 操作
        op = tk.Frame(inner, bg=ui.C_PANEL)
        op.pack(fill='x', pady=(10, 0))
        self.btn_disable = ttk.Button(op, text='禁用选中模块', command=self.disable_selected)
        self.btn_disable.pack(side='left', padx=(0, 8), pady=4)
        self.btn_disable.state(['disabled'])
        self.btn_enable = ttk.Button(op, text='启用选中模块', command=self.enable_selected)
        self.btn_enable.pack(side='left', padx=(0, 8), pady=4)
        self.btn_enable.state(['disabled'])
        ui.button(op, '手动输入包名操作', self.manual)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)

        self._enable_ops(False)

    def on_device_change(self, st):
        if st.adb:
            self.detect()

    def _on_select(self, _event):
        has = bool(self.tree.selection())
        if has:
            self.btn_disable.state(['!disabled'])
            self.btn_enable.state(['!disabled'])
        else:
            self._enable_ops(False)

    def _enable_ops(self, on):
        if on:
            self.btn_disable.state(['!disabled'])
            self.btn_enable.state(['!disabled'])
        else:
            self.btn_disable.state(['disabled'])
            self.btn_enable.state(['disabled'])

    # -----------------------------------------------------------
    def check_root_btn(self):
        def job(_ctl):
            ok = core.is_root(self.app.runner)
            self.app.log_out('[Root 检查] %s' % ('已获取' if ok else '未获取'))
            return ok

        self.app.run_task(job, busy_text='正在检测 Root...', done_text='检测完成')

    def detect(self):
        if not ui.require_adb(self.app):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 检测 Xposed 框架 ----------')
            if not core.is_root(app.runner):
                app.log_out('[错误] 未获取 Root，无法检测 Xposed 框架。')
                return None
            xp_type, cli = core.detect_xposed(app.runner)
            app.log_out('框架类型：%s' % TYPE_LABEL.get(xp_type, xp_type))
            if cli:
                app.log_out('CLI 路径：%s' % cli)
            return xp_type, cli

        def done(res):
            if not ui.widget_alive(self.lbl_type):
                return
            if res is None:
                self.lbl_type.configure(text='框架：检测失败（需 Root）', fg=ui.C_ERR)
                self.lbl_cli.configure(text='请先执行模式 2 或模式 3 提权。')
                self._enable_ops(False)
                return
            self.xp_type, self.cli_path = res
            label = TYPE_LABEL.get(self.xp_type, self.xp_type)
            if self.xp_type == core.XP_NONE:
                self.lbl_type.configure(text='框架：未检测到', fg=ui.C_ERR)
                self.lbl_cli.configure(
                    text='未发现 Vector / LSPosed / 原始 Xposed 的安装痕迹。')
                self._enable_ops(False)
            elif self.xp_type == core.XP_ORIGINAL_INSTALLED:
                self.lbl_type.configure(text='框架：%s' % label, fg=ui.C_WARN)
                self.lbl_cli.configure(
                    text='检测到管理器已安装但模块列表缺失，框架可能未正常激活。')
                self._enable_ops(False)
            else:
                self.lbl_type.configure(text='框架：%s' % label, fg=ui.C_OK)
                self.lbl_cli.configure(
                    text='CLI 路径：%s' % (self.cli_path or '（原始 Xposed 使用配置文件方式）'))
                self._enable_ops(True)
                self.load_modules()

        self.app.run_task(job, on_done=done, busy_text='正在检测 Xposed 框架...',
                          done_text='检测完成')

    # -----------------------------------------------------------
    def load_modules(self):
        if self.xp_type in (core.XP_NONE, core.XP_ORIGINAL_INSTALLED):
            self._enable_ops(False)
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 读取 Xposed 模块 ----------')
            rows = []
            if self.xp_type in (core.XP_VECTOR, core.XP_LSPOSED):
                res = r.su('%s modules list' % self.cli_path, quiet=True, timeout=25)
                for line in res.lines:
                    line = line.strip()
                    if not line or line.lower().startswith(('module', '---')):
                        continue
                    rows.append((line, ''))
                    app.log_out('  %s' % line)
                if not rows:
                    app.log_out('（CLI 未返回模块，或输出格式与预期不同）')
            else:
                res = r.su('cat ' + ORIG_LIST, quiet=True, timeout=20)
                for line in res.lines:
                    line = line.strip()
                    if line:
                        rows.append((line, '启用'))
                        app.log_out('  [启用] %s' % line)
                if not rows:
                    app.log_out('（模块列表为空或文件不存在）')
            return rows

        def done(rows):
            # 任务结束时可能已切换模式，控件被销毁则直接放弃本次渲染。
            if not ui.widget_alive(self.tree):
                return
            for i in self.tree.get_children():
                self.tree.delete(i)
            if rows is None:
                return
            for mod, state in rows:
                self.tree.insert('', 'end', values=(mod, state))
            self._enable_ops(bool(rows))

        self.app.run_task(job, on_done=done, busy_text='正在读取模块列表...',
                          done_text='模块列表已更新')

    # -----------------------------------------------------------
    def _selected_module(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], 'values')[0]

    def disable_selected(self):
        mod = self._selected_module()
        if mod:
            self._operate(mod, enable=False)

    def enable_selected(self):
        mod = self._selected_module()
        if mod:
            self._operate(mod, enable=True)

    def manual(self):
        if self.xp_type in (core.XP_NONE, core.XP_ORIGINAL_INSTALLED):
            messagebox.showinfo('提示', '当前未检测到可用框架，请先执行「重新检测框架」。')
            return
        pkg = simpledialog.askstring('手动操作', '请输入模块包名 / 标识：', parent=self)
        if not pkg or not pkg.strip():
            return
        pkg = pkg.strip()
        if not core.valid_module_name(pkg.replace('.', '_')) and not pkg:
            messagebox.showerror('非法输入', '模块标识不能为空。')
            return
        if not messagebox.askyesno('选择操作', '要对 [%s] 执行什么操作？\n\n是=禁用，否=启用' % pkg):
            self._operate(pkg, enable=True)
        else:
            self._operate(pkg, enable=False)

    def _operate(self, mod, enable):
        action = '启用' if enable else '禁用'
        if not messagebox.askyesno(
                '确认%s' % action,
                '即将%s模块：\n\n  %s\n\n操作重启手机后生效，是否继续？' % (action, mod)):
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- %s模块 %s ----------' % (action, mod))

            if self.xp_type in (core.XP_VECTOR, core.XP_LSPOSED):
                verb = 'enable' if enable else 'disable'
                res = r.su('%s modules %s %s' % (self.cli_path, verb, mod),
                           quiet=True, timeout=25)
                if res.ok:
                    app.log_out('[成功] 模块 %s 已%s，重启手机后生效。' % (mod, action))
                    return True
                app.log_out('[错误] %s失败，请确认模块标识正确且 CLI 支持该操作。' % action)
                return False

            # 原始 Xposed：通过 modules.list / disabled 文件管理
            if enable:
                check = r.su('grep -q "^%s$" %s' % (mod, ORIG_LIST),
                             quiet=True, timeout=20)
                if check.ok:
                    app.log_out('[提示] 模块 %s 已在列表中，无需重复启用。' % mod)
                    return True
                res = r.su('echo %s >> %s' % (mod, ORIG_LIST), quiet=True, timeout=20)
                if res.ok:
                    app.log_out('[成功] 模块 %s 已添加到列表，重启后生效。' % mod)
                    return True
                app.log_out('[错误] 写入 modules.list 失败，请检查权限。')
                return False
            else:
                tmp = ORIG_LIST + '.tmp'
                res = r.su('grep -v "^%s$" %s > %s' % (mod, ORIG_LIST, tmp),
                           quiet=True, timeout=20)
                if not res.ok:
                    app.log_out('[错误] 未找到模块 %s 或 grep 不可用。' % mod)
                    return False
                res = r.su('mv %s %s' % (tmp, ORIG_LIST), quiet=True, timeout=20)
                if res.ok:
                    app.log_out('[成功] 模块 %s 已从列表移除，重启后生效。' % mod)
                    return True
                app.log_out('[错误] 替换 modules.list 失败，请检查权限。')
                return False

        def done(_ok):
            if not ui.widget_alive(self.tree):
                return
            self.load_modules()

        self.app.run_task(job, on_done=done, busy_text='正在%s模块...' % action,
                          done_text='操作完成')
