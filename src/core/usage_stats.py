"""Token usage statistics captured from proxied Codex responses."""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from config import CONFIG_DIR

USAGE_STATS_FILE = CONFIG_DIR / "usage_stats.json"
USAGE_HISTORY_DB = CONFIG_DIR / "usage_history.sqlite"
DAILY_DAYS = 31
MAX_DAILY_DAYS = 371
WEEKLY_WEEKS = 53
RETENTION_DAYS = 371
COUNTING_POLICY = "proxy_captured_usage"
COUNTING_POLICY_DETAIL = (
    "Local proxy-captured usage from upstream response payloads. "
    "Displayed totals add captured cache tokens to approximate the official heatmap. "
    "Requests that did not expose usage are counted as unknown and do not add tokens."
)
COUNTER_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_tokens",
    "cache_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cache_tokens_observed_requests",
    "reasoning_tokens_observed_requests",
    "raw_total_tokens",
    "total_tokens",
    "requests",
    "unknown_requests",
)

logger = logging.getLogger(__name__)


def _empty_counter() -> dict:
    return {key: 0 for key in COUNTER_KEYS}


def _number(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    return None


INPUT_TOKEN_KEYS = (
    "input_tokens",
    "prompt_tokens",
    "input_token_count",
    "prompt_token_count",
    "input_text_tokens",
)
OUTPUT_TOKEN_KEYS = (
    "output_tokens",
    "completion_tokens",
    "output_token_count",
    "completion_token_count",
    "output_text_tokens",
)
TOTAL_TOKEN_KEYS = (
    "total_tokens",
    "total_token_count",
    "tokens_total",
    "totalTokens",
)
REASONING_TOKEN_KEYS = (
    "reasoning_tokens",
    "reasoningTokens",
)
CACHED_TOKEN_KEYS = (
    "cached_tokens",
    "cachedTokens",
)
CACHE_TOKEN_KEYS = (
    "cache_tokens",
    "cacheTokens",
)
CACHE_READ_TOKEN_KEYS = (
    "cache_read_tokens",
    "cacheReadTokens",
)
CACHE_CREATION_TOKEN_KEYS = (
    "cache_creation_tokens",
    "cacheCreationTokens",
)
USAGE_CONTAINER_KEYS = (
    "usage",
    "tokens",
    "token_usage",
    "tokenUsage",
    "token_counts",
    "tokenCounts",
)


def _first_number(data: dict, keys: tuple[str, ...]) -> Optional[int]:
    for key in keys:
        number = _number(data.get(key))
        if number is not None:
            return number
    return None


def _first_nested_number(data: dict, container_keys: tuple[str, ...], value_keys: tuple[str, ...]) -> Optional[int]:
    for container_key in container_keys:
        container = data.get(container_key)
        if isinstance(container, dict):
            number = _first_number(container, value_keys)
            if number is not None:
                return number
    return None


def _first_string(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def compatible_cached_tokens(usage: Optional[dict]) -> int:
    if not usage:
        return 0
    cache_tokens = int(usage.get("cache_tokens") or usage.get("cached_tokens") or 0)
    cache_read_tokens = int(usage.get("cache_read_tokens") or 0)
    cache_creation_tokens = int(usage.get("cache_creation_tokens") or 0)
    return 0 if (cache_read_tokens or cache_creation_tokens) else cache_tokens


def _usage_from_dict(data: dict, *, usage_container: bool = False) -> Optional[dict]:
    input_keys = INPUT_TOKEN_KEYS + (("input", "prompt") if usage_container else ())
    output_keys = OUTPUT_TOKEN_KEYS + (("output", "completion") if usage_container else ())
    total_keys = TOTAL_TOKEN_KEYS + (("total",) if usage_container else ())

    input_tokens = _first_number(data, input_keys)
    output_tokens = _first_number(data, output_keys)
    reasoning_tokens = _first_number(data, REASONING_TOKEN_KEYS)
    cached_tokens = _first_number(data, CACHED_TOKEN_KEYS)
    cache_tokens = _first_number(data, CACHE_TOKEN_KEYS)
    cache_read_tokens = _first_number(data, CACHE_READ_TOKEN_KEYS)
    cache_creation_tokens = _first_number(data, CACHE_CREATION_TOKEN_KEYS)
    nested_cached_tokens = _first_nested_number(
        data,
        (
            "input_tokens_details",
            "input_token_details",
            "inputTokensDetails",
            "inputTokenDetails",
            "prompt_tokens_details",
            "prompt_token_details",
            "promptTokensDetails",
            "promptTokenDetails",
        ),
        CACHED_TOKEN_KEYS + CACHE_TOKEN_KEYS,
    )
    nested_reasoning_tokens = _first_nested_number(
        data,
        (
            "output_tokens_details",
            "output_token_details",
            "outputTokensDetails",
            "outputTokenDetails",
            "completion_tokens_details",
            "completion_token_details",
            "completionTokensDetails",
            "completionTokenDetails",
        ),
        REASONING_TOKEN_KEYS,
    )
    if cached_tokens is None:
        cached_tokens = nested_cached_tokens
    if cache_tokens is None and nested_cached_tokens is not None:
        cache_tokens = nested_cached_tokens
    if reasoning_tokens is None:
        reasoning_tokens = nested_reasoning_tokens
    cache_tokens_observed = any(
        value is not None
        for value in (cached_tokens, cache_tokens, cache_read_tokens, cache_creation_tokens, nested_cached_tokens)
    )
    reasoning_tokens_observed = reasoning_tokens is not None or nested_reasoning_tokens is not None
    total_tokens = _first_number(data, total_keys)
    usage = {
        "input_tokens": input_tokens or 0,
        "output_tokens": output_tokens or 0,
        "reasoning_tokens": reasoning_tokens or 0,
        "cached_tokens": cached_tokens or 0,
        "cache_tokens": cache_tokens if cache_tokens is not None else (cached_tokens or 0),
        "cache_read_tokens": cache_read_tokens or 0,
        "cache_creation_tokens": cache_creation_tokens or 0,
        "cache_tokens_observed": cache_tokens_observed,
        "reasoning_tokens_observed": reasoning_tokens_observed,
        "requested_model": _first_string(data, ("requested_model", "requestedModel")),
        "resolved_model": _first_string(data, ("resolved_model", "resolvedModel", "model")),
        "reasoning_effort": _first_string(data, ("reasoning_effort", "reasoningEffort")),
        "service_tier": _first_string(data, ("service_tier", "serviceTier")),
        "executor_type": _first_string(data, ("executor_type", "executorType")),
    }

    if total_tokens is None and (
        input_tokens is not None
        or output_tokens is not None
        or reasoning_tokens is not None
        or cached_tokens is not None
        or cache_tokens is not None
        or cache_read_tokens is not None
        or cache_creation_tokens is not None
    ):
        total_tokens = (
            usage["input_tokens"]
            + usage["output_tokens"]
            + usage["reasoning_tokens"]
            + compatible_cached_tokens(usage)
            + usage["cache_read_tokens"]
            + usage["cache_creation_tokens"]
        )
    if total_tokens is None:
        return None
    usage["total_tokens"] = total_tokens
    return usage


def _find_usage_values(value: Any) -> list[dict]:
    found = []
    if isinstance(value, dict):
        for key in USAGE_CONTAINER_KEYS:
            usage = value.get(key)
            if isinstance(usage, dict):
                parsed = _usage_from_dict(usage, usage_container=True)
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
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return extract_usage_from_sse_bytes(data) or extract_usage_from_text(text)
    if isinstance(data, str):
        return extract_usage_from_sse_bytes(data.encode("utf-8")) or extract_usage_from_text(data)
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


def _load_legacy_json() -> dict:
    if not USAGE_STATS_FILE.exists():
        return {"requests": {}}
    try:
        with open(USAGE_STATS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"requests": {}}
    except Exception as e:
        logger.warning("failed to load token usage stats: %s", e)
        return {"requests": {}}


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


def _event_hash(*parts: Any) -> str:
    text = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _connect() -> sqlite3.Connection:
    USAGE_HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USAGE_HISTORY_DB)
    conn.row_factory = sqlite3.Row
    _ensure_db(conn)
    _import_legacy_json_once(conn)
    return conn


def initialize_storage() -> dict:
    """Create/migrate usage history storage and return diagnostics."""
    with _connect() as conn:
        return _storage_diagnostics(conn)


def _storage_diagnostics(conn: sqlite3.Connection) -> dict:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()}
    required = {"cache_tokens_observed", "reasoning_tokens_observed"}
    return {
        "history_db": str(USAGE_HISTORY_DB),
        "history_available": True,
        "observed_columns_ok": required.issubset(columns),
        "has_cache_tokens_observed": "cache_tokens_observed" in columns,
        "has_reasoning_tokens_observed": "reasoning_tokens_observed" in columns,
    }


