# RootTool —— 小米 / 红米 设备临时 Root 工具（GUI 版）

基于 Python + Tkinter 实现的可视化刷机 / Root 辅助工具，**零第三方依赖**，
通过 adb / fastboot / ksud 完成设备检测、临时提权、模块管理与故障自救。

完整操作流程（Fastboot `oem set-gpu-preemption` + `ksud late-load` 漏洞链）
源自 Redmi K70 Pro 等机型的实践整理。

---

## 一、仓库结构

```
code/
├─ README.md                  本说明文档
├─ gui/                       程序源码（Python，零依赖）
│  ├─ roottool.pyw            启动器（双击运行，无控制台窗口）
│  ├─ main.py                 主窗口：侧栏导航 / 状态栏 / 实时日志
│  ├─ branding.py             应用图标：纯标准库生成多尺寸 ico（打包 + 窗口图标）
│  ├─ assets/                 界面资源
│  │  └─ brand.ico            应用图标（由 branding.py 生成）
│  ├─ core.py                 核心层：路径解析、adb/fastboot 调用、设备检测
│  ├─ single_instance.py      单实例检测（重复启动时询问是否结束旧实例）
│  ├─ mode_status.py          模式 1   设备状态检测
│  ├─ mode_adb.py             模式 2   ADB 直连提权
│  ├─ mode_fastboot.py        模式 3   Fastboot 分区提权（分步 + 一键）
│  ├─ mode_selinux.py         模式 4   SELinux 模式切换
│  ├─ mode_modules.py         模式 5   Root 模块管理
│  ├─ mode_zygisk.py          模式 6   Zygisk 崩溃修复 + Vector 一键激活
│  ├─ mode_safemode.py        模式 7   KernelSU 安全模式自救
│  ├─ mode_backup.py          模式 8   模块列表备份恢复
│  ├─ mode_logs.py            模式 9   查看运行日志
│  ├─ mode_xposed.py          模式 10  Xposed 模块管理
│  ├─ mode_reboot.py          模式 11  重启控制
│  └─ mode_links.py           模式 12  相关链接（GitHub 项目与依赖）
├─ tools/                     运行必需的二进制与脚本
│  ├─ adb.exe                 Android 调试桥
│  ├─ fastboot.exe            Fastboot 命令行
│  ├─ AdbWinApi.dll           adb.exe 依赖
│  ├─ AdbWinUsbApi.dll        adb.exe 依赖
│  ├─ libwinpthread-1.dll     fastboot.exe 依赖
│  ├─ ksud                    KernelSU 提权载荷（push 至设备执行）
│  └─ fix_lspd.sh             LSPosed / zygiskd 重新注入修复脚本
├─ packaging/                 打包配置
│  ├─ RootTool.spec           PyInstaller 打包脚本（生成免安装 exe）
│  └─ brand.ico               打包用应用图标（由 branding.py 生成）
└─ scripts/                   辅助脚本与笔记
   ├─ Connector.cmd           无线调试配对向导（IP / 端口 / 配对码）
   └─ readme.txt              手动命令速查笔记
```

---

## 二、运行环境

- **操作系统**：Windows 10 及以上
- **Python**：3.8 及以上，安装时需勾选 `tcl/tk`（Anaconda 自带）
- **第三方库**：无需 `pip install`，全部使用标准库
- 连接设备需已安装对应机型的 ADB / Fastboot 驱动

---

## 三、如何运行

### 方式一：源码运行

```powershell
python gui\roottool.pyw
```

或直接双击 `gui\roottool.pyw`（`.pyw` 扩展名不会弹出黑色控制台窗口）。

### 方式二：打包为 exe（免安装、免 Python 环境）

使用 `packaging/RootTool.spec`，会把 adb / fastboot / ksud 等二进制一并
**内嵌进单个 exe**，因此生成的 exe 可拷贝到**任何未安装 Python 的电脑**上直接双击运行：

```powershell
python -m PyInstaller --noconfirm --clean packaging\RootTool.spec
```

产出 `code/dist/RootTool.exe`（约 19 MB，单文件）。

> 该 exe 为构建产物，**不纳入仓库**（避免二进制使仓库膨胀）。正式发布包由
> [GitHub Actions](../.github/workflows/build.yml) 在打 tag 时自动构建并上传到 Releases。

