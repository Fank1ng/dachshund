"""Locate the Codex CLI across desktop install layouts."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable, Mapping, Optional


CODEX_CLI_ENV = "CODEX_CLI_PATH"
DEFAULT_MAC_CODEX_CLI = "/Applications/Codex.app/Contents/Resources/codex"
CODEX_CLI_MISSING_MESSAGE = (
    "Codex CLI not found. Install or open Codex once, make sure codex is available, "
    f"or set {CODEX_CLI_ENV} to the full path of codex.exe."
)
LOGIN_URL_RE = re.compile(r"https://[^\s<>'\")\]]+")
LOGIN_URL_SUFFIX_CHARS = ".,;:!?"
LOGIN_URL_HOST_HINTS = ("openai.com", "chatgpt.com", "codex")
DEVICE_CODE_RE = re.compile(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,6}\b")
LOGIN_RATE_LIMIT_COOLDOWN_SECONDS = 600
LOGIN_DEVICE_CODE_EXPIRY_SECONDS = 15 * 60
LOGIN_DEVICE_CODE_EXPIRY_GRACE_SECONDS = 60
LOGIN_ERROR_PATTERNS = (
    ("rate_limited", re.compile(r"\b429\b|too many requests|rate limit", re.I)),
    ("device_auth_failed", re.compile(r"device auth failed|device authorization failed|authorization failed", re.I)),
    (
        "expired",
        re.compile(
            r"device auth timed out|timed out after|device code expired|authorization expired|auth(?:orization)? timed out",
            re.I,
        ),
    ),
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


def format_login_command(codex_cli: str, target_dir: Path, *, platform_name: Optional[str] = None) -> str:
    """Return a shell command users can paste to login into an account dir."""
    platform_name = platform_name or sys.platform
    if platform_name == "win32":
        home = _powershell_quote(str(target_dir))
        cli = _powershell_quote(str(codex_cli))
        return f"$env:CODEX_HOME={home}; & {cli} login"
    return f"CODEX_HOME={shlex.quote(str(target_dir))} {shlex.quote(str(codex_cli))} login"


def login_device_auth_args() -> list[str]:
    """Return Codex CLI args for browser-based device auth login."""
    return ["login", "--device-auth"]


def extract_login_url(text: str) -> str:
    """Return the most likely browser login URL from Codex CLI output."""
    urls = [_clean_login_url(match.group(0)) for match in LOGIN_URL_RE.finditer(text or "")]
    urls = [url for url in urls if url]
    for url in urls:
        lowered = url.lower()
        if any(hint in lowered for hint in LOGIN_URL_HOST_HINTS):
            return url
    return urls[0] if urls else ""


def extract_device_code(text: str) -> str:
    """Return the first Codex device auth code from CLI output."""
    for match in DEVICE_CODE_RE.finditer(text or ""):
        code = match.group(0)
        prefix = (text or "")[max(0, match.start() - 80):match.start()].lower()
        suffix = (text or "")[match.end():match.end() + 80].lower()
        if "device" in prefix or "code" in prefix or "one-time" in prefix or "expires" in suffix:
            return code
    return ""


def wait_for_login_url(
    log_path: Path,
    *,
    timeout: float = 8.0,
    interval: float = 0.2,
    log_offset: Optional[int] = None,
) -> str:
    """Poll a Codex login log briefly until a login URL appears."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            url = extract_login_url(_read_login_log_text(log_path, log_offset=log_offset))
            if url:
                return url
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return ""
        time.sleep(interval)


def wait_for_login_details(
    log_path: Path,
    *,
    timeout: float = 8.0,
    interval: float = 0.2,
    log_offset: Optional[int] = None,
) -> dict:
    """Poll a Codex login log until URL and device code details appear or timeout."""
    deadline = time.monotonic() + max(0.0, timeout)
    details = {"login_url": "", "device_code": ""}
    while True:
        try:
            text = _read_login_log_text(log_path, log_offset=log_offset)
            details["login_url"] = details["login_url"] or extract_login_url(text)
            details["device_code"] = details["device_code"] or extract_device_code(text)
            if details["login_url"] and details["device_code"]:
                return details
        except OSError:
            pass
        if time.monotonic() >= deadline:
            return details
        time.sleep(interval)


def login_state_path(runtime_dir: Path, account_name: str) -> Path:
    return runtime_dir / "login-state" / f"{account_name}.json"


