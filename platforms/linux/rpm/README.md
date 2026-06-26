# Fedora RPM

The RPM package is produced by `electron-builder` from the root `package.json`.

```sh
npm install
npm run check
python3 -m unittest tests.test_core
npm run build:linux
```

Expected RPM output:

```text
dist/electron/Dachshund-<version>-linux-x86_64.rpm
```

The package installs the Electron control center as `dachshund`. The Python
proxy runtime is bundled as an Electron resource and is copied to the user
runtime directory when the user clicks "Start or Repair".

On Fedora KDE Plasma Wayland, `/usr/bin/dachshund` starts a Python/Gio
StatusNotifier menu helper and then opens the normal Electron control center
window without creating Electron's tray or Linux application menu. The native
menu can be started directly with:

```sh
dachshund --tray
```

To manually test Electron tray support in that session:

```sh
DACHSHUND_ENABLE_TRAY=1 dachshund
```

To debug Electron's X11/Xwayland path directly:

```sh
DACHSHUND_FORCE_XWAYLAND=1 dachshund
```

Runtime paths:

```text
runtime:      ${XDG_CONFIG_HOME:-~/.config}/dachshund
systemd unit: ${XDG_CONFIG_HOME:-~/.config}/systemd/user/dachshund.service
log:          ${XDG_CONFIG_HOME:-~/.config}/dachshund/proxy.log
```

RPM metadata declares these Fedora runtime dependencies:

```text
python3
python3-aiohttp
python3-gobject
systemd
xdg-utils
```

Install and verify on Fedora:

```sh
sudo dnf install ./dist/electron/Dachshund-*-linux-x86_64.rpm
dachshund
systemctl --user status dachshund.service
curl --fail http://127.0.0.1:18800/api/health
```
