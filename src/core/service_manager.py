"""Fallback service manager for platforms without a platform module on PYTHONPATH."""

import sys
from pathlib import Path

from config import CONFIG_DIR
from version import APP_VERSION

LABEL = "com.fank1ng.dachshund"
RUNTIME_DIR = CONFIG_DIR
LOG_PATH = RUNTIME_DIR / "proxy.log"


class RuntimeSyncError(RuntimeError):
    pass


def status() -> dict:
    return {
        "supported": False,
        "platform": sys.platform,
        "label": LABEL,
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(Path(__file__).resolve().parent),
        "installed": False,
        "loaded": False,
        "expected_version": APP_VERSION,
        "running_version": "",
        "bundle_version": APP_VERSION,
        "runtime_version": APP_VERSION,
        "manifest_ok": None,
        "manifest_error": "",
        "log_path": str(LOG_PATH),
    }


def install(*, sync: bool = True, keep_backup: bool = False) -> dict:
    raise RuntimeError(f"background service is not implemented for {sys.platform}")


def uninstall() -> dict:
    return {**status(), "uninstalled": False}


def restart() -> bool:
    return False


def ensure_running() -> dict:
    return status()
