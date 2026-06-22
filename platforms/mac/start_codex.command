#!/bin/zsh
set -e

MAC_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$MAC_DIR/../.." && pwd)"
export PYTHONPATH="$ROOT/src/core:$MAC_DIR${PYTHONPATH:+:$PYTHONPATH}"
export CODEX_PROXY_SOURCE_DIR="$ROOT"
cd "$ROOT"
python3 - <<'PY'
import json
import subprocess
import time
import urllib.error
import urllib.request

import codex_config
import service_manager

STATUS_URL = "http://127.0.0.1:18800/api/status"
HEALTH_URL = "http://127.0.0.1:18800/api/config"


def compact(data):
    if not isinstance(data, dict):
        return str(data)
    keys = ("installed", "loaded", "enabled", "mode", "changed", "running", "port", "active_accounts")
    return json.dumps({key: data.get(key) for key in keys if key in data}, ensure_ascii=False)


def proxy_status(timeout=1):
    try:
        with urllib.request.urlopen(STATUS_URL, timeout=timeout) as response:
            if response.status == 200:
                return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError):
        return None
    return None


def proxy_health(timeout=2):
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_proxy(timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = proxy_status(timeout=2)
        if status:
            return status
        if proxy_health():
            return {"running": True}
        time.sleep(0.4)
    return None


status = proxy_status(timeout=2)
if not status and proxy_health():
    status = {"running": True}
if status:
    print("Proxy already running.")
    print(compact(status))
else:
    service = service_manager.status()
    if service.get("installed"):
        print("Checking existing background proxy service...")
        status = wait_for_proxy(timeout=4)
        if status:
            print(compact(status))
        elif not service.get("loaded"):
            print("Loading background proxy service...")
            service_manager.install()
        else:
            print("Restarting background proxy service...")
            service_manager.restart()
    else:
        print("Background service is not installed; installing it once...")
        service_manager.install()

    if not status:
        status = wait_for_proxy(timeout=15)
    if not status and service.get("installed"):
        print("Repairing background proxy service...")
        service_manager.install()
        status = wait_for_proxy(timeout=20)
    if not status:
        raise RuntimeError("Proxy did not become ready. Run setup_proxy.command to repair the service.")
    print(compact(status))

print("Ensuring Codex proxy config...")
config = codex_config.ensure_enabled(True)
print(compact(config))
if config.get("changed"):
    print("Codex config changed. If Codex is already open, quit and reopen it.")

print("Opening Codex...")
subprocess.run(["open", "-a", "Codex"], check=False)
print("Ready. The proxy remains running in the background.")
PY
