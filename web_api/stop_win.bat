@echo off
setlocal
chcp 65001 >nul
title 知乎 Workbench — Stop Services

:: Stop hidden Workbench services started by web_api\start_win.bat.
:: This kills processes listening on the API and Vite ports only.

echo.
echo ====================================================
echo  Stopping zhihu Workbench services
echo  API      : 8765
echo  Frontend : 5173
echo ====================================================
echo.

for %%P in (8765 5173) do (
    echo [端口 %%P] 查找监听进程...
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr /C:":%%P" ^| findstr /C:"LISTENING"') do (
        echo [端口 %%P] taskkill /PID %%A /F
        taskkill /PID %%A /F >nul 2>&1
    )
)

echo.
echo 已发送停止命令。如仍无法访问端口，请在任务管理器检查残留 node.exe/python.exe。
echo.
pause
