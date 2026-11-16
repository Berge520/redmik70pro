# 一键修复「Zygisk / Vector / LSPosed 未激活」—— 手机上由 App 调用 su 执行
# 逻辑与 code/tools/activate_remote.sh 一致，仅去掉交互、末尾输出固定结论标记。
# 由 App 以 `su -c "sh <内置路径> fix|check"` 调用；第二个参数缺省视为 fix。

MODE="${1:-fix}"

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisksu
NEO_BIN="$MODDIR/bin/zygisk-ptrace64"
NEO_TMP=/data/adb/neozygisk
MON_LOG=/data/local/tmp/monitor.log
VEC_DIR=/data/adb/modules/zygisk_vector
LSPD_CLI=/data/adb/lspd/bin/cli

# `say "$(空)"` 时 echo 会输出空行，而 `adb shell` 对「只有空行」的输出返回 255，
# 容易被误认为脚本失败。这里把空内容换成占位符，保证每行都有内容。
say() {
    if [ -z "$*" ]; then
        echo "  （无输出）"
    else
        echo "$@"
    fi
}
head1() { echo ""; echo "===== $* ====="; }

has_cmd() { command -v "$1" >/dev/null 2>&1; }

# 送入独立会话启动（避免被 zygote 重启连带杀死），setsid 缺失时退回 nohup。
start_detached() {
    if has_cmd setsid; then
        setsid "$@" > "$MON_LOG" 2>&1 < /dev/null &
    else
        nohup "$@" > "$MON_LOG" 2>&1 < /dev/null &
    fi
}

# 同上，但日志写到指定文件（模块自带的 service.sh 用它，避免覆盖 monitor 日志）。
start_detached_log() {
    log=$1
    shift
    if has_cmd setsid; then
        setsid "$@" > "$log" 2>&1 < /dev/null &
    else
        nohup "$@" > "$log" 2>&1 < /dev/null &
    fi
}
pids_of() {
    if has_cmd pidof; then
        pidof "$1" 2>/dev/null
    else
        pgrep -x "$1" 2>/dev/null
    fi
}

# 真正的 zygote PID（可能不止一个：软重启瞬间新旧并存）。
# pidof zygote64 不可靠：App 被 zygote fork 出后 cmdline 会被改写成
# `zygote64 ...`，于是 pidof 会把一堆 App 进程也算进来（实测一次返回 3 个，
# 其中 2 个是 untrusted_app / system_app 域）。只有 SELinux 域为 zygote 的
# 才是真正的那一个，按它筛选。
zygote_pids() {
    for p in $(pids_of zygote64); do
        case "$(tr -d '\n' < /proc/$p/attr/current 2>/dev/null)" in
        u:r:zygote:*) echo "$p" ;;
        esac
    done
}

# 注意：zygote_pids 的结果可能是多行（两个 PID），下面所有比较都必须先
# 归一成单行，否则 `[ "$NOW" != "$OLD64" ]` 在多行时会报
# `unknown operand`，进而把已成功的重建误判成失败。
# 同时把多 PID 排序后取全量，便于日志里看清。
zygote_pid1() {
    zygote_pids | sort -n | tr '\n' ' ' | sed 's/ *$//'
}

# 「重建 zygote」判定专用：只看主 zygote，取最小 PID 的单个值。
#
# 不能拿 zygote_pid1 的多 PID 串直接比较：软重启瞬间新旧并存时，
# NOW="1234 5678"、OLD64="1234"，`!=` 成立就把「新 zygote 已起来」判成
# 成功，NEW64 于是变成两个 PID；接着 svc 兜底分支又会拿它去 kill -9，
# 等于再杀一次 zygote —— 重复 kill 正是触发 init 判崩溃循环、整机重启的主因。
# 这里只认单个 PID，比较才有意义。
zygote_main_pid() {
    zygote_pids | sort -n | head -1
}

head1 "[0] 环境探测"
MY_UID=$(id -u)
say "  UID=$MY_UID  模式=$MODE"
if [ "$MY_UID" != "0" ]; then
    say "  ✗ 未拿到 root。请在 KernelSU/APatch/Magisk 里允许本应用，然后重试。"
    say "RESULT:FAIL:NOROOT"
    exit 0
