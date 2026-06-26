#!/usr/bin/env python3
"""Cross-platform action entrypoint used by Electron."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Optional
import urllib.error
import urllib.request


def _root_dir() -> Path:
    path = Path(__file__).resolve()
    if path.parent.name == "platform" and path.parent.parent.name == "app":
        return path.parents[2]
    return path.parent


ROOT = _root_dir()
CORE_DIR = ROOT / "src" / "core" if (ROOT / "src" / "core").is_dir() else ROOT
PLATFORM_DIR = ROOT / "platforms" / ("windows" if sys.platform == "win32" else "linux")
for entry in (str(CORE_DIR), str(PLATFORM_DIR), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


if sys.platform == "darwin":
    mac_actions = ROOT / "platforms" / "mac" / "control_actions.py"
    if mac_actions.exists():
        spec = importlib.util.spec_from_file_location("dachshund_mac_control_actions", mac_actions)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        if __name__ == "__main__":
            module.main()
            raise SystemExit


from account_manager import Account, AccountPool, account_dir, validate_account_name
import account_manager
import codex_config
import config
from codex_cli import (
    CODEX_CLI_MISSING_MESSAGE,
    complete_login_imports,
    current_log_offset,
    find_codex_cli,
    format_login_command,
    login_device_auth_args,
    login_rate_limit_cooldown,
    login_startup_error_result,
    login_status_from_state,
    remove_login_state,
    wait_for_login_details,
    write_login_state,
)


def _load_service_manager():
    path = PLATFORM_DIR / "service_manager.py"
    if not path.exists():
        import service_manager
        return service_manager
    spec = importlib.util.spec_from_file_location("dachshund_platform_service_manager", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


service_manager = _load_service_manager()


def _align_runtime_dir() -> None:
    runtime = Path(os.environ.get(getattr(service_manager, "CONFIG_DIR_ENV", "CODEX_PROXY_CONFIG_DIR")) or service_manager.RUNTIME_DIR).expanduser()
    os.environ.setdefault(getattr(service_manager, "CONFIG_DIR_ENV", "CODEX_PROXY_CONFIG_DIR"), str(runtime))
    service_manager.RUNTIME_DIR = runtime
    if hasattr(service_manager, "LOG_PATH"):
        service_manager.LOG_PATH = runtime / "proxy.log"
    config.CONFIG_DIR = runtime
    config.CONFIG_PATH = runtime / "config.json"
    account_manager.ACCOUNTS_DIR = runtime / "accounts"


_align_runtime_dir()

CODEX_AUTH_PATH = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"
CODEX_APP_PATH = Path("/Applications/Codex.app")
CODEX_CLI_INSTALL_HINT = CODEX_CLI_MISSING_MESSAGE


CONFIG_SET_KEYS = {
    "port",
    "rate_limit_cooldown",
    "rotation_strategy",
    "product_mode",
    "max_retries",
    "quota_refresh_interval",
    "quota_tracker_enabled",
    "quota_tracker_user_set",
    "max_request_body_mb",
    "upstream_connect_timeout_sec",
    "upstream_transient_retries",
    "upstream_transient_backoff_ms",
    "codex_stream_mode",
    "codex_stream_mode_user_set",
    "codex_hybrid_probe_seconds",
    "codex_hybrid_probe_bytes",
    "codex_stream_retry_cooldown",
    "stream_keepalive_seconds",
    "stream_bootstrap_retries",
    "nonstream_keepalive_interval",
    "websocket_heartbeat_seconds",
    "session_affinity_enabled",
    "session_affinity_ttl_seconds",
    "quota_weight_5h",
    "quota_weight_7d",
    "log_level",
}


def api_root() -> str:
    return f"http://127.0.0.1:{config.get('port')}"


def status_url() -> str:
    return f"{api_root()}/api/status"


def health_url() -> str:
    return f"{api_root()}/api/health"


def fetch_json_url(url: str, timeout: float = 3.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    try:
        result = subprocess.run(
            ["curl", "-sS", "--max-time", str(max(1, int(timeout))), url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (OSError, json.JSONDecodeError):
        return None
    return None


def fetch_api(path: str, *, method: str = "GET", timeout: float = 5.0):
    try:
        request = urllib.request.Request(f"{api_root()}{path}", data=b"" if method != "GET" else None, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def proxy_status(timeout: float = 3.0) -> Optional[dict]:
    health = fetch_json_url(health_url(), timeout)
    if health and health.get("running"):
        return health
    return fetch_json_url(status_url(), timeout)


def wait_for_proxy(timeout: float = 25.0, expected_version: Optional[str] = None) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = proxy_status(timeout=2)
        if status and (not expected_version or status.get("version") == expected_version):
            return status
        time.sleep(0.5)
    return None


def runtime_status(source_dir: Optional[str] = None) -> dict:
    source = Path(source_dir).expanduser() if source_dir else Path(service_manager.status().get("source_dir") or ROOT)
    integrity_func = getattr(service_manager, "runtime_integrity", None)
    if callable(integrity_func):
        integrity = integrity_func(source=source, runtime=service_manager.RUNTIME_DIR)
    else:
        integrity = {
            "ok": None,
            "bundle_version": service_manager.status().get("bundle_version", ""),
            "runtime_version": service_manager.status().get("runtime_version", ""),
        }
    return {
        "runtime_exists": service_manager.RUNTIME_DIR.exists(),
        "resource_runtime_exists": source.exists(),
        "bundle_version": integrity.get("bundle_version", ""),
        "runtime_version": integrity.get("runtime_version", ""),
        "manifest_ok": integrity.get("ok", False),
        "manifest_error": integrity.get("error", ""),
        "manifest": integrity,
    }


def codex_dependency_status() -> dict:
    codex_cli = find_codex_cli()
    cli_found = bool(codex_cli)
    return {
        "codex_cli_found": cli_found,
        "codex_cli": codex_cli or "",
        "codex_app_found": CODEX_APP_PATH.exists(),
        "codex_cli_error": "" if cli_found else CODEX_CLI_INSTALL_HINT,
    }


def with_product_status(data: dict) -> dict:
    result = dict(data)
    result.update(codex_dependency_status())
    result.update(runtime_status(result.get("source_dir")))
    return result


def status() -> dict:
    service = service_manager.status()
    menubar = service_manager.menubar_login_status()
    codex = codex_config.status()
    proxy = proxy_status()
    cfg = config.load()
    return with_product_status({
        "action": "status",
        "installed": service.get("installed"),
        "loaded": service.get("loaded"),
        "needs_repair": service.get("needs_repair"),
        "enabled": codex.get("enabled"),
        "mode": codex.get("mode"),
        "strategy": cfg.get("rotation_strategy"),
        "product_mode": cfg.get("product_mode"),
        "config": cfg,
        "codex_stream_mode": cfg.get("codex_stream_mode"),
        "codex_hybrid_probe_seconds": cfg.get("codex_hybrid_probe_seconds"),
        "codex_hybrid_probe_bytes": cfg.get("codex_hybrid_probe_bytes"),
        "codex_stream_retry_cooldown": cfg.get("codex_stream_retry_cooldown") or cfg.get("rate_limit_cooldown"),
        "codex_provider_base_url": codex.get("current", {}).get("model_providers.codex-account-pool.base_url"),
        "codex_provider_supports_websockets": codex.get("current", {}).get("model_providers.codex-account-pool.supports_websockets"),
        "codex_expected_base_url": codex.get("expected", {}).get("codex_base_url"),
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
        "version": proxy.get("version") if proxy else None,
        "proxy_version": proxy.get("version") if proxy else None,
        "expected_version": service.get("expected_version"),
        "running_version": service.get("running_version"),
        "bundle_version": service.get("bundle_version"),
        "runtime_version": service.get("runtime_version"),
        "manifest_ok": service.get("manifest_ok"),
        "manifest_error": service.get("manifest_error"),
        "manifest": service.get("manifest"),
        "version_mismatch": service.get("version_mismatch"),
        "installed_program": service.get("installed_program"),
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "log_path": service.get("log_path"),
        "menubar_login": menubar,
        "menubar_login_enabled": menubar.get("enabled"),
        "service": service,
    })


def repair() -> dict:
    proxy_before = proxy_status(timeout=2)
    codex = codex_config.ensure_enabled(True)
    previous_service = service_manager.status()
    expected_version = previous_service.get("expected_version") or previous_service.get("bundle_version")
    previous_version = proxy_before.get("version") if proxy_before else previous_service.get("running_version")
    try:
        service = service_manager.install(sync=True)
    except service_manager.RuntimeSyncError as exc:
        return with_product_status({
            "action": "started_or_repaired",
            "installed": previous_service.get("installed"),
            "loaded": previous_service.get("loaded"),
            "needs_repair": previous_service.get("needs_repair"),
            "version_mismatch": previous_service.get("version_mismatch"),
            "manifest_ok": previous_service.get("manifest_ok"),
            "manifest_error": previous_service.get("manifest_error"),
            "manifest": previous_service.get("manifest"),
            "enabled": codex.get("enabled"),
            "mode": codex.get("mode"),
            "running": bool(proxy_before),
            "version": previous_version,
            "previous_version": previous_version,
            "expected_version": expected_version,
            "updated": False,
            "restart_started": False,
            "source_dir": previous_service.get("source_dir"),
            "runtime_dir": previous_service.get("runtime_dir"),
            "restart_required": False,
            "backup_path": str(getattr(exc, "backup_path", "")) if getattr(exc, "backup_path", None) else None,
            "error": str(exc),
            "restore_error": getattr(exc, "restore_error", ""),
        })
    restart_started = False
    if not service.get("restart_required"):
        restart_started = service_manager.restart()
    proxy = wait_for_proxy(expected_version=expected_version or None)
    updated = bool(proxy and expected_version and previous_version != expected_version and proxy.get("version") == expected_version)
    return with_product_status({
        "action": "started_or_repaired",
        "installed": service.get("installed"),
        "loaded": service.get("loaded"),
        "needs_repair": service.get("needs_repair"),
        "version_mismatch": service.get("version_mismatch"),
        "manifest_ok": service.get("manifest_ok"),
        "manifest_error": service.get("manifest_error"),
        "manifest": service.get("manifest"),
        "enabled": codex.get("enabled"),
        "mode": codex.get("mode"),
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
        "version": proxy.get("version") if proxy else None,
        "previous_version": previous_version,
        "expected_version": expected_version,
        "updated": updated,
        "restart_started": restart_started,
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "restart_required": service.get("restart_required"),
    })


def restart_proxy() -> dict:
    if not service_manager.restart():
        service_manager.ensure_running()
    proxy = wait_for_proxy()
    return {
        "action": "restart_proxy",
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
    }


def apply_update() -> dict:
    result = repair()
    result["action"] = "apply_update"
    result["updated"] = bool(result.get("running"))
    return result


def enable_codex_proxy() -> dict:
    result = codex_config.ensure_enabled(True)
    result["action"] = "enable_codex_proxy"
    return result


def disable_codex_proxy() -> dict:
    result = codex_config.ensure_enabled(False)
    result["action"] = "disable_codex_proxy"
    return result


def open_log() -> dict:
    path = str(service_manager.LOG_PATH)
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass
    return {"action": "open_log", "log_path": path}


def show_paths() -> dict:
    service = service_manager.status()
    return {
        "action": "show_paths",
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "accounts_dir": str(account_dir("a").parent),
        "config_path": str(Path(service.get("runtime_dir") or config.CONFIG_DIR) / "config.json"),
        "log_path": service.get("log_path"),
        "python": sys.executable,
        "installed_program": service.get("installed_program", ""),
        "dependencies": ["Python", "aiohttp", "Codex CLI"],
    }


def scan_accounts() -> dict:
    complete_login_imports(service_manager.RUNTIME_DIR)
    proxy = proxy_status()
    if proxy:
        rows = fetch_api("/api/accounts/scan", method="POST")
        return {"action": "scan_accounts", "running": True, "total_accounts": len(rows) if isinstance(rows, list) else None}
    pool = AccountPool()
    pool.scan()
    return {"action": "scan_accounts_local", "running": False, "total_accounts": len(pool.accounts), "active_accounts": pool.active_count()}


def list_accounts() -> dict:
    login_results = complete_login_imports(service_manager.RUNTIME_DIR)
    pool = AccountPool()
    pool.scan()
    return {
        "action": "list_accounts",
        "total_accounts": len(pool.accounts),
        "active_accounts": pool.active_count(),
        "login_status": login_results,
        "accounts": [
            {
                "name": account.name,
                "email": account.email,
                "enabled": account.enabled,
                "has_tokens": bool(account.access_token),
                "auth_error": account.auth_error,
                "rate_limited": account.is_rate_limited,
            }
            for account in pool.accounts
        ],
    }


def login_command(name: str) -> dict:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    codex_cli = find_codex_cli()
    if not codex_cli:
        return {"action": "login_command", "account": safe_name, "account_dir": str(target_dir), "error": "codex_cli_missing", "codex_cli_error": CODEX_CLI_INSTALL_HINT}
    command = format_login_command(codex_cli, target_dir)
    return {"action": "login_command", "account": safe_name, "account_dir": str(target_dir), "command": command}


def start_login(name: str) -> dict:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if auth_path.exists():
        return {"action": "start_login", "account": safe_name, "error": "account already has auth.json"}
    cooldown = login_rate_limit_cooldown(service_manager.RUNTIME_DIR, safe_name)
    if cooldown:
        return {"action": "start_login", **cooldown}
    codex_cli = find_codex_cli()
    if not codex_cli:
        return {"action": "start_login", "account": safe_name, "error": "codex_cli_missing", "codex_cli_error": CODEX_CLI_INSTALL_HINT}
    target_dir.mkdir(parents=True, exist_ok=True)
    command = format_login_command(codex_cli, target_dir)
    log_path = service_manager.RUNTIME_DIR / "login.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CODEX_HOME": str(target_dir)}
    started_at = time.time()
    log_offset = current_log_offset(log_path)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting login for {safe_name}\n")
        process = subprocess.Popen([codex_cli, *login_device_auth_args()], cwd=str(service_manager.RUNTIME_DIR), env=env, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT)
    state_path = write_login_state(
        service_manager.RUNTIME_DIR,
        account_name=safe_name,
        account_dir=target_dir,
        source_auth_path=CODEX_AUTH_PATH,
        log_path=log_path,
        started_at=started_at,
        log_offset=log_offset,
        pid=process.pid,
    )
    login_details = wait_for_login_details(log_path, log_offset=log_offset)
    if not login_details.get("login_url") or not login_details.get("device_code"):
        startup_error = login_startup_error_result(log_path, account=safe_name, log_offset=log_offset)
        if startup_error:
            return {
                "action": "start_login",
                "account": safe_name,
                "account_dir": str(target_dir),
                "command": command,
                "log_path": str(log_path),
                "state_path": str(state_path),
                "pid": process.pid,
                **startup_error,
            }
    return {
        "action": "login_started",
        "account": safe_name,
        "account_dir": str(target_dir),
        "command": command,
        "log_path": str(log_path),
        "state_path": str(state_path),
        "pid": process.pid,
        "started": True,
        **login_details,
    }


def login_status(name: str) -> dict:
    safe_name = validate_account_name(name)
    status = login_status_from_state(service_manager.RUNTIME_DIR, safe_name)
    status["action"] = "login_status"
    return status


def import_current(name: str) -> dict:
    safe_name = validate_account_name(name)
    if not CODEX_AUTH_PATH.exists():
        return {"action": "import_current", "account": safe_name, "error": f"not found: {CODEX_AUTH_PATH}"}
    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if auth_path.exists():
        return {"action": "import_current", "account": safe_name, "error": "account already has auth.json"}
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CODEX_AUTH_PATH, auth_path)
    scan_accounts()
    return {"action": "import_current", "account": safe_name, "account_dir": str(target_dir)}


def load_account(name: str) -> Account:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    account = Account(safe_name, target_dir / "auth.json")
    account.load()
    account.load_meta()
    return account


def toggle_account(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}/toggle", method="PUT")
        if isinstance(result, dict) and not result.get("error"):
            return {"action": "toggle_account", "running": True, "account": safe_name, "enabled": result.get("enabled")}
    account = load_account(safe_name)
    account.enabled = not account.enabled
    account.save_meta()
    return {"action": "toggle_account_local", "running": False, "account": safe_name, "enabled": account.enabled}


def delete_account(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}", method="DELETE")
        if isinstance(result, dict) and not result.get("error"):
            state_removed = remove_login_state(service_manager.RUNTIME_DIR, safe_name)
            return {"action": "delete_account", "running": True, "deleted": result.get("deleted") or safe_name, "trashed_to": result.get("trashed_to"), "login_state_removed": state_removed}
    target_dir = account_dir(safe_name)
    if not target_dir.exists():
        return {"action": "delete_account_local", "running": False, "account": safe_name, "error": "account not found"}
    trash_dir = account_dir("a").parent / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    trashed = trash_dir / f"{safe_name}-{stamp}"
    suffix = 1
    while trashed.exists():
        trashed = trash_dir / f"{safe_name}-{stamp}-{suffix}"
        suffix += 1
    try:
        shutil.move(str(target_dir), str(trashed))
    except OSError as exc:
        return {
            "action": "delete_account_local",
            "running": bool(proxy_status()),
            "account": safe_name,
            "error": str(exc),
        }
    running = bool(proxy_status())
    if running:
        fetch_api("/api/accounts/scan", method="POST")
    state_removed = remove_login_state(service_manager.RUNTIME_DIR, safe_name)
    return {"action": "delete_account_local", "running": running, "deleted": safe_name, "trashed_to": str(trashed), "login_state_removed": state_removed}


def refresh_token(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}/refresh", method="POST", timeout=45)
        if isinstance(result, dict) and not result.get("error"):
            account = result.get("account") or {}
            return {"action": "refresh_token", "running": True, "account": safe_name, "refreshed": result.get("refreshed"), "enabled": account.get("enabled"), "auth_error": account.get("auth_error")}
    account = load_account(safe_name)
    ok = asyncio.run(account.refresh())
    return {"action": "refresh_token_local", "running": False, "account": safe_name, "refreshed": ok, "enabled": account.enabled, "auth_error": account.auth_error}


def clear_cooldown(name: str) -> dict:
    safe_name = validate_account_name(name)
    if not proxy_status():
        return {
            "action": "clear_cooldown",
            "running": False,
            "account": safe_name,
            "error": "proxy is offline; cooldown is in-memory and clears when the proxy restarts",
        }
    result = fetch_api(f"/api/accounts/{safe_name}/cooldown/clear", method="PUT")
    if isinstance(result, dict) and not result.get("error"):
        return {"action": "clear_cooldown", "running": True, "account": safe_name, "enabled": result.get("enabled")}
    return {
        "action": "clear_cooldown",
        "running": True,
        "account": safe_name,
        "error": (result or {}).get("error") if isinstance(result, dict) else "request failed",
    }


def clear_auth_error(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}/auth-error/clear", method="PUT")
        if isinstance(result, dict) and not result.get("error"):
            return {"action": "clear_auth_error", "running": True, "account": safe_name, "enabled": result.get("enabled"), "auth_error": result.get("auth_error")}
    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if not auth_path.exists():
        return {"action": "clear_auth_error_local", "running": False, "account": safe_name, "error": "account not found"}
    account = Account(safe_name, auth_path)
    account.load()
    account.load_meta()
    previous = account.auth_error
    account.auth_error = ""
    account.enabled = True
    account.save_meta()
    running = bool(proxy_status())
    if running:
        fetch_api("/api/accounts/scan", method="POST")
    return {
        "action": "clear_auth_error_local",
        "running": running,
        "account": safe_name,
        "enabled": account.enabled,
        "auth_error": account.auth_error,
        "previous_auth_error": previous,
    }


def set_rotation_strategy(strategy: str) -> dict:
    if strategy not in {"round_robin", "most_available"}:
        return {"action": "set_rotation_strategy", "error": "rotation_strategy must be round_robin or most_available", "strategy": strategy}
    cfg = config.load()
    previous = cfg.get("rotation_strategy")
    cfg["rotation_strategy"] = strategy
    config.save(cfg)
    return {"action": "set_rotation_strategy", "strategy": strategy, "previous_strategy": previous, "changed": previous != strategy}


def set_codex_stream_mode(mode: str) -> dict:
    if mode not in {"hybrid", "buffered", "realtime"}:
        return {"action": "set_codex_stream_mode", "error": "codex_stream_mode must be hybrid, buffered, or realtime", "codex_stream_mode": mode}
    cfg = config.load()
    previous = cfg.get("codex_stream_mode")
    cfg["codex_stream_mode"] = mode
    config.save(cfg)
    return {"action": "set_codex_stream_mode", "codex_stream_mode": mode, "previous_codex_stream_mode": previous, "changed": previous != mode}


def set_config(config_json: str) -> dict:
    try:
        updates = json.loads(config_json or "{}")
    except json.JSONDecodeError as e:
        return {"action": "set_config", "error": f"invalid config json: {e}"}
    if not isinstance(updates, dict):
        return {"action": "set_config", "error": "config update must be an object"}
    unknown = sorted(set(updates) - CONFIG_SET_KEYS)
    if unknown:
        return {"action": "set_config", "error": "unsupported config keys: " + ", ".join(unknown), "unsupported_keys": unknown}
    current = config.load()
    old_port = current.get("port")
    if "quota_tracker_enabled" in updates:
        updates["quota_tracker_user_set"] = True
    if "codex_stream_mode" in updates:
        updates["codex_stream_mode_user_set"] = True
    current.update(updates)
    try:
        config.save(current)
        updated = config.load()
    except config.ConfigError as e:
        return {"action": "set_config", "error": str(e)}
    changed = {key: updated.get(key) for key in sorted(updates) if key in updated}
    return {"action": "set_config", "updated": True, "changed": changed, "config": updated, "restart_required": old_port != updated.get("port")}


def menubar_login_status() -> dict:
    return service_manager.menubar_login_status()


def set_menubar_login_item(enabled: bool) -> dict:
    try:
        return service_manager.set_menubar_login_item(enabled)
    except RuntimeError as exc:
        return {"action": "set_menubar_login_item", "error": str(exc), "enabled": enabled}


def render_output(data: dict, output_format: str = "pretty") -> str:
    return json.dumps(data, ensure_ascii=False, default=str, indent=None if output_format == "json" else 2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=tuple(ACTIONS))
    parser.add_argument("--name", default="")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--stream-mode", default="")
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--format", choices=("pretty", "json"), default="pretty")
    args = parser.parse_args()
    actions = {
        "status": status,
        "repair": repair,
        "repair-open-web": repair,
        "repair-open-codex": repair,
        "restart-proxy": restart_proxy,
        "apply-update": apply_update,
        "enable-codex-proxy": enable_codex_proxy,
        "disable-codex-proxy": disable_codex_proxy,
        "open-log": open_log,
        "show-paths": show_paths,
        "scan-accounts": scan_accounts,
        "list-accounts": list_accounts,
        "login-command": lambda: login_command(args.name),
        "start-login": lambda: start_login(args.name),
        "login-status": lambda: login_status(args.name),
        "import-current": lambda: import_current(args.name),
        "toggle-account": lambda: toggle_account(args.name),
        "delete-account": lambda: delete_account(args.name),
        "refresh-token": lambda: refresh_token(args.name),
        "clear-cooldown": lambda: clear_cooldown(args.name),
        "clear-auth-error": lambda: clear_auth_error(args.name),
        "set-rotation-strategy": lambda: set_rotation_strategy(args.strategy),
        "set-codex-stream-mode": lambda: set_codex_stream_mode(args.stream_mode),
        "set-config": lambda: set_config(args.config_json),
        "menubar-login-status": menubar_login_status,
        "enable-menubar-login": lambda: set_menubar_login_item(True),
        "disable-menubar-login": lambda: set_menubar_login_item(False),
    }
    print(render_output(actions[args.action](), args.format))


ACTIONS = {
    "status",
    "repair",
    "repair-open-web",
    "repair-open-codex",
    "restart-proxy",
    "apply-update",
    "enable-codex-proxy",
    "disable-codex-proxy",
    "open-log",
    "show-paths",
    "scan-accounts",
    "list-accounts",
    "login-command",
    "start-login",
    "login-status",
    "import-current",
    "toggle-account",
    "delete-account",
    "refresh-token",
    "clear-cooldown",
    "clear-auth-error",
    "set-rotation-strategy",
    "set-codex-stream-mode",
    "set-config",
    "menubar-login-status",
    "enable-menubar-login",
    "disable-menubar-login",
}


if __name__ == "__main__":
    main()
