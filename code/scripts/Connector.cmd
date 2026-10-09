@echo off
@chcp 65001
@echo.
@echo.
echo 注意：无线调试功能仅Android 11及以上系统支持！需输入IP、端口、配对码 
@echo.
set /p a=IP:
@echo.
set /p b=端口号:
@echo.
set /p c=配对码:
echo 授权中... 请留意手机端调试提示，若询问请勾选永久允许。
for /f "delims=" %%i in ('adb pair %a%:%b% %c%') do set res=%%i
set str=Successfully
set strs=tcp
echo %res% | findstr %str% >nul && (
    @echo.
    echo 授权完成！连接中...

) || (
    echo 授权失败！原因：%res% 
)

for /f "delims=" %%i in ('adb devices') do set resc=%%i
echo %resc% | findstr %strs% >nul && (
    @echo.
    echo 已连接！按任意键关闭向导
    

) || (
    echo 连接失败！原因：%resc% 
)
pause



