# 更新记录

本文件记录本项目的重要变更。版本号规范：`v主版本.次版本.修订号`。

---

## v0.0.1

初版。在原命令行方案基础上补齐 GUI 工具与文档。

### 图形工具（`code/`）

**修复**

- **Root 状态误判**：`is_root()` 原先会把 `test -x /data/adb/ksud`、
  `/sys/module` 存在等"旁证"当作已获 Root，导致"仅推送了 ksud 但提权
  失败"被误判为成功。现改为只认 `su -c id` 输出的真实 `uid=0`。
- **源码运行找不到二进制**：`find_tool()` / `find_ksud()` 现会自动探测
  `tools/` 子目录与程序根目录，源码直接运行无需再手工移动 adb / ksud。
- **取消按钮失效**：`Runner.run()` 改为轮询并支持 `proc.kill()`，
  长任务（如 `adb push`）现在可被真正中断。
- **单实例检测脆弱**：改用命名互斥体（`CreateMutexW`）作权威判据，
  窗口标题匹配仅用于定位旧窗口，不再受标题变化 / 字体缩放影响。
- **危险操作防护不足**：模式 2 的"执行自定义 Shell 命令"新增二次确认。
- **日志无限增长**：启动时自动仅保留最近 30 份日志。

**变更**

- 版本号统一为 `v0.0.1`（本项目起始版本）。
- 版本号集中定义于 `gui/core.py`，主窗口与单实例检测统一引用，避免漂移。

**新增**

- **模式 12「相关链接」**（`gui/mode_links.py`）：集中本项目、KernelSU、
  Zygisk Next、Vector 等依赖仓库的 GitHub 链接，支持一键打开。
- **应用图标**（`gui/branding.py`）：纯标准库按 BMP/PNG + ICONDIR 结构
  生成多尺寸（16~256）`brand.ico`，经 3× 超采样抗锯齿渲染；
  同一份图标既供 PyInstaller 内嵌进 exe，又在运行时注入窗口标题栏。
- `packaging/RootTool.spec`：PyInstaller 打包配置，可生成免安装单文件 exe；
  内嵌 adb / fastboot / ksud 等二进制，在未安装 Python 的电脑上可直接运行。

**界面美化**

- **macOS 桌面风格重构**：整体改为苹果浅色观感 —— 浅灰窗口底
  `#ececee` + 毛玻璃灰侧栏 `#e7e7ea` + 纯白大卡片，强调色统一为
  系统蓝 `#007aff`（状态色对齐系统绿/橙/红 `#34c759` / `#ff9f0a` / `#ff3b30`）。
- **主窗口**（`main.py`）：新增共享 UI 组件 `section / badge / dot /
  card / stat`，供各模式复用；顶栏浅色化并加底部分隔线、状态胶囊带描边、
  「刷新设备」按钮带悬停态；侧栏导航改为「序号徽章 + 标题」，选中项为
  系统蓝整块高亮，新增品牌区（Logo + 版本号）；日志区改为 macOS 终端风
  深灰底 `#1c1c1e`，按钮与滚动条细节统一。
- **表格与按钮**：Treeview 选中态改为蓝底白字；按钮统一为白底细描边 +
  悬停泛蓝，主按钮为系统蓝实心。
- **各模式页面**：`selinux` / `reboot / links / adb / backup / fastboot /
  safemode / zygisk / xposed / logs / status / modules` 全部改用新组件，
  信息卡、状态卡、分区标题与字体风格统一，消除重复的硬编码颜色。
- **应用图标**：`branding.py` 主色由品牌橙改为系统蓝渐层，与界面同源。
- **`code/启动GUI.bat`**：修复中文乱码（改以 GBK 编码保存），
  重排启动提示输出。

### 文档

