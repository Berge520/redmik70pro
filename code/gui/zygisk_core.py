# -*- coding: utf-8 -*-
"""Zygisk 框架探测与激活（NeoZygisk / Zygisk Next）。

从 core.py 拆出的独立后端模块：只依赖标准库与 Runner 协议（runner.su /
runner.shell），不依赖 tkinter，也不反向 import core。
core.py 通过 `from zygisk_core import *` 转发，故外部仍以 core.xxx 访问。
"""

import re
import time


# 公开 API 边界：限定 `from zygisk_core import *`（core.py 转发）的范围，
# 避免把 re / time 等模块级名字一并泄漏出去。清单须与 core.py 的显式 import 一致。
__all__ = [
    # 常量
    'ZYGISK_MODULE',
    'ZYGISK_MODULE_DIR',
    'ZYGISK_NEO_BIN',
    'ZYGISK_NEO_TMP',
    'ZYGISK_NEO_PROP',
    'ZYGISK_NEXT_BIN',
    'ZYGISK_NEXT_BIN64',
    'ZYGISK_NEXT_PROC',
    'ZYGISK_MONITOR_LOG',
    'ZY_NONE',
    'ZY_NEO',
    'ZY_NEXT',
    'ZY_LABEL',
    # 函数
    'detect_zygisk',
    'zygisk_monitor_running',
    'zygisk_read_prop',
    'zygisk_status',
    'zygisk_zygote_count',
    'start_zygisk_daemon',
    'zygote64_pid',
    'zygote_injected',
    'restart_zygote',
]


# ---------------------------------------------------------------
#  Zygisk 框架探测与激活（兼容 NeoZygisk 与 Zygisk Next）
# ---------------------------------------------------------------
# ⚠️ 二者模块 ID **同为 `zygisksu`**（历史上都沿用 Magisk 的 zygisksu 目录），
#    无法靠目录名区分，必须靠「入口可执行文件 / 常驻进程名」判定：
#      · NeoZygisk (JingMatrix)：bin/zygisk-ptrace64，常驻 zygisk-ptrace64，
#        运行时目录 /data/adb/neozygisk，状态写在 $TMP/module.prop（键值文本）。
#      · Zygisk Next (LSPosed Developers)：bin/zygiskd（软链→zygiskd64）、
#        bin/zygiskd32、bin/zygiskd64。注入完成后会为每个 zygote 派生一个名为
#        `zn-nsdaemon-zygote` / `zn-nsdaemon-zygote_secondary` 的守护进程，并建立
#        `@zn_zygote_*` / `@zn_init_*` 系列 unix socket；zygiskd 自身的「管理器」
#        进程 comm 名不可见（ps 的 NAME 列看不到），只能靠 /proc/<pid>/exe 软链识别。
#        状态查询：在 $MODDIR 下执行 `./bin/zygiskd status`，输出 `zygote_states: N`
#        （N=已注入的 zygote 数）与 `zygote_state_i:...` 明细。
# ⚠️ **注入判据不可通用**：NeoZygisk 把 libzygisk.so 常驻映射在 zygote 里，可用
#    `grep -c libzygisk /proc/<zygote64>/maps` 判定；但 Zygisk Next 注入后会**把
#    自身 loader（libzn_loader.so 等）从 zygote 的 maps 中 unmap 掉**（反检测），
#    实测该 grep 恒为 0。故 Zygisk Next 必须改用 `zygiskd status` 的 `zygote_states`。
#    详见 docs/troubleshooting.md「七、GUI 工具的框架自动识别」。
ZYGISK_MODULE = 'zygisksu'
ZYGISK_MODULE_DIR = '/data/adb/modules/%s' % ZYGISK_MODULE

# NeoZygisk 专属
ZYGISK_NEO_BIN = ZYGISK_MODULE_DIR + '/bin/zygisk-ptrace64'
ZYGISK_NEO_TMP = '/data/adb/neozygisk'
ZYGISK_NEO_PROP = ZYGISK_NEO_TMP + '/module.prop'

