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
四、修复 LSPosed / Zygisk 注入（fix_lspd.sh）
--------------------------------------------------------------------
用途：模块更新或重启系统框架后，LSPosed 未加载 / Zygisk 崩溃时重新注入。

  # 方式 A：把脚本推到设备后以 root 执行（推荐路径固定、可复现）
  adb push fix_lspd.sh /data/local/tmp/
  adb shell su -c "sh /data/local/tmp/fix_lspd.sh"

  # 方式 B：脚本已在手机存储时直接执行（路径按实际存放位置替换）
  adb shell su -c "sh /sdcard/Download/fix_lspd.sh"

  说明：脚本会杀掉旧 lspd → 重新注入 ZygiskSU → 重启 zygote/system_server
        → 等待 bridge 建立，最后打印「修复成功 / 修复失败」。


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