- **`code/README.md`**：
  - 重写"目录布局"一节，与自动探测逻辑保持一致（删除已过时的
    `Move-Item tools\* .` 操作指引）；
  - 新增"界面说明与操作指引"：界面构成、首次使用流程、
    两种提权路径选择、常用按钮、任务与取消、危险操作确认；
  - 补全 `tools/` / `packaging/` 目录树说明；
  - 新增无线调试配对（`scripts/Connector.cmd`）使用说明。
- **`README.md`**（主文档）：
  - 重排为**图形工具优先**：新增「快速开始」四步流程（准备设备 → 获取工具 →
    一键提权 → 验证），把纯命令行方案**折叠**进
    `命令行方案（旧 · 折叠）`，日常使用无需展开；
  - **更正提权主流程**：新版 KernelSU 只需「Fastboot 下发临时 permissive →
    `continue` 启动 → 在 KernelSU 管理器点**「越狱」**」，不再把手动推送
    `ksud` / `service call` 当作主步骤；该手动链已明确归入**旧版 KernelSU**
    的折叠流程与排障条目；
  - 新增「功能模式一览」「附件说明」两节，修正已过期的模块清单
    （LSPosed → 推荐 **Vector**，并说明两者同源）；
  - 补全 `late-load` 下 Zygisk 不自启、需模式 6 一键激活的说明；
  - 精简原「测试环境 / 重要警告」等重复段落，合并进顶部信息表与免责声明。
- **`code/README.md`**：
  - 「首次使用推荐流程」补入「开机后在 KernelSU 管理器点『越狱』」一步，
    并说明新版仅需执行到模式 3 的 `[3]`、旧版才需展开手动流程。
- **`code/scripts/readme.txt`**：整理为规范的手动命令速查，去除重复命令、
  修正失效的个人路径引用、补全参数说明与排障。

### 代码结构优化：公共 helper、逐模式去重与大文件拆分

对图形工具代码做一轮系统性整理，**行为零改动**（静态检查 + 真机只读回归均通过）：

- **`code/gui/main.py` 抽取公共 UI helper**：新增 `tree3`（三列 Treeview 外框 +
  列表，统一列宽/对齐/标题）、`ops`（操作按钮栏，返回 `set_enabled` 控制器）、
  `dark_text` / `set_dark_text`（深色预览框 + 写入）、`confirm`（统一的二次确认框）；
  新增 `Danger.TButton` 样式；修正 `require_root()` 未使用的参数。
- **逐模式去重**：`mode_backup / mode_logs / mode_modules / mode_status /
  mode_selinux / mode_safemode / mode_fastboot / mode_adb / mode_reboot /
  mode_links / mode_zygisk / mode_xposed` 统一改用上述 helper，消除重复的
  深色预览、Treeview、按钮栏与确认框实现；统一命名；清理空 `on_device_change`
  与重复定义的 `_sleep_cancellable`。
- **大文件拆分**（被拆出代码落到同目录新模块，原文件保留兼容转发/继承，外部零改动）：
  - `core.py` 的 Zygisk 段拆至 **`zygisk_core.py`**、Xposed 段拆至 **`xposed_core.py`**
    （并一并迁移其依赖的 `valid_xposed_id`），`core.py` 通过 re-export 转发，
    使既有 `core.xxx` 调用不变；
  - `mode_zygisk.py` 的激活能力块拆至 **`mode_zygisk_activation.py`**
    （`ZygiskActivationMixin`，由 `ZygiskFrame` 继承）；
  - `mode_xposed.py` 的作用域编辑面板拆至 **`mode_xposed_scope.py`**
    （`XposedScopeMixin`，由 `XposedFrame` 继承）；
  - `mode_fastboot.py` 的「旧版 KernelSU 流程」折叠区构建抽为 `_build_legacy_steps()`。
- **文档同步**：`code/README.md` 更新仓库结构树（补 4 个新模块）、新增
  「Xposed 模块作用域编辑」小节与危险操作确认条目；`README.md`、
  `docs/maintenance.md` 的模式 10 说明补「模块作用域编辑」。

---

