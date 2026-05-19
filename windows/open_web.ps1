$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $WindowsDir
Set-Location $Root

$env:CODEX_PROXY_SOURCE_DIR = $Root
$env:CODEX_PROXY_CONFIG_DIR = Join-Path $env:LOCALAPPDATA "codexproxyapi"
$Service = Join-Path $WindowsDir "codex_proxy_service.py"

python $Service --install
Start-Process "http://127.0.0.1:8800/app"
