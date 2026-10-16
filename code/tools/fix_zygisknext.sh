#!/system/bin/sh
# Zygisk 注入修复脚本 —— Zygisk Next 专用版（临时 Root / KernelSU late-load 场景）
#
# 用途：重越狱（late-load）后，KernelSU 不会重放 post-fs-data 事件，
#       Zygisk Next 的注入守护进程需要手动补启动，并触发 zygote 重建让它注入。
#
# ┌─ 三个脚本的关系（模块 ID 同为 zygisksu，NeoZygisk 与 Zygisk Next 只能装其一）─┐
# │  fix_zygisk.sh      通用版：运行时自动识别框架，再走对应分支（推荐，最省心） │
# │  fix_neozygisk.sh   NeoZygisk 专用版：路径固定、逻辑确定                  │
# │  fix_zygisknext.sh  Zygisk Next 专用版（本脚本）：路径固定、逻辑确定      │
# │  fix_lspd.sh        NeoZygisk 专用版的历史别名（内容等价）               │
# └──────────────────────────────────────────────────────────────────────────┘
#
# Zygisk Next 特征（与本脚本强绑定，作者 LSPosed Developers）：
#   · 入口 bin/zygiskd（软链 → zygiskd64），另有 zygiskd32
#   · 启动命令 ./bin/zygiskd daemon；状态命令 ./bin/zygiskd status
#     （注意：znctl 只是配置工具，`znctl status` 会打印帮助并返回 1）
#   · 管理器进程 comm 名不可见，只能用 /proc/<pid>/exe 软链识别
#   · 注入后为每个 zygote 派生常驻进程 zn-nsdaemon-zygote / zn-nsdaemon-zygote_secondary
#     （★ 没有名为 zn-daemon 的进程）
#   · 运行时目录 /data/adb/zygisksu（znctx、modules_info、denylist_enforce 等）
#   · ★ 不能直接 `sh ./post-fs-data.sh`：其末行 `./bin/zygiskd daemon` 会前台
#     常驻不返回，会让本脚本永久挂起。故照搬其前置动作后自行后台化启动。
#   · 注入判据：zygiskd status 的 `zygote_states: N`（N≥1 即已注入）。
#     ★ 不能用 grep libzygisk 判定：Zygisk Next 注入后会 unmap 自身 loader
#       （反检测），该 grep 恒为 0。
#
# 用法：
#   adb push code/tools/fix_zygisknext.sh /data/local/tmp/
#   adb shell su -c "sh /data/local/tmp/fix_zygisknext.sh"

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisksu
ZN_TMP=/data/adb/zygisksu
MON_LOG=/data/local/tmp/zygisknext-daemon.log

echo "########## Zygisk Next 注入修复（专用版）##########"

# ── [0] 前置校验：确认装的是 Zygisk Next ──
if [ ! -x "$MODDIR/bin/zygiskd" ] && [ ! -x "$MODDIR/bin/zygiskd64" ]; then
    echo "ERROR: 未检测到 Zygisk Next（无 $MODDIR/bin/zygiskd）。"
    echo "       若设备装的是 NeoZygisk，请改用 fix_neozygisk.sh，"
    echo "       或使用通用版 fix_zygisk.sh（自动识别）。"
    exit 1
fi

echo "===== [1] 以 \$MODDIR 为 CWD 后台化启动 daemon ====="
# ⚠️ 不能直接 `sh ./post-fs-data.sh`（见文件头说明）。照搬其前置动作后自行后台化启动。
mkdir -p "$ZN_TMP"
cd "$MODDIR" || { echo "ERROR: 无法进入 $MODDIR"; exit 1; }
# 清理上次运行的运行时上下文（与官方 post-fs-data.sh 行为一致）。
[ -f "$ZN_TMP/znctx" ] && mv "$ZN_TMP/znctx" "$ZN_TMP/znctx.old"
[ -f "$ZN_TMP/modules_info" ] && mv "$ZN_TMP/modules_info" "$ZN_TMP/modules_info.old"
nohup ./bin/zygiskd daemon > "$MON_LOG" 2>&1 &
sleep 3

echo "  zygiskd 管理器进程（按 /proc/<pid>/exe 软链识别）:"
for p in /proc/[0-9]*; do
    e=$(readlink "$p/exe" 2>/dev/null)
    case "$e" in *zygiskd*) echo "    ${p#/proc/} -> $e";; esac
done
echo "  daemon.log:"
cat "$MON_LOG" 2>/dev/null

echo "===== [2] 触发 zygote 重建，让 daemon seize 并注入 ====="
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
sleep 2

echo "===== [3] 验证注入结果（Zygisk Next 判据：zygote_states: N，N≥1 即已注入）====="
echo "  zygiskd status:"
cd "$MODDIR" && ./bin/zygiskd status 2>&1 | grep -E 'zygote_state|inject_state|modules'
ZS=$(cd "$MODDIR" && ./bin/zygiskd status 2>/dev/null | \
     awk -F: '/^zygote_states/{gsub(/ /,"",$2);print $2}')
echo "  zygote_states=$ZS"

echo "  zn-nsdaemon-zygote 常驻进程:"
pgrep -f zn-nsdaemon-zygote >/dev/null 2>&1 && \
    ps -A -o PID,CMDLINE 2>/dev/null | grep zn-nsdaemon | grep -v grep || \
    echo "    (未发现)"

echo ""
if [ "${ZS:-0}" -gt 0 ]; then
    echo "=== ✓ Zygisk Next 注入成功（zygote_states=$ZS）==="
else
    echo "=== ✗ 注入未确认，请查看上方 daemon.log 与 status 输出 ==="
fi
echo "DONE"
