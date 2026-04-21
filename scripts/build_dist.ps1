$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ReleaseRoot = Join-Path $Root "release"
$DistName = "MoonToolBox"
$DistDir = Join-Path $ReleaseRoot $DistName
$ZipPath = Join-Path $ReleaseRoot "$DistName.zip"

Set-Location $Root

function Require-Path($Path, $Hint) {
  if (-not (Test-Path $Path)) {
    throw "$Path not found. $Hint"
  }
}

function Copy-Directory($Source, $Destination) {
  Require-Path $Source "Run .\scripts\install_local.cmd first."
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Copy-Item (Join-Path $Source "*") $Destination -Recurse -Force
}

Write-Host "[1/5] Checking local build outputs..."
Require-Path ".venv\Scripts\python.exe" "Run .\scripts\install_local.cmd first."
Require-Path "frontend\dist\index.html" "Run .\scripts\install_local.cmd first."

& ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, yaml, PIL"
if ($LASTEXITCODE -ne 0) {
  throw ".venv is missing runtime Python dependencies. Run .\scripts\install_local.cmd and fix any pip errors first."
}

$RequiredExes = @("pcd_map_cli.exe", "pcd_tile_cli.exe", "network_scan_cli.exe", "costmap_cli.exe")
foreach ($ExeName in $RequiredExes) {
  Require-Path (Join-Path "cpp\build" $ExeName) "Run .\scripts\install_local.cmd first."
}

Write-Host "[2/5] Cleaning release directory..."
if (Test-Path $DistDir) {
  Remove-Item $DistDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Write-Host "[3/5] Copying runtime files..."
Copy-Directory ".venv" (Join-Path $DistDir ".venv")
Copy-Directory "backend" (Join-Path $DistDir "backend")
Copy-Directory "frontend\dist" (Join-Path $DistDir "frontend\dist")
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "cpp\build") | Out-Null
foreach ($ExeName in $RequiredExes) {
  Copy-Item (Join-Path "cpp\build" $ExeName) (Join-Path $DistDir "cpp\build") -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "scripts") | Out-Null
Copy-Item "scripts\start_local.ps1" (Join-Path $DistDir "scripts") -Force
Copy-Item "scripts\start_local.cmd" (Join-Path $DistDir "scripts") -Force
Copy-Item "README.md" $DistDir -Force
Copy-Item "LICENSE" $DistDir -Force

Write-Host "[4/5] Removing non-runtime files..."
$CleanupPaths = @(
  "backend\__pycache__",
  "backend\app\__pycache__",
  "backend\app\api\__pycache__",
  "backend\app\services\__pycache__",
  "backend\data\tool_preferences.json"
)
foreach ($RelativePath in $CleanupPaths) {
  $Target = Join-Path $DistDir $RelativePath
  if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
  }
}

Write-Host "[5/5] Creating zip..."
if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Release folder: $DistDir"
Write-Host "Release zip:    $ZipPath"
Write-Host "Start with:     $DistName\scripts\start_local.cmd"
