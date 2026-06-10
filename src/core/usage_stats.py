"""Token usage statistics captured from proxied Codex responses."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from config import CONFIG_DIR

USAGE_STATS_FILE = CONFIG_DIR / "usage_stats.json"
DAILY_DAYS = 31
WEEKLY_WEEKS = 53
RETENTION_DAYS = 371

logger = logging.getLogger(__name__)


def _empty_counter() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "requests": 0,
        "unknown_requests": 0,
    }


def _number(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


def _usage_from_dict(data: dict) -> Optional[dict]:
    input_tokens = _number(data.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _number(data.get("prompt_tokens"))
    output_tokens = _number(data.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _number(data.get("completion_tokens"))
    total_tokens = _number(data.get("total_tokens"))

    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    if total_tokens is None:
        return None
    return {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "total_tokens": total_tokens,
    }


def _find_usage_values(value: Any) -> list[dict]:
    found = []
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            parsed = _usage_from_dict(usage)
            if parsed:
                found.append(parsed)
        parsed = _usage_from_dict(value)
        if parsed:
            found.append(parsed)
        for item in value.values():
            found.extend(_find_usage_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_usage_values(item))
    return found


def extract_usage_from_json(value: Any) -> Optional[dict]:
    """Return the most complete token usage dict found in a JSON-like value."""
    found = _find_usage_values(value)
    if not found:
        return None
    return max(found, key=lambda item: item.get("total_tokens", 0))


def extract_usage_from_text(text: str) -> Optional[dict]:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return extract_usage_from_json(payload)


def extract_usage_from_bytes(body: bytes) -> Optional[dict]:
    try:
        return extract_usage_from_text(body.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def extract_usage_from_sse_bytes(body: bytes) -> Optional[dict]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    best = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        payload = stripped[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        usage = extract_usage_from_text(payload)
        if usage and (not best or usage["total_tokens"] >= best["total_tokens"]):
            best = usage
    return best


def extract_usage_from_ws_payload(data: Any) -> Optional[dict]:
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(data, str):
        return extract_usage_from_text(data)
    return None


class UsageCollector:
    """Incrementally captures the best usage payload from stream chunks."""

    def __init__(self):
        self._buffer = ""
        self._all_text = ""
        self.usage = None

    def feed_bytes(self, chunk: bytes) -> None:
        if not chunk:
            return
        try:
            text = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return
        self.feed_text(text)

    def feed_text(self, text: str) -> None:
        if not text:
            return
        self._all_text += text
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._feed_line(line)

    def finish(self) -> Optional[dict]:
        if self._buffer:
            self._feed_line(self._buffer)
            self._buffer = ""
        if not self.usage:
            self.usage = extract_usage_from_text(self._all_text)
        return self.usage

    def _feed_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped.startswith("data:"):
            return
        payload = stripped[5:].strip()
        if not payload or payload == "[DONE]":
            return
        usage = extract_usage_from_text(payload)
        if usage and (not self.usage or usage["total_tokens"] >= self.usage["total_tokens"]):
            self.usage = usage


def _load() -> dict:
    if not USAGE_STATS_FILE.exists():
        return {"requests": {}}
    try:
        with open(USAGE_STATS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"requests": {}}
    except Exception as e:
        logger.warning("failed to load token usage stats: %s", e)
        return {"requests": {}}


def _save(data: dict) -> None:
    try:
        USAGE_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = USAGE_STATS_FILE.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        tmp_path.replace(USAGE_STATS_FILE)
    except OSError as e:
        logger.warning("failed to save token usage stats: %s", e)


def _day_key(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).date().isoformat()


def _week_key(epoch: float) -> str:
    day = datetime.fromtimestamp(epoch).date()
    monday = day - timedelta(days=day.weekday())
    return monday.isoformat()


def _request_key(request_id: str, account: str, path: str, epoch: float) -> str:
    if request_id:
        return request_id
    return f"{account}:{path}:{int(epoch * 1000)}"


def _prune(data: dict, now: float) -> None:
    cutoff = now - (RETENTION_DAYS * 86400)
    requests = data.setdefault("requests", {})
    for key in list(requests.keys()):
        if float(requests.get(key, {}).get("at") or 0) < cutoff:
            requests.pop(key, None)


def record_request_usage(
    *,
    request_id: str,
    account: str,
    path: str,
    usage: Optional[dict],
    at: Optional[float] = None,
) -> None:
    """Persist exact usage when present, or mark the request as unknown."""
    if not path or "codex" not in path and not path.startswith("/v1/responses"):
        return
    epoch = at or time.time()
    key = _request_key(request_id, account, path, epoch)
    data = _load()
    _prune(data, epoch)
    requests = data.setdefault("requests", {})
    existing = requests.get(key)
    known = bool(usage)
    if existing and (existing.get("known") or not known):
        return
    counter = _empty_counter()
    if usage:
        counter.update({
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "requests": 1,
            "unknown_requests": 0,
        })
    else:
        counter["requests"] = 1
        counter["unknown_requests"] = 1
    requests[key] = {
        **counter,
        "known": known,
        "account": account,
        "path": path,
        "at": epoch,
        "day": _day_key(epoch),
        "week": _week_key(epoch),
    }
    _save(data)


def _date_series(days: int) -> list[str]:
    today = datetime.fromtimestamp(time.time()).date()
    start = today - timedelta(days=days - 1)
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _week_series(weeks: int) -> list[str]:
    today = datetime.fromtimestamp(time.time()).date()
    this_monday = today - timedelta(days=today.weekday())
    start = this_monday - timedelta(weeks=weeks - 1)
    return [(start + timedelta(weeks=i)).isoformat() for i in range(weeks)]


def _add(target: dict, source: dict) -> None:
    for key in ("input_tokens", "output_tokens", "total_tokens", "requests", "unknown_requests"):
        target[key] = int(target.get(key) or 0) + int(source.get(key) or 0)


def summary() -> dict:
    data = _load()
    now = time.time()
    _prune(data, now)
    requests = data.setdefault("requests", {})
    daily_keys = _date_series(DAILY_DAYS)
    weekly_keys = _week_series(WEEKLY_WEEKS)
    daily = {key: {"date": key, **_empty_counter()} for key in daily_keys}
    weekly = {key: {"week_start": key, **_empty_counter()} for key in weekly_keys}
    total = _empty_counter()
    last_recorded_at = None
    for row in requests.values():
        if not isinstance(row, dict):
            continue
        day = row.get("day")
        week = row.get("week")
        if day in daily:
            _add(daily[day], row)
        if week in weekly:
            _add(weekly[week], row)
        _add(total, row)
        at = float(row.get("at") or 0)
        if at > 0 and (last_recorded_at is None or at > last_recorded_at):
            last_recorded_at = at
    _save(data)
    return {
        "daily": [daily[key] for key in daily_keys],
        "weekly": [weekly[key] for key in weekly_keys],
        "total": total,
        "last_recorded_at": last_recorded_at,
    }
