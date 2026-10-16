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

        # 结果表：前两列固定宽度（不拉伸），最后一列吸收剩余空间。
        # 若全部拉伸，Tk 会按比例拉伸并插入多余空白列，导致错位。
        cols = ('item', 'value', 'note')
        box, self.tree = ui.tree3(
            inner, cols, ('检测项', '结果', '判断依据 / 说明'),
            ((140, 110, 'w'), (240, 140, 'w'), (370, 180, 'w')),
            height=10, style='Status.Treeview')
        box.pack(fill='both', expand=True, pady=(12, 0))

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
        """刷新设备连接，并在刷新完成后按最新状态决定是否重新检测。

        refresh_devices 是异步的，调用后 self.app.device 还是旧值，
        直接读取会用到过期状态，因此把后续判断放进 on_done 回调。
        """
        def after_refresh(st):
            if st is None:
                return
            if st.any:
                self.start(silent=True)
            elif st.adb_devices or st.fastboot_devices:
                # 手机插上了但未授权/离线：明确告知，避免"连了却检测不到"的困惑。
                self.app.log_out('[提示] %s' % st.describe())
                msg = ('已检测到设备，但尚未就绪：\n%s\n\n'
                       '· 若状态为 unauthorized：请在手机上点击「允许 USB 调试」后重试。\n'
                       '· 若状态为 offline：请重新插拔数据线或执行 adb kill-server。'
                       % st.describe())
                tk.messagebox.showwarning('设备未就绪', msg)
            else:
                self.app.log_out('[提示] 未检测到设备，请连接手机并开启 USB 调试。')

        self.app.refresh_devices(on_done=after_refresh)

    def _reset(self):
        for i in self.tree.get_children():
            self.tree.delete(i)

    def _add(self, item, value, note='', tag=''):
        self.tree.insert('', 'end', values=(item, value, note), tags=(tag,) if tag else ())

    # -----------------------------------------------------------
    def start(self, silent=False):
        if not self.app.device.any:
            if silent:
                # 自动触发时不弹窗。若此时设备扫描仍在进行（启动阶段常见），
                # 说明只是还没扫完，不要误报"未检测到设备"——扫描结束后
                # _apply_devices 会再次触发 on_device_change 重新检测。
                if getattr(self.app, '_dev_scanning', False):
                    self._render([])
                    self.app.log_out('[提示] 正在检测设备，请稍候…')
                    return
                # 扫描确已完成且无设备，给出空表提示
                self._render([])
                self.app.log_out('[提示] 未检测到设备，请连接手机后点击「刷新设备连接」。')
                return
            if not ui.confirm(
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
            selinux = r.shell('getenforce', quiet=True, timeout=15).first().strip()

            self.app.log_out('型号：%s' % (model or '未知'))
            self.app.log_out('Android 版本：%s' % (release or '未知'))
            self.app.log_out('SDK 版本：%s' % (sdk or '未知'))
            self.app.log_out('当前活动槽：%s' % (slot or '（非 A/B 分区设备）'))
            self.app.log_out('SELinux：%s' % (selinux or '未知'))

            rows.append(('设备型号', model or '未知', '', ''))
            rows.append(('Android 版本', release or '未知', '', ''))
            rows.append(('SDK 版本', sdk or '未知', '', ''))
            if slot:
                rows.append(('当前活动槽', slot, 'A/B 分区设备的活动槽位', 'ok'))
            else:
                rows.append(('当前活动槽', '非 A/B 设备',
                             '未读取到 ro.boot.slot_suffix', ''))
            is_perm = selinux.lower() == 'permissive'
            rows.append(('SELinux 状态', selinux or '未知',
                         'Permissive 表示宽松模式，Enforcing 为强制模式',
                         'warn' if is_perm else ('ok' if selinux else '')))

            # Root（多方式探测，并附明细）
            self.app.log_out('---------- Root 状态探测 ----------')
            status, method, tag, detail = core.probe_root(r)
            rows.append(('Root 状态', status, method, tag))
            self.app.log_out('Root 状态：%s（%s）' % (status, method))
            for name, result, hit in detail:
                rows.append(('　└ 探测方式：%s' % name,
                             '命中' if hit else '未命中',
                             result, 'ok' if hit else ''))
                self.app.log_out('  [%s] %s：%s' % ('命中' if hit else '未命中', name, result))

            # KernelSU（多方式探测，并附明细）
            self.app.log_out('---------- KernelSU 探测 ----------')
            kstatus, kmethod, ktag, kdetail = core.probe_ksu(r)
            rows.append(('KernelSU', kstatus, kmethod, ktag))
            self.app.log_out('KernelSU：%s（%s）' % (kstatus, kmethod))
            for name, result, hit in kdetail:
                rows.append(('　└ 探测方式：%s' % name,
                             '命中' if hit else '未命中',
                             result, 'ok' if hit else ''))
                self.app.log_out('  [%s] %s：%s' % ('命中' if hit else '未命中', name, result))
        else:
            if st.adb_devices:
                states = '、'.join('%s(%s)' % (sn, s) for sn, s in st.adb_devices)
                rows.append(('ADB', '设备未就绪', '%s；请在手机上允许 USB 调试' % states, 'bad'))
                self.app.log_out('[ADB] 检测到设备但未就绪：%s' % states)
            else:
                rows.append(('ADB', '未连接', '请连接手机并开启 USB 调试', 'bad'))
                self.app.log_out('[ADB] 未连接')

        if st.fastboot:
            self.app.log_out('========== [Fastboot 设备信息] ==========')
            rows.extend(self._probe_fastboot(r))
        else:
            rows.append(('Fastboot', '未连接', '', 'bad'))

        if not st.any:
            self.app.log_out('[提示] %s' % st.describe())

        self.app.log_out('===================================')
        return rows

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
