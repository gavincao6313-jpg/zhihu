@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_zhihu_live.bat  知乎直播流一键转写
::
:: 用法:
::   run_zhihu_live.bat <直播间URL> [输出名] [--resume]
::
:: 示例:
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx"
::     （不填名称时用 live-YYYYMMDD-HHMMSS 自动命名）
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519 --resume
::     （--resume 从上次中断的 chunk 结束时间点继续，需同名 checkpoint 文件存在）
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

:: ---- WORKER MODE: 内部自调用，无窗口后台执行所有 Python 步骤 ----
:: 调用方式: run_zhihu_live.bat --worker "<LOG_FILE>"
:: NAME / PAGE_URL / PYTHON / AUTH_STATE 等变量从父进程环境继承
if /i "%~1"=="--worker" (
    set "LOG_FILE=%~2"
    set "SCRIPT_DIR=%~dp0"
    goto :WORKER
)

:: ================================================================
:: MAIN MODE: 参数校验 → 后台静默启动 WORKER → 本窗口 tail 日志
:: ================================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "AUTH_STATE=%SCRIPT_DIR%zhihu_auth_state.json"
set "STREAM_WORK_DIR=%SCRIPT_DIR%Videos\.stream"
set "PAGE_URL=%~1"
set "NAME=%~2"
set "RESUME_FLAG="
if /i "%~3"=="--resume" set "RESUME_FLAG=--resume"

:: merge_vad=true 适合 60s 分片（短片段内 VAD 合并让文本更连贯）
set "SENSEVOICE_MERGE_VAD=true"

:: --gemini 仅在 GEMINI_API_KEY 存在时传递，避免无 key 时 Python 内部触发无效 Gemini 调用
if not "!GEMINI_API_KEY!"=="" (
    set "GEMINI_FLAG=--gemini"
) else (
    set "GEMINI_FLAG="
)

:: ---- 自动生成名称（未提供时，用 PowerShell 保证跨 locale 格式一致）----
if "!NAME!"=="" (
    for /f "usebackq" %%t in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"`) do set "NAME=live-%%t"
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

:: ---- ffmpeg / ffprobe 检查 ----
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo [错误] 未找到 ffmpeg，请安装并加入 PATH:
    echo   winget install Gyan.FFmpeg   或   https://ffmpeg.org/download.html
    echo.
    exit /b 1
)
where ffprobe >nul 2>&1
if errorlevel 1 (
    echo.
    echo [错误] 未找到 ffprobe（通常与 ffmpeg 同包），请检查 PATH。
    echo.
    exit /b 1
)

:: ---- Videos\.stream 目录可写检查 ----
if not exist "!STREAM_WORK_DIR!" mkdir "!STREAM_WORK_DIR!" 2>nul
(echo preflight) > "!STREAM_WORK_DIR!\.preflight_test" 2>nul
if not exist "!STREAM_WORK_DIR!\.preflight_test" (
    echo.
    echo [错误] 无法写入工作目录: !STREAM_WORK_DIR!
    echo 请检查路径权限或磁盘状态。
    echo.
    exit /b 1
)
del "!STREAM_WORK_DIR!\.preflight_test" >nul 2>&1

:: ---- 磁盘空间检查（< 10GB 警告，不阻断）----
set "WORK_DRIVE=!STREAM_WORK_DIR:~0,1!"
powershell -NoProfile -Command "$free=[math]::Round((Get-PSDrive '!WORK_DRIVE!').Free/1GB,1); if($free -lt 10){Write-Host '[警告] 磁盘剩余 ' + $free + ' GB，建议保持 10 GB 以上（不足时录制中途可能中断）'}else{Write-Host '[信息] 磁盘剩余 ' + $free + ' GB'}"

:: ---- 转写后端信息 ----
if "!TRANSCRIBE_BACKEND!"=="" (
    echo [信息] TRANSCRIBE_BACKEND: 未设置（使用默认后端）
) else (
    echo [信息] TRANSCRIBE_BACKEND: !TRANSCRIBE_BACKEND!
)

