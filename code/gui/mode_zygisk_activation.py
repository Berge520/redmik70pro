# -*- coding: utf-8 -*-
"""Zygisk / Xposed 激活（临时 Root late-load 恢复流程）。

从 mode_zygisk.py 拆出的独立能力块：以 ZygiskActivationMixin 形式提供
"检测状态 / 一键激活 / 按序启动注入服务 + 重启 zygote" 的 UI 与逻辑，
由 ZygiskFrame 直接继承。依赖约定：宿主类需提供 `self.app`（含 runner /
log_out / run_task）以及 `self.lbl_zygisk`（状态标签）。

拆出目的：mode_zygisk.py 兼有「崩溃修复向导」与「框架激活」两条职责，
二者互不相关，分文件后单文件更短、职责更单一。
"""

import tkinter as tk
from tkinter import ttk

import core
import main as ui

# 复用 core 的可中断等待，避免各模式各自包装。
_sleep_cancellable = core.sleep_cancellable


class ZygiskActivationMixin:
    """为 ZygiskFrame 提供「Zygisk / Xposed 激活」相关方法。"""

    # -----------------------------------------------------------
    #  Zygisk / Vector 激活（临时 Root late-load 恢复流程）
    # -----------------------------------------------------------
    def _build_activation(self, inner):
        """构建「Zygisk / Xposed 激活」区块控件。"""
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
        if not ui.confirm(
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
