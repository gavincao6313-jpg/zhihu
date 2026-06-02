@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 知乎 Workbench — API Server

:: ============================================================
:: start_win.bat  WIN 端 Workbench 一键启动
::
:: 启动内容:
::   1. zhihu API Watchdog  (0.0.0.0:8765，server.py 崩溃后 5s 自动重启)
::   2. frontend Vite       (0.0.0.0:5173，局域网可访问)
::
:: MAC 访问方式（同局域网）:
::   浏览器: http://<WIN局域网IP>:5173
::   查看 IP: ipconfig | findstr IPv4
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%~dp0.."
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "LAUNCH_MODE=live"

cd /d "%PROJECT_DIR%"

if exist "!VENV_PYTHON!" (
    set "PYTHON=!VENV_PYTHON!"
) else (
    set "PYTHON=python"
    echo [提示] 未找到 venv，使用系统 python
)

echo.
echo ====================================================
echo  API Watchdog : http://0.0.0.0:8765  (auto-restart)
echo  Frontend     : http://0.0.0.0:5173
echo  Launch mode  : !LAUNCH_MODE!
echo ====================================================
echo.

:: API Watchdog — server.py 崩溃后 5s 自动重启
start "zhihu API Watchdog" /D "%PROJECT_DIR%" cmd /k ^
  "set PYTHON_EXE=!PYTHON!&& set LAUNCH_MODE=!LAUNCH_MODE!&& set PROJECT_DIR=!PROJECT_DIR!&& call web_api\api_watchdog.bat"

timeout /t 2 /nobreak >nul

if exist "%PROJECT_DIR%\frontend\node_modules" (
    start "zhihu Frontend" /D "%PROJECT_DIR%\frontend" cmd /k "set VITE_HOST=0.0.0.0&& npx vite"
) else (
    start "zhihu Frontend" /D "%PROJECT_DIR%\frontend" cmd /k "npm install && set VITE_HOST=0.0.0.0&& npx vite"
)

echo 两个服务窗口已启动。API 崩溃后会在 5s 内自动恢复。
echo MAC 访问: http://^<WIN局域网IP^>:5173
echo.
pause
