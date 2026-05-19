# Platform File Layout

This repository is in a transition period from a mature macOS app to a
cross-platform app. For now, the stable source layout stays in place and new
Windows work is isolated under `windows/`.

## Shared proxy core

These files remain at the repository root because the current macOS app,
command shortcuts, tests, and packaging scripts already depend on these paths:

- `proxy.py`
- `proxy_core.py`
- `account_manager.py`
- `quota_tracker.py`
- `config.py`
- `codex_config.py`
- `login_manager.py`
- `requirements.txt`
- `static/`

## macOS app and helpers

The existing macOS app remains at the repository root to avoid disturbing the
working release pipeline:

- `ControlApp.m`
- `service_manager.py`
- `control_actions.py`
- `control_panel.py`
- `build_control_app.command`
- `build_dmg.command`
- `setup_proxy.command`
- `start_codex.command`
- `open_web.command`

## Windows work area

Windows-only files should live in `windows/`. Do not copy generated app
bundles, Python frameworks, vendored dependency trees, build outputs, account
data, or token files into this directory.

The current files in `windows/` are migrated from the older experimental
Windows folder as a starting point. They should be adapted against the current
root source before being treated as a finished Windows release path.

## Documentation

Cross-platform and Windows-specific docs live in `docs/`.

- `docs/windows11.md` documents the Windows packaging and usage path.
- `docs/platform-files.md` documents the temporary platform classification.

## Future migration

After the Windows app is stable, a second pass can move files into a stricter
layout such as `src/`, `mac/`, and `windows/`. That migration should update
imports, packaging scripts, tests, and docs in one dedicated change.
