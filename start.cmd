@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set "volunteerLauncherExit=1"
set "volunteerProjectPython=%~dp0.conda\envs\volunteer-core\python.exe"

rem Interpreter fallback: VOLUNTEER_PYTHON, then the bundled project env, then
rem whatever Python is on PATH. start.py re-runs itself with the bundled env if
rem the chosen Python is too old or lacks the runtime dependencies.
if defined VOLUNTEER_PYTHON if exist "%VOLUNTEER_PYTHON%" (
    "%VOLUNTEER_PYTHON%" -X utf8 "%~dp0start.py" %*
    set "volunteerLauncherExit=!errorlevel!"
    goto :volunteerReport
)
if exist "%volunteerProjectPython%" (
    "%volunteerProjectPython%" -X utf8 "%~dp0start.py" %*
    set "volunteerLauncherExit=!errorlevel!"
    goto :volunteerReport
)
where python >nul 2>nul
if not errorlevel 1 (
    python -X utf8 "%~dp0start.py" %*
    set "volunteerLauncherExit=!errorlevel!"
    goto :volunteerReport
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -X utf8 "%~dp0start.py" %*
    set "volunteerLauncherExit=!errorlevel!"
    goto :volunteerReport
)
echo 未找到可用的 Python。
echo 请安装 Python 3.10 或更新版本并执行 python -m pip install -r requirements.txt，
echo 或设置环境变量 VOLUNTEER_PYTHON 指向已安装依赖的解释器。

:volunteerReport
if not "%volunteerLauncherExit%"=="0" (
    echo.
    echo 启动未完成，请查看上方错误信息。按任意键关闭此窗口。
    pause >nul
)
exit /b %volunteerLauncherExit%