## 说明

- 工具在**本次开机内**提供临时 Root，重启后失效；不修改任何系统分区。
- 核心提权链中的 `fastboot oem set-gpu-preemption 0
  androidboot.selinux=permissive` 取自原方案，**正确性需按机型实测**，
  未在本项目中做额外验证。

### 文档修正（v0.0.1 之后）

- **`README.md`**：更正「获取工具」下载说明 —— 图形工具为**单文件 exe**
  （已内嵌 adb / fastboot / ksud），无需解压包、无需与工具文件同目录；
  下载方式指向 **Releases**，移除已不存在的
  `小米红米临时Root专业工具_*.zip` 死链。
- **明确附件包（Release 文件名 `fujian.zip`）的定位**：附件包是**旧方案（命令行）的必需载荷**，
  其中 `ksud` 为本方案**专用版本**（旧流程的 `service call late-load` 依赖它，
  换官方最新版可能注入失败），故**保留并要求旧方案使用**；原「附件说明」一节
  更名为**「获取所需文件」**，并列清两类文件（`RootTool.exe` 对应新方案、
  附件包对应旧方案）及各自获取方式；同时给出"想用最新版组件"时的官方仓库链接作为补充。
- **`docs/maintenance.md`**（原 `更新Kernel-Zygisk-Vector.md`）：补入**步骤 ⑪「一键激活」**
  （补启动 Zygisk + 重启双 zygote）—— 此前该文档讲完全流程却漏掉临时 Root
  下最关键的一步；同步更新流程总览、阶段 D 验证、常见问题与图形工具对照。
- **`docs/troubleshooting.md`**（原 `排查记录-Vector未激活.md`）：新增「九、相关文档」章节，串联 README /
  更新流程 / 新手教程三份文档。
- **`code/README.md`**：删除已不存在的 `Root_Tool.bat` 过时引用，
  小节标题由「与 bat 版的关系」改为「设计要点」。
- **`.gitignore`**：补 `小米红米临时Root专业工具_*.zip` 忽略规则，
  修正注释与规则不符。

### 注入判据与 zygote 重启修正（实测验证）

- **`code/gui/core.py`**：修正 `restart_zygote()` —— 原先用 `pkill -9 -x zygote64`
  在实机**返回 `rc=1` 且不生效**（`ps -o NAME` 会截断进程名，`-x` 精确匹配失效），
  改用 `pkill -9 -f zygote64`（匹配完整命令行），并以「**zygote64 PID 是否变化**」
  作为重启成功判据（不再依赖 pkill 返回码）。
- **注入判据更正**：新增 `zygote_injected()`，以「**`zygote64` 的 `/proc/<pid>/maps`
  是否映射 `libzygisk.so`**」为权威判据，替代 Vector CLI 的 `isFdAttached` ——
  实测该字段反映的是 CLI **短命进程自身视角**，在其报 `false` 时 Vector 实际已正常
  注入 framework（`VectorDeopter` 在大量 app 进程 hook、`IFrameworkService` binder 活跃）。
- **`code/gui/mode_zygisk.py`**：检测 / 激活流程改用上述新判据；框架文案由
  「Zygisk Next」更正为「**NeoZygisk**（框架本体）」。
- **全仓库校正框架名称**：`README.md`（模式 12 文案、附件清单、组件下载与致谢链接）、
  `code/gui/mode_links.py`（模式 12 链接项）、`.github/workflows/build.yml`
  （附件包说明）等处，把「Zygisk-Next / Dr-TSNG/ZygiskNext」统一更正为
  「**NeoZygisk** / JingMatrix/NeoZygisk」（模块 id `zygisksu`）；并移除
  README 中「重启两个 zygote（`zygote` 与 `zygote_mi_secondary`）」的过时描述，
  改为与实机一致的「重启 `zygote64`」。
