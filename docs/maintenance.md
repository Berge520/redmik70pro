# 红米 K70 Pro · 更新 KernelSU 组件 / Zygisk / Vector

> **免解锁 · 临时 Root(KernelSU `ksud` · `late-load`)环境下的更新维护指南**

| 项目 | 说明 |
|--|--|
| 📱 设备 | 红米 K70 Pro(`manet`) |
| 🤖 系统 | HyperOS 3 · Android 16 |
| ⚙️ Root 方案 | KernelSU(免解锁 · 临时 · 重启即失效) |
| 📌 本文定位 | 在 [`README.md`](../README.md) 部署基础上 → **更新 KernelSU 组件与模块** → 重新**越狱** |

> [!IMPORTANT]
> **前置条件**：已按仓库 [`README.md`](../README.md) 完成「免解锁临时 root」初始部署(adb 环境、`ksud` 注入流程均可用)。
> 本文为**更新维护流程**，不复述初始搭建步骤。

> [!TIP]
> **不想敲命令？** 仓库 [`code/`](../code/README.md) 提供了图形化工具，本流程中的
> 提权(模式 3)、Xposed 模块管理(模式 10)、Zygisk 修复(模式 6)等均有对应的一键入口。
> 可先用 GUI 完成，本文作为原理与纯命令行参考。详见 [图形工具指引](#图形工具对照)。

---

## 📖 目录

- [🧭 流程总览](#-流程总览)
- [📚 名词速查(先看这)](#-名词速查先看这)
- [📦 阶段 A · 准备(步骤 ①–②)](#-阶段-a--准备步骤---)
- [🔓 阶段 B · 越狱(步骤 ③–④)](#-阶段-b--越狱步骤---)
- [🧬 阶段 C · 模块(步骤 ⑤–⑨)](#-阶段-c--模块步骤---)
- [✅ 阶段 D · 验证(步骤 ⑩–⑪)](#-阶段-d--验证步骤--)
- [🖥️ 图形工具对照](#图形工具对照)
- [📜 完整命令流](#-完整命令流)
- [🆘 常见问题 / 排查](#-常见问题--排查)
- [↩️ 出错恢复 / 回退](#️-出错恢复--回退)
- [⚠️ 风险与免责声明](#️-风险与免责声明)
- [🔗 相关资源](#-相关资源)

---

## 🧭 流程总览

```
┌─── 阶段 A · 准备 ────────────────────────────────────────────┐
│   ① 准备新版文件  ─▶  ② 安装新版本管理器                       │
└───────────────────────────────────────────────────────────────┘
                              │
┌─── 阶段 B · 越狱(激活临时 Root)───────────────────────────────┐
│   ③ 进 fastboot · 开启宽容模式(临时参数)                      │
│   ④ 进系统 → 打开管理器 → 点击越狱 → 显示「越狱模式」(已激活)   │
└───────────────────────────────────────────────────────────────┘
                              │
┌─── 阶段 C · 模块 ────────────────────────────────────────────┐
│   ⑤ 安装 Zygisk ─▶ ⑥ 软重启 ─▶ ⑦ 查看 Zygisk：运行中 ✅       │
│   ⑧ 安装 Vector ─▶ ⑨ 再软重启                                 │
└───────────────────────────────────────────────────────────────┘
                              │
┌─── 阶段 D · 验证 ────────────────────────────────────────────┐
│   ⑩ Zygisk 运行中 ✅ │ 模块列表出现 Vector ✅                   │
│   ⚠ 若 Vector 显示「未激活」→ ⑪ 一键激活(补启动 Zygisk+重启    │
│     双 zygote，关 5 章 / code 模式 6)                          │
└───────────────────────────────────────────────────────────────┘
```

---

## 📚 名词速查(先看这)

| 术语 | 含义 |
|--|--|
| **更新 KernelSU 组件** | 本方案**免解 BL、不能刷自定义内核**，**内核本身无法也不应更新**(只能随系统 OTA)。所谓「更新 Kernel / KernelSU」实际是指：**把 KernelSU 组件升级到新版本**——替换电脑上的 **`ksud`** 二进制(用户态守护进程) + 安装配套的新管理器 |
| **Zygisk** | 注入 zygote 进程的框架；KernelSU **没有内置**，需安装 **Zygisk-Next** 模块提供 |
| **Vector** | [JingMatrix/Vector](https://github.com/JingMatrix/Vector)：**LSPosed 的现代复刻框架**，以 **Zygisk 模块**形式运行 |
| **越狱** | 本方案中指**临时 Root 激活**：fastboot 宽容 + `ksud` 注入后，管理器识别到 su 环境即「越狱成功」；**仅本次开机有效** |
| **宽容模式** | SELinux `permissive` **临时启动参数**，不写入分区，重启自动恢复 enforcing |
| **软重启** | 只重启 zygote/系统框架，**不重启内核**，临时 Root(ksud)**保留**；⚠️ **严禁完整重启** |

> [!CAUTION]
> **软重启 ≠ 完整重启！** 点「重启」(完整重启)会让越狱失效，必须重走 ③~④。

---

## 📦 阶段 A · 准备(步骤 ①–②)

### ① 准备新版本文件

先从 GitHub 下载最新 release：

| 组件 | 下载地址 | 需下载的文件 |
|--|--|--|
| **KernelSU**(ksud) | tiann/KernelSU · [releases](https://github.com/tiann/KernelSU/releases) | `ksud`(放 adb 目录) + `KernelSU-Manager_*.apk` |
| **Zygisk-Next** | Dr-TSNG/ZygiskNext · [releases](https://github.com/Dr-TSNG/ZygiskNext/releases) | `Zygisk-Next-*-*.zip`(模块) |
| **Vector** | JingMatrix/Vector · [releases](https://github.com/JingMatrix/Vector/releases) | `Vector-*-release.zip`(框架模块) + 配套管理器 App(如有) |

> [!NOTE]
> **关于 Zygisk-Next 的授权**：该组件自 `v4-0.9.2` 起已**转为闭源分发**
> (不再是 GPL-3.0)，仅提供编译好的 zip。介意者请自行评估是否使用。
>
> **关于 Vector 的命名**：`JingMatrix/Vector` 即原 **LSPosed** 的现代复刻，
> 自 v2.0 起正式由 `LSPosed` 更名为 `Vector`，两者指同一框架。

> [!TIP]
> 备用参考：[magisk.dev/modules/vector](https://magisk.dev/modules/vector) · [Vector-SR(社区维护分支)](https://github.com/byemaxx/Vector-SR)

**版本对照(当前使用 → 更新目标)**

| 组件 | 更新目标 | 官方来源 |
|--|--|--|
| KernelSU / `ksud` | GitHub Releases **最新版** | [tiann/KernelSU › Releases](https://github.com/tiann/KernelSU/releases) |
| KernelSU 管理器 | 与 `ksud` **配套**的最新版 | 同上 |
| Zygisk-Next | 最新版 | [Dr-TSNG/ZygiskNext › Releases](https://github.com/Dr-TSNG/ZygiskNext/releases) |
| Vector | 最新版 | [JingMatrix/Vector › Releases](https://github.com/JingMatrix/Vector/releases) |

> 💡 **本节讲的是「主动升级到最新版」**：各组件从**官方仓库**取最新版即可。
> 但请注意：**旧方案默认用附件包（Release 文件名 `fujian.zip`）内的专用 `ksud`**，升级属可选操作，
> 且升级后可能影响旧流程的兼容性（见下方 WARNING）。

**放置要求**

- 📌 新 `ksud` 放到 **adb.exe 所在目录**(如 `D:\adb\platform-tools`)，**覆盖旧文件**；
  - 若使用 [`code/`](../code/README.md) 图形工具，则替换 **`code/tools/ksud`** 即可，
    GUI 会自动定位新文件，无需关心 adb 目录。
- 📌 `ksud` 与 KernelSU 管理器必须**同一版本线**(官方 release 配套)；
- 📌 apk / zip 传到手机备用。

> [!WARNING]
> **并非任意新版都能免解锁使用。** 本方案的 `late-load` 依赖手机内核侧的配合，
> 新版 `ksud` 若改动了加载协议、或官方收紧了对该方式的兼容，可能**注入失败**。
> 建议：**优先沿用已验证过的版本线**；升级前先保留一份可用的旧 `ksud` 以便回退
> (见[出错恢复 / 回退](#️-出错恢复--回退))。升级失败时可换回旧版。

### ② 安装新版本管理器

- 手机**覆盖安装**新 **KernelSU 管理器** APK；
- 打开确认**版本号已更新**。

> [!NOTE]
> 管理器仅是 APK，不含内核功能；真正生效的是 `ksud` + 步骤④的注入。

---

## 🔓 阶段 B · 越狱(步骤 ③–④)

### ③ 进入 fastboot · 开启宽容模式(临时)

电脑 cmd 执行：

```sh
# ① 进入 fastboot(已授权 adb)
adb reboot bootloader

# ② 临时启动参数：关 GPU 抢占 + SELinux 宽容(不写分区)
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive

# ③ 继续启动，进系统
fastboot continue
```

> [!NOTE]
> 宽容模式是**临时启动参数**：不写入任何分区，重启即恢复强制模式。
> 若 `fastboot continue` 后卡 Logo：按住 **电源 + 音量上** 强制重启，或 `fastboot reboot`。

### ④ 进系统 → 打开管理器 → 点击越狱(激活临时 Root)

| 步骤 | 操作 | 结果 |
|--|--|--|
| 4.1 | 手机开机进系统，打开 **KernelSU 管理器** | — |
| 4.2 | 主页显示 **「已激活 / 已越狱」** | ✅ **越狱成功**(su 环境生效) |
| 4.3 | 若显示 **「未激活」** → 电脑 cmd 执行注入(**核心步骤**) | 见下方命令 |

```bat
:: ① 推送新版 ksud 到手机
adb push ksud /data/local/tmp/

:: ② 加执行权限
adb shell chmod 777 /data/local/tmp/ksud

:: ③ 调用系统服务加载(越狱)
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60
```

**验证越狱成功**

```sh
adb shell su -c id     # 期望输出 uid=0(root)
```

> [!WARNING]
> **越狱成功后不要完整重启！** 否则临时 Root 失效，须重走 ③~④。
> (可选)按 README 建议恢复强制模式：`adb shell su -c setenforce 1` — 宽容模式下 Zygisk / Vector 也能正常工作。

---

## 🧬 阶段 C · 模块(步骤 ⑤–⑨)

### ⑤ 安装 Zygisk

1. 打开 **KernelSU 管理器** → **模块**页 → 「从本地安装」；
2. 刷入 **`Zygisk-Next-*-*.zip`**：
   - 已装旧版 → 先**卸载旧版**，再刷新版(或直接覆盖)；
3. **记住优先级**：Vector 依赖 Zygisk → **先装好 Zygisk，再装 Vector**。

### ⑥ 点击管理器「软重启」

- 管理器主页 → 点击 **「软重启」**；
  - 新版管理器自带；旧版可用 README 的 **热重启模块 + `fix_lspd`** 方式；
- ⚠️ **不要点「重启」**(完整重启)！！

### ⑦ 查看 Zygisk 状态 → 运行中

1. 软重启完成后，打开 **KernelSU 管理器**；
2. 查看 **Zygisk 状态：`运行中`** ✅(或确认模块页 Zygisk-Next 已启用)；
3. 若**未运行**：
   - 确认 Zygisk-Next 已启用 → 再软重启一次；
   - 仍无效 → `adb pull /sdcard/ksulog.txt` 查日志，或卸载重刷 Zygisk-Next。

### ⑧ 安装 Vector

1. 管理器 → **模块** → 从本地安装，刷入 **`Vector-*-release.zip`**；
2. 安装配套 **Vector 管理器** App(如有)；
3. **⚠️ 刷入前必须先确认 Zygisk 已运行**(见步骤⑦)。

> [!WARNING]
> - Vector 是 LSPosed 的现代复刻框架，**覆盖刷新版 zip 即可更新**，模块数据保留；
> - **不要刷修改系统分区的 Xposed 模块**，否则变砖 🧱。

### ⑨ 再次软重启

- 管理器 → 点击 **「软重启」**。

### ⑪ 若 Vector 显示「未激活」→ 一键激活(补启动 Zygisk + 重启双 zygote)

> [!CAUTION]
> **这是本方案最容易被漏掉、也最关键的一步。**
> 临时 Root(`late-load`)是**后注入**的，系统早已越过 `post-fs-data` 阶段，
> 而 Zygisk 的守护进程(`zn-daemon`)恰恰由 `post-fs-data.sh` 拉起。
> 因此**每次重越狱后**，`zn-daemon` 不会自动启动 → 两个 zygote 都没被接管
> → Vector 自然显示「未激活」。**软重启也救不回来**，必须手动补齐下面两步。

处理顺序（先起 Zygisk，后重启 zygote，顺序不能反）：

```sh
# ① 补触发 post-fs-data，拉起 Zygisk 守护进程(zn-daemon)
adb shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'"

# ② 重启 64 位 zygote
adb shell "su -c 'setprop ctl.restart zygote'"

# ③ 重启 32 位 zygote(小米 tango 转译层，勿漏)
adb shell "su -c 'setprop ctl.restart zygote_mi_secondary'"

# ④ 验证，期望 zygote_states:2
adb shell "su -c 'sh /data/adb/modules/zygisksu/bin/zygiskd status'"
```

- 或用图形工具 [`code/`](../code/README.md) **模式 6** 的「一键激活」
  自动跑完 ①~④ 并复查状态；
- ⚠️ 重启 zygote 会短暂黑屏 10~30 秒，属正常；
- 📖 详细原理与排错见 [troubleshooting.md](troubleshooting.md)。

---

## ✅ 阶段 D · 验证(步骤 ⑩–⑪)

| 检查项 | 期望结果 |
|--|--|
| 🧬 **Zygisk 状态** | **运行中** ✅ |
| 📦 **模块列表** | **出现「Vector」** ✅ |
| (可选)Vector 管理器 | 框架已激活，可启用具体模块 |
| (可选)su 验证 | `adb shell su -c id` → `uid=0(root)` |

> [!IMPORTANT]
> **管理器显示「运行中」不代表 Vector 一定已激活。**
> 临时 Root 下若 Vector 显示「未激活」，请执行上文 **步骤 ⑪ 一键激活**，
> 并以「打开依赖该模块的 App 实测」为最终黄金标准，别只看管理器上的字。

---

## 🖥️ 图形工具对照

仓库 [`code/`](../code/README.md) 下的图形工具已把本流程多数步骤做成**点击操作**，
无需手敲命令。对照关系如下：

| 本文步骤 | GUI 对应 | 说明 |
|--|--|--|
| ③④ 越狱(推送 `ksud` + 注入) | **模式 3** Fastboot 分区提权 → 一键流程 | 自动完成"进 Fastboot → 宽容 → 推送 → 注入" |
| ① 更新 `ksud` | 替换 `code/tools/ksud` 后重新运行 | GUI 会自动定位新文件 |
| ⑥⑨ 软重启 | **模式 11** 重启控制 →「软重启」 | ⚠️ 不要点「完整重启」 |
| ⑦⑩ Zygisk / Vector 状态 | **模式 6** Zygisk 崩溃修复 | 含状态检查、修复向导与「一键激活」(补启动 Zygisk + 重启双 zygote) |
| ⑧⑩ Xposed 模块管理 | **模式 10** Xposed 模块管理 | 查询 / 禁用 / 启用 |
| 全流程排障 | **模式 9** 查看运行日志 | 含底层命令输出 |

> 📌 **`fix_lspd.sh` 的位置**：脚本本体在 [`code/tools/fix_lspd.sh`](../code/tools/fix_lspd.sh)，
> 用于 Zygisk / LSPosed 注入异常时的重新注入修复。手工用法见
> [code/scripts/readme.txt](../code/scripts/readme.txt) 第四节。

---

## 📜 完整命令流

```sh
# ── 1) fastboot → 宽容(临时) ────────────────────────────
adb reboot bootloader
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue

# ── 2) 越狱：推送新版 ksud 并加载 ────────────────────────
adb push ksud /data/local/tmp/
adb shell chmod 777 /data/local/tmp/ksud
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60

# ── 3) 验证越狱成功 ─────────────────────────────────────
adb shell su -c id     # uid=0(root)
```

---

## 🆘 常见问题 / 排查

| 现象 | 处理 |
|--|--|
| 管理器显示「未激活」 | 确认已执行步骤④注入命令；`adb shell su -c id` 验证；查 `ksulog.txt` |
| ksud 版本与管理器不匹配 | 下载**同一 release** 的 `ksud` 与管理器 APK |
| Zygisk 状态非「运行中」 | 确认 Zygisk-Next 已启用 → 软重启；无效则卸载重刷 |
| 模块列表不出现 Vector | **先装 Zygisk 且运行中**，再刷 Vector；刷后**软重启** |
| Zygisk 显示运行中但 Vector 显示「未激活」 | 临时 Root 下 `zn-daemon` 未自启 → 执行阶段 C 的 **步骤 ⑪ 一键激活**；软重启无效 |
| 误点完整重启 | 越狱失效属正常 → 重走 ③(进 fastboot)→ ④(注入越狱) |
| 升级新版 `ksud` 后注入失败 | 换回旧版 `ksud` 重试；详见[出错恢复 / 回退](#️-出错恢复--回退) |
| 卡在 MIUI Logo | 电源 + 音量上 强制重启；`fastboot reboot` 回系统 |
| 银行/支付 App 拦截 | 临时 Root 期间属预期行为 |
| 刷了修改系统分区模块 | 可能**变砖** → 通过 fastboot 刷回官方完整固件救砖 |

---

## ↩️ 出错恢复 / 回退

更新过程中若出现异常，按下表处理。**核心思路：临时 Root 重启即失效，
所以"回退"成本很低——重启到干净系统后重来即可。**

| 情形 | 处理 |
|--|--|
| 新版 `ksud` 注入失败 / 管理器仍显示「未激活」 | 换回**旧版 `ksud`**(升级前保留的那份)重新注入；旧版可用说明该版本线兼容 |
| 新版管理器异常 / 闪退 | 卸载后装回旧版管理器 APK(管理器仅是 App，不影响系统) |
| Zygisk 或 Vector 刷入后系统异常 | 进 **KernelSU 管理器安全模式**(开机时长按音量键)，或经 [`code/`](../code/README.md) **模式 7** 写入安全模式标记，禁用出问题的模块 |
| 系统卡 Logo / 无法进系统 | 按住 **电源 + 音量上** 强制重启；仍不行则 `fastboot reboot`。因全程未写分区，重启后即回到官方原厂状态 |
| 想彻底放弃临时 Root | **直接完整重启手机**即可。不修改任何系统分区，重启后临时 Root 自动失效，无需"卸载" |

> [!IMPORTANT]
> 本方案**全程不写入任何系统分区**，因此不存在"刷坏分区导致变砖"的常规刷机风险。
> 唯一的高风险操作是**刷入会修改系统分区的 Xposed 模块**(见阶段 C 警示)，
> 请务必避免。

---

## ⚠️ 风险与免责声明

1. 临时 Root(越狱)仅对**本次开机**生效，重启即还原；
2. 使用 `ksud` / KernelSU 可能触发**保修失效**、**银行 / 国密 / 支付类 App 检测**，甚至**变砖**；
3. **不要刷修改系统分区模块**；
4. 操作前请**务必**备份数据；本流程仅供学习与个人设备维护使用。

---

## 🔗 相关资源

- [KernelSU](https://github.com/tiann/KernelSU) — Root 方案内核模块(`ksud` / 管理器)
- [Zygisk-Next](https://github.com/Dr-TSNG/ZygiskNext) — KernelSU 下的 Zygisk 实现(自 v4-0.9.2 起闭源分发)
- [JingMatrix/Vector](https://github.com/JingMatrix/Vector) — LSPosed 现代复刻框架(需 Zygisk)
- [Vector-SR](https://github.com/byemaxx/Vector-SR) — Vector 社区维护分支
- [`README.md`](../README.md) — 免解锁临时 Root 初始部署与原理说明
- [`code/README.md`](../code/README.md) — 图形化工具说明(含本流程的一键入口)
- [`troubleshooting.md`](troubleshooting.md) — Vector「未激活」根因与一键恢复方案
