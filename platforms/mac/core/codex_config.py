"""Helpers for toggling Codex CLI/App proxy settings."""

import re
import time
from pathlib import Path
from typing import Optional

from config import get

CODEX_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
LEGACY_OPENAI_KEY = "openai_base_url"
PROVIDER_ID = "codex-account-pool"
LEGACY_PROVIDER_IDS = ("openai-proxy",)
OPENAI_SECTION = f"model_providers.{PROVIDER_ID}"
MODEL_PROVIDER_KEY = "model_provider"
OPENAI_KEY = "base_url"
CHATGPT_KEY = "chatgpt_base_url"
STREAM_MAX_RETRIES_KEY = "stream_max_retries"
STREAM_IDLE_TIMEOUT_MS_KEY = "stream_idle_timeout_ms"
STREAM_MAX_RETRIES = 8
STREAM_IDLE_TIMEOUT_MS = 600000


def proxy_urls() -> dict:
    port = get("port")
    return {
        "openai_base_url": f"http://127.0.0.1:{port}/v1",
        "chatgpt_base_url": f"http://127.0.0.1:{port}/backend-api/",
        "codex_base_url": f"http://127.0.0.1:{port}/v1",
        "legacy_codex_base_url": f"http://127.0.0.1:{port}/backend-api/codex",
    }


def status(path: Optional[Path] = None) -> dict:
    config_path = path or CODEX_CONFIG_PATH
    urls = proxy_urls()
    values = _read_values(config_path)
    provider = values.get(MODEL_PROVIDER_KEY)
    chatgpt_backend_enabled = values.get(CHATGPT_KEY) == urls["chatgpt_base_url"]
    stream_settings_enabled = (
        values.get(STREAM_MAX_RETRIES_KEY) == STREAM_MAX_RETRIES
        and values.get(STREAM_IDLE_TIMEOUT_MS_KEY) == STREAM_IDLE_TIMEOUT_MS
    )
    codex_pool_enabled = (
        provider == PROVIDER_ID
        and values.get(f"{OPENAI_SECTION}.{OPENAI_KEY}") == urls["codex_base_url"]
        and values.get(f"{OPENAI_SECTION}.wire_api") == "responses"
        and values.get(f"{OPENAI_SECTION}.supports_websockets") is True
        and stream_settings_enabled
    )
    legacy_codex_pool_enabled = (
        provider == PROVIDER_ID
        and values.get(f"{OPENAI_SECTION}.{OPENAI_KEY}") == urls["legacy_codex_base_url"]
        and values.get(f"{OPENAI_SECTION}.wire_api") == "responses"
    )
    legacy_provider_enabled = provider in LEGACY_PROVIDER_IDS or (
        values.get(f"model_providers.openai-proxy.{OPENAI_KEY}") == urls["openai_base_url"]
    )
    enabled = chatgpt_backend_enabled and codex_pool_enabled
    return {
        "path": str(config_path),
        "exists": config_path.exists(),
        "enabled": enabled,
        "mode": (
                "codex_pool_provider"
                if enabled
                else (
                    "legacy_codex_pool_provider"
                    if chatgpt_backend_enabled and legacy_codex_pool_enabled
                    else ("partial_chatgpt_backend" if chatgpt_backend_enabled else ("legacy_openai_provider" if legacy_provider_enabled else "direct"))
                )
        ),
        "provider_mode_enabled": codex_pool_enabled,
        "legacy_provider_mode_enabled": legacy_codex_pool_enabled,
        "chatgpt_backend_enabled": chatgpt_backend_enabled,
        "expected": urls,
        "current": {
            MODEL_PROVIDER_KEY: values.get(MODEL_PROVIDER_KEY),
            f"{OPENAI_SECTION}.{OPENAI_KEY}": values.get(f"{OPENAI_SECTION}.{OPENAI_KEY}"),
            f"{OPENAI_SECTION}.wire_api": values.get(f"{OPENAI_SECTION}.wire_api"),
            f"{OPENAI_SECTION}.requires_openai_auth": values.get(f"{OPENAI_SECTION}.requires_openai_auth"),
            f"{OPENAI_SECTION}.supports_websockets": values.get(f"{OPENAI_SECTION}.supports_websockets"),
            STREAM_MAX_RETRIES_KEY: values.get(STREAM_MAX_RETRIES_KEY),
            STREAM_IDLE_TIMEOUT_MS_KEY: values.get(STREAM_IDLE_TIMEOUT_MS_KEY),
            LEGACY_OPENAI_KEY: values.get(LEGACY_OPENAI_KEY),
            CHATGPT_KEY: values.get(CHATGPT_KEY),
        },
    }


