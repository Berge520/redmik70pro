# -*- coding: utf-8 -*-
"""模式6：Zygisk 崩溃修复向导"""

import time
import tkinter as tk
from tkinter import ttk, messagebox

import core
import main as ui

# 常见导致 Zygisk 崩溃的模块关键字
SUSPECT_KEYS = ('zygisk', 'zygisknext', 'lsposed', 'shamiko', 'riru')

# 已知的 Zygisk 框架本体，属于正常运行组件而非崩溃元凶。
# 命中这些时标注为「框架本体」，避免被误当成可疑模块卸载。
KNOWN_FRAMEWORKS = {
    'zygisksu': 'Zygisk Next（框架本体）',
    'zygisk_vector': 'Vector（框架本体）',
    'zygisk-next': 'Zygisk Next（框架本体）',
    'vector': 'Vector（框架本体）',
    'lsposed': 'LSPosed（框架本体）',
    'shamiko': 'Shamiko（配套组件）',
    'riru': 'Riru（旧版框架）',
}


def _framework_label(folder):
    """若该模块属于已知框架本体，返回其标签，否则返回 None。"""
    low = folder.lower()
    for key, label in KNOWN_FRAMEWORKS.items():
        if low == key or low.startswith(key):
            return label
    return None


def classify_module(folder, name):
    """对一个模块分类，返回 (状态, 说明)。

    状态取值：'可疑' / '框架本体' / '正常'。
    name 为该模块的显示名，也参与关键字匹配（有些模块文件夹名很普通，
    但描述里带 zygisk 字样）。"""
    fw = _framework_label(folder)
    if fw:
        return '框架本体', fw
    low = folder.lower() + ' ' + (name or '').lower()
    for key in SUSPECT_KEYS:
        if key in low:
            return '可疑', '名称含 %s，疑似冲突' % key
    return '正常', '未命中可疑关键字'


class ZygiskFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, 'Zygisk 崩溃修复向导',
                  'Zygisk / ZygiskNext 等模块异常会导致应用启动即闪退、甚至开机变砖。\n'
                  '本向导通过安全模式禁用问题模块，请严格按下述步骤操作。')

        # 步骤指引
        steps = [
            ('① 重启进入安全模式',
             '让手机重启，在开机出现品牌 Logo 时长按音量键进入系统安全模式。'),
            ('② 连接电脑并提权',
             '进入安全模式后连接 USB，先执行模式 2（ADB 直连提权）获取 Root。'),
            ('③ 定位并卸载问题模块',
             '点击下方「扫描全部模块」，列表中「可疑」项为冲突嫌疑，「框架本体」请勿卸载。'),
            ('④ 重启恢复',
             '卸载完成后重启手机退出安全模式，验证应用是否恢复正常。'),
        ]
        for title, desc in steps:
            row = tk.Frame(inner, bg='#f7f9fc', highlightbackground='#e2e5ea',
                           highlightthickness=1)
            row.pack(fill='x', pady=3)
            tk.Label(row, text=title, bg='#f7f9fc', fg=ui.C_TEXT, font=ui.FONT_BOLD,
                     anchor='w', width=18).pack(side='left', padx=(12, 0), pady=9)
            tk.Label(row, text=desc, bg='#f7f9fc', fg=ui.C_MUTED,
                     font=('Microsoft YaHei UI', 9), anchor='w',
                     wraplength=520, justify='left').pack(side='left', padx=(6, 12), pady=9)

        # 操作
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x', pady=(14, 8))
        ui.button(bar, '扫描全部模块', self.scan, accent=True)
        self.btn_fix = ttk.Button(bar, text='一键提权并扫描', command=self.auto_fix)
        self.btn_fix.pack(side='left', padx=(0, 8), pady=4)
        self.lbl_summary = tk.Label(bar, text='', bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT)
        self.lbl_summary.pack(side='left', padx=(8, 0))

        tk.Label(inner, text='全部模块（状态说明：可疑 = 名称含 %s，建议卸载；框架本体 = 运行必需，请勿卸载）'
                 % '、'.join(SUSPECT_KEYS),
                 bg=ui.C_PANEL, fg=ui.C_TEXT, font=ui.FONT_BOLD).pack(anchor='w')

        self.tree = ttk.Treeview(inner, columns=('status', 'folder', 'name', 'reason'),
                                 show='headings', height=9)
        self.tree.heading('status', text='状态')
        self.tree.heading('folder', text='模块文件夹名')
        self.tree.heading('name', text='显示名称')
        self.tree.heading('reason', text='说明')
        # 状态列窄且固定，文件夹名固定，显示名称与说明按需拉伸，
        # 避免默认 stretch=True 让列被拉错位。
        self.tree.column('status', width=80, minwidth=70, anchor='center', stretch=False)
        self.tree.column('folder', width=180, minwidth=130, anchor='w', stretch=False)
        self.tree.column('name', width=230, minwidth=140, anchor='w', stretch=False)
        self.tree.column('reason', width=330, minwidth=160, anchor='w', stretch=True)
        vsb = ttk.Scrollbar(inner, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y', pady=(6, 0))
        self.tree.pack(side='left', fill='both', expand=True, pady=(6, 0))
        # 状态列配色：可疑=红，框架本体=绿，正常=灰
        self.tree.tag_configure('suspect', foreground=ui.C_ERR)
        self.tree.tag_configure('framework', foreground=ui.C_OK)
        self.tree.tag_configure('normal', foreground=ui.C_MUTED)

    def on_device_change(self, st):
        if not st.adb:
            return
        cached = self.app.mode_cache.get('zygisk')
        if cached is not None:
            self._apply_hits(cached)
            self.app.log_out('[提示] 已恢复上次扫描结果，点「扫描全部模块」可重新扫描。')
            return
        self.scan()

    # -----------------------------------------------------------
    def scan(self):
        if not ui.require_adb(self.app):
            return

        def job(_ctl):
            app = self.app
            app.log_out('---------- 扫描全部模块 ----------')
            if not core.is_root(app.runner):
                app.log_out('[错误] 未获取 Root，请先在安全模式下执行模式 2 提权。')
                return None
            rows, suspects = self._collect(app.runner, app)
            app.log_out('设备共 %d 个模块，其中可疑 %d 个。' % (len(rows), len(suspects)))
            return rows

        def done(rows):
            if rows is not None:
                self._apply_hits(rows)
                self.app.mode_cache['zygisk'] = list(rows)

        self.app.run_task(job, on_done=done, busy_text='正在扫描全部模块...',
                          done_text='扫描完成')

    def _collect(self, runner, app=None):
        """遍历全部模块并分类，返回 (rows, suspects)。

        rows: [(status, folder, name, reason)]，供表格渲染。
        app 非空时同步输出分类明细到日志。"""
        folders = core.list_modules(runner)
        rows, suspects, frameworks = [], [], []
        for folder in folders:
            name = core.read_module_name(runner, folder)
            status, reason = classify_module(folder, name)
            rows.append((status, folder, name or '', reason))
            if status == '可疑':
                suspects.append((folder, name, reason))
                if app:
                    app.log_out('  [可疑] %s  (%s) —— %s' % (folder, name or '无描述', reason))
            elif status == '框架本体':
                frameworks.append(folder)
        # 排序：可疑排最前，其次框架本体，最后正常；同类保持文件夹名顺序
        order = {'可疑': 0, '框架本体': 1, '正常': 2}
        rows.sort(key=lambda r: (order[r[0]], r[1].lower()))
        if app:
            if frameworks:
                app.log_out('  [正常] 框架本体：%s（运行必需，请勿卸载）' % '、'.join(frameworks))
            if not suspects:
                app.log_out('未发现名称可疑的模块，请人工核对下方完整列表。')
        return rows, suspects

    def auto_fix(self):
        if not ui.require_adb(self.app):
            return
        if not messagebox.askyesno(
                '确认一键修复',
                '将执行：\n'
                '  1. 推送 ksud 并尝试提权\n'
                '  2. 扫描全部模块\n\n'
                '注意：本操作不会自动卸载模块，卸载仍需你确认后手动执行。\n是否继续？'):
            return

        def done(rows):
            if rows is not None:
                self._apply_hits(rows)
                self.app.mode_cache['zygisk'] = list(rows)

        self.app.run_task(self._work_auto, on_done=done,
                          busy_text='正在提权并扫描...', done_text='一键处理完成')

    def _work_auto(self, ctl):
        from mode_adb import EXPLOIT_CMD
        app = self.app
        r = app.runner

        app.log_out('========== Zygisk 修复：自动提权 ==========')
        ksud = core.find_ksud()
        if not ksud:
            app.log_out('[错误] 找不到 ksud 文件。')
            return None

        if core.is_root(r):
            app.log_out('已具备 Root 权限，跳过错位提权。')
        else:
            app.log_out('[步骤1] 推送 ksud...')
            if not r.run(['adb', 'push', ksud, '/data/local/tmp/'],
                         quiet=True, timeout=90).ok:
                app.log_out('[错误] adb push 失败。')
                return None
            r.shell('chmod 777 /data/local/tmp/ksud', quiet=True, timeout=20)

            app.log_out('[步骤2] 执行漏洞提权...')
            r.run(['adb', 'shell', EXPLOIT_CMD], quiet=True, timeout=40)
            time.sleep(3)
            if core.is_root(r):
                app.log_out('[成功] 已获取 Root。')
            else:
                app.log_out('[!] 尚未获得 Root，请确认已在安全模式下并已授权调试。')

        app.log_out('[步骤3] 扫描全部模块...')
        rows, suspects = self._collect(r, app)
        app.log_out('设备共 %d 个模块，其中可疑 %d 个。' % (len(rows), len(suspects)))
        return rows

    def _apply_hits(self, rows):
        # 任务跑完时用户可能已切到别的模式，本 frame 连同 tree 已被销毁。
        # 此时再访问会抛 invalid command name，需先确认控件仍存活。
        if not ui.widget_alive(self.tree):
            return
        for i in self.tree.get_children():
            self.tree.delete(i)
        counts = {'可疑': 0, '框架本体': 0, '正常': 0}
        for row in rows:
            status, folder, name, reason = row
            counts[status] = counts.get(status, 0) + 1
            tag = {'可疑': 'suspect', '框架本体': 'framework'}.get(status, 'normal')
            self.tree.insert('', 'end',
                             values=(status, folder, name or '（无描述）', reason),
                             tags=(tag,))
        self.lbl_summary.configure(
            text='共 %d 个：可疑 %d · 框架本体 %d · 正常 %d'
                 % (len(rows), counts['可疑'], counts['框架本体'], counts['正常']),
            fg=ui.C_ERR if counts['可疑'] else ui.C_MUTED)
