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
    [string] $Command,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
  )

  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
  }
}

Require-Command "python" "Install Python 3.10+ and add it to PATH."
Require-Command "npm" "Install Node.js LTS and add npm to PATH."

Write-Host "[1/5] Creating Python virtual environment..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  Invoke-Checked "python" "-m" "venv" ".venv"
}
$Python = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "[2/5] Installing Python dependencies..."
Invoke-Checked $Python "-m" "pip" "install" "--upgrade" "pip"
Invoke-Checked $Python "-m" "pip" "install" "-r" "requirements.txt" "-r" "backend\requirements.txt"

$RequiredExes = @("pcd_map_cli.exe", "pcd_tile_cli.exe", "network_scan_cli.exe", "costmap_cli.exe")
$MissingExes = @($RequiredExes | Where-Object { -not (Test-Path (Join-Path $Root "cpp\build\$_")) })
if ($MissingExes.Count -gt 0) {
  Write-Host "[3/5] Building C++ CLI tools..."
  Require-Command "cmake" "Install CMake and add it to PATH, or copy a prebuilt cpp\build folder with the required CLI exes."

  $ConfigureArgs = @("-S", "cpp", "-B", "cpp\build", "-DCMAKE_BUILD_TYPE=Release")
  if (Get-Command "ninja" -ErrorAction SilentlyContinue) {
    $ConfigureArgs += @("-G", "Ninja")
  }
  Invoke-Checked "cmake" @ConfigureArgs
  Invoke-Checked "cmake" "--build" "cpp\build" "--config" "Release"

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
  Invoke-Checked "npm" "ci"
} else {
  Invoke-Checked "npm" "install"
}

Write-Host "[5/5] Building frontend..."
Invoke-Checked "npm" "run" "build"
Pop-Location

Write-Host ""
Write-Host "Local install finished."
Write-Host "Start with: .\scripts\start_local.cmd"
