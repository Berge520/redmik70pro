## 红米 K70 Pro — 免解锁 临时 Root(KSU)

本仓库内容**仅适配红米 K70 Pro**，采用**电脑免刷**(无需刷机、免解 BL)临时 root 方案。

> 通过 KernelSU 的 `ksud` 经 MIUI 系统服务接口注入并加载，在**本次开机**内获得 root 权限：
**不修改 `/boot` 分区、不刷入自定义内核、不破坏 OTA，重启后自动失效(免解BL)**。

- **适用设备**：红米 K70 Pro(代号 `manet` / 骁龙 8 Gen 3)
- **风险等级**：⚠️ **高危，请务必先备份数据**
- **重要**：**不要刷修改系统分区模块！** 否则会变砖 🧱

---

## 测试环境(实际验证通过)

|项目|版本|
|--|--|
|设备|Xiaomi Redmi K70 Pro(`manet`)|
|系统|澎湃 OS(HyperOS 3)|
|固件版本|HyperOS 3.0.0.10.WNMCNXM|
|Android|Android 16|
|安全更新|2025-10-01|

---

## ⚠️ 重要警告 / 免责声明

1. 临时 root 仅对**本次开机**生效，重启后一切恢复原状。
2. 使用 `ksud` / KernelSU 可能触发**设备保修失效**、**银行 / 国密 / 支付类 App 检测**，甚至**变砖**。
3. 操作前请**务必**备份重要数据。
4. **不要刷修改系统分区模块**，否则会变砖 🧱。
5. 以下步骤可能**触发系统验证 / 导致意外行为**，执行后果自负。
6. 本方案属于**免解锁 Bootloader(免解BL)临时 root**，**不需要**也不建议申请官方解锁；
重启即还原，不触发 Bootloader 解锁校验。
7. 本项目仅供学习与个人设备维护使用，请遵守当地法律法规。

---

## 原理简述

`miui.mqsas.IMQSNative` 是 MIUI/澎湃 OS 系统自带的服务(接口编号 `21`)，
存在**以 root(uid=0) 执行/加载二进制**的利用点。本方案在不修改任何系统分区的前提下，
通过该服务接口注入并加载 KernelSU 的 `ksud`(`late-load` 模式)，获得本次开机的 root 环境：

```
miui.mqsas.IMQSNative service call 21
   └─ 以 root(uid=0) 执行 / 加载指定二进制
        └─ KernelSU ksud (late-load)
             └─ 本次开机内提供 su 环境(KernelSU Manager 可识别)
```

- **不修改** `/boot`/`/system`/`init` → 不影响 OTA、不破坏校验、重启即还原(免解BL)。
- 属于**漏洞利用性质**的操作，随固件版本变化，不保证在其它机型/固件上可用。

> **不想敲命令？** `code/` 下提供了图形化一键工具（含免安装 exe），
> 把上述流程做成了点击操作，并自带设备检测、模块管理、日志查看等功能。
> 详见 [code/README.md](code/README.md)。本文件则是**纯命令行的完整原理与操作说明**，
> 两者等价，可按需选用。

---

## 准备工作

|物品|说明|
|--|--|
|红米 K70 Pro|已开启 **USB 调试**(设置 → 我的设备 → 全部参数 → 连续点击 **OS 版本** 启动开发者选项；设置 → 搜索「开发者选项」→ 打开 **USB 调试**)|
|电脑 + adb 环境|见下方步骤 1|
|附件 `附件.zip`|压缩包内含：`LSPosed-v1.11.0-7209-zygisk-release`、`Zygisk-Next-1.3.2-688-2c60cdd-release`、`热重启模块`、`fix_lspd`、`KernelSU_v3.1.0-29-gf0615d3c_32331-release`、`ksud`|
|USB 数据线|连接 K70 Pro 与电脑|

---

## 一、电脑 adb 环境搭建(已安装可跳过)

1. **下载 adb 文件**(platform-tools)。
2. 解压到一个盘符，例如：`D:\adb` 或 `D:\adb\platform-tools`。
3. **安装 adb 环境**：
   - 右键桌面「此电脑」→ 属性
   - 点右侧「高级系统设置」
   - 点右下角「环境变量」
   - 下方「系统变量」找到 `Path` → 选中 → 点「编辑」
   - 点「新建」→ 粘贴解压路径，例如 `D:\adb\platform-tools`
   - 一路「确定」→「确定」→「确定」关掉所有窗口
4. **测试是否成功**：
   - 按 `Win + R` → 输入 `cmd` → 回车
   - 输入 `adb --version`，出现版本号即成功

---

## 二、放置 ksud 并安装 KernelSU 管理器

1. 把 `附件.zip` 中的 **ksud** 放到 **adb.exe 所在目录**(例如 `D:\adb\platform-tools`)。
2. 在 K70 Pro 上安装 `附件.zip` 中的 **KernelSU 管理器**(`KernelSU_v3.1.0-29-gf0615d3c_32331-release`)。

---

## 三、进入 fastboot + 检查设备支持

K70 Pro 进入 **fastboot 模式**(两种方式任选其一)，连接电脑：

```sh
# 方式 1(开机状态下，已授权 adb)：用 adb 重启进入 fastboot
adb reboot bootloader

# 方式 2(关机状态)：按住 开机键 + 音量下键，直到出现 FASTBOOT 界面
```

