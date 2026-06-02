@echo off
set VENV_PYTHON=D:\zhihu\zhihu_file\.venv-sensevoice\Scripts\python.exe
set SCRIPT=D:\zhihu\zhihu_file\scripts\toutiao_login.py

echo ============================================================
echo Opening Toutiao login page...
echo After scanning QR code in browser, press Enter here to save.
echo ============================================================

"%VENV_PYTHON%" "%SCRIPT%" --login-url "https://www.toutiao.com/"

pause
