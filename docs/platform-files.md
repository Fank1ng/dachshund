# Platform File Layout

This repository is organized into shared proxy code and platform-specific app
packaging code.

## Shared proxy core

Shared code lives in `src/core/`:

- `src/core/proxy.py`
- `src/core/proxy_core.py`
- `src/core/account_manager.py`
- `src/core/quota_tracker.py`
- `src/core/config.py`
- `src/core/codex_config.py`
- `src/core/login_manager.py`
- `src/core/static/`

## macOS app and helpers

macOS-only app and packaging files live in `platforms/mac/`:

- `platforms/mac/ControlApp.m`
- `platforms/mac/service_manager.py`
- `platforms/mac/control_actions.py`
- `platforms/mac/control_panel.py`
- `platforms/mac/build_control_app.command`
- `platforms/mac/build_dmg.command`
- `platforms/mac/setup_proxy.command`
- `platforms/mac/start_codex.command`
- `platforms/mac/open_web.command`

## Windows work area

Windows-only files live in `platforms/windows/`. Do not copy generated app
bundles, Python frameworks, vendored dependency trees, build outputs, account
data, or token files into this directory.

Windows packaging uses PyInstaller for executables and Inno Setup for the
installer.

## Documentation

Cross-platform and Windows-specific docs live in `docs/`.

- `docs/windows11.md` documents the Windows packaging and usage path.
- `docs/platform-files.md` documents this platform classification.

## Future migration

Root-level `accounts/`, `config.json`, and `recent_requests.json` are runtime
data when running from source. They are intentionally separate from `src/core/`
so source files can move without relocating local account data.