# Zygisk Next 专属
ZYGISK_NEXT_BIN = ZYGISK_MODULE_DIR + '/bin/zygiskd'   # 兼容不分 ABI 子目录的旧版
ZYGISK_NEXT_BIN64 = ZYGISK_MODULE_DIR + '/bin/zygiskd64'
ZYGISK_NEXT_PROC = 'zn-nsdaemon-zygote'                # 注入后派生的 zygote 守护进程

ZYGISK_MONITOR_LOG = '/data/local/tmp/monitor.log'

# 探测结果类型
ZY_NONE = 'none'
ZY_NEO = 'neo'          # NeoZygisk
ZY_NEXT = 'next'        # Zygisk Next
ZY_LABEL = {
    ZY_NEO: 'NeoZygisk',
    ZY_NEXT: 'Zygisk Next',
    ZY_NONE: '未检测到 Zygisk 框架',
}


def detect_zygisk(runner):
    """探测本机安装的 Zygisk 实现，返回 ZY_* 常量之一。

    判据（按可靠性排序）：
      1. 入口文件：bin/zygisk-ptrace64 → NeoZygisk；bin/**/zygiskd → Zygisk Next。
         （Zygisk Next 的 zygiskd 按 ABI 分目录，故用通配匹配任意一层。）
      2. 常驻进程：zygisk-ptrace64 / zn-nsdaemon-zygote（运行时兜底）。
      3. 运行时目录：/data/adb/neozygisk 存在 → NeoZygisk。
    均不命中返回 ZY_NONE。
    """
    # 1. 入口文件（最可靠，模块未运行时也可判定）
    if runner.su('test -x ' + ZYGISK_NEO_BIN, quiet=True, timeout=15).ok:
        return ZY_NEO
    # Zygisk Next 的 zygiskd 位于 bin/<abi>/zygiskd
    if runner.su('ls %s/bin/*/zygiskd %s/bin/zygiskd 2>/dev/null'
                 % (ZYGISK_MODULE_DIR, ZYGISK_MODULE_DIR),
                 quiet=True, timeout=15).text.strip():
        return ZY_NEXT
    # 2. 常驻进程兜底
    if runner.shell('pgrep -f zygisk-ptrace64', quiet=True, timeout=15).text.strip():
        return ZY_NEO
    # Zygisk Next 注入后会派生 zn-nsdaemon-zygote（未注入时不存在）；
    # zygiskd 管理器进程 comm 名不可见，故再兜一个 exe 软链判定。
    if runner.shell('pgrep -f %s' % ZYGISK_NEXT_PROC,
                    quiet=True, timeout=15).text.strip():
        return ZY_NEXT
    if runner.su('for p in /proc/[0-9]*; do '
                 'e=$(readlink $p/exe 2>/dev/null); '
                 'case "$e" in *zygiskd*) exit 0;; esac; done; exit 1',
                 quiet=True, timeout=20).ok:
        return ZY_NEXT
    # 3. 运行时目录兜底
    if runner.su('test -d ' + ZYGISK_NEO_TMP, quiet=True, timeout=15).ok:
        return ZY_NEO
    return ZY_NONE


