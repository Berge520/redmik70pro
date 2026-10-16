#!/system/bin/sh
# Vector（原 LSPosed 复刻）Xposed 模块**生效**验证脚本
#   · 只读，不修改任何配置 / 不重启进程
#   · 用于回答一个问题：装上的 Xposed 模块到底有没有真正 hook 到目标进程？
#
# 背景（★ 判据选择依据，均为真机实测）：
#   Vector / LSPosed 自身 CLI 的 `isFdAttached` 字段**不可用**——
#   实机模块明明在工作，该字段却恒为 false（它只反映 CLI 短命进程自身的 fd 视角）。
#   故本脚本改用三层证据链，逐层加强：
#     L1 框架活着     : vectord 守护进程存在
#     L2 模块被启用   : cli modules ls 列出（注册级，不代表已加载）
#     L3 模块真 hook  : cli log cat 中出现该模块自己的 hook 记录（★ 唯一可靠判据）
#
# 实机环境：Redmi K70 Pro（manet）/ KernelSU 临时 Root（late-load）
#   Vector v2.2 (3112, JingMatrix)，模块 ID zygisk_vector
#   CLI 实际位置 /data/adb/modules/zygisk_vector/cli（主类 org.matrix.vector.daemon.Cli）
#   真实子命令：status / modules(ls,enable,disable) / scope(ls,add,rm,set) / config / db / log(cat,clear,tail)
#
# 用法：
#   adb push code/tools/verify_vector.sh /data/local/tmp/
#   adb shell su -c "sh /data/local/tmp/verify_vector.sh"            # 全量三层验证
#   adb shell su -c "sh /data/local/tmp/verify_vector.sh <包名>"      # 追加：查该模块作用域

PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR=/data/adb/modules/zygisk_vector
CLI="$MODDIR/cli"
LOG_DIR=/data/adb/lspd/log

echo "############ Vector 模块生效验证 ############"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ─────────────────────────────────────────────
echo "===== [L1] 框架是否活着 ====="
# vectord 是 Vector 的守护进程。没有它 → 框架根本没起来，后两层无意义。
VD_PID=$(pgrep -f vectord 2>/dev/null | head -1)
if [ -n "$VD_PID" ]; then
    echo "  vectord PID=$VD_PID ✓"
    # 顺带确认注入到 system_server（Vector 在 system_server 里挂 FrameworkService）
    SS=$(pidof system_server)
    echo "  system_server PID=${SS:-（无）}"
else
    echo "  ✗ 未发现 vectord 进程 —— 框架未运行"
    echo "    → 请先修复 Zygisk 注入（fix_zygisk.sh）后重启 zygote"
fi
echo ""

# ─────────────────────────────────────────────
echo "===== [L2] CLI 是否可用 & 框架状态 ====="
if [ ! -x "$CLI" ]; then
    echo "  ✗ CLI 不可执行: $CLI"
    echo "    （备选路径 /data/adb/vector/bin/cli 本机不存在）"
    echo "DONE"; exit 1
fi
# status：框架版本 / 启用模块数。注意 isFdAttached 恒 false，不采纳。
# ★ 不去空格：JSON 的 key 本身含空格（"Framework Version"），tr -d ' ' 会破坏匹配。
"$CLI" --json status 2>/dev/null \
    | grep -E 'Framework Version|Version Code|API Version|Enabled Modules|isFdAttached'
echo "  注：isFdAttached 字段不可信（实测模块在工作时仍为 false），已忽略"
echo ""

# ─────────────────────────────────────────────
echo "===== [L3] 已启用模块清单（注册级）====="
# 真实子命令是 `modules ls`（不是 list）。
"$CLI" modules ls 2>/dev/null
echo ""

# ─────────────────────────────────────────────
echo "===== [L4] 模块 Hook 实证（★ 唯一可靠判据）====="
# cli log cat = dump 框架日志缓冲。格式：
#   [ 时间 PID:UID:TID I/VectorLegacyBridge ] [模块Tag] process=xxx
# 其中 [模块Tag] 是模块自己在 hook 代码里打的日志，出现即证明该模块已在目标进程执行。
echo "  --- 框架日志中的模块 hook 记录 ---"
"$CLI" log cat 2>/dev/null > /data/local/tmp/_vlog.txt
LINES=$(wc -l < /data/local/tmp/_vlog.txt)
if [ "${LINES:-0}" -le 1 ]; then
    echo "  （日志为空。日志缓冲会随重启清空，建议在『打开被 hook 的 App』后再跑本脚本）"
else
    # 提取所有 [模块Tag]，统计出现次数
    grep -aoE '\[[A-Za-z0-9_.]+\]' /data/local/tmp/_vlog.txt 2>/dev/null \
        | sort | uniq -c | sort -rn
    echo ""
    echo "  --- 最近 8 条 hook 记录 ---"
    grep -aE '^\[' /data/local/tmp/_vlog.txt 2>/dev/null | tail -8
fi
rm -f /data/local/tmp/_vlog.txt
# ★ 重要局限（实机核实）：本日志只记录**模块主动打出的 log**。
#   静默工作的模块（如 HyperCeiler）不会留痕，故 L4 为空 ≠ 该模块未生效。
#   判定静默模块是否生效，请看 L5 作用域（有作用域=框架会向其注入）或直接功能实测。
echo "  ⚠️ 局限：此处仅能看见『主动打 log』的模块；静默模块无记录属正常。"
echo ""

# ─────────────────────────────────────────────
# 逐模块汇总：已启用模块 → 各自作用域条目数（静默模块的间接证据）
echo "===== [L4b] 各启用模块的作用域规模（判断框架是否会向 App 注入）====="
"$CLI" modules ls 2>/dev/null | awk 'NR>2 && NF>=3 {print $1}' | while read pkg; do
    [ -z "$pkg" ] && continue
    n=$("$CLI" scope ls "$pkg" 2>/dev/null | awk 'NR>2 && NF>=1' | wc -l)
    printf "  %-32s 作用域条目=%s\n" "$pkg" "$n"
done
echo ""

# ─────────────────────────────────────────────
# 可选：指定包名 → 追加查询它的注入作用域
if [ -n "$1" ]; then
    echo "===== [L5] 模块作用域: $1 ====="
    "$CLI" scope ls "$1" 2>/dev/null | head -40
    echo "  （作用域 = 该模块会注入哪些 App。列表为空则它不会 hook 任何进程）"
    echo ""
fi

echo "############ 验证完成 ############"
echo "判读："
echo "  L1 有 vectord + L2 有模块数        → 框架正常运行 ✓"
echo "  L4 出现 [模块Tag] hook 记录        → 有模块确实在 hook（★ 最强证据）"
echo "    注意：Tag 由模块自命名，与包名不同域，无法逐行对应到某个模块"
echo "  L4b 作用域条目>0                   → 该模块已配置注入范围（静默模块的间接证据）"
echo "  L4b 作用域条目=0                   → 该模块不会注入任何 App，需在管理器里配作用域"
echo "  最终黄金标准：打开依赖该模块的 App 实测功能是否生效（文档 maintenance.md）"
echo "DONE"