def diagnostics() -> dict:
    try:
        with _connect() as conn:
            return _storage_diagnostics(conn)
    except sqlite3.Error as e:
        return {
            "history_db": str(USAGE_HISTORY_DB),
            "history_available": False,
            "observed_columns_ok": False,
            "error": str(e),
        }


def _ensure_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_hash TEXT NOT NULL UNIQUE,
            request_id TEXT,
            at REAL NOT NULL,
            day TEXT NOT NULL,
            week TEXT NOT NULL,
            account TEXT NOT NULL,
            path TEXT NOT NULL,
            method TEXT,
            model TEXT,
            status INTEGER,
            failed INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            reasoning_tokens INTEGER NOT NULL DEFAULT 0,
            cached_tokens INTEGER NOT NULL DEFAULT 0,
            cache_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
            cache_tokens_observed INTEGER NOT NULL DEFAULT 0,
            reasoning_tokens_observed INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            known INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'proxy',
            latency_ms REAL,
            ttft_ms REAL,
            requested_model TEXT,
            resolved_model TEXT,
            reasoning_effort TEXT,
            service_tier TEXT,
            executor_type TEXT,
            created_at REAL NOT NULL
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(usage_events)").fetchall()}
    migrations = {
        "cache_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cache_read_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cache_creation_tokens": "INTEGER NOT NULL DEFAULT 0",
        "cache_tokens_observed": "INTEGER NOT NULL DEFAULT 0",
        "reasoning_tokens_observed": "INTEGER NOT NULL DEFAULT 0",
        "latency_ms": "REAL",
        "ttft_ms": "REAL",
        "requested_model": "TEXT",
        "resolved_model": "TEXT",
        "reasoning_effort": "TEXT",
        "service_tier": "TEXT",
        "executor_type": "TEXT",
    }
    for name, ddl in migrations.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE usage_events ADD COLUMN {name} {ddl}")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_at ON usage_events(at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_day ON usage_events(day)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_week ON usage_events(week)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_account ON usage_events(account)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_model ON usage_events(model)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_events_request_id ON usage_events(request_id)")
    conn.commit()