- **`code/tools/fix_lspd.sh`**：整体重写 —— 旧版是基于 **Zygisk Next + LSPosed**
  的过时逻辑（`zygiskd daemon` / `service-stage` / `zygisk_lsposed` 目录），与实机
  完全不匹配；现改为 NeoZygisk 版：清理旧 monitor/socket → 以 `$MODDIR` 为 CWD
  启动 monitor → `pkill -f` 触发 zygote 重建 → 校验注入并打印结果。
- **`docs/troubleshooting.md`**：
  - `isFdAttached` 由「注入核心标志」**降级为不可靠旁证**，并新增
    「zygote64 映射 `libzygisk.so`」首选判据与 `module.prop` 辅助判据；
  - 「五、最终解决方案」步骤 3/4 改用 `pkill -f` 与新判据，「两条铁律」扩为「三条」；
  - 踩坑表新增 **`pkill -x` 失效**、**误信 isFdAttached** 两条。
- **`docs/maintenance.md`**、**`code/scripts/readme.txt`**：同步 zygote 重启命令
  （`pkill -f`）与注入验证方法（`grep -c libzygisk`）。
- **验证结果**（实机）：`pkill -9 -f zygote64` 后 zygote64 PID 变化并被 monitor 重新
  seize，`grep -c libzygisk /proc/<pid>/maps` = 3，`module.prop` 三行全 😋。


### 构建与分发调整

- **exe 不再入库**：`code/dist/RootTool.exe`（约 19 MB）从 git 追踪中移除
  （`git rm --cached`，本地文件保留），并新增 `code/dist/` 忽略规则。
  二进制入库会使仓库随每次构建持续膨胀；发布包统一由
  [GitHub Actions](.github/workflows/build.yml) 构建后上传到 **Releases**。
- **附件包改为随 Release 分发**：因体积约 23 MB 不宜入库（加入 `.gitignore`），
  改由 **Releases** 页 Assets 提供（上传后文件名显示为 `fujian.zip`），
  且**仅随首个版本（`v0.0.1`）发布一次**
  （附件为固定的第三方组件快照，不随工具版本更新）；旧方案（命令行）继续保留支持，
  README「获取所需文件」附件链接固定指向该 Release。
- **日志忽略规则统一**：原 `code/logs/` + `code/dist/logs/` 合并为无前缀
  `logs/`，可匹配源码运行、exe 运行（仓库根 / `code/dist/`）等各层级日志目录。

### Zygisk / Xposed 通用兼容（NeoZygisk + Zygisk Next · Vector + LSPosed）

把模式 6 由「硬编码 NeoZygisk」改造为**运行时自动识别框架**，同时兼容
NeoZygisk / Zygisk Next 与 Vector / LSPosed。

- **`code/gui/core.py` 新增框架探测层**：
  - `detect_zygisk()` 返回 `ZY_NEO` / `ZY_NEXT` / `ZY_NONE`。因 **NeoZygisk 与
    Zygisk Next 的模块 id 同为 `zygisksu`**（无法靠目录名区分），改以
    **入口文件**（`bin/zygisk-ptrace64` ↔ `bin/zygiskd`(软链→`zygiskd64`)）为首选判据，
    常驻进程（`zygisk-ptrace64` ↔ `zn-nsdaemon-zygote`，Zygisk Next 侧无法靠 comm 名识别时
    再兜 `/proc/<pid>/exe` 软链含 `zygiskd`）与运行时目录
    （`/data/adb/neozygisk`）为兜底。
    （**注意：Zygisk Next 没有 `zn-daemon` 进程**；`znctl` 只是配置工具，状态入口是
    `./bin/zygiskd status`。）
  - `zygisk_monitor_running()` / `zygisk_status()` / `zygisk_zygote_count()` /
    `start_zygisk_daemon()` 均按探测结果分派：NeoZygisk 走
    `zygisk-ptrace64 monitor`（`cd $MODDIR` + `TMP_PATH`），Zygisk Next 走
    `cd $MODDIR` → `./bin/zygiskd daemon`（等价官方 `post-fs-data.sh` 末行）。
  - **★ 注入判据不可通用**（真机 Zygisk Next 1.5.2 实测**推翻**早期假设）：
    NeoZygisk 把 `libzygisk.so` 常驻映射在 zygote 里，可用
    `grep -c libzygisk /proc/<zygote64>/maps` 判定；但 **Zygisk Next 注入完成后
    会把自身 loader（`libzn_loader.so` 等）从 zygote 的 maps 中 unmap 掉**
    （反检测），**实测该 grep 恒为 0**。故 `zygote_injected()` 改为**按框架分派**：
    Zygisk Next 走 `zygiskd status` 的 `zygote_states: N`。
  - `detect_xposed()` 改为返回 `(类型, CLI 路径)`，按序探测
    Vector（`zygisk_vector/cli` → `/data/adb/vector/bin/cli`）、
    LSPosed（`/data/adb/lspd/bin/cli`）、原版 Xposed；
    新增 `xposed_fd_attached()` 输出 `isFdAttached`（仅作参考）。
