"""Configuration management — reads and writes config.json."""

import json
import os
from pathlib import Path


def _default_config_dir() -> Path:
    core_dir = Path(__file__).resolve().parent
    if core_dir.name == "core" and core_dir.parent.name == "src":
        return core_dir.parent.parent
    return core_dir


CONFIG_DIR = Path(os.environ.get("CODEX_PROXY_CONFIG_DIR") or _default_config_dir()).expanduser()
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "port": 8800,
    "rate_limit_cooldown": 60,
    "rotation_strategy": "most_available",
    "product_mode": "standard",
    "max_retries": 10,
    "quota_refresh_interval": 300,
    "quota_tracker_enabled": True,
    "quota_tracker_user_set": False,
    "max_request_body_mb": 512,
    "upstream_connect_timeout_sec": 10,
    "upstream_transient_retries": 2,
    "upstream_transient_backoff_ms": 250,
    "codex_stream_mode": "realtime",
    "codex_stream_mode_user_set": False,
    "codex_hybrid_probe_seconds": 8,
    "codex_hybrid_probe_bytes": 262144,
    "codex_stream_retry_cooldown": 0,
    "stream_keepalive_seconds": 15,
    "stream_bootstrap_retries": 1,
    "nonstream_keepalive_interval": 15,
    "websocket_heartbeat_seconds": 0,
    "session_affinity_enabled": True,
    "session_affinity_ttl_seconds": 3600,
    "remote_proxy_mode": "fixed_account",
    "remote_account": "current",
    "quota_weight_5h": 0.5,
    "quota_weight_7d": 0.5,
    "log_level": "INFO",
}


class ConfigError(ValueError):
    """Raised when config input is invalid."""


def load() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
    if cfg.get("quota_tracker_enabled") is False and not cfg.get("quota_tracker_user_set"):
        cfg["quota_tracker_enabled"] = True
    return validate({**DEFAULTS, **cfg})


def save(cfg: dict) -> None:
    validated = validate(cfg)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)
        f.write("\n")
    tmp_path.replace(CONFIG_PATH)


def get(key: str):
    cfg = load()
    return cfg.get(key, DEFAULTS.get(key))


def validate(cfg: dict) -> dict:
    """Return normalized config or raise ConfigError."""
    merged = {**DEFAULTS, **(cfg or {})}
    errors = []

    def int_range(key: str, min_value: int, max_value: int) -> int:
        value = merged.get(key)
        if isinstance(value, bool):
            errors.append(f"{key} must be an integer")
            return DEFAULTS[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            errors.append(f"{key} must be an integer")
            return DEFAULTS[key]
        if not min_value <= value <= max_value:
            errors.append(f"{key} must be between {min_value} and {max_value}")
        return value

    def float_range(key: str, min_value: float, max_value: float) -> float:
        value = merged.get(key)
        if isinstance(value, bool):
            errors.append(f"{key} must be a number")
            return DEFAULTS[key]
        try:
            value = float(value)
        except (TypeError, ValueError):
            errors.append(f"{key} must be a number")
            return DEFAULTS[key]
        if not min_value <= value <= max_value:
            errors.append(f"{key} must be between {min_value} and {max_value}")
        return round(value, 3)

    def bool_value(key: str) -> bool:
        value = merged.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        errors.append(f"{key} must be true or false")
        return DEFAULTS[key]

    normalized = {
        "port": int_range("port", 1024, 65535),
        "rate_limit_cooldown": int_range("rate_limit_cooldown", 1, 3600),
        "rotation_strategy": str(merged.get("rotation_strategy", DEFAULTS["rotation_strategy"])),
        "product_mode": str(merged.get("product_mode", DEFAULTS["product_mode"])).lower(),
        "max_retries": int_range("max_retries", 1, 50),
        "quota_refresh_interval": int_range("quota_refresh_interval", 30, 86400),
        "quota_tracker_enabled": bool_value("quota_tracker_enabled"),
        "quota_tracker_user_set": bool_value("quota_tracker_user_set"),
        "max_request_body_mb": int_range("max_request_body_mb", 1, 1024),
        "upstream_connect_timeout_sec": int_range("upstream_connect_timeout_sec", 1, 60),
        "upstream_transient_retries": int_range("upstream_transient_retries", 0, 5),
        "upstream_transient_backoff_ms": int_range("upstream_transient_backoff_ms", 0, 5000),
        "codex_stream_mode": str(merged.get("codex_stream_mode", DEFAULTS["codex_stream_mode"])).lower(),
        "codex_stream_mode_user_set": bool_value("codex_stream_mode_user_set"),
        "codex_hybrid_probe_seconds": int_range("codex_hybrid_probe_seconds", 0, 120),
        "codex_hybrid_probe_bytes": int_range("codex_hybrid_probe_bytes", 1024, 10485760),
        "codex_stream_retry_cooldown": int_range("codex_stream_retry_cooldown", 0, 3600),
        "stream_keepalive_seconds": int_range("stream_keepalive_seconds", 0, 300),
        "stream_bootstrap_retries": int_range("stream_bootstrap_retries", 0, 5),
        "nonstream_keepalive_interval": int_range("nonstream_keepalive_interval", 0, 300),
        "websocket_heartbeat_seconds": int_range("websocket_heartbeat_seconds", 0, 300),
        "session_affinity_enabled": bool_value("session_affinity_enabled"),
        "session_affinity_ttl_seconds": int_range("session_affinity_ttl_seconds", 60, 86400),
        "remote_proxy_mode": str(merged.get("remote_proxy_mode", DEFAULTS["remote_proxy_mode"])).lower(),
        "remote_account": str(merged.get("remote_account", DEFAULTS["remote_account"])).strip() or DEFAULTS["remote_account"],
        "quota_weight_5h": float_range("quota_weight_5h", 0, 1),
        "quota_weight_7d": float_range("quota_weight_7d", 0, 1),
        "log_level": str(merged.get("log_level", DEFAULTS["log_level"])).upper(),
    }

    if (
        normalized["codex_stream_mode"] == "hybrid"
        and not normalized["codex_stream_mode_user_set"]
    ):
        normalized["codex_stream_mode"] = "realtime"

    if normalized["rotation_strategy"] not in {"round_robin", "most_available"}:
        errors.append("rotation_strategy must be round_robin or most_available")

    if normalized["product_mode"] not in {"standard", "compatibility", "diagnostic"}:
        errors.append("product_mode must be standard, compatibility, or diagnostic")

    if normalized["codex_stream_mode"] not in {"realtime", "buffered", "hybrid"}:
        errors.append("codex_stream_mode must be realtime, buffered, or hybrid")

    if normalized["remote_proxy_mode"] not in {"fixed_account", "off"}:
        errors.append("remote_proxy_mode must be fixed_account or off")

    if normalized["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    if normalized["quota_weight_5h"] + normalized["quota_weight_7d"] <= 0:
        errors.append("quota weights must not both be zero")

    if errors:
        raise ConfigError("; ".join(errors))

    return normalized
