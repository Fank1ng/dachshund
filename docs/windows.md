# Windows

Dachshund's public app surface is Electron-only.

The current public tree keeps shared Python core code and the Electron UI. The
old native Windows control app and installer pipeline were removed. Windows
Electron packaging can be added on top of:

- `src/core/`
- `app/electron/`
- `platforms/windows/`
- `%LOCALAPPDATA%\dachshund`

No Windows release artifact is produced by the current build scripts.
