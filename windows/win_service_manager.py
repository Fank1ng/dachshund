"""Windows Scheduled Task helpers for Codex Proxy Control."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Optional


TASK_NAME = "CodexProxyApi"
CONFIG_DIR_ENV = "CODEX_PROXY_CONFIG_DIR"
SOURCE_DIR_ENV = "CODEX_PROXY_SOURCE_DIR"
RUNTIME_DIR = Path(
    os.environ.get(CONFIG_DIR_ENV)
    or (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "codexproxyapi")
).expanduser()
LOG_PATH = RUNTIME_DIR / "proxy.log"
SUPERVISOR_PID_PATH = RUNTIME_DIR / "supervisor.pid"
PROXY_PID_PATH = RUNTIME_DIR / "proxy.pid"

COPY_FILES = {
    "account_manager.py",
    "codex_config.py",
    "config.py",
    "config.json",
    "login_manager.py",
    "proxy.py",
    "proxy_core.py",
    "quota_tracker.py",
    "requirements.txt",
    "service_manager.py",
}
COPY_DIRS = {"static"}
ACCOUNT_FILES = {"auth.json", "account.json", "quota.json"}


def status() -> dict:
    installed = _task_query().returncode == 0 if _is_windows() else False
    proxy = _proxy_health()
    return {
        "supported": _is_windows(),
        "task_name": TASK_NAME,
        "installed": installed,
        "loaded": installed,
        "running": bool(proxy),
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(_source_dir()),
        "log_path": str(LOG_PATH),
        "supervisor_pid": _read_pid(SUPERVISOR_PID_PATH),
        "proxy_pid": _read_pid(PROXY_PID_PATH),
        "proxy": proxy,
    }


def install(*, source_runtime: Optional[Path] = None, service_command: Optional[list[str]] = None) -> dict:
    _require_windows()
    source_runtime = source_runtime or _source_dir()
    service_command = service_command or _default_service_command()
    sync_runtime(source_runtime)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.touch(exist_ok=True)
    _create_task(service_command)
    _start_task()
    result = status()
    result["action"] = "install"
    return result


def uninstall() -> dict:
    _require_windows()
    stop()
    _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=False)
    result = status()
    result["action"] = "uninstall"
    return result


def stop() -> dict:
    _require_windows()
    _run(["schtasks", "/End", "/TN", TASK_NAME], check=False)
    _taskkill(_read_pid(PROXY_PID_PATH))
    _taskkill(_read_pid(SUPERVISOR_PID_PATH))
    result = status()
    result["action"] = "stop"
    return result


def restart(*, source_runtime: Optional[Path] = None, service_command: Optional[list[str]] = None) -> dict:
    _require_windows()
    if source_runtime:
        sync_runtime(source_runtime)
    if service_command and _task_query().returncode != 0:
        _create_task(service_command)
    else:
        stop()
    _start_task()
    result = status()
    result["action"] = "restart"
    return result


def sync_runtime(source_runtime: Path) -> dict:
    source = source_runtime.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"runtime source not found: {source}")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for name in COPY_FILES:
        src = source / name
        if not src.exists():
            continue
        dst = RUNTIME_DIR / name
        if name == "config.json" and dst.exists():
            continue
        shutil.copy2(src, dst)
    for name in COPY_DIRS:
        src = source / name
        if not src.exists():
            continue
        dst = RUNTIME_DIR / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    _sync_accounts(source / "accounts", RUNTIME_DIR / "accounts")
    _assert_no_packaged_credentials(RUNTIME_DIR)
    return {"action": "sync_runtime", "runtime_dir": str(RUNTIME_DIR), "source_dir": str(source)}


def command_line(args: Iterable[str]) -> str:
    return subprocess.list2cmdline([str(arg) for arg in args])


def _default_service_command() -> list[str]:
    return [sys.executable]


def _source_dir() -> Path:
    configured = os.environ.get(SOURCE_DIR_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    return Path(__file__).resolve().parent


def _create_task(service_command: list[str]) -> None:
    command = command_line(service_command)
    result = _run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            command,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(_process_message(result) or "failed to create scheduled task")


def _start_task() -> None:
    result = _run(["schtasks", "/Run", "/TN", TASK_NAME], check=False)
    if result.returncode != 0:
        raise RuntimeError(_process_message(result) or "failed to start scheduled task")


def _task_query() -> subprocess.CompletedProcess:
    if not _is_windows():
        return subprocess.CompletedProcess([], 1, "", "not Windows")
    return _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"], check=False)


def _taskkill(pid: Optional[int]) -> None:
    if not pid:
        return
    _run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)


def _read_pid(path: Path) -> Optional[int]:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _sync_accounts(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for account_dir in source.iterdir():
        if not account_dir.is_dir():
            continue
        destination = target / account_dir.name
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ACCOUNT_FILES:
            src = account_dir / filename
            dst = destination / filename
            if src.exists() and src.is_file() and not dst.exists():
                shutil.copy2(src, dst)


def _assert_no_packaged_credentials(runtime: Path) -> None:
    for path in runtime.rglob("auth.json"):
        try:
            if (runtime / "accounts").resolve() in path.resolve().parents:
                continue
        except OSError:
            pass
        raise RuntimeError(f"refusing runtime with credential file: {path}")


def _proxy_health() -> Optional[dict]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8800/api/health", timeout=2) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return None


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(_process_message(result) or f"command failed: {args[0]}")
    return result


def _process_message(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout or "").strip()


def _is_windows() -> bool:
    return sys.platform == "win32"


def _require_windows() -> None:
    if not _is_windows():
        raise RuntimeError("Windows Scheduled Task support is only available on Windows")
