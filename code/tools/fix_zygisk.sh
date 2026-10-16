#!/system/bin/sh
# Zygisk 注入修复脚本（通用版 · 临时 Root / KernelSU late-load 场景）
#
# 用途：重越狱（late-load）后，KernelSU 不会重放 post-fs-data 事件，
#       Zygisk 注入服务需要手动补启动，并触发 zygote 重建让它注入。
#
# ┌─ 三个脚本的关系（模块 ID 同为 zygisksu，NeoZygisk 与 Zygisk Next 只能装其一）─┐
# │  fix_zygisk.sh      通用版（本脚本）：运行时自动识别框架，再走对应分支       │
# │  fix_neozygisk.sh   NeoZygisk 专用版：路径固定、逻辑确定                    │
# │  fix_zygisknext.sh  Zygisk Next 专用版：路径固定、逻辑确定                  │
# │  fix_lspd.sh        NeoZygisk 专用版的历史别名（内容等价）                 │
# └──────────────────────────────────────────────────────────────────────────┘
# 不确定装的是哪个框架时，直接用本脚本即可。
#
# 两框架差异（本脚本据此分派）：
#   · NeoZygisk（JingMatrix，入口 bin/zygisk-ptrace64，常驻进程 zygisk-ptrace64）
#   · Zygisk Next（LSPosed Developers，入口 bin/zygiskd→zygiskd64，
#     管理器进程 comm 名不可见，注入后派生 zn-nsdaemon-zygote）
# 两者模块 ID 同为 zygisksu（无法靠目录名区分），故按入口文件 / 常驻进程判定。
#
# 用法：
#   adb push code/tools/fix_zygisk.sh /data/local/tmp/
#   adb shell su -c "sh /data/local/tmp/fix_zygisk.sh"

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisksu
NEO_BIN="$MODDIR/bin/zygisk-ptrace64"
NEO_TMP=/data/adb/neozygisk
MON_LOG=/data/local/tmp/monitor.log

# ── 探测框架：输出 neo / next / none ──
detect_zygisk() {
    if [ -x "$NEO_BIN" ]; then
        echo neo
        return
    fi
    if [ -x "$MODDIR/bin/zygiskd" ] || [ -x "$MODDIR/bin/zygiskd64" ]; then
        echo next
        return
    fi
    if pgrep -f zygisk-ptrace64 >/dev/null 2>&1; then
        echo neo
        return
    fi
    if pgrep -f zn-nsdaemon-zygote >/dev/null 2>&1; then
        echo next
        return
    fi
    if [ -d "$NEO_TMP" ]; then
        echo neo
        return
    fi
    echo none
}

KIND=$(detect_zygisk)
echo "===== [0] 框架识别: $KIND ====="

case "$KIND" in
neo)
    echo "  → NeoZygisk（入口 $NEO_BIN）"

    echo "===== [1] 清理旧 monitor 与脏 socket ====="
    # 按精确进程名清理（-x），避免 -f 命中本脚本/调用命令自身。
    pkill -x zygisk-ptrace64 2>/dev/null
    sleep 1
    rm -f "$NEO_TMP/init_monitor"

    echo "===== [2] 以 \$MODDIR 为 CWD 启动 monitor（★ cd 不能少）====="
    cd "$MODDIR" || { echo "ERROR: 无法进入 $MODDIR"; exit 1; }
    export TMP_PATH="$NEO_TMP"
    nohup ./bin/zygisk-ptrace64 monitor > "$MON_LOG" 2>&1 &
    sleep 3

    echo "  monitor 进程:"
    ps -A -o PID,CMDLINE 2>/dev/null | grep zygisk-ptrace | grep -v grep
    echo "  monitor.log:"
    cat "$MON_LOG" 2>/dev/null
    ;;
