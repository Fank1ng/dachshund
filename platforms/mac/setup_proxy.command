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

APP_URL = "http://127.0.0.1:8800/app"
STATUS_URL = "http://127.0.0.1:8800/api/status"


def compact(data):
    if not isinstance(data, dict):
        return str(data)
    keys = ("installed", "loaded", "enabled", "mode", "changed", "port", "active_accounts")
    return json.dumps({key: data.get(key) for key in keys if key in data}, ensure_ascii=False)


def wait_for_proxy(timeout=20):
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"Proxy did not become ready within {timeout}s: {last_error}")


print("Installing or updating background proxy service...")
print(compact(service_manager.install()))

print("Waiting for proxy health check...")
print(compact(wait_for_proxy()))

print("Ensuring Codex account-pool proxy config...")
config = codex_config.ensure_enabled(True)
print(compact(config))
if config.get("changed"):
    print("Codex config changed. Restart Codex if it is already open.")

print("Opening proxy dashboard...")
subprocess.run(["open", APP_URL], check=False)
print("Ready. The proxy is now managed by a macOS LaunchAgent and will keep running in the background.")
PY
