<#
功能说明：
为当前 PowerShell 会话导入 Visual Studio Build Tools 的 C++ 编译环境变量。

注意事项：
1. 该脚本不会修改系统级环境变量，只会更新当前进程及其后续子进程。
2. 主要用于让 `cmake` / `ninja` / `cl.exe` 在普通 PowerShell 中也能拿到
   `INCLUDE`、`LIB`、`LIBPATH` 等标准 C++ 编译环境。
3. 若机器上未安装 VS Build Tools 或未包含 C++ 工具链，本脚本会直接报错。
#>

[CmdletBinding()]
param(
  [string]$Arch = "amd64"
)

$ErrorActionPreference = "Stop"

function Get-VsWherePath {
  $candidate = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
  if (-not (Test-Path $candidate)) {
    throw "未找到 vswhere.exe，请先安装 Visual Studio Build Tools 2022。"
  }
  return $candidate
}

function Get-VsInstallPath {
  $vswhere = Get-VsWherePath
  $installPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
  if (-not $installPath) {
    throw "未找到包含 C++ x64/x86 工具链的 Visual Studio Build Tools 安装。"
  }
  return $installPath.Trim()
}

function Import-VsDevEnvironment {
  param(
    [Parameter(Mandatory = $true)]
    [string]$InstallPath,
    [Parameter(Mandatory = $true)]
    [string]$TargetArch
  )

  $vsDevCmd = Join-Path $InstallPath "Common7\Tools\VsDevCmd.bat"
  if (-not (Test-Path $vsDevCmd)) {
    throw "未找到 VsDevCmd.bat: $vsDevCmd"
  }

  $cmdOutput = & cmd.exe /s /c "`"$vsDevCmd`" -no_logo -arch=$TargetArch && set"
  if ($LASTEXITCODE -ne 0) {
    throw "执行 VsDevCmd.bat 失败，退出码: $LASTEXITCODE"
  }

  foreach ($line in $cmdOutput) {
    if ([string]::IsNullOrWhiteSpace($line)) {
      continue
    }
    $separatorIndex = $line.IndexOf("=")
    if ($separatorIndex -lt 1) {
      continue
    }
    $name = $line.Substring(0, $separatorIndex)
    $value = $line.Substring($separatorIndex + 1)
    Set-Item -Path "Env:$name" -Value $value
  }
}

$installPath = Get-VsInstallPath
Import-VsDevEnvironment -InstallPath $installPath -TargetArch $Arch

Write-Host "已导入 VS C++ 编译环境: $installPath ($Arch)"
