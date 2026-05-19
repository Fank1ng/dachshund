# Changelog

## 0.5.0 - 2026-05-20

- Added the first Windows 11 installer path using PyInstaller and Inno Setup.
- Added a Windows Scheduled Task service helper for user-level background startup.
- Added a minimal Windows control app for starting, stopping, restarting, opening the Web UI, opening logs, and toggling Codex proxy mode.
- Updated Windows PowerShell helper scripts to use the Windows service CLI instead of macOS LaunchAgent actions.
- Added packaging guards to reject credentials, `.docx` files, macOS app bundles, and copied runtime dependency trees.
- Updated Windows documentation for the `0.5.0` installer build flow.
