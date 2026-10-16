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

# 配色 —— macOS 桌面风格：浅灰窗口底 + 半透明灰侧栏 + 纯白圆角卡片
C_BG = '#ececee'          # 窗口背景（macOS 窗口灰）
C_PANEL = '#ffffff'        # 内容卡片白
C_SIDE = '#e7e7ea'         # 侧栏（毛玻璃灰）
C_SIDE_HOVER = '#dcdce1'   # 侧栏悬停
C_SIDE_ACTIVE = '#007aff'  # 侧栏选中（系统蓝）
C_TEXT = '#1d1d1f'         # 主文本（苹果近黑）
C_MUTED = '#86868b'        # 次要文本（苹果灰）
C_OK = '#34c759'           # 系统绿
C_WARN = '#ff9f0a'         # 系统橙
C_ERR = '#ff3b30'          # 系统红
C_ACCENT = '#007aff'       # 系统蓝（强调色）
# 派生色：强调色的深浅变体，统一 hover / 高亮 / 浅底
C_ACCENT_DARK = '#0069d9'
C_ACCENT_LIGHT = '#e5f0ff'
C_BORDER = '#d8d8dd'       # 分隔线 / 卡片描边
C_CARD = '#f5f5f7'         # 卡片内的浅灰填充

FONT = ('Microsoft YaHei UI', 10)
FONT_BOLD = ('Microsoft YaHei UI', 10, 'bold')
FONT_TITLE = ('Microsoft YaHei UI', 15, 'bold')
FONT_SMALL = ('Microsoft YaHei UI', 9)
FONT_MONO = ('Microsoft YaHei UI', 9)

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
    ('links', '12. 相关链接', 'GitHub 项目与依赖'),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(APP_GEOMETRY)
        self.minsize(*APP_MIN)
        self.configure(bg=C_BG)
        # 接管窗口关闭（右上角 X），确保退出前也走清理流程，
        # 否则直接 destroy 会漏掉 adb server 清理并触发 _MEI 删除警告。
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        self._ui_queue = queue.Queue()
        self._busy = False
        self._current_key = None
        self._frames = {}
        self._last_device_sig = None
        self._task_started = 0.0
        self._current_task = None
        # 任务代际号：每次发起任务 / 切换模式都会自增。
        # 后台任务在启动时记下当时的代际，回调（on_done/on_error）执行前
        # 比对代际，只有"仍是当前代"的回调才允许落地。
        # 这样快速点击切换模式或连续触发检测时，早先任务迟到的回调会被
        # 安全丢弃，不会去写已经销毁的控件、也不会错误复位 _busy。
        self._generation = 0
        # 设备刷新代际号：独立于任务代际。
        # 设备检测是后台异步的，且启动时会先刷新再渲染模式。若与任务共用
        # 同一代际，紧随其后的 show_mode 会把它作废，导致"启动检测不到、
        # 必须手动点刷新"。故设备刷新单独计数，只被"更晚的设备刷新"取代，
        # 不被模式切换影响。
        self._dev_generation = 0
        # 是否有设备扫描正在进行中。用于区分"扫描未完成"与"确实无设备"，
        # 避免启动阶段误报"未检测到设备"。
        self._dev_scanning = False
        # 各模式的检测结果缓存，切换模式回来时可秒开
        self.mode_cache = {}

        self.logger = core.Logger(sink=self._queue_log)
        self.runner = core.Runner(logger=self.logger, emit=self._queue_out)
        self.device = core.DeviceState()

        self._build_style()
        self._build_layout()
        self._pump_queue()

        # 应用窗口图标（打包后为内嵌 ico，源码运行时现场渲染）
        try:
            import branding
            branding.apply_window_icon(self)
        except Exception:
            pass

        self.logger.write('===== 图形界面启动 =====')
        self.logger.write('工具目录：%s' % core.ROOT_DIR)
        self._run_preflight()
        self.set_status('正在检测设备...')
        # 先渲染界面骨架（此时 device 尚为空），检测完成后再触发自动检测。
        # 关键：不能在这里直接 show_mode 后依赖它自己检测——首次设备扫描是
        # 异步的，show_mode 时 device 还是空的，会把"未检测到设备"当成结论，
        # 造成"启动点开始检测没反应、必须手动刷新"的错觉。
        # 改为：检测完成后由 _apply_devices 统一触发当前模式的 on_device_change。
        self.show_mode(MODES[0][0])
        self.refresh_devices(initial=True)

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

        # ── 普通按钮：白底细描边、圆润，hover 泛蓝 ──
        st.configure('TButton', font=FONT, padding=(14, 7), relief='flat',
                     background='#ffffff', foreground=C_TEXT,
                     bordercolor=C_BORDER, focuscolor='#ffffff',
                     lightcolor='#ffffff', darkcolor='#ffffff')
        st.map('TButton',
               background=[('disabled', '#f5f5f7'), ('pressed', '#e8e8ed'),
                           ('active', '#f0f0f5')],
               foreground=[('disabled', '#b0b0b5')],
               bordercolor=[('active', C_ACCENT)])
        # ── 强调按钮：系统蓝底 + 白字 ──
        st.configure('Accent.TButton', font=FONT_BOLD, padding=(14, 8), relief='flat',
                     background=C_ACCENT, foreground='#ffffff',
                     bordercolor=C_ACCENT, focuscolor=C_ACCENT,
                     lightcolor=C_ACCENT, darkcolor=C_ACCENT)
        st.map('Accent.TButton',
               background=[('disabled', '#b3d1ff'), ('pressed', C_ACCENT_DARK),
                           ('active', C_ACCENT_DARK)],
               foreground=[('disabled', '#f0f6ff')])
        # ── 危险按钮：红色底 + 白字（卸载 / 清除等不可撤销操作） ──
        st.configure('Danger.TButton', font=FONT_BOLD, padding=(14, 8), relief='flat',
                     background=C_ERR, foreground='#ffffff',
                     bordercolor=C_ERR, focuscolor=C_ERR,
                     lightcolor=C_ERR, darkcolor=C_ERR)
        st.map('Danger.TButton',
               background=[('disabled', '#f5c2c2'), ('pressed', '#c62828'),
                           ('active', '#c62828')],
               foreground=[('disabled', '#fff5f5')])

        st.configure('TCheckbutton', background=C_PANEL, font=FONT,
                     focuscolor=C_PANEL)

        # ── 分组框 ──
        st.configure('TLabelframe', background=C_PANEL, bordercolor=C_BORDER,
                     relief='solid', borderwidth=1)
        st.configure('TLabelframe.Label', background=C_PANEL, foreground=C_TEXT,
                     font=FONT_BOLD)

        # ── 表格 ──
        st.configure('Treeview', font=FONT, rowheight=28, relief='flat',
                     background='#ffffff', fieldbackground='#ffffff',
                     bordercolor=C_BORDER, borderwidth=0)
        st.configure('Treeview.Heading', font=FONT_BOLD, relief='flat',
                     background='#f5f5f7', foreground=C_TEXT, padding=(6, 6))
        st.map('Treeview.Heading', background=[('active', '#ebebf0')])
        st.map('Treeview', background=[('selected', C_ACCENT)],
               foreground=[('selected', '#ffffff')])

        # ── 滚动条：细瘦扁平，去掉 clam 的立体槽 ──
        for orient in ('Vertical', 'Horizontal'):
            st.configure('%s.TScrollbar' % orient, background='#c7c7cc',
                         troughcolor=C_BG, bordercolor=C_BG, arrowcolor='#8e8e93',
                         relief='flat', borderwidth=0, width=10)
            st.map('%s.TScrollbar' % orient,
                   background=[('active', C_ACCENT), ('pressed', C_ACCENT)])
        st.configure('Log.Vertical.TScrollbar', background='#48484a',
                     troughcolor='#1c1c1e', bordercolor='#1c1c1e',
                     arrowcolor='#8e8e93', relief='flat', borderwidth=0, width=10)
        st.configure('Log.Horizontal.TScrollbar', background='#48484a',
                     troughcolor='#1c1c1e', bordercolor='#1c1c1e',
                     arrowcolor='#8e8e93', relief='flat', borderwidth=0)

    # -----------------------------------------------------------
    #  整体布局
    # -----------------------------------------------------------
    def _build_layout(self):
        # 顶部状态栏
        self._build_header()

        body = tk.Frame(self, bg=C_BG)
        body.pack(fill='both', expand=True)

        # 左侧导航
        side = tk.Frame(body, bg=C_SIDE, width=228)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        self._build_sidebar(side)

        # 侧栏与内容区之间的分隔线
        tk.Frame(body, bg=C_BORDER, width=1).pack(side='left', fill='y')

        # 右侧内容区（与侧栏留出内边距，形成卡片感）
        right = tk.Frame(body, bg=C_BG)
        right.pack(side='left', fill='both', expand=True, padx=(12, 12),
                   pady=(10, 0))

        # 内容区：放进可纵向滚动的画布，避免高内容（如 Zygisk/Xposed/模块列表）
        # 超出窗口高度时被裁掉、导致表格只露出表头却看不到数据。
        self._build_content_area(right)

        # 底部日志
        self._build_logpanel(right)

    def _build_content_area(self, parent):
        """构造可纵向滚动的模式内容容器，暴露为 self.content。"""
        holder = tk.Frame(parent, bg=C_BG)
        holder.pack(fill='both', expand=True)

        canvas = tk.Canvas(holder, bg=C_BG, highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview,
                            style='Log.Vertical.TScrollbar')
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        self.content = tk.Frame(canvas, bg=C_BG)
        self._content_window = canvas.create_window(
            (0, 0), window=self.content, anchor='nw')
        self._content_canvas = canvas

        # 内容尺寸变化时同步滚动范围
        def _on_content_config(_e):
            canvas.configure(scrollregion=canvas.bbox('all'))

        def _on_canvas_config(e):
            # 让内容宽度始终等于画布宽度（横向不滚动，只纵向滚动）
            canvas.itemconfigure(self._content_window, width=e.width)

        self.content.bind('<Configure>', _on_content_config)
        canvas.bind('<Configure>', _on_canvas_config)

        # 鼠标滚轮：指针在内容区上时滚动；表格/日志等自带滚动条的控件不接管。
        canvas.bind_all('<MouseWheel>', lambda e: self._wheel_if_inside(e, canvas))
        canvas.bind_all('<Button-4>', lambda e: self._wheel_if_inside(e, canvas, True))
        canvas.bind_all('<Button-5>', lambda e: self._wheel_if_inside(e, canvas, True))

    def _wheel_if_inside(self, event, canvas, linux=False):
        """仅当鼠标位于内容区上方时滚动，避免影响日志区/表格自身滚动。"""
        try:
            w = self.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        # 指针在表格/日志等自带滚动条的控件上时不接管
        while w is not None:
            if w is canvas:
                if linux:
                    canvas.yview_scroll(-1 if event.num == 4 else 1, 'units')
                else:
                    canvas.yview_scroll(int(-event.delta / 120), 'units')
                return
            if w in (self.log_text,):
                return
            if w.winfo_class() in ('Treeview', 'Text'):
                return
            w = w.master

    def _build_header(self):
        head = tk.Frame(self, bg=C_SIDE, height=56)
        head.pack(fill='x')
        head.pack_propagate(False)

        # 左侧标题组：整体垂直居中，避免与标题栏贴太近
        left = tk.Frame(head, bg=C_SIDE)
        left.pack(side='left', padx=(18, 0))
        tk.Label(left, text='RootTool', bg=C_SIDE, fg=C_TEXT,
                 font=('Microsoft YaHei UI', 15, 'bold')).pack(side='left')
        tk.Label(left, text=core.APP_NAME + ' ' + core.APP_VERSION,
                 bg=C_SIDE, fg=C_MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(8, 0),
                                                       pady=(4, 0))

        # 设备状态指示（胶囊样式，浅底细描边）
        def _pill(text, fg, on_click=None):
            f = tk.Frame(head, bg='#f2f2f5', highlightbackground=C_BORDER,
                         highlightthickness=1)
            f.pack(side='right', padx=(8, 0), pady=(6, 0))
            l = tk.Label(f, text=text, bg='#f2f2f5', fg=fg,
                         font=('Microsoft YaHei UI', 9), padx=10, pady=4)
            l.pack()
            if on_click is not None:
                # 可点击胶囊：手型光标 + 悬停高亮 + 点击回调
                l.configure(cursor='hand2')

                def _enter(_e):
                    l.configure(bg='#e6e6eb')
                    f.configure(bg='#e6e6eb')

                def _leave(_e):
                    l.configure(bg='#f2f2f5')
                    f.configure(bg='#f2f2f5')

                l.bind('<Enter>', _enter)
                l.bind('<Leave>', _leave)
                l.bind('<Button-1>', lambda _e: on_click())
            return l, f

        self.lbl_adb, _ = _pill('● ADB 未连接', C_MUTED)
        self.lbl_fb, _ = _pill('● Fastboot 未连接', C_MUTED)
        # 权限指示灯：显示 Windows 侧是否以管理员运行。
        # 措辞避免与"手机 Root"混淆，未提权时点击可直接触发 UAC 提权重启。
        self._admin_ok = core.is_admin()
        self.lbl_admin, self._admin_pill = _pill(
            '● 管理员权限' if self._admin_ok else '● 未提权（点击提权）',
            C_OK if self._admin_ok else C_WARN,
            on_click=None if self._admin_ok else self.elevate)

        btn = tk.Button(head, text='刷新设备', command=self.refresh_devices,
                        bg=C_ACCENT, fg='#ffffff', activebackground=C_ACCENT_DARK,
                        activeforeground='#ffffff', bd=0, font=FONT_BOLD,
                        padx=16, pady=6, cursor='hand2', relief='flat')
        btn.pack(side='right', padx=(12, 18), pady=(5, 0))
        btn.bind('<Enter>', lambda e: btn.configure(bg=C_ACCENT_DARK))
        btn.bind('<Leave>', lambda e: btn.configure(bg=C_ACCENT))

        # 底部分隔线，把顶栏与内容区分开
        tk.Frame(head, bg=C_BORDER, height=1).place(x=0, rely=1.0,
                                                    y=-1, relwidth=1)

    def _build_sidebar(self, parent):
        # 品牌区：与应用图标同源的圆角方块 + 名称
        brand = tk.Frame(parent, bg=C_SIDE)
        brand.pack(fill='x', padx=16, pady=(16, 6))
        logo = tk.Frame(brand, bg=C_ACCENT, width=34, height=34)
        logo.pack(side='left')
        logo.pack_propagate(False)
        tk.Label(logo, text='R', bg=C_ACCENT, fg='#ffffff',
                 font=('Segoe UI', 16, 'bold')).pack(expand=True)
        box = tk.Frame(brand, bg=C_SIDE)
        box.pack(side='left', padx=(10, 0))
        tk.Label(box, text='临时 Root 工具', bg=C_SIDE, fg=C_TEXT,
                 font=FONT_BOLD).pack(anchor='w')
        tk.Label(box, text=core.APP_VERSION + ' · manet', bg=C_SIDE, fg=C_MUTED,
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w')

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill='x', padx=0, pady=(6, 0))
        tk.Label(parent, text='功能模式', bg=C_SIDE, fg=C_MUTED,
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', padx=16,
                                                      pady=(12, 8))

        self._nav_buttons = {}
        for key, title, _desc in MODES:
            row = tk.Frame(parent, bg=C_SIDE, cursor='hand2')
            row.pack(fill='x', padx=8, pady=1)

            # 左侧选中指示条
            bar = tk.Frame(row, bg=C_SIDE, width=3)
            bar.pack(side='left', fill='y')

            # 序号徽章（1~12），独立于标题，便于对齐
            num, _, rest = title.partition('. ')
            badge = tk.Label(row, text=num, bg='#dcdce1', fg=C_MUTED,
                             font=('Microsoft YaHei UI', 8), width=3, pady=2)
            badge.pack(side='left', padx=(10, 8), pady=7)

            lbl = tk.Label(row, text=rest, bg=C_SIDE, fg=C_TEXT,
                           font=FONT, anchor='w')
            lbl.pack(side='left', fill='x', expand=True, pady=7)

            widgets = (row, lbl, bar, badge)
            for w in widgets:
                w.bind('<Button-1>', lambda e, k=key: self.show_mode(k))
            for w in (row, lbl, badge):
                w.bind('<Enter>', lambda e, r=row, l=lbl, b=badge:
                       self._nav_hover(r, l, b, True))
                w.bind('<Leave>', lambda e, r=row, l=lbl, b=badge:
                       self._nav_hover(r, l, b, False))
            self._nav_buttons[key] = {'row': row, 'lbl': lbl, 'bar': bar,
                                      'badge': badge}

        # 底部弹性空白，把「退出」顶到侧栏最下方
        tk.Frame(parent, bg=C_SIDE).pack(fill='both', expand=True)

        tk.Frame(parent, bg=C_BORDER, height=1).pack(fill='x')
        quit_row = tk.Frame(parent, bg=C_SIDE, cursor='hand2')
        quit_row.pack(fill='x')
        tk.Frame(quit_row, bg=C_SIDE, width=3).pack(side='left', fill='y')
        quit_lbl = tk.Label(quit_row, text='⏻  退出', bg=C_SIDE, fg=C_TEXT,
                            font=FONT, anchor='w', padx=13, pady=10)
        quit_lbl.pack(side='left', fill='x', expand=True)
        quit_lbl.bind('<Button-1>', lambda e: self.on_close())
        quit_row.bind('<Button-1>', lambda e: self.on_close())
        quit_lbl.bind('<Enter>', lambda e: (quit_row.configure(bg=C_SIDE_HOVER),
                                            quit_lbl.configure(bg=C_SIDE_HOVER,
                                                               fg=C_ERR)))
        quit_lbl.bind('<Leave>', lambda e: (quit_row.configure(bg=C_SIDE),
                                            quit_lbl.configure(bg=C_SIDE,
                                                               fg=C_TEXT)))

    def _nav_hover(self, row, lbl, badge, entering):
        # 选中项由 _highlight_nav 接管，不做 hover 覆盖
        if row.cget('bg') == C_SIDE_ACTIVE:
            return
        color = C_SIDE_HOVER if entering else C_SIDE
        row.configure(bg=color)
        lbl.configure(bg=color)
        badge.configure(bg='#d0d0d6' if entering else '#dcdce1')

    def _highlight_nav(self, key):
        """高亮当前模式：系统蓝背景 + 白字（macOS 侧栏选中）。"""
        for k, w in self._nav_buttons.items():
            active = (k == key)
            bg = C_SIDE_ACTIVE if active else C_SIDE
            fg = '#ffffff' if active else C_TEXT
            w['row'].configure(bg=bg)
            w['lbl'].configure(bg=bg, fg=fg)
            w['bar'].configure(bg=bg)
            w['badge'].configure(
                bg='#ffffff' if active else '#dcdce1',
                fg=C_ACCENT if active else C_MUTED)

    def _build_logpanel(self, parent):
        # 固定高度的日志面板：不参与纵向伸缩，避免内容区（expand=True）
        # 把日志区挤到只剩标题栏，导致「无法看见日志」。
        wrap = tk.Frame(parent, bg=C_BG, height=210)
        wrap.pack(fill='x', side='bottom', expand=False, pady=(0, 0))
        wrap.pack_propagate(False)

        # 与内容区之间的分隔线
        tk.Frame(wrap, bg=C_BORDER, height=1).pack(fill='x', pady=(6, 8))

        bar = tk.Frame(wrap, bg=C_BG)
        bar.pack(fill='x')
        tk.Label(bar, text='●', bg=C_BG, fg=C_ACCENT, font=FONT).pack(side='left')
        tk.Label(bar, text='实时日志', bg=C_BG, fg=C_TEXT,
                 font=FONT_BOLD).pack(side='left', padx=(4, 0))
        self.lbl_busy = tk.Label(bar, text='', bg=C_BG, fg=C_ACCENT, font=FONT_BOLD)
        self.lbl_busy.pack(side='left', padx=(10, 0))
        self.btn_cancel = ttk.Button(bar, text='取消', command=self.cancel_task)
        self.btn_cancel.pack(side='left', padx=(10, 0))
        self.btn_cancel.state(['disabled'])
        self.lbl_status = tk.Label(bar, text='就绪', bg=C_BG, fg=C_MUTED, font=FONT)
        self.lbl_status.pack(side='left', padx=8)
        tk.Button(bar, text='清空日志', command=self.clear_log, bd=0, font=FONT,
                  bg=C_BG, fg=C_ACCENT, activebackground=C_BG,
                  activeforeground=C_ACCENT_DARK,
                  cursor='hand2').pack(side='right')
        tk.Button(bar, text='打开日志目录', command=self.open_log_dir, bd=0, font=FONT,
                  bg=C_BG, fg=C_ACCENT, activebackground=C_BG,
                  activeforeground=C_ACCENT_DARK,
                  cursor='hand2').pack(side='right', padx=8)

        # 日志区：macOS 终端风深灰底 + 圆角描边。
        # 填满 wrap 的剩余空间（wrap 已固定高度，此处不再用固定高度）。
        box = tk.Frame(wrap, bg='#1c1c1e',
                       highlightbackground='#2c2c2e', highlightthickness=1)
        box.pack(fill='both', expand=True, pady=(0, 6))
        self.log_text = tk.Text(box, bg='#1c1c1e', fg='#e5e5ea', insertbackground='#e5e5ea',
                                font=FONT_MONO, bd=0, wrap='none', state='disabled',
                                padx=10, pady=8, selectbackground='#0a84ff')
        vs = ttk.Scrollbar(box, orient='vertical', command=self.log_text.yview,
                           style='Log.Vertical.TScrollbar')
        hs = ttk.Scrollbar(box, orient='horizontal', command=self.log_text.xview,
                           style='Log.Horizontal.TScrollbar')
        self.log_text.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side='right', fill='y')
        hs.pack(side='bottom', fill='x')
        self.log_text.pack(side='left', fill='both', expand=True)

        self.log_text.tag_configure('err', foreground='#ff6961')
        self.log_text.tag_configure('ok', foreground='#5dd879')
        self.log_text.tag_configure('warn', foreground='#ffd60a')
        self.log_text.tag_configure('info', foreground='#64b5ff')

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
                    try:
                        self._apply_devices(payload)
                    except Exception as exc:  # noqa: BLE001 - 单个模式处理失败不应阻断队列
                        self._append_log('设备状态更新失败：%s' % exc, 'err')
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
    def refresh_devices(self, initial=False, on_done=None):
        # 设备检测使用独立的设备代际：只被"更晚的设备刷新"取代，
        # 不会被 show_mode 的模式切换作废（否则启动时会把自己的首次
        # 检测结果丢掉，表现为"必须手动点刷新才检测得到"）。
        self._dev_generation += 1
        gen = self._dev_generation
        self._dev_scanning = True

        def job(_ctl):
            # 先确保 adb server 已启动：server 未运行时 adb devices 首次
            # 自动拉起需数秒，且偶发因旧进程/端口占用失败，会表现为
            # "手机已连接却检测不到"。显式 start-server 可消除这类漏检。
            core.start_adb_server(self.runner)
            return core.detect_devices(self.runner)

        def done(st):
            # 设备代际过期：已有更新的刷新发起，丢弃本次结果。
            if gen != self._dev_generation:
                return
            self._dev_scanning = False
            self.device = st
            self._ui_queue.put(('devices', st))
            if not initial:
                self.set_status('设备状态已刷新：%s' % st.describe())
            # on_done 由后台线程回调，需调度回主线程再执行。
            if on_done is not None:
                self._ui_queue.put(('call', lambda: on_done(st)))

        self.set_status('正在检测设备...')
        core.Task(job, on_done=done).start()

    def _apply_devices(self, st):
        # recovery / sideload 状态（第三方 Recovery）下 adb 仍可用，
        # 指示灯用不同文案与配色区分，避免用户误以为"未连接"。
        if st.adb:
            self.lbl_adb.configure(text='● ADB 已连接', fg=C_OK)
        elif st.adb_recovery:
            self.lbl_adb.configure(text='● ADB 已连接（Recovery）', fg=C_WARN)
        else:
            self.lbl_adb.configure(text='● ADB 未连接', fg=C_MUTED)
        self.lbl_fb.configure(
            text='● Fastboot 已连接' if st.fastboot else '● Fastboot 未连接',
            fg=C_OK if st.fastboot else C_MUTED)

        # 仅在连接状态真正变化时通知各模式。
        # 否则每次刷新都会触发一轮自动加载，导致任务被"已有任务在执行"挡掉。
        sig = (st.adb, st.fastboot, st.adb_recovery)
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

        # 切换模式即作废上一代：旧模式挂起的后台回调（on_done/on_error）
        # 会因代际不符被丢弃，不会去写已 destroy 的控件，也不会误复位 _busy。
        self._generation += 1
        # 主动取消仍在跑的旧任务，尽早终止其 adb 子进程，避免切换后
        # 后台残留任务继续占用设备、与新模式的检测争抢资源。
        if self._current_task is not None:
            try:
                self._current_task.cancel()
            except Exception:
                pass
            self.runner.cancel_current()
        self._busy = False
        self.set_busy_indicator(False)
        self._set_cancel_state(False)
        self._current_task = None

        self._highlight_nav(key)

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
        # 切换模式后自动加载：此前已作废旧任务，这里可安全触发。
        if hasattr(frame, 'on_device_change'):
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
        import mode_links

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
            'links': mode_links.LinksFrame,
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

        # 记录本任务的代际：切换模式或再次发起任务会自增代际，
        # 使本任务迟到的回调失效。
        self._generation += 1
        gen = self._generation

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
                # 代际已过期：说明用户已切换模式或发起了新任务，
                # 本次回调属于"迟到的旧任务"，直接丢弃，不碰 UI、不复位 _busy。
                if gen != self._generation:
                    return
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
                if gen != self._generation:
                    return
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
    def elevate(self):
        """以管理员权限重新启动程序（点击「未提权」胶囊时触发）。"""
        if self._busy:
            messagebox.showinfo('请稍候', '有任务正在执行，请等待任务结束后再提权。')
            return
        if not messagebox.askyesno(
                '以管理员身份重启',
                '部分操作（如识别 USB 设备、fastboot 刷写）需要管理员权限。\n\n'
                '将重新启动本程序并弹出 UAC 提权确认框，当前窗口会关闭。\n'
                '是否继续？'):
            return
        ok, msg = core.relaunch_as_admin()
        if ok:
            self.logger.write('已发起管理员提权重启，正在彻底退出当前实例')
            self._shutdown_cleanup()
            self._quit_process()
        else:
            messagebox.showwarning('提权未完成', msg)
            self.logger.write('提权未完成：%s' % msg)

    def _quit_process(self):
        """彻底退出当前进程，避免留下无窗口的僵尸实例。

        仅 destroy() 只销毁 Tk 窗口，并不保证进程退出：后台任务线程、
        自循环的 after 轮询、以及被 ShellExecuteW 拉起后仍在的父进程
        都可能让进程悬挂。提权重启场景尤其明显——旧实例不彻底退出，
        用户就会看到"开了多个程序、旧的关不掉"。

        这里先清除单实例登记（让新实例能立刻接管），再销窗口，
        最后用 os._exit(0) 强制结束进程（不触发 atexit / 非守护线程 join）。
        """
        try:
            import single_instance
            single_instance.clear_registry()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
        try:
            os._exit(0)
        except Exception:
            sys.exit(0)

    def on_close(self):
        if self._busy:
            if not messagebox.askyesno('确认退出', '仍有任务在执行，确定要退出吗？'):
                return
        self.logger.write('用户关闭程序')
        # 退出前收尾：单文件 exe 退出时 PyInstaller 要删除临时解包目录
        # （%TEMP%\_MEIxxxxxx），而常驻的 adb server 会占用从该目录加载的
        # adb.exe，导致删除失败并弹出 "Failed to remove temporary directory"。
        # 先关掉 adb server 并回收子进程，可避免该警告。
        self._shutdown_cleanup()
        # 清除单实例登记，否则下次启动可能误判"仍有实例在运行"
        # （例如旧实例被强杀、登记文件残留时）。
        try:
            import single_instance
            single_instance.clear_registry()
        except Exception:
            pass
        self.destroy()

    def _shutdown_cleanup(self):
        """退出清理：结束 adb server 与仍在运行的子进程。"""
        self.logger.write('正在清理 adb server 与后台子进程...')
        try:
            # kill-server 会终止常驻 adb 进程，释放对 _MEI 目录内 adb.exe 的占用。
            self.runner.run(['adb', 'kill-server'], quiet=True, timeout=8)
        except Exception as exc:
            self.logger.write('清理 adb server 失败：%s' % exc)
        # 兜底：若仍有本工具启动的子进程残存，直接回收。
        try:
            self.runner.cancel_current()
        except Exception:
            pass