fi
say "  ✓ 已获得 root"
SEL=$(getenforce 2>/dev/null)
say "  SELinux=${SEL:-未知}"
if ! test -d /data/adb/modules; then
    say "  ✗ 读不到 /data/adb/modules，Root 环境异常"
    say "RESULT:FAIL:NOADB"
    exit 0
fi

head1 "[1] 识别 Zygisk 框架"
KIND=none
if test -x "$NEO_BIN"; then
    KIND=neo
elif ls "$MODDIR"/bin/*/zygiskd "$MODDIR/bin/zygiskd" >/dev/null 2>&1; then
    KIND=next
elif [ -n "$(pgrep -f zygisk-ptrace64)" ]; then
    KIND=neo
elif [ -n "$(pgrep -f zn-nsdaemon-zygote)" ]; then
    KIND=next
elif test -d "$NEO_TMP"; then
    KIND=neo
fi

# 注意：不能用「zygote 里出现 libzygisk 映射」作为成功判据。
# NeoZygisk 的 monitor 是先把 .so dlopen 进 zygote（这一步很容易成功），
# 再由它 fork 出真正干活的 daemon；只有 daemon 就位后 monitor 才会重新
# exec zygote 并改写 $NEO_TMP/module.prop 的状态行。因此旧判据会把
# 「只完成第一步」误报成已激活，而实际所有应用进程都拿不到 zygisk。
# 权威判据是 NeoZygisk 自己写出的状态文件。
# 注意该文件每行以 Tab 开头，先把 Tab 归一成空格再匹配。
neo_line() {
    tr '\t' ' ' < "$NEO_TMP/module.prop" 2>/dev/null | sed -n "s/^ *$1: *//p" | head -1
}

neo_state() { neo_line zygote64; }

# monitor 进程（zygisk-ptrace64）与它 fork 出的注入守护进程（zygiskd64）要分别看：
# 前者负责在 zygote 启动时 ptrace 注入，后者才是常驻干活的。
neo_monitor_pid() { pgrep -f zygisk-ptrace64 | tr '\n' ' ' | sed 's/ *$//'; }

neo_daemon_pid() { pgrep -f zygiskd64 | tr '\n' ' ' | sed 's/ *$//'; }

neo_daemon_ok() {
    [ -n "$(pgrep -f zygiskd64)" ]
}

# 单个进程内是否拿到 zygisk（libzygisk.so 被映射进来）。
proc_has_zygisk() {
    [ -n "$1" ] && grep -qi libzygisk /proc/$1/maps 2>/dev/null
}

# Zygisk 是否对普通 App 生效。
#
# 不能直接用「App 进程里有没有 libzygisk.so」来判断：KernelSU 开了
# kernel_umount（NeoZygisk 的 managedFeatures 里就会列出它），App 进程
# fork 出来后模块目录会被内核卸载，所以所有 App 进程的 maps 里都看不到
# libzygisk —— 这是正常的 root 隐藏，不代表没注入。
#
# 可靠判据是 zygote 本身：它必须
#   (1) 映射了 libzygisk，
#   (2) TracerPid=0（monitor 只在注入瞬间 ptrace，完成后会 detach；一直挂着
#       非 0 说明还卡在注入中，此时 App 起不来也没法用模块），
#   (3) NeoZygisk 自报的 daemon64 处于 running。
# 三者都满足时，新启动的 App 才会真正拿到注入。
#
# 注意 pidof 可能返回多个 PID（软重启期间新旧 zygote 并存），必须逐个试。
app_injected() {
    ok=0
    for p in $(zygote_pids); do
        proc_has_zygisk "$p" || continue
        tp=$(awk '/^TracerPid:/{print $2}' /proc/$p/status 2>/dev/null)
        [ "${tp:-1}" = "0" ] || continue
        ok=1
        break
    done
    [ "$ok" = "1" ] || { echo 0; return; }
    if [ "$KIND" = "neo" ]; then
        case "$(neo_line daemon64)" in
        *running*) echo 1 ;;
        *) echo 0 ;;
        esac
    else
        echo 1
    fi
}

