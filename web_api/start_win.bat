@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 知乎 Workbench — API Server

:: ============================================================
:: start_win.bat  WIN 端 Workbench 一键启动
::
:: 启动内容:
::   1. zhihu API Watchdog  (0.0.0.0:8765，server.py 崩溃后 5s 自动重启，默认隐藏后台运行)
::   2. frontend Vite       (0.0.0.0:5173，局域网可访问，默认隐藏后台运行)
::
:: MAC 访问方式（同局域网）:
::   浏览器: http://<WIN局域网IP>:5173
::   查看 IP: ipconfig | findstr IPv4
::   调试前台窗口: set ZH_WORKBENCH_FOREGROUND=1 后再运行本脚本
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%~dp0.."
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "LAUNCH_MODE=live"
set "LOG_DIR=%PROJECT_DIR%\logs\web_api"

:: AI 助手面板需要 DEEPSEEK_API_KEY。
:: 请通过 Windows 系统环境变量设置（控制面板 → 高级系统设置 → 环境变量），
:: 或在启动前的 CMD 会话中执行：setx DEEPSEEK_API_KEY "sk-..."（该命令不进入本文件）。
:: 绝不在此文件或任何版本控制文件中写入真实密钥。

cd /d "%PROJECT_DIR%"

if not exist "!LOG_DIR!" mkdir "!LOG_DIR!"

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
echo  Logs         : !LOG_DIR!
echo ====================================================
echo.

set "API_PID="
set "FRONTEND_PID="
for /f "tokens=5" %%A in ('netstat -ano ^| findstr /C:":8765" ^| findstr /C:"LISTENING"') do set "API_PID=%%A"
for /f "tokens=5" %%A in ('netstat -ano ^| findstr /C:":5173" ^| findstr /C:"LISTENING"') do set "FRONTEND_PID=%%A"

if defined API_PID echo [提示] API 端口 8765 已在监听，PID=!API_PID!，将跳过 API 启动。
if defined FRONTEND_PID echo [提示] Frontend 端口 5173 已在监听，PID=!FRONTEND_PID!，将跳过 Frontend 启动。
if defined API_PID echo 如需重启服务，请先运行 web_api\stop_win.bat。
if defined FRONTEND_PID echo 如需重启服务，请先运行 web_api\stop_win.bat。
if defined API_PID echo.
if defined FRONTEND_PID echo.

if /i "!ZH_WORKBENCH_FOREGROUND!"=="1" goto foreground

echo [启动] 默认后台隐藏模式：关闭本启动器不会停止 API/Vite。
echo [日志] API      : !LOG_DIR!\api-watchdog.log
echo [日志] Frontend : !LOG_DIR!\frontend-vite.log
echo.

if defined API_PID (
    echo [跳过] API 已在运行。
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_background.ps1" ^
      -Service api ^
      -ProjectDir "%PROJECT_DIR%" ^
      -PythonExe "!PYTHON!" ^
      -LaunchMode "!LAUNCH_MODE!" ^
      -LogDir "!LOG_DIR!"
    if errorlevel 1 (
        echo [错误] API 后台启动失败，请查看上方 PowerShell 错误。
        pause
        exit /b 1
    )
)

timeout /t 2 /nobreak >nul

if defined FRONTEND_PID (
    echo [跳过] Frontend 已在运行。
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_background.ps1" ^
      -Service frontend ^
      -ProjectDir "%PROJECT_DIR%" ^
      -PythonExe "!PYTHON!" ^
      -LaunchMode "!LAUNCH_MODE!" ^
      -LogDir "!LOG_DIR!"
    if errorlevel 1 (
        echo [错误] Frontend 后台启动失败，请查看上方 PowerShell 错误。
        pause
        exit /b 1
    )
)

goto done

:foreground
echo [启动] 前台调试模式：会打开两个可见窗口。
echo.

:: API Watchdog — server.py 崩溃后 5s 自动重启
if defined API_PID (
    echo [跳过] API 已在运行。
) else (
    start "zhihu API Watchdog" /D "%PROJECT_DIR%" cmd /k ^
      "set PYTHON_EXE=!PYTHON!&& set LAUNCH_MODE=!LAUNCH_MODE!&& set PROJECT_DIR=!PROJECT_DIR!&& call web_api\api_watchdog.bat"
)

timeout /t 2 /nobreak >nul

if defined FRONTEND_PID (
    echo [跳过] Frontend 已在运行。
) else (
    if exist "%PROJECT_DIR%\frontend\node_modules" (
        start "zhihu Frontend" /D "%PROJECT_DIR%\frontend" cmd /k "set VITE_HOST=0.0.0.0&& npx vite --host 0.0.0.0"
    ) else (
        start "zhihu Frontend" /D "%PROJECT_DIR%\frontend" cmd /k "npm install && set VITE_HOST=0.0.0.0&& npx vite --host 0.0.0.0"
    )
)

:done
echo 服务已启动。API 崩溃后会在 5s 内自动恢复。
echo MAC 访问: http://^<WIN局域网IP^>:5173
echo 查看日志: !LOG_DIR!
echo 停止服务: web_api\stop_win.bat
echo.
pause
