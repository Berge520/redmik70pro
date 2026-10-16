# -*- coding: utf-8 -*-
"""Xposed 框架（Vector / LSPosed / 原版）检测与模块作用域操作。

从 core.py 拆出的独立后端模块：只依赖标准库与 Runner 协议（runner.su /
runner.shell），不依赖 tkinter，也不反向 import core。
core.py 通过 `from xposed_core import *` 转发，故外部仍以 core.xxx 访问。
"""

import re


# ---------------------------------------------------------------
#  Xposed 框架检测
# ---------------------------------------------------------------
XP_NONE = 'none'
XP_VECTOR = 'vector'
XP_LSPOSED = 'lsposed'
XP_ORIGINAL = 'original'
XP_ORIGINAL_INSTALLED = 'original_installed'

XP_CLI = {
    XP_VECTOR: '/data/adb/vector/bin/cli',
    XP_LSPOSED: '/data/adb/lspd/bin/cli',
}

# Vector 的 CLI 可能出现在两个位置，探测时按序尝试。
VECTOR_MODULE_DIR = '/data/adb/modules/zygisk_vector'
XP_VECTOR_CLI_PATHS = (
    VECTOR_MODULE_DIR + '/cli',
    XP_CLI[XP_VECTOR],
)


# Xposed 模块标识：包名（含点）或模块目录名，允许字母/数字/下划线/连字符/点，
# 但不能以点开头或结尾，且不含连续的 ".."（避免路径穿越）。
# 该值会被拼入 root 命令，故必须严格白名单，杜绝 shell 元字符注入。
_XP_ID_RE = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$')


def valid_xposed_id(name):
    """校验 Xposed 模块标识（包名/模块目录名）是否合法。

    该值会被拼入 root 命令，必须严格白名单以免命令注入。
    """
    if not name:
        return False
    return bool(_XP_ID_RE.match(name))


def detect_xposed(runner):
    """返回 (type, cli_path)。type 为 XP_* 常量之一。

    · Vector：CLI 有两个位置 —— 模块目录内 `zygisk_vector/cli`，以及
      /data/adb/vector/bin/cli（安装脚本软链/副本）。两者都探测。
    · LSPosed：CLI 固定在 /data/adb/lspd/bin/cli（主类 org.lsposed.lspd.cli.Main）。
    """
    for path in (XP_VECTOR_CLI_PATHS):
        if runner.su('test -x ' + path, quiet=True, timeout=15).ok:
            return XP_VECTOR, path
    if runner.su('test -x ' + XP_CLI[XP_LSPOSED], quiet=True, timeout=15).ok:
        return XP_LSPOSED, XP_CLI[XP_LSPOSED]

    conf = '/data/data/de.robv.android.xposed.installer/conf/modules.list'
    if runner.su('test -f ' + conf, quiet=True, timeout=15).ok:
        return XP_ORIGINAL, ''

    res = runner.shell('pm list packages', quiet=True, timeout=20)
    if 'de.robv.android.xposed.installer' in res.text:
        return XP_ORIGINAL_INSTALLED, ''

    return XP_NONE, ''


def xposed_fd_attached(runner, cli):
    """查询 Vector / LSPosed 的 isFdAttached 状态：True/False/None。

    ⚠️ 该字段反映的是 CLI 这个短命进程**自身**的 fd 视角，实测在
    system_server 已注入时仍可能报 false，**不可作为激活判据**，
    仅作参考输出。真正的判据是 zygote 是否映射 libzygisk.so。
    cli 为空（未安装/无 CLI）时返回 None。
    """
    if not cli:
        return None
    res = runner.su('sh %s --json status' % cli, quiet=True, timeout=20)
    if not res.ok:
        return None
    m = re.search(r'"isFdAttached"\s*:\s*(true|false)', res.text, re.I)
    if m:
        return m.group(1).lower() == 'true'
    return None


# Vector / LSPosed 的框架日志目录（cli log cat 读取的就是这里的 modules_*.log）。
XP_LOG_DIR = '/data/adb/lspd/log'


def xposed_module_list(runner, cli):
    """列出 Vector / LSPosed 已注册模块：返回 [(包名, 状态), ...]。

    ★ CLI 的正确子命令是 `modules ls`，**不是 `modules list`**
      （实机验证：`modules list` 报 `Unmatched argument at index 1: 'list'` 且不返回数据）。
    cli 为空或命令失败时返回 []。
    """
    if not cli:
        return []
    res = runner.su('sh %s modules ls' % cli, quiet=True, timeout=25)
    rows = []
    for line in res.lines:
        line = line.strip()
        if not line or line.lower().startswith(('package', '---')):
            continue
        parts = line.split()
        token = parts[0]
        if not valid_xposed_id(token):
            continue
        # 实机列格式：PACKAGE  UID  STATUS（如 `com.x  10688  enabled`）。
        # 只取末列 STATUS 作显示，避免把中间 UID 一并带入。
        status = parts[-1] if len(parts) >= 2 else 'enabled'
        rows.append((token, status))
    return rows


