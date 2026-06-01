#!/usr/bin/env python3
"""Windows background supervisor for the Codex account-pool proxy."""

import argparse
import json
import os
import runpy
import subprocess
import sys
import time
from pathlib import Path

import win_service_manager


def _windows_runtime_dir() -> Path:
    configured = os.environ.get("CODEX_PROXY_CONFIG_DIR")
    if configured:
        return Path(configured).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "codexproxyapi"
    return Path.home() / "AppData" / "Local" / "codexproxyapi"


RUNTIME_DIR = _windows_runtime_dir() if sys.platform == "win32" else Path(__file__).resolve().parent
os.environ.setdefault("CODEX_PROXY_CONFIG_DIR", str(RUNTIME_DIR))
os.environ.setdefault("PYTHONUNBUFFERED", "1")
VENDOR_DIR = RUNTIME_DIR / "vendor"
DLL_DIRECTORY_HANDLES = []
PYTHON_BOOT_ENV_KEYS = ("PYTHONHOME", "PYTHONPATH", "PYTHONPLATLIBDIR", "PYTHONSAFEPATH")


def _clean_python_boot_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    for key in PYTHON_BOOT_ENV_KEYS:
        cleaned.pop(key, None)
    return cleaned


def _configure_runtime_imports() -> None:
    paths = [RUNTIME_DIR, VENDOR_DIR]
    for path in reversed(paths):
        if path.exists():
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
    if VENDOR_DIR.exists():
        existing = os.environ.get("PYTHONPATH")
        vendor = str(VENDOR_DIR)
        parts = [vendor, str(RUNTIME_DIR)]
        if existing:
            parts.append(existing)
        os.environ["PYTHONPATH"] = os.pathsep.join(parts)
        if hasattr(os, "add_dll_directory"):
            handle = os.add_dll_directory(vendor)
            DLL_DIRECTORY_HANDLES.append(handle)


def _service_args() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--proxy-child"]
    return [sys.executable, str(Path(__file__).resolve()), "--proxy-child"]


def _service_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve())]


def _source_runtime_dir() -> Path:
    configured = os.environ.get("CODEX_PROXY_SOURCE_DIR")
    if configured:
        return Path(configured).expanduser()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "runtime"
    return Path(__file__).resolve().parents[2]


def _write_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _proxy_child() -> None:
    _configure_runtime_imports()
    os.chdir(RUNTIME_DIR)
    _write_pid(RUNTIME_DIR / "proxy.pid")
    runpy.run_path(str(RUNTIME_DIR / "proxy.py"), run_name="__main__")


def _supervise() -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _write_pid(RUNTIME_DIR / "supervisor.pid")
    log_path = RUNTIME_DIR / "proxy.log"
    _configure_runtime_imports()
    env = {
        **_clean_python_boot_env(os.environ),
        "CODEX_PROXY_CONFIG_DIR": str(RUNTIME_DIR),
        "CODEX_PROXY_SOURCE_DIR": str(_source_runtime_dir()),
        "PYTHONUNBUFFERED": "1",
        "PYTHONUTF8": "1",
    }
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    while True:
        with open(log_path, "a", encoding="utf-8", buffering=1) as log:
            log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting proxy child\n")
            process = subprocess.Popen(
                _service_args(),
                cwd=str(RUNTIME_DIR),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            (RUNTIME_DIR / "proxy.pid").write_text(str(process.pid), encoding="utf-8")
            returncode = process.wait()
            log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] proxy child exited: {returncode}\n")
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--proxy-child", action="store_true")
    args = parser.parse_args()

    result = None
    if args.proxy_child:
        _proxy_child()
        return 0
    if args.install:
        result = win_service_manager.install(
            source_runtime=_source_runtime_dir(),
            service_command=_service_command(),
        )
    elif args.uninstall:
        result = win_service_manager.uninstall()
    elif args.stop:
        result = win_service_manager.stop()
    elif args.restart:
        result = win_service_manager.restart(
            source_runtime=_source_runtime_dir(),
            service_command=_service_command(),
        )
    elif args.status:
        result = win_service_manager.status()
    else:
        return _supervise()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
