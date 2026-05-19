"""Codex Account Pool Proxy — main entry point.

Start with: python3 proxy.py
Web UI:      http://127.0.0.1:8800/app
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
from typing import Optional

import aiohttp
from aiohttp import web

from account_manager import (
    ACCOUNTS_DIR,
    AccountNameError,
    AccountPool,
    account_dir,
    validate_account_name,
)
import codex_config
from config import CONFIG_DIR, ConfigError, load, save, get
from login_manager import LoginManager, find_codex_cli
from proxy_core import handle as proxy_handle
from quota_tracker import refresh_once as refresh_quota_once, run as quota_run
import service_manager

CODE_CLI = find_codex_cli() or "/Applications/Codex.app/Contents/Resources/codex"
CODEX_AUTH_PATH = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"
APP_VERSION = "0.4.3"

# ── Setup ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, str(get("log_level")).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("proxy")

pool = AccountPool()
login_manager = LoginManager()

STATIC_DIR = CONFIG_DIR / "static"
TRASH_DIR = ACCOUNTS_DIR / ".trash"
TRASH_ENTRY_RE = re.compile(r"^([A-Za-z0-9_-]{1,64})-(\d{8})-(\d{6})$")
OPENAI_INFERENCE_PATHS = (
    "/v1/responses",
    "/v1/chat/completions",
    "/v1/completions",
)
NON_QUOTA_CODEX_PATH_PREFIXES = (
    "/backend-api/codex/analytics-events",
    "/backend-api/codex/usage",
)
QUOTA_CODEX_PATH_PREFIXES = (
    "/backend-api/codex/responses",
)
BACKGROUND_PATH_PREFIXES = (
    "/backend-api/wham/",
    "/backend-api/connectors/",
    "/backend-api/plugins/",
)


def _is_openai_inference_request(path: str) -> bool:
    return path.startswith(OPENAI_INFERENCE_PATHS)


def _is_known_background_request(path: str) -> bool:
    return path.startswith(BACKGROUND_PATH_PREFIXES) or path.startswith(NON_QUOTA_CODEX_PATH_PREFIXES)


def _is_potential_quota_request(path: str) -> bool:
    if _is_openai_inference_request(path):
        return True
    return path.startswith(QUOTA_CODEX_PATH_PREFIXES)


# ── Management API ─────────────────────────────────────────────────────

async def api_accounts(request: web.Request) -> web.Response:
    """GET /api/accounts — list all accounts."""
    return web.json_response([a.to_dict() for a in pool.accounts])


async def api_accounts_add(request: web.Request) -> web.Response:
    """POST /api/accounts/add — return the codex login command for a new account."""
    try:
        body = await request.json()
        name = validate_account_name(body.get("name") or "")
        target_dir = account_dir(name)
    except (AccountNameError, json.JSONDecodeError) as e:
        return web.json_response({"error": str(e) or "invalid request"}, status=400)

    if target_dir.exists():
        return web.json_response({"error": "account already exists"}, status=409)

    target_dir.mkdir(parents=True, exist_ok=True)
    cmd = f'CODEX_HOME={target_dir} {CODE_CLI} login'
    return web.json_response({
        "command": cmd,
        "hint": "Run this in your terminal, then refresh accounts.",
        "account_dir": str(target_dir),
    })


async def api_accounts_delete(request: web.Request) -> web.Response:
    """DELETE /api/accounts/{name} — remove an account directory."""
    try:
        name = validate_account_name(request.match_info["name"])
        target = account_dir(name)
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not target.exists():
        return web.json_response({"error": "not found"}, status=404)
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    trashed_name = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    trashed = TRASH_DIR / trashed_name
    shutil.move(str(target), str(trashed))
    pool.scan()
    return web.json_response({"deleted": name, "trashed_to": str(trashed)})


def _trash_entry(entry_name: str) -> Optional[dict]:
    match = TRASH_ENTRY_RE.fullmatch(entry_name)
    if not match:
        return None
    original_name, date_part, time_part = match.groups()
    try:
        validate_account_name(original_name)
    except AccountNameError:
        return None
    return {
        "id": entry_name,
        "original_name": original_name,
        "trashed_at": f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} "
                      f"{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}",
    }


async def api_accounts_trash(request: web.Request) -> web.Response:
    """GET /api/accounts/trash — list accounts moved to trash."""
    if not TRASH_DIR.exists():
        return web.json_response([])
    entries = []
    for entry in sorted(TRASH_DIR.iterdir(), reverse=True):
        if not entry.is_dir() or not (entry / "auth.json").exists():
            continue
        item = _trash_entry(entry.name)
        if item:
            entries.append(item)
    return web.json_response(entries)


async def api_accounts_restore(request: web.Request) -> web.Response:
    """POST /api/accounts/trash/{trash_id}/restore — restore a trashed account."""
    trash_id = request.match_info["trash_id"]
    item = _trash_entry(trash_id)
    if not item:
        return web.json_response({"error": "invalid trash entry"}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}
    try:
        restore_name = validate_account_name(body.get("name") or item["original_name"])
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)

    source = (TRASH_DIR / trash_id).resolve()
    trash_root = TRASH_DIR.resolve()
    if source != trash_root and trash_root not in source.parents:
        return web.json_response({"error": "trash path escapes trash directory"}, status=400)
    if not source.exists() or not (source / "auth.json").exists():
        return web.json_response({"error": "trash entry not found"}, status=404)

    target = account_dir(restore_name)
    if target.exists():
        return web.json_response({"error": f"account '{restore_name}' already exists"}, status=409)

    shutil.move(str(source), str(target))
    pool.scan()
    acct = pool.get(restore_name)
    return web.json_response({
        "restored": restore_name,
        "account": acct.to_dict() if acct else None,
    })


async def api_accounts_toggle(request: web.Request) -> web.Response:
    """PUT /api/accounts/{name}/toggle — enable or disable an account."""
    try:
        name = validate_account_name(request.match_info["name"])
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    acct = pool.get(name)
    if not acct:
        return web.json_response({"error": "not found"}, status=404)
    acct.enabled = not acct.enabled
    acct.save_meta()
    return web.json_response(acct.to_dict())


async def api_accounts_refresh(request: web.Request) -> web.Response:
    """POST /api/accounts/{name}/refresh — manually refresh an account's token."""
    try:
        name = validate_account_name(request.match_info["name"])
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    acct = pool.get(name)
    if not acct:
        return web.json_response({"error": "not found"}, status=404)
    ok = await acct.refresh()
    return web.json_response({"refreshed": ok, "account": acct.to_dict()})


