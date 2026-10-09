# 排查记录 · Vector「未激活」与 Zygisk 注入时序

> **记录一次实机排查：临时 Root(KernelSU `late-load`)下 Vector 框架显示「未激活」的完整过程**

| 项目 | 说明 |
|--|--|
| 📱 设备 | 红米 K70 Pro(`manet`) · 序列号 `a234db9` |
| 🤖 系统 | HyperOS 3 · Android 16(SDK 36) |
| ⚙️ Root 方案 | KernelSU 免解锁 · 临时 · `late-load`(重启即失效) |
| 🧩 相关模块 | Zygisk Next `1.5.0-843-5217106-release`、Vector `v2.2`、HMA-OSS(隐藏 Root)、HyperCeiler 等 |
| 🎯 排查目标 | 为何 `Vector 管理器` 显示「未激活」，且**时好时坏** |
| 🧭 结论 | ✅**已解决**：根因是**重越狱后 Zygisk(`zn-daemon`)未自动拉起**，导致两个 zygote 全未接管；手动补启动 Zygisk 并重启两个 zygote 后，Vector **完全激活** |
| 📌 最终状态 | `zygote 64 已注入(11352)` / `zygote_secondary 32 已注入(11366)` / **Vector「已激活」2.2(3080) API 102** / 系统框架「已注入」 |

---

## 目录

