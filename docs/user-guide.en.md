# Dachshund User Guide

## Install

Download `dachshund-<version>-mac.dmg` and drag `dachshund.app` to
Applications.

If macOS blocks the app because it is not notarized, right-click
`dachshund.app` and choose Open.

## Start The Proxy

Open Dachshund and click Start / Repair. It prepares:

- Runtime directory: `~/Library/Application Support/dachshund`
- LaunchAgent: `~/Library/LaunchAgents/com.fank1ng.dachshund.plist`
- Local API: `http://127.0.0.1:18800`

## Add Accounts

In the Accounts tab, enter an account name and choose:

- Start Login: opens the Codex login flow
- Import Current Codex Account: imports an existing local Codex login
- Scan: refreshes the account list

Account tokens stay in the local runtime directory and must not be committed.

## Enable Codex Proxy

In the Config tab, click Enable Codex Proxy. Dachshund writes
`~/.codex/config.toml` so Codex uses the local proxy.

Click Codex Direct to restore direct mode.

## Daily Use

1. Open `dachshund.app`
2. Check that the proxy is online
3. Open Codex

Log path:

```sh
open "$HOME/Library/Application Support/dachshund/proxy.log"
```

Accounts directory:

```sh
open "$HOME/Library/Application Support/dachshund/accounts"
```
