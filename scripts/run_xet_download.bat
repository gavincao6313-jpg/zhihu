@echo off
chcp 65001 >nul
echo ===== 小鹅通 PDF 批量下载 =====

REM 检查 requests 是否安装
python -c "import requests" 2>nul
if errorlevel 1 (
    echo [安装依赖] pip install requests
    pip install requests
)

echo.
echo 开始下载...
python scripts\xet_batch_download.py %*

echo.
echo 下载完成，文件在 downloads\xet_pdfs\
pause
