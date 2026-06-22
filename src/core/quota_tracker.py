"""Quota tracker — fetches usage stats from Codex API in the background."""

import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp

from account_manager import AccountPool, ACCOUNTS_DIR
from config import get
from proxy_core import _account_headers

USAGE_URL = "https://chatgpt.com/backend-api/codex/usage"

logger = logging.getLogger(__name__)
_refresh_lock: Optional[asyncio.Lock] = None
_state = {
    "in_progress": False,
    "last_run_at": None,
    "last_elapsed_ms": None,
    "last_result": None,
    "last_error": None,
}


class UsageFetchError(Exception):
    def __init__(self, status: int):
        super().__init__(f"usage API returned {status}")
        self.status = status


async def _fetch_usage(account, session: aiohttp.ClientSession) -> Optional[dict]:
    if not account.access_token:
        return None
    headers = _account_headers(
        {
            "Accept": "*/*",
            "accept-encoding": "identity",
        },
        account,
        "/backend-api/codex/usage",
    )
    try:
        async with session.get(
            USAGE_URL,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status != 200:
                logger.debug(
                    f"Account {account.name}: usage API returned {resp.status}"
                )
                raise UsageFetchError(resp.status)
            return await resp.json()
    except asyncio.TimeoutError:
        raise
    except UsageFetchError:
        raise
    except Exception as e:
        logger.debug(f"Account {account.name}: usage fetch error: {e}")
        return None


def _summary(result: dict) -> dict:
    refreshed = sum(1 for item in result.values() if item.get("refreshed"))
    skipped = sum(1 for item in result.values() if item.get("skipped"))
    failed = max(0, len(result) - refreshed - skipped)
    return {
        "accounts": len(result),
        "refreshed": refreshed,
        "skipped": skipped,
        "failed": failed,
    }


def status(task: Optional[asyncio.Task] = None) -> dict:
    """Return quota tracker runtime status for diagnostics."""
    running = bool(task and not task.done())
    task_error = None
    if task and task.done() and not task.cancelled():
        exc = task.exception()
        task_error = str(exc) if exc else None
    return {
        "enabled": bool(get("quota_tracker_enabled")),
        "interval": get("quota_refresh_interval"),
        "running": running,
        "in_progress": bool(_state["in_progress"]),
        "last_run_at": _state["last_run_at"],
        "last_elapsed_ms": _state["last_elapsed_ms"],
        "last_result": _state["last_result"],
        "last_error": task_error or _state["last_error"],
    }


async def refresh_once(pool: AccountPool) -> dict:
    """Fetch and persist quota data for all enabled accounts once."""
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()

    async def refresh_account(acct, session):
        if not acct.enabled:
            return acct.name, {"refreshed": False, "skipped": "disabled"}
        try:
            data = await _fetch_usage(acct, session)
        except asyncio.TimeoutError:
            logger.debug(f"Account {acct.name}: usage fetch timed out")
            return acct.name, {"refreshed": False, "error": "timeout"}
        except UsageFetchError as e:
            return acct.name, {
                "refreshed": False,
                "error": f"usage_http_{e.status}",
                "status": e.status,
            }
        if data:
            quota_file = ACCOUNTS_DIR / acct.name / "quota.json"
            data["_fetched_at"] = time.time()
            quota_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = quota_file.with_suffix(".json.tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            tmp_file.replace(quota_file)
            logger.debug(f"Account {acct.name}: quota updated")
            return acct.name, {"refreshed": True, "fetched_at": data["_fetched_at"]}
        return acct.name, {"refreshed": False, "error": "usage_unavailable"}

    async with _refresh_lock:
        started = time.monotonic()
        _state["in_progress"] = True
        _state["last_error"] = None
        try:
            async with aiohttp.ClientSession() as session:
                pairs = await asyncio.gather(
                    *(refresh_account(acct, session) for acct in pool.accounts)
                )
            result = {name: item for name, item in pairs}
            _state["last_run_at"] = time.time()
            _state["last_elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
            _state["last_result"] = _summary(result)
            return result
        except Exception as e:
            _state["last_run_at"] = time.time()
            _state["last_elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
            _state["last_result"] = None
            _state["last_error"] = str(e)
            raise
        finally:
            _state["in_progress"] = False


async def run(pool: AccountPool) -> None:
    """Run the quota tracker loop. Meant to be launched as a background task."""
    while True:
        try:
            await refresh_once(pool)
        except Exception as e:
            logger.error(f"quota tracker error: {e}")
        slept = 0.0
        while slept < float(get("quota_refresh_interval") or 300):
            step = min(5.0, float(get("quota_refresh_interval") or 300) - slept)
            await asyncio.sleep(step)
            slept += step
