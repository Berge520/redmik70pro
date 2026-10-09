# -*- coding: utf-8 -*-
"""模式1：设备状态检测"""

import tkinter as tk
from tkinter import ttk

import core
import main as ui


class StatusFrame(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=ui.C_BG)
        self.app = app

        p = ui.panel(self)
        p.pack(fill='both', expand=True, padx=1, pady=1)
        inner = tk.Frame(p, bg=ui.C_PANEL)
        inner.pack(fill='both', expand=True, padx=14, pady=12)

        ui.header(inner, '设备状态检测',
                  '读取型号、Android 版本、SDK、活动槽位、SELinux 状态，'
                  '并多方式探测 Root 与 KernelSU 是否已加载。')
        bar = tk.Frame(inner, bg=ui.C_PANEL)
        bar.pack(fill='x', pady=(0, 4))
        ui.button(bar, '开始检测', self.start, accent=True)
        ui.button(bar, '刷新设备连接', self.refresh_all)

        # 结果表
        style = ttk.Style()
        style.configure('Status.Treeview', font=ui.FONT, rowheight=27)
        cols = ('item', 'value', 'note')
        self.tree = ttk.Treeview(inner, columns=cols, show='headings',
                                 style='Status.Treeview', height=10)
        self.tree.heading('item', text='检测项')
        self.tree.heading('value', text='结果')
        self.tree.heading('note', text='判断依据 / 说明')
        # 前两列固定宽度（stretch=False），最后一列吸收剩余空间。
        # 若全部 stretch=True，Tk 会按比例拉伸并插入多余空白列，导致错位。
        self.tree.column('item', width=140, minwidth=110, anchor='w', stretch=False)
        self.tree.column('value', width=240, minwidth=140, anchor='w', stretch=False)
        self.tree.column('note', width=370, minwidth=180, anchor='w', stretch=True)

        vsb = ttk.Scrollbar(inner, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y', pady=(12, 0))
        self.tree.pack(side='left', fill='both', expand=True, pady=(12, 0))

        self.tree.tag_configure('ok', foreground=ui.C_OK)
        self.tree.tag_configure('bad', foreground=ui.C_ERR)
        self.tree.tag_configure('warn', foreground=ui.C_WARN)

    def on_device_change(self, st):
        # 进入本模式时自动检测。若已有缓存结果则直接复用，
        # 避免每次切换模式都重跑一遍完整检测（约 1~2 秒）。
        cached = self.app.mode_cache.get('status')
        if cached:
            self._render(cached)
            self.app.log_out('[提示] 已恢复上次检测结果，点「开始检测」可重新读取。')
            return
        self.start(silent=True)

    def refresh_all(self):
        """刷新设备连接，并在有新设备时重新检测。"""
        self.app.refresh_devices()
        if self.app.device.any:
            self.start(silent=True)

    def _reset(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _add(self, item, value, note='', tag=''):
        self.tree.insert('', 'end', values=(item, value, note), tags=(tag,) if tag else ())

    # -----------------------------------------------------------
    def start(self, silent=False):
        if not self.app.device.any:
            if silent:
                # 自动触发时不弹窗，直接给出空表提示
                self._render([])
                self.app.log_out('[提示] 未检测到设备，请连接手机后点击「刷新设备连接」。')
                return
            if not tk.messagebox.askyesno(
                    '未检测到设备',
                    '当前未检测到 ADB 或 Fastboot 设备。\n是否仍然尝试检测？'):
                return
        self.app.run_task(self._work, on_done=self._render,
                          busy_text='正在检测设备状态...',
                          done_text='状态检测完成')

    def _render(self, rows):
        """在主线程渲染检测结果（Tk 控件只能在主线程操作）。"""
        # 任务结束时可能已切换模式，控件被销毁则直接放弃本次渲染。
        if not ui.widget_alive(self.tree):
            return
        self._reset()
        for item, value, note, tag in (rows or []):
            self._add(item, value, note, tag)
        if rows:
            self.app.mode_cache['status'] = list(rows)

    def _work(self, ctl):
        """在后台线程收集检测结果，返回行列表，不触碰任何控件。"""
        r = self.app.runner
        st = self.app.device
        rows = []

        if st.adb:
            self.app.log_out('========== [ADB 设备信息] ==========')
            model = core.getprop(r, 'ro.product.model')
            release = core.getprop(r, 'ro.build.version.release')
            sdk = core.getprop(r, 'ro.build.version.sdk')
            slot = core.getprop(r, 'ro.boot.slot_suffix')
            selinux = r.shell('getenforce', quiet=True, timeout=15).first()

            self.app.log_out('型号：%s' % (model or '未知'))
            self.app.log_out('Android 版本：%s' % (release or '未知'))
            self.app.log_out('SDK 版本：%s' % (sdk or '未知'))
            self.app.log_out('当前活动槽：%s' % (slot or '（非 A/B 分区设备）'))
            self.app.log_out('SELinux：%s' % (selinux or '未知'))

            rows.append(('设备型号', model or '未知', '', ''))
            rows.append(('Android 版本', release or '未知', '', ''))
            rows.append(('SDK 版本', sdk or '未知', '', ''))
            rows.append(('当前活动槽', slot or '（非 A/B）', '', ''))
            rows.append(('SELinux 状态', selinux or '未知',
                         'Permissive 表示宽松模式',
                         'warn' if selinux == 'Permissive' else 'ok'))

            # Root
            self.app.log_out('---------- Root 状态探测 ----------')
            status, method, tag = self._probe_root(r)
            rows.append(('Root 状态', status, method, tag))
            self.app.log_out('Root 状态：%s（%s）' % (status, method))

            # KernelSU
            self.app.log_out('---------- KernelSU 探测 ----------')
            kstatus, kmethod, ktag = self._probe_ksu(r)
            rows.append(('KernelSU', kstatus, kmethod, ktag))
            self.app.log_out('KernelSU：%s（%s）' % (kstatus, kmethod))
        else:
            rows.append(('ADB', '未连接', '请连接手机并开启 USB 调试', 'bad'))
            self.app.log_out('[ADB] 未连接')

        if st.fastboot:
            self.app.log_out('========== [Fastboot 设备信息] ==========')
            rows.extend(self._probe_fastboot(r))
        else:
            rows.append(('Fastboot', '未连接', '', 'bad'))

        if not st.any:
            self.app.log_out('[提示] 未检测到任何设备，请连接手机并进入 ADB 或 Fastboot 模式。')

        self.app.log_out('===================================')
        return rows

    def _probe_root(self, r):
        if r.su('echo 1', quiet=True, timeout=15).ok:
            return '已获取', 'su 命令生效', 'ok'
        if r.su('id', quiet=True, timeout=15).ok:
            return '已获取', 'su 命令生效', 'ok'
        if 'uid=0' in r.shell('id', quiet=True, timeout=15).text:
            return '已获取', '当前 shell 为 root', 'ok'
        if r.shell('test -x /data/adb/ksud', quiet=True, timeout=15).ok:
            return '已获取（疑似 LKM）', '/data/adb/ksud 存在', 'ok'
        if 'kernelsu' in r.shell('ls /sys/module/', quiet=True, timeout=15).text.lower():
            return '已获取（LKM 模式）', '内核模块 kernelsu 已加载', 'ok'
        sel = r.shell('getenforce', quiet=True, timeout=15).first()
        if sel.lower() == 'permissive':
            return '可能已获取（需确认）', 'SELinux 处于 Permissive', 'warn'
        return '未获取', '以上方式均未通过', 'bad'

    def _probe_ksu(self, r):
        if 'me.weishu.kernelsu' in r.shell('pm list packages', quiet=True, timeout=20).text:
            return '已安装（管理器存在）', '检测到包 me.weishu.kernelsu', 'ok'
        if r.shell('test -x /data/adb/ksud', quiet=True, timeout=15).ok:
            return '已加载（LKM 模式）', '/data/adb/ksud 存在', 'ok'
        if 'kernelsu' in r.shell('ls /sys/module/', quiet=True, timeout=15).text.lower():
            return '已加载（内核模块）', '内核模块 kernelsu 已加载', 'ok'
        if r.shell('test -d /data/adb', quiet=True, timeout=15).ok:
            return '疑似已加载（目录存在）', '/data/adb 目录存在', 'warn'
        return '未检测到', '', 'bad'

    def _probe_fastboot(self, r):
        """探测 Fastboot 信息，返回行列表（后台线程，不触碰控件）。"""
        rows = []
        res = r.run(['fastboot', 'getvar', 'all'], quiet=True, timeout=30)
        wanted = {
            'product': '产品型号',
            'unlocked': '解锁状态',
            'current-slot': '当前槽位',
            'secure': '安全启动',
        }
        found = {}
        for line in res.lines:
            if ':' not in line:
                continue
            key, _, val = line.partition(':')
            key = key.strip().lower()
            # fastboot 每行形如 "(bootloader) product:manet"，前缀带空格，
            # 剥掉 "(xxx)" 后必须再 strip 一次，否则会得到 "(bootloader) product"
            # 这种带前缀的键，永远匹配不上 wanted。
            if ')' in key:
                key = key.rsplit(')', 1)[-1].strip()
            if key in wanted:
                found[key] = val.strip()

        if not found:
            rows.append(('Fastboot 信息', '读取失败',
                         '请确认设备处于 Fastboot 模式且驱动正常', 'bad'))
            self.app.log_out('[Fastboot] getvar 未返回预期字段，请检查驱动。')
            return rows

        for key, label in wanted.items():
            val = found.get(key, '')
            if val:
                rows.append((label, val, '', ''))
                self.app.log_out('%s：%s' % (label, val))
        return rows
