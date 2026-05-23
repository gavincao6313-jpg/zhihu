@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_zhihu_live.bat  知乎直播流一键转写
::
:: 用法:
::   run_zhihu_live.bat <直播间URL> [输出名] [--no-gemini] [--dry-run]
::
:: 示例:
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" gaowei-20260519
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx"
::     （不填名称时由 Python 按 live_YYYYMMDD_<页面标题> 自动命名）
::   run_zhihu_live.bat "https://www.zhihu.com/xen/training/live/room/xxx" --dry-run
::     （只打印命令和 Gemini 预算，不启动直播转写）
::
:: 输出（位于 runs\ 目录）:
::   stream-<NAME>-<时间>.combined-transcript.txt   完整逐字转写
::   stream-<NAME>-<时间>.manifest.md               逐块统计
::   Markdowns\TTS_stream-<NAME>.md                NotebookLM 文档（默认最多 1+2 次 Gemini 成功调用）
::   Slides\<NAME>\slides.pdf + slides.pptx        幻灯片 PDF + PPTX
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
set "REQUESTED_NAME="
set "NAME=%REQUESTED_NAME%"
set "RESUME_FLAG="
set "NO_GEMINI=0"
set "DRY_RUN=0"
set "BUILD_MAX_RETRIES=2"
set "BUILD_MAX_CONTINUATIONS=2"

:PARSE_ARGS
if "%~2"=="" goto ARGS_DONE
if /i "%~2"=="--resume" (
    set "RESUME_FLAG=--resume"
) else if /i "%~2"=="--no-gemini" (
    set "NO_GEMINI=1"
) else if /i "%~2"=="--dry-run" (
    set "DRY_RUN=1"
) else if "!REQUESTED_NAME!"=="" (
    set "REQUESTED_NAME=%~2"
    set "NAME=%~2"
) else (
    echo [错误] 无法识别或重复的参数: %~2
    echo 用法: run_zhihu_live.bat ^<直播间URL^> [输出名] [--no-gemini] [--dry-run]
    exit /b 1
)
shift /2
goto PARSE_ARGS
:ARGS_DONE

if not "!RESUME_FLAG!"=="" (
    echo [错误] 当前默认 continuous HLS 直播入口不支持 --resume。
    echo        若需处理中断后已落盘的 .ts 分片，请手动使用:
    echo        python zhihuTTS_stream.py --hls-consumer-only --stream-work-dir ^<上次日志中的 HLS work dir^>
    exit /b 1
)

:: merge_vad=true 适合 60s 分片（短片段内 VAD 合并让文本更连贯）
set "SENSEVOICE_MERGE_VAD=true"

:: Gemini 预算：直播转写阶段永不传 --gemini；只允许最终 NotebookLM 合成一次。
set "FINAL_GEMINI_ENABLED=0"
if "!NO_GEMINI!"=="0" if not "!GEMINI_API_KEY!"=="" (
    set "FINAL_GEMINI_ENABLED=1"
)

:: ---- 日志名（未提供输出名时仅用于本次 BAT 日志；真实输出名由 Python 回写）----
if "!NAME!"=="" (
    for /f "usebackq" %%t in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"`) do set "NAME=live-%%t"
)
set "BASE_MARKER=%SCRIPT_DIR%runs\stream-base-!NAME!.txt"

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

