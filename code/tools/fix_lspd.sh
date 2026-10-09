#!/system/bin/sh
# v8: 直接调用zygiskd重新注入 + lspd + 正确的zygote重启
PATH=/system/bin:/vendor/bin:/data/adb/ksu/bin:$PATH
export PATH

MODDIR="/data/adb/modules/zygisk_lsposed"
LOGDIR="/data/adb/lspd/log"
ZYGISKDIR="/data/adb/modules/zygisksu"

echo "[1] 杀掉旧lspd..."
for PID in $(ps -A -o PID,NAME 2>/dev/null | grep 'lspd' | awk '{print $1}'); do
    kill -9 "$PID" 2>/dev/null
    echo "  killed $PID"
done
sleep 1

echo "[2] 获取zygote环境变量..."
ZPID=$(ps -A -o PID,NAME 2>/dev/null | grep 'zygote64' | awk '{print $1}' | head -1)
if [ -z "$ZPID" ]; then
    echo "ERROR: 找不到zygote64"; exit 1
fi
BOOTCP=$(cat /proc/$ZPID/environ 2>/dev/null | tr '\0' '\n' | grep '^BOOTCLASSPATH=' | head -1)
DEX2OAT=$(cat /proc/$ZPID/environ 2>/dev/null | tr '\0' '\n' | grep '^DEX2OATBOOTCLASSPATH=' | head -1)
if [ -z "$BOOTCP" ]; then
    echo "ERROR: 无法获取BOOTCLASSPATH"; exit 1
fi
echo "  BOOTCLASSPATH (${#BOOTCP} chars)"

echo "[3] 重新注入ZygiskSU..."
echo "  当前zygote64 PID=$ZPID"

# 直接运行zygiskd daemon (从zygisksu模块目录)
cd "$ZYGISKDIR" || { echo "ERROR: 无法进入ZygiskSU目录"; exit 1; }
echo "  运行 zygiskd daemon..."
./bin/zygiskd daemon 2>&1 &
ZYGISKD_PID=$!
sleep 3

echo "  zygiskd 进程:"
ps -A -o PID,NAME 2>/dev/null | grep -i 'zygisk'
echo "  native_bridge: $(getprop ro.dalvik.vm.native.bridge 2>/dev/null)"

echo "[4] 运行 zygiskd service-stage..."
./bin/zygiskd service-stage 2>&1 &
sleep 2

echo "[5] 清理旧状态..."
rm -f /data/adb/lspd/monitor 2>/dev/null
rm -f /data/adb/lspd/lock 2>/dev/null

echo "[6] 记录旧system_server..."
OLD_SS=$(ps -A -o PID,NAME 2>/dev/null | grep 'system_server' | awk '{print $1}' | head -1)
echo "  旧SS PID=${OLD_SS:-(无)}"

echo "[7] setsid启动lspd..."
java_options="-Djava.class.path=$MODDIR/daemon.apk -Xnoimage-dex2oat"
setsid nsenter -t 1 -m -- /system/bin/sh -c "
    cd $MODDIR
    export $BOOTCP
    export $DEX2OAT
    export PATH=$PATH
    exec /system/bin/app_process $java_options /system/bin --nice-name=lspd org.lsposed.lspd.Main
" </dev/null >/dev/null 2>&1 &
sleep 3

LSPD_PID=$(ps -A -o PID,NAME 2>/dev/null | grep 'lspd' | awk '{print $1}' | head -1)
if [ -z "$LSPD_PID" ]; then
    echo "ERROR: lspd未启动!"; exit 1
fi
echo "  lspd PID=$LSPD_PID"

echo "[8] 等lspd初始化 (5s)..."
sleep 5
LSPD_PID=$(ps -A -o PID,NAME 2>/dev/null | grep 'lspd' | awk '{print $1}' | head -1)
if [ -z "$LSPD_PID" ]; then
    echo "ERROR: lspd崩溃!"; exit 1
fi
echo "  lspd 存活"

echo "=== 杀zygote64 ==="
ZPID=$(ps -A -o PID,NAME 2>/dev/null | grep 'zygote64' | awk '{print $1}' | head -1)
echo "[9] 杀 zygote64 PID=$ZPID"
kill -9 "$ZPID"

echo "[10] 等旧SS死亡..."
if [ -n "$OLD_SS" ]; then
    for i in $(seq 1 15); do
        sleep 1
        if ! kill -0 "$OLD_SS" 2>/dev/null; then
            echo "  旧SS已死 (${i}s)"
            break
        fi
    done
fi

