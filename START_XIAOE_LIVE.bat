@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 小鹅通直播转写 — 启动器

cd /d "%~dp0"

:: ============================================================
:: START_XIAOE_LIVE.bat  小鹅通直播转写一键启动器
::
:: 用法:  双击此文件，粘贴直播间 URL 回车即可。
::        不要在 PowerShell 中直接执行。
::
:: 自动完成: 认证检查 → 探针获取流地址 → 录制+转写 → 合成笔记
:: ============================================================

set "VENV_PYTHON=d:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe"
set "AUTH_FILE=zhihu_auth_state_xiaoe.json"
set "STREAM_WORK_DIR=Videos\.stream"
set "HEADERS_FILE=%STREAM_WORK_DIR%\xiaoe_headers.txt"

echo.
echo ============================================================
echo   小鹅通直播转写启动器 (双击启动)
echo ============================================================
echo.

:: ---- 1. 环境检查 ----
if not exist "%VENV_PYTHON%" (
    echo [错误] venv Python 不存在: %VENV_PYTHON%
    pause
    exit /b 1
)

:: ---- 2. 输入 URL ----
if "%~1"=="" (
    echo 请粘贴小鹅通直播间 URL，然后按回车：
    echo （含 ^& ? = 的完整 URL 均可直接粘贴）
    echo.
    set /p "PAGE_URL=URL: "
) else (
    set "PAGE_URL=%~1"
)
set "PAGE_URL=!PAGE_URL: =!"

if "!PAGE_URL!"=="" (
    echo [错误] 未输入 URL，退出。
    pause
    exit /b 1
)

echo !PAGE_URL! | findstr /i "^http" >nul
if errorlevel 1 (
    echo [错误] URL 格式不正确，必须以 http:// 或 https:// 开头。
    pause
    exit /b 1
)

:: Extract origin for Referer header
for /f "tokens=1,2,3 delims=/" %%a in ("!PAGE_URL!") do (
    set "ORIGIN=%%a//%%b"
)

echo.
echo URL: !PAGE_URL:~0,100!...
echo Origin: !ORIGIN!
echo.

:: ---- 3. 认证检查 ----
if not exist "%AUTH_FILE%" (
    echo [认证] 未找到 %AUTH_FILE%，正在打开浏览器登录...
    echo [认证] 请在浏览器中扫码或手机号登录，脚本会自动检测。
    "%VENV_PYTHON%" save_xiaoe_auth.py "!PAGE_URL!"
    if not exist "%AUTH_FILE%" (
        echo [错误] 登录失败，请手动运行: python save_xiaoe_auth.py
        pause
        exit /b 1
    )
    echo [认证] 登录成功。
) else (
    echo [认证] %AUTH_FILE% 已存在。
)

:: ---- 4. 自动生成名称 ----
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
    set "NAME=xiaoe-%%c%%a%%b-%%d%%e%%f"
)
set "NAME=!NAME: =0!"
echo [名称] !NAME!

:: ---- 5. 探针：获取 m3u8 流地址 ----
echo.
echo [探针] 正在获取直播流地址 (最多等待 45 秒)...
set "M3U8_URL="
for /f "tokens=2 delims==" %%a in ('"%VENV_PYTHON%" probe_xiaoe_stream.py "!PAGE_URL!" "%AUTH_FILE%" 2^>nul ^| findstr "M3U8_URL="') do (
    set "M3U8_URL=%%a"
)
if "!M3U8_URL!"=="" (
    echo [错误] 无法获取直播流地址。可能原因:
    echo   1. 直播尚未开始（老师未进入教室）
    echo   2. 认证已过期（删除 %AUTH_FILE% 后重试）
    echo   3. URL 已失效
    pause
    exit /b 1
)
echo [探针] 流地址: !M3U8_URL:~0,100!...

:: ---- 6. 创建 Referer 头文件 ----
mkdir "%STREAM_WORK_DIR%" 2>nul
echo Referer: !ORIGIN!/ > "%HEADERS_FILE%"
echo [头文件] 已创建: %HEADERS_FILE%

:: ---- 7. 启动录制+转写 ----
echo.
echo ============================================================
echo   录制+转写运行中...
echo   名称  : !NAME!
echo   流地址: !M3U8_URL:~0,80!...
echo.
echo   ** 关闭此窗口将停止录制 **
echo ============================================================
echo.

set "SENSEVOICE_MERGE_VAD=true"

"%VENV_PYTHON%" zhihuTTS_stream.py ^
  --continuous-hls ^
  --url "!M3U8_URL!" ^
  --headers-file "%HEADERS_FILE%" ^
  --chunk-duration 60 ^
  --name "!NAME!" ^
  --stream-work-dir "%STREAM_WORK_DIR%"

if errorlevel 1 (
    echo.
    echo [异常] 录制异常退出，退出码: !errorlevel!
    echo 已保存的分片不受影响。检查 CMD 窗口上方的错误信息。
    pause
    exit /b 1
)

:: ---- 8. 后处理：合并 + 合成 ----
echo.
echo ============================================================
echo   录制结束，正在生成笔记...
echo ============================================================
echo.

echo [合并] 合并所有分片...
"%VENV_PYTHON%" scripts\merge_stream_chunks.py --base "!NAME!" --runs-dir runs

echo.
if errorlevel 1 (
    echo [提示] 分片合并失败或无需合并，手动运行:
    echo   python scripts\merge_stream_chunks.py --base !NAME! --runs-dir runs
) else (
    echo [合并] 完成: runs\stream-!NAME!-merged.md
)

echo.
echo [合成] 生成 NotebookLM 笔记...
if not "!GEMINI_API_KEY!"=="" (
    "%VENV_PYTHON%" scripts\build_stream_markdown.py --base "!NAME!" --runs-dir runs --markdowns-dir Markdowns
    if errorlevel 1 (
        echo [提示] 笔记生成失败，手动运行:
        echo   python scripts\build_stream_markdown.py --base !NAME! --runs-dir runs --markdowns-dir Markdowns
    ) else (
        echo [合成] 完成: Markdowns\TTS_stream-!NAME!-gemini35.md
    )
) else (
    echo [提示] 未设置 GEMINI_API_KEY，跳过笔记生成。
    echo   手动运行: set GEMINI_API_KEY=your_key ^& python scripts\build_stream_markdown.py --base !NAME! --runs-dir runs --markdowns-dir Markdowns
)

echo.
echo ============================================================
echo   全部完成！
echo   产物目录:
echo     runs\stream-!NAME!-*
echo     Markdowns\TTS_stream-!NAME!-*.md
echo ============================================================
pause