zygote_injected() {
    case "$KIND" in
    neo)
        # 自报 injected 不能单独采信：实测出现过 zygote64 里一个 libzygisk 映射
        # 都没有、状态文件却写着 injected 的情况（monitor 已退出但状态没刷新）。
        # 判据 = zygote 真有映射 + NeoZygisk 的 daemon 在跑。
        neo_daemon_ok || { echo 0; return; }
        for p in $(zygote_pids); do
            proc_has_zygisk "$p" && { echo 1; return; }
        done
        echo 0
        ;;
    next)
        zs=$(cd "$MODDIR" 2>/dev/null && ./bin/zygiskd status 2>/dev/null | \
             awk -F: '/^zygote_states/{gsub(/ /,"",$2); print $2}')
        echo "${zs:-0}"
        ;;
    *) echo 0 ;;
    esac
}

# 识别注入框架的统一入口：check 与 fix 都要用，避免两处各写一份而逐渐不一致
# （之前 check 分支只认 Vector，装了 LSPosed 时会显示 vectord 未运行，误导用户）。
detect_xp() {
    XP=none
    XP_CLI=""
    if test -x "$VEC_DIR/cli"; then
        XP=Vector; XP_CLI="$VEC_DIR/cli"
    elif test -x /data/adb/vector/bin/cli; then
        XP=Vector; XP_CLI=/data/adb/vector/bin/cli
    elif test -x "$LSPD_CLI"; then
        XP=LSPosed; XP_CLI="$LSPD_CLI"
    fi
}

# 各框架的常驻守护进程名不同，不能一律拿 vectord 去探测，
# 否则装了 LSPosed 的设备会一直显示「vectord 未运行」。
xp_daemon_pid() {
    case "$XP" in
    Vector) pgrep -f vectord | head -1 ;;
    LSPosed) pgrep -f zsld | head -1 ;;
    esac
}

# 打印当前状态（check 与 fix 收尾共用）
show_state() {
    case "$KIND" in
    neo)
        say "  NeoZygisk 自报状态:"
        say "    zygote64: $(neo_state | sed 's/^$/(状态文件未生成)/')"
        say "    daemon64: $(neo_line daemon64 | sed 's/^$/(未知)/')"
        say "    monitor 进程: $(neo_monitor_pid | sed 's/^$/未运行/')"
        say "    daemon 进程: $(neo_daemon_pid | sed 's/^$/未运行/')"
        # module.prop 是上次运行留下的文件，重启后不会自动清空：实测出现过
        # 手机重启后它仍写着 injected / running，而两个进程其实都不在。
        # 进程不在时明确提示，避免把残留状态当成「已激活」。
        if [ -z "$(neo_monitor_pid)$(neo_daemon_pid)" ]; then
            say "    ⚠️ 上面两行是上次运行的残留记录，对应进程已不存在，实际未注入"
        fi
        ;;
    next)
        say "  Zygisk Next zygote_states=$(zygote_injected)"
        ;;
    esac
    say "  注入链路实测: $( [ "$(app_injected)" = 1 ] && echo '正常（新启动的 App 会拿到 zygisk）' || echo '未打通' )"
    # 只有 Vector 有常驻的 vectord；LSPosed 的守护进程叫别的名字，
    # 不能拿 vectord 去判断它，否则会给用户一个错误的「未运行」。
    case "$XP" in
    Vector) say "  Vector daemon(vectord): $(xp_daemon_pid | sed 's/^$/未运行/')" ;;
    LSPosed) say "  LSPosed daemon(zsld): $(xp_daemon_pid | sed 's/^$/按开源版命名探测，未读到不算失败/')" ;;
    esac
}

# 只检测：直接看现状并给结论
if [ "$MODE" = "check" ]; then
    case "$KIND" in
    neo)  say "  ✓ NeoZygisk" ;;
    next) say "  ✓ Zygisk Next" ;;
    *)    say "  ✗ 未安装 NeoZygisk / Zygisk Next"
          say "RESULT:FAIL:NOZYGISK"; exit 0 ;;
    esac
    detect_xp
    show_state
    ST=$(zygote_injected)
    if [ "${ST:-0}" -gt 0 ] 2>/dev/null; then
        say "  ✓ 当前已处于注入状态"
        say "RESULT:OK:ALREADY"
    else
        say "  ✗ 当前未注入（需要点「一键激活」修复）"
        say "RESULT:FAIL:NOTACTIVE"
    fi
    exit 0
fi

case "$KIND" in
neo)  say "  ✓ NeoZygisk（入口 bin/zygisk-ptrace64）" ;;
next) say "  ✓ Zygisk Next（入口 bin/zygiskd*）" ;;
*)
    say "  ✗ 未发现 NeoZygisk / Zygisk Next"
    say "    → 请先在 KernelSU 管理器刷入二者之一，重启后再试"
    say "RESULT:FAIL:NOZYGISK"
    exit 0
    ;;
