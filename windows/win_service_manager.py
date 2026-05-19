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
    supervisor_pid = _read_pid(SUPERVISOR_PID_PATH)
    proxy_pid = _read_pid(PROXY_PID_PATH)
    supervisor_running = _pid_running(supervisor_pid)
    proxy_process_running = _pid_running(proxy_pid)
    return {
        "supported": _is_windows(),
        "task_name": TASK_NAME,
        "installed": installed,
        "loaded": installed,
        "running": bool(proxy) or proxy_process_running,
        "install_mode": "scheduled_task" if installed else ("process" if supervisor_running else None),
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(_source_dir()),
        "log_path": str(LOG_PATH),
        "supervisor_pid": supervisor_pid,
        "supervisor_running": supervisor_running,
        "proxy_pid": proxy_pid,
        "proxy_process_running": proxy_process_running,
        "proxy": proxy,
    }


def install(*, source_runtime: Optional[Path] = None, service_command: Optional[list[str]] = None) -> dict:
    _require_windows()
    source_runtime = source_runtime or _source_dir()
    service_command = service_command or _default_service_command()
    sync_runtime(source_runtime)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.touch(exist_ok=True)
    task_error = None
    try:
        _create_task(service_command)
        _start_task()
    except RuntimeError as exc:
        task_error = str(exc)
        _start_supervisor_process(service_command)
    result = status()
    result["action"] = "install"
    if task_error:
        result["task_error"] = task_error
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
    task_error = None
    stop()
    try:
        if service_command and _task_query().returncode != 0:
            _create_task(service_command)
        _start_task()
    except RuntimeError as exc:
        task_error = str(exc)
        if not service_command:
            raise
        _start_supervisor_process(service_command)
    result = status()
    result["action"] = "restart"
    if task_error:
        result["task_error"] = task_error
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
    if getattr(sys, "frozen", False):
        runtime = Path(sys.executable).resolve().parent / "runtime"
        if runtime.exists():
            return runtime
    return Path(__file__).resolve().parent


def _create_task(service_command: list[str]) -> None:
    command = command_line(service_command)
    candidates = [
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
            "/RU",
            _current_user(),
            "/F",
        ],
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
    ]
    errors = []
    for args in candidates:
        result = _run(args, check=False)
        if result.returncode == 0:
            return
        errors.append(_process_message(result) or f"exit code {result.returncode}")
    raise RuntimeError("; ".join(errors) or "failed to create scheduled task")


def _start_task() -> None:
    result = _run(["schtasks", "/Run", "/TN", TASK_NAME], check=False)
    if result.returncode != 0:
        raise RuntimeError(_process_message(result) or "failed to start scheduled task")


def _start_supervisor_process(service_command: list[str]) -> None:
    if _pid_running(_read_pid(SUPERVISOR_PID_PATH)):
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.touch(exist_ok=True)
    env = {
        **os.environ,
        CONFIG_DIR_ENV: str(RUNTIME_DIR),
        SOURCE_DIR_ENV: str(_source_dir()),
        "PYTHONUNBUFFERED": "1",
    }
    flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    with open(LOG_PATH, "a", encoding="utf-8", buffering=1) as log:
        process = subprocess.Popen(
            [str(arg) for arg in service_command],
            cwd=str(RUNTIME_DIR),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    SUPERVISOR_PID_PATH.write_text(str(process.pid))
    time.sleep(1)
    if process.poll() is not None:
        raise RuntimeError(f"failed to start supervisor process: exit code {process.returncode}")


def _task_query() -> subprocess.CompletedProcess:
    if not _is_windows():
        return subprocess.CompletedProcess([], 1, "", "not Windows")
    return _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", "/V"], check=False)


def _taskkill(pid: Optional[int]) -> None:
    if not pid:
        return
    _run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)


def _pid_running(pid: Optional[int]) -> bool:
    if not pid or not _is_windows():
        return False
    result = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], check=False)
    return result.returncode == 0 and str(pid) in (result.stdout or "")


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
    result = subprocess.run(args, capture_output=True, text=True, stdin=subprocess.DEVNULL)
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


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN")
    username = os.environ.get("USERNAME")
    if domain and username:
        return f"{domain}\\{username}"
    return username or os.getlogin()
