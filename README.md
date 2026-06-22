# Dachshund

Dachshund is a local Electron control app and Python reverse proxy for using a
pool of ChatGPT Plus accounts with Codex.

Dachshund 是一个本地 Electron 控制端和 Python 反向代理，用来让 Codex 使用多个
ChatGPT Plus 账号池。

## Status

- UI: Electron
- Core: Python / aiohttp
- Supported runtime today: macOS
- Windows and Linux packaging directories are reserved for Electron packages.

## Layout

```text
app/electron/          Electron desktop app
src/core/              Shared proxy, account, config, and runtime code
platforms/mac/         macOS LaunchAgent helpers and app packaging
platforms/windows/     Windows Electron packaging placeholder
platforms/linux/deb/   Debian/Ubuntu package placeholder
platforms/linux/rpm/   Fedora/RHEL/openSUSE package placeholder
docs/                  User and platform docs
tests/                 Python unit tests
```

## Quick Start

```sh
npm install
npm start
```

The app talks to the local proxy at:

```text
http://127.0.0.1:18800
```

When enabled, Dachshund writes Codex settings to `~/.codex/config.toml`:

```toml
openai_base_url = "http://127.0.0.1:18800/v1"
chatgpt_base_url = "http://127.0.0.1:18800"
```

## Build And Check

```sh
npm run check
npm test
platforms/mac/build_dachshund_app.command
```

Build output stays under `dist/` and is ignored by Git.

## Runtime Paths

- macOS runtime: `~/Library/Application Support/dachshund`
- macOS LaunchAgent: `~/Library/LaunchAgents/com.fank1ng.dachshund.plist`
- macOS app bundle: `dachshund.app`
- Windows target runtime: `%LOCALAPPDATA%\dachshund`

## Docs

- [中文用户指南](docs/user-guide.zh.md)
- [English user guide](docs/user-guide.en.md)
- [Platform files](docs/platform-files.md)
- [Linux packaging](docs/linux.md)

## Privacy

Account tokens live in the local runtime directory. Do not commit `accounts/`,
runtime data, logs, app bundles, installers, DMGs, or files from `dist/`.

账号令牌只应保存在本机运行目录。不要提交 `accounts/`、runtime 数据、日志、
app bundle、安装包、DMG 或 `dist/` 下的构建产物。

## License

MIT
