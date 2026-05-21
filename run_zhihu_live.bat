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
::   logs\run-<NAME>.log                            完整运行日志（本机保留，不入 Git）
::
:: 依赖（首次使用前确认）:
::   1. python login_save_auth.py   扫码登录，生成 zhihu_auth_state.json
::   2. 设置环境变量 GEMINI_API_KEY（可选，不设则跳过笔记生成）
:: ============================================================

:: ---- WORKER MODE: 内部自调用，在独立后台窗口中执行所有 Python 步骤 ----
:: 调用方式: run_zhihu_live.bat --worker "<LOG_FILE>"
:: NAME / PAGE_URL / PYTHON / AUTH_STATE 等变量从父进程环境继承
if /i "%~1"=="--worker" (
    set "LOG_FILE=%~2"
    set "SCRIPT_DIR=%~dp0"
    goto :WORKER
)

:: ================================================================
:: MAIN MODE: 参数校验 → 启动后台工作窗口 → 本窗口 tail 日志
:: ================================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "AUTH_STATE=%SCRIPT_DIR%zhihu_auth_state.json"
set "STREAM_WORK_DIR=%SCRIPT_DIR%Videos\.stream"
set "PAGE_URL=%~1"
set "NAME=%~2"

:: merge_vad=true 适合 60s 分片（短片段内 VAD 合并让文本更连贯）
set "SENSEVOICE_MERGE_VAD=true"

:: ---- 自动生成名称（未提供时）----
if "!NAME!"=="" (
    for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
        set "NAME=live-%%c%%a%%b-%%d%%e%%f"
    )
    set "NAME=!NAME: =0!"
)

:: ---- URL 检查（双击时弹出输入提示）----
if "!PAGE_URL!"=="" (
    echo.
    echo 请粘贴知乎直播间 URL，然后按回车：
    echo （示例: https://www.zhihu.com/xen/training/live/room/...）
    echo.
    set /p "PAGE_URL=URL: "
    set "PAGE_URL=!PAGE_URL: =!"
)
if "!PAGE_URL!"=="" (
    echo.
    echo [错误] 未输入 URL，退出。
    echo.
    pause
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

:: ---- Cookie 有效性检查（快速预检，失败立刻提示，不进入后台）----
"!PYTHON!" "!SCRIPT_DIR!scripts\check_auth.py" "!AUTH_STATE!"
if errorlevel 1 (
    echo.
    echo [错误] 登录 Cookie 已失效，请重新登录后再运行:
    echo   python login_save_auth.py
    echo.
    exit /b 1
)

:: ---- 日志目录 + 初始化空日志文件（供 tail 立刻打开）----
if not exist "!SCRIPT_DIR!logs" mkdir "!SCRIPT_DIR!logs"
set "LOG_FILE=!SCRIPT_DIR!logs\run-!NAME!.log"
echo. > "!LOG_FILE!"

:: ---- 启动信息 ----
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
echo.
echo  [后台独立运行] 关闭此窗口不影响转写任务
echo  日志文件 : !LOG_FILE!
echo  实时监控 : powershell Get-Content -Wait -Tail 50 "!LOG_FILE!"
echo ====================================================
echo.

:: ---- 启动后台工作窗口（独立进程，与本窗口生命周期解耦）----
start "zhihu [!NAME!]" cmd /k call "%~f0" --worker "!LOG_FILE!"

:: ---- 本窗口实时 tail 日志（Ctrl+C 或直接关窗退出监控，不影响后台任务）----
echo 实时日志（可随时关闭此窗口，后台任务不受影响）：
echo.
powershell -NoProfile -Command "Start-Sleep -Milliseconds 800; Get-Content -Wait -Tail 100 '!LOG_FILE!'"
exit /b 0


:: ================================================================
:: WORKER: 在后台窗口中运行，所有输出写入 LOG_FILE
:: 所需变量（NAME / PAGE_URL / PYTHON / AUTH_STATE / STREAM_WORK_DIR
::          / SENSEVOICE_MERGE_VAD / GEMINI_API_KEY）
:: 均由父进程环境继承，无需重新传参。
:: ================================================================
:WORKER

(
echo ====================================================
echo  知乎直播转写 - 后台任务
echo  名称  : !NAME!
echo  URL   : !PAGE_URL!
echo  Python: !PYTHON!
echo  开始  : %date% %time%
echo ====================================================
echo.
) >> "!LOG_FILE!" 2>&1

:: ---- [1/3] 主转写（-u 保证实时刷入日志，不缓冲）----
echo [%date% %time%] [1/3] 开始直播转写... >> "!LOG_FILE!" 2>&1
"!PYTHON!" -u "!SCRIPT_DIR!zhihuTTS_stream.py" ^
  --playwright-keepalive ^
  --page-url "!PAGE_URL!" ^
  --playwright-storage-state "!AUTH_STATE!" ^
  --playwright-save-storage-state "!AUTH_STATE!" ^
  --duration 0 ^
  --chunk-duration 60 ^
  --stream-work-dir "!STREAM_WORK_DIR!" ^
  --cleanup-slices ^
  --name "!NAME!" ^
  --gemini >> "!LOG_FILE!" 2>&1

if errorlevel 1 (
    echo. >> "!LOG_FILE!" 2>&1
    echo [%date% %time%] [错误] zhihuTTS_stream.py 异常退出，退出码: !errorlevel! >> "!LOG_FILE!" 2>&1
    echo.
    echo ==============================
    echo  转写失败！详细原因见日志:
    echo  !LOG_FILE!
    echo ==============================
    echo.
    pause
    exit /b 1
)

:: ---- [2/3] 分片合并 ----
echo. >> "!LOG_FILE!" 2>&1
echo [%date% %time%] [2/3] 合并分片为结构化 Markdown... >> "!LOG_FILE!" 2>&1
"!PYTHON!" "!SCRIPT_DIR!scripts\merge_stream_chunks.py" ^
  --base "!NAME!" ^
  --runs-dir "!SCRIPT_DIR!runs" >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo [%date% %time%] [提示] 分片合并失败，手动运行: >> "!LOG_FILE!" 2>&1
    echo   python scripts\merge_stream_chunks.py --base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %time%] 结构化 Markdown: runs\stream-!NAME!-merged.md >> "!LOG_FILE!" 2>&1
)

