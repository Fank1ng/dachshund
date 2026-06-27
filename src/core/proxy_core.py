"""Core proxy — request forwarding with account pool, failover, and SSE streaming."""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import logging
import random
import time
import uuid
from typing import Optional, Union

import aiohttp
from aiohttp import web

from account_manager import AccountPool
from config import get
from usage_stats import (
    UsageCollector,
    extract_usage_from_bytes,
    extract_usage_from_sse_bytes,
    extract_usage_from_ws_payload,
    record_request_usage,
)

logger = logging.getLogger(__name__)


class _RetryableStreamError(Exception):
    """Raised when a stream fails before anything has been sent downstream."""

    def __init__(self, message: str, *, bytes_read: int = 0, completed: bool = False):
        super().__init__(message)
        self.bytes_read = bytes_read
        self.completed = completed


@dataclass
class _BufferedStreamResult:
    body: bytes
    bytes_read: int
    completed: bool
    stream_mode: str


@dataclass
class _WebSocketConnectResult:
    account: object
    upstream_ws: object
    retry_idx: int
    started: float
    attempts: list[dict]
    affinity_hit: bool = False


@dataclass
class _WebSocketRelayResult:
    origin: str
    messages: int
    bytes_forwarded: int
    completed: bool
    close_code: Optional[int] = None
    error: str = ""
    replay_frames: Optional[list[tuple[str, Union[bytes, str]]]] = None
    usage: Optional[dict] = None


UPSTREAM_MAP = {
    "/v1/": "https://api.openai.com",
    "/backend-api/": "https://chatgpt.com",
    "/wham/": "https://chatgpt.com",
    "/codex/": "https://chatgpt.com",
    "/ps/": "https://chatgpt.com",
    "/connectors/": "https://chatgpt.com",
    "/plugins/": "https://chatgpt.com",
}
V1_RESPONSES_PATH = "/v1/responses"
CODEX_RESPONSES_PATH = "/backend-api/codex/responses"
COMPACT_SUFFIX = "/compact"
CODEX_COMPLETED_MARKER = b"response.completed"
WEBSOCKET_HEARTBEAT_SECONDS = 0
SSE_KEEPALIVE_CHUNK = b": keep-alive\n\n"
JSON_KEEPALIVE_CHUNK = b"\n"
ROUTE_MODEL_POOL = "model_pool"
ROUTE_REMOTE_FIXED = "remote_fixed"
ROUTE_BACKEND_FIXED = "backend_fixed"
REMOTE_BACKEND_PREFIXES = (
    "/backend-api/codex/sessions",
    "/backend-api/codex/remote",
    "/backend-api/codex/presence",
    "/backend-api/codex/devices",
    "/backend-api/codex/relay",
    "/backend-api/remote",
    "/backend-api/presence",
    "/backend-api/devices",
    "/backend-api/relay",
    "/backend-api/connections",
)
BACKEND_ALIAS_PREFIXES = ("/wham/", "/codex/", "/ps/", "/connectors/", "/plugins/")


class _CodexCompletionTracker:
    def __init__(self, marker: bytes = CODEX_COMPLETED_MARKER):
        self.marker = marker
        self.completed = False
        self._tail = b""

    def feed(self, chunk: bytes) -> bool:
        if self.completed:
            return True
        if not chunk:
            return False
        window = self._tail + chunk
        self.completed = self.marker in window
        self._tail = window[-(len(self.marker) - 1):]
        return self.completed

HOP_HEADERS = {
    "host", "transfer-encoding", "content-length", "connection",
    "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "upgrade", "accept-encoding",
}

ACCOUNT_BOUND_HEADERS = {
    "authorization",
    "cookie",
    "openai-organization",
    "openai-project",
    "chatgpt-account-id",
    "openai-account-id",
    "x-openai-account-id",
    "oai-account-id",
    "x-oai-account-id",
}

MODEL_IDS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
)

CHATGPT_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://chatgpt.com",
    "Referer": "https://chatgpt.com/",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def _get_upstream(path: str) -> Optional[str]:
    if _is_v1_codex_responses_path(path):
        return "https://chatgpt.com"
    for prefix, host in UPSTREAM_MAP.items():
        if path.startswith(prefix):
            return host
    return None


def _is_models_path(path: str) -> bool:
    return path == "/v1/models" or path.startswith("/v1/models/")


def _is_openai_inference_path(path: str) -> bool:
    return (
        path == "/v1/chat/completions"
        or path == "/v1/completions"
    )


def _is_v1_codex_responses_path(path: str) -> bool:
    return path == V1_RESPONSES_PATH or path.startswith(f"{V1_RESPONSES_PATH}/")


def _is_codex_responses_path(path: str) -> bool:
    return (
        _is_v1_codex_responses_path(path)
        or path == CODEX_RESPONSES_PATH
        or path.startswith(f"{CODEX_RESPONSES_PATH}/")
    )


def _is_codex_compact_path(path: str) -> bool:
    return path in {
        f"{V1_RESPONSES_PATH}{COMPACT_SUFFIX}",
        f"{CODEX_RESPONSES_PATH}{COMPACT_SUFFIX}",
    }


def _codex_upstream_path(path: str) -> str:
    if path == V1_RESPONSES_PATH:
        return CODEX_RESPONSES_PATH
    if path.startswith(f"{V1_RESPONSES_PATH}/"):
        return f"{CODEX_RESPONSES_PATH}{path[len(V1_RESPONSES_PATH):]}"
    if path.startswith("/backend-api/wham/remote/control/"):
        return path[len("/backend-api"):]
    if path.startswith("/wham/remote/control/"):
        return path
    if path.startswith(BACKEND_ALIAS_PREFIXES):
        return f"/backend-api{path}"
    return path


def _target_url(upstream: str, path: str, query_string: str = "") -> str:
    target = f"{upstream}{_codex_upstream_path(path)}"
    if query_string:
        target += f"?{query_string}"
    return target


def _websocket_target_url(path: str, query_string: str = "") -> str:
    return _target_url("wss://chatgpt.com", path, query_string)


def _uses_chatgpt_backend(path: str) -> bool:
    return path.startswith(("/backend-api/", *BACKEND_ALIAS_PREFIXES)) or _is_v1_codex_responses_path(path)


def _route_class(path: str) -> str:
    if _is_codex_responses_path(path):
        return ROUTE_MODEL_POOL
    if path.startswith(REMOTE_BACKEND_PREFIXES):
        return ROUTE_REMOTE_FIXED
    if path.startswith(("/backend-api/", *BACKEND_ALIAS_PREFIXES)):
        return ROUTE_BACKEND_FIXED
    return ROUTE_MODEL_POOL


def _uses_fixed_backend_account(path: str) -> bool:
    return (
        str(get("remote_proxy_mode") or "fixed_account").lower() == "fixed_account"
        and _route_class(path) in {ROUTE_REMOTE_FIXED, ROUTE_BACKEND_FIXED}
    )


def _is_websocket_request(request: web.Request) -> bool:
    return request.headers.get("Upgrade", "").lower() == "websocket"


def _websocket_protocols(headers: dict) -> list[str]:
    value = headers.get("Sec-WebSocket-Protocol") or headers.get("sec-websocket-protocol") or ""
    return [item.strip() for item in value.split(",") if item.strip()]


def _clean_websocket_headers(headers: dict) -> dict:
    blocked = {
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
    }
    return {k: v for k, v in _clean_headers(headers).items() if k.lower() not in blocked}