- **`code/gui/mode_zygisk.py`**：检测 / 激活页文案与日志改为按探测到的框架
  动态显示（框架名、常驻进程名、激活方式各不相同）；
  `KNOWN_FRAMEWORKS` 补入 Zygisk Next / LSPosed / Riru 等条目。
- **实测验证**（真机，NeoZygisk + Vector 环境）：`detect_zygisk=neo`、
  `monitor_running=True`、`zygote_count=1`、`zygote_injected=True`、
  `detect_xposed=vector (/data/adb/modules/zygisk_vector/cli)` 全部符合预期。
- **实测验证（真机 Zygisk Next 1.5.2）**：部署后跑通完整激活链路 ——
  `detect_zygisk=next`、`monitor_running=True`（`/proc/*/exe` 软链含 `zygiskd64`）、
  `zygiskd daemon` 后台化启动 12.8s 返回、`restart_zygote` 后
  `zygote_states: 0 → 2`、`inject_state:1`、
  `modules64:2,hma_oss_zygisk,zygisk_vector`、`modules_with_issue:0`
  —— **HMA-OSS 与 Vector 两模块共存无冲突**。
  此轮同时实测确认 Zygisk Next 的若干真实特征（已回写代码与文档）：
  · 无 `zn-daemon`，注入后派生 `zn-nsdaemon-zygote` / `zn-nsdaemon-zygote_secondary`；
    zygiskd 管理器进程 comm 名不可见，只能靠 `/proc/<pid>/exe` 识别；
  · 状态命令是 `./bin/zygiskd status`（**不是 `znctl status`**，`znctl` 只做配置）；
  · `post-fs-data.sh` 末行 `./bin/zygiskd daemon` 前台常驻，直接 `sh` 它会让 su 会话
    永久挂起（实测 90s 不返回），必须后台化启动；
  · `bin/` 为 `zygiskd`(软链→`zygiskd64`) / `zygiskd32` / `zygiskd64`，**无** `zygisk-ptrace64`。
- **新增 `code/tools/fix_zygisk.sh`（通用注入修复脚本）**：命令行版的运行时框架
  自动识别，逻辑与 GUI 模式 6 一致 —— 探测 NeoZygisk / Zygisk Next 后分派
  （前者 `cd $MODDIR` 启动 `zygisk-ptrace64 monitor`，后者 `cd $MODDIR` 后台化启动
  `./bin/zygiskd daemon`），再触发 zygote 重建并**按框架分派**校验注入
  （NeoZygisk 查 `libzygisk.so` 映射，Zygisk Next 查 `zygote_states`）。
  **原 `fix_lspd.sh` 保持原样、仅 NeoZygisk 专用**，
  两份脚本并存；`RootTool.spec` 已把新脚本一并打入 exe。
