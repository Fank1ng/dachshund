param(
    [string]$Version = "0.6.8",
    [switch]$SkipPip,
    [switch]$SkipInstaller,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent (Split-Path -Parent $WindowsDir)
$CoreDir = Join-Path $Root "src\core"
$Dist = Join-Path $Root "dist\windows"
$Build = Join-Path $Root "build\windows"
$Runtime = Join-Path $Dist "runtime"
$Vendor = Join-Path $Runtime "vendor"
$IconPath = Join-Path $CoreDir "static\icons\favicon.ico"
$ServiceCollectModules = @(
    "asyncio",
    "aiohappyeyeballs",
    "aiohttp",
    "aiosignal",
    "attrs",
    "frozenlist",
    "multidict",
    "propcache",
    "yarl"
)
$ServiceCollectArgs = foreach ($Module in $ServiceCollectModules) {
    "--collect-submodules"
    $Module
}

Set-Location $Root

function Assert-NativeCommandSucceeded {
    param([string]$CommandName)
    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE"
    }
}

function Assert-CleanPackageTree {
    param([string]$Path)
    $Forbidden = Get-ChildItem -Path $Path -Recurse -Force -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "auth.json" -or
        $_.Name -eq ".env" -or
        $_.Name -eq "quota.json" -or
        $_.Extension -eq ".docx" -or
        $_.FullName -match "\\Codex Proxy Control\.app(\\|$)" -or
        $_.FullName -match "\\runtime\\python(\\|$)" -or
        $_.FullName -match "\\accounts\\[^\\]+\\auth\.json$"
    } | Select-Object -First 1

    if ($Forbidden) {
        throw "Refusing to package forbidden file or directory: $($Forbidden.FullName)"
    }
}

if (-not $SkipPip) {
    & $Python -m pip install -r requirements.txt pyinstaller
    Assert-NativeCommandSucceeded "pip install"
}

Remove-Item $Dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Build -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Dist, $Build, $Runtime | Out-Null

if (-not $SkipPip) {
    & $Python -m pip install --upgrade --target $Vendor -r requirements.txt
    Assert-NativeCommandSucceeded "pip vendor install"
    & icacls $Vendor /reset /T /C | Out-Null
    Assert-NativeCommandSucceeded "vendor ACL reset"
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "Codex Proxy Control" `
    --icon $IconPath `
    --distpath $Dist `
    --workpath (Join-Path $Build "control") `
    --specpath $Build `
    --paths $CoreDir `
    --paths $WindowsDir `
    (Join-Path $WindowsDir "win_control_app.py")
Assert-NativeCommandSucceeded "PyInstaller control build"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "CodexProxyService" `
    --distpath $Dist `
    --workpath (Join-Path $Build "service") `
    --specpath $Build `
    --paths $CoreDir `
    --paths $WindowsDir `
    @ServiceCollectArgs `
    (Join-Path $WindowsDir "codex_proxy_service.py")
Assert-NativeCommandSucceeded "PyInstaller service build"

$RootRuntimeFiles = @(
    "account_manager.py",
    "codex_cli.py",
    "codex_config.py",
    "config.py",
    "config.json",
    "login_manager.py",
    "proxy.py",
    "proxy_core.py",
    "quota_tracker.py",
    "requirements.txt"
)

foreach ($File in $RootRuntimeFiles) {
    if ($File -eq "requirements.txt") {
        Copy-Item (Join-Path $Root $File) (Join-Path $Runtime $File) -Force
    } else {
        Copy-Item (Join-Path $CoreDir $File) (Join-Path $Runtime $File) -Force
    }
}

Copy-Item (Join-Path $WindowsDir "codex_proxy_service.py") (Join-Path $Runtime "codex_proxy_service.py") -Force
Copy-Item (Join-Path $WindowsDir "win_service_manager.py") (Join-Path $Runtime "win_service_manager.py") -Force
Copy-Item (Join-Path $WindowsDir "win_service_manager.py") (Join-Path $Runtime "service_manager.py") -Force
Copy-Item (Join-Path $CoreDir "static") (Join-Path $Runtime "static") -Recurse -Force
Assert-CleanPackageTree -Path $Runtime

Write-Host "Built portable Windows files in $Dist"

if (-not $SkipInstaller) {
    $IsccPath = $null
    $Iscc = Get-Command "iscc.exe" -ErrorAction SilentlyContinue
    if ($Iscc) {
        $IsccPath = $Iscc.Source
    }
    if (-not $IsccPath) {
        $Common = @(
            (Join-Path $env:LOCALAPPDATA "Programs\Inno\ISCC.exe"),
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
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
        & $IsccPath (Join-Path $WindowsDir "installer.iss") "/DSourceDir=$Dist" "/DMyAppVersion=$Version"
        Assert-NativeCommandSucceeded "Inno Setup build"
        Write-Host "Built installer via Inno Setup."
    } else {
        Write-Host "Inno Setup not found. Portable files are ready; rerun without -SkipInstaller after installing Inno Setup."
    }
}