esac

# 系统已经过载时，绝不做任何 kill / 重启动作。
# 负载高说明有进程在狂转或卡在不可中断状态（D），此时重建 zygote 极易演变成
# 崩溃循环，最后被 init 判定失败而整机重启 —— 临时 root 就没了。
# 实测过一次 load 66 时手机黑屏发烫，宁可让用户等，也不冒这个险。
LOAD1=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null | cut -d. -f1)
case "$LOAD1" in
''|*[!0-9]*) LOAD1=0 ;;
esac
if [ "$LOAD1" -ge 20 ]; then
    say "  ⚠️ 系统负载过高（1 分钟负载 $LOAD1），已中止，不做任何重启动作"
    say "     → 请先让手机凉下来、负载降到 20 以下，再点「一键激活」"
    say "     → 现在强行重建 zygote 可能变成崩溃循环，进而整机重启丢掉临时 root"
    say "RESULT:FAIL:BUSY"
    exit 0
fi

# 内存闸门：本机实测过两次「内存被吃干 → kswapd 占满一个核 → 黑屏卡死」。
# 卡死前 MemFree 只剩十几 MB、swap 全部用满，此时再重建 zygote 只会加速恶化。
# MemAvailable 是内核估算的「还能拿出来用」的量，比 MemFree 更能反映真实余量。
MEMAVAIL=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
case "$MEMAVAIL" in
''|*[!0-9]*) MEMAVAIL=9999999 ;;
esac
if [ "$MEMAVAIL" -lt 600000 ]; then
    say "  ⚠️ 可用内存过低（$((MEMAVAIL / 1024)) MB），已中止，不做任何重启动作"
    say "     → 请先清理后台应用，等手机凉下来再试"
    say "     → 内存不足时重建 zygote 会让所有 App 重新冷启动，直接触发卡死"
    say "RESULT:FAIL:LOWMEM"
    exit 0
fi

# 已经激活时绝不再重建 zygote。
# 重建的代价是全机所有 App 同时冷启动，这是本机实测中内存/swap 被抽干、
# 黑屏卡死的直接诱因。用户重复点「一键激活」是最容易踩到这条的场景，
# 所以在动手之前就拦下来，直接告诉他已经好了。
detect_xp
if [ "$(zygote_injected)" = "1" ] && [ "$(app_injected)" = "1" ]; then
    say "  ✓ 已经处于注入状态（zygote 已有 libzygisk、daemon 在跑）"
    say "  → 无需重复激活：重复重建 zygote 会让全机 App 冷启动，是卡死的主要诱因"
    say "  → 如果某个模块没生效，请直接重开那个 App，不要重新点激活"
    say "RESULT:OK:ALREADY"
    exit 0
fi

head1 "[2] 启动 Zygisk 注入服务（必须以模块目录为 CWD）"
case "$KIND" in
neo)
    # -x 精确进程名：用 -f 会命中本脚本自身的命令行而自杀。
    # 旧 daemon（zygiskd64）被 reparent 到 init 后不会随 monitor 一起退出，
    # 残留会占着 socket，必须显式清掉，否则新 daemon 可能连不上。
    pkill -x zygisk-ptrace64 2>/dev/null
    pkill -f zygiskd64 2>/dev/null
    sleep 1
    rm -f "$NEO_TMP/init_monitor"
    ( cd "$MODDIR" && export TMP_PATH="$NEO_TMP" && \
      start_detached ./bin/zygisk-ptrace64 monitor )
    # 注意：monitor 要等下面的 zygote 重建才会 fork 出 daemon（zygiskd64），
    # 此刻等它是白等，日志里也不会出现 "starting daemon"。这里只确认 monitor
    # 自己起来了，真正的判据放在 [4]。
    i=0
    while [ $i -lt 10 ] && [ -z "$(neo_monitor_pid)" ]; do
        sleep 1
        i=$((i + 1))
    done
    say "  monitor 进程: $(neo_monitor_pid | sed 's/^$/未运行/')"
    if [ -z "$(neo_monitor_pid)" ]; then
        say "  ⚠️ monitor 没起来，看上面的日志；仍会继续尝试重建 zygote"
    fi
    ;;
