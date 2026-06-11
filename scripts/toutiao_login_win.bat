@echo off
set SCRIPT_DIR=%~dp0
set REPO_ROOT=%SCRIPT_DIR%..
set VENV_PYTHON=%REPO_ROOT%\.venv-sensevoice\Scripts\python.exe
set SCRIPT=%SCRIPT_DIR%toutiao_login.py

echo ============================================================
echo Opening Toutiao login page...
echo After scanning QR code in browser, press Enter here to save.
echo ============================================================

"%VENV_PYTHON%" "%SCRIPT%" --login-url "https://www.toutiao.com/"

pause
