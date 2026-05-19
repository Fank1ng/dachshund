# Windows Work Area

This directory contains Windows-only packaging and helper files. The stable
shared proxy source still lives at the repository root.

The Windows installer path uses PyInstaller for the GUI and background
supervisor, plus Inno Setup for the user-level installer. Keep Windows app
code, PowerShell scripts, installer definitions, and Windows-specific
service/task helpers here.

Do not add generated installers, portable builds, copied runtimes, `vendor/`,
Python framework folders, account data, logs, or token files.
