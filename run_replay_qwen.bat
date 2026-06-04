@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_replay_qwen.bat  回放/本地 MP4 Qwen 合成一键入口
::
:: 用法:
::   run_replay_qwen.bat <视频文件路径> <输出名称>
::
:: 示例:
::   run_replay_qwen.bat "Videos\replay-20260603.mp4" replay-20260603
::
:: 输出:
::   Markdowns\TTS_stream-{NAME}-qwen.md
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"

if exist "!VENV_PYTHON!" (
    set "PYTHON=!VENV_PYTHON!"
) else (
    set "PYTHON=python"
)

set "VIDEO_PATH=%~1"
set "BASE_NAME=%~2"
set "QWEN_MAX_FRAMES=128"
if "!QWEN_MODEL!"=="" set "QWEN_MODEL=qwen3.7-plus"

if "!VIDEO_PATH!"=="" (
    echo [错误] 请提供视频文件路径
    echo 用法: run_replay_qwen.bat ^<视频文件路径^> ^<输出名称^>
    pause & exit /b 1
)
if "!BASE_NAME!"=="" (
    echo [错误] 请提供输出名称
    pause & exit /b 1
)
if "!DASHSCOPE_API_KEY!"=="" (
    echo [错误] 请先设置: set DASHSCOPE_API_KEY=your_key
    pause & exit /b 1
)

echo.
echo ====================================================
echo  回放/本地 MP4 Qwen 合成
echo  视频     : !VIDEO_PATH!
echo  输出名称 : !BASE_NAME!
echo  模型     : !QWEN_MODEL!
echo ====================================================
echo.

:: ---- Step 1: 关键帧提取 + 分块转写 ----
echo [1/2] 关键帧提取 + 分块转写 (process_replay_qwen.py)...
"!PYTHON!" "!SCRIPT_DIR!process_replay_qwen.py" ^
  "!VIDEO_PATH!" ^
  --base "!BASE_NAME!" ^
  --runs-dir "!SCRIPT_DIR!runs"
if errorlevel 1 (
    echo [错误] 预处理失败
    pause & exit /b 1
)

:: Read run_ts written by process_replay_qwen.py to isolate this run's chunks
set "RUN_TS_FILE=!SCRIPT_DIR!runs\stream-!BASE_NAME!.last-run-ts.txt"
if not exist "!RUN_TS_FILE!" (
    echo [错误] 找不到 run_ts 标记文件: !RUN_TS_FILE!
    pause & exit /b 1
)
set /p RUN_TS=<"!RUN_TS_FILE!"
echo [info] Run TS: !RUN_TS!

:: ---- Step 2: Qwen 合成 ----
echo.
echo [2/2] Qwen 合成 NotebookLM 文档 (sliding-window)...
"!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
  --base "!BASE_NAME!" ^
  --run-ts "!RUN_TS!" ^
  --runs-dir "!SCRIPT_DIR!runs" ^
  --markdowns-dir "!SCRIPT_DIR!Markdowns" ^
  --provider qwen ^
  --synthesis-pass sliding-window ^
  --qwen-max-frames "!QWEN_MAX_FRAMES!" ^
  --output-label qwen ^
  --max-retries 2 ^
  --max-continuations 2
if errorlevel 1 (
    echo.
    echo [错误] 合成失败，续跑命令（复用已完成窗口）:
    echo   python scripts\build_stream_markdown.py --base !BASE_NAME! --provider qwen --synthesis-pass sliding-window --resume-window-notes --qwen-max-frames !QWEN_MAX_FRAMES! --output-label qwen
    pause & exit /b 1
)

echo.
echo 完成: Markdowns\TTS_stream-!BASE_NAME!-qwen.md
pause