def xposed_hook_evidence(runner, cli):
    """从框架日志中提取「模块 hook 实证」：返回 [(模块Tag, 次数), ...]（按次数降序）。

    原理：`cli log cat` dump 模块日志，形如
        [ 时间 PID:UID:TID I/VectorLegacyBridge ] [模块Tag] process=xxx
    其中 `[模块Tag]` 是模块在 hook 代码里主动打出的，出现即证明该模块已在目标进程执行。

    ⚠️ 重要局限（实机核实）：日志只记录**模块主动打 log** 的行为。
       静默工作的模块（如 HyperCeiler）不会留痕，故结果为空 ≠ 该模块未生效。
       判定静默模块请看 xposed_module_scope() 或直接功能实测。
    """
    if not cli:
        return []
    res = runner.su('sh %s log cat' % cli, quiet=True, timeout=25)
    counts = {}
    for line in res.lines:
        # 只取行尾那组 [Tag]（模块自己的标签），避开 I/VectorLegacyBridge 这类框架标签。
        tags = re.findall(r'\]\s*\[([A-Za-z0-9_.]+)\]', line)
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def xposed_module_scope(runner, cli, module_id):
    """查询某模块的注入作用域条目数（= 它会注入多少个 App）。失败返回 -1。

    作用域是「框架会不会向 App 注入该模块」的依据：条目>0 表示已配置注入范围；
    条目=0 表示该模块不会 hook 任何 App。这是静默模块（无 log）生效的间接证据。
    """
    if not cli or not valid_xposed_id(module_id):
        return -1
    res = runner.su('sh %s scope ls %s' % (cli, module_id), quiet=True, timeout=25)
    if not res.ok:
        return -1
    n = 0
    for line in res.lines:
        line = line.strip()
        if not line or line.upper().startswith(('APP_PACKAGE', '---')):
            continue
        n += 1
    return n


# 作用域作用目标的合法性校验：scope 的 add/rm 参数格式是 `pkg/user_id`。
# 该串会被拼入 root 命令，必须严格白名单，杜绝 shell 元字符注入。
#   · 包名段：与 xposed 模块标识同规则（字母/数字/下划线/连字符/点）。
#   · /user_id：可选，非负整数（如 0 表示机主）。两者都用 ^...$ 全匹配。
_SCOPE_TARGET_RE = re.compile(r'^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*/[0-9]+$')


def valid_scope_target(text):
    """校验作用域条目 `pkg/user_id` 是否合法（可安全拼入 root 命令）。"""
    if not text:
        return False
    return bool(_SCOPE_TARGET_RE.match(text))


def xposed_scope_list(runner, cli, module_id):
    """列出某模块注入作用域内的全部 App。

    返回 [(包名, user_id), ...]；查询失败返回 None（区别于"查询成功但为空"的 []）。
    优先解析 `scope ls --json`（结构化、不受表头/列宽变化影响），
    解析不出时退回按文本行解析 `scope ls`（格式：`APP_PACKAGE  USER_ID`）。
    仅在 Vector/LSPosed 且已安装 CLI 时可用。
    """
    if not cli or not valid_xposed_id(module_id):
        return None
    res = runner.su('sh %s scope ls --json %s' % (cli, module_id),
                    quiet=True, timeout=25)
    if not res.ok:
        return None
    text = res.text
    # JSON 模式：逐条抓 "APP_PACKAGE": "xxx" / "USER_ID": n。
    # 为避免引入 json 依赖与格式细节耦合，这里用正则按对象顺序配对。
    pairs = re.findall(
        r'"APP_PACKAGE"\s*:\s*"([^"]+)"\s*,\s*"USER_ID"\s*:\s*(\d+)', text)
    if pairs:
        return [(pkg, int(uid)) for pkg, uid in pairs]
    # JSON 解析成功但确实为空：确认到 success/data 结构即可判定为空列表。
    if '"data"' in text and '"success"' in text:
        return []
    # 兜底：文本表格解析（跳过表头与分隔线，按空白切出两列）。
    rows = []
    for line in res.lines:
        line = line.strip()
        if not line or line.upper().startswith(('APP_PACKAGE', '---')):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            rows.append((parts[0], int(parts[1])))
    if rows:
        return rows
    return [] if res.ok else None


def xposed_scope_add(runner, cli, module_id, target):
    """把单个 App（`pkg/user_id`）加入某模块的注入作用域。返回 (ok, 输出文本)。"""
    if not cli or not valid_xposed_id(module_id) or not valid_scope_target(target):
        return False, '参数不合法，已拒绝执行。'
    res = runner.su('sh %s scope add %s %s' % (cli, module_id, target),
                    quiet=True, timeout=25)
    return res.ok, res.text


def xposed_scope_remove(runner, cli, module_id, target):
    """把单个 App（`pkg/user_id`）从某模块的注入作用域移除。返回 (ok, 输出文本）。"""
    if not cli or not valid_xposed_id(module_id) or not valid_scope_target(target):
        return False, '参数不合法，已拒绝执行。'
    res = runner.su('sh %s scope rm %s %s' % (cli, module_id, target),
                    quiet=True, timeout=25)
    return res.ok, res.text


def xposed_vectord_running(runner):
    """Vector 守护进程 vectord 是否在运行（框架活着的最粗判据）。"""
    return runner.su('pgrep -f vectord', quiet=True, timeout=15).ok
