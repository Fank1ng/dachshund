"""Core proxy — request forwarding with account pool, failover, and SSE streaming."""

import asyncio
import logging
import random
import time
import uuid
from typing import Optional

import aiohttp
from aiohttp import web

from account_manager import AccountPool
from config import get

logger = logging.getLogger(__name__)

UPSTREAM_MAP = {
    "/v1/": "https://api.openai.com",
    "/backend-api/": "https://chatgpt.com",
}

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
    for prefix, host in UPSTREAM_MAP.items():
        if path.startswith(prefix):
            return host
    return None


def _is_models_path(path: str) -> bool:
    return path == "/v1/models" or path.startswith("/v1/models/")


def _is_openai_inference_path(path: str) -> bool:
    return (
        path == "/v1/responses"
        or path == "/v1/chat/completions"
        or path == "/v1/completions"
    )


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
    if path.startswith("/backend-api/"):
        headers.update(CHATGPT_WEB_HEADERS)
    headers["Authorization"] = f"Bearer {account.access_token}"
    if path.startswith("/backend-api/") and account.account_id:
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


def _is_streaming_response(upstream_resp: aiohttp.ClientResponse) -> bool:
    content_type = upstream_resp.headers.get("Content-Type", "").lower()
    return "text/event-stream" in content_type


def _response_headers(upstream_resp: aiohttp.ClientResponse, request_id: str) -> dict:
    headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in HOP_HEADERS
    }
    headers["x-request-id"] = request_id
    return headers


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
    if _is_models_path(path):
        started = time.monotonic()
        resp = _models_response(request_id, path)
        pool.record_local_request(path, resp.status, (time.monotonic() - started) * 1000, request_id)
        return resp
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

    target_url = f"{upstream}{path}"
    if request.query_string:
        target_url += f"?{request.query_string}"

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
    base_headers = _clean_headers(dict(request.headers))
    base_headers["accept-encoding"] = "identity"

    cooldown = get("rate_limit_cooldown")
    max_retries = get("max_retries")
    transient_retries = int(get("upstream_transient_retries") or 0)
    tried_accounts: set[str] = set()

    for retry_idx in range(max_retries):
        account = pool.pick(exclude=tried_accounts)
        if account is None:
            if tried_accounts:
                return web.Response(
                    status=502,
                    text='{"error": "all eligible accounts failed for this request"}',
                    content_type="application/json",
                    headers={"x-request-id": request_id},
                )
            return web.Response(
                status=429,
                text='{"error": "all accounts rate-limited"}',
                content_type="application/json",
                headers={"x-request-id": request_id},
            )

        tried_accounts.add(account.name)
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
                                )
                                retry_after = _retry_after_seconds(upstream_resp.headers.get("Retry-After"))
                                pool.mark_rate_limited(account, retry_after or cooldown, "rate_limit_429")
                                await asyncio.sleep(random.uniform(0.01, 0.05))
                                break

                            if upstream_resp.status == 401:
                                logger.info(f"Account {account.name}: got 401, refreshing")
                                pool.stats["auth_refreshes"] += 1
                                if auth_attempt > 0:
                                    pool.mark_rate_limited(account, 300, "auth_failed")
                                    break
                                ok = await account.refresh()
                                if not ok:
                                    pool.mark_rate_limited(account, 300, "auth_failed")
                                else:
                                    headers["Authorization"] = f"Bearer {account.access_token}"
                                    retry_after_refresh = True
                                break

                            if not _is_streaming_response(upstream_resp):
                                payload = await upstream_resp.read()
                                duration_ms = (time.monotonic() - started) * 1000
                                pool.record_request(
                                    account,
                                    path,
                                    upstream_resp.status,
                                    duration_ms,
                                    retry_idx,
                                    request_id,
                                )
                                return web.Response(
                                    status=upstream_resp.status,
                                    body=payload,
                                    headers=_response_headers(upstream_resp, request_id),
                                )

                            resp = web.StreamResponse(
                                status=upstream_resp.status,
                                headers=_response_headers(upstream_resp, request_id),
                            )

                            duration_ms = (time.monotonic() - started) * 1000
                            try:
                                await resp.prepare(request)
                                async for chunk, _ in upstream_resp.content.iter_chunks():
                                    await resp.write(chunk)
                                await resp.write_eof()
                            except (ConnectionResetError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                                logger.info(f"stream ended early request_id={request_id}: {e}")
                                pool.record_error(path, str(e), account, request_id, retry_idx)
                                pool.record_request(
                                    account,
                                    path,
                                    upstream_resp.status,
                                    duration_ms,
                                    retry_idx,
                                    request_id,
                                )
                                return resp
                            duration_ms = (time.monotonic() - started) * 1000
                            pool.record_request(
                                account,
                                path,
                                upstream_resp.status,
                                duration_ms,
                                retry_idx,
                                request_id,
                            )
                            return resp
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

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"upstream error: {e}")
            pool.record_error(path, str(e), account, request_id, retry_idx)
            continue

    return web.Response(
        status=502,
        text='{"error": "upstream unavailable"}',
        content_type="application/json",
        headers={"x-request-id": request_id},
    )
