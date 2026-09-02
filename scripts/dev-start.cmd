@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-start.ps1" %* -Tail
echo.
echo 窗口已保留。后台服务仍在运行，如需停止请运行 scripts\dev-stop.ps1
echo 按任意键关闭窗口...
pause >nul