# ---------------------------------------------------------------
#  公共 UI 工具（供各模式模块复用）
# ---------------------------------------------------------------
def panel(parent, title=None):
    """创建一个白色卡片面板。"""
    if title:
        lf = ttk.Labelframe(parent, text=' %s ' % title, padding=12)
        lf.pack(fill='both', expand=True)
        return lf
    fr = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER,
                  highlightthickness=1)
    fr.pack(fill='both', expand=True)
    return fr


def header(parent, title, subtitle=''):
    """面板标题区：左侧强调竖条 + 标题 + 副标题 + 底部细分割线。"""
    box = tk.Frame(parent, bg=C_PANEL)
    box.pack(fill='x', pady=(0, 12))

    line = tk.Frame(box, bg=C_PANEL)
    line.pack(anchor='w', fill='x')
    tk.Frame(line, bg=C_ACCENT, width=4, height=22).pack(side='left', pady=(1, 0))
    ttk.Label(line, text=title, style='Title.TLabel').pack(side='left', padx=(8, 0))
    if subtitle:
        ttk.Label(box, text=subtitle, style='Muted.TLabel',
                  wraplength=720, justify='left').pack(anchor='w', pady=(4, 0))
    tk.Frame(box, bg=C_BORDER, height=1).pack(fill='x', pady=(10, 0))
    return box


