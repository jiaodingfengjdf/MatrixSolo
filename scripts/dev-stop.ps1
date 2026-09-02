param()

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $Root "data\admin\dev_processes.json"

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "没有找到 $PidFile，可能尚未用 dev-start.ps1 启动。"
    exit 0
}

$entries = Get-Content -LiteralPath $PidFile -Raw | ConvertFrom-Json
if ($entries -is [System.Management.Automation.PSCustomObject]) {
    $entries = @($entries)
}

Write-Host "== MatrixSolo 开发者模式一键停止 =="
foreach ($item in $entries) {
    $pidValue = [int]$item.pid
    if ($pidValue -le 0) { continue }
    Write-Host "  停止 $($item.name) (pid=$pidValue)"
    # 整棵进程树（uvicorn --reload / next dev 都会派生子进程）
    & taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
    if (Get-Process -Id $pidValue -ErrorAction SilentlyContinue) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "已停止并清理进程记录。端口 9797 / 3434 / 8765 可复用。"