next)
    # 不能直接跑 post-fs-data.sh（末行前台常驻会挂死会话）
    mkdir -p /data/adb/zygisksu
    [ -f /data/adb/zygisksu/znctx ] && mv /data/adb/zygisksu/znctx /data/adb/zygisksu/znctx.old
    [ -f /data/adb/zygisksu/modules_info ] && \
        mv /data/adb/zygisksu/modules_info /data/adb/zygisksu/modules_info.old
    ( cd "$MODDIR" && start_detached ./bin/zygiskd daemon )
    sleep 3
    say "  zn-nsdaemon-zygote: $(pgrep -f zn-nsdaemon-zygote | tr '\n' ' ')"
    ;;
esac
say "  daemon 日志末尾:"
tail -5 "$MON_LOG" 2>/dev/null | sed 's/^/    /'

# Zygisk 类模块的 service.sh 只在开机时被 root 管理器跑一次，它们靠这个时机
# 启动自己的常驻 daemon（Vector 的 vectord 就是这样起来的）。软重启 zygote
# 不会重跑 service.sh，于是注入链断了。这里按模块脚本自己的方式补跑。
start_sub_modules() {
    for d in /data/adb/modules/*; do
        [ -d "$d/zygisk" ] || continue
        [ -f "$d/disable" ] && continue
        [ -f "$d/service.sh" ] || continue
        case "$d" in "$MODDIR"|*/zygisksu) continue ;; esac
        nm=$(basename "$d")
        SUB_LOG="/data/local/tmp/${nm}_service.log"
        say "  重启 $nm 的常驻服务"
        # 旧 daemon 还活着与否很关键：zygote 换了 PID 后，daemon 内部记的还是旧
        # zygote，会一直连不上。必须先杀掉再让 service.sh 重新拉起。
        case "$nm" in
        zygisk_vector) pkill -f 'vectord' 2>/dev/null ; sleep 1 ;;
        esac
        say "    日志: $SUB_LOG"
        start_detached_log "$SUB_LOG" sh "$d/service.sh"
    done
}

head1 "[2.5] 启动 Zygisk 模块的常驻服务"
start_sub_modules
sleep 5
say "  vectord: $(pgrep -f vectord | tr '\n' ' ' | sed 's/ *$//' | sed 's/^$/未运行/')"

head1 "[3] 重建 zygote（屏幕会短暂黑一下，本机不会重启）"
OLD64=$(zygote_main_pid)
say "  旧 zygote64 PID=${OLD64:-（无）}"
# 拿不到旧 PID 就绝对不能往下 kill：kill -9 后面没有参数时，在部分 shell 里
# 会被当成空参数直接返回，但「以为杀掉了其实没杀」会让后面的等待白等 50 秒；
# 更糟的是 OLD64 为空时，一旦有任何分支退化成 `kill -9`，行为不可预期。
# 此时直接交给用户判断，不要冒险。
if [ -z "$OLD64" ]; then
    say "  ✗ 读不到 zygote64 的 PID（可能 zygote 已经没了或 /proc 不可读）"
    say "     → 先在「仅检测」里看状态；不要点第二次，也不要手动重启"
    say "RESULT:FAIL:NOZYGOTE"
    exit 0
fi
# 为什么不能只 kill zygote：
#   zygote 死后 init 会按 onrestart 把依赖它的 system_server 也重启，
#   而 system_server 重新拉起时又可能连带重启 zygote；在这种「互相重启」的
#   路径上，init 一旦认定服务进入崩溃循环，就会直接 reboot 整机 —— 本机是
#   KernelSU late-load 临时 root，一整机重启 root 就丢了，必须重新越狱。
#
# 实测有效的做法（本机 MIUI/HyperOS，Android 15）：
#   1) 先用 `svc system-server stop` 把 system_server 停掉并让它保持停止，
#      init 此时不会因为 zygote 死掉而去重启它；
#   2) 再 kill zygote，init 只重启 zygote 本身；
#   3) 最后 `svc system-server start` 由新 zygote fork 出新的 system_server。
#   实测 zygote 2 秒内重建、uptime 连续、boot_completed 始终为 1，即未重启整机。
#
# 绝不在循环里重复 kill：重复 kill 才是触发 init 判崩溃循环、整机重启的主因。
#
# 两条撤销 zygote 的路径，按安全性排序：
#   A) setprop ctl.restart zygote —— init 的正规接口，由 init 自己重启 zygote，
#      不经过“子进程崩溃 → 计数 → reboot”那条路，理论上最不容易整机重启；
#   B) svc system-server stop → kill -9 zygote → svc system-server start
#      —— 已实测在本机不重启整机（zygote 2 秒内重建、uptime 连续、
#      boot_completed 始终为 1），作为 A 不生效时的兜底。
NEW64=""
if has_cmd setprop; then
    say "  setprop ctl.restart zygote（init 正规接口，优先）"
    setprop ctl.restart zygote >/dev/null 2>&1
    i=0
    while [ $i -lt 8 ]; do
        sleep 1
        NOW=$(zygote_main_pid)
        if [ -n "$NOW" ] && [ "$NOW" != "$OLD64" ]; then
            NEW64=$NOW
            say "  ✓ 新 zygote64 PID=$NEW64（约 $((i + 1)) 秒）"
            break
        fi
        i=$((i + 1))
    done
    [ -z "$NEW64" ] && say "  ctl.restart 未生效，改用 svc + kill 兜底"