def _import_legacy_json_once(conn: sqlite3.Connection) -> None:
    if not USAGE_STATS_FILE.exists():
        return
    key = f"legacy_json_imported:{USAGE_STATS_FILE.resolve()}"
    imported = conn.execute("SELECT value FROM usage_meta WHERE key = ?", (key,)).fetchone()
    if imported:
        return
    data = _load_legacy_json()
    requests = data.get("requests") if isinstance(data, dict) else {}
    if not isinstance(requests, dict):
        requests = {}
    now = time.time()
    for legacy_key, row in requests.items():
        if not isinstance(row, dict):
            continue
        at = float(row.get("at") or now)
        usage = {
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "reasoning_tokens": int(row.get("reasoning_tokens") or 0),
            "cached_tokens": int(row.get("cached_tokens") or 0),
            "cache_tokens": int(row.get("cache_tokens") or row.get("cached_tokens") or 0),
            "cache_read_tokens": int(row.get("cache_read_tokens") or 0),
            "cache_creation_tokens": int(row.get("cache_creation_tokens") or 0),
            "total_tokens": int(row.get("total_tokens") or 0),
        }
        if not usage["total_tokens"] and any(usage.values()):
            usage["total_tokens"] = (
                usage["input_tokens"]
                + usage["output_tokens"]
                + usage["reasoning_tokens"]
                + compatible_cached_tokens(usage)
                + usage["cache_read_tokens"]
                + usage["cache_creation_tokens"]
            )
        _insert_or_update_event(
            conn,
            request_id=str(legacy_key) if legacy_key else "",
            account=str(row.get("account") or ""),
            path=str(row.get("path") or ""),
            usage=usage if bool(row.get("known")) else None,
            at=at,
            method=str(row.get("method") or ""),
            model=str(row.get("model") or ""),
            status=_optional_int(row.get("status")),
            failed=bool(row.get("failed") or False),
            source="legacy_json",
            event_hash=_event_hash("legacy_json", legacy_key),
        )
    conn.execute(
        "INSERT OR REPLACE INTO usage_meta(key, value) VALUES (?, ?)",
        (key, str(now)),
    )
    conn.commit()


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _prune(conn: sqlite3.Connection, now: float) -> None:
    cutoff = now - (RETENTION_DAYS * 86400)
    conn.execute("DELETE FROM usage_events WHERE at < ?", (cutoff,))


