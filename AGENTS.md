# Dachshund — Project Overview

Local macOS control app and reverse proxy for pooling multiple ChatGPT Plus accounts with Codex.

## Architecture

```
Codex CLI → src/core/proxy.py (aiohttp, :18800) → api.openai.com / chatgpt.com
                 │
                 ├── /app        → src/core/static/index.html
                 ├── /api/*      → management REST API
                 └── /v1/*, /backend-api/* → proxy_core

dachshund.app → Electron tray/control center → platforms/mac/control_actions.py
```

## Isolation Rules

- New app bundle: `dachshund.app`.
- Bundle id: `com.fank1ng.dachshund`.
- Runtime dir: `~/Library/Application Support/dachshund`.
- LaunchAgent: `com.fank1ng.dachshund`.
- Default API: `http://127.0.0.1:18800`.
- Do not auto-import old accounts or old runtime data.
- Only write `~/.codex/config.toml` when the user enables the proxy from the app.

## Important Files

| File | Purpose |
|------|---------|
| `src/core/proxy.py` | aiohttp proxy and management API. |
| `src/core/config.py` | Config defaults and validation. |
| `platforms/mac/service_manager.py` | LaunchAgent/runtime helpers for Dachshund. |
| `platforms/mac/control_actions.py` | JSON action layer used by Electron. |
| `app/electron/main.js` | Electron tray, menu, windows, IPC. |
| `app/electron/preload.js` | Renderer API whitelist. |
| `app/electron/renderer/` | Control center UI. |
| `platforms/mac/build_dachshund_app.command` | mac app and DMG build script. |

## Build And Check

```sh
npm install
npm run check
python3 -m unittest tests.test_core
platforms/mac/build_dachshund_app.command
```

Build output stays under `dist/`:

- `dist/dachshund.app`
- `dist/dachshund-<version>-mac.dmg`

## Config Written When Enabled

```toml
openai_base_url = "http://127.0.0.1:18800/v1"
chatgpt_base_url = "http://127.0.0.1:18800"
```
