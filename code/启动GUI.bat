@echo off
chcp 936 >nul 2>&1
title RootTool 图形界面启动器

cd /d "%~dp0"

echo 正在启动 RootTool 图形界面...
echo.

rem 优先使用 pythonw（无控制台窗口）
where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw "gui\roottool.pyw"
    exit /b 0
)

rem 退而求其次，使用 python
where python >nul 2>&1
if %errorlevel% equ 0 (
    start "" python "gui\roottool.pyw"
    exit /b 0
)

rem 都找不到时给出明确提示
echo [错误] 未找到 Python。
echo.
echo 请先安装 Python 3.8 或以上版本，安装时务必勾选：
echo    Add Python to PATH
echo.
echo 下载地址：https://www.python.org/downloads/
echo.
pause
exit /b 1
