@echo off
rem ============================================================
rem  Build minimal APK by hand (no Gradle).
rem  Requires: JDK 11+ and Android SDK (aapt2 / d8 / apksigner).
rem  Default SDK: D:\Android\Sdk  -  override: build.cmd D:\path\to\Sdk
rem ============================================================
setlocal EnableDelayedExpansion

if "%~1"=="" (set SDK=D:\Android\Sdk) else (set SDK=%~1)
set BT=%SDK%\build-tools\36.0.0
set PLATFORM=%SDK%\platforms\android-37.0\android.jar
set PROJ=%~dp0
set SRC=%PROJ%src\main
set OUT=%PROJ%build
set DIST=%PROJ%dist

set PKG=com.redmik70pro.zygiskfix
set APK=%DIST%\ZygiskFix.apk
set ALIGNED=%OUT%\aligned.apk

if not exist "%PLATFORM%" goto :no_platform
if not exist "%BT%\aapt2.exe" goto :no_bt

if exist "%OUT%" rmdir /s /q "%OUT%"
if not exist "%DIST%" mkdir "%DIST%"
mkdir "%OUT%\res" 2>nul
mkdir "%OUT%\gen" 2>nul
mkdir "%OUT%\classes" 2>nul
mkdir "%OUT%\dex" 2>nul

echo [1/6] aapt2 compile resources...
"%BT%\aapt2.exe" compile --dir "%SRC%\res" -o "%OUT%\res.zip"
if errorlevel 1 goto :fail

echo [2/6] aapt2 link...
"%BT%\aapt2.exe" link -o "%OUT%\base.apk" -I "%PLATFORM%" ^
  --manifest "%SRC%\AndroidManifest.xml" ^
  -A "%SRC%\assets" ^
  --java "%OUT%\gen" ^
  "%OUT%\res.zip"
if errorlevel 1 goto :fail

echo [3/6] javac...
rem Accumulate the source list with delayed expansion (call set would eat %F).
set FILES=
for /f "delims=" %%F in ('dir /b /s "%OUT%\gen\*.java"') do set FILES=!FILES! "%%F"
for /f "delims=" %%F in ('dir /b /s "%SRC%\java\*.java"') do set FILES=!FILES! "%%F"
javac -encoding UTF-8 -source 8 -target 8 -bootclasspath "%PLATFORM%" ^
  -d "%OUT%\classes" !FILES! > "%OUT%\javac.log" 2>&1
if errorlevel 1 goto :javac_fail

echo [4/6] d8...
rem Call d8.jar via java directly: d8.bat mis-parses multi-file arguments here.
set D8JAR=%BT%\lib\d8.jar
if not exist "!D8JAR!" goto :no_d8jar
set CLASSES=
for /f "delims=" %%F in ('dir /b /s "%OUT%\classes\*.class"') do set CLASSES=!CLASSES! "%%F"
java -cp "!D8JAR!" com.android.tools.r8.D8 --min-api 26 --lib "%PLATFORM%" ^
  --output "%OUT%\dex" !CLASSES!
if errorlevel 1 goto :fail
if not exist "%OUT%\dex\classes.dex" goto :no_dex

echo [5/6] add classes.dex into apk...
pushd "%OUT%\dex"
"%BT%\aapt.exe" add "%OUT%\base.apk" classes.dex
if errorlevel 1 (popd & goto :fail)
popd

echo [6/6] zipalign + sign...
"%BT%\zipalign.exe" -f -p 4 "%OUT%\base.apk" "%ALIGNED%"
if errorlevel 1 goto :fail

set KS=%PROJ%debug.keystore
if not exist "%KS%" (
  echo    generating debug keystore...
  keytool -genkeypair -keystore "%KS%" -storepass android -keypass android ^
    -alias debugkey -keyalg RSA -keysize 2048 -validity 10950 ^
    -dname "CN=RedmiK70Pro,OU=mod,O=mod,L=CN,S=CN,C=CN" >nul 2>&1
  if not exist "%KS%" goto :fail
)

"%BT%\apksigner.bat" sign --ks "%KS%" --ks-pass pass:android --key-pass pass:android ^
  --out "%APK%" "%ALIGNED%"
if errorlevel 1 goto :fail
"%BT%\apksigner.bat" verify "%APK%"
if errorlevel 1 goto :fail

echo.
echo ============================================
echo  BUILD OK: %APK%
for %%F in ("%APK%") do echo  size: %%~zF bytes
echo ============================================
echo install: adb install -r "%APK%"
exit /b 0

:no_platform
echo [ERROR] android.jar not found: %PLATFORM%
echo         pass SDK path as first argument: build.cmd D:\Android\Sdk
exit /b 1
:no_bt
echo [ERROR] aapt2.exe not found under %BT%
exit /b 1
:no_r
echo [ERROR] R.java not generated
exit /b 1
:no_dex
echo [ERROR] classes.dex not generated
exit /b 1
:no_d8jar
echo [ERROR] d8.jar not found: %BT%\lib\d8.jar
exit /b 1
:javac_fail
echo [ERROR] javac failed:
type "%OUT%\javac.log"
exit /b 1
:fail
echo.
echo [FAILED] build aborted, see messages above.
exit /b 1
