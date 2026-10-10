# 红米 K70 Pro — 免解锁 临时 Root（KSU）

![Build](https://github.com/Berge520/redmik70pro/actions/workflows/build.yml/badge.svg)
![Release](https://img.shields.io/github/v/release/Berge520/redmik70pro)
![License](https://img.shields.io/github/license/Berge520/redmik70pro)

本仓库内容**仅适配红米 K70 Pro（`manet` / 骁龙 8 Gen 3）**，采用**电脑免刷**（免解锁 BL、不刷机）的临时 Root 方案。

> 通过 KernelSU 的 `ksud` 经 MIUI / 澎湃 OS 系统服务接口注入并加载，在**本次开机**内获得 root 权限：
> **不修改 `/boot` 分区、不刷入自定义内核、不破坏 OTA，重启后自动失效（免解 BL）**。

| 项目 | 说明 |
|--|--|
| 📱 设备 | 红米 K70 Pro（代号 `manet`） |
| 🤖 系统 | 澎湃 OS（HyperOS 3）· Android 16 |
| ⚙️ 方案 | KernelSU `ksud` · `late-load`（免解锁 · 临时 · 重启即失效） |
| 🧰 工具 | [`code/`](code/README.md) 图形化一键工具（免安装 exe 由 Releases 提供）· 纯命令行方案 |
| ⚠️ 风险 | **高危，请先备份数据**；**严禁刷入修改系统分区的模块** 🧱 |

---

## 🚀 快速开始

**推荐路径：使用图形化工具 `code/`（免安装 exe，双击即用，无需敲命令、无需 Python 环境）。**

### 第一步 · 准备设备

1. 手机开启 **USB 调试**：
   *设置 → 我的设备 → 全部参数 → 连续点击「OS 版本」* 启动开发者选项；再 *设置 → 搜索「开发者选项」→ 打开「USB 调试」*。
2. 用数据线连接电脑，手机屏幕出现授权弹窗时勾选「始终允许」。

### 第二步 · 获取工具

| 方式 | 获取 | 说明 |
|--|--|--|
| **A（推荐）** | 到本仓库 **Releases** 页下载 `RootTool.exe`（由 GitHub Actions 构建；也可按 [code/README.md](code/README.md) 本地自行构建） | 单文件免安装，放到任意位置**双击即用**，无需另放 `adb.exe` / `fastboot.exe` / `ksud` |
| B | 源码运行 | 需 Python 3.8+，见 [code/README.md](code/README.md) |

> ⚠️ exe 已**内嵌** `adb.exe` / `fastboot.exe` / `ksud` 等二进制，**无需**与工具文件放同一目录，
> 单独拷走也能运行。首次运行可能被 Windows Defender / 杀软误报（PyInstaller 打包常见现象），
> 添加信任即可（源码完全开源可查）。
>
> 💡 **下载缓慢？** 若直连 GitHub Releases 速度慢或失败，可借助代理 / 加速镜像
> （如 `ghproxy` 类服务：在资源直链前加镜像前缀）下载。

### 第三步 · 一键提权（主推）

**核心流程（新版 KernelSU，推荐）**：

1. 工具内 **模式 3 · Fastboot 分区提权**，执行 **[1]→[3]**：
   *[1] 重启进入 Fastboot → [2] 下发 SELinux 宽松（permissive）参数 → [3] `fastboot continue` 继续启动系统*。
2. 手机重启完成后，打开手机上的 **KernelSU 管理器**，点击 **「越狱」** 按钮 —— 即可获取本次开机的临时 Root。

> 💡 新版 KernelSU 自带 `ksud`，**无需**手动推送文件或执行 `service call`；工具的模式 3 也提供「★ 一键完整流程」把 [1]→[3] 一次跑完。

**可选的后续操作**：

| 顺序 | 模式 | 操作 | 目的 |
|--|--|--|--|
| ① | **模式 4 · SELinux 模式切换** | 恢复 `Enforcing` | 越狱成功后按需恢复强制模式，提升安全性 |
| ② | **模式 6 · Zygisk / Vector 一键激活** | 点「一键激活」 | **重越狱后（装 Zygisk/Vector 时）必做**：补启动 Zygisk + 重启两个 zygote |
| ③ | **模式 5 / 10** | 按需 | 管理 Root 模块 / Xposed 模块 |

> 🔁 需要重启时**优先用模式 11 的「软重启」**（或 KernelSU 管理器的「软重启」），**不要点「完整重启」**，否则临时 Root 失效、需重走第三步。

### 第四步 · 验证

手机 **KernelSU 管理器** 或工具内 **模式 1** 检测：

- Root 状态：`uid=0(root)` ✅（管理器显示「已激活」）
- 需要 Xposed 框架时：**模式 6** 确认 `Zygisk 运行中` + **Vector 已激活** ✅

---

## 📖 目录

- [🔰 原理简述](#-原理简述)
- [🧩 功能模式一览](#-功能模式一览)
- [📦 获取所需文件](#-获取所需文件)
- [🆘 常见问题 / 排查](#-常见问题--排查)
- [↩️ 如何恢复 / 回退](#️-如何恢复--回退)
- [🛠️ 命令行方案（旧）](#️-命令行方案旧)
- [🔗 相关资源](#-相关资源)
- [📄 许可](#-许可)

---

## 🔰 原理简述

`miui.mqsas.IMQSNative` 是 MIUI / 澎湃 OS 系统自带的服务（接口编号 `21`），
存在**以 root（uid=0）执行 / 加载二进制**的利用点。本方案在不修改任何系统分区的前提下，
先让系统以 **SELinux 宽松（permissive）模式临时启动**，再借助该服务接口完成 KernelSU
的 `late-load` 越狱，获得本次开机的 root 环境：

```
Fastboot: 下发 androidboot.selinux=permissive（临时，不写入分区）
   └─ 系统以宽容模式启动
        └─ KernelSU 管理器点「越狱」
             └─ 经 miui.mqsas.IMQSNative 注入并加载 ksud (late-load)
                  └─ 本次开机内提供 su 环境（KernelSU Manager 显示「已激活」）
```

- **不修改** `/boot` `/system` `/init` → 不影响 OTA、不破坏校验、重启即还原（免解 BL）。
- 属于**漏洞利用性质**的操作，随固件版本变化，不保证在其它机型 / 固件上可用。
- 新版 KernelSU 已内置 `ksud`，此时**只需在管理器点「越狱」**；较早版本才需手动
  推送 `ksud` 并执行 `service call`（即图形工具的**旧版流程**，见下方折叠节）。
- **图形工具** `code/` 已把该流程做成点击操作，并自带设备检测、模块管理、日志查看等；完整原理与纯命令行等价写法见 [命令行方案](#️-命令行方案旧)。

---

## 🧩 功能模式一览

| 模式 | 功能 | 前置条件 |
|--|--|--|
| 1 | 设备状态检测（型号 / SDK / Root / KernelSU / Fastboot） | 任意连接 |
| 2 | ADB 直连漏洞提权 | ADB 已连接 |
| 3 | Fastboot 分区提权（分步 + 一键） | Fastboot 模式 |
| 4 | SELinux 模式切换（Permissive / Enforcing） | ADB + Root，或 Fastboot |
| 5 | Root 模块管理（查看 / 禁用 / 启用 / 卸载） | ADB + Root |
| 6 | Zygisk 崩溃修复 + **Vector 一键激活** | ADB + Root |
| 7 | KernelSU 安全模式自救（进入 / 退出） | ADB + Root |
| 8 | 模块列表备份与恢复 | ADB + Root |
| 9 | 查看运行日志 | 无 |
| 10 | Xposed 模块管理（Vector / LSPosed / 原始） | ADB + Root |
| 11 | 重启控制（软重启 / 完整重启 / Recovery / Fastboot / 关机） | ADB 已连接 |
| 12 | 相关链接（本项目 / KernelSU / Zygisk-Next / Vector） | 无 |

> 各模式的详细操作、按钮说明与两种提权路径的取舍，见 [code/README.md](code/README.md)。

---

## 📦 获取所需文件

本方案涉及**两类文件**，分别对应**两套方案**。二者**均不随仓库源码分发**（exe 由 CI 构建、附件为第三方组件），到 **Releases** 页获取：

| 文件 | 获取方式 | 用于 |
|--|--|--|
| `RootTool.exe` | 到本仓库 **[Releases](../../releases)** 页 Assets 处下载**最新版**（GitHub Actions 构建产物），或按 [code/README.md](code/README.md) 本地自行构建 | **新方案（图形工具，推荐）**，双击即用 |
| 附件包 | 到 **[v0.0.1 Release](../../releases/tag/v0.0.1)** 的 Assets 处下载，Release 中文件名显示为 **`fujian.zip`**（即本文所称「附件包」；它是固定的第三方组件快照，**仅随首个版本发布一次**，不随工具版本更新；也可按下方「内容一览」自行收集同名组件） | **旧方案（命令行）**：其中 `ksud` 等载荷需为本方案**专用版本** |

**附件包内容一览**：

| 文件 | 说明 |
|--|--|
| `KernelSU_*.apk` | KernelSU 管理器（安装到手机） |
| `ksud` | KernelSU 提权载荷，**旧方案专用版本**（推送到设备执行） |
| `Zygisk-Next-*.zip` | Zygisk 实现模块（KernelSU 刷入） |
| `Vector-*-release.zip`（或 `LSPosed-*.zip`） | Xposed 框架（LSPosed 现代复刻，推荐） |
| 热重启模块.zip | 管理器不带「软重启」时使用的热重启模块 |
| `fix_lspd.sh` | Zygisk / Xposed 注入异常时的重新注入脚本 |

> ⚠️ **走旧方案（命令行）时，请用附件包（`fujian.zip`）自带的 `ksud`，勿替换为官方最新版** ——
> 旧方案的 `service call late-load` 是针对该版本编写的，换版可能导致**注入失败**
> （见 [更新维护指南](docs/maintenance.md) 的版本告警）。

> 💡 **想用最新版组件**（不依赖旧方案）时，可到各组件官方仓库下载：
> [KernelSU](https://github.com/tiann/KernelSU/releases) ·
> [Zygisk-Next](https://github.com/Dr-TSNG/ZygiskNext/releases) ·
> [Vector](https://github.com/JingMatrix/Vector/releases)。
> 配套更新流程见 [更新维护指南](docs/maintenance.md)。

> **关于 Xposed 框架**：`JingMatrix/Vector` 即原 **LSPosed** 的现代复刻，自 v2.0 起正式更名为 Vector，两者指同一框架。
> 更新到新版时请优先选用 **Vector**（下载与对比见 [更新维护指南](docs/maintenance.md)）。

---

## 🆘 常见问题 / 排查

| 现象 | 处理 |
|--|--|
| `adb devices` 显示 `unauthorized` | 手机屏幕确认授权弹窗，勾选「始终允许」 |
| `fastboot` 不识别设备 | 检查驱动、换 USB 口 / 数据线、关闭手机助手占用；建议以管理员身份运行 |
| 注入后 `su` 不可用 | 查看加载日志：`adb pull /sdcard/ksulog.txt`，确认 `ksud` 是否加载成功 |
| KernelSU 管理器**没有「越狱」按钮** | 属**旧版 KernelSU**：需手动推送 `ksud` 并执行 `service call`（见 [命令行方案](#️-命令行方案旧) 步骤 4~6，或工具模式 3 的「旧版流程」） |
| KernelSU 显示未加载 | 确认已授予 `shell` root 权限（模式 2 / 管理器内授权） |
| 重越狱后 Vector「未激活」 | **预期现象**：`late-load` 不触发 `post-fs-data`，用**模式 6「一键激活」**修复；详见 [排查记录](docs/troubleshooting.md) |
| 卡在 MIUI Logo | 强制重启（电源 + 音量上）；可用 `fastboot reboot` 恢复 |
| 银行 / 支付 App 无法使用 | 临时 Root 后该类应用通常会检测并拦截，属预期行为 |
| 重启后失效 | **正常现象**——本次为临时 Root，重启即还原 |
| 刷了修改系统分区模块 | 可能**变砖**：请通过 fastboot 刷回官方完整固件救砖 |

---

## ↩️ 如何恢复 / 回退

由于本方案**未修改任何系统分区**，恢复方法非常简单：

```sh
# 直接重启即可，彻底还原为未 root 状态
adb reboot
# 或
fastboot reboot
```

> 操作过程不会写入 `/boot` `/system`，因此 OTA 升级、校验均不受影响；
> 但若你在临时 root 环境中**进一步修改了系统**（如刷入修改系统分区的模块），则需自行刷回官方固件恢复。

---

## 🛠️ 命令行方案（旧）

> 本节保留**纯命令行**的完整旧流程，供不使用图形工具、或需要手工排障时参考。
> 图形工具与其完全等价，日常使用**无需**阅读本节。

<details>
<summary><b>展开：纯命令行完整流程（点击）</b></summary>

### 准备

| 物品 | 说明 |
|--|--|
| 红米 K70 Pro | 已开启 USB 调试（见[快速开始](#-快速开始)） |
| 电脑 + adb 环境 | 见下方步骤 1 |
| 附件包（**必需**，见 [v0.0.1 Release](../../releases/tag/v0.0.1)，文件名 `fujian.zip`） | 含本方案**专用**的 `ksud`、KernelSU 管理器 APK、Zygisk-Next、Xposed 框架模块、`fix_lspd.sh` 等（见[获取所需文件](#-获取所需文件)） |
| USB 数据线 | 连接 K70 Pro 与电脑 |

> ⚠️ **本（旧）方案的 `ksud` 必须用附件包（`fujian.zip`）里的那个专用版本**，**不要**换成官方最新版：
> 本节步骤 4 的 `service call late-load` 是针对该版本编写的，换版可能**注入失败**
> （原因见 [更新维护指南](docs/maintenance.md) 的版本告警）。

#### 1. 电脑 adb 环境搭建（已安装可跳过）

1. **下载 adb 文件**（platform-tools），解压到某盘符，例如 `D:\adb\platform-tools`。
2. **加入环境变量**：右键「此电脑」→ 属性 → 高级系统设置 → 环境变量 → 系统变量 `Path` → 编辑 → 新建 → 粘贴解压路径 → 一路确定。
3. **验证**：`Win + R` → `cmd` → 输入 `adb --version`，出现版本号即成功。

#### 2. 放置 ksud 并安装 KernelSU 管理器

1. 把 **附件包（`fujian.zip`）中的 `ksud`** 放到 **adb.exe 所在目录**（例如 `D:\adb\platform-tools`）。⚠️ 请用附件自带的版本，勿换官方最新版。
2. 在手机上安装 **KernelSU 管理器**（附件包中的 KernelSU 管理器 APK）。

### 提权步骤

#### 3. 进入 Fastboot + 检查设备支持

K70 Pro 进入 **Fastboot 模式**（两种方式任选其一），连接电脑后打开 cmd 执行：

```sh
# 方式 1（开机状态，已授权 adb）：用 adb 重启进入 fastboot
adb reboot bootloader

# 方式 2（关机状态）：按住 开机键 + 音量下键，直到出现 FASTBOOT 界面
```

```sh
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue
```

> ✅ **支持性检测**：执行完这两条后手机开机，打开 **KernelSU 管理器**，
> **SELinux 状态为「宽容模式」** —— 则代表你的设备**支持**本方案。
>
> - `androidboot.selinux=permissive` 是临时启动参数，**不写入分区**，重启即恢复 enforcing。
> - 若 `fastboot continue` 后手机拒绝启动或卡在 Logo，请按住 **电源 + 音量上** 强制重启，或 `fastboot reboot` 回系统。

#### 4. 推送 ksud 并调用系统服务加载

手机继续连接电脑，cmd 执行：

```bat
:: 切换到 adb 文件夹目录（即安装 adb 的目录）
cd D:\adb\platform-tools

:: ① 推送文件到手机
adb push ksud /data/local/tmp/

:: ② 给文件加权限
adb shell chmod 777 /data/local/tmp/ksud

:: ③ 调用系统服务执行（核心步骤）
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60
```

**`service call` 参数说明：**

| 参数 | 含义 |
|--|--|
| `21` | IMQSNative 服务中用于加载二进制的方法编号 |
| `i32 1` | 加载开关 / 模式（1 = 启用） |
| `s16 "/data/local/tmp/ksud"` | 要加载的二进制路径 |
| `s16 'late-load'` | 加载模式：`late-load`（延迟加载） |
| `s16 '/sdcard/ksulog.txt'` | 日志输出路径 |
| `i32 60` | 超时（秒） |

#### 5. 授予 shell root 权限

**重新打开 KernelSU 管理器**，在管理器里给 **`shell`** 授权 root 权限。

#### 6. 恢复 SELinux 为强制模式

```bat
adb shell su -c setenforce 1
```

或手机 MT 管理器：KernelSU 管理器授权 MT 管理器 root → 打开「终端模拟器」执行 `su` → `setenforce 1`。

| 命令 | 作用 |
|--|--|
| `setenforce 0` | 打开宽容模式（Permissive） |
| `setenforce 1` | 打开强制模式（Enforcing） |

#### 7. 安装 Zygisk / Xposed 框架（可选）

1. 在 KernelSU 管理器里刷入附件包（`fujian.zip`）中的 **Zygisk-Next** 与 Xposed 框架模块（推荐 **Vector**）。
2. 如需**热重启**，刷入附件包（`fujian.zip`）中的**热重启模块**。
3. **重启**后按**步骤 4 ~ 6** 重新激活 KernelSU。
4. MT 管理器授予 root 权限，执行附件包（`fujian.zip`）里的 **`fix_lspd.sh`**。
5. 之后若模块需要**重启系统框架**，只需**再执行一次 `fix_lspd.sh`**。

> ⚠️ **`late-load` 模式下 Zygisk 不会自启**：重越狱后需手动补执行
> `post-fs-data.sh` 拉起 `zn-daemon`，再重启两个 zygote（`zygote` 与
> `zygote_mi_secondary`），Vector 才会激活。等价于图形工具**模式 6「一键激活」**，
> 完整原理见 [排查记录](docs/troubleshooting.md)。
>
> 🧱 **不要刷修改系统分区模块**，否则会变砖！

### 完整命令流（一键复现）

```sh
# 1) 进入 Fastboot
adb reboot bootloader

# 2) 临时启动参数（permissive + 关 GPU 抢占）并继续启动
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue

# 3) 等待系统启动后，推送并准备 ksud
adb push ksud /data/local/tmp/
adb shell chmod 777 /data/local/tmp/ksud

# 4) 注入并加载 ksud
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60

# 5) 重新打开 KernelSU Manager，给 shell 授权 root

# 6) 恢复 SELinux 并验证
adb shell su -c setenforce 1
adb shell su -c id            # 期望输出 uid=0(root)
```

</details>

> 📄 更完整的手动命令速查（含 SELinux 切换、`fix_lspd.sh`、排障）见 [code/scripts/readme.txt](code/scripts/readme.txt)。

---

## 🔗 相关资源

- [KernelSU](https://github.com/tiann/KernelSU) — 本方案使用的 Root 方案内核模块管理工具
- [Zygisk-Next](https://github.com/Dr-TSNG/ZygiskNext) — KernelSU 下的 Zygisk 实现（自 v4-0.9.2 起闭源分发）
- [JingMatrix/Vector](https://github.com/JingMatrix/Vector) — LSPosed 现代复刻框架（需 Zygisk）
- [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools) — adb / fastboot
- [mi_nobl_root（免解 BL 的 ksu + lsp 方案）](https://github.com/xunchahaha/mi_nobl_root) — 同 mqsas 漏洞原理，面向小米 15 的 LKM 内核模块（insmod）运行时加载方案
- [酷安数码玩机QvQ](https://www.coolapk.com/feed/70681212) — 小米 / 红米 免电脑 免 BL 临时 root（ksu）

### 仓库内文档

- [code/README.md](code/README.md) — 图形化工具完整说明（界面构成、操作指引、打包）
- [docs/maintenance.md](docs/maintenance.md) — 更新 KernelSU 组件 / Zygisk / Vector 的维护流程
- [docs/troubleshooting.md](docs/troubleshooting.md) — Vector「未激活」根因与一键恢复方案
- [CHANGELOG.md](CHANGELOG.md) — 更新记录

---

## 📄 许可

本项目以 [GNU AGPL-3.0](./LICENSE) 协议发布。请合理使用，遵守当地法律法规。

---

## ⚠️ 免责声明

1. 临时 root 仅对**本次开机**生效，重启后一切恢复原状。
2. 使用 `ksud` / KernelSU 可能触发**设备保修失效**、**银行 / 国密 / 支付类 App 检测**，甚至**变砖**。
3. 操作前请**务必**备份重要数据。
4. **不要刷修改系统分区模块**，否则会变砖 🧱。
5. 本方案属于**免解锁 Bootloader（免解 BL）临时 root**，**不需要**也不建议申请官方解锁；重启即还原，不触发 Bootloader 解锁校验。
6. 本项目仅供学习与个人设备维护使用，请遵守当地法律法规；执行后果自负。
