# 功能说明：关闭 MoonToolBox 托盘和后端进程，用于手动完整退出程序。

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$StatePath = Join-Path $Root "logs\tray_state.json"

function Stop-ProcessIfExists {
  param(
    [Parameter(Mandatory = $false)]
    [Nullable[int]] $ProcessId
  )

  if (-not $ProcessId) {
    return
  }

  $Process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if (-not $Process) {
    return
  }

  Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $StatePath)) {
  Write-Host "MoonToolBox is not running, or the tray state file is missing."
  exit 0
}

$State = Get-Content $StatePath -Raw | ConvertFrom-Json
Stop-ProcessIfExists $State.tray_pid
Start-Sleep -Milliseconds 300
Stop-ProcessIfExists $State.backend_pid

if (Test-Path $StatePath) {
  Remove-Item $StatePath -Force
}

Write-Host "MoonToolBox has been stopped."
