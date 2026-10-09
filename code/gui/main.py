# -*- coding: utf-8 -*-
"""
RootTool 图形界面主窗口
Tkinter 实现，零第三方依赖。左侧模式导航，右侧功能面板，底部实时日志。
"""

import os
import sys
import time
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402

# 版本号集中在 core 中定义，避免多处硬编码导致漂移。
APP_TITLE = core.APP_TITLE
APP_GEOMETRY = '1080x720'
APP_MIN = (900, 620)

# 配色
C_BG = '#f4f5f7'
C_PANEL = '#ffffff'
C_SIDE = '#2b2f3a'
C_SIDE_HOVER = '#3a4050'
C_SIDE_ACTIVE = '#4a90d9'
C_TEXT = '#22262e'
C_MUTED = '#7a8290'
C_OK = '#2e9e5b'
C_WARN = '#d9822b'
C_ERR = '#d94b4b'
C_ACCENT = '#4a90d9'

FONT = ('Microsoft YaHei UI', 10)
FONT_BOLD = ('Microsoft YaHei UI', 10, 'bold')
FONT_TITLE = ('Microsoft YaHei UI', 14, 'bold')
FONT_MONO = ('Consolas', 9)

# 侧栏模式定义：(key, 标题, 说明)
MODES = [
    ('status', '1. 设备状态检测', '型号/版本/Root/SELinux/槽位'),
    ('adb', '2. ADB 直连提权', '依赖设备已开启调试'),
    ('fastboot', '3. Fastboot 分区提权', '分步或一键流程'),
    ('selinux', '4. SELinux 模式切换', '宽松 / 强制'),
    ('modules', '5. Root 模块管理', '查看 / 禁用 / 启用 / 卸载模块'),
    ('zygisk', '6. Zygisk 崩溃修复', '应用变砖恢复向导'),
    ('safemode', '7. KernelSU 安全模式自救', '自动 / 手动'),
    ('backup', '8. 模块列表备份恢复', '导出 / 查看'),
    ('log', '9. 查看运行日志', '本次与历史日志'),
    ('xposed', '10. Xposed 模块管理', '查询 / 禁用 / 启用'),
    ('reboot', '11. 重启控制', '软重启 / 完整重启 / 关机'),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(APP_GEOMETRY)
        self.minsize(*APP_MIN)
        self.configure(bg=C_BG)

        self._ui_queue = queue.Queue()
        self._busy = False
        self._current_key = None
        self._frames = {}
        self._last_device_sig = None
        self._task_started = 0.0
        self._current_task = None
        # 各模式的检测结果缓存，切换模式回来时可秒开
        self.mode_cache = {}

        self.logger = core.Logger(sink=self._queue_log)
        self.runner = core.Runner(logger=self.logger, emit=self._queue_out)
        self.device = core.DeviceState()

        self._build_style()
        self._build_layout()
        self._pump_queue()

        self.logger.write('===== 图形界面启动 =====')
        self.logger.write('工具目录：%s' % core.ROOT_DIR)
        self._run_preflight()
        self.set_status('正在检测设备...')
        self.refresh_devices(initial=True)
        # 启动即渲染第一个模式，避免内容区空白等待用户点击
        self.show_mode(MODES[0][0])

    def _run_preflight(self):
        """启动自检：缺少 adb/fastboot/ksud 时明确告知，而不是静默失败。"""
        ok, problems = core.preflight()
        if ok:
            self.logger.write('自检通过：adb / fastboot / ksud 均已就绪。')
            return
        for p in problems:
            self.logger.write('[警告] ' + p)
        messagebox.showwarning(
            '环境自检未通过',
            '检测到以下问题，部分功能将不可用：\n\n· ' + '\n· '.join(problems) +
            '\n\n请把缺失文件放入工具目录：\n%s' % core.ROOT_DIR)

    # -----------------------------------------------------------
    #  样式
    # -----------------------------------------------------------
    def _build_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use('clam')
        except tk.TclError:
            pass
        st.configure('TFrame', background=C_BG)
        st.configure('Panel.TFrame', background=C_PANEL)
        st.configure('TLabel', background=C_BG, foreground=C_TEXT, font=FONT)
        st.configure('Panel.TLabel', background=C_PANEL, foreground=C_TEXT, font=FONT)
        st.configure('Title.TLabel', background=C_PANEL, foreground=C_TEXT, font=FONT_TITLE)
        st.configure('Muted.TLabel', background=C_PANEL, foreground=C_MUTED, font=FONT)
        st.configure('TButton', font=FONT, padding=(10, 6))
        st.configure('Accent.TButton', font=FONT_BOLD, padding=(10, 7))
        st.configure('TCheckbutton', background=C_PANEL, font=FONT)
        st.configure('TLabelframe', background=C_PANEL, font=FONT_BOLD)
        st.configure('TLabelframe.Label', background=C_PANEL, foreground=C_TEXT, font=FONT_BOLD)
        st.configure('Treeview', font=FONT, rowheight=26)
        st.configure('Treeview.Heading', font=FONT_BOLD)

    # -----------------------------------------------------------
    #  整体布局
    # -----------------------------------------------------------
    def _build_layout(self):
        # 顶部状态栏
        self._build_header()

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill='both', expand=True, padx=10, pady=(0, 6))

        # 左侧导航
        side = tk.Frame(body, bg=C_SIDE, width=228)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        self._build_sidebar(side)

        # 右侧内容区
        right = tk.Frame(body, bg=C_BG)
        right.pack(side='left', fill='both', expand=True, padx=(8, 0))

        self.content = tk.Frame(right, bg=C_BG)
        self.content.pack(fill='both', expand=True)

        # 底部日志
        self._build_logpanel(right)

    def _build_header(self):
        head = tk.Frame(self, bg=C_SIDE, height=52)
        head.pack(fill='x')
        head.pack_propagate(False)

        tk.Label(head, text=APP_TITLE, bg=C_SIDE, fg='#ffffff',
                 font=('Microsoft YaHei UI', 13, 'bold')).pack(side='left', padx=16)

        # 设备状态指示
        self.lbl_adb = tk.Label(head, text='● ADB 未连接', bg=C_SIDE, fg='#8b93a3', font=FONT)
        self.lbl_adb.pack(side='right', padx=(0, 16))
        self.lbl_fb = tk.Label(head, text='● Fastboot 未连接', bg=C_SIDE, fg='#8b93a3', font=FONT)
        self.lbl_fb.pack(side='right', padx=(0, 16))
        self.lbl_admin = tk.Label(
            head, text='管理员' if core.is_admin() else '普通用户',
            bg=C_SIDE, fg=C_OK if core.is_admin() else C_WARN, font=FONT)
        self.lbl_admin.pack(side='right', padx=(0, 16))

        tk.Button(head, text='刷新设备', command=self.refresh_devices,
                  bg='#3a4050', fg='#ffffff', activebackground='#4a5060',
                  activeforeground='#ffffff', bd=0, font=FONT,
                  padx=12, pady=4, cursor='hand2').pack(side='right', padx=(0, 10))

    def _build_sidebar(self, parent):
        tk.Label(parent, text='功能模式', bg=C_SIDE, fg='#8b93a3',
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', padx=16, pady=(14, 6))

        self._nav_buttons = {}
        for key, title, _desc in MODES:
            btn = tk.Frame(parent, bg=C_SIDE, cursor='hand2')
            btn.pack(fill='x')
            lbl = tk.Label(btn, text=title, bg=C_SIDE, fg='#d6dae2',
                           font=FONT, anchor='w', padx=16, pady=9)
            lbl.pack(fill='x')
            lbl.bind('<Button-1>', lambda e, k=key: self.show_mode(k))
            btn.bind('<Button-1>', lambda e, k=key: self.show_mode(k))
            lbl.bind('<Enter>', lambda e, w=lbl: self._nav_hover(w, True))
            lbl.bind('<Leave>', lambda e, w=lbl: self._nav_hover(w, False))
            self._nav_buttons[key] = lbl

        # 退出
        tk.Frame(parent, bg=C_SIDE, height=1).pack(fill='x', pady=(12, 0))
        quit_lbl = tk.Label(parent, text='退出', bg=C_SIDE, fg='#d6dae2',
                            font=FONT, anchor='w', padx=16, pady=9, cursor='hand2')
        quit_lbl.pack(fill='x')
        quit_lbl.bind('<Button-1>', lambda e: self.on_close())
        quit_lbl.bind('<Enter>', lambda e: quit_lbl.configure(bg=C_SIDE_HOVER))
        quit_lbl.bind('<Leave>', lambda e: quit_lbl.configure(bg=C_SIDE))

    def _nav_hover(self, widget, entering):
        if widget.cget('bg') == C_SIDE_ACTIVE:
            return
        widget.configure(bg=C_SIDE_HOVER if entering else C_SIDE)

    def _build_logpanel(self, parent):
        wrap = tk.Frame(parent, bg=C_BG)
        wrap.pack(fill='both', expand=False, pady=(8, 0))

        bar = tk.Frame(wrap, bg=C_BG)
        bar.pack(fill='x')
        tk.Label(bar, text='实时日志', bg=C_BG, fg=C_TEXT, font=FONT_BOLD).pack(side='left')
        self.lbl_busy = tk.Label(bar, text='', bg=C_BG, fg=C_ACCENT, font=FONT_BOLD)
        self.lbl_busy.pack(side='left', padx=(10, 0))
        self.btn_cancel = ttk.Button(bar, text='取消', command=self.cancel_task)
        self.btn_cancel.pack(side='left', padx=(10, 0))
        self.btn_cancel.state(['disabled'])
        self.lbl_status = tk.Label(bar, text='就绪', bg=C_BG, fg=C_MUTED, font=FONT)
        self.lbl_status.pack(side='left', padx=8)
        tk.Button(bar, text='清空', command=self.clear_log, bd=0, font=FONT,
                  bg=C_BG, fg=C_ACCENT, activebackground=C_BG,
                  cursor='hand2').pack(side='right')
        tk.Button(bar, text='打开日志目录', command=self.open_log_dir, bd=0, font=FONT,
                  bg=C_BG, fg=C_ACCENT, activebackground=C_BG,
                  cursor='hand2').pack(side='right', padx=8)

        box = tk.Frame(wrap, bg='#1e222b', height=176)
        box.pack(fill='both', expand=True)
        box.pack_propagate(False)
        self.log_text = tk.Text(box, bg='#1e222b', fg='#c9d1d9', insertbackground='#c9d1d9',
                                font=FONT_MONO, bd=0, wrap='none', state='disabled')
        vs = ttk.Scrollbar(box, orient='vertical', command=self.log_text.yview)
        hs = ttk.Scrollbar(box, orient='horizontal', command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side='right', fill='y')
        hs.pack(side='bottom', fill='x')
        self.log_text.pack(side='left', fill='both', expand=True)

        self.log_text.tag_configure('err', foreground='#ff8080')
        self.log_text.tag_configure('ok', foreground='#7ee787')
        self.log_text.tag_configure('warn', foreground='#ffc46b')
        self.log_text.tag_configure('info', foreground='#79c0ff')

    # -----------------------------------------------------------
    #  日志与状态（线程安全）
    # -----------------------------------------------------------
    def _queue_log(self, line):
        self._ui_queue.put(('log', line))

    def _queue_out(self, line):
        self._ui_queue.put(('out', line))

    def _pump_queue(self):
        try:
            while True:
                kind, payload = self._ui_queue.get_nowait()
                if kind == 'log':
                    self._append_log(payload, 'info')
                elif kind == 'out':
                    self._append_log(payload, self._classify(payload))
                elif kind == 'status':
                    self.lbl_status.configure(text=payload)
                elif kind == 'busy':
                    on, text = payload
                    self.lbl_busy.configure(text=text if on else '')
                elif kind == 'devices':
                    self._apply_devices(payload)
                elif kind == 'call':
                    # 后台线程请求在主线程执行 UI 操作（Tk 非线程安全）
                    try:
                        payload()
                    except Exception as exc:  # noqa: BLE001 - 单个回调失败不应中断轮询
                        self._append_log('界面更新失败：%s' % exc, 'err')
        except queue.Empty:
            pass
        self.after(80, self._pump_queue)

    @staticmethod
    def _classify(line):
        low = line.lower()
        # 先判断成功/提示，再判断错误：避免输出里偶然出现 "error"
        # 字样（如路径、模块名）被误标为红色错误。
        if '[成功]' in line or '[√]' in line:
            return 'ok'
        if '[警告]' in line or '[!]' in line or '[提示]' in line or '[已取消]' in line:
            return 'warn'
        if ('[错误]' in line or '[失败]' in line or '[超时]' in line
                or 'error:' in low or 'failed' in low):
            return 'err'
        return 'plain'

    def _append_log(self, text, tag):
        self.log_text.configure(state='normal')
        self.log_text.insert('end', text + '\n', tag)
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def set_status(self, text):
        self._ui_queue.put(('status', text))

    def set_busy_indicator(self, on, text='⏳ 执行中'):
        """在日志标题旁显示/隐藏忙碌标记，让用户明确知道任务在跑。"""
        self._ui_queue.put(('busy', (on, text)))

    def log(self, text, tag=None):
        self._queue_log(text)

    def log_out(self, text):
        self._queue_out(text)

    def ui_call(self, fn):
        """从后台线程安全地更新界面。

        Tkinter 只能在主线程操作控件，后台线程直接调用 tree.insert()
        等会抛 RuntimeError 且被静默吞掉，表现为界面空白。
        """
        self._ui_queue.put(('call', fn))

    def open_log_dir(self):
        try:
            os.startfile(core.LOG_DIR)
        except Exception:
            messagebox.showinfo('日志目录', core.LOG_DIR)

    # -----------------------------------------------------------
    #  设备状态
    # -----------------------------------------------------------
    def refresh_devices(self, initial=False):
        def job(_ctl):
            return core.detect_devices(self.runner)

        def done(st):
            self.device = st
            self._ui_queue.put(('devices', st))
            if not initial:
                self.set_status('设备状态已刷新')

        self.set_status('正在检测设备...')
        core.Task(job, on_done=done).start()

    def _apply_devices(self, st):
        self.lbl_adb.configure(
            text='● ADB 已连接' if st.adb else '● ADB 未连接',
            fg=C_OK if st.adb else '#8b93a3')
        self.lbl_fb.configure(
            text='● Fastboot 已连接' if st.fastboot else '● Fastboot 未连接',
            fg=C_OK if st.fastboot else '#8b93a3')

        # 仅在连接状态真正变化时通知各模式。
        # 否则每次刷新都会触发一轮自动加载，导致任务被"已有任务在执行"挡掉。
        sig = (st.adb, st.fastboot)
        if sig == self._last_device_sig:
            return
        self._last_device_sig = sig
        # 连接状态变化后，之前的检测结果可能已失效
        self.mode_cache.clear()

        frame = self._frames.get(self._current_key)
        if frame is not None and hasattr(frame, 'on_device_change'):
            # frame 可能已被 show_mode 销毁，先确认存活再回调
            if widget_alive(frame):
                frame.on_device_change(st)

    # -----------------------------------------------------------
    #  模式切换
    # -----------------------------------------------------------
    def show_mode(self, key):
        if self._current_key == key and key in self._frames:
            return

        for k, lbl in self._nav_buttons.items():
            lbl.configure(bg=C_SIDE_ACTIVE if k == key else C_SIDE,
                          fg='#ffffff' if k == key else '#d6dae2')

        # 销毁当前内容区，并从缓存中剔除已销毁的 frame。
        # 否则再次进入同一模式时会拿到已 destroy 的控件，pack 时报
        # "bad window path name"。
        for f in self.content.winfo_children():
            f.destroy()
        self._frames.clear()

        self._current_key = key
        frame = self._create_frame(key)
        self._frames[key] = frame
        frame.pack(fill='both', expand=True)
        # 有任务在跑时不触发自动加载，避免任务互相顶掉；
        # 此时仅渲染界面骨架，用户可点该模式的刷新按钮手动加载。
        if hasattr(frame, 'on_device_change') and not self._busy:
            frame.on_device_change(self.device)
        self.set_status('当前模式：%s' % dict((k, t) for k, t, _ in MODES)[key])

    def _create_frame(self, key):
        import mode_status
        import mode_adb
        import mode_fastboot
        import mode_selinux
        import mode_modules
        import mode_zygisk
        import mode_safemode
        import mode_backup
        import mode_logs
        import mode_xposed
        import mode_reboot

        mapping = {
            'status': mode_status.StatusFrame,
            'adb': mode_adb.AdbFrame,
            'fastboot': mode_fastboot.FastbootFrame,
            'selinux': mode_selinux.SelinuxFrame,
            'modules': mode_modules.ModulesFrame,
            'zygisk': mode_zygisk.ZygiskFrame,
            'safemode': mode_safemode.SafeModeFrame,
            'backup': mode_backup.BackupFrame,
            'log': mode_logs.LogFrame,
            'xposed': mode_xposed.XposedFrame,
            'reboot': mode_reboot.RebootFrame,
        }
        return mapping[key](self.content, self)

    # -----------------------------------------------------------
    #  任务执行封装
    # -----------------------------------------------------------
    def run_task(self, fn, on_done=None, busy_text='正在执行...', done_text='完成'):
        """在后台执行 fn(ctl)，期间禁用模式切换。

        on_done / on_error 会被调度回主线程执行，因此回调里可以安全
        操作 Tk 控件（Tk 非线程安全，后台线程直接改控件会静默失败）。

        注意：任务结束时用户可能已切换到别的模式，原模式的控件已被
        destroy。回调实现需自行确认控件存活（参考各模式的 _alive()）。
        """
        if self._busy:
            messagebox.showwarning('请稍候', '已有任务正在执行，请等待完成。')
            return

        self._busy = True
        self._task_started = time.time()
        # 每次任务使用独立的计时基准，避免与 refresh_devices 等并发任务
        # 共用 self._task_started 导致耗时显示错误。
        started = self._task_started
        self.set_status(busy_text)
        self.set_busy_indicator(True)
        self._set_cancel_state(True)

        def wrapper(ctl):
            return fn(ctl)

        def done(result):
            def apply():
                self._busy = False
                self.set_busy_indicator(False)
                self._set_cancel_state(False)
                self.set_status('%s（耗时 %.1f 秒）'
                                % (done_text, time.time() - started))
                if on_done:
                    on_done(result)
            self._ui_queue.put(('call', apply))

        def err(exc):
            def apply():
                self._busy = False
                self.set_busy_indicator(False)
                self._set_cancel_state(False)
                self.set_status('执行出错')
                self.log('执行出错：%s' % exc)
                messagebox.showerror(
                    '执行出错',
                    '%s\n\n详细信息已写入实时日志，可通过模式 9 查看。' % exc)
            self._ui_queue.put(('call', apply))

        self._current_task = core.Task(wrapper, on_done=done, on_error=err)
        # 让所有经 runner 执行的命令默认响应取消：轮询当前任务的 cancelled 标志。
        self.runner.cancel_check = lambda: self._current_task is not None and self._current_task.cancelled
        self._current_task.start()

    def cancel_task(self):
        """请求中断当前任务。

        立即终止正在执行的子进程（长命令如 adb push 也能即刻停下），
        同时置位 cancelled 标志，让尚在纯 Python 轮询的任务尽早退出。
        """
        task = self._current_task
        if task is None or not self._busy:
            return
        task.cancel()
        self.runner.cancel_current()
        self.log('已发送取消请求，正在中断当前命令...')

    def _set_cancel_state(self, enabled):
        try:
            self.btn_cancel.state(['!disabled'] if enabled else ['disabled'])
        except tk.TclError:
            pass

    @property
    def busy(self):
        return self._busy

    # -----------------------------------------------------------
    #  关闭
    # -----------------------------------------------------------
    def on_close(self):
        if self._busy:
            if not messagebox.askyesno('确认退出', '仍有任务在执行，确定要退出吗？'):
                return
        self.logger.write('用户关闭程序')
        self.destroy()


# ---------------------------------------------------------------
#  公共 UI 工具（供各模式模块复用）
# ---------------------------------------------------------------
def panel(parent, title=None):
    """创建一个白色卡片面板。"""
    if title:
        lf = ttk.Labelframe(parent, text=' %s ' % title, padding=12)
        lf.pack(fill='both', expand=True)
        return lf
    fr = tk.Frame(parent, bg=C_PANEL, highlightbackground='#e2e5ea',
                  highlightthickness=1)
    fr.pack(fill='both', expand=True)
    return fr


def header(parent, title, subtitle=''):
    """面板标题区。"""
    box = tk.Frame(parent, bg=C_PANEL)
    box.pack(fill='x', pady=(0, 10))
    ttk.Label(box, text=title, style='Title.TLabel').pack(anchor='w')
    if subtitle:
        ttk.Label(box, text=subtitle, style='Muted.TLabel',
                  wraplength=680, justify='left').pack(anchor='w', pady=(3, 0))
    return box


def button(parent, text, command, accent=False):
    btn = ttk.Button(parent, text=text, command=command,
                     style='Accent.TButton' if accent else 'TButton')
    btn.pack(side='left', padx=(0, 8), pady=4)
    return btn


def widget_alive(widget):
    """控件是否仍存活。

    后台任务结束时用户可能已切换模式，原模式的控件已被 destroy。
    此时访问会抛 TclError: invalid command name，必须先判断存活。
    """
    try:
        return widget is not None and bool(widget.winfo_exists())
    except tk.TclError:
        return False


def require_adb(app, silent=False):
    """需要 ADB 前置检查，返回 True 表示可用。"""
    if not app.device.adb:
        if not silent:
            messagebox.showwarning('未连接设备',
                                   '未检测到 ADB 设备。\n请连接手机、开启 USB 调试并授权后重试。')
        return False
    return True


def require_root(app, runner, silent=False):
    """探测 Root；不可用时提示。"""
    if core.is_root(runner):
        return True
    if not silent:
        messagebox.showwarning('未获取 Root',
                               '当前未获取 Root 权限。\n请先执行模式 2 或模式 3 完成提权。')
    return False