def _http_transport_label(stream_mode: str) -> str:
    if not stream_mode:
        return ""
    if stream_mode == "realtime":
        return "http-realtime"
    if stream_mode == "buffered":
        return "http-buffered"
    return "http-hybrid"


def _stream_keepalive_seconds() -> int:
    return int(get("stream_keepalive_seconds") or 0)


def _nonstream_keepalive_interval() -> int:
    return int(get("nonstream_keepalive_interval") or 0)


def _stream_bootstrap_retries() -> int:
    return int(get("stream_bootstrap_retries") or 0)


def _websocket_heartbeat_seconds() -> Optional[int]:
    seconds = int(get("websocket_heartbeat_seconds") or 0)
    return seconds if seconds > 0 else None


def _keepalive_chunk(path: str) -> bytes:
    return JSON_KEEPALIVE_CHUNK if _is_codex_compact_path(path) else SSE_KEEPALIVE_CHUNK


def _extract_session_key(headers: dict, body: bytes) -> str:
    lower_headers = {str(k).lower(): v for k, v in headers.items()}
    for key in ("session_id", "x-session-id", "session-id"):
        value = lower_headers.get(key)
        if value:
            return str(value)
    if not body:
        return ""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    metadata = payload.get("metadata")
    for value in (
        metadata.get("user_id") if isinstance(metadata, dict) else "",
        payload.get("conversation_id"),
        payload.get("previous_response_id"),
    ):
        if value:
            return str(value)
    return ""