def zygisk_monitor_running(runner, kind=None):
    """Zygisk 注入服务是否在运行（按框架分派）。

    · NeoZygisk：常驻进程名 zygisk-ptrace64（monitor）。
    · Zygisk Next：zygiskd 管理器进程（comm 名不可见），用 /proc/<pid>/exe
      软链是否指向 bin/zygiskd* 判定；注入后还会派生 zn-nsdaemon-zygote。
    kind 为空时自动探测，避免重复探测可显式传入。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        return bool(runner.shell('pgrep -f zygisk-ptrace64',
                                 quiet=True, timeout=15).text.strip())
    if kind == ZY_NEXT:
        # 管理器进程在 → daemon 已拉起（这是「服务在跑」的可靠判据）。
        if runner.su('for p in /proc/[0-9]*; do '
                     'e=$(readlink $p/exe 2>/dev/null); '
                     'case "$e" in *zygiskd*) exit 0;; esac; done; exit 1',
                     quiet=True, timeout=20).ok:
            return True
        # 兜底：已注入时必有 zn-nsdaemon-zygote。
        return bool(runner.shell('pgrep -f %s' % ZYGISK_NEXT_PROC,
                                 quiet=True, timeout=15).text.strip())
    return False


def zygisk_read_prop(runner):
    """读取 NeoZygisk 运行时状态文件，返回 {key: value}。

    monitor 运行时会实时重写 $ZYGISK_NEO_TMP/module.prop，内容形如：
        monitor: 😋 tracing
        zygote64: 😋 injected
        daemon64: 😋 running
        Modules (2): hma_oss_zygisk, zygisk_vector
    monitor 未运行时该文件可能不存在或为空，此时返回空字典。
    （Zygisk Next 无此文件，调用前请先用 detect_zygisk 判定。）
    """
    res = runner.su('cat %s' % ZYGISK_NEO_PROP, quiet=True, timeout=15)
    info = {}
    if not res.ok:
        return info
    for line in res.lines:
        if ':' not in line:
            continue
        key, _, value = line.partition(':')
        info[key.strip()] = value.strip()
    return info


def zygisk_status(runner, kind=None):
    """返回 Zygisk 状态摘要文本（按框架分派），失败返回空串。

    · NeoZygisk：读 $ZYGISK_NEO_TMP/module.prop（键值文本）。
    · Zygisk Next：执行 `./bin/zygiskd status`（含 zygote_states 字段）。
      必须以 $MODDIR 为 CWD 执行（zygiskd 内部走相对路径）。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        return runner.su('cat %s' % ZYGISK_NEO_PROP, quiet=True, timeout=15).text
    if kind == ZY_NEXT:
        res = runner.su(
            'cd %(d)s && ./bin/zygiskd status 2>&1' % {'d': ZYGISK_MODULE_DIR},
            quiet=True, timeout=20)
        return res.text
    return ''


