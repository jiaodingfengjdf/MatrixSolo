@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-stop.ps1" %*
echo.
echo 按任意键关闭窗口...
pause >nul
