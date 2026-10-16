#!/system/bin/sh
# Zygisk 注入修复脚本 —— NeoZygisk 专用版 · 历史文件名 fix_lspd.sh
#
# 说明：本文件是 fix_neozygisk.sh 的历史别名，二者内容等价。
#       名称中的 "lspd" 源自早期 LSPosed 时代，与当前逻辑无关；
#       保留该文件名仅为兼容既有文档与附件包。新用法请优先用 fix_neozygisk.sh。
#
# 用途：重越狱（late-load）后，KernelSU 不会重放 post-fs-data 事件，
#       NeoZygisk 的 monitor 需要手动补启动，并触发 zygote 重建让它注入。
#
# ┌─ 三个脚本的关系（模块 ID 同为 zygisksu，NeoZygisk 与 Zygisk Next 只能装其一）─┐
# │  fix_zygisk.sh      通用版：运行时自动识别框架，再走对应分支（推荐，最省心） │
# │  fix_neozygisk.sh   NeoZygisk 专用版（本脚本的正名）                      │
# │  fix_zygisknext.sh  Zygisk Next 专用版                                    │
# │  fix_lspd.sh        本脚本文件名（NeoZygisk 专用版的历史别名）            │
# └──────────────────────────────────────────────────────────────────────────┘
#
# NeoZygisk 特征：
#   · 入口 bin/zygisk-ptrace64（子命令 monitor / trace / ctl / version）
#   · 常驻进程名即 zygisk-ptrace64；运行时目录 /data/adb/neozygisk
#   · 无 zn-daemon、无 zygiskd daemon/service-stage
#   · ★ 必须以模块目录 $MODDIR 为 CWD 启动，否则相对路径（./module.prop、
#     ./bin/zygiskd64、./lib64/libzygisk.so）全部失效，monitor 会立刻 exit=1
#   · 注入判据：zygote64 的 /proc/<pid>/maps 能 grep 到 libzygisk.so
#
# 用法：
#   adb push code/tools/fix_lspd.sh /data/local/tmp/
#   adb shell su -c "sh /data/local/tmp/fix_lspd.sh"
#   （或改用 fix_neozygisk.sh / 通用版 fix_zygisk.sh，用法相同）

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisksu
TMP_PATH=/data/adb/neozygisk
MON_LOG=/data/local/tmp/monitor.log

echo "########## NeoZygisk 注入修复（专用版 · 历史文件名 fix_lspd.sh）##########"

# ── [0] 前置校验：确认装的是 NeoZygisk ──
if [ ! -x "$MODDIR/bin/zygisk-ptrace64" ] && [ ! -d "$TMP_PATH" ]; then
    echo "ERROR: 未检测到 NeoZygisk（既无 $MODDIR/bin/zygisk-ptrace64 也无 $TMP_PATH）"
    echo "       若设备装的是 Zygisk Next，请改用 fix_zygisknext.sh，"
    echo "       或使用通用版 fix_zygisk.sh（自动识别）。"
    exit 1
fi

echo "===== [1] 清理旧 monitor 与脏 socket ====="
# 按精确进程名清理（-x），避免 -f 命中本脚本/调用命令自身。
pkill -x zygisk-ptrace64 2>/dev/null
sleep 1
rm -f "$TMP_PATH/init_monitor"

echo "===== [2] 以 \$MODDIR 为 CWD 启动 monitor（★ cd 不能少）====="
cd "$MODDIR" || { echo "ERROR: 无法进入 $MODDIR"; exit 1; }
export TMP_PATH
nohup ./bin/zygisk-ptrace64 monitor > "$MON_LOG" 2>&1 &
sleep 3

echo "  monitor 进程:"
ps -A -o PID,CMDLINE 2>/dev/null | grep zygisk-ptrace | grep -v grep
echo "  monitor.log:"
cat "$MON_LOG" 2>/dev/null

echo "===== [3] 触发 zygote 重建，让 monitor seize 并注入 ====="
# 记录旧 PID（用 pidof 精确匹配 zygote64，避免误伤 webview_zygote）。
OLD_ZG=$(pidof zygote64)
echo "  旧 zygote64 PID=${OLD_ZG:-(无)}"
# ⚠️ 按 PID 精确 kill：zygote64 的进程名(comm)是 "main"，`pkill -x zygote64`
#    匹配不到、`pkill -x main` 又会误杀一片；故统一按 PID 杀。
KILL_PIDS="$OLD_ZG $(pidof zygote)"
[ -n "$KILL_PIDS" ] && kill -9 $KILL_PIDS 2>/dev/null

NEW_ZG=""
for i in $(seq 1 30); do
    sleep 1
    NOW=$(pidof zygote64)
    if [ -n "$NOW" ] && [ "$NOW" != "$OLD_ZG" ]; then
        NEW_ZG="$NOW"
        echo "  新 zygote64 PID=$NEW_ZG (${i}s)"
        break
    fi
done
if [ -z "$NEW_ZG" ]; then
    echo "WARNING: 未检测到 zygote64 重建（PID 未变化）"
fi

echo "===== [4] 验证注入结果（NeoZygisk 判据：zygote64 映射 libzygisk.so）====="
echo "  module.prop:"
cat "$TMP_PATH/module.prop" 2>/dev/null
CNT=0
if [ -n "$NEW_ZG" ]; then
    CNT=$(grep -c libzygisk /proc/$NEW_ZG/maps 2>/dev/null)
    echo "  zygote64($NEW_ZG) 映射 libzygisk.so 次数=$CNT"
    echo "  TracerPid=$(grep TracerPid /proc/$NEW_ZG/status 2>/dev/null | awk '{print $2}')"
fi

echo ""
if [ "${CNT:-0}" -gt 0 ]; then
    echo "=== ✓ NeoZygisk 注入成功（zygote64 已映射 libzygisk.so）==="
elif grep -q "injected" "$TMP_PATH/module.prop" 2>/dev/null; then
    echo "=== ✓ NeoZygisk 注入成功（module.prop 标记 injected）==="
else
    echo "=== ✗ 注入未确认，请查看上方 monitor.log ==="
fi
echo "DONE"