:: ---- [3/3] Gemini 综合调用 → NotebookLM 文档 ----
echo. >> "!LOG_FILE!" 2>&1
if "!GEMINI_API_KEY!"=="" (
    echo [%date% %time%] [3/3] 跳过 NotebookLM 生成（未设置 GEMINI_API_KEY） >> "!LOG_FILE!" 2>&1
    echo   手动生成: set GEMINI_API_KEY=your_key ^& python scripts\build_stream_markdown.py --base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %time%] [3/3] 生成 NotebookLM 文档（预计 2-5 分钟）... >> "!LOG_FILE!" 2>&1
    "!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
      --base "!NAME!" ^
      --runs-dir "!SCRIPT_DIR!runs" ^
      --markdowns-dir "!SCRIPT_DIR!Markdowns" >> "!LOG_FILE!" 2>&1
    if errorlevel 1 (
        echo [%date% %time%] [提示] NotebookLM 文档生成失败，手动运行: >> "!LOG_FILE!" 2>&1
        echo   python scripts\build_stream_markdown.py --base !NAME! >> "!LOG_FILE!" 2>&1
    ) else (
        echo [%date% %time%] NotebookLM 文档: Markdowns\TTS_stream-!NAME!.md >> "!LOG_FILE!" 2>&1
    )
)

echo. >> "!LOG_FILE!" 2>&1
echo [%date% %time%] ======== 全部完成 ======== >> "!LOG_FILE!" 2>&1

echo.
echo ==============================
echo  全部完成！输出文件:
echo    runs\       转写 + 统计
echo    Markdowns\  NotebookLM 文档
echo    !LOG_FILE!
echo ==============================
echo.
pause
exit /b 0