def button(parent, text, command, accent=False):
    btn = ttk.Button(parent, text=text, command=command,
                     style='Accent.TButton' if accent else 'TButton')
    btn.pack(side='left', padx=(0, 8), pady=4)
    return btn


def section(parent, title, hint=''):
    """分区标题：小色块 + 标题 + 可选说明，用于同一面板内的逻辑分组。"""
    row = tk.Frame(parent, bg=C_PANEL)
    row.pack(fill='x', pady=(10, 6))
    tk.Frame(row, bg=C_ACCENT, width=3, height=14).pack(side='left')
    tk.Label(row, text=title, bg=C_PANEL, fg=C_TEXT,
             font=FONT_BOLD).pack(side='left', padx=(7, 0))
    if hint:
        tk.Label(row, text=hint, bg=C_PANEL, fg=C_MUTED,
                 font=FONT_SMALL).pack(side='left', padx=(8, 0))
    return row


def badge(parent, text, color=C_ACCENT, bg=None):
    """小圆角徽章：用于状态、标签、类型等。返回 Label。"""
    lbl = tk.Label(parent, text=text, fg=color, bg=bg or C_PANEL,
                   font=('Microsoft YaHei UI', 8, 'bold'), padx=7, pady=1,
                   highlightbackground=color, highlightthickness=1)
    return lbl


