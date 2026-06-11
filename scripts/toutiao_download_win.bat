@echo off
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..
set VENV_PYTHON=%REPO_ROOT%\.venv-sensevoice\Scripts\python.exe
set SCRIPT=%SCRIPT_DIR%toutiao_download_favorites.py

echo ============================================================
echo Toutiao Favorites Downloader
echo ============================================================
echo.

REM -- Dry-run first so the user sees what will be downloaded --
echo [Step 1/2] Checking pending downloads...
"%VENV_PYTHON%" "%SCRIPT%" --new-only --dry-run
if errorlevel 1 (
    echo ERROR: dry-run failed. Check that auth_state.json exists.
    pause
    exit /b 1
)

echo.
set /p CONFIRM=Start downloading? [Y/N]:
if /i not "%CONFIRM%"=="Y" (
    echo Aborted.
    pause
    exit /b 0
)

echo.
echo [Step 2/2] Downloading...
"%VENV_PYTHON%" "%SCRIPT%" --new-only --prefer-playwright
if errorlevel 1 (
    echo ERROR: download script exited with an error.
) else (
    echo Done.
)

pause
