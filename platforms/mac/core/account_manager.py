"""Account management — CRUD, token loading, OAuth token refresh."""

import asyncio
import json
import logging
import re
import time
from collections import deque
from typing import Optional
from pathlib import Path

import aiohttp

from config import CONFIG_DIR, get

ACCOUNTS_DIR = CONFIG_DIR / "accounts"
RECENT_REQUESTS_FILE = CONFIG_DIR / "recent_requests.json"
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

logger = logging.getLogger(__name__)


class AccountNameError(ValueError):
    """Raised when an account name cannot safely map to accounts/."""


def validate_account_name(name: str) -> str:
    normalized = (name or "").strip()
    if not ACCOUNT_NAME_RE.fullmatch(normalized):
        raise AccountNameError("account name must be 1-64 letters, numbers, dashes, or underscores")
    return normalized


def account_dir(name: str) -> Path:
    safe_name = validate_account_name(name)
    root = ACCOUNTS_DIR.resolve()
    target = (ACCOUNTS_DIR / safe_name).resolve()
    if target != root and root not in target.parents:
        raise AccountNameError("account path escapes accounts directory")
    return target


class Account:
    def __init__(self, name: str, auth_path: Path):
        self.name = name
        self.auth_path = auth_path
        self.meta_path = auth_path.parent / "account.json"
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.email: str = ""
        self.account_id: str = ""
        self.expires_at: float = 0
        self.rate_limited_until: float = 0
        self.cooldown_reason: str = ""
        self.enabled: bool = True
        self.auth_error: str = ""
        self._refresh_lock: Optional[asyncio.Lock] = None

    def load(self) -> bool:
        """Load tokens from auth.json. Returns False if file missing or invalid."""
        if not self.auth_path.exists():
            return False
        try:
            with open(self.auth_path) as f:
                data = json.load(f)
            tokens = data.get("tokens", {})
            self.access_token = tokens.get("access_token", "")
            self.refresh_token = tokens.get("refresh_token", "")
            self.email = self._decode_email(self.access_token)
            self.account_id = tokens.get("account_id", "") or self._decode_account_id(self.access_token)
            self.expires_at = self._decode_expiry(self.access_token)
            self.load_meta()
            return bool(self.access_token)
        except Exception as e:
            logger.warning(f"Account {self.name}: failed to load tokens: {e}")
            return False

    def save(self) -> None:
        """Persist current tokens back to auth.json."""
        data = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "id_token": "",
                "account_id": self.account_id,
            },
            "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
        }
        if self.auth_path.exists():
            try:
                with open(self.auth_path) as f:
                    old = json.load(f)
                data["tokens"]["id_token"] = old.get("tokens", {}).get("id_token", "")
                data["tokens"]["account_id"] = old.get("tokens", {}).get("account_id", "")
            except Exception:
                pass
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.auth_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_meta(self) -> None:
        """Load non-secret account metadata."""
        if not self.meta_path.exists():
            self.enabled = True
            return
        try:
            with open(self.meta_path) as f:
                data = json.load(f)
            self.enabled = bool(data.get("enabled", True))
            self.auth_error = str(data.get("auth_error", ""))
        except Exception as e:
            logger.warning(f"Account {self.name}: failed to load metadata: {e}")
            self.enabled = True
            self.auth_error = ""

    def save_meta(self) -> None:
        """Persist non-secret account metadata."""
        data = {
            "enabled": self.enabled,
            "auth_error": self.auth_error,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime()),
        }
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.meta_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        tmp_path.replace(self.meta_path)

    async def refresh(self) -> bool:
        """Refresh the OAuth token. Returns False on failure."""
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            if not self.refresh_token:
                logger.warning(f"Account {self.name}: no refresh token")
                return False
            logger.info(f"Account {self.name}: refreshing token...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        TOKEN_ENDPOINT,
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": self.refresh_token,
                            "client_id": CLIENT_ID,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.error(
                                f"Account {self.name}: refresh failed ({resp.status}): {text}"
                            )
                            if "refresh_token_reused" in text or "invalid_grant" in text:
                                self.enabled = False
                                self.auth_error = "refresh_token_invalid"
                                self.save_meta()
                                logger.warning(
                                    f"Account {self.name}: disabled because refresh token is invalid"
                                )
                            return False
                        data = await resp.json()
                        self.access_token = data["access_token"]
                        if "refresh_token" in data:
                            self.refresh_token = data["refresh_token"]
                        self.expires_at = self._decode_expiry(self.access_token)
                        self.auth_error = ""
                        self.save()
                        self.save_meta()
                        logger.info(f"Account {self.name}: token refreshed OK")
                        return True
            except Exception as e:
                logger.error(f"Account {self.name}: refresh error: {e}")
                return False

    @property
    def is_rate_limited(self) -> bool:
        return time.time() < self.rate_limited_until

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
            "account_id": self.account_id,
            "enabled": self.enabled,
            "auth_error": self.auth_error,
            "rate_limited": self.is_rate_limited,
            "rate_limited_until": self.rate_limited_until,
            "cooldown_reason": self.cooldown_reason if self.is_rate_limited else "",
            "expires_at": self.expires_at,
            "has_tokens": bool(self.access_token),
        }

    @staticmethod
    def _decode_claims(token: str) -> dict:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            import base64
            return json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            return {}

    @staticmethod
    def _decode_email(token: str) -> str:
        claims = Account._decode_claims(token)
        email = (
            claims.get("email")
            or claims.get("https://api.openai.com/profile", {}).get("email", "")
        )
        return email or ""

    @staticmethod
    def _decode_account_id(token: str) -> str:
        claims = Account._decode_claims(token)
        return (
            claims.get("https://api.openai.com/auth", {}).get("chatgpt_account_id", "")
            or claims.get("sub", "")
        )

    @staticmethod
    def _decode_expiry(token: str) -> float:
        claims = Account._decode_claims(token)
        return claims.get("exp", 0)


