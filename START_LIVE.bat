@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title 知乎直播转写 — 启动器

:: ============================================================
:: START_LIVE.bat  知乎直播转写一键启动器
::
:: 用法:  双击此文件，或在 CMD 窗口执行  START_LIVE.bat
::        不要在 PowerShell 中直接执行（引号处理不兼容）
::
:: 解决的问题:
::   1. 安全传递含 & ? = 的知乎 URL（通过 env var 而非命令行参数）
::   2. 无需 PowerShell，双击即可启动
::   3. 可见窗口，方便监控直播进度和排查问题
:: ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   知乎直播转写启动器  ^(双击启动，无需 PowerShell^)
echo ============================================================
echo.

:: ---- 1. 前置检查 ----
if not exist "run_zhihu_live.bat" (
    echo [错误] 未找到 run_zhihu_live.bat，请确认此文件与 run_zhihu_live.bat 在同一目录
    pause
    exit /b 1
)

if not exist "zhihu_auth_state.json" (
    echo [错误] 未找到 zhihu_auth_state.json，请先运行:
    echo   python login_save_auth.py
    pause
    exit /b 1
)

:: ---- 2. 输入 URL ----
echo 请粘贴知乎直播间 URL，然后按回车：
echo （含 ^& ^? = 的完整 URL 均可直接粘贴，无需任何处理）
echo.
set /p "ZHIHU_PAGE_URL=URL: "
set "ZHIHU_PAGE_URL=!ZHIHU_PAGE_URL: =!"

if "!ZHIHU_PAGE_URL!"=="" (
    echo.
    echo [错误] 未输入 URL，退出。
    pause
    exit /b 1
)

echo !ZHIHU_PAGE_URL! | findstr /i "^http" >nul
if errorlevel 1 (
    echo.
    echo [错误] URL 格式不正确，必须以 http:// 或 https:// 开头。
    echo 您输入的内容: !ZHIHU_PAGE_URL!
    pause
    exit /b 1
)

echo.
echo URL: !ZHIHU_PAGE_URL!
echo.

:: ---- 3. 启动流水线 ----
:: ZHIHU_PAGE_URL 由 run_zhihu_live.bat 读取（已添加 env var 支持）
:: 使用 call 在当前可见窗口中运行，输出实时可见
call run_zhihu_live.bat

:: ---- 4. 结束后暂停（防止窗口立即关闭）----
echo.
echo ============================================================
echo   流水线已退出。按任意键关闭此窗口。
echo ============================================================
pause >nul
