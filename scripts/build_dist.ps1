$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ReleaseRoot = Join-Path $Root "release"
$DistName = "MoonToolBox"
$DistDir = Join-Path $ReleaseRoot $DistName
$ZipPath = Join-Path $ReleaseRoot "$DistName.zip"
$PythonVersion = if ($env:ROS_TOOL_EMBED_PYTHON_VERSION) { $env:ROS_TOOL_EMBED_PYTHON_VERSION } else { "3.12.10" }
$PythonZipName = "python-$PythonVersion-embed-amd64.zip"
$PythonZipUrl = "https://www.python.org/ftp/python/$PythonVersion/$PythonZipName"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$DownloadDir = Join-Path $Root "build\downloads"

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

function Get-Download($Url, $Path) {
  if (Test-Path $Path) {
    return
  }

  New-Item -ItemType Directory -Force -Path (Split-Path $Path -Parent) | Out-Null
  Write-Host "Downloading $Url"
  Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path
}

function Enable-EmbeddedPythonSitePackages($PythonDir) {
  $PthFile = Get-ChildItem $PythonDir -Filter "python*._pth" | Select-Object -First 1
  if (-not $PthFile) {
    throw "Embedded Python ._pth file was not found under $PythonDir."
  }

  $Lines = @(Get-Content $PthFile.FullName)
  $Lines = @($Lines | ForEach-Object {
    if ($_ -eq "#import site") { "import site" } else { $_ }
  })

  if ($Lines -notcontains "Lib\site-packages") {
    $Lines += "Lib\site-packages"
  }

  Set-Content -Path $PthFile.FullName -Value $Lines -Encoding ASCII
}

function Install-EmbeddedPython($Destination) {
  $PythonZip = Join-Path $DownloadDir $PythonZipName
  $GetPip = Join-Path $DownloadDir "get-pip.py"

  Get-Download $PythonZipUrl $PythonZip
  Get-Download $GetPipUrl $GetPip

  if (Test-Path $Destination) {
    Remove-Item $Destination -Recurse -Force
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Expand-Archive -Path $PythonZip -DestinationPath $Destination -Force
  Enable-EmbeddedPythonSitePackages $Destination

  $RuntimePython = Join-Path $Destination "python.exe"
  Invoke-Checked $RuntimePython @($GetPip, "--no-warn-script-location")
  Invoke-Checked $RuntimePython @("-m", "pip", "install", "--no-warn-script-location", "--upgrade", "pip")
  Invoke-Checked $RuntimePython @("-m", "pip", "install", "--no-warn-script-location", "-r", "backend\requirements.txt")
  Invoke-Checked $RuntimePython @("-c", "import fastapi, uvicorn, yaml, PIL, websockets")
}

Write-Host "[1/6] Checking local build outputs..."
Require-Path ".venv\Scripts\python.exe" "Run .\scripts\install_local.cmd first."
Require-Path "frontend\dist\index.html" "Run .\scripts\install_local.cmd first."

& ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, yaml, PIL, websockets"
if ($LASTEXITCODE -ne 0) {
  throw ".venv is missing runtime Python dependencies. Run .\scripts\install_local.cmd and fix any pip errors first."
}

$RequiredExes = @("pcd_map_cli.exe", "pcd_tile_cli.exe", "network_scan_cli.exe", "costmap_cli.exe")
foreach ($ExeName in $RequiredExes) {
  Require-Path (Join-Path "cpp\build" $ExeName) "Run .\scripts\install_local.cmd first."
}

Write-Host "[2/6] Cleaning release directory..."
if (Test-Path $DistDir) {
  Remove-Item $DistDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

Write-Host "[3/6] Copying app runtime files..."
Copy-Directory "backend" (Join-Path $DistDir "backend")
Copy-Directory "frontend\dist" (Join-Path $DistDir "frontend\dist")
New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "cpp\build") | Out-Null
foreach ($ExeName in $RequiredExes) {
  Copy-Item (Join-Path "cpp\build" $ExeName) (Join-Path $DistDir "cpp\build") -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $DistDir "scripts") | Out-Null
Copy-Item "scripts\start_local.ps1" (Join-Path $DistDir "scripts") -Force
Copy-Item "scripts\start_local.cmd" (Join-Path $DistDir "scripts") -Force
Copy-Item "scripts\diagnose_mtslash.py" (Join-Path $DistDir "scripts") -Force
Copy-Item "scripts\diagnose_mtslash.cmd" (Join-Path $DistDir "scripts") -Force
Copy-Item "requirements.txt" $DistDir -Force
Copy-Item "README.md" $DistDir -Force
Copy-Item "LICENSE" $DistDir -Force

Write-Host "[4/6] Installing embedded Python runtime..."
Install-EmbeddedPython (Join-Path $DistDir "runtime\python")

Write-Host "[5/6] Removing non-runtime files..."
$CleanupPaths = @(
  "backend\__pycache__",
  "backend\app\__pycache__",
  "backend\app\api\__pycache__",
  "backend\app\services\__pycache__",
  "backend\data\_debug",
  "backend\data\browser_profiles",
  "backend\data\tool_preferences.json"
)
foreach ($RelativePath in $CleanupPaths) {
  $Target = Join-Path $DistDir $RelativePath
  if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
  }
}

Write-Host "[6/6] Creating zip..."
if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}
Compress-Archive -Path $DistDir -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Release folder: $DistDir"
Write-Host "Release zip:    $ZipPath"
Write-Host "Start with:     $DistName\scripts\start_local.cmd"
