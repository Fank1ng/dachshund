# Platform Files

## Shared Core

- `src/core/proxy.py`: aiohttp management API and proxy entrypoint
- `src/core/proxy_core.py`: upstream proxy behavior
- `src/core/account_manager.py`: account storage and rotation
- `src/core/config.py`: runtime config defaults and validation

## Electron App

- `app/electron/main.js`: tray, window, IPC, and action bridge
- `app/electron/preload.js`: renderer API whitelist
- `app/electron/renderer/`: control center UI

## macOS

- `platforms/mac/control_actions.py`: JSON action layer used by Electron
- `platforms/mac/service_manager.py`: LaunchAgent and runtime sync helpers
- `platforms/mac/build_dachshund_app.command`: app and DMG build script

## Windows

- `platforms/windows/README.md`: Electron packaging placeholder
- Runtime target: `%LOCALAPPDATA%\dachshund`

## Linux

- `platforms/linux/deb/`: Debian/Ubuntu package placeholder
- `platforms/linux/rpm/`: Fedora/RHEL/openSUSE package placeholder
- Runtime target: `${XDG_CONFIG_HOME:-~/.config}/dachshund`

## Build Output

Generated files stay under `dist/` and are ignored by Git.