def remove_login_state(runtime_dir: Path, account_name: str) -> str:
    state_path = login_state_path(runtime_dir, account_name)
    try:
        state_path.unlink()
        return str(state_path)
    except FileNotFoundError:
        return ""


def current_log_offset(log_path: Path) -> int:
    try:
        return log_path.stat().st_size
    except OSError:
        return 0


def write_login_state(
    runtime_dir: Path,
    *,
    account_name: str,
    account_dir: Path,
    source_auth_path: Path,
    log_path: Path,
    started_at: float,
    log_offset: Optional[int] = None,
    pid: Optional[int] = None,
) -> Path:
    state_path = login_state_path(runtime_dir, account_name)
    source_mtime = None
    try:
        source_mtime = source_auth_path.stat().st_mtime
    except OSError:
        pass
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "account": account_name,
                "account_dir": str(account_dir),
                "auth_path": str(account_dir / "auth.json"),
                "account_dir_exists_at_start": account_dir.exists(),
                "source_auth_path": str(source_auth_path),
                "source_auth_mtime_at_start": source_mtime,
                "log_path": str(log_path),
                "log_offset": int(log_offset or 0),
                "started_at": started_at,
                "pid": pid,
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return state_path


def login_status_from_state(runtime_dir: Path, account_name: str) -> dict:
    state_path = login_state_path(runtime_dir, account_name)
    if not state_path.exists():
        return {"account": account_name, "state": "not_started"}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"account": account_name, "state": "error", "error": f"invalid login state: {exc}"}
    result = complete_login_import(state)
    result["state_path"] = str(state_path)
    return result


