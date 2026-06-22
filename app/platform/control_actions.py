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
import codex_config
import config
from codex_cli import CODEX_CLI_MISSING_MESSAGE, find_codex_cli, format_login_command


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


def fetch_api(path: str, *, method: str = "GET", timeout: float = 5.0):
    try:
        request = urllib.request.Request(f"{api_root()}{path}", data=b"" if method != "GET" else None, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def proxy_status(timeout: float = 3.0) -> Optional[dict]:
    return fetch_api("/api/health", timeout=timeout) or fetch_api("/api/status", timeout=timeout)


def wait_for_proxy(timeout: float = 20.0) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = proxy_status(timeout=2)
        if status:
            return status
        time.sleep(0.5)
    return None


def status() -> dict:
    service = service_manager.status()
    codex = codex_config.status()
    proxy = proxy_status(timeout=1)
    return {
        "action": "status",
        "installed": service.get("installed"),
        "loaded": service.get("loaded"),
        "enabled": codex.get("enabled"),
        "mode": codex.get("mode"),
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
        "version": proxy.get("version") if proxy else service.get("running_version"),
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "log_path": service.get("log_path"),
        "config": {"port": config.get("port")},
        "service": service,
    }


def repair() -> dict:
    service = service_manager.install(sync=True)
    service_manager.restart()
    proxy = wait_for_proxy()
    return {
        "action": "started_or_repaired",
        "installed": service.get("installed"),
        "loaded": service.get("loaded"),
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
        "version": proxy.get("version") if proxy else None,
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
    }


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
    proxy = proxy_status()
    if proxy:
        rows = fetch_api("/api/accounts/scan", method="POST")
        return {"action": "scan_accounts", "running": True, "total_accounts": len(rows) if isinstance(rows, list) else None}
    pool = AccountPool()
    pool.scan()
    return {"action": "scan_accounts_local", "running": False, "total_accounts": len(pool.accounts), "active_accounts": pool.active_count()}


def list_accounts() -> dict:
    pool = AccountPool()
    pool.scan()
    return {
        "action": "list_accounts",
        "total_accounts": len(pool.accounts),
        "active_accounts": pool.active_count(),
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
        return {"action": "login_command", "account": safe_name, "account_dir": str(target_dir), "error": "codex_cli_missing", "codex_cli_error": CODEX_CLI_MISSING_MESSAGE}
    return {"action": "login_command", "account": safe_name, "account_dir": str(target_dir), "command": format_login_command(codex_cli, target_dir)}


def start_login(name: str) -> dict:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if auth_path.exists():
        return {"action": "start_login", "account": safe_name, "error": "account already has auth.json"}
    codex_cli = find_codex_cli()
    if not codex_cli:
        return {"action": "start_login", "account": safe_name, "error": "codex_cli_missing", "codex_cli_error": CODEX_CLI_MISSING_MESSAGE}
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = service_manager.RUNTIME_DIR / "login.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "CODEX_HOME": str(target_dir)}
    with open(log_path, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen([codex_cli, "login"], cwd=str(service_manager.RUNTIME_DIR), env=env, stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT)
    return {"action": "login_started", "account": safe_name, "account_dir": str(target_dir), "command": format_login_command(codex_cli, target_dir), "log_path": str(log_path), "pid": process.pid, "started": True}


def import_current(name: str) -> dict:
    safe_name = validate_account_name(name)
    source = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"
    if not source.exists():
        return {"action": "import_current", "account": safe_name, "error": f"not found: {source}"}
    target = account_dir(safe_name)
    auth_path = target / "auth.json"
    if auth_path.exists():
        return {"action": "import_current", "account": safe_name, "error": "account already has auth.json"}
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, auth_path)
    return {"action": "import_current", "account": safe_name, "account_dir": str(target)}


def load_account(name: str) -> Account:
    safe_name = validate_account_name(name)
    account = Account(safe_name, account_dir(safe_name) / "auth.json")
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
            return {"action": "delete_account", "running": True, "deleted": result.get("deleted") or safe_name, "trashed_to": result.get("trashed_to")}
    target = account_dir(safe_name)
    if not target.exists():
        return {"action": "delete_account_local", "running": False, "account": safe_name, "error": "account not found"}
    trash = target.parent / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    trashed = trash / f"{safe_name}-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.move(str(target), str(trashed))
    return {"action": "delete_account_local", "running": False, "deleted": safe_name, "trashed_to": str(trashed)}


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
    result = fetch_api(f"/api/accounts/{safe_name}/cooldown/clear", method="PUT") if proxy_status() else None
    return {"action": "clear_cooldown", "running": bool(result), "account": safe_name, "enabled": result.get("enabled") if isinstance(result, dict) else None, "error": None if isinstance(result, dict) else "proxy is offline"}


def clear_auth_error(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}/auth-error/clear", method="PUT")
        if isinstance(result, dict) and not result.get("error"):
            return {"action": "clear_auth_error", "running": True, "account": safe_name, "enabled": result.get("enabled"), "auth_error": result.get("auth_error")}
    account = load_account(safe_name)
    previous = account.auth_error
    account.auth_error = ""
    account.enabled = True
    account.save_meta()
    return {"action": "clear_auth_error_local", "running": False, "account": safe_name, "previous_auth_error": previous, "auth_error": ""}


def set_rotation_strategy(strategy: str) -> dict:
    return set_config(json.dumps({"rotation_strategy": strategy}))


def set_codex_stream_mode(mode: str) -> dict:
    return set_config(json.dumps({"codex_stream_mode": mode, "codex_stream_mode_user_set": True}))


def set_config(config_json: str) -> dict:
    try:
        updates = json.loads(config_json)
    except json.JSONDecodeError as e:
        return {"action": "set_config", "error": str(e)}
    if not isinstance(updates, dict):
        return {"action": "set_config", "error": "config must be an object"}
    unsupported = sorted(set(updates) - CONFIG_SET_KEYS)
    if unsupported:
        return {"action": "set_config", "error": f"unsupported config key: {', '.join(unsupported)}"}
    try:
        current = config.load()
        old_port = current.get("port")
        current.update(updates)
        config.save(current)
        updated = config.load()
    except config.ConfigError as e:
        return {"action": "set_config", "error": str(e)}
    return {"action": "set_config", "updated": True, "changed": {key: updated.get(key) for key in sorted(updates)}, "config": updated, "restart_required": old_port != updated.get("port")}


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
        "import-current": lambda: import_current(args.name),
        "toggle-account": lambda: toggle_account(args.name),
        "delete-account": lambda: delete_account(args.name),
        "refresh-token": lambda: refresh_token(args.name),
        "clear-cooldown": lambda: clear_cooldown(args.name),
        "clear-auth-error": lambda: clear_auth_error(args.name),
        "set-rotation-strategy": lambda: set_rotation_strategy(args.strategy),
        "set-codex-stream-mode": lambda: set_codex_stream_mode(args.stream_mode),
        "set-config": lambda: set_config(args.config_json),
        "menubar-login-status": service_manager.menubar_login_status,
        "enable-menubar-login": lambda: service_manager.set_menubar_login_item(True),
        "disable-menubar-login": lambda: service_manager.set_menubar_login_item(False),
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