> 运行时二进制由 PyInstaller 解包到临时目录并自动定位，**无需**在旁边放 `tools/`；
> 日志仍写入 exe 同级的 `logs/` 目录，便于长期查看。

**目标电脑需要准备什么？**

| 依赖 | 是否需预装 | 说明 |
|------|-----------|------|
| Python 解释器 | 否 | 已内嵌进 exe（含标准库与 tkinter） |
| adb / fastboot / ksud | 否 | 已内嵌，运行时自动解包定位 |
| AdbWinApi.dll 等 adb 依赖 | 否 | 已内嵌，随 adb 一并解包 |
| **小米 / 红米 USB 驱动** | **是** | 系统级驱动，无法打进 exe |

也就是说，把 `RootTool.exe` 拷贝到**任意未安装 Python、未装 adb 的 Windows 电脑**，
双击即可打开界面并按第四节「等待启动完成」后续流程操作。
唯一需要用户自行安装的是**设备对应的 USB 驱动**：

- 设备在 `adb devices` 中不出现 → 缺 ADB 驱动；
- 设备在 `fastboot devices` 中不出现 → 缺 Fastboot 驱动。

可使用小米官方驱动，或通用的 Google USB Driver（`android_winusb.inf`）。

> 提示：exe 为单文件模式，首次运行会自解压到临时目录，启动会略慢（秒级），属正常现象；
> 日志写在 exe 同级的 `logs/`，故请勿把 exe 放在只读目录（如受保护的
> `C:\Program Files`）下运行。

---

## 四、目录布局与二进制查找

程序通过 [core.py](gui/core.py) 的 `find_tool()` / `find_ksud()` 查找
`adb.exe` / `fastboot.exe` / `ksud`，**无需手工移动文件**。

**查找顺序**（命中即止）：

1. `tools/` 子目录（本仓库的默认布局）
2. 程序根目录
3. 系统 `PATH`

其中"程序根目录"的含义：

- **源码运行**：`gui/` 的**上一级目录**，即本 `code/` 目录。
- **exe 运行**：exe 自身所在目录；同时 PyInstaller 解包出的内嵌二进制
  （位于临时解包目录的 `tools/` 下）也会被自动命中。

**因此本仓库的 `tools/` 布局可直接运行，无需任何调整。**

```powershell
# 直接运行即可，二进制定位由程序自动完成
python gui\roottool.pyw
```

> 只有在二进制既不在 `tools/`、也不在根目录、且未加入 `PATH` 时，程序才会报错。

程序启动时会自检 `adb` / `fastboot` / `ksud` 三者是否就绪，缺失会弹窗提示。

### 日志位置

日志写入「可写目录」的 `logs/` 子目录：

- **源码运行**：`code/logs/`
- **exe 运行**：exe 同级的 `logs/`
- 启动时自动只保留最近 30 份日志，超出部分自动清理。

---

## 五、功能模式一览

| 模式 | 功能 | 前置条件 |
|------|------|----------|
| 1 | 设备状态检测（型号 / SDK / Root / KernelSU / Fastboot 信息） | 任意连接 |
| 2 | ADB 直连漏洞提权 | ADB 已连接 |
| 3 | Fastboot 分区提权（分步 + 一键） | Fastboot 模式 |
| 4 | SELinux 模式切换（Permissive / Enforcing） | ADB + Root，或 Fastboot |
| 5 | Root 模块管理（查看 / 禁用 / 启用 / 卸载） | ADB + Root |
| 6 | Zygisk 崩溃修复向导 + Vector 一键激活 | ADB + Root |
| 7 | KernelSU 安全模式自救（进入 / 退出） | ADB + Root |
| 8 | 模块列表备份与恢复 | ADB + Root |
| 9 | 查看运行日志 | 无 |
| 10 | Xposed 模块管理（Vector / LSPosed / 原始） | ADB + Root |
| 11 | 重启控制（软重启 / 完整重启 / Recovery / Fastboot / 关机） | ADB 已连接 |
| 12 | 相关链接（本项目 / KernelSU / Zygisk Next / Vector 仓库） | 无 |

---

## 六、界面说明与操作指引

### 6.1 界面构成

