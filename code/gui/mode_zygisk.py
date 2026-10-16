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
    'zygisksu': 'Zygisk 实现（NeoZygisk / Zygisk Next，框架本体）',
    'zygisk_vector': 'Vector（框架本体）',
    'zygisk-next': 'Zygisk Next（框架本体）',
    'zygisk_next': 'Zygisk Next（框架本体）',
    'vector': 'Vector（框架本体）',
    'lsposed': 'LSPosed（框架本体）',
    'shamiko': 'Shamiko（配套组件）',
    'riru': 'Riru（旧版框架）',
}


def _sleep_cancellable(ctl, seconds, step=0.2):
    """可中断等待，统一由 core 提供实现（见 core.sleep_cancellable）。"""
    return core.sleep_cancellable(ctl, seconds, step)


def _framework_label(folder):
    """若该模块属于已知框架本体，返回其标签，否则返回 None。"""
    low = folder.lower()
    # 精确匹配或"<key>_" / "<key>-" 前缀（如 zygisk_vector_xxx），
    # 不能只用 startswith(key)——'vectorized' 之类也会被误判为框架本体。
    for key, label in KNOWN_FRAMEWORKS.items():
        if low == key or low.startswith(key + '_') or low.startswith(key + '-'):
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
                  '本向导通过安全模式禁用问题模块，请严格按下述步骤操作。\n'
                  '另提供「一键激活」：临时 Root 重越狱后恢复 Zygisk 与 Xposed 框架。')

        # 步骤指引
        ui.section(inner, '崩溃排查步骤', '请严格按顺序执行，避免误卸载框架本体')
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
            row, body = ui.card(inner, accent=ui.C_ACCENT, fill=ui.C_CARD, pad=(12, 8))
            row.pack(fill='x', pady=3)
            tk.Label(body, text=title, bg=ui.C_CARD, fg=ui.C_TEXT, font=ui.FONT_BOLD,
                     anchor='w', width=18).pack(side='left')
            tk.Label(body, text=desc, bg=ui.C_CARD, fg=ui.C_MUTED,
                     font=ui.FONT_SMALL, anchor='w',
                     wraplength=520, justify='left').pack(side='left', padx=(6, 0))

        # 操作
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x', pady=(14, 8))
        ui.button(bar, '扫描全部模块', self.scan, accent=True)
        self.btn_fix = ttk.Button(bar, text='一键提权并扫描', command=self.auto_fix)
        self.btn_fix.pack(side='left', padx=(0, 8), pady=4)
        self.lbl_summary = tk.Label(bar, text='', bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT)
        self.lbl_summary.pack(side='left', padx=(8, 0))

        # ---- Zygisk / Xposed 激活（临时 Root late-load 恢复） ----
        ui.section(inner, 'Zygisk / Xposed 激活', '临时 Root 重越狱后必做')
        # 通用说明：适用于 NeoZygisk 与 Zygisk Next 两种框架。
        tk.Label(inner, text='临时 Root(late-load)重越狱后 Zygisk 注入服务不会自启，'
                             '导致 Vector / LSPosed 等框架显示「未激活」。点「一键激活」按序执行：'
                             '以正确工作目录启动注入服务（自动识别 NeoZygisk / Zygisk Next）'
                             ' → 重启 zygote 触发注入。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL,
                 anchor='w', wraplength=680, justify='left').pack(anchor='w', pady=(0, 6))

        # 分别 2 种：两框架的专用命令与注入判据不同，并列展示便于对照。
        # 二者模块 ID 同为 zygisksu（安装目录 /data/adb/modules/zygisksu），
        # 只能装其一；脚本名亦按框架区分（详见 code/tools/ 下三个脚本）。
        self._framework_notes(inner)

        act = tk.Frame(inner, bg=ui.C_PANEL)
        act.pack(fill='x')
        ui.button(act, '检测 Zygisk / Xposed 状态', self.check_zygisk)
        self.btn_activate = ttk.Button(act, text='一键激活（启动注入服务 + 重启 zygote）',
                                       command=self.activate)
        self.btn_activate.pack(side='left', padx=(0, 8), pady=4)
        self.lbl_zygisk = tk.Label(act, text='', bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT)
        self.lbl_zygisk.pack(side='left', padx=(8, 0))

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
    #  Zygisk / Vector 激活（临时 Root late-load 恢复流程）
    # -----------------------------------------------------------
    def _show_zygisk(self, text, color=None):
        if not ui.widget_alive(self.lbl_zygisk):
            return
        self.lbl_zygisk.configure(text=text, fg=color or ui.C_MUTED)

    def _framework_notes(self, parent):
        """并列展示两种 Zygisk 框架的专用命令与注入判据（分别 2 种）。

        NeoZygisk 与 Zygisk Next 模块 ID 同为 zygisksu，只能装其一；
        两者的启动命令、常驻进程、注入判据均不同，判据尤其不可通用。"""
        notes = [
            ('NeoZygisk', 'fix_neozygisk.sh',
             '启动：cd $MODDIR && ./bin/zygisk-ptrace64 monitor\n'
             '常驻进程：zygisk-ptrace64\n'
             '注入判据：grep -c libzygisk /proc/<zygote64>/maps > 0'),
            ('Zygisk Next', 'fix_zygisknext.sh',
             '启动：cd $MODDIR && ./bin/zygiskd daemon\n'
             '常驻进程：zn-nsdaemon-zygote\n'
             '注入判据：./bin/zygiskd status → zygote_states ≥ 1'),
        ]
        box = tk.Frame(parent, bg=ui.C_PANEL)
        box.pack(fill='x', pady=(0, 8))
        for name, script, detail in notes:
            col = tk.Frame(box, bg=ui.C_CARD, highlightthickness=1,
                           highlightbackground=ui.C_BORDER)
            col.pack(side='left', fill='both', expand=True, padx=(0, 8))
            tk.Label(col, text='%s · 专用' % name, bg=ui.C_CARD, fg=ui.C_TEXT,
                     font=ui.FONT_BOLD, anchor='w').pack(anchor='w', padx=10, pady=(8, 0))
            tk.Label(col, text='对应脚本：%s' % script, bg=ui.C_CARD, fg=ui.C_MUTED,
                     font=ui.FONT_SMALL, anchor='w').pack(anchor='w', padx=10)
            tk.Label(col, text=detail, bg=ui.C_CARD, fg=ui.C_MUTED,
                     font=ui.FONT_SMALL, anchor='w', justify='left',
                     wraplength=300).pack(anchor='w', padx=10, pady=(2, 8))
        tk.Label(parent, text='通用脚本 fix_zygisk.sh 会自动识别框架并分派上述命令，'
                              '无需手动选择；两框架的注入判据不可混用。',
                 bg=ui.C_PANEL, fg=ui.C_MUTED, font=ui.FONT_SMALL,
                 anchor='w', wraplength=680, justify='left').pack(anchor='w', pady=(0, 6))

    def check_zygisk(self):
        if not ui.require_adb(self.app):
            return

        def job(_ctl):
            app = self.app
            r = app.runner
            app.log_out('---------- 检测 Zygisk / Xposed 状态 ----------')
            if not core.is_root(r):
                app.log_out('[错误] 未获取 Root，请先执行模式 2 提权。')
                return None
            kind = core.detect_zygisk(r)
            label = core.ZY_LABEL.get(kind, kind)
            app.log_out('Zygisk 框架：%s' % label)
            monitor = core.zygisk_monitor_running(r, kind)
            count = core.zygisk_zygote_count(r, kind)
            injected = core.zygote_injected(r, kind)
            app.log_out('注入服务：%s' % ('运行中' if monitor else '未运行'))
            app.log_out('已接管 zygote 数量：%d' % count)
            app.log_out('zygote 注入状态：%s'
                        % ('已注入' if injected else ('未注入' if injected is False else '未知')))
            # Xposed 框架：Vector / LSPosed；isFdAttached 仅供参考。
            xp_type, xp_cli = core.detect_xposed(r)
            app.log_out('Xposed 框架：%s' % {
                core.XP_VECTOR: 'Vector',
                core.XP_LSPOSED: 'LSPosed',
                core.XP_ORIGINAL: '原版 Xposed',
                core.XP_ORIGINAL_INSTALLED: '原版 Xposed（已安装未激活）',
            }.get(xp_type, '未检测到'))
            fd = core.xposed_fd_attached(r, xp_cli)
            app.log_out('Xposed isFdAttached：%s（仅供参考，CLI 自身未挂 fd 时也会为 false）'
                        % ('true' if fd else ('false' if fd is False else '未知（未安装/未运行）')))
            return kind, label, monitor, count, injected

        def done(res):
            if res is None:
                self._show_zygisk('检测失败（需 Root）', ui.C_ERR)
                return
            kind, label, monitor, count, injected = res
            if kind == core.ZY_NONE:
                self._show_zygisk('未检测到 Zygisk 框架（NeoZygisk / Zygisk Next 均未安装）',
                                  ui.C_ERR)
                return
            if monitor and injected:
                self._show_zygisk('%s 已注入 %d 个 zygote · Zygisk 已生效' % (label, count),
                                  ui.C_OK)
            elif monitor:
                self._show_zygisk('%s 运行中，接管 %d 个 zygote · 尚未注入 zygote64'
                                  % (label, count), ui.C_WARN)
            else:
                self._show_zygisk('%s 注入服务未运行 → 框架必为「未激活」，请点「一键激活」'
                                  % label, ui.C_ERR)

        self.app.run_task(job, on_done=done, busy_text='正在检测 Zygisk / Xposed...',
                          done_text='检测完成')

    def activate(self):
        if not ui.require_adb(self.app):
            return
        if not messagebox.askyesno(
                '确认激活',
                '将按顺序执行以下操作：\n'
                '  1. 以正确工作目录启动 Zygisk 注入服务\n'
                '     （NeoZygisk → 启动 monitor；Zygisk Next → 后台化启动 zygiskd daemon）\n'
                '  2. 重启 zygote，触发注入\n\n'
                '重启 zygote 会使系统界面短暂黑屏/重启，属正常现象。\n是否继续？'):
            return

        def done(res):
            if res is None:
                self._show_zygisk('激活流程未完成', ui.C_ERR)
                return
            kind, label, monitor, count, injected = res
            if monitor and injected:
                self._show_zygisk('激活成功：%s 注入 %d 个 zygote · Zygisk 已生效'
                                  % (label, count), ui.C_OK)
            else:
                self._show_zygisk('激活后：%s %s · 接管 %d 个 · zygote64 %s'
                                  % (label,
                                     '运行中' if monitor else '未运行',
                                     count,
                                     '已注入' if injected else '未注入'), ui.C_WARN)

        self.app.run_task(self._work_activate, on_done=done,
                          busy_text='正在激活 Zygisk...', done_text='激活流程完成')

    def _work_activate(self, ctl):
        app = self.app
        r = app.runner

        app.log_out('========== Zygisk 一键激活 ==========')
        if not core.is_root(r):
            app.log_out('[错误] 未获取 Root，请先执行模式 2 提权。')
            return None

        # 先探测框架类型，后续步骤据此选择启动方式。
        kind = core.detect_zygisk(r)
        label = core.ZY_LABEL.get(kind, kind)
        if kind == core.ZY_NONE:
            app.log_out('[错误] 未检测到 Zygisk 框架（NeoZygisk / Zygisk Next 均未安装），'
                        '请先在 KernelSU 中安装对应模块。')
            return None
        app.log_out('检测到框架：%s' % label)

        # 步骤 1：以正确工作目录启动 Zygisk 注入服务
        app.log_out('[步骤1] 启动 %s 注入服务（工作目录 = 模块目录）...' % label)
        ok, msg = core.start_zygisk_daemon(r, kind)
        if ok:
            app.log_out('[成功] 启动命令已执行。')
        else:
            app.log_out('[警告] %s' % msg)
        if _sleep_cancellable(ctl, 2):
            app.log_out('[已取消] 激活流程被用户中断。')
            return None
        if core.zygisk_monitor_running(r, kind):
            proc = 'zygisk-ptrace64' if kind == core.ZY_NEO else 'zygiskd'
            app.log_out('[成功] 注入服务(%s) 已在运行。' % proc)
        else:
            app.log_out('[警告] 未检测到注入服务，后续注入可能失败；'
                        '请确认已安装 %s 模块且具备 Root。' % label)

        # 步骤 2：重启 zygote，让注入服务捕获并注入新 zygote
        app.log_out('[步骤2] 重启 zygote，触发注入...')
        if core.restart_zygote(r):
            app.log_out('[成功] zygote 已重建，注入服务应已捕获并注入新 zygote。')
        else:
            app.log_out('[警告] 未检测到 zygote64 重建（PID 未变化），注入可能未生效。')
        if _sleep_cancellable(ctl, 12):
            app.log_out('[已取消] 激活流程被用户中断。')
            return None

        # 步骤 3：复查
        app.log_out('[步骤3] 复查状态...')
        monitor = core.zygisk_monitor_running(r, kind)
        count = core.zygisk_zygote_count(r, kind)
        injected = core.zygote_injected(r, kind)
        app.log_out('%s 注入服务：%s' % (label, '运行中' if monitor else '未运行'))
        app.log_out('已接管 zygote 数量：%d' % count)
        app.log_out('zygote 注入状态：%s'
                    % ('已注入' if injected else ('未注入' if injected is False else '未知')))
        if monitor and injected:
            app.log_out('[成功] %s 已注入新 zygote，Zygisk 已生效，'
                        'Vector / LSPosed / HMA-OSS 等框架与模块将随之加载。' % label)
        else:
            app.log_out('[提示] 若仍未生效，可稍后点「检测 Zygisk / Xposed 状态」复查，'
                        '或重启手机后重新越狱再试。')
        return kind, label, monitor, count, injected

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
        exploit_cmd = core.EXPLOIT_CMD
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
            r.run(['adb', 'shell', exploit_cmd], quiet=True, timeout=40)
            if _sleep_cancellable(ctl, 3):
                app.log_out('[已取消] 一键修复被用户中断。')
                return None
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
