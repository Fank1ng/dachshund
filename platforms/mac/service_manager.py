"""macOS LaunchAgent helpers for keeping the proxy alive outside Codex."""

import os
import json
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from config import CONFIG_DIR

LABEL = "com.fank1ng.xiaolachang"
OLD_LABEL = "com.fank1ng.codexproxyapi"
SOURCE_DIR_ENV = "CODEX_PROXY_SOURCE_DIR"
APP_BUNDLE_ENV = "CODEX_PROXY_APP_BUNDLE"
PYTHON_ENV = "CODEX_PROXY_PYTHON"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
OLD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{OLD_LABEL}.plist"
RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "xiaolachang"
OLD_RUNTIME_DIR = Path.home() / "Library" / "Application Support" / "codexproxyapi"
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
    "usage_stats.py",
}
COPY_DIRS = {"static", "vendor", "python"}
ACCOUNT_FILES = {"auth.json", "account.json", "quota.json"}
SYNC_MANIFEST = ".sync-manifest.json"


class RuntimeSyncError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        backup_path: Optional[Path] = None,
        restored: bool = False,
        restore_error: str = "",
    ):
        super().__init__(message)
        self.backup_path = backup_path
        self.restored = restored
        self.restore_error = restore_error


def status() -> dict:
    loaded = _launchctl_print().returncode == 0
    legacy_loaded = _legacy_launchctl_print().returncode == 0
    source = _source_dir()
    runtime_is_source = source.resolve() == RUNTIME_DIR.resolve()
    installed_plist = _installed_plist()
    legacy_plist = _installed_plist(OLD_PLIST_PATH)
    expected_plist = _plist()
    installed_args = installed_plist.get("ProgramArguments") or []
    installed_env = installed_plist.get("EnvironmentVariables") or {}
    installed_program = str(installed_args[1]) if len(installed_args) >= 2 else ""
    legacy_args = legacy_plist.get("ProgramArguments") or []
    legacy_program = str(legacy_args[1]) if len(legacy_args) >= 2 else ""
    expected_program = str(RUNTIME_DIR / "proxy.py")
    repair_reasons = _repair_reasons(installed_plist, expected_plist)
    expected_version = _proxy_version(_source_file(source, "proxy.py"))
    running_program = installed_program if loaded else ""
    if legacy_loaded:
        running_program = legacy_program or str(OLD_RUNTIME_DIR / "proxy.py")
    running_version = _proxy_version(Path(running_program)) if running_program else ""
    version_mismatch = bool(expected_version and running_version and expected_version != running_version)
    migration_required = bool(
        legacy_loaded
        or (not PLIST_PATH.exists() and OLD_PLIST_PATH.exists())
        or version_mismatch
        or (PLIST_PATH.exists() and repair_reasons)
    )
    needs_repair = bool((PLIST_PATH.exists() and repair_reasons) or migration_required)
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
        "legacy_installed": OLD_PLIST_PATH.exists(),
        "legacy_runtime_dir": str(OLD_RUNTIME_DIR),
        "loaded": loaded,
        "legacy_loaded": legacy_loaded,
        "legacy_running": legacy_loaded,
        "installed_program": installed_program,
        "installed_python": str(installed_args[0]) if installed_args else "",
        "installed_source_dir": str(installed_env.get(SOURCE_DIR_ENV, "")),
        "installed_app_bundle": str(installed_env.get(APP_BUNDLE_ENV, "")),
        "installed_pythonpath": str(installed_env.get("PYTHONPATH", "")),
        "expected_program": expected_program,
        "expected_version": expected_version,
        "running_version": running_version,
        "version_mismatch": version_mismatch,
        "migration_required": migration_required,
        "needs_repair": needs_repair,
        "repair_reasons": repair_reasons,
        "log_path": str(LOG_PATH),
    }