if "!DRY_RUN!"=="1" (
    echo.
    echo ====================================================
    echo  DRY RUN: 知乎直播转写计划
    echo  URL                  : !PAGE_URL!
    if "!REQUESTED_NAME!"=="" (
        echo  输出名              : Python 自动生成 live_YYYYMMDD_页面标题
    ) else (
        echo  输出名              : !REQUESTED_NAME!
    )
    echo  Python               : !PYTHON!
    echo  采集模式            : continuous HLS recorder + async consumer
    echo  直播转写 Gemini       : disabled
    if "!FINAL_GEMINI_ENABLED!"=="1" (
        echo  最终 NotebookLM Gemini: enabled
        echo  Gemini model         : gemini-2.5-flash
        echo  max successful calls : 3 ^(1 initial + !BUILD_MAX_CONTINUATIONS! continuation^)
        echo  retry cap            : !BUILD_MAX_RETRIES!
    ) else (
        echo  最终 NotebookLM Gemini: disabled
    )
    echo.
    echo  Step 1: zhihuTTS_stream.py --continuous-hls --base-marker ^<marker^> ^(no --gemini^)
    echo  Step 2: merge_stream_chunks.py --base ^<resolved marker base^>
    echo  Step 3: build_stream_markdown.py --base ^<resolved marker base^> --max-retries !BUILD_MAX_RETRIES! --max-continuations !BUILD_MAX_CONTINUATIONS!
    echo  Step 4: extract_slides.py --stream-base ^<resolved marker base^> ^(PDF + PPTX^)
    echo ====================================================
    exit /b 0
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
if "!REQUESTED_NAME!"=="" (
    echo  名称  : 自动（live_日期_页面标题）
) else (
    echo  名称  : !REQUESTED_NAME!
)
echo  URL   : !PAGE_URL!
echo  Auth  : !AUTH_STATE!
echo  Mode  : continuous HLS recorder + async consumer
if "!GEMINI_API_KEY!"=="" (
    echo  Gemini: 未设置 GEMINI_API_KEY，将跳过最终 NotebookLM 生成
) else if "!NO_GEMINI!"=="1" (
    echo  Gemini: 已通过 --no-gemini 禁用
) else (
    echo  Gemini: 最终 NotebookLM 生成启用（直播转写阶段不调用 Gemini）
    echo  Gemini预算: max successful calls=3, retry cap=!BUILD_MAX_RETRIES!
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
::          / SENSEVOICE_MERGE_VAD / GEMINI_API_KEY / FINAL_GEMINI_ENABLED）
:: 均由父进程环境继承，无需重新传参。
:: ================================================================
:WORKER

(
echo ====================================================
echo  知乎直播转写 - 后台任务
if "!REQUESTED_NAME!"=="" (
    echo  名称  : 自动（live_日期_页面标题）
) else (
    echo  名称  : !REQUESTED_NAME!
)
echo  URL   : !PAGE_URL!
echo  Python: !PYTHON!
echo  开始  : %date% %TIME: =0%
echo ====================================================
echo.
) >> "!LOG_FILE!" 2>&1

:: ---- [1/4] 主转写（-u 保证实时刷入日志，不缓冲）----
echo [%date% %TIME: =0%] [1/4] 开始直播转写（continuous HLS，不在采集阶段调用 Gemini）... >> "!LOG_FILE!" 2>&1
if exist "!BASE_MARKER!" del "!BASE_MARKER!" >nul 2>&1
if "!REQUESTED_NAME!"=="" (
    "!PYTHON!" -u "!SCRIPT_DIR!zhihuTTS_stream.py" ^
      --playwright-keepalive ^
      --continuous-hls ^
      --page-url "!PAGE_URL!" ^
      --playwright-storage-state "!AUTH_STATE!" ^
      --playwright-save-storage-state "!AUTH_STATE!" ^
      --duration 0 ^
      --chunk-duration 60 ^
      --stream-work-dir "!STREAM_WORK_DIR!" ^
      --base-marker "!BASE_MARKER!" ^
      !RESUME_FLAG! >> "!LOG_FILE!" 2>&1
) else (
    "!PYTHON!" -u "!SCRIPT_DIR!zhihuTTS_stream.py" ^
      --playwright-keepalive ^
      --continuous-hls ^
      --page-url "!PAGE_URL!" ^
      --playwright-storage-state "!AUTH_STATE!" ^
      --playwright-save-storage-state "!AUTH_STATE!" ^
      --duration 0 ^
      --chunk-duration 60 ^
      --stream-work-dir "!STREAM_WORK_DIR!" ^
      --name "!REQUESTED_NAME!" ^
      --base-marker "!BASE_MARKER!" ^
      !RESUME_FLAG! >> "!LOG_FILE!" 2>&1
)

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

set "BASE_STEM="
if exist "!BASE_MARKER!" (
    for /f "usebackq delims=" %%b in ("!BASE_MARKER!") do (
        if not "%%~b"=="" set "BASE_STEM=%%~b"
    )
)
if "!BASE_STEM!"=="" (
    echo [%date% %TIME: =0%] [错误] 未读取到 Python 回写的输出名称 marker: !BASE_MARKER! >> "!LOG_FILE!" 2>&1
    echo.
    echo ==============================
    echo  转写失败！未读取到输出名称:
    echo  !BASE_MARKER!
    echo ==============================
    echo.
    pause
    exit /b 1
)
set "NAME=!BASE_STEM!"
echo [%date% %TIME: =0%] 实际输出名称: !NAME! >> "!LOG_FILE!" 2>&1

:: ---- [2/4] 分片合并 ----
echo. >> "!LOG_FILE!" 2>&1
echo [%date% %TIME: =0%] [2/4] 合并分片为结构化 Markdown... >> "!LOG_FILE!" 2>&1
"!PYTHON!" "!SCRIPT_DIR!scripts\merge_stream_chunks.py" ^
  --base "!NAME!" ^
  --runs-dir "!SCRIPT_DIR!runs" >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo [%date% %TIME: =0%] [提示] 分片合并失败，手动运行: >> "!LOG_FILE!" 2>&1
    echo   python scripts\merge_stream_chunks.py --base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %TIME: =0%] 结构化 Markdown: runs\stream-!NAME!-merged.md >> "!LOG_FILE!" 2>&1
)

