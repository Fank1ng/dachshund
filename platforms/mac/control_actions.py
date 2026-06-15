#!/usr/bin/env python3
"""Non-GUI actions used by the macOS app launcher and command shortcuts."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Optional
import urllib.error
import urllib.request

from account_manager import Account, AccountPool, account_dir, validate_account_name
import codex_config
import config
from login_manager import find_codex_cli
import service_manager


APP_URL = "http://127.0.0.1:8800/app"
STATUS_URL = "http://127.0.0.1:8800/api/status"
HEALTH_URL = "http://127.0.0.1:8800/api/health"
CODEX_AUTH_PATH = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"
CODEX_APP_PATH = Path("/Applications/Codex.app")
CODEX_CLI_INSTALL_HINT = "请先安装 Codex App，或确保 codex 命令在 PATH 中。"
UPDATE_LOCK_DIR = service_manager.RUNTIME_DIR / ".update.lock"

KEY_LABELS = {
    "action": "动作",
    "installed": "后台服务已安装",
    "loaded": "后台服务已加载",
    "needs_repair": "需要修复",
    "version_mismatch": "版本不一致",
    "migration_required": "需要迁移",
    "legacy_running": "旧后台正在运行",
    "enabled": "已启用",
    "mode": "模式",
    "product_mode": "运行模式",
    "running": "代理在线",
    "active_accounts": "可用账号数",
    "total_accounts": "账号总数",
    "source_dir": "源码目录",
    "runtime_dir": "运行目录",
    "restart_required": "需要重启",
    "command": "命令",
    "account": "账号",
    "account_dir": "账号目录",
    "deleted": "已删除账号",
    "trashed_to": "已移到",
    "accounts": "账号列表",
    "error": "错误",
    "log_path": "日志文件",
    "pid": "进程 ID",
    "started": "已启动",
    "refreshed": "已刷新",
    "auth_error": "认证异常",
    "previous_auth_error": "原异常状态",
    "previous_version": "更新前版本",
    "expected_version": "目标版本",
    "version": "当前版本",
    "bundle_version": "App 内置版本",
    "runtime_version": "运行目录版本",
    "proxy_version": "后台 API 版本",
    "manifest_ok": "Manifest 一致",
    "manifest_error": "Manifest 错误",
    "menubar_login": "菜单栏登录项",
    "token_usage_api_ok": "Token 汇总接口",
    "token_usage_events_api_ok": "Token 事件接口",
    "token_usage_schema_ok": "Token 捕获状态表结构",
    "frontend_restart_required": "需要重开前台",
    "updated": "已更新",
    "rolled_back": "已回滚",
    "backup_path": "备份路径",
    "restart_started": "已发起重启",
    "source_app": "App 入口",
    "app_bundle": "App 位置",
    "resource_runtime_dir": "App 内置运行资源",
    "accounts_dir": "账号目录",
    "config_path": "配置文件",
    "result_path": "结果文件",
    "python": "Python",
    "pythonpath": "Python 包路径",
    "installed_program": "LaunchAgent 程序",
    "codex_cli_found": "Codex CLI 已找到",
    "codex_cli": "Codex CLI",
    "codex_app_found": "Codex App 已找到",
    "codex_cli_error": "Codex 依赖提示",
    "runtime_exists": "运行目录已存在",
    "resource_runtime_exists": "App 内置资源已存在",
    "dependencies": "依赖项",
    "name": "名称",
    "email": "邮箱",
    "has_tokens": "已有令牌",
    "rate_limited": "冷却中",
}

VALUE_LABELS = {
    "already_running": "代理已在运行",
    "started_or_repaired": "已启动或修复",
    "apply_update": "应用更新",
    "enable_codex_proxy": "启用 Codex 代理",
    "disable_codex_proxy": "Codex 直连",
    "scan_accounts": "扫描账号",
    "scan_accounts_local": "本地扫描账号",
    "list_accounts": "列出账号",
    "login_command": "生成登录命令",
    "start_login": "打开登录页",
    "import_current": "导入当前账号",
    "toggle_account": "启用/禁用账号",
    "toggle_account_local": "本地启用/禁用账号",
    "delete_account": "删除账号",
    "delete_account_local": "本地删除账号",
    "refresh_token": "刷新账号令牌",
    "refresh_token_local": "本地刷新账号令牌",
    "clear_cooldown": "解除账号冷却",
    "clear_auth_error": "解除账号异常状态",
    "clear_auth_error_local": "本地解除账号异常状态",
    "show_paths": "查看路径与依赖",
    "login_started": "登录已启动",
    "request failed": "请求失败",
    "account already has auth.json": "账号已经存在 auth.json",
    "account not found": "账号不存在",
    "codex_pool_provider": "账号池代理",
    "partial_chatgpt_backend": "部分代理配置",
    "legacy_openai_provider": "旧版代理配置",
    "direct": "直连",
    "proxy is offline; cooldown is in-memory and clears when the proxy restarts": (
        "代理离线；冷却状态只保存在内存中，代理重启后会自然清除"
    ),
    "codex_cli_missing": "未找到 Codex CLI",
    "codex_app_missing": "未找到 Codex App",
    "update already in progress": "正在应用更新，请稍后再试",
    "set_config": "保存设置",
    "menubar_login_status": "菜单栏登录项状态",
    "set_menubar_login_item": "设置菜单栏登录项",
}

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
    url = f"http://127.0.0.1:8800{path}"
    try:
        request = urllib.request.Request(url, data=b"" if method != "GET" else None, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def proxy_status(timeout: float = 3.0) -> Optional[dict]:
    health = fetch_json_url(HEALTH_URL, timeout)
    if health and health.get("running"):
        return health
    return fetch_json_url(STATUS_URL, timeout)


def wait_for_proxy(timeout: float = 25.0, expected_version: Optional[str] = None) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = proxy_status(timeout=2)
        if status and (not expected_version or status.get("version") == expected_version):
            return status
        time.sleep(0.5)
    return None


def source_app_version(source_dir: Optional[str] = None) -> str:
    source = Path(source_dir).expanduser() if source_dir else service_manager._source_dir()
    proxy_file = service_manager._source_file(source, "proxy.py")
    return service_manager._proxy_version(proxy_file)


def _localized_value(value):
    if isinstance(value, bool):
        return "是" if value else "否"
    if value is None:
        return "无"
    if isinstance(value, str):
        if value.startswith("not found: "):
            return "未找到：" + value.removeprefix("not found: ")
        return VALUE_LABELS.get(value, value)
    if isinstance(value, list):
        return [_localized_value(item) for item in value]
    if isinstance(value, dict):
        return {
            KEY_LABELS.get(key, key): _localized_value(item)
            for key, item in value.items()
        }
    return value


def compact(data: dict) -> str:
    keys = (
        "action",
        "installed",
        "loaded",
        "needs_repair",
        "version_mismatch",
        "migration_required",
        "legacy_running",
        "enabled",
        "mode",
        "product_mode",
        "running",
        "active_accounts",
        "total_accounts",
        "source_dir",
        "runtime_dir",
        "restart_required",
        "command",
        "account",
        "account_dir",
        "deleted",
        "trashed_to",
        "accounts",
        "error",
        "log_path",
        "pid",
        "started",
        "source_app",
        "app_bundle",
        "resource_runtime_dir",
        "accounts_dir",
        "config_path",
        "result_path",
        "python",
        "pythonpath",
        "codex_cli_found",
        "codex_cli",
        "codex_app_found",
        "codex_cli_error",
        "runtime_exists",
        "resource_runtime_exists",
        "dependencies",
        "refreshed",
        "auth_error",
        "previous_auth_error",
        "previous_version",
        "expected_version",
        "version",
        "bundle_version",
        "runtime_version",
        "proxy_version",
        "manifest_ok",
        "manifest_error",
        "token_usage_api_ok",
        "token_usage_events_api_ok",
        "token_usage_schema_ok",
        "frontend_restart_required",
        "updated",
        "rolled_back",
        "backup_path",
        "restart_started",
    )
    localized = {
        KEY_LABELS.get(key, key): _localized_value(data.get(key))
        for key in keys
        if key in data
    }
    return json.dumps(localized, ensure_ascii=False, indent=2)


def render_output(data: dict, output_format: str = "pretty") -> str:
    if output_format == "json":
        return json.dumps(data, ensure_ascii=False, default=str)
    return compact(data)


def codex_dependency_status() -> dict:
    codex_cli = find_codex_cli()
    cli_found = bool(codex_cli)
    app_found = CODEX_APP_PATH.exists()
    return {
        "codex_cli_found": cli_found,
        "codex_cli": codex_cli or "",
        "codex_app_found": app_found,
        "codex_cli_error": "" if cli_found else CODEX_CLI_INSTALL_HINT,
    }


def runtime_status(source_dir: Optional[str] = None) -> dict:
    source = Path(source_dir).expanduser() if source_dir else service_manager._source_dir()
    integrity = service_manager.runtime_integrity(source=source, runtime=service_manager.RUNTIME_DIR)
    return {
        "runtime_exists": service_manager.RUNTIME_DIR.exists(),
        "resource_runtime_exists": source.exists(),
        "bundle_version": integrity.get("bundle_version", ""),
        "runtime_version": integrity.get("runtime_version", ""),
        "manifest_ok": integrity.get("ok", False),
        "manifest_error": integrity.get("error", ""),
        "manifest": integrity,
    }


def with_product_status(data: dict) -> dict:
    result = dict(data)
    result.update(codex_dependency_status())
    result.update(runtime_status(result.get("source_dir")))
    return result


def _service_matches_current_app(service: dict, proxy: Optional[dict], expected_version: str) -> bool:
    if not proxy:
        return False
    manifest = service.get("manifest") if isinstance(service.get("manifest"), dict) else {}
    if service.get("manifest_ok") is False or manifest.get("ok") is False:
        return False
    if service.get("needs_repair") or service.get("version_mismatch"):
        return False
    if service.get("migration_required") or service.get("legacy_running") or service.get("legacy_loaded"):
        return False
    if not service.get("installed") or not service.get("loaded"):
        return False
    if expected_version and proxy.get("version") != expected_version:
        return False
    usage = proxy.get("usage") if isinstance(proxy.get("usage"), dict) else {}
    if usage and usage.get("observed_columns_ok") is False:
        return False
    return True


def repair() -> dict:
    proxy_before = proxy_status(timeout=2)
    service = service_manager.status()
    codex = codex_config.ensure_enabled(True)
    expected_version = service.get("expected_version") or source_app_version(service.get("source_dir"))
    previous_version = proxy_before.get("version") if proxy_before else service.get("running_version")
    if _service_matches_current_app(service, proxy_before, expected_version):
        return with_product_status({
            "action": "already_running",
            "installed": service.get("installed"),
            "loaded": service.get("loaded"),
            "needs_repair": service.get("needs_repair"),
            "version_mismatch": service.get("version_mismatch"),
            "migration_required": service.get("migration_required"),
            "legacy_running": service.get("legacy_running"),
            "manifest_ok": service.get("manifest_ok"),
            "manifest_error": service.get("manifest_error"),
            "manifest": service.get("manifest"),
            "enabled": codex.get("enabled"),
            "mode": codex.get("mode"),
            "running": True,
            "active_accounts": proxy_before.get("active_accounts"),
            "total_accounts": proxy_before.get("total_accounts"),
            "version": proxy_before.get("version"),
            "previous_version": previous_version,
            "expected_version": expected_version,
            "updated": False,
            "restart_started": False,
            "source_dir": service.get("source_dir"),
            "runtime_dir": service.get("runtime_dir"),
            "restart_required": False,
        })
    try:
        service = service_manager.install(sync=True)
    except service_manager.RuntimeSyncError as e:
        return with_product_status({
            "action": "started_or_repaired",
            "installed": service.get("installed"),
            "loaded": service.get("loaded"),
            "needs_repair": service.get("needs_repair"),
            "version_mismatch": service.get("version_mismatch"),
            "migration_required": service.get("migration_required"),
            "legacy_running": service.get("legacy_running"),
            "manifest_ok": service.get("manifest_ok"),
            "manifest_error": service.get("manifest_error"),
            "manifest": service.get("manifest"),
            "enabled": codex.get("enabled"),
            "mode": codex.get("mode"),
            "running": bool(proxy_before),
            "version": previous_version,
            "previous_version": previous_version,
            "expected_version": expected_version,
            "updated": False,
            "restart_started": False,
            "source_dir": service.get("source_dir"),
            "runtime_dir": service.get("runtime_dir"),
            "restart_required": False,
            "backup_path": str(e.backup_path) if e.backup_path else None,
            "error": str(e),
            "restore_error": e.restore_error,
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
        "migration_required": service.get("migration_required"),
        "legacy_running": service.get("legacy_running"),
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


def repair_open_web() -> dict:
    result = repair()
    subprocess.run(["open", APP_URL], check=False)
    return result


def repair_open_codex() -> dict:
    result = repair()
    if not CODEX_APP_PATH.exists():
        result["error"] = "codex_app_missing"
        result["codex_cli_error"] = "请先安装 Codex App，再使用“打开 Codex”。"
        return result
    subprocess.run(["open", "-a", "Codex"], check=False)
    return result


def restart_proxy() -> dict:
    if not service_manager.restart():
        service_manager.ensure_running()
    proxy = wait_for_proxy()
    return {
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
    }


def _acquire_update_lock() -> Optional[Path]:
    service_manager.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        UPDATE_LOCK_DIR.mkdir()
        (UPDATE_LOCK_DIR / "pid").write_text(str(os.getpid()), encoding="utf-8")
        return UPDATE_LOCK_DIR
    except FileExistsError:
        return None


def _release_update_lock(lock: Optional[Path]) -> None:
    if not lock:
        return
    shutil.rmtree(lock, ignore_errors=True)


def _post_update_validation(proxy: Optional[dict], expected_version: str) -> tuple[bool, dict, str]:
    service = service_manager.status()
    integrity = service.get("manifest") or service_manager.runtime_integrity()
    proxy_version = proxy.get("version") if proxy else ""
    details = {
        "service": service,
        "manifest": integrity,
        "bundle_version": integrity.get("bundle_version") or service.get("bundle_version") or expected_version,
        "runtime_version": integrity.get("runtime_version") or service.get("runtime_version") or "",
        "proxy_version": proxy_version,
        "manifest_ok": bool(integrity.get("ok")),
        "manifest_error": integrity.get("error", ""),
        "token_usage_api_ok": False,
        "token_usage_events_api_ok": False,
        "token_usage_schema_ok": False,
    }
    if not proxy:
        return False, details, f"proxy did not report expected version {expected_version or '-'}"
    if expected_version and proxy_version != expected_version:
        return False, details, f"proxy_version_mismatch: expected {expected_version}, observed {proxy_version or '-'}"
    if service.get("needs_repair") or service.get("migration_required") or service.get("version_mismatch"):
        return False, details, f"launchagent_source_mismatch: {service.get('repair_reasons') or 'service needs repair'}"
    expected_program = str(service_manager.RUNTIME_DIR / "proxy.py")
    if service.get("installed_program") and Path(str(service.get("installed_program"))).expanduser().resolve() != Path(expected_program).resolve():
        return False, details, f"launchagent_source_mismatch: {service.get('installed_program')}"
    if not integrity.get("ok"):
        return False, details, f"runtime_manifest_mismatch: {integrity.get('error') or integrity}"
    token_usage = fetch_json_url("http://127.0.0.1:8800/api/token-usage", timeout=3)
    token_events = fetch_json_url("http://127.0.0.1:8800/api/token-usage/events?limit=1", timeout=3)
    usage_diag = proxy.get("usage") if isinstance(proxy.get("usage"), dict) else {}
    details["token_usage_api_ok"] = isinstance(token_usage, dict) and token_usage.get("history_available") is True
    details["token_usage_events_api_ok"] = isinstance(token_events, dict) and isinstance(token_events.get("events"), list)
    details["token_usage_schema_ok"] = bool(usage_diag.get("observed_columns_ok"))
    if not details["token_usage_api_ok"]:
        return False, details, "token_usage_api_missing"
    if not details["token_usage_events_api_ok"]:
        return False, details, "token_usage_events_api_missing"
    if not details["token_usage_schema_ok"]:
        return False, details, "token_usage_schema_missing_observed_columns"
    return True, details, ""


def apply_update() -> dict:
    lock = _acquire_update_lock()
    if not lock:
        return {
            "action": "apply_update",
            "updated": False,
            "rolled_back": False,
            "error": "update already in progress",
        }

    backup_path = None
    previous_proxy = proxy_status(timeout=2)
    previous_version = previous_proxy.get("version") if previous_proxy else None
    expected_version = source_app_version()
    restart_started = False
    service = {}
    proxy = None
    error = ""
    rolled_back = False
    updated = False
    try:
        try:
            service = service_manager.install(sync=True, keep_backup=True)
            sync_result = service.get("sync") or {}
            backup_path = sync_result.get("backup_path")
        except service_manager.RuntimeSyncError as e:
            return {
                "action": "apply_update",
                "installed": None,
                "loaded": None,
                "needs_repair": None,
                "running": False,
                "version": previous_version,
                "previous_version": previous_version,
                "expected_version": expected_version,
                "updated": False,
                "rolled_back": e.restored,
                "backup_path": str(e.backup_path) if e.backup_path else None,
                "error": str(e),
                "restore_error": e.restore_error,
            }

        if not service.get("restart_required"):
            restart_started = service_manager.restart()
        proxy = wait_for_proxy(expected_version=expected_version or None)
        validation_ok, validation, validation_error = _post_update_validation(proxy, expected_version)
        updated = validation_ok
        if updated:
            service_manager.cleanup_runtime_backup(backup_path)
            backup_path = None
        else:
            error = validation_error or f"proxy did not report expected version {expected_version or '-'}"
            if backup_path:
                try:
                    service_manager.rollback_runtime(backup_path)
                    rolled_back = True
                    if not service.get("restart_required"):
                        service_manager.restart()
                except Exception as e:
                    error += f"; rollback failed: {e}"
    finally:
        _release_update_lock(lock)

    validation = locals().get("validation") or {}
    result = {
        "action": "apply_update",
        "installed": service.get("installed"),
        "loaded": service.get("loaded"),
        "needs_repair": service.get("needs_repair"),
        "running": bool(proxy),
        "active_accounts": proxy.get("active_accounts") if proxy else None,
        "total_accounts": proxy.get("total_accounts") if proxy else None,
        "version": proxy.get("version") if proxy else None,
        "bundle_version": validation.get("bundle_version") or expected_version,
        "runtime_version": validation.get("runtime_version") or service.get("runtime_version"),
        "proxy_version": validation.get("proxy_version") or (proxy.get("version") if proxy else None),
        "manifest_ok": bool(validation.get("manifest_ok")),
        "manifest_error": validation.get("manifest_error", ""),
        "token_usage_api_ok": bool(validation.get("token_usage_api_ok")),
        "token_usage_events_api_ok": bool(validation.get("token_usage_events_api_ok")),
        "token_usage_schema_ok": bool(validation.get("token_usage_schema_ok")),
        "frontend_restart_required": bool(updated and previous_version and previous_version != expected_version),
        "previous_version": previous_version,
        "expected_version": expected_version,
        "updated": updated,
        "rolled_back": rolled_back,
        "backup_path": backup_path,
        "restart_started": restart_started,
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "restart_required": service.get("restart_required"),
    }
    if error:
        result["error"] = error
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
    subprocess.run(["open", str(service_manager.LOG_PATH)], check=False)
    return {"log_path": str(service_manager.LOG_PATH)}


def show_paths() -> dict:
    app_bundle = service_manager._app_bundle_dir()
    source_dir = service_manager._source_dir()
    service = service_manager.status()
    integrity = service.get("manifest") or service_manager.runtime_integrity(source=source_dir, runtime=service_manager.RUNTIME_DIR)
    proxy = proxy_status(timeout=1)
    result = {
        "action": "show_paths",
        "source_app": str(app_bundle),
        "app_bundle": str(app_bundle),
        "resource_runtime_dir": str(source_dir),
        "source_dir": str(source_dir),
        "runtime_dir": str(service_manager.RUNTIME_DIR),
        "accounts_dir": str(account_dir("a").parent),
        "config_path": str(service_manager.RUNTIME_DIR / "config.json"),
        "log_path": str(service_manager.LOG_PATH),
        "result_path": str(service_manager.RUNTIME_DIR / "control-result.txt"),
        "python": str(service_manager._python_executable()),
        "pythonpath": str(service_manager._pythonpath() or ""),
        "bundle_version": integrity.get("bundle_version") or service.get("bundle_version", ""),
        "runtime_version": integrity.get("runtime_version") or service.get("runtime_version", ""),
        "proxy_version": proxy.get("version") if proxy else "",
        "manifest_ok": integrity.get("ok", False),
        "manifest_error": integrity.get("error", ""),
        "manifest": integrity,
        "installed_program": service.get("installed_program", ""),
        "dependencies": [
            "系统 Python 或 App/运行目录内置 Python",
            "aiohttp（系统安装或运行目录 vendor）",
            "platforms/mac/control_actions.py",
            "platforms/mac/core/account_manager.py",
            "platforms/mac/core/codex_config.py",
            "platforms/mac/service_manager.py",
            "platforms/mac/core/config.py",
            "platforms/mac/core/proxy.py / platforms/mac/core/proxy_core.py",
            "platforms/mac/core/static/index.html",
            "accounts/{name}/auth.json",
            "accounts/{name}/account.json",
        ],
    }
    return with_product_status(result)


def scan_accounts() -> dict:
    proxy = proxy_status()
    if proxy:
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:8800/api/accounts/scan",
                data=b"",
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                rows = json.loads(response.read().decode("utf-8"))
            return {
                "action": "scan_accounts",
                "running": True,
                "total_accounts": len(rows) if isinstance(rows, list) else None,
            }
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
    pool = AccountPool()
    pool.scan()
    return {
        "action": "scan_accounts_local",
        "running": False,
        "total_accounts": len(pool.accounts),
        "active_accounts": pool.active_count(),
    }


def list_accounts() -> dict:
    pool = AccountPool()
    pool.scan()
    rows = [
        {
            "name": account.name,
            "email": account.email,
            "enabled": account.enabled,
            "has_tokens": bool(account.access_token),
            "auth_error": account.auth_error,
            "rate_limited": account.is_rate_limited,
        }
        for account in pool.accounts
    ]
    return {
        "action": "list_accounts",
        "total_accounts": len(rows),
        "active_accounts": pool.active_count(),
        "accounts": rows,
    }


def login_command(name: str) -> dict:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    target_dir.mkdir(parents=True, exist_ok=True)
    codex_cli = find_codex_cli()
    if not codex_cli:
        return {
            "action": "login_command",
            "account": safe_name,
            "account_dir": str(target_dir),
            "error": "codex_cli_missing",
            "codex_cli_error": CODEX_CLI_INSTALL_HINT,
        }
    command = f"CODEX_HOME={target_dir} {codex_cli} login"
    try:
        subprocess.run(["pbcopy"], input=command, text=True, check=False)
    except Exception:
        pass
    return {
        "action": "login_command",
        "account": safe_name,
        "account_dir": str(target_dir),
        "command": command,
    }


def start_login(name: str) -> dict:
    safe_name = validate_account_name(name)
    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if auth_path.exists():
        return {"action": "start_login", "account": safe_name, "error": "account already has auth.json"}

    codex_cli = find_codex_cli()
    if not codex_cli:
        return {
            "action": "start_login",
            "account": safe_name,
            "error": "codex_cli_missing",
            "codex_cli_error": CODEX_CLI_INSTALL_HINT,
        }

    target_dir.mkdir(parents=True, exist_ok=True)
    command = f"CODEX_HOME={target_dir} {codex_cli} login"
    log_path = service_manager.RUNTIME_DIR / "login.log"
    env = {**os.environ, "CODEX_HOME": str(target_dir)}
    with open(log_path, "a") as log_file:
        log_file.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting login for {safe_name}\n")
        process = subprocess.Popen(
            [codex_cli, "login"],
            cwd=str(service_manager.RUNTIME_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    try:
        subprocess.run(["pbcopy"], input=command, text=True, check=False)
    except Exception:
        pass
    return {
        "action": "login_started",
        "account": safe_name,
        "account_dir": str(target_dir),
        "command": command,
        "log_path": str(log_path),
        "pid": process.pid,
        "started": True,
    }


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
    return {
        "action": "import_current",
        "account": safe_name,
        "account_dir": str(target_dir),
    }


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
            return {
                "action": "toggle_account",
                "running": True,
                "account": safe_name,
                "enabled": result.get("enabled"),
            }
    account = load_account(safe_name)
    account.enabled = not account.enabled
    account.save_meta()
    return {
        "action": "toggle_account_local",
        "running": False,
        "account": safe_name,
        "enabled": account.enabled,
    }


def delete_account(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}", method="DELETE")
        if isinstance(result, dict) and not result.get("error"):
            return {
                "action": "delete_account",
                "running": True,
                "deleted": result.get("deleted") or safe_name,
                "trashed_to": result.get("trashed_to"),
            }

    target_dir = account_dir(safe_name)
    if not target_dir.exists():
        return {
            "action": "delete_account_local",
            "running": False,
            "account": safe_name,
            "error": "account not found",
        }

    trash_dir = account_dir("a").parent / ".trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    trashed = trash_dir / f"{safe_name}-{time.strftime('%Y%m%d-%H%M%S')}"
    suffix = 1
    while trashed.exists():
        trashed = trash_dir / f"{safe_name}-{time.strftime('%Y%m%d-%H%M%S')}-{suffix}"
        suffix += 1
    shutil.move(str(target_dir), str(trashed))
    running = bool(proxy_status())
    if running:
        fetch_api("/api/accounts/scan", method="POST")
    return {
        "action": "delete_account_local",
        "running": running,
        "deleted": safe_name,
        "trashed_to": str(trashed),
    }


def refresh_token(name: str) -> dict:
    safe_name = validate_account_name(name)
    if proxy_status():
        result = fetch_api(f"/api/accounts/{safe_name}/refresh", method="POST", timeout=45)
        if isinstance(result, dict) and not result.get("error"):
            account = result.get("account") or {}
            return {
                "action": "refresh_token",
                "running": True,
                "account": safe_name,
                "refreshed": result.get("refreshed"),
                "enabled": account.get("enabled"),
                "auth_error": account.get("auth_error"),
            }
    account = load_account(safe_name)
    ok = asyncio.run(account.refresh())
    return {
        "action": "refresh_token_local",
        "running": False,
        "account": safe_name,
        "refreshed": ok,
        "enabled": account.enabled,
        "auth_error": account.auth_error,
    }


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
        return {
            "action": "clear_cooldown",
            "running": True,
            "account": safe_name,
            "enabled": result.get("enabled"),
        }
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
            return {
                "action": "clear_auth_error",
                "running": True,
                "account": safe_name,
                "enabled": result.get("enabled"),
                "auth_error": result.get("auth_error"),
            }

    target_dir = account_dir(safe_name)
    auth_path = target_dir / "auth.json"
    if not auth_path.exists():
        return {
            "action": "clear_auth_error_local",
            "running": False,
            "account": safe_name,
            "error": "account not found",
        }
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


def status() -> dict:
    service = service_manager.status()
    menubar = service_manager.menubar_login_status()
    codex = codex_config.status()
    proxy = proxy_status()
    cfg = config.load()
    return with_product_status({
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
        "migration_required": service.get("migration_required"),
        "legacy_running": service.get("legacy_running"),
        "installed_program": service.get("installed_program"),
        "source_dir": service.get("source_dir"),
        "runtime_dir": service.get("runtime_dir"),
        "menubar_login": menubar,
        "menubar_login_enabled": menubar.get("enabled"),
    })


def set_codex_stream_mode(mode: str) -> dict:
    if mode not in {"hybrid", "buffered", "realtime"}:
        return {
            "action": "set_codex_stream_mode",
            "error": "codex_stream_mode must be hybrid, buffered, or realtime",
            "codex_stream_mode": mode,
        }
    cfg = config.load()
    previous = cfg.get("codex_stream_mode")
    cfg["codex_stream_mode"] = mode
    config.save(cfg)
    return {
        "action": "set_codex_stream_mode",
        "codex_stream_mode": mode,
        "previous_codex_stream_mode": previous,
        "changed": previous != mode,
    }


def set_rotation_strategy(strategy: str) -> dict:
    if strategy not in {"round_robin", "most_available"}:
        return {
            "action": "set_rotation_strategy",
            "error": "rotation_strategy must be round_robin or most_available",
            "strategy": strategy,
        }
    cfg = config.load()
    previous = cfg.get("rotation_strategy")
    cfg["rotation_strategy"] = strategy
    config.save(cfg)
    return {
        "action": "set_rotation_strategy",
        "strategy": strategy,
        "previous_strategy": previous,
        "changed": previous != strategy,
    }


def set_config(config_json: str) -> dict:
    try:
        updates = json.loads(config_json or "{}")
    except json.JSONDecodeError as e:
        return {"action": "set_config", "error": f"invalid config json: {e}"}
    if not isinstance(updates, dict):
        return {"action": "set_config", "error": "config update must be an object"}

    unknown = sorted(set(updates) - CONFIG_SET_KEYS)
    if unknown:
        return {
            "action": "set_config",
            "error": "unsupported config keys: " + ", ".join(unknown),
            "unsupported_keys": unknown,
        }

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

    changed = {
        key: updated.get(key)
        for key in sorted(updates)
        if key in updated
    }
    return {
        "action": "set_config",
        "updated": True,
        "changed": changed,
        "config": updated,
        "restart_required": old_port != updated.get("port"),
    }


def menubar_login_status() -> dict:
    return service_manager.menubar_login_status()


def set_menubar_login_item(enabled: bool) -> dict:
    try:
        return service_manager.set_menubar_login_item(enabled)
    except RuntimeError as e:
        return {"action": "set_menubar_login_item", "error": str(e), "enabled": enabled}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
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
        ),
    )
    parser.add_argument("--name", default="")
    parser.add_argument("--strategy", default="")
    parser.add_argument("--stream-mode", default="")
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--format", choices=("pretty", "json"), default="pretty")
    args = parser.parse_args()

    actions = {
        "status": status,
        "repair": repair,
        "repair-open-web": repair_open_web,
        "repair-open-codex": repair_open_codex,
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
        "menubar-login-status": menubar_login_status,
        "enable-menubar-login": lambda: set_menubar_login_item(True),
        "disable-menubar-login": lambda: set_menubar_login_item(False),
    }
    print(render_output(actions[args.action](), args.format))


if __name__ == "__main__":
    main()
