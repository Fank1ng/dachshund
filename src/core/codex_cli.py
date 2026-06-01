"""Locate the Codex CLI across desktop install layouts."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, Mapping, Optional


CODEX_CLI_ENV = "CODEX_CLI_PATH"
DEFAULT_MAC_CODEX_CLI = "/Applications/Codex.app/Contents/Resources/codex"
CODEX_CLI_MISSING_MESSAGE = (
    "Codex CLI not found. Install or open Codex once, make sure codex is available, "
    f"or set {CODEX_CLI_ENV} to the full path of codex.exe."
)


def find_codex_cli(
    env: Optional[Mapping[str, str]] = None,
    *,
    platform_name: Optional[str] = None,
) -> Optional[str]:
    """Return an absolute path to the Codex CLI when it can be discovered."""
    env = env or os.environ
    platform_name = platform_name or sys.platform

    configured = _env_get(env, CODEX_CLI_ENV)
    if configured:
        candidate = _clean_path(configured)
        if _is_file(candidate):
            return str(candidate)

    found = shutil.which("codex", path=_env_get(env, "PATH"))
    if found:
        return found

    if platform_name == "darwin":
        candidate = Path(DEFAULT_MAC_CODEX_CLI)
        return str(candidate) if _is_file(candidate) else None

    if platform_name != "win32":
        return None

    for candidate in _windows_codex_candidates(env):
        if _is_file(candidate):
            return str(candidate)
    return None


def _env_get(env: Mapping[str, str], key: str) -> str:
    for candidate in (key, key.upper(), key.lower(), key.title()):
        value = env.get(candidate)
        if value:
            return value
    return ""


def _clean_path(value: str) -> Path:
    text = value.strip().strip('"')
    if "," in text and text.lower().endswith(".exe,0"):
        text = text.rsplit(",", 1)[0]
    return Path(os.path.expandvars(os.path.expanduser(text)))


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _windows_codex_candidates(env: Mapping[str, str]) -> Iterable[Path]:
    yielded: set[str] = set()

    def yield_once(path: Path) -> Iterable[Path]:
        key = str(path).lower()
        if key not in yielded:
            yielded.add(key)
            yield path

    for entry in _windows_path_entries(env):
        for candidate in _path_entry_candidates(entry):
            yield from yield_once(candidate)

    local_app_data = _env_get(env, "LOCALAPPDATA")
    if local_app_data:
        bin_root = _clean_path(local_app_data) / "OpenAI" / "Codex" / "bin"
        for candidate in _glob_by_mtime(bin_root, "*", "codex.exe"):
            yield from yield_once(candidate)

    for program_files_key in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        program_files = _env_get(env, program_files_key)
        if not program_files:
            continue
        windows_apps = _clean_path(program_files) / "WindowsApps"
        for pattern in (
            "OpenAI.Codex_*_x64__*",
            "OpenAI.Codex_*_x64_*",
            "OpenAI.Codex_*_neutral_*",
            "OpenAI.Codex_*",
        ):
            for candidate in _glob_by_mtime(windows_apps, pattern, "app", "resources", "codex.exe"):
                yield from yield_once(candidate)

    for candidate in _registry_candidates():
        yield from yield_once(candidate)


def _windows_path_entries(env: Mapping[str, str]) -> list[Path]:
    entries: list[str] = []
    for key in ("PATH", "Path", "path"):
        value = env.get(key)
        if value:
            entries.extend(value.split(os.pathsep))
    entries.extend(_registry_environment_path_values())

    paths: list[Path] = []
    seen: set[str] = set()
    for entry in entries:
        if not entry:
            continue
        path = _clean_path(entry)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return paths


def _path_entry_candidates(entry: Path) -> Iterable[Path]:
    yield entry / "codex.exe"
    yield entry / "codex"

    text = str(entry).lower()
    if "\\openai\\codex\\bin" in text or "/openai/codex/bin" in text:
        yield from _glob_by_mtime(entry, "*", "codex.exe")

    if entry.name.lower() == "windowsapps":
        for pattern in ("OpenAI.Codex_*",):
            yield from _glob_by_mtime(entry, pattern, "app", "resources", "codex.exe")


def _glob_by_mtime(root: Path, *parts: str) -> list[Path]:
    try:
        matches = list(root.glob(str(Path(*parts))))
    except OSError:
        return []

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            return (path.stat().st_mtime, str(path).lower())
        except OSError:
            return (0, str(path).lower())

    return sorted(matches, key=sort_key, reverse=True)


def _registry_environment_path_values() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except (ImportError, OSError):
        return []

    values: list[str] = []
    keys = (
        (winreg.HKEY_CURRENT_USER, r"Environment", "Path"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            "Path",
        ),
    )
    for root, subkey, value_name in keys:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if value:
                    values.append(str(value))
        except OSError:
            continue
    return values


def _registry_candidates() -> Iterable[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except (ImportError, OSError):
        return []

    registry_keys = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\codex.exe",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\OpenAI Codex",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\OpenAI Codex",
    )
    value_names = ("", "DisplayIcon", "InstallLocation", "InstallSource")
    candidates: list[Path] = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in registry_keys:
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for value_name in value_names:
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        candidates.extend(_registry_value_candidates(str(value)))
            except OSError:
                continue
    return candidates


def _registry_value_candidates(value: str) -> Iterable[Path]:
    if not value:
        return []
    path = _clean_path(value)
    if path.suffix.lower() == ".exe":
        return [path]
    return [
        path / "codex.exe",
        path / "app" / "resources" / "codex.exe",
    ]
