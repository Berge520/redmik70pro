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
- **明确 `附件.zip` 的定位**：`附件.zip` 是**旧方案（命令行）的必需载荷**，
  其中 `ksud` 为本方案**专用版本**（旧流程的 `service call late-load` 依赖它，
  换官方最新版可能注入失败），故**保留并要求旧方案使用**；原「附件说明」一节
  更名为**「获取所需文件」**，并列清两类文件（`RootTool.exe` 对应新方案、
  `附件.zip` 对应旧方案）及各自获取方式；同时给出"想用最新版组件"时的官方仓库链接作为补充。
- **`docs/maintenance.md`**（原 `更新Kernel-Zygisk-Vector.md`）：补入**步骤 ⑪「一键激活」**
  （补启动 Zygisk + 重启双 zygote）—— 此前该文档讲完全流程却漏掉临时 Root
  下最关键的一步；同步更新流程总览、阶段 D 验证、常见问题与图形工具对照。
- **`docs/troubleshooting.md`**（原 `排查记录-Vector未激活.md`）：新增「九、相关文档」章节，串联 README /
  更新流程 / 新手教程三份文档。
- **`code/README.md`**：删除已不存在的 `Root_Tool.bat` 过时引用，
  小节标题由「与 bat 版的关系」改为「设计要点」。
- **`.gitignore`**：补 `小米红米临时Root专业工具_*.zip` 忽略规则，
  修正注释与规则不符。

### 构建与分发调整

- **exe 不再入库**：`code/dist/RootTool.exe`（约 19 MB）从 git 追踪中移除
  （`git rm --cached`，本地文件保留），并新增 `code/dist/` 忽略规则。
  二进制入库会使仓库随每次构建持续膨胀；发布包统一由
  [GitHub Actions](.github/workflows/build.yml) 构建后上传到 **Releases**。
- **`附件.zip` 改为随 Release 分发**：因体积约 23 MB 不宜入库（加入 `.gitignore`），
  改由 **Releases** 页 Assets 提供，且**仅随首个版本（`v0.0.1`）发布一次**
  （附件为固定的第三方组件快照，不随工具版本更新）；旧方案（命令行）继续保留支持，
  README「获取所需文件」附件链接固定指向该 Release。
- **日志忽略规则统一**：原 `code/logs/` + `code/dist/logs/` 合并为无前缀
  `logs/`，可匹配源码运行、exe 运行（仓库根 / `code/dist/`）等各层级日志目录。
