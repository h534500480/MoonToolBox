$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$BackendUrl = "http://127.0.0.1:8000"
$HealthUrl = "$BackendUrl/api/health"

if (-not (Test-Path $Python)) {
  throw "Python virtual environment not found. Run .\scripts\install_local.cmd first."
}

if (-not (Test-Path "frontend\dist\index.html")) {
  throw "Frontend build not found. Run .\scripts\install_local.cmd first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:ROS_TOOL_RELOAD = "0"

Write-Host "Starting backend..."
$BackendProcess = Start-Process `
  -FilePath $Python `
  -ArgumentList "backend\run.py" `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $BackendOutLog `
  -RedirectStandardError $BackendErrLog `
  -PassThru

for ($Attempt = 1; $Attempt -le 30; $Attempt++) {
  if ($BackendProcess.HasExited) {
    Write-Host "Backend exited early. Log:"
    Get-Content $BackendOutLog -ErrorAction SilentlyContinue
    Get-Content $BackendErrLog -ErrorAction SilentlyContinue
    exit $BackendProcess.ExitCode
  }

  try {
    $Response = Invoke-WebRequest -UseBasicParsing $HealthUrl -TimeoutSec 1
    if ($Response.StatusCode -eq 200) {
      Write-Host "Backend ready: $BackendUrl"
      Start-Process $BackendUrl
      Write-Host "Keep this window open while using MoonToolBox."
      Wait-Process -Id $BackendProcess.Id
      exit $LASTEXITCODE
    }
  } catch {
    Start-Sleep -Milliseconds 500
  }
}

Write-Host "Backend did not become ready. Log:"
Get-Content $BackendOutLog -ErrorAction SilentlyContinue
Get-Content $BackendErrLog -ErrorAction SilentlyContinue
exit 1
