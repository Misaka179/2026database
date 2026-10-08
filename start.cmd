@echo off
chcp 65001 >nul
setlocal
python -X utf8 "%~dp0start.py" %*
set "volunteerLauncherExit=%errorlevel%"
if not "%volunteerLauncherExit%"=="0" (
    echo.
    echo 启动未完成，请查看上方错误信息。按任意键关闭此窗口。
    pause >nul
)
exit /b %volunteerLauncherExit%