:: ---- 日志目录 + 追加式日志文件（>> 不截断，支持同名重跑）----
if not exist "!SCRIPT_DIR!logs" mkdir "!SCRIPT_DIR!logs"
set "LOG_FILE=!SCRIPT_DIR!logs\run-!NAME!.log"
echo === 新运行 %date% %TIME: =0% === >> "!LOG_FILE!"
echo. >> "!LOG_FILE!"

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
echo  转写任务已在后台静默启动，本窗口可随时关闭
echo  日志文件 : !LOG_FILE!
echo  重新查看 : powershell Get-Content -Wait -Tail 50 "!LOG_FILE!"
echo ====================================================
echo.

:: ---- 后台静默启动 WORKER（/B 不创建新窗口，关闭本窗口不影响后台进程）----
start "" /B cmd /c call "%~f0" --worker "!LOG_FILE!"

:: ---- 本窗口实时 tail 日志（可随时关闭，后台任务继续运行）----
echo 实时日志（本窗口可随时关闭，转写在后台继续运行）：
echo.
powershell -NoProfile -Command "Start-Sleep -Milliseconds 800; Get-Content -Wait -Tail 100 '!LOG_FILE!'"
exit /b 0


:: ================================================================
:: WORKER: 无窗口静默运行，所有输出写入 LOG_FILE
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
echo  开始  : %date% %TIME: =0%
echo ====================================================
echo.
) >> "!LOG_FILE!" 2>&1

:: ---- [1/3] 主转写（-u 保证实时刷入日志，不缓冲）----
echo [%date% %TIME: =0%] [1/3] 开始直播转写... >> "!LOG_FILE!" 2>&1
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
  !GEMINI_FLAG! !RESUME_FLAG! >> "!LOG_FILE!" 2>&1

if errorlevel 1 (
    echo. >> "!LOG_FILE!" 2>&1
    echo [%date% %TIME: =0%] [错误] zhihuTTS_stream.py 异常退出，退出码: !errorlevel! >> "!LOG_FILE!" 2>&1
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
echo [%date% %TIME: =0%] [2/3] 合并分片为结构化 Markdown... >> "!LOG_FILE!" 2>&1
"!PYTHON!" "!SCRIPT_DIR!scripts\merge_stream_chunks.py" ^
  --base "!NAME!" ^
  --runs-dir "!SCRIPT_DIR!runs" >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo [%date% %TIME: =0%] [提示] 分片合并失败，手动运行: >> "!LOG_FILE!" 2>&1
    echo   python scripts\merge_stream_chunks.py --base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %TIME: =0%] 结构化 Markdown: runs\stream-!NAME!-merged.md >> "!LOG_FILE!" 2>&1
)

:: ---- [3/3] Gemini 综合调用 → NotebookLM 文档 ----
echo. >> "!LOG_FILE!" 2>&1
if "!GEMINI_API_KEY!"=="" (
    echo [%date% %TIME: =0%] [3/3] 跳过 NotebookLM 生成（未设置 GEMINI_API_KEY） >> "!LOG_FILE!" 2>&1
    echo   手动生成: set GEMINI_API_KEY=your_key ^& python scripts\build_stream_markdown.py --base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %TIME: =0%] [3/3] 生成 NotebookLM 文档（预计 2-5 分钟）... >> "!LOG_FILE!" 2>&1
    "!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
      --base "!NAME!" ^
      --runs-dir "!SCRIPT_DIR!runs" ^
      --markdowns-dir "!SCRIPT_DIR!Markdowns" ^
      --sectioned >> "!LOG_FILE!" 2>&1
    if errorlevel 1 (
        echo [%date% %TIME: =0%] [提示] NotebookLM 文档生成失败，手动运行: >> "!LOG_FILE!" 2>&1
        echo   python scripts\build_stream_markdown.py --base !NAME! --sectioned >> "!LOG_FILE!" 2>&1
    ) else (
        echo [%date% %TIME: =0%] NotebookLM 文档: Markdowns\TTS_stream-!NAME!.md >> "!LOG_FILE!" 2>&1
    )
)

echo. >> "!LOG_FILE!" 2>&1
echo [%date% %TIME: =0%] ======== 全部完成 ======== >> "!LOG_FILE!" 2>&1

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