def _counter_from_usage(usage: Optional[dict]) -> dict:
    counter = _empty_counter()
    if usage:
        for key in ("input_tokens", "output_tokens", "reasoning_tokens", "cached_tokens", "cache_tokens", "cache_read_tokens", "cache_creation_tokens", "total_tokens"):
            counter[key] = int(usage.get(key) or 0)
        if not counter["cache_tokens"] and counter["cached_tokens"]:
            counter["cache_tokens"] = counter["cached_tokens"]
        counter["cache_tokens_observed_requests"] = 1 if usage.get("cache_tokens_observed") else 0
        counter["reasoning_tokens_observed_requests"] = 1 if usage.get("reasoning_tokens_observed") else 0
        counter["requests"] = 1
        if not counter["total_tokens"]:
            counter["total_tokens"] = (
                counter["input_tokens"]
                + counter["output_tokens"]
                + counter["reasoning_tokens"]
                + compatible_cached_tokens(counter)
                + counter["cache_read_tokens"]
                + counter["cache_creation_tokens"]
            )
    else:
        counter["requests"] = 1
        counter["unknown_requests"] = 1
    return counter


def _insert_or_update_event(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    account: str,
    path: str,
    usage: Optional[dict],
    at: float,
    method: str = "",
    model: str = "",
    status: Optional[int] = None,
    failed: bool = False,
    source: str = "proxy",
    event_hash: str = "",
    latency_ms: Optional[float] = None,
    ttft_ms: Optional[float] = None,
    requested_model: str = "",
    resolved_model: str = "",
    reasoning_effort: str = "",
    service_tier: str = "",
    executor_type: str = "",
) -> None:
    if not path or "codex" not in path and not path.startswith("/v1/responses"):
        return
    key = _request_key(request_id, account, path, at)
    event_hash = event_hash or _event_hash("usage", key, account, path)
    known = bool(usage)
    counter = _counter_from_usage(usage)
    existing = None
    if request_id:
        existing = conn.execute(
            "SELECT id, known FROM usage_events WHERE request_id = ? ORDER BY id DESC LIMIT 1",
            (request_id,),
        ).fetchone()
    if existing is None:
        existing = conn.execute(
            "SELECT id, known FROM usage_events WHERE event_hash = ?",
            (event_hash,),
        ).fetchone()
    if existing and (int(existing["known"]) or not known):
        return
    values = {
        "event_hash": event_hash,
        "request_id": request_id,
        "at": at,
        "day": _day_key(at),
        "week": _week_key(at),
        "account": account,
        "path": path,
        "method": method,
        "model": model,
        "status": status,
        "failed": 1 if failed or (status is not None and status >= 400) else 0,
        "input_tokens": counter["input_tokens"],
        "output_tokens": counter["output_tokens"],
        "reasoning_tokens": counter["reasoning_tokens"],
        "cached_tokens": counter["cached_tokens"],
        "cache_tokens": counter["cache_tokens"],
        "cache_read_tokens": counter["cache_read_tokens"],
        "cache_creation_tokens": counter["cache_creation_tokens"],
        "cache_tokens_observed": 1 if counter["cache_tokens_observed_requests"] else 0,
        "reasoning_tokens_observed": 1 if counter["reasoning_tokens_observed_requests"] else 0,
        "total_tokens": counter["total_tokens"],
        "known": 1 if known else 0,
        "source": source,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "requested_model": requested_model or str(usage.get("requested_model") or "") if usage else requested_model,
        "resolved_model": resolved_model or str(usage.get("resolved_model") or "") if usage else resolved_model,
        "reasoning_effort": reasoning_effort or str(usage.get("reasoning_effort") or "") if usage else reasoning_effort,
        "service_tier": service_tier or str(usage.get("service_tier") or "") if usage else service_tier,
        "executor_type": executor_type or str(usage.get("executor_type") or "") if usage else executor_type,
        "created_at": time.time(),
    }
    if existing:
        conn.execute("""
            UPDATE usage_events
            SET event_hash = :event_hash,
                at = :at,
                day = :day,
                week = :week,
                account = :account,
                path = :path,
                method = :method,
                model = :model,
                status = :status,
                failed = :failed,
                input_tokens = :input_tokens,
                output_tokens = :output_tokens,
                reasoning_tokens = :reasoning_tokens,
                cached_tokens = :cached_tokens,
                cache_tokens = :cache_tokens,
                cache_read_tokens = :cache_read_tokens,
                cache_creation_tokens = :cache_creation_tokens,
                cache_tokens_observed = :cache_tokens_observed,
                reasoning_tokens_observed = :reasoning_tokens_observed,
                total_tokens = :total_tokens,
                known = :known,
                source = :source,
                latency_ms = :latency_ms,
                ttft_ms = :ttft_ms,
                requested_model = :requested_model,
                resolved_model = :resolved_model,
                reasoning_effort = :reasoning_effort,
                service_tier = :service_tier,
                executor_type = :executor_type
            WHERE id = :id
        """, {**values, "id": existing["id"]})
        return
    conn.execute("""
        INSERT OR IGNORE INTO usage_events (
            event_hash, request_id, at, day, week, account, path, method, model,
            status, failed, input_tokens, output_tokens, reasoning_tokens,
            cached_tokens, cache_tokens, cache_read_tokens, cache_creation_tokens,
            cache_tokens_observed, reasoning_tokens_observed,
            total_tokens, known, source, latency_ms, ttft_ms, requested_model,
            resolved_model, reasoning_effort, service_tier, executor_type, created_at
        ) VALUES (
            :event_hash, :request_id, :at, :day, :week, :account, :path, :method, :model,
            :status, :failed, :input_tokens, :output_tokens, :reasoning_tokens,
            :cached_tokens, :cache_tokens, :cache_read_tokens, :cache_creation_tokens,
            :cache_tokens_observed, :reasoning_tokens_observed,
            :total_tokens, :known, :source, :latency_ms, :ttft_ms, :requested_model,
            :resolved_model, :reasoning_effort, :service_tier, :executor_type, :created_at
        )
    """, values)