def dot(parent, color, text='', bg=None, font=None):
    """状态圆点 + 说明文字，返回 (容器, 圆点 Label, 文字 Label)。"""
    frame = tk.Frame(parent, bg=bg or C_PANEL)
    d = tk.Label(frame, text='●', fg=color, bg=bg or C_PANEL,
                 font=('Microsoft YaHei UI', 8))
    d.pack(side='left')
    t = tk.Label(frame, text=text, fg=C_TEXT, bg=bg or C_PANEL,
                 font=font or FONT)
    t.pack(side='left', padx=(5, 0))
    return frame, d, t


def card(parent, accent=None, fill=C_PANEL, pad=(12, 10)):
    """圆角感卡片容器：细边框 + 可选左侧强调色条。返回可放置内容的 Frame。"""
    outer = tk.Frame(parent, bg=fill, highlightbackground=C_BORDER,
                     highlightthickness=1)
    if accent:
        tk.Frame(outer, bg=accent, width=3).pack(side='left', fill='y')
    inner = tk.Frame(outer, bg=fill)
    inner.pack(side='left', fill='both', expand=True,
               padx=pad[0], pady=pad[1])
    return outer, inner


def stat(parent, label, value='—', color=C_TEXT, bg=C_CARD):
    """统计小卡：上方说明 + 下方数值。返回可更新数值的 Label。"""
    box = tk.Frame(parent, bg=bg, highlightbackground=C_BORDER,
                   highlightthickness=1)
    tk.Label(box, text=label, bg=bg, fg=C_MUTED,
             font=FONT_SMALL, anchor='w').pack(fill='x', padx=12, pady=(9, 0))
    val = tk.Label(box, text=value, bg=bg, fg=color, font=FONT_BOLD, anchor='w')
    val.pack(fill='x', padx=12, pady=(1, 9))
    return box, val