echo "[11] 等新system_server (PID != $OLD_SS)..."
SSPID=""
for i in $(seq 1 30); do
    sleep 1
    NEW_SS=$(ps -A -o PID,NAME 2>/dev/null | grep 'system_server' | awk '{print $1}' | head -1)
    if [ -n "$NEW_SS" ] && [ "$NEW_SS" != "$OLD_SS" ]; then
        SSPID="$NEW_SS"
        echo "  新SS PID=$SSPID (${i}s)"
        break
    fi
done
if [ -z "$SSPID" ]; then
    echo "ERROR: 新system_server未启动"; exit 1
fi

echo "[12] 检查ZygiskSU是否注入新zygote..."
NEW_ZPID=$(ps -A -o PID,NAME 2>/dev/null | grep 'zygote64' | awk '{print $1}' | head -1)
echo "  新zygote64 PID=$NEW_ZPID"
echo "  zygiskd进程: $(ps -A -o PID,NAME | grep -i zygisk)"
echo "  native_bridge: $(getprop ro.dalvik.vm.native.bridge)"

echo "[13] 等bridge建立 (最多60s)..."
BRIDGE_OK=""
for i in $(seq 1 60); do
    sleep 1
    LATEST=$(ls -t $LOGDIR/verbose_*.log 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        BRIDGE_OK=$(grep "binder received" "$LATEST" 2>/dev/null | grep "$SSPID" | tail -1)
        if [ -n "$BRIDGE_OK" ]; then
            echo "  bridge建立! (${i}s)"
            echo "  $BRIDGE_OK"
            break
        fi
    fi
    if [ $((i % 10)) -eq 0 ]; then
        LSPD_PID=$(ps -A -o PID,NAME 2>/dev/null | grep 'lspd' | awk '{print $1}' | head -1)
        echo "  等待中 (${i}s) lspd=${LSPD_PID:-DEAD}"
    fi
done

if [ -z "$BRIDGE_OK" ]; then
    echo "WARNING: bridge未建立"
    echo "  可能ZygiskSU未成功注入新zygote"
    echo "--- 最后15行日志 ---"
    LATEST=$(ls -t $LOGDIR/verbose_*.log 2>/dev/null | head -1)
    [ -n "$LATEST" ] && tail -15 "$LATEST"
    
    echo ""
    echo "--- 尝试方案B: 杀system_server让zygote重新fork ---"
    echo "  杀 system_server PID=$SSPID"
    kill -9 "$SSPID"
    sleep 3
    
    SSPID2=""
    for i in $(seq 1 20); do
        sleep 1
        SSPID2=$(ps -A -o PID,NAME 2>/dev/null | grep 'system_server' | awk '{print $1}' | head -1)
        if [ -n "$SSPID2" ] && [ "$SSPID2" != "$SSPID" ]; then
            echo "  新SS PID=$SSPID2 (${i}s)"
            break
        fi
    done
    
    if [ -n "$SSPID2" ]; then
        echo "  等bridge (30s)..."
        for i in $(seq 1 30); do
            sleep 1
            LATEST=$(ls -t $LOGDIR/verbose_*.log 2>/dev/null | head -1)
            if [ -n "$LATEST" ]; then
                BRIDGE_OK=$(grep "binder received" "$LATEST" 2>/dev/null | grep "$SSPID2" | tail -1)
                if [ -n "$BRIDGE_OK" ]; then
                    echo "  方案B bridge建立! (${i}s)"
                    echo "  $BRIDGE_OK"
                    SSPID="$SSPID2"
                    break
                fi
            fi
        done
    fi
fi

echo "[14] 等稳定 (15s)..."
sleep 15

echo "[15] 修复权限..."
chmod 644 /data/adb/lspd/monitor 2>/dev/null

echo "[16] 最终状态..."
LSPD_PID=$(ps -A -o PID,NAME 2>/dev/null | grep 'lspd' | awk '{print $1}' | head -1)
echo "  lspd: ${LSPD_PID:-DEAD}"
echo "  zygote64: $(ps -A -o PID,NAME | grep zygote64)"
echo "  system_server: $(ps -A -o PID,NAME | grep system_server)"
MONITOR=$(cat /data/adb/lspd/monitor 2>/dev/null)
echo "  monitor: ${MONITOR:-(空)}"
echo "  service: $(service check "$MONITOR" 2>/dev/null)"

echo "[17] 日志..."
LATEST=$(ls -t $LOGDIR/verbose_*.log 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    grep -E 'binder received|sent service|no response|HandleSystemServer|Loaded|hook|version|error.*init|native_bridge' "$LATEST" 2>/dev/null | tail -15
fi

echo ""
if [ -n "$BRIDGE_OK" ] && [ -n "$LSPD_PID" ]; then
    echo "=== ✓ 修复成功 ==="
else
    echo "=== ✗ 修复失败 ==="
fi
echo "DONE"
