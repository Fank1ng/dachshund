"""Configuration management — reads and writes config.json."""

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "port": 8800,
    "rate_limit_cooldown": 60,
    "rotation_strategy": "round_robin",
    "max_retries": 10,
    "quota_refresh_interval": 300,
    "quota_tracker_enabled": False,
    "max_request_body_mb": 512,
    "upstream_connect_timeout_sec": 10,
    "upstream_transient_retries": 2,
    "upstream_transient_backoff_ms": 250,
    "quota_weight_5h": 0.7,
    "quota_weight_7d": 0.3,
    "log_level": "INFO",
}


class ConfigError(ValueError):
    """Raised when config input is invalid."""


def load() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    else:
        cfg = {}
    return validate({**DEFAULTS, **cfg})


def save(cfg: dict) -> None:
    validated = validate(cfg)
    tmp_path = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w") as f:
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
        "max_retries": int_range("max_retries", 1, 50),
        "quota_refresh_interval": int_range("quota_refresh_interval", 30, 86400),
        "quota_tracker_enabled": bool_value("quota_tracker_enabled"),
        "max_request_body_mb": int_range("max_request_body_mb", 1, 1024),
        "upstream_connect_timeout_sec": int_range("upstream_connect_timeout_sec", 1, 60),
        "upstream_transient_retries": int_range("upstream_transient_retries", 0, 5),
        "upstream_transient_backoff_ms": int_range("upstream_transient_backoff_ms", 0, 5000),
        "quota_weight_5h": float_range("quota_weight_5h", 0, 1),
        "quota_weight_7d": float_range("quota_weight_7d", 0, 1),
        "log_level": str(merged.get("log_level", DEFAULTS["log_level"])).upper(),
    }

    if normalized["rotation_strategy"] not in {"round_robin", "most_available"}:
        errors.append("rotation_strategy must be round_robin or most_available")

    if normalized["log_level"] not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append("log_level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

    if normalized["quota_weight_5h"] + normalized["quota_weight_7d"] <= 0:
        errors.append("quota weights must not both be zero")

    if errors:
        raise ConfigError("; ".join(errors))

    return normalized
