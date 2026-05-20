"""macOS LaunchAgent helpers for keeping the proxy alive outside Codex."""

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from config import CONFIG_DIR

LABEL = "com.fank1ng.codexproxyapi"
SOURCE_DIR_ENV = "CODEX_PROXY_SOURCE_DIR"
APP_BUNDLE_ENV = "CODEX_PROXY_APP_BUNDLE"
PYTHON_ENV = "CODEX_PROXY_PYTHON"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "codexproxyapi"
LOG_PATH = RUNTIME_DIR / "proxy.log"
COPY_FILES = {
    ".gitignore",
    "account_manager.py",
    "control_actions.py",
    "control_panel.py",
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
COPY_DIRS = {"static", "vendor", "python"}
ACCOUNT_FILES = {"auth.json", "account.json", "quota.json"}


def status() -> dict:
    loaded = _launchctl_print().returncode == 0
    source = _source_dir()
    runtime_is_source = source.resolve() == RUNTIME_DIR.resolve()
    installed_program = _installed_program()
    expected_program = str(RUNTIME_DIR / "proxy.py")
    needs_repair = bool(
        PLIST_PATH.exists()
        and installed_program
        and Path(installed_program).expanduser() != Path(expected_program)
    )
    return {
        "supported": sys.platform == "darwin",
        "label": LABEL,
        "plist_path": str(PLIST_PATH),
        "app_bundle": str(_app_bundle_dir()),
        "runtime_dir": str(RUNTIME_DIR),
        "source_dir": str(source),
        "runtime_is_source": runtime_is_source,
        "can_sync_source": (not runtime_is_source) and _source_file(source, "proxy.py").exists(),
        "python": str(_python_executable()),
        "pythonpath": str(_pythonpath()),
        "installed": PLIST_PATH.exists(),
        "loaded": loaded,
        "installed_program": installed_program,
        "expected_program": expected_program,
        "needs_repair": needs_repair,
        "log_path": str(LOG_PATH),
    }


def install(*, sync: bool = True) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent is only supported on macOS")
    if sync or not (RUNTIME_DIR / "proxy.py").exists():
        _sync_runtime_dir()
    codex_proxy = None
    codex_proxy_error = None
    try:
        import codex_config

        codex_proxy = codex_config.ensure_enabled(True)
    except Exception as e:
        codex_proxy_error = str(e)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(_plist(), f)

    # When called from the Web UI running inside this LaunchAgent, bootout would
    # terminate the process before the HTTP response can reach the browser.
    if not _inside_launchagent():
        _run(["launchctl", "bootout", _domain(), str(PLIST_PATH)], check=False)
        _run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)])

    result = status()
    result["codex_proxy"] = codex_proxy
    result["codex_proxy_error"] = codex_proxy_error
    result["restart_required"] = _inside_launchagent()
    return result


def uninstall() -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent is only supported on macOS")
    _run(["launchctl", "bootout", _domain(), str(PLIST_PATH)], check=False)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
    return status()


def restart() -> bool:
    if sys.platform != "darwin" or not PLIST_PATH.exists():
        return False
    result = _run(["launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}"], check=False)
    return result.returncode == 0


def ensure_running() -> dict:
    """Start or repair the LaunchAgent without syncing source files."""
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent is only supported on macOS")
    current = status()
    if current.get("installed") and not current.get("needs_repair"):
        if current.get("loaded"):
            _run(["launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}"], check=False)
        else:
            _run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)], check=False)
        return status()
    return install(sync=False)


def _plist() -> dict:
    env = {
        "PYTHONUNBUFFERED": "1",
        SOURCE_DIR_ENV: str(_source_dir().resolve()),
        APP_BUNDLE_ENV: str(_app_bundle_dir()),
    }
    pythonpath = _pythonpath()
    if pythonpath:
        env["PYTHONPATH"] = str(pythonpath)
    return {
        "Label": LABEL,
        "ProgramArguments": [str(_python_executable()), str(RUNTIME_DIR / "proxy.py")],
        "WorkingDirectory": str(RUNTIME_DIR),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": env,
    }


