$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
  throw "Python virtual environment not found. Run .\scripts\install_local.cmd first."
}

if (-not (Test-Path "frontend\dist\index.html")) {
  throw "Frontend build not found. Run .\scripts\install_local.cmd first."
}

$env:ROS_TOOL_RELOAD = "0"
Start-Process "http://127.0.0.1:8000"
& $Python backend\run.py