class AccountPool:
    def __init__(self):
        self.accounts: list[Account] = []
        self._next_idx = 0
        self.stats = {
            "total_requests": 0,
            "upstream_2xx": 0,
            "upstream_4xx": 0,
            "upstream_5xx": 0,
            "rate_limits": 0,
            "auth_refreshes": 0,
            "errors": 0,
        }
        self.recent_requests = deque(maxlen=50)
        self.recent_errors = deque(maxlen=20)
        self._load_recent_requests()

    def scan(self) -> None:
        """Scan accounts/ directory and load all valid accounts."""
        ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
        seen = set()
        for entry in sorted(ACCOUNTS_DIR.iterdir()):
            if entry.name.startswith("."):
                continue
            if not entry.is_dir():
                continue
            auth_file = entry / "auth.json"
            if not auth_file.exists():
                continue
            name = entry.name
            seen.add(name)
            existing = self.get(name)
            if existing:
                existing.load()
            else:
                acct = Account(name, auth_file)
                if acct.load():
                    self.accounts.append(acct)
                    logger.info(f"Account '{name}' loaded: {acct.email}")
        # Remove accounts whose directory no longer exists
        self.accounts = [a for a in self.accounts if a.name in seen]

    def get(self, name: str) -> Optional["Account"]:
        for a in self.accounts:
            if a.name == name:
                return a
        return None

    def pick(self, exclude: Optional[set[str]] = None) -> Optional["Account"]:
        """Pick an account using the configured strategy."""
        exclude = exclude or set()
        if not self.accounts:
            return None

        strategy = get("rotation_strategy")
        if strategy == "most_available":
            picked = self._pick_most_available(exclude)
            if picked:
                return picked

        return self._pick_round_robin(exclude)

    def _eligible_accounts(self, exclude: set[str]) -> list["Account"]:
        return [
            acct for acct in self.accounts
            if acct.name not in exclude
            and acct.enabled
            and not acct.is_rate_limited
            and acct.access_token
        ]

    def _pick_round_robin(self, exclude: set[str]) -> Optional["Account"]:
        for _ in range(len(self.accounts)):
            idx = self._next_idx % len(self.accounts)
            self._next_idx += 1
            acct = self.accounts[idx]
            if acct.name not in exclude and acct.enabled and not acct.is_rate_limited and acct.access_token:
                return acct
        return None

    def _pick_most_available(self, exclude: set[str]) -> Optional["Account"]:
        candidates = self._eligible_accounts(exclude)
        ranked = [
            (self._quota_pressure(acct), index, acct)
            for index, acct in enumerate(candidates)
        ]
        known = [item for item in ranked if item[0] is not None]
        if not known or len(known) != len(candidates):
            return None
        _, _, picked = min(known, key=lambda item: (item[0], item[1]))
        if picked in self.accounts:
            self._next_idx = self.accounts.index(picked) + 1
        return picked

    def selection_report(self) -> dict:
        """Return a non-mutating explanation of the account that would be picked."""
        strategy = get("rotation_strategy")
        weight_5h = float(get("quota_weight_5h") or 0)
        weight_7d = float(get("quota_weight_7d") or 0)
        rows = []
        eligible = []
        for index, acct in enumerate(self.accounts):
            pressure = self._quota_pressure(acct)
            reasons = []
            if not acct.enabled:
                reasons.append("disabled")
            if acct.is_rate_limited:
                seconds = max(0, int(acct.rate_limited_until - time.time()))
                detail = acct.cooldown_reason or "cooldown"
                reasons.append(f"{detail}:{seconds}s")
            if not acct.access_token:
                reasons.append("missing_token")
            if acct.auth_error:
                reasons.append(acct.auth_error)
            if strategy == "most_available" and pressure is None:
                reasons.append("missing_quota")
            selectable = not reasons or reasons == ["missing_quota"]
            if acct.enabled and not acct.is_rate_limited and acct.access_token:
                eligible.append((index, acct, pressure))
            rows.append({
                "name": acct.name,
                "email": acct.email,
                "enabled": acct.enabled,
                "rate_limited": acct.is_rate_limited,
                "auth_error": acct.auth_error,
                "has_tokens": bool(acct.access_token),
                "quota_pressure": None if pressure is None else round(pressure, 2),
                "selectable": selectable,
                "reasons": reasons,
            })

        predicted = None
        note = ""
        if strategy == "most_available":
            known = [item for item in eligible if item[2] is not None]
            if known and len(known) == len(eligible):
                _, predicted_acct, _ = min(known, key=lambda item: (item[2], item[0]))
                predicted = predicted_acct.name
                note = "using weighted quota pressure"
            elif eligible:
                predicted = self._preview_round_robin(set())
                note = "falling back to round_robin because quota data is incomplete"
        else:
            predicted = self._preview_round_robin(set())
            note = "using round_robin"

        if predicted is None and eligible:
            predicted = self._preview_round_robin(set())
        if predicted is None:
            note = "no eligible account"

        return {
            "strategy": strategy,
            "quota_weight_5h": weight_5h,
            "quota_weight_7d": weight_7d,
            "predicted_account": predicted,
            "note": note,
            "accounts": rows,
        }

    def _preview_round_robin(self, exclude: set[str]) -> Optional[str]:
        if not self.accounts:
            return None
        for offset in range(len(self.accounts)):
            idx = (self._next_idx + offset) % len(self.accounts)
            acct = self.accounts[idx]
            if acct.name not in exclude and acct.enabled and not acct.is_rate_limited and acct.access_token:
                return acct.name
        return None

    def _quota_pressure(self, account: Account) -> Optional[float]:
        quota_file = ACCOUNTS_DIR / account.name / "quota.json"
        if not quota_file.exists():
            return None
        try:
            with open(quota_file) as f:
                data = json.load(f)
        except Exception:
            return None
        rate_limit = data.get("rate_limit") or {}
        primary = rate_limit.get("primary_window") or {}
        secondary = rate_limit.get("secondary_window") or {}
        five_hour = self._quota_percent(primary.get("used_percent"), data.get("5h_usage"))
        seven_day = self._quota_percent(secondary.get("used_percent"), data.get("weekly_usage"))
        if five_hour is None:
            return None
        if self._uses_shared_codex_window(data, primary, secondary):
            seven_day = five_hour
        elif seven_day is None:
            return None

        weight_5h = float(get("quota_weight_5h") or 0)
        weight_7d = float(get("quota_weight_7d") or 0)
        total_weight = weight_5h + weight_7d
        if total_weight <= 0:
            return None
        return ((five_hour * weight_5h) + (seven_day * weight_7d)) / total_weight

    @staticmethod
    def _uses_shared_codex_window(data: dict, primary: dict, secondary: dict) -> bool:
        plan_type = str(data.get("plan_type") or "").lower()
        if plan_type not in {"free", "go"}:
            return False
        return not AccountPool._has_distinct_weekly_window(primary, secondary)

    @staticmethod
    def _has_distinct_weekly_window(primary: dict, secondary: dict) -> bool:
        secondary_seconds = AccountPool._quota_number(secondary.get("limit_window_seconds"))
        if secondary_seconds is None:
            return False
        if secondary_seconds < 604800 * 0.9:
            return False
        primary_seconds = AccountPool._quota_number(primary.get("limit_window_seconds"))
        if primary_seconds is not None and abs(secondary_seconds - primary_seconds) < 60:
            return False
        return True

    @staticmethod
    def _quota_percent(*values) -> Optional[float]:
        for value in values:
            if isinstance(value, (int, float)):
                return float(value)
        return None

    @staticmethod
    def _quota_number(value) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def record_request(
        self,
        account: Account,
        path: str,
        status: int,
        duration_ms: float,
        retries: int,
        request_id: str = "",
    ) -> None:
        self.stats["total_requests"] += 1
        if status == 429:
            self.stats["rate_limits"] += 1
        elif 200 <= status < 300:
            self.stats["upstream_2xx"] += 1
        elif 400 <= status < 500:
            self.stats["upstream_4xx"] += 1
        elif status >= 500:
            self.stats["upstream_5xx"] += 1

        self.recent_requests.appendleft({
            "request_id": request_id,
            "account": account.name,
            "email": account.email,
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "retries": retries,
            "strategy": get("rotation_strategy"),
            "at": time.time(),
        })
        logger.info(
            "request_id=%s account=%s status=%s duration_ms=%.1f retries=%s path=%s",
            request_id or "-",
            account.name,
            status,
            duration_ms,
            retries,
            path,
        )
        self._save_recent_requests()

    def record_local_request(
        self,
        path: str,
        status: int,
        duration_ms: float,
        request_id: str = "",
    ) -> None:
        self.stats["total_requests"] += 1
        self.recent_requests.appendleft({
            "request_id": request_id,
            "account": "local",
            "email": "",
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms, 1),
            "retries": 0,
            "strategy": "local",
            "at": time.time(),
        })
        logger.info(
            "request_id=%s account=local status=%s duration_ms=%.1f path=%s",
            request_id or "-",
            status,
            duration_ms,
            path,
        )
        self._save_recent_requests()

    def clear_recent_requests(self) -> None:
        self.recent_requests.clear()
        try:
            RECENT_REQUESTS_FILE.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f"failed to remove recent request history: {e}")

    def _load_recent_requests(self) -> None:
        if not RECENT_REQUESTS_FILE.exists():
            return
        try:
            with open(RECENT_REQUESTS_FILE) as f:
                rows = json.load(f)
            if isinstance(rows, list):
                self.recent_requests.extend(row for row in rows[:50] if isinstance(row, dict))
        except Exception as e:
            logger.warning(f"failed to load recent request history: {e}")

    def _save_recent_requests(self) -> None:
        try:
            RECENT_REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = RECENT_REQUESTS_FILE.with_suffix(".json.tmp")
            with open(tmp_path, "w") as f:
                json.dump(list(self.recent_requests), f, indent=2)
                f.write("\n")
            tmp_path.replace(RECENT_REQUESTS_FILE)
        except OSError as e:
            logger.warning(f"failed to save recent request history: {e}")

    def record_error(
        self,
        path: str = "",
        error: str = "",
        account: Optional[Account] = None,
        request_id: str = "",
        retries: int = 0,
    ) -> None:
        self.stats["errors"] += 1
        if path or error or account or request_id:
            self.recent_errors.appendleft({
                "request_id": request_id,
                "account": account.name if account else "",
                "email": account.email if account else "",
                "path": path,
                "error": error,
                "retries": retries,
                "at": time.time(),
            })

    def mark_rate_limited(self, account: Account, cooldown: int = 60, reason: str = "rate_limit") -> None:
        account.rate_limited_until = time.time() + cooldown
        account.cooldown_reason = reason
        logger.warning(
            f"Account {account.name}: cooldown reason={reason} until "
            f"{time.strftime('%H:%M:%S', time.localtime(account.rate_limited_until))}"
        )

    def clear_cooldown(self, account: Account) -> None:
        account.rate_limited_until = 0
        account.cooldown_reason = ""

    def all_limited(self) -> bool:
        return all(
            a.is_rate_limited or not a.enabled or not a.access_token
            for a in self.accounts
        )

    def active_count(self) -> int:
        return sum(
            1 for a in self.accounts if a.enabled and not a.is_rate_limited and a.access_token
        )