def zygisk_zygote_count(runner, kind=None):
    """返回已接管的 zygote 数量，无法解析返回 -1。

    · NeoZygisk：统计 module.prop 中值为 "injected" 的键（如 zygote64）。
    · Zygisk Next：解析 `zygiskd status` 输出里的 `zygote_states: N`。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEO:
        info = zygisk_read_prop(runner)
        return sum(1 for v in info.values() if 'injected' in v.lower())
    if kind == ZY_NEXT:
        text = zygisk_status(runner, ZY_NEXT)
        m = re.search(r'zygote_states\s*:\s*(\d+)', text)
        return int(m.group(1)) if m else -1
    return -1


def start_zygisk_daemon(runner, kind=None):
    """以正确的 CWD 启动 Zygisk 注入服务（重越狱后手动补启动）。

    ⚠️ 关键：NeoZygisk 的 zygisk-ptrace64 内部全部使用相对路径
    （./bin/zygiskd64、./module.prop、./lib64/libzygisk.so），
    因此**必须以模块目录 $MODDIR 为工作目录启动**，否则会因找不到
    ./module.prop 而立刻 exit=1，注入阶段也会因找不到 ./bin/zygiskd64 中断。
    这正是官方 post-fs-data.sh 里 `cd "$MODDIR"` 那一步的作用。

    · NeoZygisk：`cd $MODDIR && ./bin/zygisk-ptrace64 monitor &`
    · Zygisk Next：`cd $MODDIR && ./bin/zygiskd daemon &`（等价于官方
      post-fs-data.sh 最后那一步；daemon 会自行常驻并派生子进程）。

    ⚠️ 两者都**不能直接执行官方脚本**：NeoZygisk 没有前台脚本；Zygisk Next
    的 post-fs-data.sh 末行 `./bin/zygiskd daemon` 会**前台常驻不返回**，
    经 `su -c 'sh ./post-fs-data.sh'` 调用会让整个 su 会话永久挂起。
    因此这里统一改为「后台化 daemon + 短超时放行 + 复查进程」。

    late-load 模式下 ksud 是后注入的，不会自动重放 post-fs-data 事件，
    故重越狱后必须手动补启动。返回 (ok, 说明)。
    """
    kind = kind or detect_zygisk(runner)

    if kind == ZY_NEO:
        if not runner.su('test -x ' + ZYGISK_NEO_BIN, quiet=True, timeout=15).ok:
            return False, '未找到 %s，请确认已安装 NeoZygisk 模块（%s）。' % (
                ZYGISK_NEO_BIN, ZYGISK_MODULE)
        # 先清理可能存在的旧 monitor / 脏 socket，再以正确 CWD 启动，避免重复实例。
        # ⚠️ 清理必须用 `pkill -x zygisk-ptrace64`（按精确进程名匹配），
        #    不能用 `pkill -f zygisk-ptrace64`：后者按完整命令行匹配，会命中
        #    执行本命令的 `su -c '...zygisk-ptrace64...'` 自身（命令行里含该字样），
        #    导致 su 会话被 SIGTERM 自杀（rc=143），后续 cd/nohup 永不执行 → monitor 起不来。
        # ⚠️ 关于返回码：KernelSU 的 `su -c` 会 wait 全部子进程，只要 monitor
        #    是活的，这条命令就**永远不会主动返回**（实测带 `sleep 30 &` 也要等满 30s）。
        #    这是 su 的语义，无法靠 setsid / 子 shell / 重定向规避。因此这里
        #    **不依赖命令返回码**：给一个短超时快速放行，随后用「monitor 是否在跑」
        #    作为真正的成功判据（见下方复检）。
        cmd = (
            'pkill -x zygisk-ptrace64 2>/dev/null; sleep 1; '
            'rm -f %(tmp)s/init_monitor; '
            'cd %(dir)s && export TMP_PATH=%(tmp)s && '
            'nohup ./bin/zygisk-ptrace64 monitor '
            '> %(log)s 2>&1 < /dev/null &'
        ) % {
            'tmp': ZYGISK_NEO_TMP,
            'dir': ZYGISK_MODULE_DIR,
            'log': ZYGISK_MONITOR_LOG,
        }
        # 短超时：等 monitor 完成启动即可，不等命令「返回」（它不会返回）。
        runner.su(cmd, quiet=True, timeout=8)
        time.sleep(2)
        if zygisk_monitor_running(runner, ZY_NEO):
            return True, 'NeoZygisk monitor 已启动。'
        return False, ('monitor 未启动，请确认已安装 NeoZygisk 模块（%s）且具备 Root。'
                       % ZYGISK_MODULE)

    if kind == ZY_NEXT:
        # 定位可执行入口：优先 bin/zygiskd（软链），退回 bin/zygiskd64。
        if not runner.su('test -x %s || test -x %s'
                         % (ZYGISK_NEXT_BIN, ZYGISK_NEXT_BIN64),
                         quiet=True, timeout=15).ok:
            return False, ('未找到 %s 或 %s，请确认已安装 Zygisk Next 模块（%s）。'
                           % (ZYGISK_NEXT_BIN, ZYGISK_NEXT_BIN64, ZYGISK_MODULE))
        # 准备运行时目录 + 归档上一轮的 znctx / modules_info（照搬官方
        # post-fs-data.sh 的前置动作），再后台化启动 daemon。
        cmd = (
            'mkdir -p /data/adb/zygisksu; '
            'cd %(dir)s || exit 1; '
            '[ -f /data/adb/zygisksu/znctx ] && '
            'mv /data/adb/zygisksu/znctx /data/adb/zygisksu/znctx.old; '
            '[ -f /data/adb/zygisksu/modules_info ] && '
            'mv /data/adb/zygisksu/modules_info /data/adb/zygisksu/modules_info.old; '
            'nohup ./bin/zygiskd daemon '
            '> %(log)s 2>&1 < /dev/null &'
        ) % {'dir': ZYGISK_MODULE_DIR, 'log': ZYGISK_MONITOR_LOG}
        # 短超时：只等 daemon 完成拉起，不等命令「返回」（常驻不返回）。
        runner.su(cmd, quiet=True, timeout=10)
        time.sleep(3)
        if zygisk_monitor_running(runner, ZY_NEXT):
            return True, 'Zygisk Next daemon 已启动。'
        return False, ('daemon 未启动，请确认已安装 Zygisk Next 模块（%s）且具备 Root。'
                       % ZYGISK_MODULE)

    return False, ('未检测到 Zygisk 框架（既无 %s，也无 %s/bin/*/zygiskd）。'
                   % (ZYGISK_NEO_BIN, ZYGISK_MODULE_DIR))


def zygote64_pid(runner):
    """返回当前 64 位 zygote 的 PID（字符串），未运行返回空串。

    实机进程名就是 zygote64（另有 32 位 zygote、以及 zygote 派生的
    webview_zygote）。先用 pidof（精确匹配进程名，不会误伤
    webview_zygote），失败再退回 ps 过滤。
    """
    res = runner.su('pidof zygote64', quiet=True, timeout=15)
    pid = res.text.strip().split()
    if pid:
        return pid[0]
    res = runner.shell(
        "ps -A -o PID,NAME | awk '$2==\"zygote64\"{print $1}'",
        quiet=True, timeout=15)
    return res.text.strip().split()[0] if res.text.strip() else ''


def zygote_injected(runner, kind=None):
    """zygote 是否已被 Zygisk 注入（按框架分派，判据不可通用）。

    · NeoZygisk：检查 64 位 zygote 的 /proc/<pid>/maps 是否映射了
      libzygisk.so（NeoZygisk 会把它常驻映射在 zygote 里）。

    · Zygisk Next：**不能用 libzygisk/maps 判据** —— 实测 Zygisk Next 注入
      完成会把自身 loader 从 zygote 的 maps 中 unmap 掉（反检测），该 grep
      恒为 0。必须改用 `./bin/zygiskd status` 输出的 `zygote_states: N`
      （N≥1 表示已有 zygote 被成功注入）。

    返回 True/False；无法判定返回 None。
    """
    kind = kind or detect_zygisk(runner)
    if kind == ZY_NEXT:
        count = zygisk_zygote_count(runner, ZY_NEXT)
        if count < 0:
            return None
        return count > 0
    # NeoZygisk（及未知框架兜底）：查 zygote64 的 maps。
    pid = zygote64_pid(runner)
    if not pid:
        return None
    res = runner.su('grep -c libzygisk /proc/%s/maps' % pid, quiet=True, timeout=15)
    text = res.text.strip()
    return text.isdigit() and int(text) > 0


def restart_zygote(runner, service=None):
    """触发 zygote 重建，让 monitor 捕获新 zygote 并注入。

    NeoZygisk 的 monitor 以 PTRACE_SEIZE 接管**新出现**的 zygote，故需先
    杀掉现有 zygote，由 init 重新拉起后 monitor 才能注入。

    ⚠️ 不能用 kill/pkill 的返回码判断成败：pkill 在「没有匹配到进程」时
    返回 1，而 zygote 被 -9 杀掉后 init 会立刻重建、新旧 PID 交替，
    返回码无法反映真实结果。因此这里改用「zygote64 PID 是否变化」
    作为判据：杀掉前记录 PID，重建后 PID 必然不同。

    实机 64 位 zygote 名即 zygote64，32 位为 zygote；两者都要杀才能
    触发完整重建（只杀 64 位时 system_server 可能仍挂旧进程）。
    service 参数保留以兼容旧调用，忽略之。
    """
    before = zygote64_pid(runner)
    # ⚠️ 不能用 `pkill -f zygote64`：本命令命令行里含 "zygote64" 字样，
    #    pkill -f（按完整命令行匹配）会命中执行它的 `su -c '...zygote64...'`
    #    自身，把 su 会话一起杀掉（虽然侥幸仍能杀掉 zygote，但行为脆弱）。
    # ⚠️ 也不能用 `pkill -x zygote64`：实机 zygote64 的进程名(comm)是 "main"，
    #    精确名匹配不到，而 `-x main` 会误杀大量同名进程。
    # ✅ 正确做法：按 PID 精确 kill —— 先用 pidof 取到真实 PID 再 kill。
    pids = []
    p64 = zygote64_pid(runner)
    if p64:
        pids.append(p64)
    res32 = runner.su('pidof zygote', quiet=True, timeout=15)
    if res32.text.strip():
        pids.extend(res32.text.strip().split())
    if pids:
        runner.su('kill -9 ' + ' '.join(pids), quiet=True, timeout=30)

    # 轮询等待新 zygote 出现且 PID 与旧值不同（init 重建通常在数秒内）。
    for _ in range(30):
        time.sleep(1)
        now = zygote64_pid(runner)
        if now and now != before:
            return True
    return False