fi

# 注意这里必须用 elif 串起来，不能再写第二个独立的 if…else：
# else 只会绑定到紧邻的 if 上，ctl.restart 已成功时第二个 if 条件为假，
# 就会落入它的 else 再 kill 一次 —— 这正是「整机重启」的老坑。
if [ -n "$NEW64" ]; then
    : # ctl.restart 已成功，什么也不用做
elif has_cmd svc; then
    say "  svc system-server stop（先摘掉 system_server，避免连锁重启）"
    svc system-server stop >/dev/null 2>&1
    sleep 3
    say "  kill -9 $OLD64"
    kill -9 $OLD64 2>/dev/null
    i=0
    while [ $i -lt 50 ]; do
        sleep 1
        NOW=$(zygote_main_pid)
        if [ -n "$NOW" ] && [ "$NOW" != "$OLD64" ]; then
            NEW64=$NOW
            say "  ✓ 新 zygote64 PID=$NEW64（约 $((i + 1)) 秒）"
            break
        fi
        i=$((i + 1))
    done
    # 新 zygote 起来后立刻把 system_server 拉回来（更早没意义：它由 zygote fork）
    say "  svc system-server start"
    svc system-server start >/dev/null 2>&1
else
    # ctl.restart 与 svc 都不可用，只能硬杀。
    say "  ⚠️ 没有 svc / ctl.restart 未生效，直接 kill zygote（有概率触发整机重启）"
    kill -9 $OLD64 2>/dev/null
    i=0
    while [ $i -lt 50 ]; do
        sleep 1
        NOW=$(zygote_main_pid)
        if [ -n "$NOW" ] && [ "$NOW" != "$OLD64" ]; then
            NEW64=$NOW
            say "  ✓ 新 zygote64 PID=$NEW64（约 $((i + 1)) 秒）"
            break
        fi
        i=$((i + 1))
    done
fi
[ -z "$NEW64" ] && say "  ⚠️ 50 秒内未读到新 zygote64（可能已重建但读取延迟）"
# 如果 zygote 起不来，脚本自己不要做任何重启/再 kill 的动作，直接交给用户判断，
# 避免 init 判定崩溃循环而完整重启整机（那样临时 root 就没了）。
if [ -z "$(zygote_pids)" ]; then
    say "  ✗ zygote64 不存在，系统可能正在自行恢复"
    say "     → 请等 1 分钟：若屏幕恢复则直接点「仅检测」；"
    say "       若界面仍不可用，再手动重启并重新越狱（不要连续点击按钮）"
    say "RESULT:FAIL:NOZYGOTE"
    exit 0
fi
# 新 zygote 起来后，system_server 还要几十秒才能把桌面拉回来，
# 这期间不要急着判定失败，统一由 [4] 轮询。
# 走 ctl.restart 时 init 会自己把 system_server 一起重启；走 svc 路径时我们已经
# 显式 start 过了。两条路都要等 boot_completed 与 system_server 双双就位。
say "  等待 system_server 恢复（最多 60 秒）…"
i=0
while [ $i -lt 60 ]; do
    [ "$(getprop sys.boot_completed)" = "1" ] && [ -n "$(pgrep -f system_server)" ] && break
    sleep 1
    i=$((i + 1))
