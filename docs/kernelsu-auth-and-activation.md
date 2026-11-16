# KernelSU 授权 + 一键激活 · 真机实录

> 从「App 拿不到 root」到「10/10 模块运行中」。根因分析见 [troubleshooting.md](troubleshooting.md)。

| 项 | 值 |
|--|--|
| 设备 | 红米 K70 Pro(`manet`) `23117RK66C` · sn `a234db9` |
| 系统 | HyperOS 3 / Android 16 · 1440×3200 · density 560 |
| Root | KernelSU 免解锁 · 临时 · late-load（**整机重启即失效**） |
| 版本 | ZygiskFix **1.2.6(10206)** · NeoZygisk · Vector **2.2(3119)** · HMA-OSS `future-8ae6361d` |
| 结果 | 全部通过，**未重启**，临时 root 未丢 |

---

## 一、四条铁律

1. **KernelSU 隐藏模式不响应 App 发起的 su 请求** → 必须去 KSU 界面手动勾选。App 侧四入口全 `Permission denied` 属正常。
2. **安装 APK 要在未注入窗口做**。激活态安装风险显著升高，是否死机取决于当时的 swap 余量（见第六节）。顺序：先装 → 再激活 → 激活后尽量不装。
3. **判断是否重启看 `uptime`**，连续增长即没重启。屏幕黑一下、Vector Manager 自动弹出都是预期行为。
4. **别用 `.allowlist` 判断授权**（勾选后它不变）。唯一判据是 App 点「仅检测」看第一行是否为 `[App] 使用 su`。

---

## 二、手动授权（KernelSU）

包名 `me.weishu.kernelsu`，启动后直接落在「超级用户」页。

| 步 | 动作 | 真实坐标 |
|--|--|--|
| 1 | `adb shell am start -n me.weishu.kernelsu/.ui.MainActivity` | — |
| 2 | 点搜索框 → 输入 `zygisk` | (700, 624) |
| 3 | 点「Zygisk 修复」条目 | (720, 518) |
| 4 | **点「超级用户」开关，由灰变蓝** | **(1250, 978)**，热区只在**左半边**；点右半圆 (1252,1111) 无效 |

`App Profile` 页应显示 `Zygisk 修复 / com.redmik70pro.zygiskfix / UID 10295`。

**验证**：回 App 点「仅检测」，第一行应为 `[App] 使用 su`，且 `UID=0`。

---

## 三、一键激活时间线

闸门（脚本内置）：`MemAvailable > 600 MB`。实测 4.46 GB 放行。

| 时刻 | 事件 |
|--|--|
| T+0s | 点「一键激活」，横幅切「正在执行…」 |
| T+3s | `[0] UID=0 模式=fix SELinux=Enforcing` |
| T+5s | `[1] bin/zygisk-ptrace64` · `[2] monitor PID 27585` |
| T+8s | `[2.5] 重启 zygisk_vector 常驻服务` |
| T+40s | **屏幕全黑**（zygote 重建，预期） |
| T+85s | Vector Manager 弹出「**已激活 2.2 (3119) · API 102**」，`uptime` 连续无重启 |

### 激活后复检（连测两次一致）

```
[App] 使用 su
[0] UID=0 模式=check  ✓ 已获得 root  SELinux=Enforcing
[1] zygote64: injected   daemon64: running
    monitor 27585 · daemon 27719 · vectord 27611
    注入链路实测: 正常（新启动的 App 会拿到 zygisk）
    ✓ 当前已处于注入状态
```

横幅 **✓ 已处于激活状态，无需修复**。

### 稳定性（激活后 13 分钟）

```
uptime     load1   MemAvailable  SwapFree   zygisk  vectord
2184.12    2.92    4.28 GB       8.70 GB    3       1
2275.16    3.29    4.26 GB       8.71 GB    3       1
```

对比历史死亡快照 `load=48.43 MemFree=16MB MemAvailable=669MB SwapFree=64KB` → 当前健康。

---

## 四、模块生效（Vector Manager → 模块）

**10/10 已启用，全部「运行中」**：

| 模块 | 版本 | 作用域 |
|--|--|--|
| FuseFixer | 3574975 | Xposed 93 |
| HookVip | 4.1.7 | API 101 · 7+ |
| HyperCeiler | 2.10.166-202 | API 101 · **24 进程 / 59+** |
| HyperDragShare | 1.9.3 | API 102 |
| HyperIsland | 3.2.5 | API 102 · 4+ |
| LTW Unlock | 1.5.3 | `android`/`system_server`（模块固定不可改） |

