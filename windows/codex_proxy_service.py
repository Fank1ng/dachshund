#!/usr/bin/env python3
"""Windows background supervisor for the Codex account-pool proxy."""

import os
import runpy
import subprocess
import sys
import time
from pathlib import Path


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


def _service_args() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--proxy-child"]
    return [sys.executable, str(Path(__file__).resolve()), "--proxy-child"]


def _write_pid(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))


def _proxy_child() -> None:
    sys.path.insert(0, str(RUNTIME_DIR))
    os.chdir(RUNTIME_DIR)
    _write_pid(RUNTIME_DIR / "proxy.pid")
    runpy.run_path(str(RUNTIME_DIR / "proxy.py"), run_name="__main__")


def _supervise() -> int:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    _write_pid(RUNTIME_DIR / "supervisor.pid")
    log_path = RUNTIME_DIR / "proxy.log"
    env = {**os.environ, "CODEX_PROXY_CONFIG_DIR": str(RUNTIME_DIR), "PYTHONUNBUFFERED": "1"}
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
            (RUNTIME_DIR / "proxy.pid").write_text(str(process.pid))
            returncode = process.wait()
            log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] proxy child exited: {returncode}\n")
        time.sleep(2)


def main() -> int:
    if "--proxy-child" in sys.argv:
        _proxy_child()
        return 0
    if "--uninstall" in sys.argv:
        import service_manager

        service_manager.uninstall()
        return 0
    return _supervise()


if __name__ == "__main__":
    raise SystemExit(main())