def collapsible(parent, title, expanded=False, hint=''):
    """创建一个可折叠区域，返回内部容器 Frame。

    - title：折叠标题（点击标题栏切换展开/收起）
    - expanded：初始是否展开，默认折叠
    - hint：标题右侧的浅色说明文字
    - 返回值为内容容器，调用方直接往里面 pack 控件即可。
    """
    head = tk.Frame(parent, bg='#f5f5f7', cursor='hand2',
                    highlightbackground=C_BORDER, highlightthickness=1)
    head.pack(fill='x', pady=(8, 0))

    # 左侧强调色条，增强可点击感知
    bar = tk.Frame(head, bg=C_ACCENT, width=3)
    bar.pack(side='left', fill='y')

    arrow = tk.Label(head, text='▼' if expanded else '▶', bg='#f5f5f7',
                     fg=C_ACCENT, font=('Microsoft YaHei UI', 9))
    arrow.pack(side='left', padx=(10, 4), pady=7)
    lbl = tk.Label(head, text=title, bg='#f5f5f7', fg=C_TEXT,
                   font=FONT_BOLD, anchor='w')
    lbl.pack(side='left', pady=7)
    if hint:
        tk.Label(head, text=hint, bg='#f5f5f7', fg=C_MUTED,
                 font=FONT_SMALL, anchor='w').pack(
            side='left', padx=(8, 0), pady=7)

    hover_widgets = (head, arrow, lbl, bar)

    def _set_head_bg(color):
        for w in (head, arrow, lbl):
            w.configure(bg=color)

    def _on_enter(_e=None):
        _set_head_bg('#ebebf0')

    def _on_leave(_e=None):
        _set_head_bg('#f5f5f7')

    body = tk.Frame(parent, bg=C_PANEL)
    body._collapsed = not expanded

    def toggle(_e=None):
        if body._collapsed:
            # 展开：插回 head 之后，保持控件顺序
            body.pack(fill='x', after=head)
            body._collapsed = False
            arrow.configure(text='▼')
        else:
            body.pack_forget()
            body._collapsed = True
            arrow.configure(text='▶')

    for w in hover_widgets:
        w.bind('<Button-1>', toggle)
        w.bind('<Enter>', _on_enter)
        w.bind('<Leave>', _on_leave)

    if expanded:
        body.pack(fill='x', after=head)
    return body


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
    """需要 ADB 前置检查，返回 True 表示可用。

    recovery / sideload 状态（第三方 Recovery）下 adb 命令仍可用，一并放行。
    """
    st = app.device
    if st.adb or st.adb_recovery:
        return True
    if not silent:
        if st.adb_devices:
            states = '、'.join('%s(%s)' % (sn, s) for sn, s in st.adb_devices)
            messagebox.showwarning(
                '设备未就绪',
                '已检测到设备但尚未就绪：%s\n\n'
                '请在手机上点击「允许 USB 调试」后重试。' % states)
        else:
            messagebox.showwarning('未连接设备',
                                   '未检测到 ADB 设备。\n请连接手机、开启 USB 调试并授权后重试。')
    return False


