# -*- coding: utf-8 -*-
"""模式5：Root 模块管理（查看 / 禁用 / 启用 / 卸载）"""

import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui

STATE_TEXT = {'enabled': '已启用', 'disabled': '已禁用', 'removed': '待删除'}


class ModulesFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app
        self._modules = []

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'Root 模块管理',
                  '列出 /data/adb/modules/ 下的全部模块并读取其显示名与启用状态。'
                  '禁用会保留文件但重启后不加载（可逆），卸载则彻底删除（不可撤销）。')

        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x')
        ui.button(bar, '刷新模块列表', self.refresh, accent=True)
        self.btn_disable = ttk.Button(bar, text='禁用选中模块', command=self.disable)
        self.btn_disable.pack(side='left', padx=(0, 8), pady=4)
        self.btn_disable.state(['disabled'])
        self.btn_enable = ttk.Button(bar, text='启用选中模块', command=self.enable)
        self.btn_enable.pack(side='left', padx=(0, 8), pady=4)
        self.btn_enable.state(['disabled'])
        self.btn_uninstall = ttk.Button(bar, text='卸载选中模块', command=self.uninstall)
        self.btn_uninstall.pack(side='left', padx=(0, 8), pady=4)
        self.btn_uninstall.state(['disabled'])
        ui.button(bar, '复制模块名', self.copy_name)

        self.lbl_count = ttk.Label(inner, text='', style='Muted.TLabel')
        self.lbl_count.pack(anchor='w', pady=(8, 0))

        cols = ('folder', 'name', 'state')
        self.tree = ttk.Treeview(inner, columns=cols, show='headings')
        self.tree.heading('folder', text='模块文件夹名')
        self.tree.heading('name', text='显示名称')
        self.tree.heading('state', text='状态')
        self.tree.column('folder', width=250, minwidth=150, anchor='w', stretch=False)
        self.tree.column('name', width=400, minwidth=180, anchor='w', stretch=True)
        self.tree.column('state', width=90, minwidth=70, anchor='center', stretch=False)
        vsb = ttk.Scrollbar(inner, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y', pady=(8, 0))
        self.tree.pack(side='left', fill='both', expand=True, pady=(8, 0))
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        # 状态列配色：已禁用=橙，待删除=红
        self.tree.tag_configure('disabled', foreground=ui.C_WARN)
        self.tree.tag_configure('removed', foreground=ui.C_ERR)

        tip = tk.Label(inner,
                       text='提示：禁用 = 写入 disable 标记，文件保留、重启后不加载，可随时启用；'
                            '卸载 = 彻底删除目录，不可撤销。两者均重启后生效。',
                       bg=ui.C_PANEL, fg=ui.C_WARN, font=ui.FONT_SMALL)
        tip.pack(anchor='w', pady=(8, 0))

    def on_device_change(self, st):
        if not st.adb:
            return
        cached = self.app.mode_cache.get('modules')
        if cached is not None:
            self._render(cached)
            self.app.log_out('[提示] 已恢复上次模块列表，点「刷新模块列表」可重新读取。')
            return
        self.refresh()

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            self._set_ops(False, False, False)
            return
        state = self.tree.item(sel[0], 'values')[2]
        # 按当前状态给出可执行的操作：已禁用只能启用，正常只能禁用，
        # 待删除模块两种都不给（等重启由管理器清理）。
        self._set_ops(state == '已启用', state == '已禁用', state != '待删除')

    def _set_ops(self, can_disable, can_enable, can_uninstall):
        for btn, ok in ((self.btn_disable, can_disable),
                        (self.btn_enable, can_enable),
                        (self.btn_uninstall, can_uninstall)):
            btn.state(['!disabled'] if ok else ['disabled'])

    def _selected_folder(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.tree.item(sel[0], 'values')[0]

    # -----------------------------------------------------------
    def refresh(self):
        if not ui.require_adb(self.app):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 正在获取模块列表 ----------')
            if not core.is_root(app.runner):
                app.log_out('[错误] 未获取 Root，请先执行模式 2 或模式 3 提权。')
                return None
            items = core.list_module_states(app.runner)
            for folder, name, state in items:
                app.log_out('  [%s] %s（%s）'
                            % (folder, name or '（无描述信息）',
                               STATE_TEXT.get(state, state)))
            if not items:
                app.log_out('未发现任何模块。')
            return items

        def done(items):
            if not ui.widget_alive(self.tree):
                return
            if items is None:
                for i in self.tree.get_children():
                    self.tree.delete(i)
                self.lbl_count.configure(text='读取失败：未获取 Root 权限')
                return
            # 仅在读到内容时写缓存：空列表不应覆盖缓存，否则下次进入模式
            # 会命中"空缓存"直接渲染空表，掩盖了本可复用的历史结果。
            if items:
                self.app.mode_cache['modules'] = list(items)
            else:
                self.app.mode_cache.pop('modules', None)
            self._render(items)

        self.app.run_task(job, on_done=done, busy_text='正在读取模块列表...',
                          done_text='模块列表已更新')

    def _render(self, items):
        """渲染模块列表（主线程调用）。"""
        # 任务结束时可能已切换模式，控件被销毁则直接放弃本次渲染。
        if not ui.widget_alive(self.tree):
            return
        for i in self.tree.get_children():
            self.tree.delete(i)
        self._modules = list(items)
        for folder, name, state in items:
            tag = state if state in ('disabled', 'removed') else ''
            self.tree.insert('', 'end',
                             values=(folder, name or '（无描述信息）',
                                     STATE_TEXT.get(state, state)),
                             tags=(tag,) if tag else ())
        n_dis = sum(1 for _, _, s in items if s == 'disabled')
        self.lbl_count.configure(
            text='共 %d 个模块（已禁用 %d 个）' % (len(items), n_dis))
        self._set_ops(False, False, False)

    def copy_name(self):
        folder = self._selected_folder()
        if not folder:
            messagebox.showinfo('提示', '请先在上方列表中选择一个模块。')
            return
        self.app.clipboard_clear()
        self.app.clipboard_append(folder)
        self.app.log_out('[剪贴板] 已复制模块名：%s' % folder)

    # -----------------------------------------------------------
    def disable(self):
        self._toggle(enable=False)

    def enable(self):
        self._toggle(enable=True)

    def _toggle(self, enable):
        folder = self._selected_folder()
        if not folder:
            messagebox.showinfo('提示', '请先在上方列表中选择一个模块。')
            return
        if not core.valid_module_name(folder):
            messagebox.showerror('非法模块名', '模块名 [%s] 不合法。' % folder)
            self.app.log_out('[拒绝操作] 模块名不合法：%s' % folder)
            return

        act = '启用' if enable else '禁用'
        detail = ('将删除 disable 标记，重启后恢复加载。'
                  if enable else '将写入 disable 标记，文件保留、重启后不再加载，可随时启用。')
        if not messagebox.askyesno(
                '确认%s' % act,
                '确定要%s模块 [%s] 吗？\n\n%s' % (act, folder, detail)):
            return

        base = '/data/adb/modules/%s' % folder
        cmd = ('rm -f %s/disable' % base) if enable else ('touch %s/disable' % base)

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- %s模块 %s ----------' % (act, folder))
            # /data/adb/modules 仅 root 可读，探测必须走 su，
            # 否则非 root 的 test 必然失败，导致无法禁用/启用。
            if not r.su('test -d %s' % base, quiet=True, timeout=15).ok:
                app.log_out('[错误] 模块不存在或无法访问。')
                return False
            if r.su(cmd, quiet=True, timeout=20).ok:
                app.log_out('[成功] 已%s模块 [%s]，重启手机后生效。' % (act, folder))
                return True
            app.log_out('[错误] %s失败，请检查 Root 权限。' % act)
            return False

        def done(ok):
            if ok:
                self.refresh()

        self.app.run_task(job, on_done=done, busy_text='正在%s模块...' % act,
                          done_text='%s操作完成' % act)

    # -----------------------------------------------------------
    def uninstall(self):
        folder = self._selected_folder()
        if not folder:
            messagebox.showinfo('提示', '请先在上方列表中选择一个模块。')
            return

        # 安全校验（等价于 bat 版的双重校验）
        if not core.valid_module_name(folder):
            messagebox.showerror('非法模块名',
                                 '模块名 [%s] 不合法，只允许字母、数字、下划线、连字符和点，'
                                 '且不能包含连续点号。' % folder)
            self.app.log_out('[拒绝卸载] 模块名不合法：%s' % folder)
            return

        if not messagebox.askyesno(
                '确认卸载',
                '确定要彻底删除模块吗？\n\n'
                '  模块名：%s\n'
                '  将执行：rm -rf /data/adb/modules/%s\n\n'
                '此操作不可撤销，重启后生效。\n'
                '（若只想临时停用，请改用「禁用选中模块」）' % (folder, folder)):
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 卸载模块 %s ----------' % folder)

            # 同上：目录存在性探测必须以 root 执行。
            if not r.su('test -d /data/adb/modules/%s' % folder,
                        quiet=True, timeout=15).ok:
                app.log_out('[错误] 模块不存在或无法访问。')
                return False

            res = r.su('rm -rf /data/adb/modules/%s' % folder,
                       quiet=True, timeout=30)
            if res.ok:
                app.log_out('[成功] 已卸载模块 [%s]，重启手机后生效。' % folder)
                return True
            app.log_out('[错误] 卸载失败，请检查 Root 权限。')
            return False

        def done(ok):
            if ok:
                self.refresh()

        self.app.run_task(job, on_done=done, busy_text='正在卸载模块...',
                          done_text='卸载操作完成')