def login_rate_limit_cooldown(
    runtime_dir: Path,
    account_name: str,
    *,
    now: Optional[float] = None,
    cooldown_seconds: int = LOGIN_RATE_LIMIT_COOLDOWN_SECONDS,
) -> dict:
    state_path = login_state_path(runtime_dir, account_name)
    if not state_path.exists():
        return {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    status = complete_login_import(state)
    if status.get("error") != "rate_limited":
        return {}
    started_at = _float_or_zero(state.get("started_at"))
    retry_at = started_at + max(0, cooldown_seconds)
    retry_after = int(max(0, retry_at - (now if now is not None else time.time())))
    if retry_after <= 0:
        return {}
    return {
        "account": account_name,
        "error": "rate_limited",
        "error_message": _login_error_message("rate_limited", retry_after_seconds=retry_after),
        "retry_after_seconds": retry_after,
        "retry_at": retry_at,
    }


def complete_login_imports(runtime_dir: Path) -> list[dict]:
    state_dir = runtime_dir / "login-state"
    if not state_dir.exists():
        return []
    results = []
    for path in sorted(state_dir.glob("*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            results.append({"state": "error", "error": f"invalid login state: {exc}", "state_path": str(path)})
            continue
        result = complete_login_import(state)
        result["state_path"] = str(path)
        results.append(result)
    return results


def complete_login_import(state: Mapping[str, object]) -> dict:
    account = str(state.get("account") or "")
    auth_path = Path(str(state.get("auth_path") or Path(str(state.get("account_dir") or "")) / "auth.json"))
    source_auth_path = Path(str(state.get("source_auth_path") or ""))
    log_path = Path(str(state.get("log_path") or ""))
    started_at = _float_or_zero(state.get("started_at"))
    source_mtime_at_start = state.get("source_auth_mtime_at_start")
    log_offset = _optional_int(state.get("log_offset"))
    pid = _optional_int(state.get("pid"))
    target_dir = auth_path.parent

    if auth_path.exists():
        return _login_result(account, "success", auth_path, source_auth_path, log_path, imported=False)

    if _account_dir_was_removed(state, target_dir):
        return _login_result(
            account,
            "deleted",
            auth_path,
            source_auth_path,
            log_path,
            error="account_deleted",
        )

    source_updated = _source_auth_updated_after_start(
        source_auth_path,
        started_at=started_at,
        source_mtime_at_start=_optional_float(source_mtime_at_start),
    )
    if source_updated:
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_auth_path, auth_path)
        return _login_result(account, "success", auth_path, source_auth_path, log_path, imported=True)

    log_error = detect_login_error(log_path, account=account, log_offset=log_offset)
    if log_error:
        return _login_result(
            account,
            "expired" if log_error == "expired" else "error",
            auth_path,
            source_auth_path,
            log_path,
            error=log_error,
        )

    process_running = _login_process_running(pid)
    if process_running is False:
        if _login_state_expired(started_at):
            return _login_result(
                account,
                "expired",
                auth_path,
                source_auth_path,
                log_path,
                error="expired",
            )
        return _login_result(
            account,
            "error",
            auth_path,
            source_auth_path,
            log_path,
            error="login_exited_without_auth",
        )

    return _login_result(account, "pending", auth_path, source_auth_path, log_path)


def detect_login_error(log_path: Path, *, account: str = "", log_offset: Optional[int] = None) -> str:
    try:
        text = _read_login_log_text(log_path, account=account, log_offset=log_offset)
    except OSError:
        return ""
    for error, pattern in LOGIN_ERROR_PATTERNS:
        if pattern.search(text):
            return error
    return ""


def login_startup_error_result(log_path: Path, *, account: str = "", log_offset: Optional[int] = None) -> dict:
    error = detect_login_error(log_path, account=account, log_offset=log_offset)
    if not error:
        return {}
    return {
        "account": account,
        "error": error,
        "error_message": _login_error_message(error),
        "log_path": str(log_path),
    }


def _source_auth_updated_after_start(
    source_auth_path: Path,
    *,
    started_at: float,
    source_mtime_at_start: Optional[float],
) -> bool:
    try:
        current_mtime = source_auth_path.stat().st_mtime
    except OSError:
        return False
    if source_mtime_at_start is not None:
        return current_mtime > source_mtime_at_start + 0.000001
    return current_mtime >= max(0.0, started_at - 0.001)


def _login_process_running(pid: Optional[int]) -> Optional[bool]:
    if not pid or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _login_state_expired(started_at: float, *, now: Optional[float] = None) -> bool:
    if started_at <= 0:
        return False
    elapsed = (time.time() if now is None else now) - started_at
    return elapsed >= LOGIN_DEVICE_CODE_EXPIRY_SECONDS + LOGIN_DEVICE_CODE_EXPIRY_GRACE_SECONDS


def _login_result(
    account: str,
    state: str,
    auth_path: Path,
    source_auth_path: Path,
    log_path: Path,
    *,
    imported: bool = False,
    error: str = "",
) -> dict:
    return {
        "account": account,
        "state": state,
        "has_auth": auth_path.exists(),
        "imported": imported,
        "error": error,
        "error_message": _login_error_message(error) if error else "",
        "auth_path": str(auth_path),
        "source_auth_path": str(source_auth_path),
        "log_path": str(log_path),
    }


def _login_error_message(error: str, *, retry_after_seconds: Optional[int] = None) -> str:
    if error == "rate_limited":
        if retry_after_seconds:
            minutes = max(1, (retry_after_seconds + 59) // 60)
            return f"设备授权被 OpenAI 限流，请等待约 {minutes} 分钟后再试，不要反复点击开始登录。"
        return "设备授权被 OpenAI 限流，请等待 10-15 分钟后再试，不要反复点击开始登录。"
    if error == "expired":
        return "设备码已过期，请重新开始登录并使用新的验证码。"
    if error == "device_auth_failed":
        return "设备授权失败，请确认浏览器已登录 ChatGPT/OpenAI 后重新开始登录。"
    if error == "login_exited_without_auth":
        return "Codex 登录进程已退出，但没有生成账号令牌；请重新开始登录并确认浏览器验证码已提交。"
    if error == "account_deleted":
        return "账号目录已删除，已取消自动导入。"
    return error


def _account_dir_was_removed(state: Mapping[str, object], target_dir: Path) -> bool:
    if target_dir.exists():
        return False
    return state.get("account_dir_exists_at_start") is True


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_or_zero(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_login_log_text(
    log_path: Path,
    *,
    account: str = "",
    log_offset: Optional[int] = None,
) -> str:
    if log_offset is not None:
        with open(log_path, "rb") as handle:
            handle.seek(max(0, log_offset))
            return handle.read().decode("utf-8", errors="replace")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if not account:
        return text
    marker = f"] starting login for {account}"
    index = text.rfind(marker)
    if index < 0:
        return text
    line_start = text.rfind("\n", 0, index) + 1
    return text[line_start:]


def _clean_login_url(url: str) -> str:
    return url.rstrip(LOGIN_URL_SUFFIX_CHARS)


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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
