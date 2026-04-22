$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Get-InnoCompiler {
  $Command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
  if ($Command) {
    return $Command.Source
  }

  $RegistryKeys = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
  )

  foreach ($RegistryKey in $RegistryKeys) {
    $Install = Get-ItemProperty $RegistryKey -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -like "Inno Setup*" -and $_.InstallLocation } |
      Select-Object -First 1

    if ($Install) {
      $Candidate = Join-Path $Install.InstallLocation "ISCC.exe"
      if (Test-Path $Candidate) {
        return $Candidate
      }
    }
  }

  $Candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 5\ISCC.exe"
  )

  foreach ($Candidate in $Candidates) {
    if ($Candidate -and (Test-Path $Candidate)) {
      return $Candidate
    }
  }

  throw "ISCC.exe not found. Install Inno Setup 6, then run this script again: https://jrsoftware.org/isinfo.php"
}

Write-Host "[1/3] Checking Inno Setup compiler..."
$Iscc = Get-InnoCompiler

Write-Host "[2/3] Building portable release folder..."
& ".\scripts\build_dist.ps1"
if ($LASTEXITCODE -ne 0) {
  throw "build_dist.ps1 failed with exit code $LASTEXITCODE"
}

Write-Host "[3/3] Building installer..."
& $Iscc ".\scripts\installer.iss"
if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Installer: release\MoonToolBoxSetup.exe"