def record_request_usage(
    *,
    request_id: str,
    account: str,
    path: str,
    usage: Optional[dict],
    at: Optional[float] = None,
    method: str = "",
    model: str = "",
    status: Optional[int] = None,
    failed: bool = False,
    source: str = "proxy",
    latency_ms: Optional[float] = None,
    ttft_ms: Optional[float] = None,
    requested_model: str = "",
    resolved_model: str = "",
    reasoning_effort: str = "",
    service_tier: str = "",
    executor_type: str = "",
) -> None:
    """Persist exact usage when present, or mark the request as unknown."""
    epoch = at or time.time()
    try:
        with _connect() as conn:
            _prune(conn, epoch)
            _insert_or_update_event(
                conn,
                request_id=request_id,
                account=account,
                path=path,
                usage=usage,
                at=epoch,
                method=method,
                model=model,
                status=status,
                failed=failed,
                source=source,
                latency_ms=latency_ms,
                ttft_ms=ttft_ms,
                requested_model=requested_model,
                resolved_model=resolved_model,
                reasoning_effort=reasoning_effort,
                service_tier=service_tier,
                executor_type=executor_type,
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("failed to save token usage history: %s", e)


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
    for key in COUNTER_KEYS:
        target[key] = int(target.get(key) or 0) + int(source.get(key) or 0)


def _where_clause(*, account: str = "", model: str = "", since: Optional[float] = None, until: Optional[float] = None) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    if account:
        clauses.append("account = ?")
        params.append(account)
    if model:
        clauses.append("model = ?")
        params.append(model)
    if since is not None:
        clauses.append("at >= ?")
        params.append(float(since))
    if until is not None:
        clauses.append("at <= ?")
        params.append(float(until))
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _row_counter(row: sqlite3.Row) -> dict:
    total_tokens = int(row["total_tokens"] or 0)
    return {
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "reasoning_tokens": int(row["reasoning_tokens"] or 0),
        "cached_tokens": int(row["cached_tokens"] or 0),
        "cache_tokens": int(row["cache_tokens"] or 0),
        "cache_read_tokens": int(row["cache_read_tokens"] or 0),
        "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
        "cache_tokens_observed_requests": int(row["cache_tokens_observed_requests"] or 0),
        "reasoning_tokens_observed_requests": int(row["reasoning_tokens_observed_requests"] or 0),
        "raw_total_tokens": total_tokens,
        "total_tokens": total_tokens,
        "requests": int(row["requests"] or 0),
        "unknown_requests": int(row["unknown_requests"] or 0),
    }


def _value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _cache_value(row: Any) -> int:
    cache_read = int(_value(row, "cache_read_tokens") or 0)
    cache_creation = int(_value(row, "cache_creation_tokens") or 0)
    if cache_read or cache_creation:
        return cache_read + cache_creation
    return max(int(_value(row, "cached_tokens") or 0), int(_value(row, "cache_tokens") or 0))


def _official_like_total(row: Any) -> int:
    raw_total = _value(row, "raw_total_tokens")
    if raw_total is None:
        raw_total = _value(row, "total_tokens")
    return int(raw_total or 0) + _cache_value(row)


def _apply_official_like_total(counter: dict) -> dict:
    counter["raw_total_tokens"] = int(counter.get("raw_total_tokens") or counter.get("total_tokens") or 0)
    counter["total_tokens"] = _official_like_total(counter)
    return counter


def _capture_state(observed: bool, value: int) -> str:
    if not observed:
        return "missing"
    return "observed_value" if int(value or 0) > 0 else "observed_zero"


def _clamped_daily_days(value: Optional[int]) -> int:
    try:
        days = int(value) if value is not None else DAILY_DAYS
    except (TypeError, ValueError):
        days = DAILY_DAYS
    return max(1, min(days, MAX_DAILY_DAYS))


def summary(
    *,
    account: str = "",
    model: str = "",
    since: Optional[float] = None,
    until: Optional[float] = None,
    daily_days: Optional[int] = None,
) -> dict:
    now = time.time()
    daily_keys = _date_series(_clamped_daily_days(daily_days))
    weekly_keys = _week_series(WEEKLY_WEEKS)
    daily = {key: {"date": key, **_empty_counter()} for key in daily_keys}
    weekly = {key: {"week_start": key, **_empty_counter()} for key in weekly_keys}
    total = _empty_counter()
    last_recorded_at = None
    try:
        with _connect() as conn:
            _prune(conn, now)
            where, params = _where_clause(account=account, model=model, since=since, until=until)
            daily_rows = conn.execute(f"""
                SELECT day,
                       SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(reasoning_tokens) AS reasoning_tokens,
                       SUM(cached_tokens) AS cached_tokens,
                       SUM(cache_tokens) AS cache_tokens,
                       SUM(cache_read_tokens) AS cache_read_tokens,
                       SUM(cache_creation_tokens) AS cache_creation_tokens,
                       SUM(cache_tokens_observed) AS cache_tokens_observed_requests,
                       SUM(reasoning_tokens_observed) AS reasoning_tokens_observed_requests,
                       SUM(total_tokens) AS total_tokens,
                       COUNT(*) AS requests,
                       SUM(CASE WHEN known = 0 THEN 1 ELSE 0 END) AS unknown_requests
                FROM usage_events
                {where}
                GROUP BY day
            """, params).fetchall()
            for row in daily_rows:
                if row["day"] in daily:
                    _add(daily[row["day"]], _row_counter(row))

            weekly_rows = conn.execute(f"""
                SELECT week,
                       SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(reasoning_tokens) AS reasoning_tokens,
                       SUM(cached_tokens) AS cached_tokens,
                       SUM(cache_tokens) AS cache_tokens,
                       SUM(cache_read_tokens) AS cache_read_tokens,
                       SUM(cache_creation_tokens) AS cache_creation_tokens,
                       SUM(cache_tokens_observed) AS cache_tokens_observed_requests,
                       SUM(reasoning_tokens_observed) AS reasoning_tokens_observed_requests,
                       SUM(total_tokens) AS total_tokens,
                       COUNT(*) AS requests,
                       SUM(CASE WHEN known = 0 THEN 1 ELSE 0 END) AS unknown_requests
                FROM usage_events
                {where}
                GROUP BY week
            """, params).fetchall()
            for row in weekly_rows:
                if row["week"] in weekly:
                    _add(weekly[row["week"]], _row_counter(row))

            total_row = conn.execute(f"""
                SELECT SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(reasoning_tokens) AS reasoning_tokens,
                       SUM(cached_tokens) AS cached_tokens,
                       SUM(cache_tokens) AS cache_tokens,
                       SUM(cache_read_tokens) AS cache_read_tokens,
                       SUM(cache_creation_tokens) AS cache_creation_tokens,
                       SUM(cache_tokens_observed) AS cache_tokens_observed_requests,
                       SUM(reasoning_tokens_observed) AS reasoning_tokens_observed_requests,
                       SUM(total_tokens) AS total_tokens,
                       COUNT(*) AS requests,
                       SUM(CASE WHEN known = 0 THEN 1 ELSE 0 END) AS unknown_requests,
                       MAX(at) AS last_recorded_at
                FROM usage_events
                {where}
            """, params).fetchone()
            if total_row:
                _add(total, _row_counter(total_row))
                last = total_row["last_recorded_at"]
                last_recorded_at = float(last) if last else None
            conn.commit()
    except sqlite3.Error as e:
        logger.warning("failed to summarize token usage history: %s", e)
    return {
        "daily": [_apply_official_like_total(daily[key]) for key in daily_keys],
        "weekly": [_apply_official_like_total(weekly[key]) for key in weekly_keys],
        "total": _apply_official_like_total(total),
        "last_recorded_at": last_recorded_at,
        "storage": "sqlite",
        "history_available": True,
        "counting_policy": COUNTING_POLICY,
        "counting_policy_detail": COUNTING_POLICY_DETAIL,
    }


def events(
    *,
    limit: int = 50,
    account: str = "",
    model: str = "",
    since: Optional[float] = None,
    until: Optional[float] = None,
) -> dict:
    limit = max(1, min(int(limit or 50), 500))
    try:
        with _connect() as conn:
            where, params = _where_clause(account=account, model=model, since=since, until=until)
            rows = conn.execute(f"""
                SELECT event_hash, request_id, at, day, week, account, path, method, model,
                       status, failed, input_tokens, output_tokens, reasoning_tokens,
                       cached_tokens, cache_tokens, cache_read_tokens, cache_creation_tokens,
                       cache_tokens_observed, reasoning_tokens_observed,
                       total_tokens, known, source, latency_ms, ttft_ms, requested_model,
                       resolved_model, reasoning_effort, service_tier, executor_type
                FROM usage_events
                {where}
                ORDER BY at DESC, id DESC
                LIMIT ?
            """, [*params, limit]).fetchall()
    except sqlite3.Error as e:
        logger.warning("failed to list token usage history: %s", e)
        rows = []
    return {
        "events": [
            {
                "event_hash": row["event_hash"],
                "request_id": row["request_id"] or "",
                "at": row["at"],
                "day": row["day"],
                "week": row["week"],
                "account": row["account"],
                "path": row["path"],
                "method": row["method"] or "",
                "model": row["model"] or "",
                "status": row["status"],
                "failed": bool(row["failed"]),
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "reasoning_tokens": int(row["reasoning_tokens"] or 0),
                "cached_tokens": int(row["cached_tokens"] or 0),
                "cache_tokens": int(row["cache_tokens"] or 0),
                "cache_read_tokens": int(row["cache_read_tokens"] or 0),
                "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
                "cache_tokens_observed": bool(row["cache_tokens_observed"]),
                "reasoning_tokens_observed": bool(row["reasoning_tokens_observed"]),
                "cache_capture_state": _capture_state(
                    bool(row["cache_tokens_observed"]),
                    _cache_value(row),
                ),
                "reasoning_capture_state": _capture_state(
                    bool(row["reasoning_tokens_observed"]),
                    int(row["reasoning_tokens"] or 0),
                ),
                "raw_total_tokens": int(row["total_tokens"] or 0),
                "total_tokens": _official_like_total(row),
                "latency_ms": row["latency_ms"],
                "ttft_ms": row["ttft_ms"],
                "requested_model": row["requested_model"] or "",
                "resolved_model": row["resolved_model"] or "",
                "reasoning_effort": row["reasoning_effort"] or "",
                "service_tier": row["service_tier"] or "",
                "executor_type": row["executor_type"] or "",
                "known": bool(row["known"]),
                "source": row["source"],
            }
            for row in rows
        ],
        "limit": limit,
        "storage": "sqlite",
        "history_available": True,
        "counting_policy": COUNTING_POLICY,
        "counting_policy_detail": COUNTING_POLICY_DETAIL,
    }