async def api_accounts_cooldown_clear(request: web.Request) -> web.Response:
    """PUT /api/accounts/{name}/cooldown/clear — clear temporary cooldown state."""
    try:
        name = validate_account_name(request.match_info["name"])
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    acct = pool.get(name)
    if not acct:
        return web.json_response({"error": "not found"}, status=404)
    pool.clear_cooldown(acct)
    return web.json_response(acct.to_dict())


async def api_accounts_auth_error_clear(request: web.Request) -> web.Response:
    """PUT /api/accounts/{name}/auth-error/clear — clear persisted auth error state."""
    try:
        name = validate_account_name(request.match_info["name"])
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    acct = pool.get(name)
    if not acct:
        return web.json_response({"error": "not found"}, status=404)
    acct.auth_error = ""
    acct.enabled = True
    acct.save_meta()
    return web.json_response(acct.to_dict())


async def api_accounts_scan(request: web.Request) -> web.Response:
    """POST /api/accounts/scan — re-scan the accounts directory."""
    pool.scan()
    return web.json_response([a.to_dict() for a in pool.accounts])


async def api_accounts_import_current(request: web.Request) -> web.Response:
    """POST /api/accounts/import-current — import ~/.codex/auth.json into accounts/."""
    try:
        body = await request.json()
        name = validate_account_name(body.get("name") or "")
        target_dir = account_dir(name)
    except (AccountNameError, json.JSONDecodeError) as e:
        return web.json_response({"error": str(e) or "invalid request"}, status=400)

    if not CODEX_AUTH_PATH.exists():
        return web.json_response({"error": f"not found: {CODEX_AUTH_PATH}"}, status=404)
    if (target_dir / "auth.json").exists():
        return web.json_response({"error": "account already has auth.json"}, status=409)

    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CODEX_AUTH_PATH, target_dir / "auth.json")
    pool.scan()
    acct = pool.get(name)
    return web.json_response({
        "imported": name,
        "account": acct.to_dict() if acct else None,
        "source": str(CODEX_AUTH_PATH),
    })


