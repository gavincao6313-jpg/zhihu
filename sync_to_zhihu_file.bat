@echo off
setlocal
echo [sync] Copying updated pipeline files to zhihu_file\...
if not exist zhihu_file (
    echo [sync] ERROR: zhihu_file\ directory not found. Run from repo root.
    exit /b 1
)
copy /Y batch_process_external.py zhihu_file\batch_process_external.py
if errorlevel 1 ( echo [sync] FAILED: batch_process_external.py & exit /b 1 )
copy /Y utils.py zhihu_file\utils.py
if errorlevel 1 ( echo [sync] FAILED: utils.py & exit /b 1 )
echo [sync] Done. Run zhihu_file\batch_process_external.py as usual.
endlocal
