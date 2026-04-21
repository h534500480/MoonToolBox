$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Require-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name not found. $InstallHint"
  }
}

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

function Initialize-PipNetwork {
  if ($env:ROS_TOOL_USE_SYSTEM_PROXY -ne "1") {
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

Require-Command "python" "Install Python 3.10+ and add it to PATH."
Require-Command "npm.cmd" "Install Node.js LTS and add npm to PATH."
Initialize-PipNetwork

Write-Host "[1/5] Creating Python virtual environment..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Invoke-Checked "python" @("-m", "venv", ".venv")
}
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "[2/5] Installing Python dependencies..."
Invoke-Checked $Python @("-m", "pip", "install", "-i", $env:ROS_TOOL_PIP_INDEX_URL, "--trusted-host", ([Uri]$env:ROS_TOOL_PIP_INDEX_URL).Host, "--upgrade", "pip")
Invoke-Checked $Python @("-m", "pip", "install", "-i", $env:ROS_TOOL_PIP_INDEX_URL, "--trusted-host", ([Uri]$env:ROS_TOOL_PIP_INDEX_URL).Host, "-r", "requirements.txt", "-r", "backend\requirements.txt")

$RequiredExes = @("pcd_map_cli.exe", "pcd_tile_cli.exe", "network_scan_cli.exe", "costmap_cli.exe")
$MissingExes = @($RequiredExes | Where-Object { -not (Test-Path (Join-Path $Root "cpp\build\$_")) })
if ($MissingExes.Count -gt 0) {
  Write-Host "[3/5] Building C++ CLI tools..."
  Require-Command "cmake" "Install CMake and add it to PATH, or copy a prebuilt cpp\build folder with the required CLI exes."

  $ConfigureArgs = @("-S", "cpp", "-B", "cpp\build", "-DCMAKE_BUILD_TYPE=Release")
  if (Get-Command "ninja" -ErrorAction SilentlyContinue) {
    $ConfigureArgs += @("-G", "Ninja")
  }
  Invoke-Checked "cmake" $ConfigureArgs
  Invoke-Checked "cmake" @("--build", "cpp\build", "--config", "Release")

  foreach ($ExeName in $RequiredExes) {
    $Exe = Get-ChildItem "cpp\build" -Recurse -Filter $ExeName | Select-Object -First 1
    if (-not $Exe) {
      throw "Build finished, but $ExeName was not found under cpp\build."
    }
    $Target = Join-Path $Root "cpp\build\$ExeName"
    if ($Exe.FullName -ne $Target) {
      Copy-Item $Exe.FullName $Target -Force
    }
  }
} else {
  Write-Host "[3/5] C++ CLI tools already exist; skipping CMake build."
}

Write-Host "[4/5] Installing frontend dependencies..."
Push-Location "frontend"
if (Test-Path "package-lock.json") {
  Invoke-Checked "npm.cmd" @("ci")
} else {
  Invoke-Checked "npm.cmd" @("install")
}

Write-Host "[5/5] Building frontend..."
Invoke-Checked "npm.cmd" @("run", "build")
Pop-Location

Write-Host ""
Write-Host "Local install finished."
Write-Host "Start with: .\scripts\start_local.cmd"
