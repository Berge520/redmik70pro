====================================================================
  手动命令速查（命令行等价写法）
====================================================================
说明：本文件是 GUI 工具底层命令的手工复现参考，供不方便使用 GUI
      或需要排障时对照执行。所有命令在电脑 cmd / PowerShell 中运行。

前提：adb / fastboot / ksud 已就绪（源码运行时位于 code/tools/，
      或已加入 PATH）。以下命令假定当前工作目录即为该目录。


--------------------------------------------------------------------
一、进入 Fastboot 并开启宽容模式（临时，不写分区）
--------------------------------------------------------------------
adb reboot bootloader
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue

  说明：permissive 是临时启动参数，重启自动恢复 enforcing。
        若 fastboot continue 后卡 Logo：按住 电源 + 音量上 强制重启。


--------------------------------------------------------------------
二、推送 ksud 并通过系统服务漏洞提权（核心步骤）
--------------------------------------------------------------------
adb push ksud /data/local/tmp/
adb shell chmod 777 /data/local/tmp/ksud

adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60

  参数说明：
    21                            IMQSNative 服务中加载二进制的方法号
    i32 1                         加载开关（1 = 启用）
    s16 "/data/local/tmp/ksud"    要加载的二进制路径
    s16 'late-load'               加载模式：延迟加载
    s16 '/sdcard/ksulog.txt'      日志输出路径
    i32 60                        超时（秒）

  验证是否成功：
    adb shell su -c id           # 期望输出 uid=0(root)


--------------------------------------------------------------------
三、SELinux 模式切换
--------------------------------------------------------------------
adb shell su -c setenforce 1     # 强制模式 Enforcing（推荐，提权后恢复）
adb shell su -c setenforce 0     # 宽容模式 Permissive

  说明：setenforce 0 = 宽容(Permissive) / setenforce 1 = 强制(Enforcing)。
        宽容模式下 Zygisk / Vector 也能正常工作，可按需选择。


--------------------------------------------------------------------
四、修复 Zygisk 注入
--------------------------------------------------------------------
用途：重越狱（KernelSU late-load）后，KernelSU 不会重放 post-fs-data 事件，
      Zygisk 注入服务需手动补启动，并触发 zygote 重建让它注入。

  · fix_zygisk.sh     —— 通用版，自动识别 NeoZygisk / Zygisk Next（推荐）
  · fix_neozygisk.sh  —— 仅 NeoZygisk（命令硬编码为 zygisk-ptrace64 monitor）
  · fix_zygisknext.sh —— 仅 Zygisk Next（命令硬编码为 ./bin/zygiskd daemon）
  · fix_lspd.sh       —— fix_neozygisk.sh 的历史别名（逻辑等价，仅供旧文档兼容）

  通用版用法（自动识别框架，与 GUI 模式 6 逻辑一致）：
  adb push fix_zygisk.sh /data/local/tmp/
  adb shell su -c "sh /data/local/tmp/fix_zygisk.sh"
    → 识别框架后：NeoZygisk 以 $MODDIR 为 CWD 启动 zygisk-ptrace64 monitor；
      Zygisk Next 以 $MODDIR 为 CWD 后台化启动 `./bin/zygiskd daemon`
      （不直接跑 post-fs-data.sh，因其末行 daemon 会前台常驻导致挂起），
      随后触发 zygote 重建。

  专用版用法（已确认框架类型时）：
  adb push fix_neozygisk.sh /data/local/tmp/
  adb shell su -c "sh /data/local/tmp/fix_neozygisk.sh"     # 仅 NeoZygisk
  adb push fix_zygisknext.sh /data/local/tmp/
  adb shell su -c "sh /data/local/tmp/fix_zygisknext.sh"    # 仅 Zygisk Next
    ⚠️ 专用脚本会在开头校验框架，若与本机不符会报错并提示改用另一个。

  说明：脚本会清理旧 monitor/socket → 以 $MODDIR 为 CWD 启动注入服务
        → 触发 zygote 重建 → 按框架分派校验注入结果，
        最后打印「注入成功 / 未确认」。
        ⚠️ 注入判据不可通用：NeoZygisk 校验 zygote64 是否映射 libzygisk.so；
           Zygisk Next 注入后 unmap 自身 loader，须改用 `zygiskd status`
           的 `zygote_states: N`（N≥1 即已注入）。


--------------------------------------------------------------------
五、完整命令流（一键复现）
--------------------------------------------------------------------
adb reboot bootloader
fastboot oem set-gpu-preemption 0 androidboot.selinux=permissive
fastboot continue

adb push ksud /data/local/tmp/
adb shell chmod 777 /data/local/tmp/ksud
adb shell service call miui.mqsas.IMQSNative 21 i32 1 s16 "/data/local/tmp/ksud" i32 1 s16 'late-load' s16 '/sdcard/ksulog.txt' i32 60

adb shell su -c setenforce 1
adb shell su -c id               # 期望输出 uid=0(root)


--------------------------------------------------------------------
六、排障
--------------------------------------------------------------------
  注入后 su 不可用            adb pull /sdcard/ksulog.txt  查看加载日志
  设备 unauthorized           手机屏幕确认授权弹窗
  fastboot 不识别设备         检查驱动 / 换 USB 口与数据线 / 关闭手机助手


--------------------------------------------------------------------
注：无线调试配对请使用同目录下的 Connector.cmd。
