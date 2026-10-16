# 排查记录 · Zygisk 注入失败导致 Vector「未激活」

> **记录一次实机排查：临时 Root(KernelSU `late-load`)下 Vector 显示「未激活」的完整根因定位与修复**

> [!NOTE]
> **本文覆盖两个 Zygisk 实现的排查记录**（模块 id 同为 `zygisksu`，二者只能装其一）：
> - **§一~§六**：**NeoZygisk**(ptrace 实现)阶段的排查 —— 根因是 `monitor` 必须以模块目录为 CWD 启动；
>   另有 [多实例排查记录](zygisk-monitor-multi-instance.md) 补充 monitor 进程堆积问题。
> - **§七 ~ 附录**：**双框架通用**——GUI 的模式 6 已改为运行时自动识别 NeoZygisk / Zygisk Next，
>   两套命令接口、两套注入判据在此并列说明，并附 Zygisk Next 的真机实测数据。
>
> 两阶段都是**真实实机记录**，按时间先后叠放；阅读时请先确认本机当前用的是哪个框架。

| 项目 | 说明 |
|--|--|
| 📱 设备 | 红米 K70 Pro(`manet`) · 序列号 `a234db9` |
| 🤖 系统 | HyperOS 3 · Android 16(SDK 36) · SELinux `Enforcing`(漏洞切换过 Permissive) |
| ⚙️ Root 方案 | KernelSU 免解锁 · 临时 · `late-load`("越狱"模式，重启即失效) |
| 🧩 相关模块 | **Zygisk 实现**：`zygisksu`(**NeoZygisk** `v2.4-289-08080ef` 与 **Zygisk Next** `v1.5.2` 先后实测，二者只能装其一)；**Vector** `v2.2(3112)`；**HMA-OSS** `future-8ae6361d` |
| 🎯 排查目标 | 为何 `Vector 管理器` 显示「未激活」，且 `isFdAttached=false` |
| 🧭 结论(NeoZygisk 阶段) | ✅**已解决**：根因是 **NeoZygisk 的 `monitor` 必须以「模块目录 `$MODDIR`」为工作目录(CWD)启动**；此前手动/脚本启动时 CWD 错误，导致 monitor `exit=1` 或注入时找不到 `./bin/zygiskd64`，zygote 永远不被注入 |
| 📌 最终状态 | **NeoZygisk** 下：`monitor: 😋 tracing` / `zygote64: 😋 injected` / `daemon64: 😋 running`；**Zygisk Next** 下：`zygote_states: 2` / `modules64: 2,hma_oss_zygisk,zygisk_vector`。二者均使 **Vector 注入 system_server**、**HMA-OSS 实时过滤生效** |

---

## 目录