HMA-OSS Zygisk `module.prop`：`[✅ System service loaded]`。

> HyperCeiler **没有 launcher 入口**，但 `enabled=1 installed=true`、作用域正常、运行中 —— 属模块形态，不是故障。

---

## 五、十三个坑

| # | 坑 | 正确做法 |
|--|--|--|
| 1 | 激活状态下 `adb install` | 风险显著升高，先核对 swap 余量（第六节） |
| 2 | 指望 App 点按钮弹授权框 | 隐藏模式不响应，必须 KSU 内手动勾 |
| 3 | 点 switch 右半圆没反应 | 热区在左半边 |
| 4 | 截图坐标直接 `input tap` | 截图 460×1000，实际 1440×3200，**×3.13** |
| 5 | 用 `.allowlist` 判授权 | 会误判，看 App 日志 |
| 6 | `ps -o NAME` 找后台脚本 | NAME 是 `sh` 会漏，必须按 **ARGS** 过滤 |
| 7 | `adb shell "su -c '... \| grep'"` | PS 把 `\|` 当管道。外层改**单引号** |
| 8 | Vector 首页点偏跳浏览器 | 底部「模块」在 **(557, 2911)** |
| 9 | 以为 App 能读 `/sdcard/Download` | 属 `u0_a245`、`2770` → `Permission denied`。脚本放 **`/data/local/tmp`** |
| 10 | 想做成 KernelSU 模块求「更稳定」 | **更糟**：模块需重启生效，重启即丢临时 root |
| 11 | 以为 App 能读 `/proc/loadavg` | Android 16 SELinux 标为 `proc_loadavg`，未授权 App 域一律 **EACCES**。`su 10295 -c cat` 能读是因为仍在 `u:r:ksu:s0` 域 |
| 12 | 用 logcat 调 App 问题 | 本机 **logcat 被模块屏蔽**，`Log.i/w` 全无输出。改用「把诊断打到界面上」 |
| 13 | `Color.parseColor` 直接喂文件内容 | 写坏的半截文件会抛 `IllegalArgumentException`，App 一打开就崩。必须 try-catch |

### 坐标速查（真实 1440×3200）

| 目标 | 坐标 |
|--|--|
| ZygiskFix 一键激活 / 仅检测 | (940, 364) / (960, 364) |
| KSU 搜索框 / 超级用户开关 | (700, 624) / **(1250, 978)** |
| Vector Manager 底部「模块」 | (557, 2911) |

---

## 六、安装风险与版本演进

### 为什么激活态安装更危险

**dex2oat 不是主因**：本机 `pm.dexopt.install` 就是 `speed-profile`，`install-fast` 已是 `skip`，小包几乎不编译。区别在全局状态：

| 因素 | 平时 | 激活态 |
|--|--|--|
| zygote | 未 ptrace | `PTRACE_SEIZE` 附着，`libzygisk.so` 常驻 |
| 内存 | 正常 | 模块在每个新进程加载（HyperCeiler 作用域 24 进程） |
| 耗时 | 单次扫描 | 扫描 + dexopt 校验 + **所有 PkgUpdateObserver 回调** |
| 结果 | 秒级 | 可能 swap 打穿 → watchdog 重启 |

> 结论：**不是某个 APK 特殊，而是「激活态」让任何安装都变危险**——第三方 App、系统更新、重装自身都一样。

### 实装测试（2026-11-16，已注入状态连装 5 次）

| 时刻 | uptime | MemAvailable | SwapFree |
|--|--|--|--|
| 装前 | 6292.97 | 4.70 GB | 9.07 GB |
| 装后 | 6293.59 | 4.44 GB | 9.07 GB |

5 次 `adb install -r` 全 `Success`，**未重启、未卡死、注入态保持**。

> 但要看清前提：当时 SwapFree 还有 9 GB，历史死亡时只剩 **64 KB**。
> 所以准确说法是「风险显著升高，不是必定死机」，取决于安装那一刻的 swap 余量。

**安全线**：`SwapFree > 2 GB` 且 `MemAvailable > 1.5 GB` 时，小包（< 10 MB）覆盖安装实测安全。大包、游戏、系统更新另当别论。

> `setprop pm.dexopt.install verify` 之类改 **无效**——瓶颈不在编译阶段；`setprop` 重启即回落，无持久副作用。