next)
    echo "  → Zygisk Next（入口 $MODDIR/bin/zygiskd）"

    echo "===== [1] 以 \$MODDIR 为 CWD 后台化启动 daemon ====="
    # ⚠️ 不能直接 `sh ./post-fs-data.sh`：它末行 `./bin/zygiskd daemon` 会
    #    前台常驻不返回，会让本脚本永久挂起。故照搬其前置动作后自行后台化启动。
    mkdir -p /data/adb/zygisksu
    cd "$MODDIR" || { echo "ERROR: 无法进入 $MODDIR"; exit 1; }
    [ -f /data/adb/zygisksu/znctx ] && \
        mv /data/adb/zygisksu/znctx /data/adb/zygisksu/znctx.old
    [ -f /data/adb/zygisksu/modules_info ] && \
        mv /data/adb/zygisksu/modules_info /data/adb/zygisksu/modules_info.old
    nohup ./bin/zygiskd daemon > "$MON_LOG" 2>&1 &
    sleep 3

    echo "  zygiskd 管理器进程:"
    for p in /proc/[0-9]*; do
        e=$(readlink "$p/exe" 2>/dev/null)
        case "$e" in *zygiskd*) echo "    ${p#/proc/} -> $e";; esac
    done
    echo "  daemon.log:"
    cat "$MON_LOG" 2>/dev/null
    ;;
none)
    echo "ERROR: 未检测到 Zygisk 框架（既无 $NEO_BIN，也无 $MODDIR/bin/*/zygiskd）"
    echo "       请确认已刷入 NeoZygisk 或 Zygisk Next 模块。"
    exit 1
    ;;
esac

echo "===== [3] 触发 zygote 重建，让注入服务 seize 并注入 ====="
# 记录旧 PID（用 pidof 精确匹配 zygote64，避免误伤 webview_zygote）。
OLD_ZG=$(pidof zygote64)
echo "  旧 zygote64 PID=${OLD_ZG:-(无)}"
# ⚠️ 按 PID 精确 kill：zygote64 的进程名(comm)是 "main"，`pkill -x zygote64`
#    匹配不到、`pkill -x main` 又会误杀一片；而本脚本由 `sh fix_zygisk.sh`
#    启动（命令行不含 zygote64），故 `pkill -f` 虽可用但不够稳妥，这里统一按 PID 杀。
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

echo "===== [4] 验证注入结果 ====="
# ★ 注入判据**不可通用**：
#   · NeoZygisk 把 libzygisk.so 常驻映射在 zygote 里，可 grep /proc/<pid>/maps。
#   · Zygisk Next 注入后会 unmap 自身 loader（反检测），该 grep 恒为 0，
#     必须改用 `zygiskd status` 的 `zygote_states: N`。
if [ "$KIND" = "neo" ]; then
    echo "  module.prop:"
    cat "$NEO_TMP/module.prop" 2>/dev/null
    if [ -n "$NEW_ZG" ]; then
        CNT=$(grep -c libzygisk /proc/$NEW_ZG/maps 2>/dev/null)
        echo "  zygote64($NEW_ZG) 映射 libzygisk.so 次数=$CNT"
        echo "  TracerPid=$(grep TracerPid /proc/$NEW_ZG/status 2>/dev/null | awk '{print $2}')"
    fi
    OK=$([ "${CNT:-0}" -gt 0 ] && echo 1)
else
    echo "  zygiskd status（zygote_states: N，N≥1 表示已注入）:"
    cd "$MODDIR" && ./bin/zygiskd status 2>&1 | grep -E 'zygote_state|inject_state|modules'
    ZS=$(cd "$MODDIR" && ./bin/zygiskd status 2>/dev/null | \
         awk -F: '/^zygote_states/{gsub(/ /,"",$2);print $2}')
    echo "  zygote_states=$ZS"
    OK=$([ "${ZS:-0}" -gt 0 ] && echo 1)
fi

echo ""
if [ -n "$OK" ]; then
    echo "=== ✓ $KIND 注入成功 ==="
else
    echo "=== ✗ 注入未确认，请查看上方输出与日志 ==="
fi
echo "DONE"
