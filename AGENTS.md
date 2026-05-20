# Codex Account Pool Proxy — Project Overview

A local reverse proxy that pools multiple ChatGPT Plus accounts for use with Codex CLI, providing round-robin load balancing, automatic failover on rate limits, and a web dashboard for monitoring.

## Architecture

```
Codex CLI → src/core/proxy.py (aiohttp, :8800) → api.openai.com / chatgpt.com
                 │
                 ├── /app        → src/core/static/index.html  (Web UI)
                 ├── /api/*      → management REST API
                 └── /v1/*, /backend-api/* → proxy_core (forward + account rotation)
```

## File Map

| File | Purpose |
|------|---------|
| `src/core/proxy.py` | Main entry point. Registers all routes, starts aiohttp server, wires up background tasks. |
| `src/core/proxy_core.py` | Request forwarding engine. Routes `/v1/*` → `api.openai.com` and `/backend-api/*` → `chatgpt.com`. Picks account from pool, retries on 429/401, passes through SSE streams. |
| `src/core/account_manager.py` | `Account` class: loads OAuth tokens from `auth.json`, decodes JWT claims, refreshes via `auth.openai.com/oauth/token`. `AccountPool`: round-robin selection with cooldown tracking. |
| `src/core/quota_tracker.py` | Background task that polls `chatgpt.com/backend-api/codex/usage` per account, saves to `quota.json`. |
| `src/core/config.py` | Reads/writes `config.json`. Runtime data defaults to the repo root when running from source. |
| `src/core/static/index.html` | Single-file web dashboard (vanilla HTML/CSS/JS). Three tabs: dashboard, accounts, settings. |
| `platforms/mac/` | macOS app, LaunchAgent helpers, and DMG build scripts. |
| `platforms/windows/` | Windows control app, Scheduled Task helper, PyInstaller, and Inno Setup files. |

## Key Design Decisions

- **One dependency**: only `aiohttp`. No database, no Docker, no build step.
- **aiohttp serves both roles**: receives Codex requests (server) and forwards to upstream (client via `aiohttp.ClientSession`).
- **File-based storage**: accounts live as directories under `accounts/<name>/auth.json`. Git-ignored.
- **Account selection**: round-robin through `AccountPool.pick()`, skipping rate-limited (cooldown timer) and disabled accounts.
- **429 handling**: mark account with `rate_limited_until = now + cooldown`, retry with next account.
- **401 handling**: call `account.refresh()` → POST to `auth.openai.com/oauth/token`, retry same account.
- **SSE streaming**: `response.content.iter_chunks()` passes through chunk-by-chunk with no buffering.
- **JWT decoding**: email and account_id are in nested claims (`https://api.openai.com/profile.email`, `https://api.openai.com/auth.chatgpt_account_id`).
- **Usage API**: requires `User-Agent` and `Origin: https://chatgpt.com` headers. Returns `rate_limit.primary_window.used_percent` and `secondary_window.used_percent`.

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/accounts` | List all accounts |
| POST | `/api/accounts/add` | Generate `codex login` command for new account |
| POST | `/api/accounts/scan` | Rescan accounts directory |
| DELETE | `/api/accounts/{name}` | Remove account directory |
| PUT | `/api/accounts/{name}/toggle` | Enable/disable account |
| POST | `/api/accounts/{name}/refresh` | Manually refresh OAuth token |
| GET | `/api/quota` | Get quota data for all accounts |
| GET | `/api/status` | Proxy health and stats |
| GET | `/api/config` | Get current config |
| PUT | `/api/config` | Update config |
| GET | `/app` | Web dashboard |

## Config (`config.json`)

```json
{
  "port": 8800,
  "rate_limit_cooldown": 60,
  "rotation_strategy": "round_robin",
  "max_retries": 10,
  "quota_refresh_interval": 300,
  "log_level": "INFO"
}
```

## Codex Integration

Add to `~/.codex/config.toml`:

```toml
openai_base_url = "http://127.0.0.1:8800/v1"
chatgpt_base_url = "http://127.0.0.1:8800"
```

## Account Storage

```
accounts/{name}/auth.json   # OAuth tokens (id_token, access_token, refresh_token)
accounts/{name}/quota.json  # Latest usage data (auto-generated, git-ignored)
```

## Adding a New Account

1. Web UI: Accounts → Add Account → enter name → get login command
2. Terminal: run `CODEX_HOME=accounts/{name} codex login`
3. Browser: sign in with the new OpenAI account
4. Web UI: Rescan
