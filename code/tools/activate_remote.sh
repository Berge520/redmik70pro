#!/system/bin/sh
# ============================================================================
# 一键修复「Zygisk / Vector / LSPosed 未激活」—— 手机端版本
#
# 与 fix_zygisk.sh 的区别：
#   · fix_zygisk.sh    需 root 会话（adb shell su -c / 电脑 GUI 模式 6）
#   · 本脚本          面向手机端：一次跑完「识别 → 启动 → 重建 zygote → 验证」，
#                     末尾直接给结论；有 su 时全程提权，没有 su 只做检测。
#
# 用法（手机上任选其一）：
#   A. MT 管理器「终端模拟器」：su -c "sh /sdcard/activate_remote.sh"
#      （或先在终端输入 su 回车，再 sh /sdcard/activate_remote.sh）
#   B. KernelSU 管理器 → 模块/超级用户页里的终端，同样先 su
#   C. Termux（已 root）：su -c "sh /sdcard/activate_remote.sh"
#   D. 电脑 adb：adb push activate_remote.sh /data/local/tmp/
#                adb shell su -c "sh /data/local/tmp/activate_remote.sh"
#   注意：Shizuku 只有 shell 权限，杀不动 zygote，用它跑只能检测、无法修复。
#
# 流程（与 docs/troubleshooting.md 第五节一致）：
#   [0] 环境探测（root / SELinux） → [1] 识别 Zygisk 框架
#   [2] 以 $MODDIR 为 CWD 启动注入服务 → [3] kill zygote 触发重建
#   [4] 验证注入 → [5] 验证 Vector / LSPosed → 输出结论
#
# ⚠️ 步骤 [3] 会让桌面短暂黑屏/重启（10~30 秒），属正常现象。
# ⚠️ 临时 Root（late-load）每次重越狱后都要跑一次，这是机制决定的，不是版本问题。
# ============================================================================

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisksu
NEO_BIN="$MODDIR/bin/zygisk-ptrace64"
NEO_TMP=/data/adb/neozygisk
MON_LOG=/data/local/tmp/monitor.log
VEC_DIR=/data/adb/modules/zygisk_vector
LSPD_CLI=/data/adb/lspd/bin/cli

say()  { echo "$@"; }
head1() { echo ""; echo "===== $* ====="; }

# ── 统一执行入口：能 root 就 root，否则退回当前 shell 权限 ──
# $1 = 命令；其余 = 参数。命令里不要含单引号（su -c 需整体加引号）。
R_IS_ROOT=0
R_AS_ROOT=0
run() {
    if [ "$R_IS_ROOT" = "1" ]; then
        "$@"
    elif [ "$R_AS_ROOT" = "1" ]; then
        su -c "$*" 2>/dev/null
    else
        "$@"
    fi
}

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# adb / 部分 ROM 的 sh 内置了 pidof 以外的命令差异，这里统一用 pgrep 兜底
pids_of() {
    if has_cmd pidof; then
        pidof "$1" 2>/dev/null
    else
        pgrep -x "$1" 2>/dev/null
    fi
}

# 有输出即视为「进程存在」，供后面的流程判断使用
zygote_injected() {
    case "$KIND" in
    neo)
        p=$(pids_of zygote64)
        [ -z "$p" ] && { echo 0; return; }
        run sh -c "grep -c libzygisk /proc/$p/maps 2>/dev/null" | head -1
        ;;
    next)
        zs=$(run sh -c "cd $MODDIR && ./bin/zygiskd status 2>/dev/null" | \
             awk -F: '/^zygote_states/{gsub(/ /,"",$2); print $2}')
        echo "${zs:-0}"
        ;;
    *) echo 0 ;;
    esac
}

# ============================================================================
head1 "[0] 环境探测"
MY_UID=$(id -u)
say "  当前 UID=$MY_UID"
if [ "$MY_UID" = "0" ]; then
    # su 在 uid 0 下启动的 shell 通常不再是 setuid，故不能靠 su 探测，
    # 直接看能否读到 root 专属目录。
    if [ -r /data/adb/modules ]; then
        R_IS_ROOT=1
        say "  ✓ 已拿到 root（后续全程 root 执行）"
    else
        say "  ✗ uid=0 但读不到 /data/adb：环境异常"
        exit 1
    fi
