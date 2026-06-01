import json
import os
import sys
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "core"))
sys.path.insert(0, str(ROOT / "platforms" / "mac"))

import account_manager
import codex_cli
import codex_config
import login_manager
import control_actions
import proxy
import quota_tracker
import service_manager
from account_manager import Account, AccountNameError, AccountPool, validate_account_name
from config import ConfigError, validate
from proxy_core import (
    _account_headers,
    _clean_headers,
    _is_streaming_response,
    _is_models_path,
    _is_openai_inference_path,
    _retry_after_seconds,
    _upstream_timeout,
)


class ConfigTests(unittest.TestCase):
    def test_validate_accepts_supported_strategy_and_body_limit(self):
        cfg = validate({
            "rotation_strategy": "most_available",
            "max_request_body_mb": "128",
            "upstream_connect_timeout_sec": "12",
            "upstream_transient_retries": "3",
            "upstream_transient_backoff_ms": "500",
            "quota_tracker_enabled": "true",
            "quota_weight_5h": "0.8",
            "quota_weight_7d": "0.2",
        })
        self.assertEqual(cfg["rotation_strategy"], "most_available")
        self.assertEqual(cfg["max_request_body_mb"], 128)
        self.assertEqual(cfg["upstream_connect_timeout_sec"], 12)
        self.assertEqual(cfg["upstream_transient_retries"], 3)
        self.assertEqual(cfg["upstream_transient_backoff_ms"], 500)
        self.assertTrue(cfg["quota_tracker_enabled"])
        self.assertEqual(cfg["quota_weight_5h"], 0.8)
        self.assertEqual(cfg["quota_weight_7d"], 0.2)

    def test_validate_rejects_invalid_quota_tracker_flag(self):
        with self.assertRaises(ConfigError):
            validate({"quota_tracker_enabled": "maybe"})

    def test_validate_rejects_unknown_strategy(self):
        with self.assertRaises(ConfigError):
            validate({"rotation_strategy": "least_used"})

    def test_validate_rejects_zero_quota_weights(self):
        with self.assertRaises(ConfigError):
            validate({"quota_weight_5h": 0, "quota_weight_7d": 0})