def set_enabled(enabled: bool, path: Optional[Path] = None) -> dict:
    config_path = path or CODEX_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    original = ""
    if config_path.exists():
        try:
            original = config_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            original = config_path.read_text(encoding="utf-8-sig")
    backup_path = None
    if config_path.exists():
        backup_path = config_path.with_suffix(
            f"{config_path.suffix}.{int(time.time())}.bak"
        )
        backup_path.write_text(original, encoding="utf-8")

    lines = original.splitlines()
    urls = proxy_urls()
    if enabled:
        lines = _set_key(lines, LEGACY_OPENAI_KEY, None, comment_out=True)
        lines = _set_key(lines, MODEL_PROVIDER_KEY, PROVIDER_ID, comment_out=False, root_only=True)
        lines = _set_key(lines, CHATGPT_KEY, urls["chatgpt_base_url"], comment_out=False, root_only=True)
        lines = _set_key(lines, STREAM_MAX_RETRIES_KEY, STREAM_MAX_RETRIES, comment_out=False, root_only=True)
        lines = _set_key(lines, STREAM_IDLE_TIMEOUT_MS_KEY, STREAM_IDLE_TIMEOUT_MS, comment_out=False, root_only=True)
        for legacy_id in LEGACY_PROVIDER_IDS:
            lines = _comment_section(lines, f"model_providers.{legacy_id}")
        lines = _set_section_key(lines, OPENAI_SECTION, "name", "OpenAI")
        lines = _set_section_key(lines, OPENAI_SECTION, OPENAI_KEY, urls["codex_base_url"])
        lines = _set_section_key(lines, OPENAI_SECTION, "wire_api", "responses")
        lines = _set_section_key(lines, OPENAI_SECTION, "requires_openai_auth", True)
        lines = _set_section_key(lines, OPENAI_SECTION, "supports_websockets", True)
    else:
        lines = _set_key(lines, LEGACY_OPENAI_KEY, None, comment_out=True)
        lines = _set_key(lines, MODEL_PROVIDER_KEY, None, comment_out=True, root_only=True)
        lines = _set_key(lines, CHATGPT_KEY, None, comment_out=True, root_only=True)
        lines = _set_key(lines, STREAM_MAX_RETRIES_KEY, None, comment_out=True, root_only=True)
        lines = _set_key(lines, STREAM_IDLE_TIMEOUT_MS_KEY, None, comment_out=True, root_only=True)
        lines = _set_section_key(lines, OPENAI_SECTION, OPENAI_KEY, None, comment_out=True)
        lines = _set_section_key(lines, OPENAI_SECTION, "wire_api", None, comment_out=True)
        lines = _set_section_key(lines, OPENAI_SECTION, "requires_openai_auth", None, comment_out=True)
        lines = _set_section_key(lines, OPENAI_SECTION, "supports_websockets", None, comment_out=True)

    text = "\n".join(lines).rstrip() + "\n"
    tmp_path = config_path.with_suffix(f"{config_path.suffix}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(config_path)
    result = status(config_path)
    result["backup_path"] = str(backup_path) if backup_path else None
    result["changed"] = True
    return result


def ensure_enabled(enabled: bool = True, path: Optional[Path] = None) -> dict:
    """Set proxy mode only when the current config does not already match."""
    config_path = path or CODEX_CONFIG_PATH
    current = status(config_path)
    if current["enabled"] == enabled:
        current["backup_path"] = None
        current["changed"] = False
        return current
    return set_enabled(enabled, config_path)


def _read_values(path: Path) -> dict:
    if not path.exists():
        return {}
    values = {}
    section = ""
    section_pattern = re.compile(r'^\s*\[(.+?)\]\s*$')
    pattern = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$')
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_text(encoding="utf-8-sig")
    for line in content.splitlines():
        section_match = section_pattern.match(line)
        if section_match:
            section = section_match.group(1).strip()
            continue
        match = pattern.match(line)
        if not match:
            continue
        key = match.group(1)
        raw_value = match.group(2).split("#", 1)[0].strip()
        if raw_value.startswith(("\"", "'")) and raw_value.endswith(("\"", "'")):
            value = raw_value[1:-1]
        elif raw_value.lower() == "true":
            value = True
        elif raw_value.lower() == "false":
            value = False
        elif raw_value.isdigit():
            value = int(raw_value)
        else:
            value = raw_value
        if section:
            values[f"{section}.{key}"] = value
        else:
            values[key] = value
    return values


def _format_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return f'"{value}"'


def _set_key(
    lines: list[str],
    key: str,
    value: Optional[str],
    *,
    comment_out: bool,
    root_only: bool = False,
) -> list[str]:
    key_pattern = re.compile(rf'^(\s*)#?\s*{re.escape(key)}\s*=')
    section_pattern = re.compile(r'^\s*\[[^\]]+\]\s*$')
    output = []
    seen = False
    in_section = False
    for line in lines:
        if key_pattern.match(line) and (not root_only or not in_section):
            if comment_out:
                output.append(line if line.lstrip().startswith("#") else f"# {line}")
            elif not seen:
                output.append(f"{key} = {_format_value(value)}")
                seen = True
            continue
        output.append(line)
        if section_pattern.match(line):
            in_section = True

    if not seen and not comment_out:
        insert_at = len(output)
        if root_only:
            for index, line in enumerate(output):
                if section_pattern.match(line):
                    insert_at = index
                    break
        new_lines = []
        if insert_at > 0 and output[insert_at - 1].strip():
            new_lines.append("")
        new_lines.append(f"{key} = {_format_value(value)}")
        if insert_at < len(output) and output[insert_at].strip():
            new_lines.append("")
        output[insert_at:insert_at] = new_lines

    return output


def _set_section_key(
    lines: list[str],
    section: str,
    key: str,
    value,
    *,
    comment_out: bool = False,
) -> list[str]:
    section_pattern = re.compile(rf'^\s*\[{re.escape(section)}\]\s*$')
    any_section_pattern = re.compile(r'^\s*\[[^\]]+\]\s*$')
    key_pattern = re.compile(rf'^(\s*)#?\s*{re.escape(key)}\s*=')
    output = []
    in_section = False
    found_section = False
    seen_key = False

    for line in lines:
        if section_pattern.match(line):
            in_section = True
            found_section = True
            output.append(line)
            continue

        if in_section and any_section_pattern.match(line):
            if not seen_key and not comment_out:
                output.append(f"{key} = {_format_value(value)}")
            in_section = False

        if in_section and key_pattern.match(line):
            if comment_out:
                output.append(line if line.lstrip().startswith("#") else f"# {line}")
            elif not seen_key:
                output.append(f"{key} = {_format_value(value)}")
                seen_key = True
            continue

        output.append(line)

    if found_section:
        if in_section and not seen_key and not comment_out:
            output.append(f"{key} = {_format_value(value)}")
        return output

    if comment_out:
        return output

    if output and output[-1].strip():
        output.append("")
    output.append(f"[{section}]")
    output.append(f"{key} = {_format_value(value)}")
    return output


def _comment_section(lines: list[str], section: str) -> list[str]:
    section_pattern = re.compile(rf'^\s*\[{re.escape(section)}\]\s*$')
    any_section_pattern = re.compile(r'^\s*\[[^\]]+\]\s*$')
    output = []
    in_section = False
    for line in lines:
        if section_pattern.match(line):
            in_section = True
            output.append(line if line.lstrip().startswith("#") else f"# {line}")
            continue
        if in_section and any_section_pattern.match(line):
            in_section = False
        if in_section and line.strip() and not line.lstrip().startswith("#"):
            output.append(f"# {line}")
        else:
            output.append(line)
    return output