else
    say "  · 非 root 会话（Shizuku shell / 普通终端）"
    if has_cmd su && su -c true >/dev/null 2>&1; then
        R_AS_ROOT=1
        say "  ✓ su 可用，关键步骤将提权执行"
    else
        say "  ✗ 无 root 且 su 不可用：只能做检测，无法完成修复"
        NO_PRIV=1
    fi
fi

SEL=$(run getenforce 2>/dev/null)
say "  SELinux=$( [ -n "$SEL" ] && echo "$SEL" || echo 未知 )"
if [ "$SEL" = "Permissive" ]; then
    say "  · 提示：宽容模式不是必须的（实测 Enforcing 下注入同样成功）"
fi
if ! run test -d /data/adb/modules; then
    say "  ✗ 读不到 /data/adb/modules —— 说明当前没有可用 Root，脚本无法继续"
    say "    请先在 KernelSU 管理器里给 Shizuku 或终端授予 root，再重新运行"
    exit 1
fi

# ============================================================================
head1 "[1] 识别 Zygisk 框架"
KIND=none
if run test -x "$NEO_BIN"; then
    KIND=neo
elif run ls "$MODDIR"/bin/*/zygiskd "$MODDIR/bin/zygiskd" >/dev/null 2>&1; then
    KIND=next
elif [ -n "$(run sh -c 'pgrep -f zygisk-ptrace64')" ]; then
    KIND=neo
elif [ -n "$(run sh -c 'pgrep -f zn-nsdaemon-zygote')" ]; then
    KIND=next
elif run test -d "$NEO_TMP"; then
    KIND=neo
fi

case "$KIND" in
neo)  say "  ✓ NeoZygisk（入口 $NEO_BIN）" ;;
next) say "  ✓ Zygisk Next（入口 $MODDIR/bin/zygiskd*）" ;;
*)
    say "  ✗ 未发现 NeoZygisk / Zygisk Next"
    say "    → 请先在 KernelSU 管理器刷入二者之一（模块 id 均为 zygisksu），重启后再跑本脚本"
    exit 1
    ;;
esac

# ============================================================================
head1 "[2] 启动 Zygisk 注入服务（★ 必须以模块目录为 CWD）"
case "$KIND" in
neo)
    # 清理旧 monitor：用 -x 精确进程名，避免 -f 命中本脚本自身命令行而自杀
    run sh -c "pkill -x zygisk-ptrace64" 2>/dev/null
    sleep 1
    run rm -f "$NEO_TMP/init_monitor"
    run sh -c "cd $MODDIR && export TMP_PATH=$NEO_TMP && nohup ./bin/zygisk-ptrace64 monitor > $MON_LOG 2>&1 < /dev/null &"
    sleep 3
    say "  monitor 进程: $(run sh -c 'pgrep -f zygisk-ptrace64' | tr '\n' ' ')"
    ;;
next)
    # 不能直接跑 post-fs-data.sh（末行前台常驻会导致会话挂死），照搬前置动作后自行后台化
    run mkdir -p /data/adb/zygisksu
    run sh -c "[ -f /data/adb/zygisksu/znctx ] && mv /data/adb/zygisksu/znctx /data/adb/zygisksu/znctx.old"
    run sh -c "[ -f /data/adb/zygisksu/modules_info ] && mv /data/adb/zygisksu/modules_info /data/adb/zygisksu/modules_info.old"
    run sh -c "cd $MODDIR && nohup ./bin/zygiskd daemon > $MON_LOG 2>&1 < /dev/null &"
    sleep 3
    NSD=$(run sh -c 'pgrep -f zn-nsdaemon-zygote' | tr '\n' ' ')
    say "  zygiskd / zn-nsdaemon-zygote: ${NSD:-（尚未出现，注入派生后才有）}"
    ;;
esac
say "  daemon 日志($MON_LOG) 末尾:"
run sh -c "tail -5 $MON_LOG 2>/dev/null" | sed 's/^/    /'
if [ "$NEO_TMP" = "/data/adb/neozygisk" ] && [ "$KIND" = "neo" ]; then
    say "  状态文件 $NEO_TMP/module.prop:"
    run sh -c "cat $NEO_TMP/module.prop 2>/dev/null" | sed 's/^/    /'
fi

# ============================================================================
head1 "[3] 重建 zygote（会短暂黑屏 10~30 秒）"
OLD64=$(pids_of zygote64)
say "  旧 zygote64 PID=${OLD64:-（无）}"
if [ -n "$NO_PRIV" ]; then
    say "  ✗ 无 root，无法杀 zygote，修复中止（仅检测）"
else
    # 按 PID 精确 kill：zygote64 的 comm 名是 main，pkill -x zygote64 匹配不到；
    # 而 pkill -f 会命中本脚本命令行里的 "zygote64" 字样把自己杀掉。
    PIDS="$OLD64 $(pids_of zygote)"
    say "  即将 kill -9 $PIDS"
    run kill -9 $PIDS 2>/dev/null
    NEW64=""
    i=0
    while [ $i -lt 60 ]; do
        sleep 2
        NOW=$(pids_of zygote64)
        if [ -n "$NOW" ] && [ "$NOW" != "$OLD64" ]; then
            NEW64=$NOW
            say "  新 zygote64 PID=$NEW64（约 $((i*2+2)) 秒）"
            break
        fi
        i=$((i + 1))
    done
    [ -z "$NEW64" ] && say "  ⚠️ 120 秒内未观察到 zygote64 重建（可能已重建但 PID 未及时读到）"
fi

# ============================================================================
head1 "[4] 验证 Zygisk 注入（判据按框架分派，轮询最多 15 秒）"
# 注入发生在 zygote 重建之后，通常需数秒；故轮询而非一次性判断。
INJ_OK=0
ST=""
i=0
while [ $i -lt 15 ]; do
    ST=$(zygote_injected)
    case "$KIND" in
    neo)
        say "  zygote64 映射 libzygisk 次数=${ST:-0}（>0 即已注入）"
        ;;
    next)
        say "  zygote_states=${ST:-0}（≥1 即已注入）"
        ;;
    esac
    [ "${ST:-0}" -gt 0 ] 2>/dev/null && { INJ_OK=1; break; }
    [ $i -ge 4 ] && [ $i -lt 14 ] && say "  …等待注入（$((i+1))/15 秒）"
    i=$((i + 1))
    sleep 1
done

# ============================================================================
head1 "[5] 验证 Vector / LSPosed 是否激活"
XP=none
XP_CLI=""
if run test -x "$VEC_DIR/cli"; then
    XP="Vector"; XP_CLI="$VEC_DIR/cli"
elif run test -x /data/adb/vector/bin/cli; then
    XP="Vector"; XP_CLI=/data/adb/vector/bin/cli
elif run test -x "$LSPD_CLI"; then
    XP="LSPosed"; XP_CLI="$LSPD_CLI"
fi

if [ "$XP" = "none" ]; then
    say "  · 未安装 Vector / LSPosed，跳过（Zygisk 部分已完成）"
else
    VD=$(run sh -c "pgrep -f vectord" | head -1)
    say "  框架=$XP  CLI=$XP_CLI"
    say "  vectord 进程=${VD:-（无）}"
    say "  已启用模块（注册级）:"
    run sh -c "sh $XP_CLI modules ls 2>/dev/null" | sed 's/^/    /' | head -20
    say "  最近 hook 记录（出现 [模块Tag] 即模块确实在运行）:"
    run sh -c "sh $XP_CLI log cat 2>/dev/null" | grep -aE '^\[' | tail -5 | sed 's/^/    /'
    say "  注：isFdAttached 字段不可信（实测在工作时仍为 false），已忽略；"
    say "      静默工作的模块不会有 log，属正常。"
fi

# ============================================================================
head1 "结论"
if [ "$INJ_OK" = "1" ]; then
    say "  ✓ Zygisk 已注入（$KIND）"
    [ "$XP" != "none" ] && say "  ✓ $XP 应由 Zygisk 自动激活；请在管理器里确认状态，并打开依赖该模块的 App 实测功能"
    say "  提示：模块改了作用域或新装后，需要重启对应 App（或再跑一次本脚本）才生效"
else
    say "  ✗ Zygisk 未确认注入"
    say "  排查顺序："
    say "    1) 确认 Root 可用：KernelSU 管理器里给 Shizuku / 终端授权 root"
    say "    2) 确认模块已刷入且已启用（zygisksu 目录存在，未被标记为禁用）"
    say "    3) 查看 $MON_LOG 里的报错；NeoZygisk 可看 $NEO_TMP/module.prop"
    say "    4) 仍失败：重启手机 → 重新越狱 → 再跑本脚本"
fi
say "DONE"
