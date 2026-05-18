@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_zhihu_live.bat  知乎直播流一键转写
::
:: 用法:
::   run_zhihu_live.bat <直播间URL> [输出名]
::
:: 示例:
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx"
::     （不填名称时用 live-YYYYMMDD-HHMMSS 自动命名）
::
:: 输出（位于 runs\ 目录）:
::   stream-<NAME>-<时间>.combined-transcript.txt   完整逐字转写
::   stream-<NAME>-<时间>.manifest.md               逐块统计
::   stream-<NAME>-<时间>.notes.md                  Gemini 结构化笔记（需要 GEMINI_API_KEY）
::
:: 依赖（首次使用前确认）:
::   1. python login_save_auth.py   扫码登录，生成 zhihu_auth_state.json
::   2. 设置环境变量 GEMINI_API_KEY（可选，不设则跳过笔记生成）
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "AUTH_STATE=%SCRIPT_DIR%zhihu_auth_state.json"
set "STREAM_WORK_DIR=%SCRIPT_DIR%Videos\.stream"
set "PAGE_URL=%~1"
set "NAME=%~2"

:: ---- 自动生成名称（未提供时）----
if "!NAME!"=="" (
    for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
        set "NAME=live-%%c%%a%%b-%%d%%e%%f"
    )
    set "NAME=!NAME: =0!"
)

:: ---- 参数检查 ----
if "!PAGE_URL!"=="" (
    echo.
    echo 用法: run_zhihu_live.bat ^<直播间URL^> [输出名]
    echo 示例: run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/..." gaowei-20260519
    echo.
    exit /b 1
)

:: ---- Python 检查（venv 优先，降级到系统 python）----
if exist "!VENV_PYTHON!" (
    set "PYTHON=!VENV_PYTHON!"
) else (
    set "PYTHON=python"
    echo [提示] 未找到 venv python，使用系统 python（确保已激活对应环境）
)

:: ---- 登录状态检查 ----
if not exist "!AUTH_STATE!" (
    echo.
    echo [错误] 未找到登录状态文件:
    echo   !AUTH_STATE!
    echo.
    echo 请先运行一次登录:
    echo   python login_save_auth.py
    echo.
    exit /b 1
)

:: ---- 提示信息 ----
echo.
echo ====================================================
echo  知乎直播转写启动
echo  名称  : !NAME!
echo  URL   : !PAGE_URL!
echo  Auth  : !AUTH_STATE!
echo  临时   : !STREAM_WORK_DIR!
if "!GEMINI_API_KEY!"=="" (
    echo  Gemini: 未设置 GEMINI_API_KEY，将跳过笔记生成
) else (
    echo  Gemini: 已配置，直播结束后自动生成笔记
)
echo ====================================================
echo.

:: ---- 运行 ----
"!PYTHON!" "!SCRIPT_DIR!zhihuTTS_stream.py" ^
  --playwright-keepalive ^
  --page-url "!PAGE_URL!" ^
  --playwright-storage-state "!AUTH_STATE!" ^
  --playwright-save-storage-state "!AUTH_STATE!" ^
  --duration 0 ^
  --chunk-duration 60 ^
  --stream-work-dir "!STREAM_WORK_DIR!" ^
  --cleanup-slices ^
  --name "!NAME!" ^
  --gemini

echo.
if errorlevel 1 (
    echo [!] 脚本异常退出，退出码: %errorlevel%
) else (
    echo 转写完成，输出文件在 runs\ 目录
)
echo.
pause
