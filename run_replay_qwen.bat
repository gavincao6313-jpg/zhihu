@echo off
setlocal enabledelayedexpansion
:: ============================================================
:: run_replay_qwen.bat  回放视频 Qwen 合成一键入口
::
:: 前提：zhihuTTS_video.py 已处理视频，产出 payload.json
::
:: 用法:
::   run_replay_qwen.bat <payload.json路径> <输出名称>
::
:: 示例:
::   run_replay_qwen.bat "cache\payload\replay-20260530.payload.json" replay-20260530
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

set "PAYLOAD_PATH=%~1"
set "BASE_NAME=%~2"
set "QWEN_MAX_FRAMES=128"

if "!PAYLOAD_PATH!"=="" (
    echo [错误] 请提供 payload.json 路径
    echo 用法: run_replay_qwen.bat ^<payload.json^> ^<输出名称^>
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
echo  回放视频 Qwen 合成
echo  Payload : !PAYLOAD_PATH!
echo  输出名称 : !BASE_NAME!
echo  模型     : !QWEN_MODEL!
echo  synthesis_pass: auto-route ^(^>30K字 → sliding-window^)
echo ====================================================
echo.

:: ---- Step 1: payload → chunk 格式转换 ----
echo [1/2] 转换 payload → stream chunks...
"!PYTHON!" "!SCRIPT_DIR!scripts\convert_payload_to_chunks.py" ^
  "!PAYLOAD_PATH!" "!BASE_NAME!" "!SCRIPT_DIR!runs"
if errorlevel 1 (
    echo [错误] 转换失败
    pause & exit /b 1
)

:: ---- Step 2: Qwen 合成 ----
echo.
echo [2/2] Qwen 合成 NotebookLM 文档...
"!PYTHON!" "!SCRIPT_DIR!scripts\build_stream_markdown.py" ^
  --base "!BASE_NAME!" ^
  --runs-dir "!SCRIPT_DIR!runs" ^
  --markdowns-dir "!SCRIPT_DIR!Markdowns" ^
  --provider qwen ^
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