def require_root(runner, silent=False):
    """探测 Root；不可用时提示。返回 True 表示已获取 Root。

    注意：探测必须在后台线程做（adb get-state 最长阻塞 15 秒），
    故本函数只应在 run_task 的 job 内调用，不要在主线程直接调用。
    """
    if core.is_root(runner):
        return True
    if not silent:
        messagebox.showwarning('未获取 Root',
                               '当前未获取 Root 权限。\n请先执行模式 2 或模式 3 完成提权。')
    return False


def confirm(title, message, parent=None):
    """统一的二次确认弹窗；返回 True 表示用户确认。

    各模式大量使用 messagebox.askyesno，集中封装便于统一文案风格
    （如需统一"危险操作"红色图标或默认按钮，只改此处）。
    """
    return bool(messagebox.askyesno(title, message, parent=parent))


def dark_text(parent, mono=True, height=None, hscroll=False):
    """构建深色只读文本预览区（日志 / 备份预览共用）。

    返回 (外框, Text)。外框已含竖向滚动条；hscroll=True 时再附加横向滚动条。
    Text 处于 disabled 状态，写入需先置 normal（见 set_dark_text）。
    """
    box = tk.Frame(parent, bg='#1c1c1e', highlightbackground='#2c2c2e',
                   highlightthickness=1)
    kw = {}
    if height:
        kw['height'] = height
    text = tk.Text(box, bg='#1c1c1e', fg='#e5e5ea',
                   font=FONT_MONO if mono else FONT,
                   bd=0, wrap='none', state='disabled', padx=10, pady=8,
                   selectbackground='#0a84ff', **kw)
    vs = ttk.Scrollbar(box, orient='vertical', command=text.yview)
    text.configure(yscrollcommand=vs.set)
    vs.pack(side='right', fill='y')
    if hscroll:
        hs = ttk.Scrollbar(box, orient='horizontal', command=text.xview)
        text.configure(xscrollcommand=hs.set)
        hs.pack(side='bottom', fill='x')
    text.pack(side='left', fill='both', expand=True)
    return box, text