- [一、现象描述](#一现象描述)
- [二、关键概念](#二关键概念)
- [三、排查过程(按时间线)](#三排查过程按时间线)
- [四、根因分析](#四根因分析)
- [五、最终解决方案](#五最终解决方案)
- [六、完整启动流程（已实机验证 ✅）](#六完整启动流程已实机验证-)
- [七、GUI 工具的框架自动识别（通用兼容）](#七gui-工具的框架自动识别通用兼容)
- [八、相关文档](#八相关文档)
- [附:命令速查清单](#附命令速查清单)

> **一句话总结**：NeoZygisk 的 `zygisk-ptrace64 monitor` **内部全部用相对路径**(`./bin/zygiskd64`、`./module.prop`、`./lib64/libzygisk.so`)。
> 必须 **`cd /data/adb/modules/zygisksu` 后再启动**，否则 monitor 要么直接 `exit=1`，要么注入阶段 `exec daemon ./bin/zygiskd64 failed`，zygote 永远不被 `PTRACE_SEIZE`，Vector 的 bridge 自然不通。

---

## 一、现象描述

1. 用户使用临时 Root(`late-load`/"越狱")，HMA-OSS 与 Vector 两个 Zygisk 模块同时安装；
2. **HMA-OSS 正常工作**，但 **Vector 管理器显示「未激活」**（`系统框架=未注入`、`SELinux 策略=未加载`）；
3. Vector CLI 报 `isFdAttached:false`；
4. 手动执行 `su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'` 时**长时间无输出**（前台 monitor 常驻所致，见[步骤 2](#步骤-2--理解卡住的真相)）；
5. 排查中一度怀疑版本不兼容、SELinux、HMA 冲突等，最终通过 `strace` 锁定为 **monitor 启动 CWD 错误**。

**模块清单(用户声明均为所需)**：

| 模块 | 类型 | 说明 |
|--|--|--|
| `zygisksu` | Zygisk 实现 | **模块 id 固定为 `zygisksu`**，装的可能是 **NeoZygisk**(author JingMatrix，ptrace 注入)或 **Zygisk Next**(author LSPosed Developers)——**二者只能装其一**，需靠入口文件/进程名区分（见[§二](#二关键概念)） |
| `zygisk_vector` | Xposed 框架 | Vector(author JingMatrix，LSPosed 继任框架) |
| `hma_oss_zygisk` | Zygisk 模块 | HMA-OSS 隐藏 Root(author frknkrc44) |

---

## 二、关键概念

- **NeoZygisk ≠ Zygisk Next**（**两者模块 id 同为 `zygisksu`**，装在同一目录
  `/data/adb/modules/zygisksu`，只能靠入口文件/进程区分）：
  - **NeoZygisk** 命令接口：
    ```
    usage: zygisk-ptrace64 monitor | trace <pid> [--restart] | ctl <start|stop|exit> | version
    ```
  - **Zygisk Next** 命令接口：`./bin/zygiskd daemon | status | ...`（`znctl` 只做配置，带子命令仍打印帮助）。
  ⚠️ 切换框架后 `module.prop` 会**立即覆盖**，但 `bin/` 与脚本要**重启后由 KernelSU 从模块镜像重新部署**才生效 ——
  重启前看到的旧框架文件是**残留**，**不要在未重启的过渡态判定框架类型**。
- **stub zygote 机制**：NeoZygisk 的 monitor 常驻等待 `detected stub zygote at %d, promoting to parent monitor`。每当有新 zygote 出现(如被 kill 后 init 重建)，monitor 会 `PTRACE_SEIZE` 它、注入 `libzygisk.so`，再 fork injector daemon。
- **`TracerPid`**：`/proc/<zygote>/status` 中的 `TracerPid`。**非 0 = 已被 ptrace 接管(注入成功)**；`0` = 从未被注入。
- **`isFdAttached`（⚠️ 不可靠，勿作为判据）**：Vector CLI `--json status` 会输出此字段，理论上是 Zygisk 与 Vector 间 fd 通道是否建立的标志，但在本机实测中**它与实际工作状态不符**——`isFdAttached=false` 时 Vector **实际已正常注入 system_server**（`VectorDeopter` 在大量 app 进程 hook、`org.matrix.vector.ipc.IFrameworkService` binder 活跃）。原因是该 CLI 是短命进程，它看到的 `false` 只反映**自身视角**，而非 framework 进程的真实注入态。**因此判据请改用下面的「zygote64 映射 `libzygisk.so`」**。
- **注入成功的黄金判据（★ 首选，但 ⚠️ 仅适用于 NeoZygisk）**：
  ```sh
  grep -c libzygisk /proc/$(pidof zygote64)/maps   # >0 即注入成功
  ```
  这是**直接证据**（monitor 用 ptrace 把 `libzygisk.so` 载入 zygote 即完成注入），比 `TracerPid` 更权威：注入完成后 monitor 会 detach，`TracerPid` 可能回落到 0，但 `libzygisk.so` 的映射仍在。
  > [!CAUTION]
  > **Zygisk Next 不适用此判据**：它注入后会把自身 loader 从 zygote 的 maps 中 unmap（反检测），
  > 实测该 grep **恒为 0**。Zygisk Next 请改用 `zygiskd status` 的 `zygote_states: N`。详见第七章。
- **辅助判据**：`/data/adb/neozygisk/module.prop` 由 monitor **实时重写**，正常应为：
  ```
  monitor: 😋 tracing
  zygote64: 😋 injected
  daemon64: 😋 running
  ```
  > 若显示 `zygote64: ❓ unknown` / `daemon64: ❌ crashed`，说明注入链路断了。
- **CWD 依赖(本机真因)**：monitor 二进制内的资源路径**均为相对路径**，因此**启动时的工作目录决定了它能找到哪些文件**。这是本次排查的核心。

---

## 三、排查过程(按时间线)

### 步骤 1 · 确认模块与进程形态

```sh
./tools/adb.exe shell "su -c 'ls /data/adb/modules/'"      # → hma_oss_zygisk, zygisk_vector, zygisksu
./tools/adb.exe shell "su -c 'ps -A | grep zygisk-ptrace'" # → monitor 进程
```

`/data/adb/neozygisk/module.prop` 内容为 `monitor: ...` —— 确认**本阶段(§一~§六)用的是 NeoZygisk**。
（该文件仅 NeoZygisk 会创建；Zygisk Next 无此文件，其状态入口是 `./bin/zygiskd status`，见[§七](#七gui-工具的框架自动识别通用兼容)。）

### 步骤 2 · 理解「卡住」的真相

执行 `post-fs-data.sh` 后终端长时间无响应，**并非卡死**：
`monitor` 是**常驻进程**，脚本里 `zygisk-ptrace64 monitor &` 虽已后台化，但前台 shell 仍会等待其 stdout 关联的管道。

**解决**：加完整重定向即可立即返回：

```sh
nohup ./bin/zygisk-ptrace64 monitor > /dev/null 2>&1 < /dev/null &
```

### 步骤 3 · 排查 monitor 启动即退出(exit=1)

清空目录后手动前台启动 monitor，只输出 `starting monitor mode...` 就 `exit=1`，**且未创建 `init_monitor` socket**。

先排除 SELinux 与权限：

```sh
getenforce          # Enforcing(漏洞可切 Permissive)
id -Z               # u:r:ksu:s0
ls -Zd /data/adb/neozygisk
```

再用 `strace` 抓系统调用(关键突破)：

```sh
strace -f -e trace=openat,open,socket,bind,execve -o /data/local/tmp/strace_out.txt \
  ./bin/zygisk-ptrace64 monitor
```

**strace 输出(决定性)**：

```
openat(AT_FDCWD, "/data/adb/neozygisk/module.prop", O_WRONLY|O_CREAT|O_TRUNC, 0644) = 4
openat(AT_FDCWD, "./module.prop", O_RDONLY) = -1 ENOENT (No such file or directory)   ← ★
+++ exited with 1 +++
```

**解读**：monitor 先**创建** `$TMP_PATH/module.prop`(0 字节)，随即以**相对路径 `./module.prop`** 去读它 → 因当前 CWD 不是模块目录 → `ENOENT` → **直接 `exit(1)`**。

### 步骤 4 · 验证「CWD 假设」

```sh
cd /data/adb/neozygisk && export TMP_PATH=/data/adb/neozygisk && ./bin/zygisk-ptrace64 monitor
```

→ socket 创建成功、monitor 常驻。**但注入仍失败**，logcat 给出下一层错误：

```
E zygisk-core64: exec daemon ./bin/zygiskd64 failed with 2: No such file or directory   ← ★ 又一个相对路径
W ZygoteAbiManager: daemon64 (pid 29601) exited: 0x100 exited with 1
E zygisk-core64: failed to prepare injector for target 29802
```

`./bin/zygiskd64` 同样**依赖 CWD**。`/data/adb/neozygisk` 下没有 `bin/`，故失败。

### 步骤 5 · 找到正确的 CWD（真相）

`./bin/zygiskd64` 只存在于 **`/data/adb/modules/zygisksu/bin/`**。回看官方脚本：

```sh
cd "$MODDIR"                     # ← 关键的一行
[ -f $MODDIR/bin/zygisk-ptrace64 ] && $MODDIR/bin/zygisk-ptrace64 monitor &
```

**`$MODDIR = /data/adb/modules/zygisksu`**。所以 monitor 的 CWD 必须是 `$MODDIR`，此时相对路径解析为：

| 相对路径 | 解析目标 | 是否存在 |
|--|--|--|
| `./module.prop` | `/data/adb/modules/zygisksu/module.prop` | ✅ |
| `./bin/zygiskd64` | `/data/adb/modules/zygisksu/bin/zygiskd64` | ✅ |
| `./lib64/libzygisk.so` | `/data/adb/modules/zygisksu/lib64/libzygisk.so` | ✅ |

> 之前 (`cd /data/adb/neozygisk`) 也是错的——那个目录只有 `lib64/`，没有 `bin/`。

### 步骤 6 · 以正确 CWD 启动 → 注入成功

```sh
pkill -x zygisk-ptrace64
cd /data/adb/modules/zygisksu
export TMP_PATH=/data/adb/neozygisk
nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &

# 触发新 zygote 出现(kill 后 init 自动重建)
kill -9 $(pidof zygote64) $(pidof zygote)    # ★ 按 PID kill；勿用 pkill -x
```

**结果(实测，注入链路完整)**：

```
I zygisk-core64: detected stub zygote at ..., promoting to parent monitor
I zygisk-core64: attempting trace_seize on PID ...
I zygisk-core64: starting library injection for PID: ...
I zygisk-core64: successfully detached from zygote (via SEIZE), NeoZygisk active
```

`module.prop` 实时更新为：

```
monitor:    😋 tracing
zygote64:   😋 injected          ← ★
daemon64:   😋 running
Modules (2): hma_oss_zygisk, zygisk_vector
```

### 步骤 7 · 验证 Vector 与 HMA 真实生效

```sh
# zygote64 已被注入(映射含 libzygisk.so)
cat /proc/$(pidof zygote64)/maps | grep zygisk
grep TracerPid /proc/$(pidof zygote64)/status        # → 非 0

# system_server 中存在 Vector 注入的 memfd 模块
cat /proc/$(pidof system_server)/maps | grep memfd    # → /memfd:zygisk-module (deleted)
```

**logcat 证据**：

```
# Zygisk 框架工作(每个新进程都走 denylist 判断)
I zygisk-core64: [com.tencent.mm] is on the denylist
# Vector 工作(vectord 常驻 + 各进程运行 Deopter)
I vectord      : This is sticky GC
I VectorDeopter: Skipping deopt for android.app.Instrumentation#newApplication
# HMA 工作(实时过滤)
I HMA-OSS      : (PmsHookTarget34) @shouldFilterApplication: query from com.tencent.mm
```

---

## 四、根因分析

```
┌──────────────────────────────────────────────────────────────────────┐
│  真因:NeoZygisk monitor 必须以 $MODDIR(模块目录)为 CWD 启动           │
│       (其内部 ./bin/zygiskd64 / ./module.prop / ./lib64 均为相对路径) │
└──────────────────────────────────────────────────────────────────────┘

手动/GUI 以错误 CWD 启动 monitor(su -c 默认 CWD=/ )
        │
        ▼
读 ./module.prop → ENOENT → monitor 直接 exit=1
   （或侥幸活着，注入时 exec ./bin/zygiskd64 → ENOENT → 注入中断）
        │
        ▼
zygote64 从未被 PTRACE_SEIZE → TracerPid=0 → 无 libzygisk.so
        │
        ▼
Vector 的 Zygisk bridge 不通 → 管理器「未激活」
（注：CLI 会同时报 `isFdAttached=false`，但该字段本身不可靠，仅作旁证）

        ── 修复 ──
cd /data/adb/modules/zygisksu && export TMP_PATH=/data/adb/neozygisk
nohup ./bin/zygisk-ptrace64 monitor &
        │
        ▼
kill zygote64 触发重建 → monitor PTRACE_SEIZE 新 zygote → 注入 libzygisk.so
        │
        ▼
zygote64: 😋 injected · Vector 注入 system_server · HMA 实时过滤 ✅
```

**为什么「以前老版本能共存」**：并非版本差异，而是**当时 monitor 恰好以正确的 CWD(经 `post-fs-data.sh` 的 `cd "$MODDIR"`)被拉起**；后来用手动/GUI 方式启动时 CWD 不对，才暴露此问题。**无需回刷旧版 Vector**。

**排除项(经实测确认)**：
- ❌ 非 SELinux 问题(Permissive 下依然 `exit=1`；`Enforcing` 下注入成功)
- ❌ 非 Vector 版本不兼容(`v2.2(3112)` 注入成功)
- ❌ 非 `lateInject=false`(`10-09` 成功时也是该值)
- ❌ 非 HMA 与 Vector 模块冲突(两者现同时正常)
- ❌ 非权限/context(555 目录 + `u:object_r:system_file:s0` 均可正常建 socket)

---

## 五、最终解决方案

> 临时 Root 越狱后，若 monitor 未以正确方式运行，Vector 会「未激活」。按以下步骤恢复。

```sh
# ── 步骤 1:清理旧 monitor 与脏 socket ──
pkill -x zygisk-ptrace64    # ★ 用 -x；勿用 -f，会命中 su -c '...zygisk-ptrace64...' 自身
sleep 1
rm -f /data/adb/neozygisk/init_monitor

# ── 步骤 2:以 $MODDIR 为 CWD 启动 monitor(★ 核心) ──
cd /data/adb/modules/zygisksu
export TMP_PATH=/data/adb/neozygisk
nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &

# ── 步骤 3:触发 zygote 重建(init 会自动拉起新 zygote) ──
kill -9 $(pidof zygote64) $(pidof zygote)    # ★ 按 PID kill；勿用 pkill -x

# ── 步骤 4:验证 ──
grep -c libzygisk /proc/$(pidof zygote64)/maps       # ★ 首选判据：>0 = 已注入
cat /data/adb/neozygisk/module.prop
#   期望:monitor: 😋 tracing / zygote64: 😋 injected / daemon64: 😋 running
```

> [!IMPORTANT]
> **三条铁律**：
> 1. **必须 `cd $MODDIR`** 再启动 monitor，否则相对路径全错。
> 2. **不要用 `su -c 'sh .../post-fs-data.sh'` 直接跑**——`su -c` 的 CWD 是 `/`，等价于错误启动；如必须用，则先在脚本里 `cd "$MODDIR"`。
> 3. **清理 monitor 用 `pkill -x zygisk-ptrace64`**（精确进程名，避免 `-f` 自匹配自杀）；**杀 zygote 用 `kill -9 $(pidof zygote64) $(pidof zygote)`**（按 PID；实机 zygote64 的进程名是 `main`，`pkill -x zygote64` 匹配不到）。

---

## 六、完整启动流程（已实机验证 ✅）

> 从零到 HMA + Vector 双模块同时工作的完整一遍，**实测成功**。

```
① 进 Bootloader ──(漏洞切 SELinux Permissive)──▶ ② fastboot continue 重启手机
        │
        ▼
③ KernelSU 管理器 → 点「越狱」→ 进入临时 Root
        │
        ▼
   ⚠️ 此时 Zygisk/Vector 可能「未运行 / 未激活」← late-load 未触发 post-fs-data
        │
        ▼
④ 以正确 CWD 启动 monitor + 触发 zygote 重建
   （等价于 [第五节](#五最终解决方案) 的 4 步）
        │
        ▼
⑤ 等待系统界面恢复(10~30 秒)
        │
        ▼
⑥ ✅ HMA-OSS 实时过滤生效 · Vector 已注入 system_server
```

> [!TIP]
> **每次重新越狱后都可能需要执行一次**——这是临时 Root(`late-load`)的固有特性，**不是版本问题**，也**不需要刷回老版本 Vector**。

---

## 七、GUI 工具的框架自动识别（通用兼容）

图形工具的模式 6 已从「硬编码 NeoZygisk」改为**运行时自动识别**，可在
**NeoZygisk / Zygisk Next** 与 **Vector / LSPosed** 上通用。
识别在 `code/gui/core.py` 的 `detect_zygisk()` / `detect_xposed()` 中完成：

| 框架 | 入口文件（首选判据） | 常驻进程 | 状态/CLI 路径 | 激活方式 |
|--|--|--|--|--|
| **NeoZygisk** | `zygisksu/bin/zygisk-ptrace64` | `zygisk-ptrace64` | `$TMP/module.prop`（`/data/adb/neozygisk/module.prop`） | `cd $MODDIR` + `TMP_PATH` → `zygisk-ptrace64 monitor` |
| **Zygisk Next** | `zygisksu/bin/zygiskd`（软链→`zygiskd64`）/ `bin/zygiskd32` / `bin/zygiskd64` | **`zn-nsdaemon-zygote`**（注入后派生；zygiskd 管理器进程 comm 名不可见，靠 `/proc/<pid>/exe` 软链识别） | `cd $MODDIR && ./bin/zygiskd status`（**不是 `znctl status`**） | `cd $MODDIR` → `./bin/zygiskd daemon`（等价官方 `post-fs-data.sh` 末行） |
| **Vector** | `/data/adb/modules/zygisk_vector/cli` 或 `/data/adb/vector/bin/cli` | `vectord` | `cli --json status` | 随 Zygisk 注入，无需单独激活 |
| **LSPosed** | `/data/adb/lspd/bin/cli` | — | `cli --json status` | 同上 |

> [!IMPORTANT]
> **为何不能靠目录名区分**：**NeoZygisk 与 Zygisk Next 的模块 id 同为 `zygisksu`**
> （历史上都沿用 Magisk 时代的目录名），因此判定必须依赖**入口可执行文件 / 常驻进程名**。

> [!CAUTION]
> **★ 注入判据不可通用**（此结论已由真机 Zygisk Next 1.5.2 实测**推翻**早期假设）：
> - **NeoZygisk**：把 `libzygisk.so` 常驻映射在 zygote 里，可
>   `grep -c libzygisk /proc/<zygote64>/maps`（>0 即已注入）。
> - **Zygisk Next**：注入完成后会**把自身 loader（`libzn_loader.so` 等）从 zygote 的 maps 中
>   unmap 掉**（反检测），**实测该 grep 恒为 0**，不能用作判据。
>   必须改用 `./bin/zygiskd status` 输出的 **`zygote_states: N`**（N≥1 表示已注入）。
>
> 实测对比（同一台设备、Zygisk Next 已正常注入两模块）：
> `pidof zygote64` → `grep -c libzygisk` 得 **0**（漏判！），
> 而 `zygote_states` 得 **2**（正确）。故 `zygote_injected()` 必须按框架分派。

真机 Zygisk Next 1.5.2（HMA-OSS + Vector 共存）实测输出：

```
detect_zygisk      = next (Zygisk Next)
monitor_running    = True          # /proc/*/exe 软链含 zygiskd64
zygote_states      = 2             # ★ 权威注入判据（libzygisk grep 此时为 0）
inject_state       = 1
modules64          = 2,hma_oss_zygisk,zygisk_vector
modules_with_issue = 0
zygote_injected    = True
```

真机 NeoZygisk + Vector 环境实测输出：

```
detect_zygisk      = neo (NeoZygisk)
monitor_running    = True
zygote_count       = 1
zygote_injected    = True
detect_xposed      = vector (/data/adb/modules/zygisk_vector/cli)
```

✅ **两个框架分支均已真机验证**（NeoZygisk + Vector、Zygisk Next 1.5.2 + HMA-OSS/Vector）。

> **命令行等价脚本**（`code/tools/` 下三个，与 GUI 模式 6 逻辑一致）：
> - **通用** `fix_zygisk.sh` —— 运行时自动识别框架并分派下面两者；
> - **专用** `fix_neozygisk.sh` —— 仅 NeoZygisk（`fix_lspd.sh` 为同逻辑的历史别名）；
> - **专用** `fix_zygisknext.sh` —— 仅 Zygisk Next。

### 7.0 越狱后「软重启升级为完整重启」导致每次都要重走漏洞

**现象（用户报告）**：每次 `fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive` +
`fastboot continue` 进入系统后，在 KernelSU 管理器点「越狱」→ 触发 **soft reboot** →
**中途异常** → 升级为**完整 reboot** → `androidboot.selinux=permissive` 参数随完整重启丢失 →
系统回到 **Enforcing** → 无法再次越狱 → 必须重新 `adb reboot bootloader` 走一遍漏洞。

**已采集到的可疑线索**（`dmesg` / 运行时观察，尚未定位到唯一切断点）：

| 线索 | 观察 | 可能影响 |
|--|--|--|
| **SELinux 上下文未映射** | `SELinux: Context u:object_r:zygisk_file:s0 is not valid (left unmapped)` | 模块自带 `sepolicy.rule` 未被加载，late-load 下 ksud 后注入不会重放 `post-fs-data` 的 sepolicy 注入步骤 |
| **服务重复注册** | `servicemanager: Multiple instances installed?` | 越狱前残留的 ksu 域服务与越狱后新注册的服务**重复**，soft reboot 时 servicemanager 重建可能异常 |
| **旧框架残留 socket** | `/data/adb/neozygisk/{cp64.sock,init_monitor}` 在切换到 Zygisk Next 后**仍然存在** | 残留 unix socket 被新框架/init 误连，可能干扰重启流程 |

**可操作的规避步骤**（在每次重越狱前清理，降低软重启失败概率）：

```sh
# ① 切换到 Zygisk Next 后，NeoZygisk 的运行时目录/socket 已无用，清掉避免干扰
su -c 'rm -rf /data/adb/neozygisk'

# ② 清理上一轮 Zygisk Next 的运行时残留（下一次 daemon 启动会重建）
su -c 'rm -rf /data/adb/zygisksu'

# ③ 越狱完成后再由模式 6 重新激活（会重新拉起 daemon + 重建运行时目录）
```

> [!WARNING]
> 上述仅为**基于现有证据的规避建议**，**尚未真机验证能根治**软重启失败。
> 该问题的**唯一切断点仍需进一步诊断**（建议抓 `logcat -b all` 与 `/proc/last_kmsg`
> 覆盖 soft reboot 前后的完整时间窗）。**在根治前，临时 Root 下每次重越狱请预留重走漏洞的成本。**

### 7.1 激活路径的隐蔽坑（复测发现）

复测方法：先 `pkill -x zygisk-ptrace64` 杀掉 monitor（模拟「重新越狱后无注入」的初始态），
再跑模式 6，观察它能否重新拉起并注入。结果发现下列坑，其中 1–3 只在**「无 monitor 初始态」**
下才暴露（此前「已注入态」下测不出），4–7 为 Zygisk Next 分支真机复测补充：

| # | 现象 | 根因 | 修法 |
|--|--|--|--|
| 1 | `start_zygisk_daemon` 返回 `ok=False`，`monitor.log` 不生成，monitor 起不来 | 命令里 `pkill -f zygisk-ptrace64` **自匹配自杀**：该命令由 `su -c '...zygisk-ptrace64...'` 执行，`-f` 按完整命令行匹配会命中调用者自身 → su 会话被 SIGTERM（rc=143）杀掉，后续 `cd`/`nohup` 永不执行 | 改用 `pkill -x zygisk-ptrace64`（按精确进程名，不匹配命令行） |
| 2 | 僵尸/重复 zygote，或杀不干净 | `restart_zygote` 里 `pkill -f zygote64` 同样**自匹配**；且实机 zygote64 的进程名(comm)是 **`main`** —— `-x zygote64` 匹配不到，`-x main` 又会误伤大量同名进程 | 改为**按 PID 精确 kill**：`pidof zygote64` + `pidof zygote` 取 PID 后 `kill -9` |
| 3 | 模式 6 步骤 1 日志显示「超时失败」，但 monitor 其实已经起来 | KernelSU 的 `su -c` **wait 全部子进程**：只要 monitor 是活的，这条命令就永不返回（实测 `su -c 'sleep 30 & echo DONE'` 也要等满 30s）。setsid / 子 shell / `</dev/null` 都无法规避 | **不依赖返回码**：给短超时快速放行，再用 `zygisk_monitor_running()` 作真正的成功判据 |
| 4 | 手动 `su -c 'sh ./post-fs-data.sh'` **永久挂起**（实测 90s 不返回） | Zygisk Next 的 `post-fs-data.sh` 末行是 `./bin/zygiskd daemon`，**前台常驻不返回**，于是整个 su 会话永远卡住 | **不要直接执行官方脚本**：改为 `nohup ./bin/zygiskd daemon > log 2>&1 < /dev/null &` 后台化启动 |
| 5 | `znctl status` 恒打印帮助（rc=1），拿不到状态 | `znctl` 只是**配置工具**，不是状态查询入口 | 状态查询用 `cd $MODDIR && ./bin/zygiskd status` |
| 6 | `grep -c libzygisk /proc/<zygote64>/maps` 返回 **0**，误判为「未注入」 | Zygisk Next 注入完成后**把自身 loader 从 zygote maps 中 unmap**（反检测），该判据对它无效 | 按框架分派：Zygisk Next 用 `zygiskd status` 解析 `zygote_states: N` |
| 7 | 找不到 `zn-daemon` 进程，以为 daemon 没起来 | Zygisk Next **没有**名为 `zn-daemon` 的进程；注入后派生的是 `zn-nsdaemon-zygote` / `zn-nsdaemon-zygote_secondary`，且 zygiskd 管理器进程的 comm 名**不可见**（`ps` 的 NAME 列看不到） | 用 `pgrep -f zn-nsdaemon-zygote` 兜底，主判据用 `/proc/<pid>/exe` 软链是否指向 `bin/zygiskd*` |

> [!IMPORTANT]
> **`su -c` 启动持久后台进程的两个铁律**（本轮踩坑的核心）：
> 1. **清理进程不要用 `pkill -f <名字>`**，因为内联命令的命令行里含有这个名字，会自匹配自杀；
>    改用 `pkill -x`（精确进程名）或按 PID kill。
> 2. **判断后台进程是否启动成功，只能用「事后复查」，不能用命令返回码** ——
>    `su -c` 会 wait 全部子进程，只要后台进程活着，命令就永不返回（必然超时）。

### 7.2 `isFdAttached` 的实测结论（为何不能作激活判据）

真机（NeoZygisk + Vector 2.2，6 个模块已启用、框架工作正常）实测：

```json
{ "data": { "Framework Version": "2.2", "Enabled Modules": 6, ... },
  "isFdAttached": false, "success": true }
```

**框架、模块全部正常，该字段却恒为 `false`**，且打开任意 App、重查多次均不变。
这坐实了：`isFdAttached` 反映的是 CLI 这个**短命进程自身**的 fd 视角，
**与框架是否真正生效无关**，**绝不可作激活判据**。GUI 中它仅作「参考输出」展示，
真正的激活判据按框架分派：**NeoZygisk** 看 `zygote64` 是否映射 `libzygisk.so`；
**Zygisk Next** 看 `./bin/zygiskd status` 的 `zygote_states: N`（不能 grep libzygisk，见 §七 CAUTION）。

> 注：本机 Vector 的 CLI 实际位于 `/data/adb/modules/zygisk_vector/cli`；
> `core.XP_CLI[XP_VECTOR]`（`/data/adb/vector/bin/cli`）在本机不存在，
> 由 `XP_VECTOR_CLI_PATHS` 双候选机制兜住（实测 `detect_xposed` 返回第一候选路径）。
> 该常量仅在 `detect_xposed` 内部作候选使用，GUI 其余部分一律用其**返回**的路径，无死路径误用。


---

## 八、相关文档

- [维护指南](maintenance.md) — 组件更新与日常维护流程
- [多实例排查记录](zygisk-monitor-multi-instance.md) — monitor 进程堆积问题

---

## 附:命令速查清单

> **引号规则**：`adb shell "su -c '...'"`(外层双引号、内层单引号)。写错会以 shell 身份执行，出现大量 Permission denied。
> **PowerShell 陷阱**：命令含裸 `|`、括号、`grep -iE "..."` 时，写进 `.sh` 脚本 `adb push` 到 `/data/local/tmp/` 再执行最稳。

```sh
# ── 看清是谁(Zygisk 实现) ──
./tools/adb.exe shell "su -c 'cat /data/adb/neozygisk/module.prop'"     # → NeoZygisk 实时状态（仅 NeoZygisk 有）
./tools/adb.exe shell "su -c 'ls /data/adb/modules/zygisksu/bin/'"      # → zygisk-ptrace64(Neo) / zygiskd(Next)

# ── NeoZygisk 命令接口 ──
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && TMP_PATH=/data/adb/neozygisk ./bin/zygisk-ptrace64 version'"
#   monitor              常驻等待/注入
#   trace <pid> [--restart]  跟踪(并重启)指定进程
#   ctl <start|stop|exit>
#   version

# ── Zygisk Next 命令接口（★ 非 znctl；znctl 只做配置，带子命令仍打印帮助）──
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && ./bin/zygiskd daemon'"   # 启动（等价官方 post-fs-data.sh 末行）
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && ./bin/zygiskd status'"   # 查状态（权威：zygote_states: N）
./tools/adb.exe shell "su -c 'pgrep -f zn-nsdaemon-zygote'"                             # 注入后派生的 zygote 守护进程

# ── 启动 monitor/daemon(★ 二者都必须 cd $MODDIR) ──
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && TMP_PATH=/data/adb/neozygisk nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &'"
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && nohup ./bin/zygiskd daemon > /data/local/tmp/monitor.log 2>&1 &'"

# ── 注入是否成功（★ 判据按框架分派，不可通用！）──
#   NeoZygisk：zygote64 映射 libzygisk.so → >0 = 已注入
./tools/adb.exe shell "su -c 'grep -c libzygisk /proc/$(pidof zygote64)/maps'"
./tools/adb.exe shell "su -c 'cat /proc/$(pidof zygote64)/maps | grep zygisk'"
./tools/adb.exe shell "su -c 'grep TracerPid /proc/$(pidof zygote64)/status'"    # 辅助：非 0 = 正被 ptrace；注入后可能回落 0
#   Zygisk Next：上面 grep 恒为 0（注入后 unmap 自身 loader），只能看 zygote_states
./tools/adb.exe shell "su -c 'cd /data/adb/modules/zygisksu && ./bin/zygiskd status | grep -E \"zygote_states|inject_state|modules\"'"
./tools/adb.exe shell "su -c 'cat /proc/$(pidof system_server)/maps | grep memfd'"  # Vector 注入痕迹

# ── 触发 zygote 重建 ──
./tools/adb.exe shell "su -c 'kill -9 $(pidof zygote64) $(pidof zygote)'"   # ★ 按 PID 精确 kill（两框架通用）

# ── 日志 ──
./tools/adb.exe shell "su -c 'logcat -d | grep -iE \"zygisk-core|vector|hma\"'" | tail -30
```

### 踩坑记录

| 坑 | 现象 | 正解 |
|--|--|--|
| **进程名误认** | 找 `zn-daemon` / 跑 `zygisk-ptrace64` 无结果 | 若本机是 **NeoZygisk** 则用 `zygisk-ptrace64`（**无** `zn-daemon`/`zygiskd`）；若是 **Zygisk Next** 则用 `./bin/zygiskd status`（**也无** `zn-daemon`） |
| **★ CWD 错误** | monitor 只打印 `starting monitor mode...` 就 `exit=1` | 必须 **`cd /data/adb/modules/zygisksu`** 再启动(相对路径 `./module.prop`) |
| **★ CWD 错误(注入期)** | `exec daemon ./bin/zygiskd64 failed ... No such file or directory` | 同上；`./bin/zygiskd64` 仅存在于 `$MODDIR/bin/` |
| 误以为卡死 | `post-fs-data.sh` 前台无输出 | monitor 常驻所致，非故障；加 `> /dev/null 2>&1 </dev/null &` |
| monitor 堆积 | 多个 `zygisk-ptrace64` | 每次先 `pkill -x zygisk-ptrace64` 再启动 |
| **★ pkill 杀 zygote 均不可靠** | `pkill -x zygote64` 返回 `rc=1` 且进程没被杀；`pkill -f zygote64` 又会命中 `su -c '...zygote64...'` 自身 | 实机 zygote64 的进程名(comm)是 `main`，`-x` 匹配不到、`-x main` 误杀一片；改**按 PID 精确 kill**：`kill -9 $(pidof zygote64) $(pidof zygote)` |
| **误信 isFdAttached** | CLI 报 `false` 就判定 Vector 未激活 | 该字段反映 CLI 短命进程自身视角，**不可靠**；以 `zygote64` 映射 `libzygisk.so` 为准 |
| 误判 SELinux | 见 `exit=1` 就怀疑 SELinux | 实测 Permissive 下同样 `exit=1`，与 SELinux 无关 |
| 误判版本 | 想刷回旧版 Vector | 与版本无关，**无需回刷** |
| 引号错 | `adb shell su -c "..."` → Permission denied | 用 `adb shell "su -c '...'"` |
| PowerShell 吃管道 | 命令里裸 `\|` 被 PS 解析报错 | 写入 `.sh` 脚本 push 到设备执行 |
| 脚本语法 | `echo "(无监听)"` 在某些 sh 报 `unexpected '('` | 避免在 echo 中用裸括号 |
