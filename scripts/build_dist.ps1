$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$ReleaseRoot = Join-Path $Root "release"
$DistName = "MoonToolBox"
$DistDir = Join-Path $ReleaseRoot $DistName
$StageRoot = Join-Path $ReleaseRoot "_staging"
$StageDir = Join-Path $StageRoot $DistName
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

function Require-Command($Name, $InstallHint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name not found. $InstallHint"
  }
}

function Copy-Directory($Source, $Destination) {
  Require-Path $Source "Run .\scripts\install_local.cmd first."
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  Copy-Item (Join-Path $Source "*") $Destination -Recurse -Force
}

function Remove-PathWithRetry {
  param(
    [Parameter(Mandatory = $true)]
    [string] $Path,
    [int] $MaxAttempts = 5,
    [int] $DelayMs = 800
  )

  for ($Attempt = 1; $Attempt -le $MaxAttempts; $Attempt++) {
    try {
      if (-not (Test-Path $Path)) {
        return $true
      }
      Remove-Item $Path -Recurse -Force -ErrorAction Stop
      return $true
    } catch {
      if ($Attempt -ge $MaxAttempts) {
        Write-Warning "Failed to remove path after ${MaxAttempts} attempts: $Path`n$($_.Exception.Message)"
        return $false
      }
      Start-Sleep -Milliseconds $DelayMs
    }
  }

  return $false
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
  Invoke-Checked $RuntimePython @("-c", "import fastapi, uvicorn, yaml, PIL, websockets, pystray")
}

function Build-Frontend {
  Require-Command "npm.cmd" "Install Node.js LTS and add npm to PATH, then run this script again."

  Push-Location "frontend"
  try {
    if (-not (Test-Path "node_modules")) {
      Write-Host "Frontend node_modules not found; installing dependencies..."
      if (Test-Path "package-lock.json") {
        Invoke-Checked "npm.cmd" @("ci")
      } else {
        Invoke-Checked "npm.cmd" @("install")
      }
    }

    Invoke-Checked "npm.cmd" @("run", "build")
  } finally {
    Pop-Location
  }
}

Write-Host "[1/7] Checking local runtime outputs..."
Require-Path ".venv\Scripts\python.exe" "Run .\scripts\install_local.cmd first."

& ".venv\Scripts\python.exe" -c "import fastapi, uvicorn, yaml, PIL, websockets, pystray"
if ($LASTEXITCODE -ne 0) {
  throw ".venv is missing runtime Python dependencies. Run .\scripts\install_local.cmd and fix any pip errors first."
}

$RequiredExes = @("pcd_map_cli.exe", "pcd_tile_cli.exe", "global_relocalization_cli.exe", "nav_pcd_preview_cli.exe", "network_scan_cli.exe", "costmap_cli.exe")
foreach ($ExeName in $RequiredExes) {
  Require-Path (Join-Path "cpp\build" $ExeName) "Run .\scripts\install_local.cmd first."
}

Write-Host "[2/7] Building frontend..."
Build-Frontend
Require-Path "frontend\dist\index.html" "Frontend build did not produce frontend\dist\index.html."

Write-Host "[3/7] Cleaning release directory..."
if (Test-Path $StageDir) {
  [void](Remove-PathWithRetry -Path $StageDir)
}
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

Write-Host "[4/7] Copying app runtime files..."
Copy-Directory "backend" (Join-Path $StageDir "backend")
Copy-Directory "data" (Join-Path $StageDir "data")
Copy-Directory "frontend\dist" (Join-Path $StageDir "frontend\dist")
New-Item -ItemType Directory -Force -Path (Join-Path $StageDir "cpp\build") | Out-Null
foreach ($ExeName in $RequiredExes) {
  Copy-Item (Join-Path "cpp\build" $ExeName) (Join-Path $StageDir "cpp\build") -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $StageDir "output_nav\recordings") | Out-Null

New-Item -ItemType Directory -Force -Path (Join-Path $StageDir "scripts") | Out-Null
Copy-Item "scripts\start_local.ps1" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\start_local.cmd" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\start_local.vbs" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\stop_local.ps1" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\stop_local.cmd" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\tray_launcher.py" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\diagnose_mtslash.py" (Join-Path $StageDir "scripts") -Force
Copy-Item "scripts\diagnose_mtslash.cmd" (Join-Path $StageDir "scripts") -Force
if (Test-Path "assets\icons\runtime\setup.ico") {
  Copy-Item "assets\icons\runtime\setup.ico" (Join-Path $StageDir "MoonToolBox.ico") -Force
  Copy-Item "assets\icons\runtime\setup.ico" (Join-Path $ReleaseRoot "MoonToolBoxSetup.ico") -Force
} elseif (Test-Path "assets\icons\runtime\moontoolbox.ico") {
  Copy-Item "assets\icons\runtime\moontoolbox.ico" (Join-Path $StageDir "MoonToolBox.ico") -Force
}
Copy-Item "requirements.txt" $StageDir -Force
Copy-Item "README.md" $StageDir -Force
Copy-Item "LICENSE" $StageDir -Force

Write-Host "[5/7] Installing embedded Python runtime..."
Install-EmbeddedPython (Join-Path $StageDir "runtime\python")

Write-Host "[6/7] Removing non-runtime files..."
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
  $Target = Join-Path $StageDir $RelativePath
  if (Test-Path $Target) {
    [void](Remove-PathWithRetry -Path $Target)
  }
}

Write-Host "[7/7] Creating zip..."
if (Test-Path $ZipPath) {
  Remove-Item $ZipPath -Force
}
Compress-Archive -Path $StageDir -DestinationPath $ZipPath -Force

if (Test-Path $DistDir) {
  [void](Remove-PathWithRetry -Path $DistDir)
}
try {
  Copy-Item $StageDir $DistDir -Recurse -Force -ErrorAction Stop
} catch {
  Write-Warning "Failed to refresh canonical release folder: $DistDir`n$($_.Exception.Message)"
  Write-Warning "Portable folder remains available at: $StageDir"
}

Write-Host ""
Write-Host "Release folder: $DistDir"
Write-Host "Staging folder: $StageDir"
Write-Host "Release zip:    $ZipPath"
Write-Host "Start with:     $DistName\scripts\start_local.vbs"
