# 排查记录 · Zygisk monitor 多实例堆积与手动执行陷阱

> **记录一次实机排查：手动执行 `post-fs-data.sh` 导致 `zygisk-ptrace64` monitor 进程堆积成 7 个的完整过程与收敛方法**

| 项目 | 说明 |
|--|--|
| 📱 设备 | 红米 K70 Pro(`manet`) |
| 🤖 系统 | HyperOS 3 · Android 16(SDK 36) |
| ⚙️ Root 方案 | KernelSU 免解锁 · 临时 · `late-load`(**重启即失效，不可用 `adb reboot` 兜底**) |
| 🧩 相关模块 | **NeoZygisk**(`zygisksu`，JingMatrix) |
| 🎯 排查目标 | 为何 `adb shell "su -c 'sh .../post-fs-data.sh'"` **长时间无反应**；如何确认 Zygisk 是否正常 |
| 🧭 结论 | ✅**已解决**：命令「卡住」是 **monitor 常驻**所致，属正常现象；真正的隐患是**手动重复执行脚本叠加了 7 个 monitor**，用 `pkill` + 重跑一次收敛为 **1 个** |
| 📌 最终状态 | `zygisk-ptrace64` **仅 1 个**(PID 876，`do_epoll_wait`) · `init_monitor` socket 正常 · `lib64/` 权限 `dr-xr-xr-x`(555) |

---

## 目录

