"""Windows scheduled-task helpers for Dachshund."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from version import APP_VERSION

LABEL = "Dachshund"
TRAY_LABEL = "Dachshund Tray"
SOURCE_DIR_ENV = "CODEX_PROXY_SOURCE_DIR"
APP_EXEC_ENV = "CODEX_PROXY_APP_EXECUTABLE"
CONFIG_DIR_ENV = "CODEX_PROXY_CONFIG_DIR"
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
RUNTIME_DIR = Path(os.environ.get(CONFIG_DIR_ENV) or LOCALAPPDATA / "dachshund")
LOG_PATH = RUNTIME_DIR / "proxy.log"


class RuntimeSyncError(RuntimeError):
    pass


def status() -> dict:
    installed = _task_exists(LABEL)
    running = _task_running(LABEL)
    return {
        "supported": sys.platform == "win32",
        "platform": "win32",
        "label": LABEL,
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(_source_dir()),
        "installed": installed,
        "loaded": running,
        "enabled": installed,
        "expected_program": str(RUNTIME_DIR / "proxy.py"),
        "installed_program": str(RUNTIME_DIR / "proxy.py") if installed else "",
        "expected_version": APP_VERSION,
        "running_version": APP_VERSION if running else "",
        "bundle_version": APP_VERSION,
        "runtime_version": APP_VERSION,
        "manifest_ok": None,
        "manifest_error": "",
        "log_path": str(LOG_PATH),
        "menubar_login": menubar_login_status(),
        "menubar_login_enabled": menubar_login_status().get("enabled"),
    }


def install(*, sync: bool = True, keep_backup: bool = False) -> dict:
    if sync or not (RUNTIME_DIR / "proxy.py").exists():
        _sync_runtime_dir()
    _run(_create_proxy_task_args())
    _run(["schtasks", "/Run", "/TN", LABEL], check=False)
    return {**status(), "installed": True}


def uninstall() -> dict:
    _run(["schtasks", "/End", "/TN", LABEL], check=False)
    _run(["schtasks", "/Delete", "/TN", LABEL, "/F"], check=False)
    return {**status(), "uninstalled": True}


def restart() -> bool:
    _run(["schtasks", "/End", "/TN", LABEL], check=False)
    return _run(["schtasks", "/Run", "/TN", LABEL], check=False).returncode == 0


def ensure_running() -> dict:
    current = status()
    if current.get("loaded"):
        return current
    if not current.get("installed"):
        return install()
    _run(["schtasks", "/Run", "/TN", LABEL], check=False)
    return status()


def menubar_login_status() -> dict:
    return {
        "supported": True,
        "enabled": _task_exists(TRAY_LABEL),
        "label": TRAY_LABEL,
    }


def set_menubar_login_item(enabled: bool) -> dict:
    if enabled:
        exe = os.environ.get(APP_EXEC_ENV) or ""
        if not exe:
            return {"action": "set_menubar_login_item", "enabled": False, "error": f"{APP_EXEC_ENV} missing"}
        _run(_create_tray_task_args(exe))
    else:
        _run(["schtasks", "/Delete", "/TN", TRAY_LABEL, "/F"], check=False)
    return {"action": "set_menubar_login_item", **menubar_login_status()}


def runtime_integrity(source: Path | None = None, runtime: Path | None = None) -> dict:
    return {"ok": True, "bundle_version": APP_VERSION, "runtime_version": APP_VERSION}


def _create_proxy_task_args() -> list[str]:
    python = _python_executable()
    proxy = RUNTIME_DIR / "proxy.py"
    command = f'"{python}" "{proxy}"'
    return ["schtasks", "/Create", "/TN", LABEL, "/SC", "ONLOGON", "/TR", command, "/F"]


def _create_tray_task_args(exe: str) -> list[str]:
    return ["schtasks", "/Create", "/TN", TRAY_LABEL, "/SC", "ONLOGON", "/TR", f'"{exe}" --menubar-only', "/F"]


def _task_exists(name: str) -> bool:
    return _run(["schtasks", "/Query", "/TN", name], check=False).returncode == 0


def _task_running(name: str) -> bool:
    result = _run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"], check=False)
    return result.returncode == 0 and "Status: Running" in result.stdout


def _sync_runtime_dir() -> None:
    source = _source_dir()
    core = source / "src" / "core" if (source / "src" / "core").is_dir() else source
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for file in core.glob("*.py"):
        shutil.copy2(file, RUNTIME_DIR / file.name)
    for name in ("VERSION", "requirements.txt"):
        path = source / name
        if path.exists():
            shutil.copy2(path, RUNTIME_DIR / name)
    static = core / "static"
    if static.is_dir():
        target = RUNTIME_DIR / "static"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(static, target)
    shutil.copy2(Path(__file__), RUNTIME_DIR / "service_manager.py")


def _source_dir() -> Path:
    return Path(os.environ.get(SOURCE_DIR_ENV) or Path(__file__).resolve().parents[2]).expanduser()


def _python_executable() -> str:
    return os.environ.get("PYTHON") or sys.executable


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result