电脑打开 cmd(`Win + R` → `cmd`)，依次执行：

```
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue
```

> ✅ **支持性检测**：执行完这两条后手机开机，打开 **KernelSU 管理器**，
**SELinux 状态为「宽容模式」** —— 则代表你的设备**支持**本方案。

> **说明**
> 
> - `androidboot.selinux=permissive` 是临时启动参数，**不会被写入分区**，重启即恢复 enforcing。
> - 若 `fastboot continue` 后手机拒绝启动或卡在 Logo，请按住 **电源 + 音量上** 强制重启，
或通过 `fastboot reboot` 回到系统。

---

## 四、推送 ksud 并调用系统服务加载

手机继续连接电脑，cmd 执行：

```bat
:: 切换到 adb 文件夹目录(即安装 adb 的目录)
cd D:\adb\platform-tools

:: ① 推送文件到手机
adb push ksud /data/local/tmp/

:: ② 给文件加权限
adb shell chmod 777 /data/local/tmp/ksud

:: ③ 调用系统服务执行(核心步骤)
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60
```

**`service call` 参数说明：**

|参数|含义|
|--|--|
|`21`|IMQSNative 服务中用于加载二进制的方法编号|
|`i32 1`|加载开关/模式(1 = 启用)|
|`s16 "/data/local/tmp/ksud"`|要加载的二进制路径|
|`s16 'late-load'`|加载模式：`late-load`(延迟加载)|
|`s16 '/sdcard/ksulog.txt'`|日志输出路径|
|`i32 60`|超时(秒)|

---

## 五、KernelSU Manager 内授予 shell root 权限

**重新打开 KernelSU 管理器**，在管理器里面给 **`shell` 授权 root 权限**。

---

## 六、恢复 SELinux 为强制模式

**方法 1(电脑 cmd)：**

```bat
adb shell su -c setenforce 1
```

**方法 2(手机 MT 管理器)：**

KernelSU 管理器授权 **MT 管理器** root 权限 → 打开 **MT 管理器** → 打开「终端模拟器」：

```sh
su
setenforce 1
```

**命令速查：**

|命令|作用|
|--|--|
|`setenforce 0`|打开宽容模式|
|`setenforce 1`|打开强制模式|

---

## 七、安装 LSPosed(可选)

1. 在 KernelSU 管理器里刷入 `附件.zip` 中的 **Zygisk-Next** 与 **LSPosed** 模块。
2. 如需**热重启**，刷入 `附件.zip` 中的 **热重启模块**。
3. **重启**，重启后按**步骤四 ~ 六**重新激活 KernelSU。
4. MT 管理器授予 root 权限，执行 `附件.zip` 里的 **`fix_lspd`**。
5. 之后如果有模块需要**重启系统框架**，只需**再执行一次 `fix_lspd`** 即可。

> 🧱 **不要刷修改系统分区模块**，否则会变砖！

---

## 完整命令流(一键复现)

```sh
# 1) 进入 Fastboot
adb reboot bootloader

# 2) 临时启动参数(permissive + 关 GPU 抢占)并继续启动
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

---

## 常见问题 / 排查

|现象|处理|
|--|--|
|`adb devices` 显示 `unauthorized`|手机屏幕确认授权弹窗，勾选始终允许|
|`fastboot` 不识别设备|检查驱动、换 USB 口/数据线、关闭手机助手占用|
|注入后 `su` 不可用|查看 `ksulog.txt`：`adb pull /sdcard/ksulog.txt`，确认 ksud 是否加载成功|
|KernelSU 显示未加载|确认已授予 `shell` root 权限；LSPosed 未加载则执行 `fix_lspd`|
|卡在 MIUI Logo|强制重启(电源+音量上)；可用 `fastboot reboot` 恢复|
|银行/支付 App 无法使用|临时 root 后该类应用通常会检测并拦截，属预期行为|
|重启后失效|**正常现象**——本次为临时 root，重启即还原|
|刷了修改系统分区模块|可能**变砖**：请通过 fastboot 刷回官方完整固件救砖|

---

## 如何恢复 / 回退

由于本方案**未修改任何系统分区**，恢复方法非常简单：

```sh
# 直接重启即可，彻底还原为未 root 状态
adb reboot
# 或
fastboot reboot
```

> 操作过程不会写入 `/boot`/`/system`，因此 OTA 升级、`Verify` 校验均不受影响；
但若你在临时 root 环境中**进一步修改了系统**(如刷入修改系统分区的模块)，则需自行刷回官方固件恢复。

---

## 相关资源

- [KernelSU](https://github.com/tiann/KernelSU) — 本方案使用的 Root 方案内核模块管理工具
- [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools) — adb / fastboot
- [mi_nobl_root(免解BL的 ksu+lsp 方案)](https://github.com/xunchahaha/mi_nobl_root) — 同 mqsas 漏洞原理、面向小米 15 的 LKM 内核模块(insmod)运行时加载方案，含 Python 补丁脚本
- [酷安数码玩机QvQ](https://www.coolapk.com/feed/70681212) — 小米/红米 免电脑 免bl 临时root（ksu）注：后面有电脑免刷root

---

## 许可

本项目以 [GNU AGPL-3.0](./LICENSE) 协议发布。请合理使用，遵守当地法律法规。
