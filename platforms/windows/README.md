# Windows

Dachshund uses Task Scheduler for the background proxy and tray login item.

Target runtime directory:

```text
%LOCALAPPDATA%\dachshund
```

Package targets are wired through `electron-builder`:

```powershell
npm run build:win
```
