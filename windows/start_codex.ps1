$ErrorActionPreference = "Stop"
$WindowsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $WindowsDir
Set-Location $Root

$env:CODEX_PROXY_SOURCE_DIR = $Root
$env:CODEX_PROXY_CONFIG_DIR = Join-Path $env:LOCALAPPDATA "codexproxyapi"

python control_actions.py repair-open-codex
