@echo off
chcp 65001 >nul
echo ===== 知乎训练营课程回放批量下载 =====
echo.

REM ── 检查 Python ──────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [error] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM ── 检查 playwright ──────────────────────────────────────────
python -c "import playwright" >nul 2>&1
if errorlevel 1 (
    echo [安装] playwright...
    pip install playwright
    if errorlevel 1 (
        echo [error] playwright 安装失败，请手动运行: pip install playwright
        pause
        exit /b 1
    )
)

REM ── 检查 Chromium ─────────────────────────────────────────────
playwright install chromium >nul 2>&1

REM ── 检查 ffmpeg ───────────────────────────────────────────────
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [error] 未找到 ffmpeg
    echo   请下载: https://ffmpeg.org/download.html
    echo   解压后将 bin\ 目录加入系统 PATH，然后重新运行本脚本
    pause
    exit /b 1
)

REM ── 检查登录态 ────────────────────────────────────────────────
if not exist "zhihu_auth_state.json" (
    echo [提示] 未找到 zhihu_auth_state.json
    echo   请先运行: python login_save_auth.py
    echo   扫描二维码登录知乎后，再重新运行本脚本
    echo.
    set /p CONTINUE="是否仍然继续（无登录态可能无法访问付费视频）？[y/N] "
    if /i not "%CONTINUE%"=="y" (
        pause
        exit /b 1
    )
)

echo.
echo 开始下载课程回放...
echo 输出目录: downloads\zhihu_course\
echo （浏览器窗口会自动弹出，请勿关闭，等待脚本自动操作）
echo.

python scripts\zhihu_course_replay_downloader.py %*

echo.
echo 下载结束，文件在 downloads\zhihu_course\
pause
