@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo == MatrixSolo 开发者模式一键停止 ==

set "SEEN_BACKEND="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":9797 " ^| findstr /i "LISTENING"') do (
  if not "%%P"=="!SEEN_BACKEND!" (
    set "SEEN_BACKEND=%%P"
    taskkill /PID %%P /T /F >nul 2>nul
    echo 已停止 后端 pid=%%P
  )
)
set "SEEN_ADMIN="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":3434 " ^| findstr /i "LISTENING"') do (
  if not "%%P"=="!SEEN_ADMIN!" (
    set "SEEN_ADMIN=%%P"
    taskkill /PID %%P /T /F >nul 2>nul
    echo 已停止 管理台 pid=%%P
  )
)
set "SEEN_MCP="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8765 " ^| findstr /i "LISTENING"') do (
  if not "%%P"=="!SEEN_MCP!" (
    set "SEEN_MCP=%%P"
    taskkill /PID %%P /T /F >nul 2>nul
    echo 已停止 MCP pid=%%P
  )
)

echo.
echo 端口 9797 / 3434 / 8765 已释放。
echo.
pause