def set_dark_text(text, content):
    """向 dark_text 创建的只读 Text 写入内容（临时切回 normal 再置回 disabled）。"""
    text.configure(state='normal')
    text.delete('1.0', 'end')
    if content:
        text.insert('end', content)
    text.configure(state='disabled')


def ops(parent, *buttons):
    """构建一排「操作」按钮，返回统一的启用/禁用控制器。

    buttons 为 (按钮, 变体名) 二元组序列；变体名可取 'danger'（危险操作，
    红色样式）、'primary'（主操作，强调样式）、'plain'（默认，普通样式）。
    返回 set_enabled(**flags)：按变体名批量启用，未列出的变体保持禁用。
    例如 ops(bar, (btn_disable, 'danger'), (btn_enable, 'plain'))
    之后调用 ctl.set_enabled(danger=True) 即只亮起危险按钮。
    """
    style_of = {'danger': 'Danger.TButton', 'primary': 'Accent.TButton',
                'plain': 'TButton'}
    made = []
    for btn, variant in buttons:
        btn.configure(style=style_of.get(variant, 'TButton'))
        btn.pack(side='left', padx=(0, 8), pady=4)
        btn.state(['disabled'])
        made.append((variant, btn))

    def set_enabled(**flags):
        for variant, btn in made:
            btn.state(['!disabled'] if flags.get(variant) else ['disabled'])

    return set_enabled


