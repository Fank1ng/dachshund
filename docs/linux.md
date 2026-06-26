# Linux

Dachshund ships a Fedora-oriented Electron desktop package and runs the proxy as
a user-level systemd service. The desktop app is the control center; the proxy
continues to run through `systemd --user` after the window is closed.

## Build

Install the build toolchain and Python runtime dependencies:

```sh
sudo dnf install nodejs npm python3 python3-aiohttp rpm-build
npm install
npm run check
python3 -m unittest tests.test_core
npm run build:linux
```

RPM artifacts are written to `dist/electron/`, for example:

```text
dist/electron/Dachshund-0.1.1-linux-x86_64.rpm
```

## Install On Fedora

```sh
sudo dnf install ./dist/electron/Dachshund-*-linux-x86_64.rpm
```

Launch Dachshund from the desktop app grid or run:

```sh
dachshund
```

On GNOME/Wayland, tray icons may require a shell extension. On KDE Plasma
Wayland, `/usr/bin/dachshund` starts a Python/Gio StatusNotifier menu helper and
then opens the normal Electron control center window without creating Electron's
tray or Linux application menu. The main control center UI remains Electron;
only the system tray/menu is native on that session because Electron's tray and
application-menu integration can crash inside the KDE Wayland desktop path.

Autostart uses:

```sh
dachshund --tray
```

The native menu includes Open Control Center, Start/Repair, Restart Proxy, Codex
Proxy, Codex Direct, Open Web UI, Open Log, and Quit Menu.

To manually test Electron tray behavior after Electron or desktop updates:

```sh
DACHSHUND_ENABLE_TRAY=1 dachshund
```

To debug Electron's X11/Xwayland path directly:

```sh
DACHSHUND_FORCE_XWAYLAND=1 dachshund
```

This is only a diagnostic escape hatch; the packaged `dachshund` launcher is
the recommended entry point.

## Runtime Paths

Default paths:

```text
runtime:        ${XDG_CONFIG_HOME:-~/.config}/dachshund
systemd unit:   ${XDG_CONFIG_HOME:-~/.config}/systemd/user/dachshund.service
log file:       ${XDG_CONFIG_HOME:-~/.config}/dachshund/proxy.log
tray autostart: ${XDG_CONFIG_HOME:-~/.config}/autostart/dachshund.desktop
Codex config:   ~/.codex/config.toml
```

Clicking "Start or Repair" in the app syncs the packaged Python runtime into the
runtime directory, writes the user service, reloads `systemd --user`, and starts
the proxy.

## Service Commands

```sh
systemctl --user status dachshund.service
systemctl --user restart dachshund.service
systemctl --user stop dachshund.service
journalctl --user -u dachshund.service -f
```

The local proxy listens on:

```text
http://127.0.0.1:18800
```

The bundled web UI is available at:

```text
http://127.0.0.1:18800/app
```

## Codex Proxy Toggle

Dachshund only writes `~/.codex/config.toml` when the user enables Codex proxy
mode from the app. Enabling writes local provider settings for:

```toml
openai_base_url = "http://127.0.0.1:18800/v1"
chatgpt_base_url = "http://127.0.0.1:18800"
```

Disabling comments Dachshund-managed settings back out and leaves a timestamped
backup beside `~/.codex/config.toml`.

## Uninstall

Stop and disable the user service first:

```sh
systemctl --user disable --now dachshund.service
rm -f ~/.config/systemd/user/dachshund.service
systemctl --user daemon-reload
```

Then remove the package:

```sh
sudo dnf remove dachshund
```

Runtime data is intentionally left behind. Remove it manually only when account
tokens, logs, and local configuration are no longer needed:

```sh
rm -rf ~/.config/dachshund
rm -f ~/.config/autostart/dachshund.desktop
```

## Troubleshooting

If the proxy does not start, open the app and click "Start or Repair". If it
still fails, check:

```sh
systemctl --user status dachshund.service
journalctl --user -u dachshund.service -n 100
tail -n 100 ~/.config/dachshund/proxy.log
```

If `python3-aiohttp` is missing:

```sh
sudo dnf install python3-aiohttp
```