def _extract_request_model(body: bytes) -> str:
    if not body:
        return ""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("model", "requested_model", "requestedModel"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _public_session_key(session_key: str) -> str:
    if not session_key:
        return ""
    return hashlib.sha256(session_key.encode("utf-8", "replace")).hexdigest()[:12]


def _public_affinity_hit(session_key: str, affinity_hit: Optional[bool]) -> Optional[bool]:
    return affinity_hit if session_key else None


def _ws_message_bytes(message: aiohttp.WSMessage) -> int:
    if message.type == aiohttp.WSMsgType.TEXT:
        return len(message.data.encode("utf-8"))
    if message.type == aiohttp.WSMsgType.BINARY:
        return len(message.data)
    return 0


def _feed_ws_completion(tracker: _CodexCompletionTracker, message: aiohttp.WSMessage) -> None:
    if message.type == aiohttp.WSMsgType.TEXT:
        tracker.feed(message.data.encode("utf-8"))
    elif message.type == aiohttp.WSMsgType.BINARY:
        tracker.feed(message.data)



def _models_response(request_id: str, path: str) -> web.Response:
    if path.startswith("/v1/models/"):
        model_id = path.rsplit("/", 1)[-1]
        if model_id not in MODEL_IDS:
            return web.json_response(
                {
                    "error": {
                        "message": f"model '{model_id}' not found",
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
                status=404,
                headers={"x-request-id": request_id},
            )
        return web.json_response(
            {"id": model_id, "object": "model", "created": 0, "owned_by": "openai"},
            headers={"x-request-id": request_id},
        )
    return web.json_response(
        {
            "object": "list",
            "data": [
                {"id": model_id, "object": "model", "created": 0, "owned_by": "openai"}
                for model_id in MODEL_IDS
            ],
        },
        headers={"x-request-id": request_id},
    )


def _clean_headers(headers: dict) -> dict:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in HOP_HEADERS
        and k.lower() not in ACCOUNT_BOUND_HEADERS
        and not k.lower().startswith("x-forwarded")
        and k.lower() != "via"
    }


def _account_headers(base_headers: dict, account, path: str) -> dict:
    headers = dict(base_headers)
    if _uses_chatgpt_backend(path):
        headers.update(CHATGPT_WEB_HEADERS)
    headers["Authorization"] = f"Bearer {account.access_token}"
    if _uses_chatgpt_backend(path) and account.account_id:
        headers["chatgpt-account-id"] = account.account_id
    return headers


def _retry_after_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        seconds = int(float(value.strip()))
    except ValueError:
        return None
    return max(1, min(seconds, 3600))


def _upstream_timeout() -> aiohttp.ClientTimeout:
    """Use a short connect timeout while allowing long Codex streams to run."""
    return aiohttp.ClientTimeout(
        total=None,
        sock_connect=int(get("upstream_connect_timeout_sec") or 10),
        sock_read=None,
    )


def _transient_backoff_seconds(attempt: int) -> float:
    backoff_ms = int(get("upstream_transient_backoff_ms") or 0)
    if backoff_ms <= 0:
        return 0
    return (backoff_ms / 1000) * (2 ** attempt) + random.uniform(0, 0.1)


def _codex_stream_mode() -> str:
    mode = str(get("codex_stream_mode") or "realtime").lower()
    if mode not in {"realtime", "buffered", "hybrid"}:
        return "realtime"
    return mode


def _codex_stream_retry_cooldown() -> int:
    configured = int(get("codex_stream_retry_cooldown") or 0)
    return configured if configured > 0 else int(get("rate_limit_cooldown") or 60)


def _is_streaming_response(upstream_resp: aiohttp.ClientResponse) -> bool:
    content_type = upstream_resp.headers.get("Content-Type", "").lower()
    return "text/event-stream" in content_type


def _should_stream_response(path: str, upstream_resp: aiohttp.ClientResponse) -> bool:
    if _is_codex_responses_path(path) and 200 <= upstream_resp.status < 300:
        return True
    return _is_streaming_response(upstream_resp)


def _record_token_usage(
    path: str,
    request_id: str,
    account,
    usage: Optional[dict],
    *,
    method: str = "",
    model: str = "",
    status: Optional[int] = None,
    failed: bool = False,
    latency_ms: Optional[float] = None,
    ttft_ms: Optional[float] = None,
) -> None:
    if not _is_codex_responses_path(path):
        return
    record_request_usage(
        request_id=request_id,
        account=getattr(account, "name", ""),
        path=path,
        usage=usage,
        method=method,
        model=model,
        status=status,
        failed=failed,
        latency_ms=latency_ms,
        ttft_ms=ttft_ms,
        requested_model=model,
    )


def _response_headers(upstream_resp: aiohttp.ClientResponse, request_id: str) -> dict:
    headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in HOP_HEADERS
    }
    headers["x-request-id"] = request_id
    return headers


def _record_attempt(attempts: list[dict], account, reason: str, **details) -> None:
    item = {
        "account": account.name,
        "reason": reason,
    }
    item.update({k: v for k, v in details.items() if v is not None})
    attempts.append(item)


def _last_attempt_error(attempts: list[dict]) -> str:
    if not attempts:
        return ""
    last = attempts[-1]
    if last.get("error"):
        return str(last["error"])
    if last.get("status"):
        return f"{last.get('reason', 'upstream_status')}:{last['status']}"
    return str(last.get("reason", ""))


def _upstream_failure_response(
    request_id: str,
    path: str,
    attempts: list[dict],
    message: str = "all eligible accounts failed for this request",
) -> web.Response:
    return web.json_response(
        {
            "error": message,
            "request_id": request_id,
            "path": path,
            "attempted_accounts": attempts,
            "last_error": _last_attempt_error(attempts),
        },
        status=502,
        headers={"x-request-id": request_id},
    )


def _fixed_account_unavailable_response(request_id: str, path: str, pool: AccountPool) -> web.Response:
    report = pool.fixed_account_report()
    return web.json_response(
        {
            "error": "remote fixed account unavailable",
            "request_id": request_id,
            "path": path,
            "remote_account": report,
        },
        status=503,
        headers={"x-request-id": request_id},
    )


def _stream_error_detail(
    reason: str,
    error: str,
    bytes_forwarded: int,
    completed: bool,
) -> str:
    return (
        f"{reason}: {error}; bytes_forwarded={bytes_forwarded}; "
        f"response_completed={completed}"
    )


def _buffered_stream_error_detail(
    reason: str,
    error: str,
    bytes_read: int,
    completed: bool,
    stream_mode: str,
) -> str:
    return (
        f"{reason}: {error}; bytes_read={bytes_read}; "
        f"response_completed={completed}; stream_mode={stream_mode}"
    )


def _websocket_error_detail(
    reason: str,
    error: str,
    messages: int,
    bytes_forwarded: int,
    completed: bool,
    close_code: Optional[int],
) -> str:
    return (
        f"{reason}: {error}; messages={messages}; bytes_forwarded={bytes_forwarded}; "
        f"response_completed={completed}; close_code={close_code}"
    )


def _websocket_close_message(message: str) -> bytes:
    encoded = message.encode("utf-8", "replace")
    if len(encoded) <= 120:
        return encoded
    return encoded[:117] + b"..."


async def _close_websocket_safely(client_ws, *, code: int, message: str = "") -> None:
    try:
        await client_ws.close(code=code, message=_websocket_close_message(message))
    except (ConnectionResetError, RuntimeError, AssertionError):
        pass


def _record_ws_stream_interrupted(
    pool: AccountPool,
    account,
    path: str,
    request_id: str,
    retry_idx: int,
    result: _WebSocketRelayResult,
    cooldown: int,
) -> None:
    detail = _websocket_error_detail(
        "ws_stream_interrupted",
        result.error or "websocket closed before response.completed",
        result.messages,
        result.bytes_forwarded,
        result.completed,
        result.close_code,
    )
    logger.warning(
        "websocket stream interrupted request_id=%s account=%s path=%s messages=%s "
        "bytes_forwarded=%s response_completed=%s close_code=%s error=%s",
        request_id,
        account.name,
        path,
        result.messages,
        result.bytes_forwarded,
        result.completed,
        result.close_code,
        result.error,
    )
    pool.record_error(path, detail, account, request_id, retry_idx)
    pool.mark_rate_limited(account, cooldown, "ws_stream_interrupted")


def _clear_ws_stream_interruption_cooldown(pool: AccountPool, account) -> None:
    if getattr(account, "cooldown_reason", "") == "ws_stream_interrupted":
        pool.clear_cooldown(account)


def _can_retry_websocket_without_forwarding(result: _WebSocketRelayResult) -> bool:
    return (
        result.origin == "upstream"
        and not result.completed
        and result.messages == 0
        and result.bytes_forwarded == 0
    )


def _record_stream_interrupted(
    pool: AccountPool,
    account,
    path: str,
    request_id: str,
    retry_idx: int,
    error: str,
    bytes_forwarded: int,
    completed: bool,
    cooldown: int,
) -> None:
    detail = _stream_error_detail("stream_interrupted", error, bytes_forwarded, completed)
    logger.warning(
        "stream interrupted request_id=%s account=%s path=%s bytes_forwarded=%s "
        "response_completed=%s error=%s",
        request_id,
        account.name,
        path,
        bytes_forwarded,
        completed,
        error,
    )
    pool.record_error(path, detail, account, request_id, retry_idx)
    pool.mark_rate_limited(account, cooldown, "stream_interrupted")


def _record_buffered_stream_interrupted(
    pool: AccountPool,
    account,
    path: str,
    request_id: str,
    retry_idx: int,
    error: _RetryableStreamError,
    stream_mode: str,
    cooldown: int,
) -> None:
    detail = _buffered_stream_error_detail(
        "stream_interrupted",
        str(error),
        error.bytes_read,
        error.completed,
        stream_mode,
    )
    logger.warning(
        "buffered stream interrupted request_id=%s account=%s path=%s bytes_read=%s "
        "response_completed=%s stream_mode=%s error=%s",
        request_id,
        account.name,
        path,
        error.bytes_read,
        error.completed,
        stream_mode,
        error,
    )
    pool.record_error(path, detail, account, request_id, retry_idx)
    pool.mark_rate_limited(account, cooldown, "stream_interrupted")


def _record_client_disconnect(
    pool: AccountPool,
    account,
    path: str,
    request_id: str,
    retry_idx: int,
    error: str,
    bytes_forwarded: int,
    completed: bool,
) -> None:
    detail = _stream_error_detail("client_disconnected", error, bytes_forwarded, completed)
    logger.info(
        "client disconnected request_id=%s account=%s path=%s bytes_forwarded=%s "
        "response_completed=%s error=%s",
        request_id,
        account.name,
        path,
        bytes_forwarded,
        completed,
        error,
    )
    pool.record_error(path, detail, account, request_id, retry_idx)


async def _write_stream_chunk(resp: web.StreamResponse, chunk: bytes) -> None:
    await resp.write(chunk)
    drain = getattr(resp, "drain", None)
    if callable(drain):
        await drain()


async def _relay_realtime_stream(
    request: web.Request,
    pool: AccountPool,
    account,
    path: str,
    request_id: str,
    retry_idx: int,
    upstream_resp: aiohttp.ClientResponse,
    started: float,
    stream_mode: str,
    transport: str,
    requires_completion: bool,
    cooldown: int,
    session_key: str = "",
    affinity_hit: Optional[bool] = None,
    request_model: str = "",
    route_class: str = "",
    fixed_account: str = "",
    upstream_path: str = "",
) -> web.StreamResponse:
    resp = web.StreamResponse(
        status=upstream_resp.status,
        headers=_response_headers(upstream_resp, request_id),
    )
    tracker = _CodexCompletionTracker() if requires_completion else None
    chunks = upstream_resp.content.iter_chunks().__aiter__()
    keepalive_interval = (
        _nonstream_keepalive_interval()
        if _is_codex_compact_path(path)
        else _stream_keepalive_seconds()
    )
    keepalive_count = 0
    bytes_forwarded = 0
    first_byte_ms = None
    response_prepared = False
    usage_collector = UsageCollector() if _is_codex_responses_path(path) else None

    async def prepare_response() -> None:
        nonlocal response_prepared
        if not response_prepared:
            await resp.prepare(request)
            response_prepared = True

    async def read_next_chunk():
        nonlocal keepalive_count
        pending_read = asyncio.create_task(chunks.__anext__())
        while True:
            if keepalive_interval <= 0:
                return await pending_read
            done, _ = await asyncio.wait({pending_read}, timeout=keepalive_interval)
            if pending_read in done:
                return pending_read.result()
            try:
                await prepare_response()
                await _write_stream_chunk(resp, _keepalive_chunk(path))
                keepalive_count += 1
            except Exception:
                pending_read.cancel()
                raise

    def record(completed: bool = False) -> None:
        duration_ms = (time.monotonic() - started) * 1000
        pool.record_request(
            account,
            path,
            upstream_resp.status,
            duration_ms,
            retry_idx,
            request_id,
            stream_mode,
            transport,
            session_key=_public_session_key(session_key),
            affinity_hit=_public_affinity_hit(session_key, affinity_hit),
            first_byte_ms=first_byte_ms,
            stream_keepalive_count=keepalive_count,
            route_class=route_class,
            selected_account=account.name if route_class else "",
            fixed_account=fixed_account,
            upstream_path=upstream_path,
        )
        if usage_collector:
            _record_token_usage(
                path,
                request_id,
                account,
                usage_collector.finish(),
                method=request.method,
                model=request_model,
                status=upstream_resp.status,
                failed=not (200 <= upstream_resp.status < 400),
                latency_ms=duration_ms,
                ttft_ms=first_byte_ms,
            )
        if completed:
            pool.bind_session(session_key, account)

    try:
        try:
            first_chunk, _ = await read_next_chunk()
        except StopAsyncIteration:
            first_chunk = b""
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            raise _RetryableStreamError(str(e)) from e

        if tracker:
            tracker.feed(first_chunk)
        if usage_collector:
            usage_collector.feed_bytes(first_chunk)
        if tracker and not first_chunk and not tracker.completed:
            raise _RetryableStreamError("stream closed before response.completed")

        await prepare_response()
        if first_chunk:
            try:
                await _write_stream_chunk(resp, first_chunk)
            except ConnectionResetError as e:
                completed = bool(tracker and tracker.completed)
                _record_client_disconnect(
                    pool,
                    account,
                    path,
                    request_id,
                    retry_idx,
                    str(e),
                    bytes_forwarded,
                    completed,
                )
                record(completed=completed)
                return resp
            bytes_forwarded += len(first_chunk)
            first_byte_ms = (time.monotonic() - started) * 1000

        while True:
            try:
                chunk, _ = await read_next_chunk()
            except StopAsyncIteration:
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                completed = bool(tracker and tracker.completed)
                _record_stream_interrupted(
                    pool,
                    account,
                    path,
                    request_id,
                    retry_idx,
                    str(e),
                    bytes_forwarded,
                    completed,
                    cooldown,
                )
                record(completed=completed)
                return resp

            if tracker:
                tracker.feed(chunk)
            if usage_collector:
                usage_collector.feed_bytes(chunk)
            if not chunk:
                continue
            try:
                await _write_stream_chunk(resp, chunk)
            except ConnectionResetError as e:
                completed = bool(tracker and tracker.completed)
                _record_client_disconnect(
                    pool,
                    account,
                    path,
                    request_id,
                    retry_idx,
                    str(e),
                    bytes_forwarded,
                    completed,
                )
                record(completed=completed)
                return resp
            bytes_forwarded += len(chunk)
            if first_byte_ms is None:
                first_byte_ms = (time.monotonic() - started) * 1000

        if tracker and not tracker.completed:
            error = "stream closed before response.completed"
            if bytes_forwarded == 0 and keepalive_count == 0:
                raise _RetryableStreamError(error)
            _record_stream_interrupted(
                pool,
                account,
                path,
                request_id,
                retry_idx,
                error,
                bytes_forwarded,
                False,
                cooldown,
            )
            record(completed=False)
            try:
                await resp.write_eof()
            except ConnectionResetError:
                pass
            return resp

        try:
            await resp.write_eof()
        except ConnectionResetError as e:
            completed = bool(tracker and tracker.completed)
            _record_client_disconnect(
                pool,
                account,
                path,
                request_id,
                retry_idx,
                str(e),
                bytes_forwarded,
                completed,
            )
            record(completed=completed)
            return resp
    except _RetryableStreamError as e:
        if response_prepared:
            completed = bool(tracker and tracker.completed)
            _record_stream_interrupted(
                pool,
                account,
                path,
                request_id,
                retry_idx,
                str(e),
                bytes_forwarded,
                completed,
                cooldown,
            )
            record(completed=completed)
            return resp
        raise
    except ConnectionResetError as e:
        completed = bool(tracker and tracker.completed)
        _record_client_disconnect(
            pool,
            account,
            path,
            request_id,
            retry_idx,
            str(e),
            bytes_forwarded,
            completed,
        )
        record(completed=completed)
        return resp

    record(completed=bool(tracker and tracker.completed))
    return resp


async def _fetch_complete_codex_stream(
    upstream_resp: aiohttp.ClientResponse,
    mode: str,
    *,
    require_completion: bool = True,
) -> _BufferedStreamResult:
    tracker = _CodexCompletionTracker()
    chunks: list[bytes] = []
    bytes_read = 0
    started = time.monotonic()
    exceeded_probe = mode == "buffered"
    probe_seconds = int(get("codex_hybrid_probe_seconds") or 0)
    probe_bytes = int(get("codex_hybrid_probe_bytes") or 262144)

    try:
        async for chunk, _ in upstream_resp.content.iter_chunks():
            if not chunk:
                continue
            chunks.append(chunk)
            bytes_read += len(chunk)
            tracker.feed(chunk)
            if mode == "hybrid" and not exceeded_probe:
                elapsed = time.monotonic() - started
                exceeded_probe = bytes_read >= probe_bytes or elapsed >= probe_seconds
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise _RetryableStreamError(str(e), bytes_read=bytes_read, completed=tracker.completed) from e

    if not bytes_read:
        raise _RetryableStreamError("empty codex response stream", bytes_read=0, completed=False)
    if require_completion and not tracker.completed:
        raise _RetryableStreamError(
            "stream closed before response.completed",
            bytes_read=bytes_read,
            completed=False,
        )

    if not require_completion:
        stream_mode = f"{mode}-compact"
    elif mode == "buffered":
        stream_mode = "buffered"
    elif exceeded_probe:
        stream_mode = "hybrid-buffered"
    else:
        stream_mode = "hybrid-probe-complete"
    return _BufferedStreamResult(
        body=b"".join(chunks),
        bytes_read=bytes_read,
        completed=tracker.completed,
        stream_mode=stream_mode,
    )


async def _connect_codex_upstream_websocket(
    request: web.Request,
    pool: AccountPool,
    upstream_session: aiohttp.ClientSession,
    request_id: str,
    path: str,
    session_key: str = "",
    tried_accounts: Optional[set[str]] = None,
    attempts: Optional[list[dict]] = None,
) -> tuple[Optional[_WebSocketConnectResult], list[dict], Optional[web.Response]]:
    base_headers = _clean_websocket_headers(dict(request.headers))
    protocols = _websocket_protocols(dict(request.headers))
    target_url = _websocket_target_url(path, request.query_string)
    cooldown = get("rate_limit_cooldown")
    max_retries = get("max_retries")
    tried_accounts = tried_accounts if tried_accounts is not None else set()
    attempts = attempts if attempts is not None else []

    for _ in range(max_retries):
        retry_idx = len(tried_accounts)
        account, affinity_hit = pool.pick_for_session(session_key, exclude=tried_accounts)
        if account is None:
            if tried_accounts:
                return None, attempts, _upstream_failure_response(request_id, path, attempts)
            return None, attempts, web.Response(
                status=429,
                text='{"error": "all accounts rate-limited"}',
                content_type="application/json",
                headers={"x-request-id": request_id},
            )

        tried_accounts.add(account.name)
        pool.bind_session(session_key, account)
        headers = _account_headers(base_headers, account, _codex_upstream_path(path))
        for auth_attempt in range(2):
            started = time.monotonic()
            try:
                upstream_ws = await upstream_session.ws_connect(
                    target_url,
                    headers=headers,
                    protocols=protocols,
                    timeout=aiohttp.ClientWSTimeout(
                        ws_receive=None,
                        ws_close=int(get("upstream_connect_timeout_sec") or 10),
                    ),
                    receive_timeout=None,
                    autoclose=True,
                    autoping=True,
                    heartbeat=_websocket_heartbeat_seconds(),
                )
                return _WebSocketConnectResult(
                    account=account,
                    upstream_ws=upstream_ws,
                    retry_idx=retry_idx,
                    started=started,
                    attempts=attempts,
                    affinity_hit=affinity_hit,
                ), attempts, None
            except aiohttp.WSServerHandshakeError as e:
                duration_ms = (time.monotonic() - started) * 1000
                pool.record_request(
                    account,
                    path,
                    e.status,
                    duration_ms,
                    retry_idx,
                    request_id,
                    transport="websocket",
                    session_key=_public_session_key(session_key),
                    affinity_hit=_public_affinity_hit(session_key, affinity_hit),
                    route_class=ROUTE_MODEL_POOL,
                    selected_account=account.name,
                    upstream_path=_codex_upstream_path(path),
                )
                if e.status == 401:
                    logger.info("Account %s: websocket got 401, refreshing", account.name)
                    pool.stats["auth_refreshes"] += 1
                    if auth_attempt > 0:
                        _record_attempt(
                            attempts,
                            account,
                            "auth_failed",
                            status=e.status,
                            retry_index=retry_idx,
                            transport="websocket",
                        )
                        pool.mark_rate_limited(account, 300, "auth_failed")
                        pool.clear_session_binding(session_key, account)
                        break
                    ok = await account.refresh()
                    if not ok:
                        _record_attempt(
                            attempts,
                            account,
                            "auth_failed",
                            status=e.status,
                            retry_index=retry_idx,
                            transport="websocket",
                        )
                        pool.mark_rate_limited(account, 300, "auth_failed")
                        pool.clear_session_binding(session_key, account)
                        break
                    headers["Authorization"] = f"Bearer {account.access_token}"
                    continue

                if e.status == 429:
                    retry_after = _retry_after_seconds(e.headers.get("Retry-After") if e.headers else None)
                    _record_attempt(
                        attempts,
                        account,
                        "rate_limit_429",
                        status=e.status,
                        retry_after=retry_after,
                        retry_index=retry_idx,
                        transport="websocket",
                    )
                    pool.mark_rate_limited(account, retry_after or cooldown, "rate_limit_429")
                    pool.clear_session_binding(session_key, account)
                    break

                detail = f"ws_handshake_failed: status={e.status}; message={e.message}"
                _record_attempt(
                    attempts,
                    account,
                    "ws_handshake_failed",
                    status=e.status,
                    error=e.message,
                    retry_index=retry_idx,
                    transport="websocket",
                )
                pool.record_error(path, detail, account, request_id, retry_idx)
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                detail = f"ws_handshake_failed: {e}"
                _record_attempt(
                    attempts,
                    account,
                    "ws_handshake_failed",
                    error=str(e),
                    retry_index=retry_idx,
                    transport="websocket",
                )
                pool.record_error(path, detail, account, request_id, retry_idx)
                break

    return None, attempts, _upstream_failure_response(request_id, path, attempts, "websocket upstream unavailable")


async def _send_ws_frame(upstream_ws, frame: tuple[str, Union[bytes, str]]) -> None:
    kind, data = frame
    if kind == "text":
        await upstream_ws.send_str(str(data))
    else:
        await upstream_ws.send_bytes(bytes(data))


async def _relay_websocket_pair(
    client_ws,
    upstream_ws,
    replay_frames: Optional[list[tuple[str, Union[bytes, str]]]] = None,
) -> _WebSocketRelayResult:
    tracker = _CodexCompletionTracker()
    sent_to_upstream = list(replay_frames or [])
    metrics = {
        "messages": 0,
        "bytes_forwarded": 0,
        "completed": False,
        "close_code": None,
        "error": "",
    }

    try:
        for frame in replay_frames or []:
            await _send_ws_frame(upstream_ws, frame)
    except Exception as e:
        metrics["error"] = str(e)
        metrics["close_code"] = getattr(upstream_ws, "close_code", None)
        return _WebSocketRelayResult(
            origin="upstream",
            messages=0,
            bytes_forwarded=0,
            completed=False,
            close_code=metrics["close_code"],
            error=str(metrics["error"]),
            replay_frames=sent_to_upstream,
            usage=None,
        )

    async def upstream_to_client() -> None:
        async for msg in upstream_ws:
            if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                metrics["messages"] += 1
                metrics["bytes_forwarded"] += _ws_message_bytes(msg)
                _feed_ws_completion(tracker, msg)
                usage = extract_usage_from_ws_payload(msg.data)
                if usage and (
                    not metrics.get("usage")
                    or usage["total_tokens"] >= metrics["usage"]["total_tokens"]
                ):
                    metrics["usage"] = usage
                metrics["completed"] = tracker.completed
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await client_ws.send_str(msg.data)
                else:
                    await client_ws.send_bytes(msg.data)
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                metrics["error"] = str(upstream_ws.exception() or "upstream websocket error")
                break
        metrics["close_code"] = getattr(upstream_ws, "close_code", None)

    async def client_to_upstream() -> None:
        async for msg in client_ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                sent_to_upstream.append(("text", msg.data))
                await upstream_ws.send_str(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                sent_to_upstream.append(("binary", msg.data))
                await upstream_ws.send_bytes(msg.data)
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                break
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break

    upstream_task = asyncio.create_task(upstream_to_client())
    client_task = asyncio.create_task(client_to_upstream())
    done, pending = await asyncio.wait(
        {upstream_task, client_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    origin = "upstream" if upstream_task in done else "client"
    for task in pending:
        task.cancel()
    for task in pending:
        try:
            await task
        except asyncio.CancelledError:
            pass
    for task in done:
        try:
            await task
        except Exception as e:
            metrics["error"] = str(e)
    return _WebSocketRelayResult(
        origin=origin,
        messages=int(metrics["messages"]),
        bytes_forwarded=int(metrics["bytes_forwarded"]),
        completed=bool(metrics["completed"]),
        close_code=metrics["close_code"],
        error=str(metrics["error"]),
        replay_frames=sent_to_upstream,
        usage=metrics.get("usage"),
    )


async def _handle_codex_websocket(
    request: web.Request,
    pool: AccountPool,
    upstream_session: aiohttp.ClientSession,
    request_id: str,
    path: str,
    session_key: str = "",
) -> web.StreamResponse:
    client_ws = web.WebSocketResponse(
        protocols=_websocket_protocols(dict(request.headers)),
        heartbeat=_websocket_heartbeat_seconds(),
    )
    client_ws.headers["x-request-id"] = request_id
    try:
        await client_ws.prepare(request)
    except (AssertionError, ConnectionResetError, RuntimeError) as e:
        detail = f"ws_client_disconnected_before_prepare: {e}"
        pool.record_error(path, detail, None, request_id, 0)
        return web.Response(status=499, headers={"x-request-id": request_id})

    tried_accounts: set[str] = set()
    attempts: list[dict] = []
    replay_frames: list[tuple[str, Union[bytes, str]]] = []
    while True:
        connected, attempts, failure = await _connect_codex_upstream_websocket(
            request,
            pool,
            upstream_session,
            request_id,
            path,
            session_key,
            tried_accounts=tried_accounts,
            attempts=attempts,
        )
        if failure is not None:
            detail = (
                "ws_handshake_failed: websocket upstream unavailable; "
                f"attempts={len(attempts)}"
            )
            pool.record_error(path, detail, None, request_id, len(attempts))
            await _close_websocket_safely(
                client_ws,
                code=aiohttp.WSCloseCode.TRY_AGAIN_LATER,
                message=detail,
            )
            return client_ws

        account = connected.account
        upstream_ws = connected.upstream_ws
        if getattr(client_ws, "closed", False):
            await upstream_ws.close()
            detail = "ws_client_disconnected: client websocket closed before upstream relay"
            pool.record_error(path, detail, account, request_id, connected.retry_idx)
            return client_ws

        try:
            result = await _relay_websocket_pair(client_ws, upstream_ws, replay_frames)
        finally:
            await upstream_ws.close()

        duration_ms = (time.monotonic() - connected.started) * 1000
        pool.record_request(
            account,
            path,
            101,
            duration_ms,
            connected.retry_idx,
            request_id,
            transport="websocket",
            session_key=_public_session_key(session_key),
            affinity_hit=_public_affinity_hit(session_key, connected.affinity_hit),
            route_class=ROUTE_MODEL_POOL,
            selected_account=account.name,
            upstream_path=_codex_upstream_path(path),
            ws_close_code=result.close_code,
        )
        _record_token_usage(
            path,
            request_id,
            account,
            result.usage,
            method=request.method,
            status=101,
            latency_ms=duration_ms,
        )
        if result.completed:
            _clear_ws_stream_interruption_cooldown(pool, account)
            await _close_websocket_safely(client_ws, code=aiohttp.WSCloseCode.OK)
            return client_ws
        if result.origin == "upstream":
            _record_attempt(
                attempts,
                account,
                "ws_stream_interrupted",
                messages=result.messages,
                bytes_forwarded=result.bytes_forwarded,
                response_completed=result.completed,
                close_code=result.close_code,
                error=result.error or "websocket closed before response.completed",
                retry_index=connected.retry_idx,
                transport="websocket",
            )
            _record_ws_stream_interrupted(
                pool,
                account,
                path,
                request_id,
                connected.retry_idx,
                result,
                _codex_stream_retry_cooldown(),
            )
            if _can_retry_websocket_without_forwarding(result) and not getattr(client_ws, "closed", False):
                replay_frames = list(result.replay_frames or replay_frames)
                logger.info(
                    "retrying websocket without closing client request_id=%s account=%s "
                    "path=%s replay_frames=%s",
                    request_id,
                    account.name,
                    path,
                    len(replay_frames),
                )
                continue
            await _close_websocket_safely(client_ws, code=aiohttp.WSCloseCode.OK)
            return client_ws
        if result.origin == "client":
            detail = _websocket_error_detail(
                "ws_client_disconnected",
                result.error or "client websocket closed",
                result.messages,
                result.bytes_forwarded,
                result.completed,
                result.close_code,
            )
            pool.record_error(path, detail, account, request_id, connected.retry_idx)
            await _close_websocket_safely(client_ws, code=aiohttp.WSCloseCode.OK)
            return client_ws
    return client_ws


async def _handle_fixed_backend_websocket(
    request: web.Request,
    pool: AccountPool,
    upstream_session: aiohttp.ClientSession,
    request_id: str,
    path: str,
) -> web.StreamResponse:
    route_class = _route_class(path)
    account = pool.pick_fixed_account()
    if account is None:
        return _fixed_account_unavailable_response(request_id, path, pool)

    base_headers = _clean_websocket_headers(dict(request.headers))
    protocols = _websocket_protocols(dict(request.headers))
    target_url = _websocket_target_url(path, request.query_string)
    upstream_path = _codex_upstream_path(path)
    headers = _account_headers(base_headers, account, upstream_path)
    auth_refresh_result = ""
    upstream_ws = None
    started = time.monotonic()

    for auth_attempt in range(2):
        try:
            upstream_ws = await upstream_session.ws_connect(
                target_url,
                headers=headers,
                protocols=protocols,
                timeout=aiohttp.ClientWSTimeout(
                    ws_receive=None,
                    ws_close=int(get("upstream_connect_timeout_sec") or 10),
                ),
                receive_timeout=None,
                autoclose=True,
                autoping=True,
                heartbeat=_websocket_heartbeat_seconds(),
            )
            break
        except aiohttp.WSServerHandshakeError as e:
            if e.status == 401 and auth_attempt == 0:
                pool.stats["auth_refreshes"] += 1
                ok = await account.refresh()
                auth_refresh_result = "success" if ok else "failed"
                if ok:
                    headers["Authorization"] = f"Bearer {account.access_token}"
                    continue
            duration_ms = (time.monotonic() - started) * 1000
            pool.record_request(
                account,
                path,
                e.status,
                duration_ms,
                0,
                request_id,
                transport="websocket",
                route_class=route_class,
                selected_account=account.name,
                fixed_account=account.name,
                upstream_path=upstream_path,
                auth_refresh_result=auth_refresh_result,
            )
            pool.record_error(
                path,
                f"fixed_ws_handshake_failed: status={e.status}; message={e.message}",
                account,
                request_id,
                0,
            )
            return web.Response(
                status=e.status,
                text=json.dumps({"error": "fixed websocket upstream handshake failed", "status": e.status}),
                content_type="application/json",
                headers={"x-request-id": request_id},
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            duration_ms = (time.monotonic() - started) * 1000
            pool.record_error(path, f"fixed_ws_handshake_failed: {e}", account, request_id, 0)
            pool.record_request(
                account,
                path,
                502,
                duration_ms,
                0,
                request_id,
                transport="websocket",
                route_class=route_class,
                selected_account=account.name,
                fixed_account=account.name,
                upstream_path=upstream_path,
                auth_refresh_result=auth_refresh_result,
            )
            return web.json_response(
                {"error": "fixed websocket upstream unavailable", "detail": str(e)},
                status=502,
                headers={"x-request-id": request_id},
            )

    client_ws = web.WebSocketResponse(
        protocols=protocols,
        heartbeat=_websocket_heartbeat_seconds(),
    )
    client_ws.headers["x-request-id"] = request_id
    try:
        await client_ws.prepare(request)
    except (AssertionError, ConnectionResetError, RuntimeError) as e:
        if upstream_ws is not None:
            await upstream_ws.close()
        detail = f"fixed_ws_client_disconnected_before_prepare: {e}"
        pool.record_error(path, detail, account, request_id, 0)
        return web.Response(status=499, headers={"x-request-id": request_id})

    try:
        result = await _relay_websocket_pair(client_ws, upstream_ws)
    finally:
        await upstream_ws.close()

    duration_ms = (time.monotonic() - started) * 1000
    pool.record_request(
        account,
        path,
        101,
        duration_ms,
        0,
        request_id,
        transport="websocket",
        route_class=route_class,
        selected_account=account.name,
        fixed_account=account.name,
        upstream_path=upstream_path,
        ws_close_code=result.close_code,
        auth_refresh_result=auth_refresh_result,
    )
    if result.error:
        pool.record_error(
            path,
            _websocket_error_detail(
                "fixed_ws_relay_error",
                result.error,
                result.messages,
                result.bytes_forwarded,
                result.completed,
                result.close_code,
            ),
            account,
            request_id,
            0,
        )
    await _close_websocket_safely(client_ws, code=aiohttp.WSCloseCode.OK)
    return client_ws


async def _handle_fixed_backend_request(
    request: web.Request,
    pool: AccountPool,
    upstream_session: aiohttp.ClientSession,
    request_id: str,
    path: str,
    target_url: str,
    body: bytes,
    base_headers: dict,
) -> web.Response:
    route_class = _route_class(path)
    account = pool.pick_fixed_account()
    if account is None:
        return _fixed_account_unavailable_response(request_id, path, pool)

    upstream_path = _codex_upstream_path(path)
    headers = _account_headers(base_headers, account, upstream_path)
    transient_retries = int(get("upstream_transient_retries") or 0)
    auth_refresh_result = ""

    for auth_attempt in range(2):
        for transient_attempt in range(transient_retries + 1):
            started = time.monotonic()
            try:
                upstream_resp_ctx = upstream_session.request(
                    request.method,
                    target_url,
                    headers=headers,
                    data=body,
                    timeout=_upstream_timeout(),
                )
                async with upstream_resp_ctx as upstream_resp:
                    if upstream_resp.status == 401 and auth_attempt == 0:
                        await upstream_resp.read()
                        pool.stats["auth_refreshes"] += 1
                        ok = await account.refresh()
                        auth_refresh_result = "success" if ok else "failed"
                        if ok:
                            headers["Authorization"] = f"Bearer {account.access_token}"
                            break

                    if not _should_stream_response(path, upstream_resp):
                        payload = await upstream_resp.read()
                        duration_ms = (time.monotonic() - started) * 1000
                        pool.record_request(
                            account,
                            path,
                            upstream_resp.status,
                            duration_ms,
                            0,
                            request_id,
                            route_class=route_class,
                            selected_account=account.name,
                            fixed_account=account.name,
                            upstream_path=upstream_path,
                            auth_refresh_result=auth_refresh_result,
                        )
                        return web.Response(
                            status=upstream_resp.status,
                            body=payload,
                            headers=_response_headers(upstream_resp, request_id),
                        )

                    return await _relay_realtime_stream(
                        request,
                        pool,
                        account,
                        path,
                        request_id,
                        0,
                        upstream_resp,
                        started,
                        "",
                        "http-stream",
                        False,
                        int(get("rate_limit_cooldown") or 60),
                        route_class=route_class,
                        fixed_account=account.name,
                        upstream_path=upstream_path,
                    )
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if transient_attempt < transient_retries:
                    delay = _transient_backoff_seconds(transient_attempt)
                    if delay:
                        await asyncio.sleep(delay)
                    continue
                duration_ms = (time.monotonic() - started) * 1000
                pool.record_error(path, f"fixed_backend_error: {e}", account, request_id, 0)
                pool.record_request(
                    account,
                    path,
                    502,
                    duration_ms,
                    0,
                    request_id,
                    route_class=route_class,
                    selected_account=account.name,
                    fixed_account=account.name,
                    upstream_path=upstream_path,
                    auth_refresh_result=auth_refresh_result,
                )
                return web.json_response(
                    {"error": "fixed backend upstream unavailable", "detail": str(e)},
                    status=502,
                    headers={"x-request-id": request_id},
                )
        else:
            continue
        if auth_refresh_result == "success":
            continue
        break

    return web.json_response(
        {"error": "fixed backend auth retry failed", "request_id": request_id},
        status=502,
        headers={"x-request-id": request_id},
    )


async def handle(
    request: web.Request,
    pool: AccountPool,
    session: Optional[aiohttp.ClientSession] = None,
) -> web.Response:
    if session is None:
        async with aiohttp.ClientSession(auto_decompress=False) as temp_session:
            return await _handle_with_session(request, pool, temp_session)
    return await _handle_with_session(request, pool, session)


async def _handle_with_session(
    request: web.Request,
    pool: AccountPool,
    upstream_session: aiohttp.ClientSession,
) -> web.Response:
    path = request.path
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    websocket_session_key = _extract_session_key(dict(request.headers), b"")
    if _is_models_path(path):
        started = time.monotonic()
        resp = _models_response(request_id, path)
        pool.record_local_request(path, resp.status, (time.monotonic() - started) * 1000, request_id)
        return resp
    if _is_codex_responses_path(path) and _is_websocket_request(request):
        return await _handle_codex_websocket(
            request,
            pool,
            upstream_session,
            request_id,
            path,
            websocket_session_key,
        )
    if _uses_fixed_backend_account(path) and _is_websocket_request(request):
        return await _handle_fixed_backend_websocket(
            request,
            pool,
            upstream_session,
            request_id,
            path,
        )
    if _is_openai_inference_path(path):
        started = time.monotonic()
        resp = web.json_response(
            {
                "error": {
                    "message": (
                        "OpenAI-compatible /v1 inference is not supported for pooled "
                        "ChatGPT OAuth accounts. Enable the Codex account-pool provider instead."
                    ),
                    "type": "invalid_request_error",
                    "code": "unsupported_openai_provider_mode",
                }
            },
            status=400,
            headers={"x-request-id": request_id},
        )
        pool.record_local_request(path, resp.status, (time.monotonic() - started) * 1000, request_id)
        return resp

    upstream = _get_upstream(path)
    if upstream is None:
        return web.Response(
            status=404,
            text=f"unknown upstream for path: {path}",
            headers={"x-request-id": request_id},
        )

    target_url = _target_url(upstream, path, request.query_string)

    max_body_bytes = int(get("max_request_body_mb") or 50) * 1024 * 1024
    content_length = request.content_length
    if content_length is not None and content_length > max_body_bytes:
        return web.Response(
            status=413,
            text='{"error": "request body too large"}',
            content_type="application/json",
            headers={"x-request-id": request_id},
        )
    body = await request.read()
    if len(body) > max_body_bytes:
        return web.Response(
            status=413,
            text='{"error": "request body too large"}',
            content_type="application/json",
            headers={"x-request-id": request_id},
        )
    session_key = _extract_session_key(dict(request.headers), body) if _is_codex_responses_path(path) else ""
    request_model = _extract_request_model(body) if _is_codex_responses_path(path) else ""
    base_headers = _clean_headers(dict(request.headers))
    base_headers["accept-encoding"] = "identity"

    if _uses_fixed_backend_account(path):
        return await _handle_fixed_backend_request(
            request,
            pool,
            upstream_session,
            request_id,
            path,
            target_url,
            body,
            base_headers,
        )

    cooldown = get("rate_limit_cooldown")
    max_retries = get("max_retries")
    transient_retries = int(get("upstream_transient_retries") or 0)
    tried_accounts: set[str] = set()
    attempts: list[dict] = []
    stream_bootstrap_failures = 0

    for retry_idx in range(max_retries):
        account, affinity_hit = pool.pick_for_session(session_key, exclude=tried_accounts)
        if account is None:
            if tried_accounts:
                return _upstream_failure_response(request_id, path, attempts)
            return web.Response(
                status=429,
                text='{"error": "all accounts rate-limited"}',
                content_type="application/json",
                headers={"x-request-id": request_id},
            )

        tried_accounts.add(account.name)
        pool.bind_session(session_key, account)
        headers = _account_headers(base_headers, account, path)

        try:
            for auth_attempt in range(2):
                retry_after_refresh = False
                for transient_attempt in range(transient_retries + 1):
                    started = time.monotonic()
                    try:
                        upstream_resp_ctx = upstream_session.request(
                            request.method,
                            target_url,
                            headers=headers,
                            data=body,
                            timeout=_upstream_timeout(),
                        )
                        async with upstream_resp_ctx as upstream_resp:
                            if upstream_resp.status == 429:
                                duration_ms = (time.monotonic() - started) * 1000
                                pool.record_request(
                                    account,
                                    path,
                                    upstream_resp.status,
                                    duration_ms,
                                    retry_idx,
                                    request_id,
                                    session_key=_public_session_key(session_key),
                                    affinity_hit=_public_affinity_hit(session_key, affinity_hit),
                                    route_class=_route_class(path),
                                    selected_account=account.name,
                                    upstream_path=_codex_upstream_path(path),
                                )
                                retry_after = _retry_after_seconds(upstream_resp.headers.get("Retry-After"))
                                _record_attempt(
                                    attempts,
                                    account,
                                    "rate_limit_429",
                                    status=upstream_resp.status,
                                    retry_after=retry_after,
                                    retry_index=retry_idx,
                                )
                                pool.mark_rate_limited(account, retry_after or cooldown, "rate_limit_429")
                                pool.clear_session_binding(session_key, account)
                                await asyncio.sleep(random.uniform(0.01, 0.05))
                                break

                            if upstream_resp.status == 401:
                                logger.info(f"Account {account.name}: got 401, refreshing")
                                pool.stats["auth_refreshes"] += 1
                                if auth_attempt > 0:
                                    _record_attempt(
                                        attempts,
                                        account,
                                        "auth_failed",
                                        status=upstream_resp.status,
                                        retry_index=retry_idx,
                                    )
                                    pool.mark_rate_limited(account, 300, "auth_failed")
                                    pool.clear_session_binding(session_key, account)
                                    break
                                ok = await account.refresh()
                                if not ok:
                                    _record_attempt(
                                        attempts,
                                        account,
                                        "auth_failed",
                                        status=upstream_resp.status,
                                        retry_index=retry_idx,
                                    )
                                    pool.mark_rate_limited(account, 300, "auth_failed")
                                    pool.clear_session_binding(session_key, account)
                                else:
                                    headers["Authorization"] = f"Bearer {account.access_token}"
                                    retry_after_refresh = True
                                break

                            if not _should_stream_response(path, upstream_resp):
                                payload = await upstream_resp.read()
                                duration_ms = (time.monotonic() - started) * 1000
                                pool.record_request(
                                    account,
                                    path,
                                    upstream_resp.status,
                                    duration_ms,
                                    retry_idx,
                                    request_id,
                                    session_key=_public_session_key(session_key),
                                    affinity_hit=_public_affinity_hit(session_key, affinity_hit),
                                    route_class=_route_class(path),
                                    selected_account=account.name,
                                    upstream_path=_codex_upstream_path(path),
                                )
                                if 200 <= upstream_resp.status < 300:
                                    _record_token_usage(
                                        path,
                                        request_id,
                                        account,
                                        extract_usage_from_bytes(payload),
                                        method=request.method,
                                        model=request_model,
                                        status=upstream_resp.status,
                                        failed=False,
                                        latency_ms=duration_ms,
                                    )
                                return web.Response(
                                    status=upstream_resp.status,
                                    body=payload,
                                    headers=_response_headers(upstream_resp, request_id),
                                )

                            codex_stream_mode = _codex_stream_mode() if _is_codex_responses_path(path) else ""
                            requires_completion = (
                                bool(codex_stream_mode)
                                and not _is_codex_compact_path(path)
                            )
                            if codex_stream_mode and codex_stream_mode != "realtime":
                                try:
                                    buffered = await _fetch_complete_codex_stream(
                                        upstream_resp,
                                        codex_stream_mode,
                                        require_completion=requires_completion,
                                    )
                                except _RetryableStreamError as e:
                                    _record_attempt(
                                        attempts,
                                        account,
                                        "stream_interrupted",
                                        error=str(e),
                                        bytes_read=e.bytes_read,
                                        response_completed=e.completed,
                                        stream_mode=codex_stream_mode,
                                        retry_index=retry_idx,
                                    )
                                    _record_buffered_stream_interrupted(
                                        pool,
                                        account,
                                        path,
                                        request_id,
                                        retry_idx,
                                        e,
                                        codex_stream_mode,
                                        _codex_stream_retry_cooldown(),
                                    )
                                    pool.clear_session_binding(session_key, account)
                                    raise
                                duration_ms = (time.monotonic() - started) * 1000
                                pool.record_request(
                                    account,
                                    path,
                                    upstream_resp.status,
                                    duration_ms,
                                    retry_idx,
                                    request_id,
                                    buffered.stream_mode,
                                    _http_transport_label(codex_stream_mode),
                                    session_key=_public_session_key(session_key),
                                    affinity_hit=_public_affinity_hit(session_key, affinity_hit),
                                    route_class=_route_class(path),
                                    selected_account=account.name,
                                    upstream_path=_codex_upstream_path(path),
                                )
                                usage = (
                                    extract_usage_from_sse_bytes(buffered.body)
                                    or extract_usage_from_bytes(buffered.body)
                                )
                                _record_token_usage(
                                    path,
                                    request_id,
                                    account,
                                    usage,
                                    method=request.method,
                                    model=request_model,
                                    status=upstream_resp.status,
                                    failed=not (200 <= upstream_resp.status < 400),
                                    latency_ms=duration_ms,
                                )
                                pool.bind_session(session_key, account)
                                return web.Response(
                                    status=upstream_resp.status,
                                    body=buffered.body,
                                    headers=_response_headers(upstream_resp, request_id),
                                )

                            active_stream_mode = "realtime" if codex_stream_mode == "realtime" else ""
                            active_transport = _http_transport_label(codex_stream_mode)
                            stream_cooldown = _codex_stream_retry_cooldown() if codex_stream_mode else cooldown
                            try:
                                return await _relay_realtime_stream(
                                    request,
                                    pool,
                                    account,
                                    path,
                                    request_id,
                                    retry_idx,
                                    upstream_resp,
                                    started,
                                    active_stream_mode,
                                    active_transport,
                                    requires_completion,
                                    stream_cooldown,
                                    session_key,
                                    affinity_hit,
                                    request_model,
                                    route_class=_route_class(path),
                                    upstream_path=_codex_upstream_path(path),
                                )
                            except _RetryableStreamError as e:
                                _record_attempt(
                                    attempts,
                                    account,
                                    "stream_interrupted_before_response",
                                    error=str(e),
                                    retry_index=retry_idx,
                                )
                                pool.record_error(
                                    path,
                                    _stream_error_detail(
                                        "stream_interrupted_before_response",
                                        str(e),
                                        e.bytes_read,
                                        e.completed,
                                    ),
                                    account,
                                    request_id,
                                    retry_idx,
                                )
                                logger.warning(
                                    "stream failed before response request_id=%s account=%s "
                                    "path=%s error=%s",
                                    request_id,
                                    account.name,
                                    path,
                                    e,
                                )
                                raise
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        if transient_attempt < transient_retries:
                            delay = _transient_backoff_seconds(transient_attempt)
                            logger.warning(
                                "transient upstream error request_id=%s account=%s attempt=%s/%s path=%s: %s",
                                request_id,
                                account.name,
                                transient_attempt + 1,
                                transient_retries + 1,
                                path,
                                e,
                            )
                            if delay:
                                await asyncio.sleep(delay)
                            continue
                        raise

                    break

                if retry_after_refresh:
                    continue
                break

        except _RetryableStreamError:
            stream_bootstrap_failures += 1
            pool.clear_session_binding(session_key, account)
            if stream_bootstrap_failures <= _stream_bootstrap_retries():
                continue
            break
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"upstream error: {e}")
            _record_attempt(
                attempts,
                account,
                "upstream_error",
                error=str(e),
                retry_index=retry_idx,
            )
            pool.record_error(path, str(e), account, request_id, retry_idx)
            pool.clear_session_binding(session_key, account)
            continue

    return _upstream_failure_response(request_id, path, attempts, "upstream unavailable")