- **全量文档同步**（把本轮实测结论回写到全部 6 份文档，并消除过时/矛盾表述）：
  - `README.md`：附件表补 Zygisk Next 入口/命令并标注「与 NeoZygisk 二选一」、
    `fix_lspd.sh` 标注「仅 NeoZygisk 专用」；模式 6 说明补 Zygisk Next 等价动作；
    新增「软重启可能升级为完整重启」与「越狱后 `getenforce` 回 Enforcing 属正常」提示；
    安装框架步骤与 late-load 手动命令补 Zygisk Next 等价写法。
  - `code/README.md`：`fix_lspd.sh`/`fix_zygisk.sh` 说明加「仅 NeoZygisk / 自动分派」限定。
  - `docs/maintenance.md`：修正 **Zygisk Next 作者归属**（LSPosed Developers，早期源自
    Dr-TSNG，消除同文档内自相矛盾）；「本机使用 NeoZygisk」改为「两框架均已实测跑通」；
    版本对照表新增 Zygisk Next 备选行；步骤 ⑤ 补「切换框架后需重启再判定类型」；
    `grep -c libzygisk` 判据加「**仅 NeoZygisk 适用**」限定，并补 Zygisk Next 等价命令块；
    软重启 CAUTION 补「可能升级为完整重启」与 `getenforce` 正常现象。
  - `docs/zygisk-monitor-multi-instance.md`：修正「`zygiskd64` 无 `status`」条目，
    注明 **Zygisk Next 例外**（`./bin/zygiskd status` 正是权威状态入口）；
    「黄金判据」段补 Zygisk Next 的判据与 `post-fs-data.sh` 挂起警告。
  - `docs/troubleshooting.md`：命令速查清单补 Zygisk Next 命令接口（`zygiskd daemon/status`、
    `zn-nsdaemon-zygote`）、按框架分派的注入判据、按 PID kill zygote 的更稳写法。
  - 同步修正 `code/gui/core.py` 中 `detect_zygisk()` docstring 残留的 `zn-daemon`
    （逻辑早已用 `zn-nsdaemon-zygote`，仅注释陈旧）。
- **修复模式 6 激活路径的三个真机 bug**（复测：杀 monitor 模拟「无注入初始态」后重跑模式 6 发现）：
  1. `start_zygisk_daemon` 里 `pkill -f zygisk-ptrace64` **自匹配自杀** ——
     该命令由 `su -c '...zygisk-ptrace64...'` 执行，`-f` 按完整命令行匹配会命中
     调用者自身，su 会话被 SIGTERM 杀掉（rc=143），后续 `cd`/`nohup` 永不执行，
     monitor 根本起不来（表现为 `ok=False`、`monitor.log` 不生成）。
     改用 `pkill -x zygisk-ptrace64`（精确进程名）。
  2. `restart_zygote` 里 `pkill -f zygote64` **同源自匹配问题**；且实机 zygote64
     的进程名(comm)是 `main`，`-x` 匹配不到、`-x main` 又会误伤一片。
     改为**按 PID 精确 kill**（`pidof zygote64` + `pidof zygote`）。
  3. `start_zygisk_daemon` 命令**必然超时误报失败**：KernelSU 的 `su -c` 会
     wait 全部子进程，只要 monitor 是活的，该命令就永不返回（实测 `sleep 30 &`
     也要等满 30s）。setsid / 子 shell / 重定向均无法规避。改为**不依赖返回码**：
     短超时快速放行，再用「monitor 是否在跑」作真实判据 → `ok=True`。
- **复测结论**（真机 NeoZygisk + Vector）：杀 monitor 后重跑模式 6，
  `ok=True`、`monitor=True`、`injected=True`、zygote PID 变化，`PASS`；
  `fix_zygisk.sh` 亦端到端跑通（`libzygisk.so` 映射 3 次、module.prop 显示
  `injected/running`、双模块加载）。