done
SS_PID=$(pgrep -f system_server | head -1)
say "  system_server: ${SS_PID:-未运行}  boot_completed=$(getprop sys.boot_completed)"
if [ -z "$SS_PID" ]; then
    say "  ✗ system_server 60 秒内没起来"
    say "     → 不要重复点按钮；等 1 分钟看桌面是否恢复，再点「仅检测」"
    say "RESULT:FAIL:NOSS"
    exit 0
fi

# 重建后复查余量：这一刻全机 App 正在冷启动，是内存占用的峰值时刻，
# 也是三次卡死实际发生的位置。入口那次检查代表不了现在。
# 这里不再做任何动作（zygote 已经重建完，停不下来），只把危险信号报给用户，
# 让他在系统开始换页抖动之前主动收手，而不是继续操作把机器拖死。
MEMNOW=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
case "$MEMNOW" in
''|*[!0-9]*) MEMNOW=9999999 ;;
esac
SWAPFREE=$(awk '/^SwapFree:/{print $2}' /proc/meminfo 2>/dev/null)
case "$SWAPFREE" in
''|*[!0-9]*) SWAPFREE=9999999 ;;
esac
LOADNOW=$(cut -d' ' -f1 /proc/loadavg 2>/dev/null)
say "  重建后余量: 可用内存=$((MEMNOW / 1024))MB  swap空闲=$((SWAPFREE / 1024))MB  load=$LOADNOW"
if [ "$MEMNOW" -lt 800000 ] || [ "$SWAPFREE" -lt 300000 ]; then
    say "  ⚠️ 余量偏低：请立刻停止操作手机，锁屏静置 2 分钟，让系统把后台清干净"
    say "     → 此时继续开 App / 装应用会直接触发换页抖动，进而黑屏卡死"
    TOO_TIGHT=1
fi

# 打印日志用的辅助：real zygote 列表。
# 只用于展示，不参与判定（判定统一走 app_injected/zygote_injected）。
say_zygote_tracer() {
    out=""
    for z in $(zygote_pids); do
        out="$out zygote64($z) TracerPid=$(awk '/^TracerPid:/{print $2}' /proc/$z/status 2>/dev/null)"
    done
    say " $out"
}

head1 "[4] 验证注入（最多等 40 秒）"
INJ_OK=0
APP_OK=0
i=0
while [ $i -lt 40 ]; do
    ST=$(zygote_injected | head -1 | tr -dc '0-9')
    ST=${ST:-0}
    # 不逐秒刷屏，只打印关键的几次（第 1 次 / 每 10 秒一次 / 成功时）
    if [ $i = 0 ] || [ $((i % 10)) = 0 ] || [ "$ST" -gt 0 ]; then
        if [ "$KIND" = "neo" ]; then
            say "  NeoZygisk 自报：$(neo_state | sed 's/^$/（状态文件未生成）/')"
        else
            say "  zygote_states=$ST（≥1 即已注入）"
        fi
    fi
    if [ "$ST" -gt 0 ]; then INJ_OK=1; break; fi
    sleep 1
    i=$((i + 1))
done
# 自报注入不代表已经打通：zygote 还要真正跑起来、daemon 要在跑
APP_OK=0
if [ "$INJ_OK" = "1" ]; then
    i=0
    while [ $i -lt 15 ]; do
        APP_OK=$(app_injected | head -1 | tr -dc '0-9')
        APP_OK=${APP_OK:-0}
        [ "$APP_OK" = "1" ] && break
        sleep 1
        i=$((i + 1))
    done
    say "  注入链路实测: $( [ "$APP_OK" = "1" ] && echo '✓ 正常（新启动的 App 会拿到 zygisk）' || echo '✗ 未打通' )"
    # 逐个打印真实 zygote 的 TracerPid 便于排查（zygote_pids 已排除 App 进程）
    say_zygote_tracer
    [ "$KIND" = "neo" ] && say "  daemon64=$(neo_line daemon64)"
fi

head1 "[5] Vector / LSPosed 状态"
detect_xp

if [ "$XP" = "none" ]; then
    say "  未安装 Vector / LSPosed，跳过"
