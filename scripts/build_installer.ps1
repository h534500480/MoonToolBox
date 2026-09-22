<# 功能说明：验证独立发行包后生成离线安装程序；SkipBuild 只复用已构建产物。 #>
[CmdletBinding()]
param([switch]$SkipBuild)
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
if (-not $SkipBuild) {
  & ".\scripts\build_dist.ps1"
}
if ($SkipBuild) {
  $Python = Join-Path $Root "build\package-env\Scripts\python.exe"
  & $Python "tests\test_distribution.py" "release\ROSPlatform\runtime\ROSPlatform.exe"
  if ($LASTEXITCODE -ne 0) { throw "发行包验证失败，停止生成安装程序" }
}

Write-Host "[3/3] Building installer..."
$PackageSourceDir = "..\release\ROSPlatform"
& $Iscc "/DPackageSourceDir=$PackageSourceDir" ".\scripts\installer.iss"
if ($LASTEXITCODE -ne 0) {
  throw "Inno Setup compiler failed with exit code $LASTEXITCODE"
}

Write-Host ""
(Get-FileHash -LiteralPath "release\ROSPlatformSetup.exe" -Algorithm SHA256).Hash | Set-Content -LiteralPath "release\ROSPlatformSetup.exe.sha256" -Encoding ASCII
Write-Host "Installer: release\ROSPlatformSetup.exe"