- **端到端回归**（真机 Zygisk Next 1.5.2）：走 `core.py` 真实代码路径
  `detect_zygisk` → `zygisk_monitor_running` → `zygisk_status` →
  `zygisk_zygote_count` → `zygote_injected` → `start_zygisk_daemon`
  （幂等重启，12.8s 返回）→ `restart_zygote`（3.0s）→ 重新注入稳定为
  `zygote_states=2`，全链路 `PASS`。
- **新增记录 · 越狱后「软重启升级为完整重启」问题**（用户报告，尚在诊断）：
  临时 Root 下点「越狱」触发 soft reboot → 中途异常 → 升级完整 reboot →
  `androidboot.selinux=permissive` 丢失 → 回到 Enforcing 无法越狱 → 须重走漏洞。
  已采集可疑线索：`SELinux: Context u:object_r:zygisk_file:s0 is not valid`（模块
  `sepolicy.rule` 未加载）、`servicemanager: Multiple instances installed?`（ksu 域
  服务重复注册）、切换框架后 NeoZygisk 残留 socket `/data/adb/neozygisk/{cp64.sock,
  init_monitor}` 未清理。**唯一切断点尚未定位**，规避建议（重越狱前清理
  `/data/adb/neozygisk` 与 `/data/adb/zygisksu`）已写入 `docs/troubleshooting.md` 第七章。
- **新增 Vector 模块「生效」验证能力**（此前只能间接推断「Zygisk 注入了 → Vector 应也
  起作用」，无法直接证明某个 Xposed 模块真的 hook 了目标进程；本轮补齐直接证据链）：
  - **新增 `code/tools/verify_vector.sh`**（只读验证脚本，真机全绿）：三层证据链 ——
    L1 `vectord` 守护进程存在、L2/L3 `cli modules ls` 列出已启用模块、
    L4 `cli log cat` 中是否出现模块自己的 `[Tag]` hook 记录（★ 唯一硬判据）、
    L4b 各模块作用域规模（静默模块的间接证据）、L5 可传包名查其注入作用域。
  - **`code/gui/core.py` 新增 4 个函数**：`xposed_module_list`、`xposed_hook_evidence`、
    `xposed_module_scope`、`xposed_vectord_running`。
  - **`code/gui/mode_xposed.py`（模式 10）新增「检测模块生效」按钮**，把上述证据链
    写入模块列表的「状态」列（`已证实 hook ✓` / `生效（作用域 N）` / `无作用域`）。
- **修正模式 10 的真机 bug**：`load_modules` / `_operate` 使用的 CLI 子命令
  `modules list` **不存在**（实机报 `Unmatched argument at index 1: 'list'` 且不返回数据），
  正确子命令是 **`modules ls`**。已改用 `core.xposed_module_list()` 统一解析。
- **本轮实测确认的关键事实**（用于判据取舍）：
  · `isFdAttached` 字段**恒为 false**（模块明明在工作），不可作判据 —— 脚本与 GUI 均已忽略；
  · `kmsg.log` 是 **kernel dmesg**（与模块 hook 无关），`cli log cat` 读的是 `modules_*.log`；
  · 日志**只记录主动打 log 的模块**，静默模块（如 HyperCeiler）无记录属正常，
    故新增「作用域条目数」作为间接判据，并明确标注最终以「打开对应 App 实测」为准。
- **端到端回归**（真机 Vector v2.2 + 6 模块）：走 `core.py` 真实代码路径
  `detect_xposed`→`('vector', /data/adb/modules/zygisk_vector/cli)`、
  `xposed_vectord_running`→`True`、`xposed_module_list`→6 个、
  `xposed_hook_evidence`→`[('VoiceAssistHook', 8)]`、
  `xposed_module_scope`→`1`，与 `verify_vector.sh` 输出一致，全链路 `PASS`。

### Zygisk 修复脚本「1 通用 + 2 专用」结构