elif [ "$XP" = "LSPosed" ]; then
    # LSPosed 的 cli 参数结构与 Vector 不同（没有 modules ls / log cat），
    # 直接套用只会得到一堆报错，反而误导用户。这里只报 daemon 是否在跑，
    # 真正的激活情况让用户在 LSPosed 管理器里看「日志」页。
    say "  框架=LSPosed  daemon(zsld)=$(xp_daemon_pid | sed 's/^$/未读到（不影响注入判定）/')"
    say "  未启用模块与 hook 日志请在 LSPosed 管理器内查看"
else
    say "  框架=Vector  daemon(vectord)=$(xp_daemon_pid | sed 's/^$/未读到（不影响注入判定）/')"
    say "  已启用模块:"
    # 新 zygote 刚起来时，框架的 daemon 可能还没连上它，此时 modules ls 只会返回
    # "No records found."。这里短轮询等它连上，避免把时序问题误报成「没有模块」。
    MODS=""
    i=0
    while [ $i -lt 20 ]; do
        MODS=$(sh "$XP_CLI" modules ls 2>/dev/null)
        case "$MODS" in
        *"No records found"*|"") sleep 1; i=$((i + 1)) ;;
        *) break ;;
        esac
    done
    if [ -z "$MODS" ] || echo "$MODS" | grep -q "No records found"; then
        say "    ⚠️ 20 秒内没读到模块列表（框架 daemon 未连上新 zygote）"
        say "       → 先等 30 秒再点「仅检测」；仍为空再考虑其它办法，别急着重启（会丢临时 root）"
    else
        echo "$MODS" | head -20 | sed 's/^/    /'
    fi
    say "  最近 hook 日志（出现 [模块Tag] 即模块在运行）:"
    HLOG=$(sh "$XP_CLI" log cat 2>/dev/null | grep -aE '^\[' | tail -5)
    if [ -n "$HLOG" ]; then
        echo "$HLOG" | sed 's/^/    /'
    else
        # 只有 ----part 1 start---- 这类分隔行时 grep 结果为空。实测这不是故障：
        # 模块不打印日志时日志就是空的，而 Vector 管理器里照样显示「已激活」。
        # 所以不能把「无日志」当成「模块没生效」，判定以管理器显示的状态为准。
        say "    （暂无模块日志；模块不打印日志时为空，属正常）"
        say "    → 是否真正激活，以 Vector 管理器里显示的「已激活」为准"
    fi
    # 实测结论：本机 root 隐藏生效时，框架自己的 isFdAttached 恒为 false，
    # 且普通 App 进程的 maps 里也看不到 libzygisk，两者都不能当失败判据。
    say "  注：Vector 的 isFdAttached 与 App 进程内的 libzygisk 映射均受 root 隐藏影响，"
    say "      不作为判据。"
fi

# 关于「模块有没有真正送达 App」：不要用遍历 /proc/*/fd 的方式去查。
# 实测代价极高：本机 100+ 个 App 进程、单个进程最多 879 个 fd，每个 fd 都要
# fork 一个 readlink/stat，一次扫描就是上万个进程创建，曾把整机 load 打到 66
# 并导致黑屏死机。而且结论本身也不可靠（本机 App 进程里从来查不到模块 memfd）。
# 这里只用零成本的证据：NeoZygisk 状态文件 + zygote 自身状态。
head1 "结论"
if [ "$INJ_OK" = "1" ] && [ "$APP_OK" = "1" ]; then
    say "  ✓ Zygisk 已注入（$KIND），zygote 侧注入完成、daemon 在跑"
    [ "$XP" != "none" ] && say "  → 请直接打开用到模块的 App 实测功能；功能正常即完全生效"
    say "RESULT:OK:INJECTED"
elif [ "$INJ_OK" = "1" ]; then
    say "  ⚠️ $KIND 自报已注入，但注入链路没打通（zygote 未完成初始化或 daemon 没在跑）"
    say "     → 常见原因：zygote 刚被杀还没起来、monitor 卡住、模块目录未正确挂载"
    say "     → 稍等 10 秒再点一次「仅检测」；仍不行再看模块日志，别急着重启（会丢临时 root）"
    say "RESULT:WARN:NOAPP"
else
    say "  ✗ 未确认注入。可依次排查："
    say "    1) 模块 zygisksu 是否已刷入且处于启用状态"
    say "    2) 查看 $MON_LOG 的报错"
    say "    3) 临时 root 环境请勿频繁重启：先只点「仅检测」确认状态，"
    say "       确需重启时要重新越狱（重启会丢临时 root）"
    say "RESULT:FAIL:NOINJECT"
fi