### 版本演进

| 版本 | 变更 |
|--|--|
| 1.2.0 (10200) | 版本号规范化：清单单点维护、运行时 `PackageManager` 读、界面显示 |
| 1.2.1 (10201) | 修「激活后界面空白」：Activity 被重建销毁时原先直接 `return`，结论从未落盘。改为无条件 `writeResultFile()` + `relaunchSelf()` |
| 1.2.2 (10202) | ① **外部脚本**：优先读外部 `fix.sh`，改脚本只需 `adb push`，不装 APK 则无死机风险；② **状态条**：读 `/proc` 判 `SwapFree<1GB`、`MemAvailable<600MB` |
| 1.2.3 (10203) | 修 1.2.2 真机缺陷：外部脚本原写死 `/sdcard/Download`，App 读不进去必静默回落。改候选列表 `EXTERNAL_SCRIPTS`，首选 `/data/local/tmp/fix.sh`（1777） |
| 1.2.4 (10204) | 状态条可点重读（带 Toast）；`无读权限` 提示补 `需 chmod 644` |
| 1.2.5 (10205) | 修状态条 `load ?`：SELinux 拒读 `/proc/loadavg`，改为能读才显示、不作判据 |
| 1.2.6 (10206) | ① 修 `parseColor` 未捕获异常；② 外部脚本日志补 `大小 + mtime` |
| 1.2.7 (10207) | ① 「一键激活」加二次确认弹窗，误触不再直接重建 zygote；② 界面显示项目仓库地址，点击跳浏览器 |

### 外部脚本工作流（避开安装）

```
改 fix.sh → adb push 到 /data/local/tmp/fix.sh → App 点按钮，或
adb shell 'su -c "sh /data/local/tmp/fix.sh check"'
```

`adb push` 文本文件不触发 dex2oat、不扫包、不改 PM 数据库，**激活态可安全执行**。实测 `RESULT:OK:ALREADY`。

| 路径 | 状态 | App 可读 |
|--|--|--|
| `/data/local/tmp/fix.sh` | `644 root root`，父目录 `1777` | ✅ |
| `/sdcard/Download/fix.sh` | 父目录 `2770 u0_a245` | ❌ |
| `/proc/meminfo` | 内核虚拟文件 | ✅ |
| `/proc/loadavg` | SELinux `proc_loadavg` | ❌ EACCES |

> 验证命令：`adb shell 'su -c "su 10295 -c \"head -1 /data/local/tmp/fix.sh\""'`
> 不要用 `run-as`，非 debuggable 包直接报 `package not debuggable`。

**构建**：`& .\build.cmd`（勿 `cmd /c`）。产物 `dist\ZygiskFix.apk`，`aapt2 dump badging` + `apksigner verify` 双检。

**发版纪律**：激活状态下不推送不安装，只在重新越狱后的未注入窗口装。

---

## 七、常用命令

```bash
# 状态判据
adb shell "cat /proc/uptime"                                    # 连续增长 = 没重启
adb shell "grep -E 'MemAvailable|SwapFree' /proc/meminfo"
adb shell "ps -A -o PID,ARGS | grep -E 'zygisk|vectord' | grep -v grep"   # 应 3+1

# 模块信息
adb shell 'su -c "cat /data/adb/modules/zygisk_vector/module.prop"'

# 外部脚本（激活态也可安全执行）
adb push code\apk\src\main\assets\fix.sh /data/local/tmp/fix.sh
adb shell "chmod 644 /data/local/tmp/fix.sh"
adb shell 'su -c "sh /data/local/tmp/fix.sh check"'

# 起 App
adb shell am start -n com.redmik70pro.zygiskfix/.MainActivity

# Vector Manager 独立安装（包名 org.matrix.vector.manager）
adb shell 'su -c "pm install -r /data/adb/modules/zygisk_vector/manager.apk"'
```

---

## 八、相关

- [troubleshooting.md](troubleshooting.md) — 注入失败根因（monitor CWD）
- [zygisk-monitor-multi-instance.md](zygisk-monitor-multi-instance.md) — monitor 堆积排查
- [maintenance.md](maintenance.md) — 日常维护
- [fix.sh](../code/apk/src/main/assets/fix.sh) — 激活脚本
- [AndroidManifest.xml](../code/apk/src/main/AndroidManifest.xml) — 版本规范 `MAJOR*10000+MINOR*100+PATCH`