- [一、现象描述](#一现象描述)
- [二、关键概念](#二关键概念)
- [三、排查过程(按时间线)](#三排查过程按时间线)
- [四、根因分析](#四根因分析)
- [五、结论与验证方法](#五结论与验证方法)
- [六、最终解决方案(不重启收敛为 1 个)](#六最终解决方案不重启收敛为-1-个)
- [七、为什么本方案不能靠重启兜底](#七为什么本方案不能靠重启兜底)
- [八、相关文档](#八相关文档)
- [附:命令速查清单](#附命令速查清单)

> **一句话总结**：`post-fs-data.sh` 末尾以 `monitor &` 启动的是**常驻进程**，前台 shell 会一直等它 → 命令「卡住」是**正常**的；
> 但**手动反复执行**该脚本会**叠加多个 monitor**，需用 `pkill` 清理后**只重跑一次**收敛为单个实例。

> [!NOTE]
> 本文记录的是 **NeoZygisk**（进程名 `zygisk-ptrace64`）的实机案例，命令均按其接口编写。
> 若使用 **Zygisk Next**，其入口是 `bin/zygiskd`（无 `zygisk-ptrace64`，也**无** `zn-daemon`
> 进程；注入后派生 `zn-nsdaemon-zygote`），请勿套用本文命令；
> 图形工具**模式 6** 可自动识别框架并分派（见 [troubleshooting.md · 七](troubleshooting.md)）。

---

## 一、现象描述

1. 用户在临时 Root(KernelSU)环境下执行：

   ```powershell
   adb shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh'"
   ```

   **等了很久没有任何输出，也没有返回命令行**，看起来像「卡住 / 没反应」。

2. 用户查看该脚本内容后确认：脚本逻辑为拷贝 `libzygisk.so`、建 `neozygisk` 目录、设置权限，**末尾启动 monitor**。
3. 另开终端查进程，发现 `zygisk-ptrace64` **多达 7 个**，且数量明显异常。

**脚本末尾关键片段**：

```sh
if [ -f $MODDIR/bin/zygisk-ptrace64 ];then
$MODDIR/bin/zygisk-ptrace64 monitor &
elif [ -f $MODDIR/bin/zygisk-ptrace32 ];then
$MODDIR/bin/zygisk-ptrace32 monitor &
fi
```

---

## 二、关键概念

- **`zygisk-ptrace64 monitor`**：Zygisk 的**常驻监控进程**，负责等待被 `ptrace` 以完成注入。它**必须长期驻留**，因此**永不主动退出**。
- **`&` 不等于「命令立即返回」**：`&` 只是把进程放到后台，但 `su -c 'sh ...'` 会**等待该 shell 会话的子进程**；monitor 不退出 → shell 不返回 → 表现为「卡住」。
- **`init_monitor`**：`/data/adb/neozygisk/` 下的 **Unix domain socket**(`srwxr-xr-x`)，是 monitor 与注入端协调的通道，**它是 monitor 已启动并初始化成功的证据**。
- **`zygiskd64`**：monitor 用于**注入**的可执行文件(`$MODDIR/bin/zygiskd64`)，由 monitor 在注入 zygote 时 `exec`。⚠️ 它是**注入器**、**不是**一个常驻的「状态查询守护进程」，**没有** `status` 子命令。
- **一个 monitor 才正常**：多个 monitor 会**互相争抢 ptrace**，可能导致注入失败或行为异常。
- **`do_epoll_wait`**：进程处于该状态表示**空闲等待事件**，是 monitor 的健康态。

---

## 三、排查过程(按时间线)

### 步骤 1 · 查看脚本内容，定位「卡住」位置

用户 `cat` 脚本后确认：**拷贝/权限部分都是快操作**，唯一会长驻的是末尾的 `monitor &`。

**判断**：命令不返回 = **monitor 常驻**，而非脚本报错或死循环。

### 步骤 2 · 另开终端确认 monitor 是否真的起来了

```powershell
adb shell "pgrep -f zygisk-ptrace64"
adb shell "ps -A | grep -i zygisk"
```

**结果(异常)**：

```
root  11268  1  ... do_epoll_wait  S  zygisk-ptrace64
root  20350  1  ... do_epoll_wait  S  zygisk-ptrace64
root  21959  1  ... do_epoll_wait  S  zygisk-ptrace64
root  22073  1  ... do_epoll_wait  S  zygisk-ptrace64
root  22378  1  ... do_epoll_wait  S  zygisk-ptrace64
root  30686  1  ... do_epoll_wait  S  zygisk-ptrace64
root  31200  1  ... do_epoll_wait  S  zygisk-ptrace64
root  31428  31200  ... __skb_wait_for_more_packets  S  zygiskd64
```

**结论**：monitor **在正常运行**(`do_epoll_wait` 为健康态)，但**有 7 个**，远超正常的 1 个。

### 步骤 3 · 确认目录结构正常

```powershell
adb shell "su -c 'ls -l /data/adb/neozygisk'"
```

**结果(正常)**：

```
srwxr-xr-x 1 root root    0 ... init_monitor
dr-xr-xr-x 2 root root 3452 ... lib64
-rw-r--r-- 1 root root  190 ... module.prop
```

- `init_monitor` 存在 → monitor 初始化成功 ✅
- `lib64/` 为 `dr-xr-xr-x`(555) → 与脚本 `create_sys_perm` 预期一致 ✅

### 步骤 4 · logcat 无输出，属正常

```powershell
adb logcat -s "zygisk-sh" | Select-String "zygisk"
# → 无输出
```

**说明**：脚本里的 `log -p i -t "zygisk-sh"` **只在遍历其他带 zygisk 的模块时**才打印；
本机若无此类模块，该循环不触发，**logcat 为空 ≠ 报错**。

### 步骤 5 · 一条无效的 PowerShell 命令(与设备无关)

用户在 **Windows PowerShell** 中执行了：

```powershell
nohup $MODDIR/bin/zygisk-ptrace64 monitor >/dev/null 2>&1 &
```

**问题**：这是 **Linux 语法**跑在 **Windows** 上——`$MODDIR` 为空、`nohup`/`/dev/null`/`&` 都不适用；
结果只创建了一个**很快结束的无效后台 Job**，**对手机没有任何作用**。应 `Get-Job | Remove-Job -Force` 清理。

### 步骤 6 · 判断「叠出来的」还是「自动再生」

```powershell
adb shell "ps -A -o PID,PPID,ETIME,CMD | grep -i zygisk-ptrace64"
```

- 若**时间差极大 / 仍在增长** → 系统反复拉起(需治本)；
- 若**启动时间接近、手动跑几次就是几个** → 手动重复执行所致(清一次即可)。

本机表现为后者：**7 个 = 手动执行了多次脚本叠加**。

### 步骤 7 · 收敛为单个(不重启)

```powershell
adb shell "su -c 'pkill -x zygisk-ptrace64'"                 # ① 全杀（-x 精确进程名，避免 -f 自匹配自杀）
adb shell "ps -A | grep -i zygisk-ptrace64"                   # ② 确认清空(无输出)
adb shell "su -c 'sh /data/adb/modules/zygisksu/post-fs-data.sh' > /dev/null 2>&1 &"   # ③ 只重跑一次
adb shell "ps -A | grep -i zygisk-ptrace64"                   # ④ 验证
```

**结果(成功)**：

```
root  876  1  ... do_epoll_wait  S  zygisk-ptrace64
```

- monitor **只剩 1 个** ✅
- `pkill` 后连续两次查询均为空 → **排除了「系统自动再生」**的可能。

### 步骤 8 · 复查 socket 与清理本地 Job

```powershell
adb shell "su -c 'ls -l /data/adb/neozygisk'"
# init_monitor 仍在，时间戳更新为新一次执行 ✅
Get-Job | Remove-Job -Force
```

---

## 四、根因分析

```
┌────────────────────────────────────────────────────────────────────┐
│  现象 A：命令「卡住」  ← 主因：monitor 常驻，前台 shell 等它        │
│  现象 B：monitor 有 7 个 ← 主因：手动重复执行 post-fs-data.sh       │
└────────────────────────────────────────────────────────────────────┘

【现象 A】adb shell "su -c 'sh post-fs-data.sh'"
        │  & 仅后台化，su/shell 仍等待会话子进程
        ▼
zygisk-ptrace64 monitor 常驻(do_epoll_wait)
        │
        ▼
shell 永不返回 → 看起来「没反应 / 卡住」  ← 设计使然，非故障

【现象 B】重复手动执行同一脚本 N 次
        │  每次末尾都 monitor &
        ▼
N 个 monitor 并存 → 互相争抢 ptrace → 潜在注入异常
        │
        ▼
pkill 全杀 + 只重跑一次 → 收敛为 1 个 ✅
```

**为何不能靠「重启」解决**：本次为 **临时 Root(`late-load`)**，**重启即失效**；
`adb reboot` 会让 root 丢失，需重新走越狱流程，故必须**在本次开机内**用 `pkill` 收敛。

---

## 五、结论与验证方法

**结论**：

| 现象 | 判定 |
|--|--|
| 命令长时间不返回 | **正常** —— monitor 常驻，shell 在等它 |
| monitor 数量 | 正常应 **1 个**；多个 = 手动重复执行叠加 |
| `logcat -s zygisk-sh` 为空 | **正常** —— 该 log 仅在遍历其他 zygisk 模块时打印 |
| `init_monitor` / `lib64/` 存在 | **健康** 证据 |

**验证 Zygisk 是否正常的黄金判据**：

```powershell
# 期望只看到 1 个 zygisk-ptrace64，状态为 do_epoll_wait
adb shell "ps -A | grep zygisk-ptrace64"
```

> [!CAUTION]
> 上述判据是 **NeoZygisk 专用**。**Zygisk Next** 没有 `zygisk-ptrace64` 进程，
> 其注入判据也不同（注入后会 unmap 自身 loader，`grep -c libzygisk` 恒为 0）——
> 请改用 **`cd /data/adb/modules/zygisksu && ./bin/zygiskd status`**，看 `zygote_states: N`（N≥1 已注入）。
> 另：Zygisk Next 的 `post-fs-data.sh` 末行是 `./bin/zygiskd daemon`（**前台常驻**），
> 手跑它会让 su 会话**永久挂起**（实测 90s 不返回），切勿照搬本文 NeoZygisk 的收敛命令。

---

## 六、最终解决方案(不重启收敛为 1 个)

```powershell
# ── 步骤 1:全杀现有 monitor ──
adb shell "su -c 'pkill -x zygisk-ptrace64'"

# ── 步骤 2:确认已清空(应无输出) ──
adb shell "ps -A | grep zygisk-ptrace64"

# ── 步骤 3:只启动一次 monitor(★ 必须以 $MODDIR 为 CWD) ──
adb shell "su -c 'cd /data/adb/modules/zygisksu && TMP_PATH=/data/adb/neozygisk nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &'"

# ── 步骤 4:验证只剩 1 个 ──
adb shell "ps -A | grep zygisk-ptrace64"
```

```powershell
# ── 可选:确认 socket 正常 ──
adb shell "su -c 'ls -l /data/adb/neozygisk'"
```

> [!IMPORTANT]
> **不要手动反复执行 `post-fs-data.sh`**。该脚本本应由 KernelSU 在开机 `post-fs-data` 阶段**自动调用一次**；
> 手动执行会造成 **monitor 重复启动**、**反复删建 `neozygisk`**，可能破坏已注入进程。
> 日常只需检查 `ps -A | grep zygisk-ptrace64` **是否为 1 个**即可。

> [!CAUTION]
> **不要再直接 `sh .../post-fs-data.sh` 来启动 monitor**。`su -c` 的 CWD 是 `/`，而 monitor **内部全用相对路径**
> (`./bin/zygiskd64`、`./module.prop`)，会因找不到文件而 `exit=1`。**必须 `cd /data/adb/modules/zygisksu` 后再启动**。
> 详见 [troubleshooting.md](troubleshooting.md)。

> [!TIP]
> **想让命令立即返回**，只需把 monitor 的输入输出全部重定向并后台化：
> `... nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &`
> —— 这不会改变 monitor 常驻的本质，只是不再让前台 shell 等它。

---

## 七、为什么本方案不能靠重启兜底

| 常规做法 | 本方案是否可用 | 原因 |
|--|--|--|
| `adb reboot` 让系统重跑一次 | ❌ **不可用** | 临时 Root(`late-load`)**重启即失效**，需重新越狱 |
| `pkill` + 重跑一次脚本 | ✅ **推荐** | 在本次开机内即可收敛，不丢 root |
| 改脚本加 `pgrep` 哨兵 | ⚠️ 非必须 | 经查**不存在自动再生**，本机无需改脚本 |

> 若将来确认出现「monitor 自动再生」，再考虑在脚本启动前加
> `if ! pgrep -f zygisk-ptrace64 >/dev/null; then ... fi` 防止重复启动。

---

## 八、相关文档

- [README.md](../README.md) — 免解锁临时 Root 初始部署与原理说明
- [troubleshooting.md](troubleshooting.md) — Vector「未激活」与 Zygisk 注入时序(何时**确实需要**补跑 `post-fs-data.sh`)
- [maintenance.md](maintenance.md) — 更新 KernelSU 组件 / Zygisk / Vector 的维护流程（含步骤 ⑪ 一键激活）

---

## 附:命令速查清单

> **引号规则**:`adb shell "su -c '...'"`(外层双引号、内层单引号)。

```powershell
# ── 查看 monitor(正常应仅 1 个) ──
adb shell "ps -A | grep -i zygisk-ptrace64"
adb shell "ps -A -o PID,PPID,ETIME,CMD | grep -i zygisk-ptrace64"   # 含启动时长，判断是否叠加

# ── 查看 zygisk 临时目录(socket/so) ──
adb shell "su -c 'ls -l /data/adb/neozygisk'"

# ── 收敛为 1 个(不重启) ──
adb shell "su -c 'pkill -x zygisk-ptrace64'"
adb shell "su -c 'cd /data/adb/modules/zygisksu && TMP_PATH=/data/adb/neozygisk nohup ./bin/zygisk-ptrace64 monitor > /data/local/tmp/monitor.log 2>&1 &'"

# ── 让命令立即返回的重定向写法 ──
#    关键:cd 到 $MODDIR + 完整重定向 + 后台，见上一条

# ── 清理本地无效 PowerShell Job(与手机无关) ──
Get-Job | Remove-Job -Force
```

### 踩坑记录

| 坑 | 现象 | 正解 |
|--|--|--|
| **误判「卡住」** | `su -c 'sh post-fs-data.sh'` 长时间无输出 | monitor 常驻所致，**正常**；加 `> /dev/null 2>&1 &` 即立即返回 |
| **手动重复执行** | `zygisk-ptrace64` 出现 7 个 | `pkill` 全杀后**只重跑一次** |
| **logcat 空** | `logcat -s zygisk-sh` 无内容 | 该 log 仅在遍历其他 zygisk 模块时打印，**非报错** |
| **重启兜底** | 想用 `adb reboot` 清理进程 | 临时 Root **重启即失效**，须在本次开机内 `pkill` 收敛 |
| **Windows 跑 Linux 语法** | PowerShell 里 `nohup $MODDIR/... &` | 无效 Job，对手机无作用；`Get-Job \| Remove-Job -Force` 清理 |
| **进程名混淆** | `pgrep -f zygisk-ptrace64` 结果含 `zygiskd64` | 前者是 monitor 主进程，后者是注入器(monitor 在注入时 `exec` 它) |
| **★ CWD 错误** | 直接 `sh .../post-fs-data.sh` 启动 monitor → `exit=1` | monitor 内部用相对路径(`./bin/zygiskd64`)，**必须 `cd /data/adb/modules/zygisksu` 再启动** |
| **误信 `status` 子命令** | 跑 `zygiskd64 status` 想查状态（**本文针对 NeoZygisk**） | NeoZygisk 的 `zygiskd64` 是**注入器**，无 `status`；查状态看 `/data/adb/neozygisk/module.prop`。<br>⚠️ **Zygisk Next 例外**：它的 `./bin/zygiskd status` **正是权威状态入口**（看 `zygote_states`），勿与本文 NeoZygisk 的 `zygiskd64` 混淆 |
