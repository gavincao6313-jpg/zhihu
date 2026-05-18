@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_live.bat  知乎直播流一键转写
::
:: 用法:
::   run_live.bat <直播间URL> <输出名>
::
:: 示例:
::   run_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519
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
set "AUTH_STATE=%SCRIPT_DIR%zhihu_auth_state.json"
set "PAGE_URL=%~1"
set "NAME=%~2"

:: ---- 参数检查 ----
if "!PAGE_URL!"=="" (
    echo 用法: run_live.bat ^<直播间URL^> ^<输出名^>
    echo 示例: run_live.bat "https://www.zhihu.com/xen/training/live/room/..." gaowei-20260519
    exit /b 1
)
if "!NAME!"=="" (
    echo 错误: 请提供输出名（第二个参数）
    echo 示例: run_live.bat "https://..." gaowei-20260519
    exit /b 1
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
if "!GEMINI_API_KEY!"=="" (
    echo  Gemini: 未设置 GEMINI_API_KEY，将跳过笔记生成
) else (
    echo  Gemini: 已配置，直播结束后自动生成笔记
)
echo ====================================================
echo.

:: ---- 运行 ----
python "!SCRIPT_DIR!zhihuTTS_stream.py" ^
  --playwright-keepalive ^
  --page-url "!PAGE_URL!" ^
  --playwright-storage-state "!AUTH_STATE!" ^
  --duration 0 ^
  --chunk-duration 60 ^
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
