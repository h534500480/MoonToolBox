<# 功能说明：构建 Windows x64 无源码发行包，内置编译后的后端、算法与运行依赖。 #>
[CmdletBinding()]
param([string]$Python = "", [int]$Jobs = 4)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Stage = Join-Path $Root "release\ROSPlatform"
$Build = Join-Path $Root "build\desktop"

function Invoke-Checked([string]$Executable, [string[]]$CommandArgs) {
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "执行失败 ($LASTEXITCODE): $Executable $($CommandArgs -join ' ')" }
}

# 删除操作只允许在本仓库专用构建/发行目录内，拒绝路径逃逸。
function Clear-Output([string]$Target) {
    $Full = [IO.Path]::GetFullPath($Target)
    $Allowed = @((Join-Path $Root "build"), (Join-Path $Root "release"))
    if (-not ($Allowed | Where-Object { $Full.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) })) {
        throw "拒绝清理非构建路径: $Full"
    }
    if (Test-Path -LiteralPath $Full) { Remove-Item -LiteralPath $Full -Recurse -Force }
}

if (-not $Python) {
    $Python = Join-Path $Root "build\package-env\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python)) {
        Invoke-Checked "py" @("-3.12", "-m", "venv", (Join-Path $Root "build\package-env"))
    }
}
$Python = (Resolve-Path $Python).Path
Invoke-Checked $Python @("-m", "pip", "install", "-r", "scripts\requirements-package.txt")
Invoke-Checked $Python @("-c", "import sys, struct, tkinter; assert sys.version_info[:2] == (3, 12) and struct.calcsize('P') == 8, '需要 Python 3.12 x64'")

Write-Host "[1/5] 编译 Release C++ 算法（静态运行库）..."
. (Join-Path $PSScriptRoot "import_vsdev_env.ps1")
Invoke-Checked "cmake" @("-S", "cpp", "-B", "build\cpp-release", "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DROS_PLATFORM_STATIC_RUNTIME=ON")
Invoke-Checked "cmake" @("--build", "build\cpp-release", "--config", "Release", "--parallel", "$Jobs")

Write-Host "[2/5] 在独立目录构建网页资源..."
$FrontendBuild = Join-Path $Root "build\frontend-release"
Clear-Output $FrontendBuild
New-Item -ItemType Directory -Force -Path $FrontendBuild | Out-Null
foreach ($Item in @('src', 'public', 'index.html', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts')) {
    $Source = Join-Path $Root "frontend\$Item"
    if (Test-Path -LiteralPath $Source) { Copy-Item -LiteralPath $Source -Destination $FrontendBuild -Recurse }
}
Push-Location $FrontendBuild
try {
    Invoke-Checked "npm.cmd" @("ci")
    Invoke-Checked "npm.cmd" @("run", "typecheck")
    Invoke-Checked "npm.cmd" @("run", "build")
} finally { Pop-Location }

Write-Host "[3/5] 编译独立 Python 后端及托盘入口..."
$OldPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $Root "backend"
    # 保留编译缓存，但每次重新汇集运行目录，避免历史文件进入交付包。
    Clear-Output (Join-Path $Build "desktop.dist")
    Invoke-Checked $Python @("-m", "nuitka", "--mode=standalone", "--msvc=latest", "--enable-plugin=tk-inter", "--include-package=app", "--include-package=uvicorn", "--include-package=pystray", "--windows-console-mode=disable", "--output-dir=build/desktop", "--output-filename=ROSPlatform.exe", "--assume-yes-for-downloads", "--report=build/desktop-report.xml", "--jobs=$Jobs", "backend/desktop.py")
} finally { $env:PYTHONPATH = $OldPythonPath }

Write-Host "[4/5] 汇集运行文件并审计源码泄露..."
Clear-Output $Stage
New-Item -ItemType Directory -Force -Path $Stage | Out-Null
Copy-Item -LiteralPath (Join-Path $Build "desktop.dist") -Destination (Join-Path $Stage "runtime") -Recurse
# 主程序必须与其依赖处于同级，不分发构建目录或源代码。
$Runtime = Join-Path $Stage "runtime"
New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "cpp\build"), (Join-Path $Runtime "frontend") | Out-Null
foreach ($Name in @("pcd_map_cli", "pcd_tile_cli", "global_relocalization_cli", "nav_pcd_preview_cli")) {
    Copy-Item -LiteralPath (Join-Path $Root "build\cpp-release\$Name.exe") -Destination (Join-Path $Runtime "cpp\build\$Name.exe")
}
Copy-Item -LiteralPath (Join-Path $FrontendBuild "dist") -Destination (Join-Path $Runtime "frontend\dist") -Recurse
Copy-Item -LiteralPath (Join-Path $Root "LICENSE") -Destination $Stage
Copy-Item -LiteralPath (Join-Path $Root "docs\WINDOWS_DISTRIBUTION.md") -Destination (Join-Path $Stage "使用说明.md")
Invoke-Checked $Python @("scripts\package_notices.py", $Stage, $FrontendBuild)
$Leaked = @(Get-ChildItem -LiteralPath $Stage -Recurse -File | Where-Object { $_.Extension -in @('.py','.pyc','.cpp','.hpp','.pdb','.map','.ts','.vue') })
if ($Leaked.Count) { throw "发现禁止交付的源码/调试文件: $($Leaked.FullName -join ', ')" }
# Nuitka 应汇集 Python 和扩展模块运行库，缺失时拒绝生成安装包。
foreach ($Required in @('ROSPlatform.exe','python312.dll','vcruntime140.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $Runtime $Required))) { throw "缺少运行依赖: $Required" }
}

Invoke-Checked $Python @("tests\test_distribution.py", (Join-Path $Runtime "ROSPlatform.exe"))
Write-Host "[5/5] 生成便携包与校验值..."
$Zip = Join-Path $Root "release\ROSPlatform.zip"
if (Test-Path -LiteralPath $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -LiteralPath $Stage -DestinationPath $Zip
(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash | Set-Content -LiteralPath "$Zip.sha256" -Encoding ASCII
Write-Host "便携包: $Zip"
Write-Host "启动入口: $Runtime\ROSPlatform.exe"