class CodexCliLocatorTests(unittest.TestCase):
    def test_env_override_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "codex.exe"
            cli.write_text("exe\n")
            env = {
                "CODEX_CLI_PATH": str(cli),
                "PATH": "",
                "LOCALAPPDATA": str(Path(tmp) / "missing"),
            }

            self.assertEqual(codex_cli.find_codex_cli(env, platform_name="win32"), str(cli))

    def test_windows_local_codex_bin_is_found_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp)
            cli = local_app_data / "OpenAI" / "Codex" / "bin" / "abc123" / "codex.exe"
            cli.parent.mkdir(parents=True)
            cli.write_text("exe\n")
            env = {"PATH": "", "LOCALAPPDATA": str(local_app_data)}

            self.assertEqual(codex_cli.find_codex_cli(env, platform_name="win32"), str(cli))

    def test_windows_local_codex_bin_uses_newest_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_app_data = Path(tmp)
            old_cli = local_app_data / "OpenAI" / "Codex" / "bin" / "old" / "codex.exe"
            new_cli = local_app_data / "OpenAI" / "Codex" / "bin" / "new" / "codex.exe"
            old_cli.parent.mkdir(parents=True)
            new_cli.parent.mkdir(parents=True)
            old_cli.write_text("old\n")
            new_cli.write_text("new\n")
            os.utime(old_cli, (100, 100))
            os.utime(new_cli, (200, 200))
            env = {"PATH": "", "LOCALAPPDATA": str(local_app_data)}

            self.assertEqual(codex_cli.find_codex_cli(env, platform_name="win32"), str(new_cli))

    def test_missing_cli_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": "", "LOCALAPPDATA": str(Path(tmp) / "missing")}

            self.assertIsNone(codex_cli.find_codex_cli(env, platform_name="win32"))

    def test_login_manager_reports_clear_missing_cli_error(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        account_manager.ACCOUNTS_DIR = Path(tempfile.mkdtemp())
        try:
            with mock.patch("login_manager.find_codex_cli", return_value=None):
                with self.assertRaises(FileNotFoundError) as exc:
                    asyncio.run(login_manager.LoginManager().start("new_account"))
            self.assertIn("Codex CLI not found", str(exc.exception))
            self.assertIn("CODEX_CLI_PATH", str(exc.exception))
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir


class AccountTests(unittest.TestCase):
    def test_validate_account_name_rejects_path_values(self):
        for value in ("../x", "a/b", "", "has space"):
            with self.assertRaises(AccountNameError):
                validate_account_name(value)

    def test_account_meta_round_trip(self):
        root = Path(tempfile.mkdtemp())
        account = Account("tmp", root / "auth.json")
        account.enabled = False
        account.auth_error = "refresh_token_invalid"
        account.save_meta()

        loaded = Account("tmp", root / "auth.json")
        loaded.load_meta()
        self.assertFalse(loaded.enabled)
        self.assertEqual(loaded.auth_error, "refresh_token_invalid")

    def test_record_request_keeps_request_id(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        pool.record_request(account, "/v1/test", 200, 12.3, 0, "req123")
        self.assertEqual(pool.recent_requests[0]["request_id"], "req123")

    def test_record_local_request_uses_local_account_label(self):
        pool = AccountPool()
        pool.record_local_request("/v1/models", 200, 0.5, "local123")
        self.assertEqual(pool.recent_requests[0]["account"], "local")
        self.assertEqual(pool.stats["total_requests"], 1)

    def test_clear_recent_requests_removes_rows(self):
        pool = AccountPool()
        pool.record_local_request("/v1/models", 200, 0.5, "local123")
        pool.clear_recent_requests()
        self.assertEqual(len(pool.recent_requests), 0)

    def test_record_error_keeps_recent_diagnostic(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        pool.record_error("/backend-api/codex/responses/compact", "Server disconnected", account, "err123", 1)
        self.assertEqual(pool.stats["errors"], 1)
        self.assertEqual(pool.recent_errors[0]["request_id"], "err123")
        self.assertEqual(pool.recent_errors[0]["account"], "tmp")

    def test_selection_report_explains_disabled_account(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_a.enabled = False
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]

        report = pool.selection_report()
        self.assertEqual(report["predicted_account"], "b")
        self.assertIn("disabled", report["accounts"][0]["reasons"])

    def test_cooldown_reason_round_trip(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        pool.mark_rate_limited(account, 60, "auth_failed")
        self.assertTrue(account.is_rate_limited)
        self.assertEqual(account.to_dict()["cooldown_reason"], "auth_failed")
        pool.clear_cooldown(account)
        self.assertFalse(account.is_rate_limited)

    def test_free_account_without_distinct_weekly_window_uses_primary_quota(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        account_manager.ACCOUNTS_DIR = root
        try:
            account = Account("free", root / "free" / "auth.json")
            quota_dir = root / "free"
            quota_dir.mkdir(parents=True)
            with open(quota_dir / "quota.json", "w") as f:
                json.dump({
                    "plan_type": "free",
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 80,
                            "limit_window_seconds": 18000,
                        },
                        "secondary_window": {
                            "used_percent": 0,
                            "limit_window_seconds": 18000,
                        },
                    },
                }, f)

            self.assertEqual(AccountPool()._quota_pressure(account), 80)
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir


class ControlActionsTests(unittest.TestCase):
    def test_clear_auth_error_local_reenables_account(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        account_manager.ACCOUNTS_DIR = root
        try:
            account_dir = root / "a"
            account_dir.mkdir(parents=True)
            (account_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}))
            account = Account("a", account_dir / "auth.json")
            account.enabled = False
            account.auth_error = "refresh_token_invalid"
            account.save_meta()

            with mock.patch("control_actions.proxy_status", return_value=None):
                result = control_actions.clear_auth_error("a")

            self.assertFalse(result["running"])
            self.assertTrue(result["enabled"])
            self.assertEqual(result["auth_error"], "")
            self.assertEqual(result["previous_auth_error"], "refresh_token_invalid")

            loaded = Account("a", account_dir / "auth.json")
            loaded.load_meta()
            self.assertTrue(loaded.enabled)
            self.assertEqual(loaded.auth_error, "")
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir

    def test_delete_account_local_moves_account_to_trash(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        account_manager.ACCOUNTS_DIR = root
        try:
            account_dir = root / "a"
            account_dir.mkdir(parents=True)
            (account_dir / "auth.json").write_text(json.dumps({"tokens": {"access_token": "x"}}))

            with mock.patch("control_actions.proxy_status", return_value=None):
                result = control_actions.delete_account("a")

            self.assertFalse(result["running"])
            self.assertEqual(result["deleted"], "a")
            self.assertFalse(account_dir.exists())
            self.assertTrue(Path(result["trashed_to"]).exists())
            self.assertEqual(Path(result["trashed_to"]).parent.resolve(), (root / ".trash").resolve())
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir

    def test_disable_codex_proxy_action_sets_direct_mode(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"
        codex_config.set_enabled(True, config_path)
        with mock.patch.object(codex_config, "CODEX_CONFIG_PATH", config_path):
            result = control_actions.disable_codex_proxy()

        self.assertEqual(result["action"], "disable_codex_proxy")
        self.assertFalse(result["enabled"])
        self.assertEqual(codex_config.status(config_path)["mode"], "direct")

    def test_start_login_launches_codex_with_account_home(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        account_manager.ACCOUNTS_DIR = root
        fake_process = mock.Mock(pid=1234)
        try:
            with mock.patch("control_actions.find_codex_cli", return_value="/tmp/codex"), \
                    mock.patch.object(service_manager, "RUNTIME_DIR", runtime), \
                    mock.patch("control_actions.subprocess.Popen", return_value=fake_process) as popen:
                result = control_actions.start_login("new_account")

            self.assertEqual(result["action"], "login_started")
            self.assertEqual(result["account"], "new_account")
            self.assertTrue((root / "new_account").exists())
            args, kwargs = popen.call_args_list[0]
            self.assertEqual(args[0], ["/tmp/codex", "login"])
            self.assertEqual(Path(kwargs["env"]["CODEX_HOME"]).resolve(), (root / "new_account").resolve())
            self.assertEqual(kwargs["cwd"], str(runtime))
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir

    def test_login_command_reports_missing_codex_cli(self):
        old_accounts_dir = account_manager.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        account_manager.ACCOUNTS_DIR = root
        try:
            with mock.patch("control_actions.find_codex_cli", return_value=None):
                result = control_actions.login_command("new_account")

            self.assertEqual(result["error"], "codex_cli_missing")
            self.assertFalse(result.get("command"))
            self.assertIn("Codex", result["codex_cli_error"])
        finally:
            account_manager.ACCOUNTS_DIR = old_accounts_dir

    def test_repair_open_codex_reports_missing_app(self):
        missing_app = Path(tempfile.mkdtemp()) / "Missing Codex.app"
        with mock.patch.object(control_actions, "CODEX_APP_PATH", missing_app), \
                mock.patch("control_actions.repair", return_value={"running": True}):
            result = control_actions.repair_open_codex()

        self.assertEqual(result["error"], "codex_app_missing")
        self.assertIn("Codex App", result["codex_cli_error"])

    def test_render_output_json_keeps_machine_readable_keys(self):
        payload = {
            "action": "status",
            "running": True,
            "active_accounts": 2,
            "nested": {"mode": "direct"},
        }

        rendered = control_actions.render_output(payload, "json")

        self.assertEqual(json.loads(rendered), payload)
        self.assertNotIn("动作", rendered)

    def test_render_output_pretty_preserves_localized_default(self):
        rendered = control_actions.render_output({
            "action": "list_accounts",
            "running": False,
        })

        self.assertIn("动作", rendered)
        self.assertIn("列出账号", rendered)


class ServiceManagerTests(unittest.TestCase):
    def test_sync_runtime_replaces_code_dirs_and_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            source = Path(source_tmp)
            runtime = Path(runtime_tmp)
            (source / "python" / "bin").mkdir(parents=True)
            (source / "vendor").mkdir()
            (source / "static").mkdir()
            (source / "proxy.py").write_text("# new proxy\n")
            (source / "config.json").write_text('{"port": 8801}\n')
            (source / "python" / "bin" / "python3").write_text("new-python\n")
            (source / "vendor" / "pkg.txt").write_text("new-vendor\n")
            (source / "static" / "index.html").write_text("new-static\n")

            (runtime / "python" / "bin").mkdir(parents=True)
            (runtime / "vendor").mkdir()
            (runtime / "static").mkdir()
            (runtime / "accounts" / "a").mkdir(parents=True)
            (runtime / "config.json").write_text('{"port": 8800}\n')
            (runtime / "python" / "bin" / "python3").write_text("old-python\n")
            (runtime / "vendor" / "pkg.txt").write_text("old-vendor\n")
            (runtime / "static" / "index.html").write_text("old-static\n")
            (runtime / "accounts" / "a" / "auth.json").write_text("{}\n")

            with mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}), \
                    mock.patch.object(service_manager, "RUNTIME_DIR", runtime):
                service_manager._sync_runtime_dir()

            self.assertEqual((runtime / "python" / "bin" / "python3").read_text(), "new-python\n")
            self.assertEqual((runtime / "vendor" / "pkg.txt").read_text(), "new-vendor\n")
            self.assertEqual((runtime / "static" / "index.html").read_text(), "new-static\n")
            self.assertEqual((runtime / "config.json").read_text(), '{"port": 8800}\n')
            self.assertEqual((runtime / "accounts" / "a" / "auth.json").read_text(), "{}\n")


class TrashTests(unittest.TestCase):
    def test_trash_entry_parses_safe_name(self):
        item = proxy._trash_entry("account-a-20260515-120102")
        self.assertEqual(item["original_name"], "account-a")
        self.assertEqual(item["trashed_at"], "2026-05-15 12:01:02")

    def test_trash_entry_rejects_path_like_name(self):
        self.assertIsNone(proxy._trash_entry("../x-20260515-120102"))


class ProxyStatusTests(unittest.TestCase):
    def test_app_disables_request_body_auto_decompression(self):
        app = proxy.create_app()
        self.assertFalse(app._handler_args["auto_decompress"])

    def test_app_uses_configured_request_body_limit(self):
        with mock.patch("proxy.get", return_value=64):
            app = proxy.create_app()
        self.assertEqual(app._client_max_size, 64 * 1024 * 1024)

    def test_analytics_events_do_not_count_as_quota_request(self):
        self.assertFalse(proxy._is_potential_quota_request("/backend-api/codex/analytics-events/events"))
        self.assertTrue(proxy._is_known_background_request("/backend-api/codex/analytics-events/events"))

    def test_responses_path_counts_as_quota_request(self):
        self.assertTrue(proxy._is_potential_quota_request("/backend-api/codex/responses"))
        self.assertFalse(proxy._is_potential_quota_request("/backend-api/codex/sessions"))

    def test_quota_api_tolerates_partially_written_file(self):
        old_accounts_dir = proxy.ACCOUNTS_DIR
        old_accounts = proxy.pool.accounts
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_b = Account("b", root / "b" / "auth.json")
        (root / "a").mkdir(parents=True)
        (root / "b").mkdir(parents=True)
        (root / "a" / "quota.json").write_text("{")
        (root / "b" / "quota.json").write_text(json.dumps({
            "rate_limit": {
                "primary_window": {
                    "used_percent": 10,
                },
            },
        }))
        proxy.ACCOUNTS_DIR = root
        proxy.pool.accounts = [account_a, account_b]
        try:
            response = asyncio.run(proxy.api_quota(mock.Mock()))
            data = json.loads(response.text)
            self.assertEqual(data["a"]["error"], "quota_unavailable")
            self.assertEqual(data["b"]["rate_limit"]["primary_window"]["used_percent"], 10)
        finally:
            proxy.ACCOUNTS_DIR = old_accounts_dir
            proxy.pool.accounts = old_accounts

    def test_quota_refresh_api_fetches_fresh_data(self):
        async def fake_refresh(pool):
            return {"a": {"refreshed": True, "fetched_at": 123}}

        with mock.patch("proxy.refresh_quota_once", side_effect=fake_refresh) as refresh:
            response = asyncio.run(proxy.api_quota_refresh(mock.Mock()))
        data = json.loads(response.text)
        self.assertTrue(data["refreshed"])
        self.assertEqual(data["accounts"]["a"]["fetched_at"], 123)
        refresh.assert_called_once_with(proxy.pool)


class QuotaTrackerTests(unittest.TestCase):
    def test_refresh_once_writes_latest_usage_atomically(self):
        old_accounts_dir = quota_tracker.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        account = Account("a", root / "a" / "auth.json")
        account.enabled = True
        account.access_token = "token"
        pool = AccountPool()
        pool.accounts = [account]
        quota_tracker.ACCOUNTS_DIR = root
        try:
            async def fake_fetch(acct, session):
                return {
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 20,
                        },
                    },
                }

            with mock.patch("quota_tracker._fetch_usage", side_effect=fake_fetch):
                result = asyncio.run(quota_tracker.refresh_once(pool))
            quota_file = root / "a" / "quota.json"
            data = json.loads(quota_file.read_text())
            self.assertTrue(result["a"]["refreshed"])
            self.assertEqual(data["rate_limit"]["primary_window"]["used_percent"], 20)
            self.assertIn("_fetched_at", data)
            self.assertFalse((root / "a" / "quota.json.tmp").exists())
        finally:
            quota_tracker.ACCOUNTS_DIR = old_accounts_dir

    def test_refresh_once_runs_enabled_accounts_concurrently(self):
        old_accounts_dir = quota_tracker.ACCOUNTS_DIR
        root = Path(tempfile.mkdtemp())
        pool = AccountPool()
        for name in ("a", "b"):
            account = Account(name, root / name / "auth.json")
            account.enabled = True
            account.access_token = f"token-{name}"
            pool.accounts.append(account)
        active = 0
        peak = 0
        quota_tracker.ACCOUNTS_DIR = root
        try:
            async def fake_fetch(acct, session):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1
                return {
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 20,
                            "reset_at": 123,
                        },
                        "secondary_window": {
                            "used_percent": 30,
                            "reset_at": 456,
                        },
                    },
                }

            with mock.patch("quota_tracker._fetch_usage", side_effect=fake_fetch):
                result = asyncio.run(quota_tracker.refresh_once(pool))
            self.assertEqual(peak, 2)
            self.assertTrue(result["a"]["refreshed"])
            self.assertTrue(result["b"]["refreshed"])
        finally:
            quota_tracker.ACCOUNTS_DIR = old_accounts_dir

    def test_refresh_once_reports_timeout(self):
        root = Path(tempfile.mkdtemp())
        account = Account("a", root / "a" / "auth.json")
        account.enabled = True
        account.access_token = "token"
        pool = AccountPool()
        pool.accounts = [account]

        async def fake_fetch(acct, session):
            raise asyncio.TimeoutError()

        with mock.patch("quota_tracker._fetch_usage", side_effect=fake_fetch):
            result = asyncio.run(quota_tracker.refresh_once(pool))
        self.assertFalse(result["a"]["refreshed"])
        self.assertEqual(result["a"]["error"], "timeout")

    def test_fetch_usage_uses_chatgpt_web_headers_and_account_id(self):
        captured = {}

        class FakeResponse:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self):
                return {"rate_limit": {}}

        class FakeSession:
            def get(self, url, headers=None, timeout=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["timeout"] = timeout
                return FakeResponse()

        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "token"
        account.account_id = "account-123"

        data = asyncio.run(quota_tracker._fetch_usage(account, FakeSession()))

        self.assertEqual(data, {"rate_limit": {}})
        self.assertEqual(captured["url"], quota_tracker.USAGE_URL)
        self.assertEqual(captured["headers"]["Authorization"], "Bearer token")
        self.assertEqual(captured["headers"]["chatgpt-account-id"], "account-123")
        self.assertEqual(captured["headers"]["accept-encoding"], "identity")
        self.assertEqual(captured["headers"]["Origin"], "https://chatgpt.com")
        self.assertIn("Mozilla/5.0", captured["headers"]["User-Agent"])

    def test_refresh_once_reports_usage_http_status(self):
        root = Path(tempfile.mkdtemp())
        account = Account("a", root / "a" / "auth.json")
        account.enabled = True
        account.access_token = "token"
        pool = AccountPool()
        pool.accounts = [account]

        async def fake_fetch(acct, session):
            raise quota_tracker.UsageFetchError(403)

        with mock.patch("quota_tracker._fetch_usage", side_effect=fake_fetch):
            result = asyncio.run(quota_tracker.refresh_once(pool))
        self.assertFalse(result["a"]["refreshed"])
        self.assertEqual(result["a"]["error"], "usage_http_403")
        self.assertEqual(result["a"]["status"], 403)


class ProxyCoreTests(unittest.TestCase):
    def test_clean_headers_removes_accept_encoding(self):
        headers = _clean_headers({"Accept-Encoding": "gzip, zstd", "User-Agent": "x"})
        self.assertNotIn("Accept-Encoding", headers)
        self.assertEqual(headers["User-Agent"], "x")

    def test_clean_headers_removes_account_bound_headers(self):
        headers = _clean_headers({
            "Authorization": "Bearer current",
            "Cookie": "session=local",
            "OpenAI-Organization": "org-local",
            "ChatGPT-Account-ID": "account-local",
            "User-Agent": "x",
        })
        self.assertEqual(headers, {"User-Agent": "x"})

    def test_account_headers_use_selected_account_only(self):
        account = Account("picked", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "selected-token"
        account.account_id = "selected-account"

        headers = _account_headers({"User-Agent": "x"}, account, "/backend-api/codex/responses")

        self.assertEqual(headers["Authorization"], "Bearer selected-token")
        self.assertEqual(headers["chatgpt-account-id"], "selected-account")
        self.assertNotIn("authorization", headers)

    def test_backend_api_headers_are_chatgpt_web_compatible(self):
        account = Account("picked", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "selected-token"
        account.account_id = "selected-account"

        headers = _account_headers(
            {"User-Agent": "codex-cli", "Origin": "http://127.0.0.1:8800"},
            account,
            "/backend-api/codex/responses",
        )

        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertEqual(headers["Origin"], "https://chatgpt.com")
        self.assertEqual(headers["Referer"], "https://chatgpt.com/")
        self.assertEqual(headers["Sec-Fetch-Site"], "same-origin")
        self.assertEqual(headers["chatgpt-account-id"], "selected-account")

    def test_v1_headers_do_not_force_chatgpt_web_headers(self):
        account = Account("picked", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "selected-token"

        headers = _account_headers({"User-Agent": "codex-cli"}, account, "/v1/models")

        self.assertEqual(headers["User-Agent"], "codex-cli")
        self.assertNotIn("Origin", headers)

    def test_retry_after_seconds(self):
        self.assertEqual(_retry_after_seconds("42"), 42)
        self.assertEqual(_retry_after_seconds("99999"), 3600)
        self.assertIsNone(_retry_after_seconds("not-a-number"))

    def test_upstream_timeout_allows_long_streams(self):
        timeout = _upstream_timeout()
        self.assertIsNone(timeout.total)
        self.assertEqual(timeout.sock_connect, 10)

    def test_streaming_response_detection_uses_content_type(self):
        streaming = mock.Mock(headers={"Content-Type": "text/event-stream; charset=utf-8"})
        regular = mock.Mock(headers={"Content-Type": "application/json"})

        self.assertTrue(_is_streaming_response(streaming))
        self.assertFalse(_is_streaming_response(regular))

    def test_models_path_is_served_locally(self):
        self.assertTrue(_is_models_path("/v1/models"))
        self.assertTrue(_is_models_path("/v1/models/gpt-5.5"))
        self.assertFalse(_is_models_path("/v1/responses"))

    def test_openai_inference_path_is_blocked_for_chatgpt_tokens(self):
        self.assertTrue(_is_openai_inference_path("/v1/responses"))
        self.assertTrue(_is_openai_inference_path("/v1/chat/completions"))
        self.assertFalse(_is_openai_inference_path("/backend-api/codex/responses"))


class CodexConfigTests(unittest.TestCase):
    def test_read_values_handles_quoted_sections_without_leaking(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"
        config_path.write_text(
            'model_provider = "codex-account-pool"\n'
            "\n"
            '[plugins."documents@openai-primary-runtime"]\n'
            "enabled = true\n"
            "\n"
            "[model_providers.codex-account-pool]\n"
            'base_url = "http://127.0.0.1:8800/backend-api/codex"\n'
            'wire_api = "responses"\n'
        )

        values = codex_config._read_values(config_path)
        self.assertEqual(values["model_provider"], "codex-account-pool")
        self.assertTrue(values['plugins."documents@openai-primary-runtime".enabled'])
        self.assertEqual(values["model_providers.codex-account-pool.wire_api"], "responses")

    def test_proxy_toggle_round_trip(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"
        config_path.write_text(
            "model = 'x'\n"
            "[model_providers.openai]\n"
            'base_url = "http://old.example/v1"\n'
        )

        self.assertFalse(codex_config.status(config_path)["enabled"])
        codex_config.set_enabled(True, config_path)
        self.assertTrue(codex_config.status(config_path)["enabled"])
        text = config_path.read_text()
        self.assertIn('model_provider = "codex-account-pool"', text)
        self.assertIn('chatgpt_base_url = "http://127.0.0.1:8800/backend-api/"', text)
        self.assertIn('[model_providers.codex-account-pool]', text)
        self.assertIn('base_url = "http://127.0.0.1:8800/backend-api/codex"', text)
        self.assertIn('wire_api = "responses"', text)
        self.assertIn('requires_openai_auth = true', text)
        codex_config.set_enabled(False, config_path)
        self.assertFalse(codex_config.status(config_path)["enabled"])

    def test_ensure_enabled_does_not_rewrite_matching_config(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"

        first = codex_config.ensure_enabled(True, config_path)
        second = codex_config.ensure_enabled(True, config_path)

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertIsNone(second["backup_path"])


class ServiceManagerTests(unittest.TestCase):
    def test_source_dir_prefers_launchagent_environment(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(root)}):
            self.assertEqual(service_manager._source_dir(), root)

    def test_inside_launchagent_detects_service_name(self):
        with mock.patch.dict(os.environ, {"XPC_SERVICE_NAME": service_manager.LABEL}):
            self.assertTrue(service_manager._inside_launchagent())

    def test_sync_runtime_dir_uses_configured_source(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        (source / "proxy.py").write_text("from source")

        with mock.patch.object(service_manager, "RUNTIME_DIR", runtime), mock.patch.dict(
            os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}
        ):
            service_manager._sync_runtime_dir()

        self.assertEqual((runtime / "proxy.py").read_text(), "from source")

    def test_sync_runtime_dir_preserves_existing_config(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        (source / "config.json").write_text('{"port": 9999}\n')
        (runtime / "config.json").write_text('{"port": 8800}\n')

        with mock.patch.object(service_manager, "RUNTIME_DIR", runtime), mock.patch.dict(
            os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}
        ):
            service_manager._sync_runtime_dir()

        self.assertEqual((runtime / "config.json").read_text(), '{"port": 8800}\n')

    def test_app_bundle_dir_uses_environment(self):
        app = Path(tempfile.mkdtemp()) / "Codex Proxy Control.app"
        (app / "Contents").mkdir(parents=True)
        with mock.patch.dict(os.environ, {service_manager.APP_BUNDLE_ENV: str(app)}):
            self.assertEqual(service_manager._app_bundle_dir(), app)


if __name__ == "__main__":
    unittest.main()
