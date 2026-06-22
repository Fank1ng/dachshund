# Linux

Dachshund's Linux desktop packages are reserved for future Electron packaging.

The intended package targets are:

- Debian/Ubuntu: `.deb`
- Fedora/RHEL/openSUSE: `.rpm`

Reserved platform directories:

```text
platforms/linux/deb/
platforms/linux/rpm/
```

Target runtime directory:

```text
${XDG_CONFIG_HOME:-~/.config}/dachshund
```

No Linux release artifact is produced by the current build scripts.