def _sync_runtime_dir() -> None:
    source = _source_dir().resolve()
    target = RUNTIME_DIR.resolve()
    if source == target:
        return
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    for name in COPY_FILES:
        src = _source_file(source, name)
        if src.exists():
            if name == "config.json" and (RUNTIME_DIR / name).exists():
                continue
            shutil.copy2(src, RUNTIME_DIR / name)
    for name in COPY_DIRS:
        src = _source_dir_entry(source, name)
        if src.exists():
            dst = target / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
    _sync_accounts_dir(source / "accounts", target / "accounts")


def _source_dir() -> Path:
    configured = os.environ.get(SOURCE_DIR_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    return CONFIG_DIR


def _source_file(source: Path, name: str) -> Path:
    direct = source / name
    if direct.exists():
        return direct
    core = source / "src" / "core" / name
    if core.exists():
        return core
    mac = source / "platforms" / "mac" / name
    if mac.exists():
        return mac
    return direct


def _source_dir_entry(source: Path, name: str) -> Path:
    direct = source / name
    if direct.exists():
        return direct
    core = source / "src" / "core" / name
    if core.exists():
        return core
    return direct


def _app_bundle_dir() -> Path:
    configured = os.environ.get(APP_BUNDLE_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    source = _source_dir()
    for parent in (source, *source.parents):
        if parent.suffix == ".app" and (parent / "Contents").exists():
            return parent
    return CONFIG_DIR / "Codex Proxy Control.app"


def _python_executable() -> Path:
    configured = os.environ.get(PYTHON_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    bundled_runtime_python = RUNTIME_DIR / "python" / "bin" / "python3"
    if bundled_runtime_python.exists():
        return bundled_runtime_python
    bundled_runtime_framework_python = (
        RUNTIME_DIR
        / "python"
        / "Python3.framework"
        / "Versions"
        / "3.9"
        / "Resources"
        / "Python.app"
        / "Contents"
        / "MacOS"
        / "Python"
    )
    if bundled_runtime_framework_python.exists():
        return bundled_runtime_framework_python
    bundled_source_python = _source_dir() / "python" / "bin" / "python3"
    if bundled_source_python.exists():
        return bundled_source_python
    bundled_source_framework_python = (
        _source_dir()
        / "python"
        / "Python3.framework"
        / "Versions"
        / "3.9"
        / "Resources"
        / "Python.app"
        / "Contents"
        / "MacOS"
        / "Python"
    )
    if bundled_source_framework_python.exists():
        return bundled_source_framework_python
    return Path(sys.executable)


def _pythonpath():
    runtime_vendor = RUNTIME_DIR / "vendor"
    if runtime_vendor.exists():
        return runtime_vendor
    source_vendor = _source_dir() / "vendor"
    if source_vendor.exists():
        return source_vendor
    return None


def _inside_launchagent() -> bool:
    return os.environ.get("XPC_SERVICE_NAME") == LABEL


def _sync_accounts_dir(source: Path, target: Path) -> None:
    if not source.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    for account_dir in source.iterdir():
        if not account_dir.is_dir() or account_dir.name.startswith("."):
            continue
        if not (account_dir / "auth.json").exists():
            continue
        destination = target / account_dir.name
        destination.mkdir(parents=True, exist_ok=True)
        for filename in ACCOUNT_FILES:
            src = account_dir / filename
            dst = destination / filename
            if src.exists() and src.is_file() and not dst.exists():
                shutil.copy2(src, dst)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl_print() -> subprocess.CompletedProcess:
    return _run(["launchctl", "print", f"{_domain()}/{LABEL}"], check=False)


def _installed_program() -> str:
    if not PLIST_PATH.exists():
        return ""
    try:
        with open(PLIST_PATH, "rb") as f:
            data = plistlib.load(f)
        args = data.get("ProgramArguments") or []
        if len(args) >= 2:
            return str(args[1])
    except Exception:
        return ""
    return ""


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "launchctl failed").strip()
        raise RuntimeError(message)
    return result