启动后窗口分为四块：

```
┌──────────────────────────────────────────────────────────┐
│ 标题栏   普通用户/管理员    ● Fastboot 未连接  ● ADB 未连接   [刷新设备] │
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│  功能模式     │              内容区                        │
│  （侧栏）     │      （随所选模式切换，含按钮与说明）        │
│  1 ~ 12      │                                           │
│              ├───────────────────────────────────────────┤
│              │              实时日志区                     │
└──────────────┴───────────────────────────────────────────┘
```

- **顶部状态栏**：左侧显示当前是否以管理员运行；右侧两个指示灯
  `● ADB 未连接/已连接`、`● Fastboot 未连接/已连接`，绿=已连接、灰=未连接；
  最右是「刷新设备」按钮。
- **左侧「功能模式」**：点击任意一项切换到对应功能页。
- **内容区**：当前模式的说明、设备信息与操作按钮。
- **底部日志区**：实时打印每条底层命令与结果，出错会以红色显示，
  是所有操作的进度与排障依据。

### 6.2 首次使用推荐流程

> 前提：手机已开启 USB 调试并授权本机；或已进入 Fastboot 模式。

| 顺序 | 操作 | 目的 |
|------|------|------|
| 1 | 模式 1「设备状态检测」→ 点检测 | 确认设备型号、SDK、SELinux、当前是否已有 Root |
| 2 | 模式 3「Fastboot 分区提权」→ [1]→[3] | **主推路径**：进 Fastboot → 下发临时 permissive → `fastboot continue` 继续启动 |
| 3 | 开机后打开手机 **KernelSU 管理器** → 点「越狱」 | 新版 KernelSU 由管理器自动完成 `ksud late-load`，即得临时 Root |
| 4 | 模式 4「SELinux 模式切换」 | 越狱后按需恢复强制模式（`Enforcing`） |
| 5 | 模式 5 / 10 | 管理 Root 模块、Xposed 模块 |
| — | 模式 11 | 需要重启时优先用「软重启」，避免临时 Root 失效 |

### 6.3 两种提权路径怎么选

- **模式 2「ADB 直连提权」**：设备**正常开机 + 已开 USB 调试**时可用，
  无需进 Fastboot，最省事。但 Android 14+ 上该漏洞多已修复，**成功率较低**。
- **模式 3「Fastboot 分区提权」**：需要设备进入 Fastboot，**成功率更高**，
  是主推路径。新版 KernelSU 只需执行到 **[3] 继续启动系统**，随后在
  **KernelSU 管理器点「越狱」**即可；不确定时可直接点「★ 一键完整流程」。
  仅在**旧版 KernelSU**（管理器无「越狱」按钮）时，才需继续展开下方「旧版流程」
  手动推送 `ksud` 并执行 `service call`。

> 无论走哪条，成功后请打开手机上的 **KernelSU 管理器**确认为「已激活」。

### 6.4 常用按钮

| 按钮 | 所在模式 | 说明 |
|------|----------|------|
| 一键提权（推送 + 提权） | 模式 2 | 自动完成推送 ksud → 漏洞利用 → 验证 |
| 仅推送 ksud | 模式 2 | 只把载荷推到 `/data/local/tmp/`，不触发漏洞 |
| 执行自定义 Shell 命令 | 模式 2 | 手动下发任意命令（**执行前会二次确认**） |
| 检查 Root 状态 | 模式 2 | 通过 `su -c id` 判断是否已获真实 uid=0 |
| 刷新设备 | 顶部状态栏 | 重新检测 ADB / Fastboot 连接状态 |

### 6.5 任务与取消

- 耗时的操作（推送、提权、一键流程）会进入「任务中」状态，
  期间内容区按钮不可点，避免并发操作。
- 任务执行中会显示「取消」入口；点击后**立即终止当前正在执行的命令**
  （包括长达数十秒的 `adb push`）。
- 命令已执行完后再点取消不再生效，属正常。

### 6.6 危险操作确认

以下操作会弹出二次确认，请务必看清提示文字再决定：

- 模式 2 的「执行自定义 Shell 命令」（任意命令会直接下发到设备）；
- 模式 5 的模块**卸载**（不可撤销，建议先「禁用」验证）；
- 模式 7 的安全模式标记写入（不可撤销）；
- 模式 11 的各类重启 / 关机。

