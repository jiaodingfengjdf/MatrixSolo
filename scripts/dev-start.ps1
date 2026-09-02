param(
    [switch]$SkipBackend,
    [switch]$SkipAdmin,
    [switch]$SkipMcp,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"

# 项目根 = scripts 的上级目录
$Root = Split-Path -Parent $PSScriptRoot
$Admin = Join-Path $Root "admin"
$Logs = Join-Path $Root "data\logs"
$PidFile = Join-Path $Root "data\admin\dev_processes.json"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$PidDir = Split-Path -Parent $PidFile
New-Item -ItemType Directory -Force -Path $PidDir | Out-Null

# 优先使用项目 .venv，否则用全局 python
$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    $Python = $venvPython
} else {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
$Node = (Get-Command node -ErrorAction Stop).Source

function Test-PortInUse([int]$Port) {
    try {
        return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    } catch {
        return $false
    }
}

function Start-Tracked(
    [string]$Name,
    [string]$File,
    [string[]]$ArgList,
    [string]$WorkDir,
    [int]$Port
) {
    if (Test-PortInUse $Port) {
        Write-Host "  [跳过] $Name 端口 $Port 已被占用（视为已在运行）"
        return $null
    }
    $out = Join-Path $Logs "dev_$Name.out.log"
    $err = Join-Path $Logs "dev_$Name.err.log"
    $proc = Start-Process -FilePath $File -ArgumentList $ArgList -WorkingDirectory $WorkDir `
        -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden -PassThru
    Write-Host "  [启动] $Name  pid=$($proc.Id)  端口 $Port  日志 $out"
    return @{
        name = $Name
        pid = $proc.Id
        port = $Port
        log = $out
    }
}

Write-Host "== MatrixSolo 开发者模式一键启动 =="
Write-Host "   项目: $Root"
Write-Host "   python: $Python"
Write-Host "   node: $Node"
Write-Host ""

$entries = @()

if (-not $SkipBackend) {
    Write-Host "[1/3] 后端 FastAPI (uvicorn, reload=$(if ($NoReload) { 'off' } else { 'on' }))"
    $backendArgs = @("-m", "uvicorn", "matrixsolo.main:app", "--host", "127.0.0.1", "--port", "9797")
    if (-not $NoReload) {
        $backendArgs += "--reload"
    }
    $item = Start-Tracked "backend" $Python $backendArgs $Root 9797
    if ($item) { $entries += $item }
}

if (-not $SkipAdmin) {
    Write-Host "[2/3] 管理台 Next.js (next dev -> :3434)"
    $adminArgs = @("node_modules/next/dist/bin/next", "dev", "-p", "3434")
    $item = Start-Tracked "admin" $Node $adminArgs $Admin 3434
    if ($item) { $entries += $item }
}

if (-not $SkipMcp) {
    Write-Host "[3/3] 本地 MCP 执行器 (matrixsolo-mcp -> :8765)"
    $mcpArgs = @("-m", "matrixsolo.mcp_server.server")
    $item = Start-Tracked "mcp" $Python $mcpArgs $Root 8765
    if ($item) { $entries += $item }
}

if ($entries.Count -eq 0) {
    Write-Host ""
    Write-Host "没有新启动的服务（端口全部被占用或全部被跳过）。"
} else {
    $entries | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
    Write-Host ""
    Write-Host "已记录进程到: $PidFile"
}

Write-Host ""
Write-Host "访问入口:"
Write-Host "   Admin  http://127.0.0.1:3434"
Write-Host "   API    http://127.0.0.1:9797/health"
Write-Host "   MCP    http://127.0.0.1:8765/tools"
Write-Host ""
Write-Host "一键停止: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev-stop.ps1"
