@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem 项目根 = scripts 上级目录
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
if not exist "data\logs" mkdir "data\logs"

set DO_INSTALL=0
set NORELOAD=0
set START_BACKEND=1
set START_ADMIN=1
set START_MCP=1
for %%a in (%*) do (
  if /i "%%~a"=="-Install" set DO_INSTALL=1
  if /i "%%~a"=="-NoReload" set NORELOAD=1
  if /i "%%~a"=="-SkipBackend" set START_BACKEND=0
  if /i "%%~a"=="-SkipAdmin" set START_ADMIN=0
  if /i "%%~a"=="-SkipMcp" set START_MCP=0
)

echo == MatrixSolo 开发者模式一键启动 ==
echo 项目: %ROOT%
echo.

if "%DO_INSTALL%"=="1" (
  echo [0/3] 安装 admin 依赖 npm install ...
  pushd "%ROOT%\admin"
  call npm.cmd install --no-audit --no-fund
  popd
)

if "%START_BACKEND%"=="1" (
  netstat -ano | findstr ":9797 " | findstr /i "LISTENING" >nul 2>nul
  if errorlevel 1 (
    echo [1/3] 启动 后端 FastAPI 9797
    set "RELOAD_ARG="
    if "%NORELOAD%"=="0" set "RELOAD_ARG=--reload"
    start "MatrixSolo-Backend" /min cmd /c "python -m uvicorn matrixsolo.main:app --host 127.0.0.1 --port 9797 %RELOAD_ARG% >> data\logs\dev_backend.out.log 2>> data\logs\dev_backend.err.log"
  ) else (
    echo [1/3] 跳过 后端已在运行 9797
  )
)

if "%START_ADMIN%"=="1" (
  netstat -ano | findstr ":3434 " | findstr /i "LISTENING" >nul 2>nul
  if errorlevel 1 (
    echo [2/3] 启动 管理台 Next.js 3434
    start "MatrixSolo-Admin" /D "%ROOT%\admin" /min cmd /c "node node_modules\next\dist\bin\next dev -p 3434 >> ..\data\logs\dev_admin.out.log 2>> ..\data\logs\dev_admin.err.log"
  ) else (
    echo [2/3] 跳过 管理台已在运行 3434
  )
)

if "%START_MCP%"=="1" (
  netstat -ano | findstr ":8765 " | findstr /i "LISTENING" >nul 2>nul
  if errorlevel 1 (
    echo [3/3] 启动 本地 MCP 8765
    start "MatrixSolo-MCP" /min cmd /c "python -m matrixsolo.mcp_server.server >> data\logs\dev_mcp.out.log 2>> data\logs\dev_mcp.err.log"
  ) else (
    echo [3/3] 跳过 MCP 已在运行 8765
  )
)

echo.
echo 访问入口:
echo   Admin  http://127.0.0.1:3434
echo   API    http://127.0.0.1:9797/health
echo   MCP    http://127.0.0.1:8765/tools
echo 日志: %ROOT%\data\logs\dev_*.log
echo.
echo 一键停止: scripts\dev-stop.bat
echo.
pause
