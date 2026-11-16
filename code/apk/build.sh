#!/usr/bin/env bash
# ============================================================
#  手工构建极简 APK（不依赖 Gradle）—— Linux / macOS 版
#  与 build.cmd 等价，供 GitHub Actions 的 ubuntu runner 使用。
#  用法：./build.sh [ANDROID_SDK_ROOT]
# ============================================================
set -euo pipefail

SDK="${1:-${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Android/Sdk}}}"
BT="$SDK/build-tools/36.0.0"
PLATFORM="$SDK/platforms/android-37.0/android.jar"
PROJ="$(cd "$(dirname "$0")" && pwd)"
SRC="$PROJ/src/main"
OUT="$PROJ/build"
DIST="$PROJ/dist"

PKG=com.redmik70pro.zygiskfix
APK="$DIST/ZygiskFix.apk"
ALIGNED="$OUT/aligned.apk"

[ -f "$PLATFORM" ] || { echo "[ERROR] android.jar not found: $PLATFORM"; exit 1; }
[ -x "$BT/aapt2" ] || { echo "[ERROR] aapt2 not found under $BT"; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex" "$DIST"

echo "[1/6] aapt2 compile resources..."
"$BT/aapt2" compile --dir "$SRC/res" -o "$OUT/res.zip"

echo "[2/6] aapt2 link..."
"$BT/aapt2" link -o "$OUT/base.apk" -I "$PLATFORM" \
  --manifest "$SRC/AndroidManifest.xml" \
  -A "$SRC/assets" \
  --java "$OUT/gen" \
  "$OUT/res.zip"

echo "[3/6] javac..."
# 用 mapfile 收集源文件，避免路径含空格时被拆分
mapfile -t SOURCES < <(find "$OUT/gen" "$SRC/java" -name '*.java')
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "$PLATFORM" \
  -d "$OUT/classes" "${SOURCES[@]}"

echo "[4/6] d8..."
mapfile -t CLASSES < <(find "$OUT/classes" -name '*.class')
# 直接调 d8.jar：部分发行版的 d8 包装脚本对多文件参数处理不一致
java -cp "$BT/lib/d8.jar" com.android.tools.r8.D8 \
  --min-api 26 --lib "$PLATFORM" --output "$OUT/dex" "${CLASSES[@]}"

echo "[5/6] add classes.dex into apk..."
( cd "$OUT/dex" && "$BT/aapt" add "$OUT/base.apk" classes.dex )

echo "[6/6] zipalign + sign..."
"$BT/zipalign" -f -p 4 "$OUT/base.apk" "$ALIGNED"

KS="$PROJ/debug.keystore"
if [ ! -f "$KS" ]; then
  echo "   generating debug keystore..."
  keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
    -alias debugkey -keyalg RSA -keysize 2048 -validity 10950 \
    -dname "CN=RedmiK70Pro,OU=mod,O=mod,L=CN,S=CN,C=CN" >/dev/null 2>&1
fi

"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
  --out "$APK" "$ALIGNED"
"$BT/apksigner" verify "$APK"

echo
echo "============================================"
echo " BUILD OK: $APK"
echo " size: $(wc -c < "$APK") bytes"
echo "============================================"
