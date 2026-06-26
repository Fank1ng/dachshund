"""Linux user-service helpers for Dachshund."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import runtime_manifest
from version import APP_VERSION

LABEL = "dachshund"
SOURCE_DIR_ENV = "CODEX_PROXY_SOURCE_DIR"
APP_EXEC_ENV = "CODEX_PROXY_APP_EXECUTABLE"
CONFIG_DIR_ENV = "CODEX_PROXY_CONFIG_DIR"
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
RUNTIME_DIR = Path(os.environ.get(CONFIG_DIR_ENV) or XDG_CONFIG_HOME / "dachshund")
LOG_PATH = RUNTIME_DIR / "proxy.log"
SERVICE_PATH = XDG_CONFIG_HOME / "systemd" / "user" / f"{LABEL}.service"
AUTOSTART_PATH = XDG_CONFIG_HOME / "autostart" / f"{LABEL}.desktop"


class RuntimeSyncError(RuntimeError):
    pass


def status() -> dict:
    active = _run(["systemctl", "--user", "is-active", "--quiet", LABEL], check=False).returncode == 0
    enabled = _run(["systemctl", "--user", "is-enabled", "--quiet", LABEL], check=False).returncode == 0
    integrity = runtime_integrity()
    return {
        "supported": sys.platform.startswith("linux"),
        "platform": "linux",
        "label": LABEL,
        "service_path": str(SERVICE_PATH),
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(_source_dir()),
        "installed": SERVICE_PATH.exists(),
        "loaded": active,
        "enabled": enabled,
        "expected_program": str(RUNTIME_DIR / "proxy.py"),
        "installed_program": str(RUNTIME_DIR / "proxy.py") if SERVICE_PATH.exists() else "",
        "expected_version": APP_VERSION,
        "running_version": APP_VERSION if active else "",
        "bundle_version": APP_VERSION,
        "runtime_version": APP_VERSION,
        "manifest_ok": integrity.get("ok"),
        "manifest_error": integrity.get("error", ""),
        "log_path": str(LOG_PATH),
        "menubar_login": menubar_login_status(),
        "menubar_login_enabled": menubar_login_status().get("enabled"),
    }


def install(*, sync: bool = True, keep_backup: bool = False) -> dict:
    if sync or not (RUNTIME_DIR / "proxy.py").exists():
        _sync_runtime_dir()
    SERVICE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SERVICE_PATH.write_text(_systemd_unit(), encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"], check=False)
    _run(["systemctl", "--user", "enable", "--now", LABEL])
    return {**status(), "installed": True}


def uninstall() -> dict:
    _run(["systemctl", "--user", "disable", "--now", LABEL], check=False)
    if SERVICE_PATH.exists():
        SERVICE_PATH.unlink()
    _run(["systemctl", "--user", "daemon-reload"], check=False)
    return {**status(), "uninstalled": True}


def restart() -> bool:
    result = _run(["systemctl", "--user", "restart", LABEL], check=False)
    return result.returncode == 0


def ensure_running() -> dict:
    current = status()
    if current.get("loaded"):
        return current
    if not current.get("installed"):
        return install()
    _run(["systemctl", "--user", "start", LABEL], check=False)
    return status()


def menubar_login_status() -> dict:
    return {
        "supported": True,
        "enabled": AUTOSTART_PATH.exists(),
        "path": str(AUTOSTART_PATH),
    }


def set_menubar_login_item(enabled: bool) -> dict:
    if enabled:
        exe = os.environ.get(APP_EXEC_ENV) or ""
        if not exe:
            return {"action": "set_menubar_login_item", "enabled": False, "error": f"{APP_EXEC_ENV} missing"}
        AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_PATH.write_text(_desktop_entry(exe), encoding="utf-8")
    elif AUTOSTART_PATH.exists():
        AUTOSTART_PATH.unlink()
    return {"action": "set_menubar_login_item", **menubar_login_status()}


def runtime_integrity(source: Path | None = None, runtime: Path | None = None) -> dict:
    runtime_root = runtime or RUNTIME_DIR
    source_root = source or _bundle_runtime_dir()
    try:
        if (source_root / runtime_manifest.BUILD_MANIFEST).exists() and (runtime_root / runtime_manifest.RUNTIME_MANIFEST).exists():
            result = runtime_manifest.compare_runtime_to_bundle(source_root, runtime_root)
            return {
                **result,
                "bundle_version": result.get("expected_version") or APP_VERSION,
                "runtime_version": result.get("observed_version") or "",
            }
        if (runtime_root / "proxy.py").exists():
            observed = runtime_manifest.generate_manifest(
                runtime_root,
                manifest_name=runtime_manifest.RUNTIME_MANIFEST,
            )
            return {
                "ok": observed.get("version") == APP_VERSION and not observed.get("missing"),
                "bundle_version": APP_VERSION,
                "runtime_version": observed.get("version", ""),
                "missing": observed.get("missing", []),
            }
        return {"ok": False, "bundle_version": APP_VERSION, "runtime_version": "", "error": "runtime not installed"}
    except Exception as exc:
        return {"ok": False, "bundle_version": APP_VERSION, "runtime_version": "", "error": str(exc)}


def _systemd_unit() -> str:
    python = _python_executable()
    proxy = RUNTIME_DIR / "proxy.py"
    return "\n".join([
        "[Unit]",
        "Description=Dachshund Codex account pool proxy",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={RUNTIME_DIR}",
        f"Environment=PYTHONPATH={RUNTIME_DIR}",
        f"Environment={CONFIG_DIR_ENV}={RUNTIME_DIR}",
        f"ExecStart={python} {proxy}",
        "Restart=on-failure",
        "RestartSec=3",
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ])


def _desktop_entry(exe: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Dachshund",
        f"Exec={exe} --tray",
        "X-GNOME-Autostart-enabled=true",
        "",
    ])


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
    native_menu = Path(__file__).with_name("native_menu.py")
    if native_menu.exists():
        linux_dir = RUNTIME_DIR / "platforms" / "linux"
        linux_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(native_menu, linux_dir / "native_menu.py")
    runtime_manifest.write_manifest(RUNTIME_DIR, manifest_name=runtime_manifest.RUNTIME_MANIFEST)


def _source_dir() -> Path:
    return Path(os.environ.get(SOURCE_DIR_ENV) or Path(__file__).resolve().parents[2]).expanduser()


def _bundle_runtime_dir() -> Path:
    source = _source_dir()
    if (source / "proxy.py").exists():
        return source
    core = source / "src" / "core"
    return core if core.is_dir() else source


def _python_executable() -> str:
    return os.environ.get("PYTHON") or sys.executable


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result