---

## 七、设计要点

GUI 版针对早期 bat 脚本方案的常见问题做了系统性修复：

- **工作目录漂移**：启动时强制把工作目录固定到工具根目录，
  解决「双击能找到 adb、管理员运行找不到 adb」的问题。
- **变量展开缺陷**：模式 5 读取模块名不再受 `for /f` 子进程变量作用域限制。
- **返回码判断**：全部改用真实退出码判断，不再误判。
- **管理员检测**：使用 `IsUserAnAdmin()`，不依赖 `net session`。
- **路径穿越校验**：模块名改用白名单正则，`..` 等非法名一律拒绝。
- **中文编码**：Python 源码 UTF-8，命令输出按 GBK 优先解码，告别乱码。

---

## 八、核心提权流程（命令行等价写法）

工具底层执行的命令序列如下，可对照 `scripts/readme.txt` 手工复现：

```bash
# 1. 重启进入 Fastboot
adb reboot bootloader

# 2. 关闭 GPU 抢占并临时切到 Permissive
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue

# 3. 推送 KernelSU 载荷
adb push ksud /data/local/tmp/
adb shell chmod 777 /data/local/tmp/ksud

# 4. 通过 MIUI 服务漏洞 late-load 提权
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" ^
  i32 1 s16 "late-load" s16 "/sdcard/ksulog.txt" i32 60

# 5. 恢复 SELinux 强制模式
adb shell su -c setenforce 1
```

SELinux 两种模式：

- `setenforce 0` → 宽容模式（Permissive）
- `setenforce 1` → 强制模式（Enforcing）

---

## 九、注意事项

- **重复启动**：若工具已在运行，再次启动会弹窗询问是否结束旧实例；
  选择"是"关闭旧窗口并启动新的，选择"否"则保留旧窗口。
- **Fastboot 建议以管理员身份运行**，部分机型驱动需管理员权限才能识别设备。
- 所有提权 / 卸载 / 禁用操作**重启手机后才生效**。
- 模式 5 的**禁用是可逆的**（写入 `disable` 标记，文件保留），
  **卸载不可撤销**；排障建议先禁用验证，确认无误再卸载。
- 模式 7 的标记写入**不可撤销**，操作前请确认。
- 日志位于可写目录的 `logs/`（源码运行为 `code/logs/`，exe 运行为 exe 同级 `logs/`）。
  模式 9 可"清理 7 天前日志"或"清除全部日志"
  （清除全部时会保留本次会话正在写入的日志文件）。

### 无线调试配对（`scripts/Connector.cmd`）

当无法使用 USB 连接、需通过 Wi-Fi 调试时，用该向导完成配对：

1. 手机开启「开发者选项 → 无线调试」，进入后选择「使用配对码配对设备」，
   记下屏幕上显示的 **IP**、**端口** 与 **配对码**；
2. 双击运行 `scripts/Connector.cmd`，按提示依次输入上述三项；
3. 显示「授权完成 / 已连接」即成功（需 Android 11 及以上）。

> 该脚本依赖 `adb` 已在 PATH 中（或与脚本同级）。

---

## 十、故障排查

| 现象 | 原因与处理 |
|------|------------|
| 提示"未找到命令 adb / fastboot" | 二进制既不在 `tools/`、也不在根目录、且未加入 `PATH`，参见第四节 |
| 提示"找不到 ksud 文件" | `ksud` 未放到 `tools/` 或程序根目录 |
| Fastboot 信息读取失败 | 确认设备处于 Fastboot 模式、驱动正常；若设备确已进入 Fastboot，检查 `fastboot devices` 是否列出设备 |
| 设备已连接却显示未连接 | 检查是否以管理员身份运行，或驱动未正确安装 |
| 中文输出乱码 | 程序已按 GBK 优先解码，若仍异常请检查系统区域设置 |
| 长任务点"取消"无反应 | 取消会立即终止当前命令；若命令已执行完，取消不再生效属正常 |

---

## 十一、免责声明

本工具涉及解锁、提权、刷写分区等高危操作，**可能导致数据丢失、设备变砖或失去保修**。
请确保已充分理解每一步的作用，并自行承担一切风险。