async def api_login_start(request: web.Request) -> web.Response:
    """POST /api/accounts/{name}/login/start — start Codex login from the Web UI."""
    try:
        name = validate_account_name(request.match_info["name"])
        try:
            body = await request.json() if request.can_read_body else {}
        except json.JSONDecodeError:
            body = {}
        force_relogin = bool(body.get("force_relogin") or body.get("force"))
        status = await login_manager.start(name, force_relogin=force_relogin)
        return web.json_response(status)
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=500)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)


async def api_login_status(request: web.Request) -> web.Response:
    """GET /api/accounts/{name}/login/status — inspect a Web-started login."""
    try:
        name = validate_account_name(request.match_info["name"])
        status = await login_manager.status(name)
        if status.get("state") == "success":
            pool.scan()
            acct = pool.get(name)
            if acct and acct.auth_error:
                acct.auth_error = ""
                acct.enabled = True
                acct.save_meta()
                status["account"] = acct.to_dict()
        return web.json_response(status)
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_login_stop(request: web.Request) -> web.Response:
    """POST /api/accounts/{name}/login/stop — stop a pending Web-started login."""
    try:
        name = validate_account_name(request.match_info["name"])
        status = await login_manager.stop(name)
        return web.json_response(status)
    except AccountNameError as e:
        return web.json_response({"error": str(e)}, status=400)


async def api_quota(request: web.Request) -> web.Response:
    """GET /api/quota — return quota info for all accounts.

    Quota data is loaded from per-account quota.json files written by
    the quota_tracker module, or returned as empty if unavailable.
    """
    result = {}
    for acct in pool.accounts:
        quota_file = ACCOUNTS_DIR / acct.name / "quota.json"
        if quota_file.exists():
            try:
                with open(quota_file) as f:
                    result[acct.name] = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Account {acct.name}: failed to read quota data: {e}")
                result[acct.name] = {
                    "error": "quota_unavailable",
                    "message": "quota data is being refreshed",
                }
        else:
            result[acct.name] = None
    return web.json_response(result)


async def api_quota_refresh(request: web.Request) -> web.Response:
    """POST /api/quota/refresh — fetch fresh quota data and return it."""
    started = time.monotonic()
    result = await refresh_quota_once(pool)
    return web.json_response({
        "refreshed": any(item.get("refreshed") for item in result.values()),
        "accounts": result,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
    })


async def api_status(request: web.Request) -> web.Response:
    """GET /api/status — proxy health and stats."""
    disabled_accounts = sum(1 for acct in pool.accounts if not acct.enabled)
    rate_limited_accounts = sum(1 for acct in pool.accounts if acct.is_rate_limited)
    recent_requests = list(pool.recent_requests)
    recent_potential_quota_requests = [
        item for item in recent_requests
        if _is_potential_quota_request(str(item.get("path", "")))
        and item.get("account") != "local"
    ]
    recent_blocked_inference_requests = [
        item for item in recent_requests
        if _is_openai_inference_request(str(item.get("path", "")))
        and item.get("account") == "local"
    ]
    recent_model_catalog_requests = [
        item for item in recent_requests
        if str(item.get("path", "")).startswith("/v1/models")
    ]
    recent_background_requests = [
        item for item in recent_requests
        if _is_known_background_request(str(item.get("path", "")))
    ]
    return web.json_response({
        "version": APP_VERSION,
        "total_accounts": len(pool.accounts),
        "active_accounts": pool.active_count(),
        "disabled_accounts": disabled_accounts,
        "rate_limited_accounts": rate_limited_accounts,
        "running": True,
        "port": get("port"),
        "strategy": get("rotation_strategy"),
        "stats": pool.stats,
        "last_request": pool.recent_requests[0] if pool.recent_requests else None,
        "recent_requests": recent_requests,
        "recent_errors": list(pool.recent_errors),
        "model_proxy": {
            "observed": bool(recent_potential_quota_requests),
            "coverage": "potential_quota_path_observed" if recent_potential_quota_requests else "not_confirmed",
            "recent_model_requests": recent_potential_quota_requests[:10],
            "recent_blocked_requests": recent_blocked_inference_requests[:10],
            "recent_catalog_requests": recent_model_catalog_requests[:10],
            "recent_background_requests": recent_background_requests[:10],
            "hint": (
                "Quota-consuming Codex traffic should appear as /backend-api/codex/responses. "
                "Background paths such as /backend-api/wham, connectors, plugins, "
                "and /backend-api/codex/analytics-events do not prove model traffic is pooled."
            ),
        },
    })


