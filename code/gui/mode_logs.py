# -*- coding: utf-8 -*-
"""模式9：查看运行日志"""

import os
import glob
import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui

KEEP_DAYS = 7


class LogFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app
        self._files = []

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, '查看运行日志',
                  '查看历史会话日志，便于回溯每次提权、模块操作的结果。'
                  '日志保存在工具目录 logs/ 下。')

        # 工具条
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x')
        ui.button(bar, '查看本次日志', self.load_current, accent=True)
        ui.button(bar, '刷新列表', self.refresh)
        ui.button(bar, '打开日志目录', lambda: os.startfile(core.LOG_DIR))
        ui.button(bar, '清理 %d 天前日志' % KEEP_DAYS, self.cleanup)
        ui.button(bar, '清除全部日志', self.clear_all)

        self.lbl_info = ttk.Label(inner, text='', style='Muted.TLabel')
        self.lbl_info.pack(anchor='w', pady=(8, 6))

        # 左右分栏：文件列表 + 内容
        split = tk.Frame(inner, bg=ui.C_PANEL)
        split.pack(fill='both', expand=True)

        left = tk.Frame(split, bg=ui.C_PANEL, width=250)
        left.pack(side='left', fill='y')
        left.pack_propagate(False)
        tk.Label(left, text='日志文件', bg=ui.C_PANEL, fg=ui.C_TEXT,
                 font=ui.FONT_BOLD).pack(anchor='w', pady=(0, 4))

        lb_box = tk.Frame(left, bg=ui.C_PANEL)
        lb_box.pack(fill='both', expand=True)
        self.listbox = tk.Listbox(lb_box, font=('Consolas', 9), bd=0,
                                  highlightbackground='#e2e5ea', highlightthickness=1,
                                  activestyle='none', selectbackground=ui.C_ACCENT,
                                  selectforeground='#ffffff')
        sb = ttk.Scrollbar(lb_box, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.listbox.pack(side='left', fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self._on_pick)

        right = tk.Frame(split, bg=ui.C_PANEL)
        right.pack(side='left', fill='both', expand=True, padx=(10, 0))
        tk.Label(right, text='日志内容', bg=ui.C_PANEL, fg=ui.C_TEXT,
                 font=ui.FONT_BOLD).pack(anchor='w', pady=(0, 4))
        box = tk.Frame(right, bg='#1e222b')
        box.pack(fill='both', expand=True)
        self.text = tk.Text(box, bg='#1e222b', fg='#c9d1d9', font=ui.FONT_MONO,
                            bd=0, wrap='none', state='disabled')
        vs = ttk.Scrollbar(box, orient='vertical', command=self.text.yview)
        hs = ttk.Scrollbar(box, orient='horizontal', command=self.text.xview)
        self.text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side='right', fill='y')
        hs.pack(side='bottom', fill='x')
        self.text.pack(side='left', fill='both', expand=True)

        self.refresh()

    def on_device_change(self, st):
        pass

    # -----------------------------------------------------------
    def refresh(self):
        self._files = sorted(glob.glob(os.path.join(core.LOG_DIR, '*.log')),
                             reverse=True)
        self.listbox.delete(0, 'end')
        for path in self._files:
            self.listbox.insert('end', ' ' + os.path.basename(path))
        self.lbl_info.configure(
            text='共 %d 个日志文件，目录：%s' % (len(self._files), core.LOG_DIR))

    def _on_pick(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._files):
            self._show(self._files[idx])

    def _set_text(self, content):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', content)
        self.text.see('end')
        self.text.configure(state='disabled')

    def _show(self, path):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                self._set_text(f.read())
            self.lbl_info.configure(text='正在查看：%s' % path)
        except OSError as exc:
            self._set_text('读取失败：%s' % exc)

    def load_current(self):
        if hasattr(self.app, 'logger') and os.path.isfile(self.app.logger.path):
            self._show(self.app.logger.path)
        else:
            self._set_text('本次会话暂无日志文件。')

    # -----------------------------------------------------------
    def cleanup(self):
        if not messagebox.askyesno(
                '确认清理',
                '将删除 %d 天以前的日志文件。\n\n是否继续？' % KEEP_DAYS):
            return

        import time
        cutoff = time.time() - KEEP_DAYS * 86400
        removed = 0
        for path in self._files:
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
        self.app.log_out('[日志清理] 已删除 %d 个过期日志。' % removed)
        messagebox.showinfo('清理完成', '已删除 %d 个过期日志文件。' % removed)
        self.refresh()

    def clear_all(self):
        """删除全部历史日志，但保留当前会话正在写入的日志文件。"""
        cur = self.app.logger.path if hasattr(self.app, 'logger') else None
        # 当前会话日志正被写入，不能删（Windows 下也删不掉）
        targets = [p for p in self._files
                   if os.path.abspath(p) != os.path.abspath(cur or '')]
        if not targets:
            messagebox.showinfo('无需清除', '没有可删除的历史日志文件。')
            return

        if not messagebox.askyesno(
                '确认清除全部',
                '将删除全部 %d 个历史日志文件（不含本次会话日志）。\n\n'
                '此操作不可撤销，是否继续？' % len(targets)):
            return

        removed = 0
        failed = 0
        for path in targets:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                failed += 1
        self.app.log_out('[日志清理] 已清除全部历史日志，共删除 %d 个文件。' % removed)
        if failed:
            self.app.log_out('[警告] 有 %d 个文件删除失败（可能被占用）。' % failed)
        messagebox.showinfo(
            '清除完成',
            '已删除 %d 个历史日志文件。%s'
            % (removed, '（%d 个失败）' % failed if failed else ''))
        self.refresh()