- [一、现象描述](#一现象描述)
- [二、关键概念](#二关键概念)
- [三、排查过程(按时间线)](#三排查过程按时间线)
- [四、根因分析](#四根因分析)
- [五、结论与验证方法](#五结论与验证方法)
- [六、最终解决方案(重越狱后一键恢复)](#六最终解决方案重越狱后一键恢复)
- [七、完整启动流程（已在实机验证 ✅）](#七完整启动流程已在实机验证-)
- [八、待办 / 下一步](#八待办--下一步)
- [附:命令速查清单](#附命令速查清单)

> **一句话总结**：重越狱后 **Zygisk 不会自启**，两个 zygote 都处于未接管状态，Vector 自然「未激活」；
> 只需**手动补启动 Zygisk(`post-fs-data.sh`)** 并**重启两个 zygote**，即可让 Vector 完整激活。

---

## 一、现象描述

1. 用户越狱后(临时 Root)使用中，出现「一越狱就启动失败 / 死机重启 / 掉越狱」问题；
2. 定位并**移除元凶模块 `RescueBrick`**(救砖模块,做 f2fs 块设备挂载)后，系统恢复稳定；
3. 稳定后检查发现：**Zygisk Next App 显示正常(运行中)**，但 **Vector 管理器显示「未激活」**；
4. 用户补充关键信息：**「有时候可以，有时候不行」** → 指向**时序/自启**问题而非固定故障；
5. **最终定位并解决**：根因是**重越狱后 Zygisk 不自启**(`late-load` 不触发 `post-fs-data`)；手动补跑 `post-fs-data.sh` 并重启两个 zygote 后，**Vector 完全激活**(详见 [六、最终解决方案](#六最终解决方案重越狱后一键恢复))。

**模块清单(用户声明均为所需)**：

| 模块 | 类型 | 说明 |
|--|--|--|
| `zygisksu` | Zygisk 实现 | Zygisk Next 本体 |
| `zygisk_vector` | Xposed 框架 | Vector(LSPosed 现代复刻) |
| `hma_oss_zygisk` | Zygisk 模块 | HMA-OSS 隐藏 Root(**不走 Vector fd 通道,可能已独立工作**) |
| `RescueBrick` | 工具模块 | **已移除**(崩溃元凶) |

---

## 二、关键概念

- **`isFdAttached`**：Vector/Zygisk 注入架构的核心标志。Zygisk 需把模块 so 通过**文件描述符(fd)** 传递给在 zygote 中注入的代码。该值为 `false` 表示 **fd 通道未建立 → 框架注入失败 → 管理器显示「未激活」**。
- **32/64 位双 zygote**：系统同时运行两个 zygote。**两个都必须被 Zygisk 接管**，Xposed 框架才算完整激活。
- **`late-load` 不自启(本机真因)**：临时 Root 的 ksud 是**手动注入**的，**不会自动触发 `post-fs-data`**；而 `zn-daemon`(Zygisk 守护进程)正是由 `post-fs-data.sh` 拉起。因此**每次重越狱后 Zygisk 都未运行，两个 zygote 均未被接管** → Vector 必然「未激活」。修复手段：手动执行一次 `post-fs-data.sh`。
- **`zygote_states`**：Zygisk 记录已接管 zygote 的状态串 `state,flag,PID,name,?`。目标值是 **`zygote_states:2`**（两个 zygote 全接管）。
- **小米双 zygote 服务名(关键坑)**：本机 `getprop` 揭示——
  - `init.svc.zygote` → 实际是 **64 位**(`ro.zygote=zygote64`，exe 为 `app_process64`)
  - `init.svc.zygote_mi_secondary` → 才是 **32 位**(exe 为 `/system_ext/bin/tango_translator`，进程名仍叫 `zygote`)
  - ⚠️ **`ctl.restart zygote` 永远重启 64 位**；重启 32 位必须用 **`ctl.restart zygote_mi_secondary`**。

---

## 三、排查过程(按时间线)

### 步骤 1 · 确认 Root 与 Zygisk 服务状态

```sh
# 确认 root(注意:外层双引号、内层单引号,否则不会以 root 执行)
./tools/adb.exe shell "su -c 'id'"
# → uid=0(root)  ✅

# 查看 zygiskd 状态(注意:进程名是 zn-daemon,不是 zygiskd)
./tools/adb.exe shell "su -c 'ps -A -o PID,PPID,NAME | grep -iE \"zygote|zn-daemon\"'"
```

**结果**：

```
zn-daemon 有哪些实例(早期观察到 4 个:PID 6119/6148/7752/7773)
root: u:r:ksu:s0  ✅
```

`zygiskd status`(关键字段)：

```
version:1.5.0-843-5217106-release
zygote_states:0          ← 按时间线：早期未接管任何 zygote（最终已为 2）
inject_state:1
root_status:✅KernelSU (32601)
modules64:2,hma_oss_zygisk,zygisk_vector
modules32:2,hma_oss_zygisk,zygisk_vector
modules_with_issue:0
```

> **修正记录**：排查中曾因进程名错误(`grep zygiskd` 无结果)误判「服务未启动」；实际进程名为 **`zn-daemon`**，服务正常。此教训记入附录。

### 步骤 2 · 排除崩溃残留(ksud SIGABRT)

在 `/data/adb/ksu/log/` 中发现关键崩溃：

```
F/libc: Fatal signal 6 (SIGABRT) in tid 9391, pid 9391
F/DEBUG: >>> me.weishu.kernelsu:root:0 <<<
Abort message: 'Check failed: system_class_loader != nullptr
                 java.lang.ExceptionInInitializerError'
```

伴随大量：

```
Bad file descriptor (os error 9)
# 涉及 su_compat / kernel_umount / selinux_hide / sulog / adb_root 等 feature 全部失败
```

**判断**：这是 KernelSU 在 `late-load` 状态下的用户态进程崩溃，会**打断 Vector 的激活流程**。

### 步骤 3 · 打开 Vector 管理器(无需独立 APK)

用户反馈「不知道如何打开 Vector(未安装 APK)，平时靠 KernelSU 的『执行』按钮或通知栏」。
解析 `action.sh` 逻辑发现：**「执行」按钮会先弹一个 bugreport 警告 Activity，点“确定”后 `am start` 拉起管理器**。

等价命令：

```sh
./tools/adb.exe shell "su -c 'am start -c org.matrix.vector.manager.LAUNCH_MANAGER com.android.shell/.BugreportWarningActivity'"
```

> 手机上点「确定」即进入管理器。该警告是 MIUI 对 shell Activity 的固定提示，**不会真的生成/上传 bugreport**。

### 步骤 4 · 检查 fd 附加状态(定位病根)

```sh
./tools/adb.exe shell "su -c 'sh /data/adb/modules/zygisk_vector/cli --json status'"
```

**结果(决定性)**：

```json
{
  "Enabled Modules": 8,
  "isFdAttached": false          ← ★ 病根
}
```

8 个模块全部为 Xposed 模块(`com.sevtinge.hyperceiler` 等),**全部因 `isFdAttached=false` 而失效**。

### 步骤 5 · 检查 SELinux 与 binder 服务(排除法)

```sh
# SELinux 拒绝日志
./tools/adb.exe shell "su -c 'dmesg | grep -i avc | grep -iE \"vector|xposed|lspd\"'"
# → 无输出:无 AVC 拒绝  ✅(排除 SELinux 拦截)

# binder 服务查询
./tools/adb.exe shell "su -c 'service list | grep -iE \"vector|xposed|lsposed\"'"
# → 无输出:Vector 的 binder 服务未注册  ❌(解释了管理器为何连不上)
```

### 步骤 6 · 通过重启 zygote 尝试修复(方案 A)

**前提**：用户确认「能承受 zygote 重启风险(只要不黑砖)」。

```sh
# 说明:Android 已移除 ctl 可执行文件,用 setprop 触发 init 重启服务
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote'"
```

**重启前后对比**：

| 项 | 重启前 | 重启后 |
|--|--|--|
| 32 位 zygote(服务 `zygote_mi_secondary`) | PID **1552** | PID **1552**(**未变!**) |
| 64 位 zygote(服务 `zygote`) | PID 14554 | PID **18551**(已重启) |
| `webview_zygote` | 15596 | 19583(跟随重启) |
| 新进程 | — | 出现 `zn-nsdaemon-zygote`(PID 18798) |
| `isFdAttached` | false | **仍 false** |
| `init.svc.zygote` | running | **(空)** ← init 服务表状态异常 |

**关键发现**：`setprop ctl.restart zygote` **只重启了 64 位，32 位 zygote(PID 1552)纹丝不动**。

### 步骤 7 · 复查 zygiskd 接管状态

```
zygote_states:1
zygote_state_0:1,0,18551,zygote,3     ← 只记录了 1 个:PID 18551(zygote64)
```

**确认**：Zygisk **只接管了 64 位 zygote**，**32 位 zygote(PID 1552)从未被接管**。

### 步骤 8 · 揭秘服务名映射(关键突破)

多次 `ctl.restart zygote` 后 **PID 1552 始终不变**，遂深挖 `getprop`：

```
[init.svc.zygote]: [running]              debug_pid = 5282  (64位)
[init.svc.zygote_mi_secondary]: [running] debug_pid = 1552  (32位)
[ro.zygote]: [zygote64]                   ← 系统主 zygote 是 64 位
[ro.vendor.mi_support_zygote32_lazyload]: [false]

/proc/1552/exe -> /system_ext/bin/tango_translator   ← 32位是 tango 转译层!
/proc/5282/exe -> /system/bin/app_process64          ← 这才是真 zygote
```

**结论**：`zygote` 服务名 = **64 位**；**32 位服务名是 `zygote_mi_secondary`**。之前的 `ctl.restart zygote` **全打在了 64 位上**。

### 步骤 9 · 重启真正的 32 位服务(修复成功)

```sh
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote_mi_secondary'"
```

**结果(重大进展)**：

```
zygote_states:2                                  ← ★ 从 1 → 2!
zygote_state_0:1,0,5282,zygote,3                 ← 64位
zygote_state_1:1,1,21906,zygote_secondary,0      ← ★ 32位已接管!

32位 zygote: PID 1552 → 21906  (成功重启)
```

**Zygisk 首次同时接管两个 zygote**（`zygote_states:2`）。

### 步骤 10 · 但 isFdAttached 仍为 false

稍等后复查：

```json
{
  "Enabled Modules": 8,
  "isFdAttached": false          ← 仍未附加
}
```

进程确认管理器(`org.matrix.vector.manager`)与 `vectord` 均存活。
**说明**：单纯重启 zygote 尚不足以让 fd 附加生效——**还需 Zygisk(`zn-daemon`)本身处于运行态**。重越狱后 Zygisk 未自启,是本次「未激活」的真正原因(见步骤 11)。

### 步骤 11 · 补启动 Zygisk → Vector 完全激活(最终修复)

重越狱后发现 **`zn-daemon` 未运行**,执行 `post-fs-data.sh` 补启动,再重启两个 zygote：

```sh
./tools/adb.exe shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'"
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote'"
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote_mi_secondary'"
```

**结果(实测,最终状态)**：

| 判据 | 结果 |
|--|--|
| Zygisk 接管数 | `zygote_states:2` |
| zygote 64 | 已注入(PID **11352**)✅ |
| zygote_secondary 32 | 已注入(PID **11366**)✅ |
| Vector | **已激活** `2.2(3080) · API 102` ✅ |
| 系统框架 | 已注入 ✅ |
| SELinux / Dex | 已加载 / 支持 ✅ |

**至此 Vector 完整激活,问题闭环。**

---

## 四、根因分析

```
┌────────────────────────────────────────────────────────────────────┐
│  真因:重越狱后 Zygisk(zn-daemon)未自启 → 两个 zygote 全未接管        │
└────────────────────────────────────────────────────────────────────┘

临时 Root(late-load)重越狱
        │  ksud 手动注入,不触发 post-fs-data
        ▼
zn-daemon 未启动  ← 之前误判为“zygote 时序竞争”
        │
        ▼
zygote 64(11352) 与 zygote_secondary 32(11366) 全部未被接管
        │
        ▼
Vector 无法注入 → isFdAttached=false → 管理器显示「未激活」

        ── 修复 ──
手动执行 post-fs-data.sh(拉起 zn-daemon)
        │
        ▼
分别重启两个 zygote(zygote / zygote_mi_secondary)
        │
        ▼
zygote 64 已注入 + zygote 32 已注入
        │
        ▼
Vector「已激活」2.2(3080) API 102 · 系统框架「已注入」✅
```

**为什么「有时候行有时候不行」**：
取决于**越狱后是否有人/自动化补齐了 Zygisk 启动与 zygote 重启**。补齐了 → 激活 ✅；没补齐 → 未激活 ❌。并非版本不兼容，也非固定故障。

**排除项(经实测确认)**：
- ❌ 非 SELinux 问题(无 AVC 拒绝)
- ❌ 非 Vector 版本不兼容(同一版本已成功激活,`v2.2 3080` 在 Android 16 / API 36 上正常工作)
- ❌ 非 KernelSU 不支持(32601 正常)
- ℹ️ 日志中的 `Failed to inject VectorService into system_server` / `NoSuchFieldException: systemui_is_cached` 属 Vector **版本探测的 fallback 分支**(先试新字段失败后降级),**不影响最终注入**;实测注入仍成功。
- ⚠️ 干扰因素:KernelSU `:root:0` 的 SIGABRT 会**加剧**故障,必要时重注入 ksud

---

## 五、结论与验证方法

**结论**：Vector 未激活 = **重越狱后 Zygisk 未自启,两个 zygote 均未被接管**。

**已达成(实测)**：

| 判据 | 结果 |
|--|--|
| Zygisk 接管 zygote 数 | `zygote_states:2` ✅ |
| zygote 64 | 已注入(PID 11352)✅ |
| zygote_secondary 32 | 已注入(PID 11366)✅ |
| Vector 状态 | **已激活** `2.2(3080) · API 102` ✅ |
| Vector 系统框架 | 已注入 ✅ |
| SELinux 策略 | 已加载 ✅ |
| Dex 优化器包装 | 支持 ✅ |

**关键重启命令**：

```sh
# ❌ 错误:重启的是 64 位
setprop ctl.restart zygote

# ✅ 正确:重启 32 位(小米 tango 转译 zygote)
setprop ctl.restart zygote_mi_secondary
```

**验证成功的判据**：

```sh
# 1. Zygisk 应运行且接管 2 个 zygote
./tools/adb.exe shell "su -c 'ps -A | grep zn-daemon'"
./tools/adb.exe shell "su -c '/data/adb/modules/zygisksu/bin/zygiskd status'"
#   zygote_states:2   ← 已达成 ✅

# 2. 打开 Vector 管理器应显示「已激活」,系统状态四项全 ✅
```

---

## 六、最终解决方案(重越狱后一键恢复)

> 每次重越狱(late-load)后 **Zygisk 不会自启**,按以下顺序执行即可恢复 Vector。

```sh
# ── 步骤 1:手动补触发 post-fs-data,拉起 zn-daemon ──
./tools/adb.exe shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'"

# ── 步骤 2:确认 zn-daemon 已启动 ──
./tools/adb.exe shell "su -c 'ps -A | grep zn-daemon'"

# ── 步骤 3:重启 64 位 zygote ──
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote'"

# ── 步骤 4:重启 32 位 zygote(小米 tango 转译层) ──
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote_mi_secondary'"

# ── 步骤 5:验证接管数为 2 ──
./tools/adb.exe shell "su -c '/data/adb/modules/zygisksu/bin/zygiskd status'"
#   zygote_states:2  ✅
```

> [!IMPORTANT]
> **为何必须手动补 `post-fs-data.sh`**：`late-load` 模式下 ksud 是**后注入**的,系统早已过了 `post-fs-data` 阶段,
> 该事件**不会自动重放**。Zygisk Next 依赖 `post-fs-data` 阶段启动 `zn-daemon`,因此必须手动补执行。

---

## 七、完整启动流程（已在实机验证 ✅）

> 从零到 Vector 激活的完整一遍，**实测成功**。第六节是该流程中「步骤④」的具体命令。

```
① 进 Bootloader ──(漏洞进入宽容/SELinux Permissive 模式)──▶ ② 重启手机
        │
        ▼
③ KernelSU 管理器 → 点「越狱」→ 自动软重启(zygote 重启)
        │
        ▼
   ⚠️ 此时 Zygisk 与 Vector 均「未运行 / 未激活」← 预期现象，不是故障
        │  （late-load 未触发 post-fs-data，zn-daemon 未拉起）
        ▼
④ 打开本工具 → 模式6 →「一键激活」← 等价于 [第六节](#六最终解决方案重越狱后一键恢复) 的 5 条命令
        │
        ▼
⑤ 等待系统界面恢复(10~30 秒)
        │
        ▼
⑥ ✅ Zygisk 与 Vector 成功激活
```

> [!TIP]
> **每次重新越狱后都要执行一次「一键激活」**——这是临时 Root(late-load)的固有特性，非版本问题。

---

## 八、待办 / 下一步

- [x] **将该流程固化为脚本**：越狱后一键执行「补启动 Zygisk + 重启两个 zygote」
      → 已实现为图形工具 **模式 6「一键激活」**（`code/gui/mode_zygisk.py`，底层见 `core.start_zygisk_daemon` / `core.restart_zygote`）
- [ ] 观察 KernelSU `:root:0` SIGABRT 是否复现，必要时重新注入 ksud

> [!NOTE]
> **判断模块是否真生效的黄金标准**:不看管理器状态,而是**打开依赖该模块的 App 实测**(如 HMA 隐藏 Root 后,用检测类 App 验证)。
> 一个模块是否工作在 App 启动时才最终确定。
>
> **分流判断**:HMA 属 **Zygisk 模块**(不走 Vector 的 fd 通道),可能已独立工作;**8 个 Xposed 模块**才依赖 Vector 激活。

---

## 附:命令速查清单

> **引号规则**:`adb shell "su -c '...'"`(外层双引号、内层单引号)。写错会导致命令以 shell 身份执行,出现大量 Permission denied。

```sh
# ── 基础状态 ──
./tools/adb.exe shell "su -c 'id'"                                  # 确认 root
./tools/adb.exe shell "su -c 'getenforce'"                          # SELinux 模式

# ── 进程/服务 ──
./tools/adb.exe shell "su -c 'ps -A -o PID,PPID,NAME | grep -iE \"zygote|zn-daemon\"'"
./tools/adb.exe shell "su -c 'getprop init.svc.zygote'"                 # 64位
./tools/adb.exe shell "su -c 'getprop init.svc.zygote_mi_secondary'"    # 32位

# ── 认清 zygote 服务名与真实身份(关键) ──
./tools/adb.exe shell "su -c 'getprop | grep -i zygote'"     # 各服务名 + debug_pid
./tools/adb.exe shell "su -c 'ls -la /proc/<PID>/exe'"        # 看 exe:tango转译 or app_process64

# ── Zygisk 状态 ──
./tools/adb.exe shell "su -c '/data/adb/modules/zygisksu/bin/zygiskd status'"

# ── 重越狱后补启动 Zygisk(关键) ──
./tools/adb.exe shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'"

# ── Vector 状态(关键:isFdAttached) ──
./tools/adb.exe shell "su -c 'sh /data/adb/modules/zygisk_vector/cli --json status'"

# ── SELinux 拒绝 / binder 服务 ──
./tools/adb.exe shell "su -c 'dmesg | grep -i avc'"
./tools/adb.exe shell "su -c 'service list | grep -iE \"vector|xposed\"'"

# ── 打开 Vector 管理器(手机上点“确定”进入) ──
./tools/adb.exe shell "su -c 'am start -c org.matrix.vector.manager.LAUNCH_MANAGER com.android.shell/.BugreportWarningActivity'"

# ── 重启 zygote ──
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote'"                  # ❌ 64位
./tools/adb.exe shell "su -c 'setprop ctl.restart zygote_mi_secondary'"     # ✅ 32位
```

### 踩坑记录

| 坑 | 现象 | 正解 |
|--|--|--|
| 进程名错 | `grep zygiskd` 无结果 → 误判服务未启动 | 真实进程名为 **`zn-daemon`** |
| **服务名错** | `ctl.restart zygote` 后 32 位 PID 不变 | 32 位服务名是 **`zygote_mi_secondary`** |
| **误认 32 位身份** | 以为 PID 1552 是普通 zygote | 其 exe 是 **`tango_translator`**(小米 32 位转译层) |
| 引号错 | `adb shell su -c "..."` → 大量 Permission denied | 用 `adb shell "su -c '...'"` |
| `ctl` 不存在 | 脚本内 `ctl.restart` 返回 127 | 改用 `setprop ctl.restart <svc>` |
| PowerShell 吃管道 | 命令里裸 `|` 被 PS 解析报错 | 写入 `.sh` 脚本 push 到设备执行 |
| bugreport 弹窗 | 点「取消」→ 管理器没启动 | 点「**确定**」才会 `am start` 拉起管理器 |
| **重越狱后 Zygisk 未自启** | 重越狱后 Vector 直接「未激活」 | `late-load` 不触发 `post-fs-data`,须**手动跑 `post-fs-data.sh`** 拉起 `zn-daemon` |
| **日志误读** | 见 `Failed to inject VectorService` 就判「兼容性 bug」 | 该行属版本探测 fallback,**注入实测成功**,勿据此下结论 |
