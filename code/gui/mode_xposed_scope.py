# -*- coding: utf-8 -*-
"""Xposed 模块作用域编辑（查看 / 增删 某模块会注入哪些 App）。

从 mode_xposed.py 拆出的独立能力块：以 XposedScopeMixin 形式提供「作用域编辑」
面板的 UI 构建与操作逻辑，由 XposedFrame 直接继承。

作用域 = 该模块会注入哪些 App；某 App 崩溃时，把对应模块从它的作用域移除即可
止损（如 123云盘 被 hook 模块注入后崩溃）。

依赖约定：宿主类需提供
  · self.app          （含 runner / log_out / run_task）
  · self.xp_type      （当前框架类型）
  · self.cli_path     （CLI 路径）
  · self.tree         （模块列表 Treeview）
  · self.scope_box    （作用域区容器 Frame）
  · self._selected_module()（当前选中的模块标识）
"""

import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui


class XposedScopeMixin:

    # -----------------------------------------------------------
    #  作用域编辑：查看 / 增删 某模块会注入哪些 App
    #  （App 被 hook 崩溃时的止损手段：把该 App 从模块作用域移除）
    # -----------------------------------------------------------
    def _build_scope_box(self):
        """构建作用域编辑区控件（默认不显示）。"""
        box = self.scope_box
        ui.section(box, '作用域编辑',
                   '把某个 App 从模块作用域移除，可阻止该模块注入它（止损 App 崩溃）。')

        self.lbl_scope_mod = tk.Label(box, text='未选择模块', bg=ui.C_PANEL,
                                      fg=ui.C_TEXT, font=ui.FONT_BOLD, anchor='w')
        self.lbl_scope_mod.pack(anchor='w')

        bar = tk.Frame(box, bg=ui.C_PANEL)
        bar.pack(fill='x', pady=(6, 0))
        self.btn_scope_reload = ttk.Button(bar, text='重新加载作用域',
                                           command=self.scope_reload)
        self.btn_scope_reload.pack(side='left', padx=(0, 8), pady=4)
        self.btn_scope_rm = ttk.Button(bar, text='移除选中 App',
                                       command=self.scope_remove_selected)
        self.btn_scope_rm.pack(side='left', padx=(0, 8), pady=4)
        self.btn_scope_rm.state(['disabled'])
        ui.button(bar, '关闭作用域编辑', self._hide_scope_box)

        # 作用域列表
        self.scope_tree = ttk.Treeview(box, columns=('pkg', 'uid'), show='headings',
                                       height=6)
        self.scope_tree.heading('pkg', text='已注入的 App 包名')
        self.scope_tree.heading('uid', text='用户 ID')
        self.scope_tree.column('pkg', width=500, minwidth=200, anchor='w', stretch=True)
        self.scope_tree.column('uid', width=80, minwidth=60, anchor='center', stretch=False)
        self.scope_tree.pack(fill='both', expand=True, pady=(8, 0))
        self.scope_tree.bind('<<TreeviewSelect>>', self._on_scope_select)

        # 添加行：把 App 加入作用域
        add = tk.Frame(box, bg=ui.C_PANEL)
        add.pack(fill='x', pady=(8, 0))
        tk.Label(add, text='添加 App 到作用域：', bg=ui.C_PANEL, fg=ui.C_TEXT,
                 font=ui.FONT).pack(side='left')
        self.ent_scope_pkg = ttk.Entry(add, width=34)
        self.ent_scope_pkg.pack(side='left', padx=(6, 6))
        self.ent_scope_pkg.insert(0, 'com.example.app')
        self.ent_scope_uid = ttk.Entry(add, width=5)
        self.ent_scope_uid.pack(side='left', padx=(0, 6))
        self.ent_scope_uid.insert(0, '0')
        self.btn_scope_add = ttk.Button(add, text='添加', command=self.scope_add)
        self.btn_scope_add.pack(side='left')

        tip = tk.Label(box,
                       text='提示：作用域变更通常需重启目标 App 或手机后生效；'
                            '「用户 ID」多数为 0（机主）。',
                       bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL)
        tip.pack(anchor='w', pady=(8, 0))

    def _hide_scope_box(self):
        if ui.widget_alive(self.scope_box):
            self.scope_box.pack_forget()

    def _on_scope_select(self, _event):
        if self.scope_tree.selection():
            self.btn_scope_rm.state(['!disabled'])
        else:
            self.btn_scope_rm.state(['disabled'])

    def edit_scope_selected(self):
        mod = self._selected_module()
        if not mod:
            messagebox.showinfo('提示', '请先在模块列表中选择一个模块。')
            return
        if self.xp_type not in (core.XP_VECTOR, core.XP_LSPOSED) or not self.cli_path:
            messagebox.showinfo('提示', '当前框架不支持作用域编辑。')
            return
        self._scope_module = mod
        self.lbl_scope_mod.configure(text='模块：%s' % mod)
        self.scope_box.pack(fill='x', pady=(10, 0))
        self.scope_reload()

    def scope_reload(self):
        mod = getattr(self, '_scope_module', None)
        if not mod:
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 读取模块作用域 %s ----------' % mod)
            rows = core.xposed_scope_list(r, self.cli_path, mod)
            if rows is None:
                app.log_out('[错误] 读取作用域失败（模块标识错误或 CLI 不支持）。')
                return None
            if not rows:
                app.log_out('（该模块当前作用域为空，不会注入任何 App）')
            for pkg, uid in rows:
                app.log_out('  %s/%d' % (pkg, uid))
            return rows

        def done(rows):
            if not ui.widget_alive(self.scope_tree):
                return
            for i in self.scope_tree.get_children():
                self.scope_tree.delete(i)
            if rows:
                for pkg, uid in rows:
                    self.scope_tree.insert('', 'end', values=(pkg, str(uid)))
            self.btn_scope_rm.state(['disabled'])

        self.app.run_task(job, on_done=done, busy_text='正在读取作用域...',
                          done_text='作用域已更新')

    def scope_add(self):
        mod = getattr(self, '_scope_module', None)
        if not mod:
            return
        pkg = self.ent_scope_pkg.get().strip()
        uid = self.ent_scope_uid.get().strip() or '0'
        target = '%s/%s' % (pkg, uid)
        # 该目标会被拼入 root 命令，必须严格白名单校验，杜绝命令注入。
        if not core.valid_scope_target(target):
            messagebox.showerror(
                '非法输入',
                '作用域条目 [%s] 不合法。\n\n'
                '包名只允许字母、数字、下划线、连字符和点，'
                '用户 ID 必须是非负整数（如 com.example.app/0）。' % target)
            self.app.log_out('[拒绝操作] 作用域条目不合法：%s' % target)
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 添加作用域 %s <- %s ----------' % (mod, target))
            ok, out = core.xposed_scope_add(app.runner, self.cli_path, mod, target)
            app.log_out('[%s] %s' % ('成功' if ok else '失败', out or target))
            return ok

        def done(ok):
            if ui.widget_alive(self.scope_tree) and ok:
                self.scope_reload()

        self.app.run_task(job, on_done=done, busy_text='正在添加作用域...',
                          done_text='添加完成')

    def scope_remove_selected(self):
        mod = getattr(self, '_scope_module', None)
        sel = self.scope_tree.selection()
        if not mod or not sel:
            return
        pkg, uid = self.scope_tree.item(sel[0], 'values')
        target = '%s/%s' % (pkg, uid)
        if not core.valid_scope_target(target):
            messagebox.showerror('非法条目', '条目 [%s] 不合法，已拒绝执行。' % target)
            return
        if not ui.confirm(
                '确认移除',
                '将把 App 从模块作用域移除：\n\n  %s\n\n'
                '移除后该模块不再注入它（可用于止损该 App 崩溃），是否继续？' % target):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 移除作用域 %s -x %s ----------' % (mod, target))
            ok, out = core.xposed_scope_remove(app.runner, self.cli_path, mod, target)
            app.log_out('[%s] %s' % ('成功' if ok else '失败', out or target))
            return ok

        def done(ok):
            if ui.widget_alive(self.scope_tree) and ok:
                self.scope_reload()

        self.app.run_task(job, on_done=done, busy_text='正在移除作用域...',
                          done_text='移除完成')