把 Zygisk 注入修复的脚本、GUI、文档、README 四层统一为
**「1 通用 + 分别 2 种专用」**，消除此前「一个脚本名（`fix_lspd.sh`）既当通用
又当专用」造成的口径混乱。

- **脚本层**（`code/tools/`）：
  - **通用** `fix_zygisk.sh`（保留）：运行时自动识别 NeoZygisk / Zygisk Next 并分派；
  - **新增专用** `fix_neozygisk.sh`：NeoZygisk 专用，命令硬编码为
    `cd $MODDIR && ./bin/zygisk-ptrace64 monitor`，开头校验框架，不符则报错；
  - **新增专用** `fix_zygisknext.sh`：Zygisk Next 专用，命令硬编码为
    `cd $MODDIR && ./bin/zygiskd daemon`，开头校验框架，不符则报错；
  - `fix_lspd.sh` 明确为 `fix_neozygisk.sh` 的**历史别名**（逻辑等价，保留仅供兼容）。
  - 三个新/改脚本头部均加「三脚本关系」ASCII 框图，互相指向。
- **GUI 层**（`code/gui/mode_zygisk.py`）：模式 6 激活区新增 `_framework_notes()`，
  在通用说明下**并列展示两框架的专用命令与注入判据**（NeoZygisk：`zygisk-ptrace64 monitor`
  + 校验 `libzygisk`；Zygisk Next：`./bin/zygiskd daemon` + 校验 `zygote_states`），
  并标注各自对应的脚本名。
- **打包**（`code/packaging/RootTool.spec`）：`_TOOL_FILES` 加入 `fix_neozygisk.sh`
  与 `fix_zygisknext.sh`。
- **文档层**：`docs/troubleshooting.md` §七、`docs/maintenance.md` 步骤 ⑪ 与图形工具对照，
  均改为「通用做法 + ① NeoZygisk 专用 + ② Zygisk Next 专用」三段式；
  `code/scripts/readme.txt`、`code/README.md`、`README.md` 同步补两专用脚本说明。

### 一致性修复：`fix_lspd.sh` 名实相符 + 清理文档中已废弃的 pkill 写法

复查时发现此前重构遗留的两处名实不符，已修正：

- **`fix_lspd.sh` 名为「`fix_neozygisk.sh` 的历史别名」，实为旧版逻辑**：
  其正文仍用 `pkill -f zygisk-ptrace64`（会自匹配自杀）与 `pkill -9 -f zygote64`
  （会命中命令自身），与 `fix_neozygisk.sh` 声称的「内容等价」不符。
  已把正文完全同步为 `fix_neozygisk.sh` 的写法（`pkill -x` + 按 PID kill +
  分框架判据 + `[0]` 前置校验），经 `diff` 确认二者除文件头（别名说明）与
  多一行 `MON_LOG` 常量外**逐字节一致**。
- **文档命令示例仍教已废弃写法**：以下「怎么做」的示例此前仍用 `pkill -f zygisk-ptrace64`
  或 `pkill -9 -f zygote64`，与本项目已验证的结论（前者自匹配自杀、后者进程名 `main`
  匹配不到）矛盾，已统一改为 `pkill -x zygisk-ptrace64` + `kill -9 $(pidof zygote64) $(pidof zygote)`：
  - `README.md` 步骤 7「late-load 提示」（原先还按框架区分两种 pkill 写法，现统一为按 PID）；
  - `docs/troubleshooting.md` §五「最终解决方案」、步骤 6、速查命令、踩坑记录表
    （原「★ pkill -x 失效 → 改用 pkill -9 -f zygote64」一行结论有误，已改写为
    「pkill 杀 zygote 均不可靠 → 按 PID kill」）；
  - `docs/zygisk-monitor-multi-instance.md` 三处清理命令。
  历史性条目（`CHANGELOG` 中各次修复记录、`troubleshooting` 踩坑表第 1 行）保留原样，
  因其记录的是「当时发生了什么、当时怎么修的」，不属于「当前推荐做法」。

---

