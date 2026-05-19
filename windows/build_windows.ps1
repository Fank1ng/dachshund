param(
    [switch]$SkipPip,
    [switch]$SkipInstaller,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $WindowsDir
$Dist = Join-Path $Root "dist\windows"
$Build = Join-Path $Root "build\windows"
$Runtime = Join-Path $Dist "runtime"

Set-Location $Root

if (-not $SkipPip) {
    & $Python -m pip install -r requirements.txt pyinstaller
}

Remove-Item $Dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Dist, $Build, $Runtime | Out-Null

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Codex Proxy Control" `
    --icon "static\icons\favicon.ico" `
    --distpath $Dist `
    --workpath (Join-Path $Build "control") `
    --specpath $Build `
    "control_panel.py"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "CodexProxyService" `
    --distpath $Dist `
    --workpath (Join-Path $Build "service") `
    --specpath $Build `
    (Join-Path $WindowsDir "codex_proxy_service.py")

$RootRuntimeFiles = @(
    ".gitignore",
    "account_manager.py",
    "codex_config.py",
    "config.py",
    "config.json",
    "control_actions.py",
    "control_panel.py",
    "login_manager.py",
    "proxy.py",
    "proxy_core.py",
    "quota_tracker.py",
    "requirements.txt",
    "service_manager.py"
)

foreach ($File in $RootRuntimeFiles) {
    Copy-Item (Join-Path $Root $File) (Join-Path $Runtime $File) -Force
}

Copy-Item (Join-Path $WindowsDir "codex_proxy_service.py") (Join-Path $Runtime "codex_proxy_service.py") -Force
Copy-Item (Join-Path $Root "static") (Join-Path $Runtime "static") -Recurse -Force

Write-Host "Built portable Windows files in $Dist"

if (-not $SkipInstaller) {
    $IsccPath = $null
    $Iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($Iscc) {
        $IsccPath = $Iscc.Source
    }
    if (-not $IsccPath) {
        $Common = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        )
        foreach ($Candidate in $Common) {
            if ($Candidate -and (Test-Path $Candidate)) {
                $IsccPath = (Get-Item $Candidate).FullName
                break
            }
        }
    }

    if ($IsccPath) {
        & $IsccPath (Join-Path $WindowsDir "installer.iss") "/DSourceDir=$Dist"
        Write-Host "Built installer via Inno Setup."
    } else {
        Write-Host "Inno Setup not found. Portable files are ready; rerun without -SkipInstaller after installing Inno Setup."
    }
}
