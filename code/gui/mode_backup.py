# -*- coding: utf-8 -*-
"""模式8：模块列表备份与恢复"""

import os
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import core
import main as ui

BACKUP_NAME = 'modules_backup.txt'


class BackupFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app
        self.backup_path = os.path.join(core.ROOT_DIR, BACKUP_NAME)

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, '模块列表备份与恢复',
                  '把当前设备的模块列表导出为文本文件，便于故障后对照排查，'
                  '也可导出到自定义位置长期留存。')

        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x')
        ui.button(bar, '备份模块列表', self.do_backup, accent=True)
        ui.button(bar, '查看备份内容', self.view_backup)
        ui.button(bar, '另存到指定位置', self.save_as)
        ui.button(bar, '刷新', self.refresh_info)

        # 备份信息
        info = tk.Frame(inner, bg='#f7f9fc', highlightbackground='#e2e5ea',
                        highlightthickness=1)
        info.pack(fill='x', pady=(14, 10))
        self.lbl_path = tk.Label(info, text='', bg='#f7f9fc', fg=ui.C_TEXT,
                                 font=ui.FONT, anchor='w', justify='left')
        self.lbl_path.pack(anchor='w', padx=12, pady=(10, 2))
        self.lbl_time = tk.Label(info, text='', bg='#f7f9fc', fg=ui.C_MUTED,
                                 font=('Microsoft YaHei UI', 9), anchor='w')
        self.lbl_time.pack(anchor='w', padx=12, pady=(0, 10))

        # 内容预览
        tk.Label(inner, text='备份内容预览', bg=ui.C_PANEL, fg=ui.C_TEXT,
                 font=ui.FONT_BOLD).pack(anchor='w')
        box = tk.Frame(inner, bg='#1e222b')
        box.pack(fill='both', expand=True, pady=(6, 0))
        self.preview = tk.Text(box, bg='#1e222b', fg='#c9d1d9', font=ui.FONT_MONO,
                               bd=0, wrap='none', state='disabled')
        vs = ttk.Scrollbar(box, orient='vertical', command=self.preview.yview)
        self.preview.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y')
        self.preview.pack(side='left', fill='both', expand=True)

        self.refresh_info()

    def on_device_change(self, st):
        self.refresh_info()

    # -----------------------------------------------------------
    def refresh_info(self):
        if os.path.isfile(self.backup_path):
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(self.backup_path))
                size = os.path.getsize(self.backup_path)
                self.lbl_path.configure(text='备份文件：%s' % self.backup_path)
                self.lbl_time.configure(
                    text='更新时间：%s    大小：%d 字节' % (
                        mtime.strftime('%Y-%m-%d %H:%M:%S'), size))
            except OSError:
                self.lbl_path.configure(text='备份文件：%s' % self.backup_path)
                self.lbl_time.configure(text='无法读取文件信息')
            self._load_preview()
        else:
            self.lbl_path.configure(text='尚未创建备份')
            self.lbl_time.configure(text='点击「备份模块列表」从设备导出')
            self._set_preview('')

    def _set_preview(self, text):
        self.preview.configure(state='normal')
        self.preview.delete('1.0', 'end')
        if text:
            self.preview.insert('end', text)
        self.preview.configure(state='disabled')

    def _load_preview(self):
        try:
            with open(self.backup_path, 'r', encoding='utf-8', errors='replace') as f:
                self._set_preview(f.read())
        except OSError as exc:
            self._set_preview('读取失败：%s' % exc)

    # -----------------------------------------------------------
    def do_backup(self):
        if not ui.require_adb(self.app):
            return
        if os.path.isfile(self.backup_path):
            if not messagebox.askyesno(
                    '覆盖备份',
                    '已存在备份文件：\n%s\n\n是否覆盖？' % self.backup_path):
                return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 备份模块列表 ----------')
            if not core.is_root(app.runner):
                app.log_out('[错误] 未获取 Root，无法读取模块列表。')
                return None
            folders = core.list_modules(app.runner)
            if not folders:
                app.log_out('[提示] 未读取到任何模块。')
            lines = []
            lines.append('# RootTool 模块列表备份')
            lines.append('# 时间：%s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            lines.append('# 设备：%s' % (core.getprop(app.runner, 'ro.product.model') or '未知'))
            lines.append('')
            for folder in folders:
                name = core.read_module_name(app.runner, folder)
                lines.append('%s\t%s' % (folder, name or ''))
                app.log_out('  %s\t%s' % (folder, name or ''))
            try:
                with open(self.backup_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(lines) + '\n')
            except OSError as exc:
                app.log_out('[错误] 写入备份失败：%s' % exc)
                return None
            app.log_out('[成功] 已备份 %d 个模块到 %s' % (len(folders), self.backup_path))
            return len(folders)

        def done(count):
            if not ui.widget_alive(self.lbl_path):
                return
            self.refresh_info()
            if count is not None:
                messagebox.showinfo('备份完成', '已备份 %d 个模块。' % count)

        self.app.run_task(job, on_done=done, busy_text='正在备份模块列表...',
                          done_text='备份完成')

    def view_backup(self):
        if not os.path.isfile(self.backup_path):
            messagebox.showinfo('无备份', '尚未创建备份文件。')
            return
        self._load_preview()

    def save_as(self):
        if not os.path.isfile(self.backup_path):
            messagebox.showinfo('无备份', '请先创建备份。')
            return
        target = filedialog.asksaveasfilename(
            title='另存模块列表备份',
            defaultextension='.txt',
            initialfile='modules_backup_%s.txt' % datetime.datetime.now().strftime('%Y%m%d'),
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if not target:
            return
        try:
            with open(self.backup_path, 'rb') as src, open(target, 'wb') as dst:
                dst.write(src.read())
            self.app.log_out('[成功] 已另存到：%s' % target)
            messagebox.showinfo('保存成功', '已保存到：\n%s' % target)
        except OSError as exc:
            messagebox.showerror('保存失败', str(exc))
