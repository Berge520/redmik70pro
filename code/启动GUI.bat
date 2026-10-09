@echo off
setlocal
chcp 936 >nul 2>&1
title RootTool GUI

cd /d "%~dp0"

echo.
echo   ============================================
echo     小米 / 红米 临时 Root 专业工具 - 图形界面
echo   ============================================
echo   正在启动，请稍候...
echo.

rem 优先使用 pythonw，无控制台窗口
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "gui\roottool.pyw"
    exit /b 0
)

rem 次选 python
where python >nul 2>&1
if %errorlevel% equ 0 (
    start "" python "gui\roottool.pyw"
    exit /b 0
)

rem 均未找到时给出明确提示
echo.
echo   [错误] 未找到 Python。
echo.
echo   请先安装 Python 3.8 或以上版本，安装时务必勾选：
echo       Add Python to PATH
echo.
echo   下载地址：https://www.python.org/downloads/
echo.
pause
exit /b 1