:: ---- [3/4] Gemini 综合调用 → NotebookLM 文档 ----
echo. >> "!LOG_FILE!" 2>&1
if "!FINAL_GEMINI_ENABLED!"=="0" (
    if "!NO_GEMINI!"=="1" (
        echo [%date% %TIME: =0%] [3/4] 跳过 NotebookLM 生成（--no-gemini） >> "!LOG_FILE!" 2>&1
    ) else (
        echo [%date% %TIME: =0%] [3/4] 跳过 NotebookLM 生成（未设置 GEMINI_API_KEY） >> "!LOG_FILE!" 2>&1
    )
    echo   手动生成: set GEMINI_API_KEY=your_key ^& python scripts\build_stream_markdown.py --base !NAME! --max-retries !BUILD_MAX_RETRIES! --max-continuations !BUILD_MAX_CONTINUATIONS! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %TIME: =0%] [3/4] 生成 NotebookLM 文档（预计 2-5 分钟）... >> "!LOG_FILE!" 2>&1
    echo [%date% %TIME: =0%] Gemini budget: model=gemini-2.5-flash, pass=one-shot, max_successful_calls=3, retry_cap=!BUILD_MAX_RETRIES!, duplicate_synthesis=false >> "!LOG_FILE!" 2>&1
    "!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
      --base "!NAME!" ^
      --runs-dir "!SCRIPT_DIR!runs" ^
      --markdowns-dir "!SCRIPT_DIR!Markdowns" ^
      --max-retries "!BUILD_MAX_RETRIES!" ^
      --max-continuations "!BUILD_MAX_CONTINUATIONS!" >> "!LOG_FILE!" 2>&1
    if errorlevel 1 (
        echo [%date% %TIME: =0%] [提示] NotebookLM 文档生成失败，手动运行: >> "!LOG_FILE!" 2>&1
        echo   python scripts\build_stream_markdown.py --base !NAME! --max-retries !BUILD_MAX_RETRIES! --max-continuations !BUILD_MAX_CONTINUATIONS! >> "!LOG_FILE!" 2>&1
    ) else (
        echo [%date% %TIME: =0%] NotebookLM 文档: Markdowns\TTS_stream-!NAME!.md >> "!LOG_FILE!" 2>&1
    )
)

:: ---- [4/4] 幻灯片提取 ----
echo. >> "!LOG_FILE!" 2>&1
echo [%date% %TIME: =0%] [4/4] 从流关键帧提取幻灯片 (PDF + PPTX)... >> "!LOG_FILE!" 2>&1
"!PYTHON!" "!SCRIPT_DIR!extract_slides.py" --stream-base "!NAME!" >> "!LOG_FILE!" 2>&1
if errorlevel 1 (
    echo [%date% %TIME: =0%] [提示] 幻灯片提取失败，手动运行: >> "!LOG_FILE!" 2>&1
    echo   python extract_slides.py --stream-base !NAME! >> "!LOG_FILE!" 2>&1
) else (
    echo [%date% %TIME: =0%] 幻灯片: Slides\!NAME!\slides.pdf + slides.pptx >> "!LOG_FILE!" 2>&1
)

echo. >> "!LOG_FILE!" 2>&1
echo [%date% %TIME: =0%] ======== 全部完成 ======== >> "!LOG_FILE!" 2>&1

echo.
echo ==============================
echo  全部完成！输出文件:
echo    runs\       转写 + 统计
echo    Markdowns\  NotebookLM 文档
echo    Slides\     幻灯片 PDF + PPTX
echo    !LOG_FILE!
echo ==============================
echo.
pause
exit /b 0