def tree3(parent, columns, headers, widths, height=None, style=None,
          stretch=None, select=None):
    """构建带竖向滚动条的多列 Treeview（表头 + 列宽/对齐 + 滚轮）。

    columns：列 id 序列；headers：表头文字序列（与 columns 等长）；
    widths：(列宽, 最小宽, 对齐) 三元组序列，"对齐" 取 'w'/'center'/'e'；
    stretch：各列是否吸收剩余空间，None 表示除末列外均不拉伸（末列拉伸）；
    select：选中回调，传入后自动绑定 <<TreeviewSelect>>。
    返回 (外框, Treeview)。外框已含竖向滚动条，调用方 pack 外框即可。
    """
    n = len(columns)
    if stretch is None:
        stretch = [i == n - 1 for i in range(n)]
    kw = {}
    if height:
        kw['height'] = height
    if style:
        kw['style'] = style
    box = tk.Frame(parent, bg=C_PANEL)
    tree = ttk.Treeview(box, columns=columns, show='headings', **kw)
    for i, col in enumerate(columns):
        w, minw, anchor = widths[i]
        tree.heading(col, text=headers[i])
        tree.column(col, width=w, minwidth=minw, anchor=anchor,
                    stretch=bool(stretch[i]))
    vs = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=vs.set)
    vs.pack(side='right', fill='y')
    tree.pack(side='left', fill='both', expand=True)
    if select:
        tree.bind('<<TreeviewSelect>>', select)
    return box, tree
