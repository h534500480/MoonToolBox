$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$EmbeddedPython = Join-Path $Root "runtime\python\python.exe"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Python = $null
$BackendDir = Join-Path $Root "backend"
$LogDir = Join-Path $Root "logs"
$BackendOutLog = Join-Path $LogDir "backend.out.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$BackendUrl = "http://127.0.0.1:8000"
$HealthUrl = "$BackendUrl/api/health"

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [string] $Executable,
    [string[]] $CommandArgs = @()
  )

  & $Executable @CommandArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Executable $($CommandArgs -join ' ')"
  }
}

function Get-SystemPython {
  $Candidates = @(
    @{ Executable = "py"; Args = @("-3") },
    @{ Executable = "python"; Args = @() },
    @{ Executable = "python3"; Args = @() }
  )

  foreach ($Candidate in $Candidates) {
    if (-not (Get-Command $Candidate.Executable -ErrorAction SilentlyContinue)) {
      continue
    }

    & $Candidate.Executable @($Candidate.Args + @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)")) *> $null
    if ($LASTEXITCODE -eq 0) {
      return $Candidate
    }
  }

  throw "Python 3.10+ not found. Install Python 3.10+ and add it to PATH, then run this file again."
}

function Test-VenvPython {
  if (-not (Test-Path $VenvPython)) {
    return $false
  }

  & $VenvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
  return $LASTEXITCODE -eq 0
}

function Test-BackendDependencies {
  if (-not (Test-Path $VenvPython)) {
    return $false
  }

  & $VenvPython -c "import fastapi, uvicorn, yaml, PIL; raise SystemExit(0)" *> $null
  return $LASTEXITCODE -eq 0
}

function Test-EmbeddedPython {
  if (-not (Test-Path $EmbeddedPython)) {
    return $false
  }

  & $EmbeddedPython -c "import fastapi, uvicorn, yaml, PIL; raise SystemExit(0)" *> $null
  return $LASTEXITCODE -eq 0
}

function Initialize-PipNetwork {
  if ($env:ROS_TOOL_USE_SYSTEM_PROXY -eq "0") {
    $env:NO_PROXY = "*"
    $env:no_proxy = "*"
    $env:HTTP_PROXY = ""
    $env:HTTPS_PROXY = ""
    $env:ALL_PROXY = ""
    $env:http_proxy = ""
    $env:https_proxy = ""
    $env:all_proxy = ""
  }

  if (-not $env:ROS_TOOL_PIP_INDEX_URL) {
    $env:ROS_TOOL_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"
  }
}

function Invoke-PipInstall {
  param(
    [string[]] $PipArgs
  )

  Initialize-PipNetwork
  if ($env:ROS_TOOL_PIP_INDEX_URL) {
    $HostName = ([Uri]$env:ROS_TOOL_PIP_INDEX_URL).Host
    & $VenvPython @("-m", "pip", "install", "-i", $env:ROS_TOOL_PIP_INDEX_URL, "--trusted-host", $HostName) @PipArgs
    if ($LASTEXITCODE -eq 0) {
      return
    }
    Write-Host "Configured pip index failed. Retrying with default PyPI..."
  }

  & $VenvPython @("-m", "pip", "install") @PipArgs
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $VenvPython -m pip install $($PipArgs -join ' ')"
  }
}

function Initialize-RuntimeVenv {
  if ((Test-VenvPython) -and (Test-BackendDependencies)) {
    return
  }

  if (-not (Test-VenvPython)) {
    Write-Host "Python virtual environment is missing or not portable. Rebuilding .venv..."
  } else {
    Write-Host "Python backend dependencies are missing. Installing backend dependencies..."
  }

  if ((Test-Path ".venv") -and -not (Test-VenvPython)) {
    Remove-Item ".venv" -Recurse -Force
  }

  if (-not (Test-VenvPython)) {
    $SystemPython = Get-SystemPython
    Invoke-Checked $SystemPython.Executable @($SystemPython.Args + @("-m", "venv", ".venv"))
  }
  Invoke-PipInstall @("--upgrade", "pip")
  Invoke-PipInstall @("-r", "backend\requirements.txt")
}

if (Test-EmbeddedPython) {
  $Python = $EmbeddedPython
} else {
  Initialize-RuntimeVenv
  $Python = $VenvPython
}

if (-not (Test-Path "frontend\dist\index.html")) {
  throw "Frontend build not found. Run .\scripts\install_local.cmd first."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$env:ROS_TOOL_RELOAD = "0"

Write-Host "Starting backend..."
$BackendProcess = Start-Process `
  -FilePath $Python `
  -ArgumentList "run.py" `
  -WorkingDirectory $BackendDir `
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