async def api_health(request: web.Request) -> web.Response:
    """GET /api/health — small liveness response for native control tools."""
    return web.json_response({
        "version": APP_VERSION,
        "running": True,
        "port": get("port"),
        "total_accounts": len(pool.accounts),
        "active_accounts": pool.active_count(),
    })


async def api_version(request: web.Request) -> web.Response:
    """GET /api/version — return app version and available management features."""
    return web.json_response({
        "version": APP_VERSION,
        "features": {
            "selection": True,
            "request_id": True,
            "trash_restore": True,
            "quota_weights": True,
            "quota_path_diagnostics": True,
        },
    })


async def api_selection(request: web.Request) -> web.Response:
    """GET /api/selection — explain which account the proxy would pick next."""
    return web.json_response(pool.selection_report())


async def api_recent_requests_clear(request: web.Request) -> web.Response:
    """POST /api/status/recent/clear — clear in-memory recent request rows."""
    pool.clear_recent_requests()
    return web.json_response({"cleared": True})


async def api_config_get(request: web.Request) -> web.Response:
    """GET /api/config — return current config."""
    return web.json_response(load())


async def api_config_put(request: web.Request) -> web.Response:
    """PUT /api/config — update config."""
    try:
        body = await request.json()
        current = load()
        old_port = current.get("port")
        current.update(body)
        save(current)
        updated = load()
        logging.getLogger().setLevel(getattr(logging, str(updated.get("log_level")).upper(), logging.INFO))
        updated["hot_applied"] = True
        updated["restart_required"] = old_port != updated.get("port")
        return web.json_response(updated)
    except (ConfigError, json.JSONDecodeError) as e:
        return web.json_response({"error": str(e) or "invalid request"}, status=400)


async def api_control_app_required(request: web.Request) -> web.Response:
    """Reject high-risk management actions from the Web server process."""
    return web.json_response(
        {
            "error": "This action moved to the native Control App so the proxy can stay running.",
            "use": "Codex Proxy Control.app or control_panel.command",
        },
        status=410,
    )


async def api_codex_proxy_status(request: web.Request) -> web.Response:
    """GET /api/codex/proxy — show whether Codex is configured to use this proxy."""
    return web.json_response(codex_config.status())


