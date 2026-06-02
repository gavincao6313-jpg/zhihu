@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: api_watchdog.bat — zhihu API 进程守护
::
:: 由 start_win.bat 调用，无限循环重启 API server。
:: 所需环境变量（调用前设好）:
::   PYTHON_EXE  — python.exe 完整路径
::   LAUNCH_MODE — live | simulate
::   PROJECT_DIR — 项目根目录
:: ============================================================

if "!PYTHON_EXE!"=="" set "PYTHON_EXE=python"
if "!LAUNCH_MODE!"=="" set "LAUNCH_MODE=live"
if "!PROJECT_DIR!"=="" set "PROJECT_DIR=%~dp0.."

cd /d "!PROJECT_DIR!"

:loop
echo [%DATE% %TIME%] [Watchdog] Starting API server (mode=!LAUNCH_MODE!)...
"!PYTHON_EXE!" web_api\server.py --host 0.0.0.0 --port 8765 --launch-mode !LAUNCH_MODE!
set "EXIT_CODE=!ERRORLEVEL!"
echo [%DATE% %TIME%] [Watchdog] API exited (code !EXIT_CODE!). Restarting in 5s...
echo [Watchdog] 如需永久停止，直接关闭本窗口。
timeout /t 5 /nobreak >nul
goto loop
