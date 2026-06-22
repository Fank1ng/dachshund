# Linux

Dachshund uses a user-level systemd service for the background proxy:

- service: `~/.config/systemd/user/dachshund.service`
- runtime: `${XDG_CONFIG_HOME:-~/.config}/dachshund`
- tray autostart: `~/.config/autostart/dachshund.desktop`

Package targets are wired through `electron-builder`:

```sh
npm run build:linux
```