async def api_codex_proxy_put(request: web.Request) -> web.Response:
    """PUT /api/codex/proxy — enable or disable Codex base URL proxy settings."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid request"}, status=400)
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        return web.json_response({"error": "enabled must be true or false"}, status=400)
    try:
        return web.json_response(codex_config.set_enabled(enabled))
    except OSError as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_proxy_restart(request: web.Request) -> web.Response:
    """POST /api/proxy/restart — restart this proxy process."""
    asyncio.create_task(_restart_soon())
    return web.json_response({
        "restarting": True,
        "message": "Proxy is restarting. In-flight Codex requests may be interrupted.",
    })


async def api_service_status(request: web.Request) -> web.Response:
    """GET /api/service — return LaunchAgent service status."""
    return web.json_response(service_manager.status())


async def api_service_install(request: web.Request) -> web.Response:
    """POST /api/service/install — install and start the LaunchAgent."""
    try:
        return web.json_response(service_manager.install())
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=500)


async def api_service_uninstall(request: web.Request) -> web.Response:
    """POST /api/service/uninstall — stop and remove the LaunchAgent."""
    try:
        return web.json_response(service_manager.uninstall())
    except RuntimeError as e:
        return web.json_response({"error": str(e)}, status=500)


# ── Static UI ──────────────────────────────────────────────────────────

async def serve_ui(request: web.Request) -> web.Response:
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return web.Response(text="UI not found. Create static/index.html", status=404)
    return web.FileResponse(index, headers={"Cache-Control": "no-store"})


# ── Proxy catch-all ────────────────────────────────────────────────────

async def proxy_handler(request: web.Request) -> web.Response:
    return await proxy_handle(request, pool, request.app["upstream_session"])


async def _restart_soon() -> None:
    await asyncio.sleep(0.4)
    logger.warning("Restarting proxy process")
    if service_manager.restart():
        return
    os.execv(sys.executable, [sys.executable, *sys.argv])


# ── Main ───────────────────────────────────────────────────────────────

def create_app() -> web.Application:
    max_body_bytes = int(get("max_request_body_mb") or 50) * 1024 * 1024
    app = web.Application(
        client_max_size=max_body_bytes,
        handler_args={"auto_decompress": False},
    )

    # Management API
    app.router.add_get("/api/accounts", api_accounts)
    app.router.add_post("/api/accounts/add", api_accounts_add)
    app.router.add_post("/api/accounts/scan", api_accounts_scan)
    app.router.add_post("/api/accounts/import-current", api_accounts_import_current)
    app.router.add_get("/api/accounts/trash", api_accounts_trash)
    app.router.add_post("/api/accounts/trash/{trash_id}/restore", api_accounts_restore)
    app.router.add_delete("/api/accounts/{name}", api_accounts_delete)
    app.router.add_put("/api/accounts/{name}/toggle", api_accounts_toggle)
    app.router.add_post("/api/accounts/{name}/refresh", api_accounts_refresh)
    app.router.add_put("/api/accounts/{name}/cooldown/clear", api_accounts_cooldown_clear)
    app.router.add_put("/api/accounts/{name}/auth-error/clear", api_accounts_auth_error_clear)
    app.router.add_post("/api/accounts/{name}/login/start", api_control_app_required)
    app.router.add_get("/api/accounts/{name}/login/status", api_control_app_required)
    app.router.add_post("/api/accounts/{name}/login/stop", api_control_app_required)
    app.router.add_get("/api/quota", api_quota)
    app.router.add_post("/api/quota/refresh", api_quota_refresh)
    app.router.add_get("/api/health", api_health)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/version", api_version)
    app.router.add_get("/api/selection", api_selection)
    app.router.add_post("/api/status/recent/clear", api_recent_requests_clear)
    app.router.add_get("/api/config", api_config_get)
    app.router.add_put("/api/config", api_config_put)
    app.router.add_get("/api/codex/proxy", api_codex_proxy_status)
    app.router.add_put("/api/codex/proxy", api_codex_proxy_put)
    app.router.add_post("/api/proxy/restart", api_control_app_required)
    app.router.add_get("/api/service", api_service_status)
    app.router.add_post("/api/service/install", api_control_app_required)
    app.router.add_post("/api/service/uninstall", api_control_app_required)

    # Web UI
    app.router.add_get("/app", serve_ui)
    app.router.add_get("/app/", serve_ui)
    app.router.add_static("/static/", STATIC_DIR, name="static")

    # Proxy — catch all other paths
    app.router.add_route("*", "/{tail:.*}", proxy_handler)

    return app


async def on_startup(app: web.Application) -> None:
    app["upstream_session"] = aiohttp.ClientSession(auto_decompress=False)
    app["quota_task"] = None
    if get("quota_tracker_enabled"):
        app["quota_task"] = asyncio.create_task(quota_run(pool))


async def on_cleanup(app: web.Application) -> None:
    task = app.get("quota_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await login_manager.cleanup()
    session = app.get("upstream_session")
    if session:
        await session.close()


if __name__ == "__main__":
    port = get("port")
    logger.info(f"Scanning accounts in {ACCOUNTS_DIR}")
    pool.scan()
    logger.info(f"Loaded {len(pool.accounts)} account(s)")
    logger.info(f"Starting proxy on http://127.0.0.1:{port}")
    logger.info(f"Web UI at http://127.0.0.1:{port}/app")

    app = create_app()
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="127.0.0.1", port=port)