def install(*, sync: bool = True, keep_backup: bool = False) -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("LaunchAgent is only supported on macOS")
    _migrate_legacy_runtime()
    sync_result = None
    if sync or not (RUNTIME_DIR / "proxy.py").exists():
        sync_result = _sync_runtime_dir(keep_backup=keep_backup)
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

    # Fully retire the pre-rename service before (re)starting ours so the two
    # KeepAlive agents stop fighting over port 8800. Safe regardless of whether
    # we run inside the LaunchAgent: it targets a different label.
    _remove_legacy_service()

    # When called from the Web UI running inside this LaunchAgent, bootout would
    # terminate the process before the HTTP response can reach the browser.
    if not _inside_launchagent():
        _run(["launchctl", "bootout", _domain(), str(PLIST_PATH)], check=False)
        _run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)])

    result = status()
    result["codex_proxy"] = codex_proxy
    result["codex_proxy_error"] = codex_proxy_error
    result["restart_required"] = _inside_launchagent()
    result["sync"] = sync_result
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
    _migrate_legacy_runtime()
    current = status()
    if current.get("installed") and not current.get("needs_repair"):
        if current.get("loaded"):
            _run(["launchctl", "kickstart", "-k", f"{_domain()}/{LABEL}"], check=False)
        else:
            _run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)], check=False)
        return status()
    return install(sync=bool(current.get("migration_required") or current.get("version_mismatch")))


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


def _sync_runtime_dir(*, keep_backup: bool = False) -> dict:
    _migrate_legacy_runtime()
    source = _source_dir().resolve()
    target = RUNTIME_DIR.resolve()
    if source == target:
        return {"changed": False, "source_dir": str(source), "runtime_dir": str(target)}
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(time.time())}-{os.getpid()}"
    staging = target.parent / f".{target.name}.update-staging-{stamp}"
    backup = target.parent / f".{target.name}.update-backup-{stamp}"
    try:
        _build_runtime_staging(source, staging)
        _apply_staged_runtime(staging, target, backup)
    except RuntimeSyncError:
        raise
    except Exception as e:
        restored = False
        restore_error = ""
        if backup.exists():
            try:
                _restore_runtime_backup(target, backup)
                restored = True
            except Exception as restore_exc:
                restore_error = str(restore_exc)
        raise RuntimeSyncError(
            str(e),
            backup_path=backup if backup.exists() else None,
            restored=restored,
            restore_error=restore_error,
        ) from e
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    _sync_accounts_dir(source / "accounts", target / "accounts")
    if not keep_backup and backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    return {
        "changed": True,
        "source_dir": str(source),
        "runtime_dir": str(target),
        "backup_path": str(backup) if backup.exists() else None,
    }


def rollback_runtime(backup_path) -> dict:
    backup = Path(backup_path).expanduser()
    if not backup.exists():
        raise FileNotFoundError(f"runtime backup not found: {backup}")
    _restore_runtime_backup(RUNTIME_DIR.resolve(), backup)
    return {"rolled_back": True, "backup_path": str(backup), "runtime_dir": str(RUNTIME_DIR)}


def cleanup_runtime_backup(backup_path) -> None:
    if not backup_path:
        return
    backup = Path(backup_path).expanduser()
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def _build_runtime_staging(source: Path, staging: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    _sync_core_files(source, staging)
    for name in COPY_FILES:
        src = _source_file(source, name)
        if src.exists():
            shutil.copy2(src, staging / name)
    for name in COPY_DIRS:
        src = _source_dir_entry(source, name)
        if src.exists():
            shutil.copytree(src, staging / name, symlinks=True)
    _validate_runtime_staging(staging)


def _validate_runtime_staging(staging: Path) -> None:
    required = ("account_manager.py", "config.py", "proxy.py", "proxy_core.py", "service_manager.py")
    missing = [name for name in required if not (staging / name).is_file()]
    if missing:
        raise RuntimeSyncError(f"runtime staging missing required files: {', '.join(missing)}")
    if not (staging / "static").is_dir():
        raise RuntimeSyncError("runtime staging missing static directory")
    auth_leak = next(staging.rglob("auth.json"), None)
    if auth_leak:
        raise RuntimeSyncError(f"refusing runtime staging with credential file: {auth_leak}")


def _apply_staged_runtime(staging: Path, target: Path, backup: Path) -> None:
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True, exist_ok=True)
    manifest = []
    entries: list[tuple[str, Path, Path, str]] = []
    for name in sorted(COPY_FILES):
        src = staging / name
        if not src.exists():
            continue
        dst = target / name
        if name == "config.json" and dst.exists():
            continue
        entries.append((name, src, dst, "file"))
    for name in sorted(COPY_DIRS):
        src = staging / name
        if src.exists():
            entries.append((name, src, target / name, "dir"))

    for name, _src, dst, kind in entries:
        backup_dst = backup / name
        existed = dst.exists()
        manifest.append({"name": name, "kind": kind, "existed": existed})
        if existed:
            if dst.is_dir():
                shutil.copytree(dst, backup_dst, symlinks=True)
            else:
                backup_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_dst)
    (backup / SYNC_MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    try:
        for _name, src, dst, _kind in entries:
            _remove_entry(dst)
            _copy_staged_entry(src, dst)
    except Exception as e:
        restored = False
        restore_error = ""
        try:
            _restore_runtime_backup(target, backup)
            restored = True
        except Exception as restore_exc:
            restore_error = str(restore_exc)
        raise RuntimeSyncError(
            str(e),
            backup_path=backup,
            restored=restored,
            restore_error=restore_error,
        ) from e


def _copy_staged_entry(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _restore_runtime_backup(target: Path, backup: Path) -> None:
    manifest_path = backup / SYNC_MANIFEST
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = [
            {"name": item.name, "kind": "dir" if item.is_dir() else "file", "existed": True}
            for item in backup.iterdir()
            if item.name != SYNC_MANIFEST
        ]
    for item in manifest:
        name = item["name"]
        dst = target / name
        _remove_entry(dst)
        if not item.get("existed"):
            continue
        src = backup / name
        if src.exists():
            _copy_staged_entry(src, dst)


def _remove_entry(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _sync_core_files(source: Path, target: Path) -> None:
    core = _platform_core_dir(source)
    if not core.exists():
        return
    for src in core.glob("*.py"):
        shutil.copy2(src, target / src.name)
    config_src = core / "config.json"
    config_dst = target / "config.json"
    if config_src.exists() and not config_dst.exists():
        shutil.copy2(config_src, config_dst)


def _source_dir() -> Path:
    configured = os.environ.get(SOURCE_DIR_ENV)
    if configured:
        path = Path(configured).expanduser()
        if path.exists():
            return path
    return CONFIG_DIR


def _source_file(source: Path, name: str) -> Path:
    for candidate in _source_file_candidates(source, name):
        if candidate.exists():
            return candidate
    return source / name


def _source_dir_entry(source: Path, name: str) -> Path:
    for candidate in _source_file_candidates(source, name):
        if candidate.exists():
            return candidate
    return source / name


def _platform_core_dir(source: Path) -> Path:
    core = source / "platforms" / "mac" / "core"
    return core if core.exists() else source


def _source_file_candidates(source: Path, name: str) -> tuple[Path, ...]:
    mac_core = _platform_core_dir(source) / name
    mac = source / "platforms" / "mac" / name
    direct = source / name
    if name == "requirements.txt":
        return (mac_core, mac, direct, source / "requirements.txt")
    return (mac_core, mac, direct)


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
    return CONFIG_DIR / "小腊肠.app"


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
    return os.environ.get("XPC_SERVICE_NAME") in {LABEL, OLD_LABEL}


def _migrate_legacy_runtime() -> None:
    if not OLD_RUNTIME_DIR.exists() or RUNTIME_DIR.exists():
        return
    try:
        RUNTIME_DIR.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(OLD_RUNTIME_DIR, RUNTIME_DIR, symlinks=True)
    except Exception:
        return


def _remove_legacy_service() -> None:
    """Fully retire the pre-rename LaunchAgent and its runtime.

    The old teardown only ran ``launchctl bootout``, leaving the old plist on
    disk and the old runtime intact. The 0.5.4 KeepAlive agent therefore kept
    respawning (on login, or when the old Control.app was opened) and fought the
    new agent for port 8800. Disable it, delete its plist, and move its runtime
    aside so the old proxy.py can never spawn again.
    """
    # Preserve any accounts that only ever lived in the old runtime.
    _sync_accounts_dir(OLD_RUNTIME_DIR / "accounts", RUNTIME_DIR / "accounts")
    _run(["launchctl", "bootout", f"{_domain()}/{OLD_LABEL}"], check=False)
    if OLD_PLIST_PATH.exists():
        _run(["launchctl", "bootout", _domain(), str(OLD_PLIST_PATH)], check=False)
    # Persistent override so a stray plist can never be bootstrapped again.
    _run(["launchctl", "disable", f"{_domain()}/{OLD_LABEL}"], check=False)
    if OLD_PLIST_PATH.exists():
        try:
            OLD_PLIST_PATH.unlink()
        except OSError:
            pass
    if OLD_RUNTIME_DIR.exists():
        retired = OLD_RUNTIME_DIR.parent / f".{OLD_RUNTIME_DIR.name}.legacy-removed-{int(time.time())}"
        try:
            shutil.move(str(OLD_RUNTIME_DIR), str(retired))
        except OSError:
            pass


def _installed_plist(path: Optional[Path] = None) -> dict:
    path = path or PLIST_PATH
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = plistlib.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _repair_reasons(installed: dict, expected: dict) -> list[str]:
    if not PLIST_PATH.exists():
        return []
    if not installed:
        return ["plist_unreadable"]

    reasons = []
    installed_args = installed.get("ProgramArguments") or []
    expected_args = expected.get("ProgramArguments") or []
    if len(installed_args) < 2:
        reasons.append("program_arguments_missing")
    elif len(expected_args) >= 2:
        if not _same_path(installed_args[0], expected_args[0]):
            reasons.append("python_mismatch")
        if not _same_path(installed_args[1], expected_args[1]):
            reasons.append("program_mismatch")

    installed_workdir = installed.get("WorkingDirectory")
    expected_workdir = expected.get("WorkingDirectory")
    if installed_workdir or expected_workdir:
        if not _same_path(installed_workdir, expected_workdir):
            reasons.append("working_directory_mismatch")

    installed_env = installed.get("EnvironmentVariables") or {}
    expected_env = expected.get("EnvironmentVariables") or {}
    env_path_keys = (SOURCE_DIR_ENV, APP_BUNDLE_ENV, PYTHON_ENV, "PYTHONPATH")
    for key in env_path_keys:
        installed_value = installed_env.get(key)
        expected_value = expected_env.get(key)
        if installed_value or expected_value:
            if not _same_path(installed_value, expected_value):
                reasons.append(f"{key.lower()}_mismatch")
    return reasons


def _same_path(left, right) -> bool:
    if not left and not right:
        return True
    if not left or not right:
        return False
    return Path(str(left)).expanduser().resolve() == Path(str(right)).expanduser().resolve()


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


def _legacy_launchctl_print() -> subprocess.CompletedProcess:
    return _run(["launchctl", "print", f"{_domain()}/{OLD_LABEL}"], check=False)


def _installed_program() -> str:
    args = _installed_plist().get("ProgramArguments") or []
    if len(args) >= 2:
        return str(args[1])
    return ""


def _proxy_version(proxy_file: Path) -> str:
    try:
        text = proxy_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("APP_VERSION"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"\'')
    return ""


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "launchctl failed").strip()
        raise RuntimeError(message)
    return result
