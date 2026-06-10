import json
import os
import plistlib
import sys
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "core"))
sys.path.insert(0, str(ROOT / "platforms" / "mac"))

import account_manager
import codex_cli
import codex_config
import login_manager
import control_actions
import proxy
import proxy_core
import quota_tracker
import service_manager
import usage_stats
from account_manager import Account, AccountNameError, AccountPool, validate_account_name
from config import ConfigError, validate
from proxy_core import (
    _CodexCompletionTracker,
    _RetryableStreamError,
    _WebSocketRelayResult,
    _can_retry_websocket_without_forwarding,
    _clear_ws_stream_interruption_cooldown,
    _connect_codex_upstream_websocket,
    _fetch_complete_codex_stream,
    _handle_codex_websocket,
    _account_headers,
    _clean_headers,
    _codex_stream_mode,
    _codex_stream_retry_cooldown,
    _extract_session_key,
    _is_streaming_response,
    _should_stream_response,
    _is_codex_compact_path,
    _is_models_path,
    _is_openai_inference_path,
    _is_codex_responses_path,
    _record_buffered_stream_interrupted,
    _record_client_disconnect,
    _record_stream_interrupted,
    _record_ws_stream_interrupted,
    _relay_realtime_stream,
    _relay_websocket_pair,
    _retry_after_seconds,
    _stream_error_detail,
    _target_url,
    _upstream_failure_response,
    _upstream_timeout,
    _websocket_heartbeat_seconds,
    _websocket_target_url,
)
from usage_stats import (
    extract_usage_from_json,
    extract_usage_from_sse_bytes,
    record_request_usage,
)

usage_stats.USAGE_STATS_FILE = Path(tempfile.mkdtemp()) / "usage_stats.json"


class ConfigTests(unittest.TestCase):
    def test_validate_accepts_supported_strategy_and_body_limit(self):
        cfg = validate({
            "rotation_strategy": "most_available",
            "max_request_body_mb": "128",
            "upstream_connect_timeout_sec": "12",
            "upstream_transient_retries": "3",
            "upstream_transient_backoff_ms": "500",
            "codex_stream_mode": "hybrid",
            "codex_stream_mode_user_set": "true",
            "codex_hybrid_probe_seconds": "8",
            "codex_hybrid_probe_bytes": "262144",
            "codex_stream_retry_cooldown": "60",
            "stream_keepalive_seconds": "15",
            "stream_bootstrap_retries": "1",
            "nonstream_keepalive_interval": "15",
            "websocket_heartbeat_seconds": "0",
            "session_affinity_enabled": "true",
            "session_affinity_ttl_seconds": "3600",
            "quota_tracker_enabled": "true",
            "quota_weight_5h": "0.8",
            "quota_weight_7d": "0.2",
        })
        self.assertEqual(cfg["rotation_strategy"], "most_available")
        self.assertEqual(cfg["max_request_body_mb"], 128)
        self.assertEqual(cfg["upstream_connect_timeout_sec"], 12)
        self.assertEqual(cfg["upstream_transient_retries"], 3)
        self.assertEqual(cfg["upstream_transient_backoff_ms"], 500)
        self.assertEqual(cfg["codex_stream_mode"], "hybrid")
        self.assertTrue(cfg["codex_stream_mode_user_set"])
        self.assertEqual(cfg["codex_hybrid_probe_seconds"], 8)
        self.assertEqual(cfg["codex_hybrid_probe_bytes"], 262144)
        self.assertEqual(cfg["codex_stream_retry_cooldown"], 60)
        self.assertEqual(cfg["stream_keepalive_seconds"], 15)
        self.assertEqual(cfg["stream_bootstrap_retries"], 1)
        self.assertEqual(cfg["nonstream_keepalive_interval"], 15)
        self.assertEqual(cfg["websocket_heartbeat_seconds"], 0)
        self.assertTrue(cfg["session_affinity_enabled"])
        self.assertEqual(cfg["session_affinity_ttl_seconds"], 3600)
        self.assertTrue(cfg["quota_tracker_enabled"])
        self.assertEqual(cfg["quota_weight_5h"], 0.8)
        self.assertEqual(cfg["quota_weight_7d"], 0.2)

    def test_validate_defaults_to_even_quota_weights(self):
        cfg = validate({})
        self.assertEqual(cfg["quota_weight_5h"], 0.5)
        self.assertEqual(cfg["quota_weight_7d"], 0.5)

    def test_validate_migrates_implicit_hybrid_to_realtime(self):
        cfg = validate({"codex_stream_mode": "hybrid"})
        self.assertEqual(cfg["codex_stream_mode"], "realtime")
        self.assertFalse(cfg["codex_stream_mode_user_set"])

    def test_validate_preserves_explicit_hybrid(self):
        cfg = validate({"codex_stream_mode": "hybrid", "codex_stream_mode_user_set": True})
        self.assertEqual(cfg["codex_stream_mode"], "hybrid")

    def test_validate_rejects_invalid_quota_tracker_flag(self):
        with self.assertRaises(ConfigError):
            validate({"quota_tracker_enabled": "maybe"})

    def test_validate_rejects_unknown_strategy(self):
        with self.assertRaises(ConfigError):
            validate({"rotation_strategy": "least_used"})

    def test_validate_rejects_unknown_codex_stream_mode(self):
        with self.assertRaises(ConfigError):
            validate({"codex_stream_mode": "sometimes"})

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


class UsageStatsTests(unittest.TestCase):
    def test_extract_usage_from_nested_json(self):
        payload = {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 8,
                    "total_tokens": 20,
                }
            },
        }

        usage = extract_usage_from_json(payload)

        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 8)
        self.assertEqual(usage["total_tokens"], 20)

    def test_extract_usage_from_sse_uses_largest_total(self):
        body = (
            b"data: {\"usage\":{\"input_tokens\":1,\"output_tokens\":2,\"total_tokens\":3}}\n\n"
            b"data: {\"response\":{\"usage\":{\"input_tokens\":10,\"output_tokens\":5,\"total_tokens\":15}}}\n\n"
        )

        usage = extract_usage_from_sse_bytes(body)

        self.assertEqual(usage["total_tokens"], 15)

    def test_record_request_usage_summarizes_daily_weekly_and_dedupes(self):
        stats_file = Path(tempfile.mkdtemp()) / "usage_stats.json"
        with mock.patch.object(usage_stats, "USAGE_STATS_FILE", stats_file):
            record_request_usage(
                request_id="req-1",
                account="a",
                path="/backend-api/codex/responses",
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
            record_request_usage(
                request_id="req-1",
                account="a",
                path="/backend-api/codex/responses",
                usage={"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998},
            )
            record_request_usage(
                request_id="req-2",
                account="a",
                path="/backend-api/codex/responses",
                usage=None,
            )
            summary = usage_stats.summary()

        self.assertEqual(len(summary["daily"]), 31)
        self.assertEqual(len(summary["weekly"]), 53)
        self.assertEqual(summary["total"]["total_tokens"], 15)
        self.assertEqual(summary["total"]["requests"], 2)
        self.assertEqual(summary["total"]["unknown_requests"], 1)
        self.assertTrue(any(day["total_tokens"] == 15 for day in summary["daily"]))

    def test_token_usage_api_returns_summary(self):
        stats_file = Path(tempfile.mkdtemp()) / "usage_stats.json"
        with mock.patch.object(usage_stats, "USAGE_STATS_FILE", stats_file):
            record_request_usage(
                request_id="req-api",
                account="a",
                path="/v1/responses",
                usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            )
            response = asyncio.run(proxy.api_token_usage(mock.Mock()))
            data = json.loads(response.text)

        self.assertEqual(data["total"]["total_tokens"], 5)
        self.assertEqual(len(data["daily"]), 31)
        self.assertEqual(len(data["weekly"]), 53)


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

    def test_wait_for_proxy_waits_for_expected_version(self):
        with mock.patch("control_actions.proxy_status", side_effect=[
            {"running": True, "version": "0.5.2"},
            {"running": True, "version": "0.5.3"},
        ]) as proxy_status, mock.patch("control_actions.time.sleep"):
            result = control_actions.wait_for_proxy(timeout=3, expected_version="0.5.3")

        self.assertEqual(result["version"], "0.5.3")
        self.assertEqual(proxy_status.call_count, 2)

    def test_repair_syncs_when_old_proxy_version_is_online(self):
        old_service = {
            "installed": False,
            "loaded": False,
            "needs_repair": True,
            "version_mismatch": True,
            "migration_required": True,
            "legacy_running": True,
            "expected_version": "0.6.0",
            "running_version": "0.5.4",
            "source_dir": "/source",
            "runtime_dir": "/runtime",
        }
        new_service = {
            "installed": True,
            "loaded": True,
            "needs_repair": False,
            "version_mismatch": False,
            "migration_required": False,
            "legacy_running": False,
            "expected_version": "0.6.0",
            "running_version": "0.6.0",
            "source_dir": "/source",
            "runtime_dir": "/runtime",
            "restart_required": False,
        }
        with mock.patch("control_actions.proxy_status", return_value={"running": True, "version": "0.5.4"}), \
                mock.patch("control_actions.service_manager.status", return_value=old_service), \
                mock.patch("control_actions.service_manager.install", return_value=new_service) as install, \
                mock.patch("control_actions.service_manager.restart", return_value=True), \
                mock.patch("control_actions.wait_for_proxy", return_value={
                    "running": True,
                    "version": "0.6.0",
                    "active_accounts": 1,
                    "total_accounts": 1,
                }), \
                mock.patch("control_actions.codex_config.ensure_enabled", return_value={
                    "enabled": True,
                    "mode": "codex_pool_provider",
                }), \
                mock.patch("control_actions.codex_dependency_status", return_value={}), \
                mock.patch("control_actions.runtime_status", return_value={}):
            result = control_actions.repair()

        self.assertEqual(result["action"], "started_or_repaired")
        self.assertEqual(result["previous_version"], "0.5.4")
        self.assertEqual(result["expected_version"], "0.6.0")
        self.assertTrue(result["updated"])
        install.assert_called_once_with(sync=True)

    def test_repair_returns_already_running_only_when_service_matches_app(self):
        service = {
            "installed": True,
            "loaded": True,
            "needs_repair": False,
            "version_mismatch": False,
            "migration_required": False,
            "legacy_running": False,
            "expected_version": "0.6.0",
            "source_dir": "/source",
            "runtime_dir": "/runtime",
        }
        with mock.patch("control_actions.proxy_status", return_value={
            "running": True,
            "version": "0.6.0",
            "active_accounts": 2,
            "total_accounts": 2,
        }), mock.patch("control_actions.service_manager.status", return_value=service), \
                mock.patch("control_actions.service_manager.install") as install, \
                mock.patch("control_actions.codex_config.ensure_enabled", return_value={
                    "enabled": True,
                    "mode": "codex_pool_provider",
                }), \
                mock.patch("control_actions.codex_dependency_status", return_value={}), \
                mock.patch("control_actions.runtime_status", return_value={}):
            result = control_actions.repair()

        self.assertEqual(result["action"], "already_running")
        self.assertFalse(result["updated"])
        self.assertEqual(result["version"], "0.6.0")
        install.assert_not_called()

    def test_apply_update_returns_busy_when_lock_exists(self):
        with mock.patch("control_actions._acquire_update_lock", return_value=None):
            result = control_actions.apply_update()

        self.assertFalse(result["updated"])
        self.assertFalse(result["rolled_back"])
        self.assertEqual(result["error"], "update already in progress")

    def test_apply_update_rolls_back_when_expected_version_never_starts(self):
        backup = Path(tempfile.mkdtemp()) / "backup"
        backup.mkdir()
        lock = Path(tempfile.mkdtemp()) / "lock"
        lock.mkdir()
        service = {
            "installed": True,
            "loaded": True,
            "needs_repair": False,
            "restart_required": False,
            "source_dir": "/source",
            "runtime_dir": "/runtime",
            "sync": {"backup_path": str(backup)},
        }
        with mock.patch("control_actions._acquire_update_lock", return_value=lock), \
                mock.patch("control_actions.proxy_status", return_value={"version": "0.5.3"}), \
                mock.patch("control_actions.source_app_version", return_value="0.5.4"), \
                mock.patch("control_actions.service_manager.install", return_value=service), \
                mock.patch("control_actions.service_manager.restart", return_value=True), \
                mock.patch("control_actions.wait_for_proxy", return_value=None), \
                mock.patch("control_actions.service_manager.rollback_runtime", return_value={"rolled_back": True}) as rollback:
            result = control_actions.apply_update()

        self.assertFalse(result["updated"])
        self.assertTrue(result["rolled_back"])
        self.assertEqual(result["previous_version"], "0.5.3")
        self.assertEqual(result["expected_version"], "0.5.4")
        self.assertEqual(result["backup_path"], str(backup))
        self.assertIn("expected version 0.5.4", result["error"])
        rollback.assert_called_once_with(str(backup))

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


class ServiceManagerRuntimeTests(unittest.TestCase):
    def _write_minimal_runtime_source(self, source: Path) -> None:
        for name in ("account_manager.py", "config.py", "proxy.py", "proxy_core.py", "service_manager.py"):
            (source / name).write_text(f"# {name}\n")
        (source / "static").mkdir(exist_ok=True)
        (source / "static" / "index.html").write_text("static\n")

    def test_migrate_legacy_runtime_copies_without_removing_old_data(self):
        with tempfile.TemporaryDirectory() as old_tmp, tempfile.TemporaryDirectory() as parent_tmp:
            old_runtime = Path(old_tmp)
            new_runtime = Path(parent_tmp) / "xiaolachang"
            (old_runtime / "accounts" / "a").mkdir(parents=True)
            (old_runtime / "accounts" / "a" / "auth.json").write_text("{}\n")
            with mock.patch.object(service_manager, "OLD_RUNTIME_DIR", old_runtime), \
                    mock.patch.object(service_manager, "RUNTIME_DIR", new_runtime):
                service_manager._migrate_legacy_runtime()

            self.assertTrue((new_runtime / "accounts" / "a" / "auth.json").exists())
            self.assertTrue((old_runtime / "accounts" / "a" / "auth.json").exists())

    def test_sync_runtime_replaces_code_dirs_and_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            source = Path(source_tmp)
            runtime = Path(runtime_tmp)
            (source / "python" / "bin").mkdir(parents=True)
            (source / "vendor").mkdir()
            (source / "static").mkdir()
            (source / "proxy.py").write_text("# new proxy\n")
            (source / "config.json").write_text('{"port": 8801}\n')
            for name in ("account_manager.py", "config.py", "proxy_core.py", "service_manager.py"):
                (source / name).write_text(f"# new {name}\n")
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

    def test_sync_runtime_staging_failure_preserves_existing_runtime(self):
        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            source = Path(source_tmp)
            runtime = Path(runtime_tmp)
            (source / "config.json").write_text('{"port": 9999}\n')
            (runtime / "proxy.py").write_text("# old proxy\n")
            (runtime / "static").mkdir()
            (runtime / "static" / "index.html").write_text("old-static\n")

            with mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}), \
                    mock.patch.object(service_manager, "RUNTIME_DIR", runtime):
                with self.assertRaises(service_manager.RuntimeSyncError):
                    service_manager._sync_runtime_dir()

            self.assertEqual((runtime / "proxy.py").read_text(), "# old proxy\n")
            self.assertEqual((runtime / "static" / "index.html").read_text(), "old-static\n")

    def test_sync_runtime_copy_failure_rolls_back_code_and_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as source_tmp, tempfile.TemporaryDirectory() as runtime_tmp:
            source = Path(source_tmp)
            runtime = Path(runtime_tmp)
            for name in ("account_manager.py", "config.py", "proxy.py", "proxy_core.py", "service_manager.py"):
                (source / name).write_text(f"# new {name}\n")
                (runtime / name).write_text(f"# old {name}\n")
            (source / "config.json").write_text('{"port": 9999}\n')
            (runtime / "config.json").write_text('{"port": 8800}\n')
            for dirname in ("python", "static", "vendor"):
                (source / dirname).mkdir()
                (runtime / dirname).mkdir()
                (source / dirname / "marker.txt").write_text(f"new-{dirname}\n")
                (runtime / dirname / "marker.txt").write_text(f"old-{dirname}\n")
            (runtime / "accounts" / "a").mkdir(parents=True)
            (runtime / "accounts" / "a" / "auth.json").write_text("{}\n")

            original_copy = service_manager._copy_staged_entry

            def flaky_copy(src, dst):
                if src.name == "vendor" and "update-staging" in str(src):
                    raise OSError("copy vendor failed")
                original_copy(src, dst)

            with mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}), \
                    mock.patch.object(service_manager, "RUNTIME_DIR", runtime), \
                    mock.patch.object(service_manager, "_copy_staged_entry", side_effect=flaky_copy):
                with self.assertRaises(service_manager.RuntimeSyncError) as raised:
                    service_manager._sync_runtime_dir()

            self.assertTrue(raised.exception.restored)
            self.assertEqual((runtime / "proxy.py").read_text(), "# old proxy.py\n")
            self.assertEqual((runtime / "python" / "marker.txt").read_text(), "old-python\n")
            self.assertEqual((runtime / "static" / "marker.txt").read_text(), "old-static\n")
            self.assertEqual((runtime / "vendor" / "marker.txt").read_text(), "old-vendor\n")
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


class _FakeChunkContent:
    def __init__(self, chunks, error=None):
        self.chunks = list(chunks)
        self.error = error
        self.index = 0

    def iter_chunks(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index < len(self.chunks):
            chunk = self.chunks[self.index]
            self.index += 1
            return chunk, False
        if self.error:
            error = self.error
            self.error = None
            raise error
        raise StopAsyncIteration


class _DelayedChunkContent:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.index = 0

    def iter_chunks(self):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        delay, chunk = self.chunks[self.index]
        self.index += 1
        await asyncio.sleep(delay)
        return chunk, False


class _FakeUpstreamResponse:
    def __init__(self, chunks, error=None):
        self.content = _FakeChunkContent(chunks, error)


class _DelayedHTTPUpstreamResponse:
    def __init__(self, chunks, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {"Content-Type": "text/event-stream"}
        self.content = _DelayedChunkContent(chunks)


class _FakeStreamResponse:
    last = None

    def __init__(self, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self.writes = []
        self.prepared = False
        self.eof = False
        _FakeStreamResponse.last = self

    async def prepare(self, request):
        self.prepared = True
        return self

    async def write(self, chunk):
        self.writes.append(chunk)

    async def drain(self):
        pass

    async def write_eof(self):
        self.eof = True


class _FakeHTTPUpstreamResponse:
    def __init__(self, chunks, *, status=200, headers=None, error=None):
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.content = _FakeChunkContent(chunks, error)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        body = []
        async for chunk, _ in self.content.iter_chunks():
            body.append(chunk)
        return b"".join(body)


class _FakeHTTPSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class _FakeRequest:
    def __init__(
        self,
        headers=None,
        query_string="",
        order=None,
        path="/v1/responses",
        method="POST",
        body=b"",
    ):
        self.headers = headers or {}
        self.query_string = query_string
        self.order = order
        self.path = path
        self.method = method
        self.content_length = len(body)
        self._body = body

    async def read(self):
        return self._body


class _FakeWebSocket:
    def __init__(self, messages=None, close_code=None, error=None, order=None, prepare_error=None):
        self.messages = list(messages or [])
        self.close_code = close_code
        self.error = error
        self.headers = {}
        self.sent = []
        self.closed = False
        self.index = 0
        self.order = order
        self.prepare_error = prepare_error
        self.prepared = False
        self.close_args = None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index < len(self.messages):
            msg = self.messages[self.index]
            self.index += 1
            return msg
        raise StopAsyncIteration

    async def send_str(self, data):
        self.sent.append(("text", data))

    async def send_bytes(self, data):
        self.sent.append(("binary", data))

    async def close(self, *args, **kwargs):
        self.closed = True
        self.close_args = (args, kwargs)

    async def prepare(self, request):
        if self.order is not None:
            self.order.append("prepare")
        if self.prepare_error:
            raise self.prepare_error
        self.prepared = True
        return self

    def exception(self):
        return self.error


class _FakeWSSession:
    def __init__(self, outcomes, order=None):
        self.outcomes = list(outcomes)
        self.calls = []
        self.order = order

    async def ws_connect(self, url, **kwargs):
        if self.order is not None:
            self.order.append("connect")
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ProxyCoreRoutingTests(unittest.TestCase):
    def test_codex_responses_2xx_streams_even_with_json_content_type(self):
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}

        self.assertTrue(_should_stream_response("/backend-api/codex/responses", response))

    def test_v1_responses_maps_to_chatgpt_codex_upstream(self):
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}

        self.assertTrue(_is_codex_responses_path("/v1/responses"))
        self.assertTrue(_should_stream_response("/v1/responses", response))
        self.assertEqual(
            _target_url("https://chatgpt.com", "/v1/responses", "foo=bar"),
            "https://chatgpt.com/backend-api/codex/responses?foo=bar",
        )
        self.assertEqual(
            _websocket_target_url("/v1/responses"),
            "wss://chatgpt.com/backend-api/codex/responses",
        )

    def test_compact_responses_maps_to_chatgpt_codex_upstream(self):
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}

        self.assertTrue(_is_codex_compact_path("/v1/responses/compact"))
        self.assertTrue(_is_codex_compact_path("/backend-api/codex/responses/compact"))
        self.assertTrue(_should_stream_response("/v1/responses/compact", response))
        self.assertEqual(
            _target_url("https://chatgpt.com", "/v1/responses/compact", "foo=bar"),
            "https://chatgpt.com/backend-api/codex/responses/compact?foo=bar",
        )

    def test_non_codex_json_response_does_not_force_streaming(self):
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "application/json"}

        self.assertFalse(_should_stream_response("/backend-api/wham/apps", response))

    def test_sse_response_still_streams_on_background_paths(self):
        response = mock.Mock()
        response.status = 200
        response.headers = {"Content-Type": "text/event-stream; charset=utf-8"}

        self.assertTrue(_should_stream_response("/backend-api/wham/apps", response))

    def test_upstream_failure_response_includes_attempt_diagnostics(self):
        response = _upstream_failure_response(
            "rid123",
            "/backend-api/codex/responses",
            [
                {
                    "account": "a",
                    "reason": "upstream_error",
                    "error": "Connection timeout",
                    "retry_index": 0,
                },
                {
                    "account": "b",
                    "reason": "rate_limit_429",
                    "status": 429,
                    "retry_index": 1,
                },
            ],
        )
        data = json.loads(response.text)

        self.assertEqual(response.status, 502)
        self.assertEqual(data["request_id"], "rid123")
        self.assertEqual(data["path"], "/backend-api/codex/responses")
        self.assertEqual(data["attempted_accounts"][0]["account"], "a")
        self.assertEqual(data["attempted_accounts"][1]["reason"], "rate_limit_429")
        self.assertEqual(data["last_error"], "rate_limit_429:429")


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

    def test_v1_responses_headers_are_chatgpt_web_compatible(self):
        account = Account("picked", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "selected-token"
        account.account_id = "selected-account"

        headers = _account_headers({"User-Agent": "codex-cli"}, account, "/v1/responses")

        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertEqual(headers["Origin"], "https://chatgpt.com")
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

    def test_codex_completion_tracker_detects_single_chunk_marker(self):
        tracker = _CodexCompletionTracker()

        self.assertTrue(tracker.feed(b'event: response.completed\ndata: {}\n\n'))
        self.assertTrue(tracker.completed)

    def test_codex_completion_tracker_detects_split_marker(self):
        tracker = _CodexCompletionTracker()

        self.assertFalse(tracker.feed(b"event: response.comp"))
        self.assertTrue(tracker.feed(b"leted\ndata: {}\n\n"))
        self.assertTrue(tracker.completed)

    def test_codex_completion_tracker_reports_missing_marker(self):
        tracker = _CodexCompletionTracker()

        tracker.feed(b"event: response.output_text.delta\n")
        tracker.feed(b"data: partial\n\n")

        self.assertFalse(tracker.completed)

    def test_stream_interruption_records_error_and_cools_account(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")

        _record_stream_interrupted(
            pool,
            account,
            "/backend-api/codex/responses",
            "rid-stream",
            0,
            "Response payload is not completed",
            128,
            False,
            60,
        )

        self.assertTrue(account.is_rate_limited)
        self.assertEqual(account.cooldown_reason, "stream_interrupted")
        self.assertIn("bytes_forwarded=128", pool.recent_errors[0]["error"])
        self.assertIn("response_completed=False", pool.recent_errors[0]["error"])

    def test_client_disconnect_records_error_without_cooldown(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")

        _record_client_disconnect(
            pool,
            account,
            "/backend-api/codex/responses",
            "rid-client",
            0,
            "Cannot write to closing transport",
            256,
            True,
        )

        self.assertFalse(account.is_rate_limited)
        self.assertEqual(account.cooldown_reason, "")
        self.assertIn("client_disconnected", pool.recent_errors[0]["error"])
        self.assertIn("bytes_forwarded=256", pool.recent_errors[0]["error"])

    def test_stream_error_detail_includes_completion_diagnostics(self):
        detail = _stream_error_detail(
            "stream_interrupted",
            "Not enough data to satisfy transfer length header",
            42,
            False,
        )

        self.assertIn("bytes_forwarded=42", detail)
        self.assertIn("response_completed=False", detail)

    def test_models_path_is_served_locally(self):
        self.assertTrue(_is_models_path("/v1/models"))
        self.assertTrue(_is_models_path("/v1/models/gpt-5.5"))
        self.assertFalse(_is_models_path("/v1/responses"))

    def test_openai_inference_path_is_blocked_for_chatgpt_tokens(self):
        self.assertFalse(_is_openai_inference_path("/v1/responses"))
        self.assertTrue(_is_openai_inference_path("/v1/chat/completions"))
        self.assertFalse(_is_openai_inference_path("/backend-api/codex/responses"))

    def test_record_request_keeps_stream_mode(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")

        pool.record_request(
            account,
            "/backend-api/codex/responses",
            200,
            12.3,
            1,
            "rid-mode",
            "hybrid-buffered",
            "http-hybrid",
        )

        self.assertEqual(pool.recent_requests[0]["stream_mode"], "hybrid-buffered")
        self.assertEqual(pool.recent_requests[0]["transport"], "http-hybrid")

    def test_codex_stream_mode_defaults_invalid_values_to_realtime(self):
        with mock.patch("proxy_core.get", return_value="sometimes"):
            self.assertEqual(_codex_stream_mode(), "realtime")

    def test_codex_stream_retry_cooldown_falls_back_to_rate_limit(self):
        def fake_get(key):
            return {
                "codex_stream_retry_cooldown": 0,
                "rate_limit_cooldown": 77,
            }.get(key)

        with mock.patch("proxy_core.get", side_effect=fake_get):
            self.assertEqual(_codex_stream_retry_cooldown(), 77)

    def test_websocket_heartbeat_defaults_to_none(self):
        with mock.patch("proxy_core.get", return_value=0):
            self.assertIsNone(_websocket_heartbeat_seconds())

    def test_websocket_heartbeat_uses_configured_seconds(self):
        with mock.patch("proxy_core.get", return_value=45):
            self.assertEqual(_websocket_heartbeat_seconds(), 45)

    def test_extract_session_key_prefers_headers_then_body(self):
        self.assertEqual(
            _extract_session_key({"Session_id": "header-session"}, b'{"previous_response_id":"body"}'),
            "header-session",
        )
        self.assertEqual(
            _extract_session_key({}, b'{"metadata":{"user_id":"meta-user"}}'),
            "meta-user",
        )
        self.assertEqual(
            _extract_session_key({}, b'{"previous_response_id":"resp_123"}'),
            "resp_123",
        )

    def test_session_affinity_reuses_bound_account_and_switches_on_cooldown(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]

        def fake_get(key):
            return {
                "session_affinity_enabled": True,
                "session_affinity_ttl_seconds": 3600,
                "rotation_strategy": "round_robin",
            }.get(key)

        with mock.patch("account_manager.get", side_effect=fake_get):
            first, first_hit = pool.pick_for_session("session-1")
            pool.bind_session("session-1", first)
            second, second_hit = pool.pick_for_session("session-1")
            pool.mark_rate_limited(first, 60, "test")
            third, third_hit = pool.pick_for_session("session-1")

        self.assertEqual(first.name, "a")
        self.assertFalse(first_hit)
        self.assertEqual(second.name, "a")
        self.assertTrue(second_hit)
        self.assertEqual(third.name, "b")
        self.assertFalse(third_hit)

    def test_fetch_complete_codex_stream_buffers_completed_response(self):
        response = _FakeUpstreamResponse([
            b"event: response.output_text.delta\ndata: x\n\n",
            b"event: response.completed\ndata: {}\n\n",
        ])

        result = asyncio.run(_fetch_complete_codex_stream(response, "buffered"))

        self.assertTrue(result.completed)
        self.assertEqual(result.stream_mode, "buffered")
        self.assertIn(b"response.completed", result.body)
        self.assertEqual(result.bytes_read, len(result.body))

    def test_realtime_stream_sends_keepalive_without_canceling_upstream_read(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        response = _DelayedHTTPUpstreamResponse([
            (0.02, b"event: response.completed\ndata: {}\n\n"),
        ])

        with mock.patch("proxy_core.web.StreamResponse", _FakeStreamResponse), \
                mock.patch("proxy_core._stream_keepalive_seconds", return_value=0.01):
            result = asyncio.run(_relay_realtime_stream(
                _FakeRequest(),
                pool,
                account,
                "/v1/responses",
                "rid-keepalive",
                0,
                response,
                time.monotonic(),
                "realtime",
                "http-realtime",
                True,
                60,
            ))

        self.assertIs(result, _FakeStreamResponse.last)
        self.assertIn(b": keep-alive\n\n", result.writes)
        self.assertIn(b"response.completed", b"".join(result.writes))
        self.assertEqual(pool.recent_requests[0]["stream_keepalive_count"], 1)
        self.assertEqual(pool.recent_requests[0]["stream_mode"], "realtime")

    def test_realtime_stream_bootstrap_failure_retries_next_account(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]
        session = _FakeHTTPSession([
            _FakeHTTPUpstreamResponse([], headers={"Content-Type": "text/event-stream"}),
            _FakeHTTPUpstreamResponse([
                b"event: response.completed\ndata: {}\n\n",
            ], headers={"Content-Type": "text/event-stream"}),
        ])

        def fake_get(key):
            return {
                "codex_stream_mode": "realtime",
                "stream_bootstrap_retries": 1,
                "stream_keepalive_seconds": 0,
                "codex_stream_retry_cooldown": 0,
                "rate_limit_cooldown": 60,
                "max_retries": 10,
                "max_request_body_mb": 512,
                "rotation_strategy": "round_robin",
                "upstream_transient_retries": 0,
                "session_affinity_enabled": True,
                "session_affinity_ttl_seconds": 3600,
            }.get(key)

        with mock.patch("proxy_core.web.StreamResponse", _FakeStreamResponse), \
                mock.patch("proxy_core.get", side_effect=fake_get), \
                mock.patch("account_manager.get", side_effect=fake_get):
            response = asyncio.run(proxy_core._handle_with_session(
                _FakeRequest(path="/v1/responses"),
                pool,
                session,
            ))

        self.assertIs(response, _FakeStreamResponse.last)
        self.assertEqual(pool.recent_requests[0]["account"], "b")
        self.assertEqual(len(session.calls), 2)
        self.assertIn("stream_interrupted_before_response", pool.recent_errors[0]["error"])

    def test_fetch_complete_codex_stream_detects_split_completion_marker(self):
        response = _FakeUpstreamResponse([
            b"event: response.comp",
            b"leted\ndata: {}\n\n",
        ])

        result = asyncio.run(_fetch_complete_codex_stream(response, "buffered"))

        self.assertTrue(result.completed)
        self.assertIn(b"response.completed", result.body)

    def test_fetch_complete_codex_stream_raises_without_completion(self):
        response = _FakeUpstreamResponse([
            b"event: response.output_text.delta\ndata: partial\n\n",
        ])

        with self.assertRaises(_RetryableStreamError) as exc:
            asyncio.run(_fetch_complete_codex_stream(response, "buffered"))

        self.assertGreater(exc.exception.bytes_read, 0)
        self.assertFalse(exc.exception.completed)

    def test_fetch_complete_codex_stream_allows_compact_without_completion_marker(self):
        response = _FakeUpstreamResponse([
            b'{"summary":"partial compact result"}\n',
        ])

        result = asyncio.run(_fetch_complete_codex_stream(
            response,
            "hybrid",
            require_completion=False,
        ))

        self.assertFalse(result.completed)
        self.assertEqual(result.stream_mode, "hybrid-compact")
        self.assertIn(b"partial compact result", result.body)

    def test_fetch_complete_codex_stream_still_raises_compact_payload_error(self):
        response = _FakeUpstreamResponse(
            [b'{"summary":"partial'],
            error=aiohttp.ClientPayloadError("not enough data"),
        )

        with self.assertRaises(_RetryableStreamError) as exc:
            asyncio.run(_fetch_complete_codex_stream(
                response,
                "hybrid",
                require_completion=False,
            ))

        self.assertGreater(exc.exception.bytes_read, 0)
        self.assertFalse(exc.exception.completed)

    def test_fetch_complete_codex_stream_raises_on_payload_error(self):
        response = _FakeUpstreamResponse(
            [b"event: response.output_text.delta\ndata: partial\n\n"],
            error=aiohttp.ClientPayloadError("not enough data"),
        )

        with self.assertRaises(_RetryableStreamError) as exc:
            asyncio.run(_fetch_complete_codex_stream(response, "buffered"))

        self.assertGreater(exc.exception.bytes_read, 0)
        self.assertFalse(exc.exception.completed)

    def test_fetch_complete_codex_stream_marks_hybrid_buffered_after_probe(self):
        def fake_get(key):
            return {
                "codex_hybrid_probe_seconds": 8,
                "codex_hybrid_probe_bytes": 4,
            }.get(key)

        response = _FakeUpstreamResponse([
            b"12345",
            b"event: response.completed\ndata: {}\n\n",
        ])

        with mock.patch("proxy_core.get", side_effect=fake_get):
            result = asyncio.run(_fetch_complete_codex_stream(response, "hybrid"))

        self.assertEqual(result.stream_mode, "hybrid-buffered")

    def test_fetch_complete_codex_stream_marks_short_hybrid_probe_complete(self):
        def fake_get(key):
            return {
                "codex_hybrid_probe_seconds": 120,
                "codex_hybrid_probe_bytes": 1024,
            }.get(key)

        response = _FakeUpstreamResponse([
            b"event: response.completed\ndata: {}\n\n",
        ])

        with mock.patch("proxy_core.get", side_effect=fake_get):
            result = asyncio.run(_fetch_complete_codex_stream(response, "hybrid"))

        self.assertEqual(result.stream_mode, "hybrid-probe-complete")

    def test_buffered_stream_interruption_records_error_and_cools_account(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        error = _RetryableStreamError("stream closed", bytes_read=512, completed=False)

        _record_buffered_stream_interrupted(
            pool,
            account,
            "/backend-api/codex/responses",
            "rid-buffered",
            2,
            error,
            "hybrid",
            60,
        )

        self.assertTrue(account.is_rate_limited)
        self.assertEqual(account.cooldown_reason, "stream_interrupted")
        self.assertIn("bytes_read=512", pool.recent_errors[0]["error"])
        self.assertIn("stream_mode=hybrid", pool.recent_errors[0]["error"])

    def test_compact_request_without_completion_marker_records_success_without_cooldown(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "token-a"
        pool.accounts = [account]
        session = _FakeHTTPSession([
            _FakeHTTPUpstreamResponse([b'{"summary":"ok"}\n'])
        ])
        request = _FakeRequest(
            path="/v1/responses/compact",
            headers={"x-request-id": "rid-compact"},
        )

        original_get = proxy_core.get

        def fake_get(key):
            if key == "codex_stream_mode":
                return "hybrid"
            if key == "codex_stream_retry_cooldown":
                return 0
            if key == "rate_limit_cooldown":
                return 60
            return original_get(key)

        with mock.patch("proxy_core.get", side_effect=fake_get):
            response = asyncio.run(proxy_core._handle_with_session(request, pool, session))

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body, b'{"summary":"ok"}\n')
        self.assertFalse(account.is_rate_limited)
        self.assertEqual(len(pool.recent_errors), 0)
        self.assertEqual(pool.recent_requests[0]["path"], "/v1/responses/compact")
        self.assertEqual(pool.recent_requests[0]["stream_mode"], "hybrid-compact")
        self.assertEqual(
            session.calls[0][1],
            "https://chatgpt.com/backend-api/codex/responses/compact",
        )

    def test_websocket_handshake_429_cools_and_switches_account(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]
        handshake_429 = aiohttp.WSServerHandshakeError(
            None,
            (),
            status=429,
            message="Too Many Requests",
            headers={"Retry-After": "12"},
        )
        upstream_ws = _FakeWebSocket()
        session = _FakeWSSession([handshake_429, upstream_ws])

        connected, attempts, failure = asyncio.run(_connect_codex_upstream_websocket(
            _FakeRequest(headers={"Sec-WebSocket-Protocol": "chatgpt"}),
            pool,
            session,
            "rid-ws",
            "/v1/responses",
        ))

        self.assertIsNone(failure)
        self.assertEqual(connected.account.name, "b")
        self.assertTrue(account_a.is_rate_limited)
        self.assertEqual(account_a.cooldown_reason, "rate_limit_429")
        self.assertEqual(attempts[0]["reason"], "rate_limit_429")
        self.assertEqual(session.calls[0][0], "wss://chatgpt.com/backend-api/codex/responses")
        self.assertEqual(session.calls[0][1]["protocols"], ["chatgpt"])
        self.assertIsNone(session.calls[0][1]["heartbeat"])

    def test_websocket_handshake_401_refreshes_same_account(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "old-token"
        pool.accounts = [account]

        async def fake_refresh():
            account.access_token = "new-token"
            return True

        account.refresh = fake_refresh
        handshake_401 = aiohttp.WSServerHandshakeError(
            None,
            (),
            status=401,
            message="Unauthorized",
            headers={},
        )
        upstream_ws = _FakeWebSocket()
        session = _FakeWSSession([handshake_401, upstream_ws])

        connected, attempts, failure = asyncio.run(_connect_codex_upstream_websocket(
            _FakeRequest(),
            pool,
            session,
            "rid-auth",
            "/v1/responses",
        ))

        self.assertIsNone(failure)
        self.assertEqual(connected.account.name, "a")
        self.assertEqual(attempts, [])
        self.assertFalse(account.is_rate_limited)
        self.assertEqual(session.calls[1][1]["headers"]["Authorization"], "Bearer new-token")

    def test_websocket_relay_replays_cached_frames_to_upstream(self):
        upstream_ws = _FakeWebSocket([
            aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, "event: response.completed\n", ""),
        ])
        client_ws = _FakeWebSocket()

        result = asyncio.run(_relay_websocket_pair(
            client_ws,
            upstream_ws,
            [("text", "response.create")],
        ))

        self.assertTrue(result.completed)
        self.assertEqual(upstream_ws.sent, [("text", "response.create")])
        self.assertEqual(result.replay_frames, [("text", "response.create")])

    def test_codex_websocket_prepares_client_before_connecting_upstream(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "token"
        pool.accounts = [account]
        order = []
        client_ws = _FakeWebSocket(order=order)
        session = _FakeWSSession([_FakeWebSocket()], order=order)
        relay_result = _WebSocketRelayResult(
            origin="upstream",
            messages=1,
            bytes_forwarded=64,
            completed=True,
            close_code=1000,
            error="",
        )

        async def fake_relay(_client_ws, _upstream_ws, _replay_frames):
            return relay_result

        with mock.patch("proxy_core.web.WebSocketResponse", return_value=client_ws) as ws_factory, \
                mock.patch("proxy_core._relay_websocket_pair", side_effect=fake_relay):
            result = asyncio.run(_handle_codex_websocket(
                _FakeRequest(headers={"Sec-WebSocket-Protocol": "chatgpt"}, order=order),
                pool,
                session,
                "rid-ws-ok",
                "/v1/responses",
            ))

        self.assertIs(result, client_ws)
        self.assertEqual(order[:2], ["prepare", "connect"])
        self.assertTrue(client_ws.prepared)
        self.assertTrue(client_ws.closed)
        self.assertIsNone(ws_factory.call_args.kwargs["heartbeat"])
        self.assertEqual(pool.recent_requests[0]["path"], "/v1/responses")
        self.assertEqual(pool.recent_requests[0]["status"], 101)
        self.assertEqual(pool.recent_requests[0]["transport"], "websocket")

    def test_codex_websocket_retries_zero_output_upstream_close_without_closing_client(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]
        client_ws = _FakeWebSocket()
        upstream_a = _FakeWebSocket(close_code=1000)
        upstream_b = _FakeWebSocket(close_code=1000)
        session = _FakeWSSession([upstream_a, upstream_b])
        first = _WebSocketRelayResult(
            origin="upstream",
            messages=0,
            bytes_forwarded=0,
            completed=False,
            close_code=1000,
            error="closed before completion",
            replay_frames=[("text", "response.create")],
        )
        second = _WebSocketRelayResult(
            origin="upstream",
            messages=1,
            bytes_forwarded=64,
            completed=True,
            close_code=1000,
            error="",
            replay_frames=[("text", "response.create")],
        )

        with mock.patch("proxy_core.web.WebSocketResponse", return_value=client_ws), \
                mock.patch("proxy_core._relay_websocket_pair", side_effect=[first, second]) as relay:
            result = asyncio.run(_handle_codex_websocket(
                _FakeRequest(),
                pool,
                session,
                "rid-ws-retry",
                "/v1/responses",
            ))

        self.assertIs(result, client_ws)
        self.assertTrue(client_ws.closed)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(relay.call_args_list[0].args[2], [])
        self.assertEqual(relay.call_args_list[1].args[2], [("text", "response.create")])
        self.assertTrue(account_a.is_rate_limited)
        self.assertEqual(account_a.cooldown_reason, "ws_stream_interrupted")
        self.assertFalse(account_b.is_rate_limited)
        self.assertEqual(pool.recent_requests[0]["account"], "b")
        self.assertEqual(pool.recent_requests[1]["account"], "a")

    def test_codex_websocket_does_not_retry_after_forwarding_partial_upstream_output(self):
        pool = AccountPool()
        root = Path(tempfile.mkdtemp())
        account_a = Account("a", root / "a" / "auth.json")
        account_a.access_token = "token-a"
        account_b = Account("b", root / "b" / "auth.json")
        account_b.access_token = "token-b"
        pool.accounts = [account_a, account_b]
        client_ws = _FakeWebSocket()
        session = _FakeWSSession([_FakeWebSocket()])
        partial = _WebSocketRelayResult(
            origin="upstream",
            messages=1,
            bytes_forwarded=64,
            completed=False,
            close_code=1006,
            error="closed after output",
            replay_frames=[("text", "response.create")],
        )

        with mock.patch("proxy_core.web.WebSocketResponse", return_value=client_ws), \
                mock.patch("proxy_core._relay_websocket_pair", return_value=partial):
            result = asyncio.run(_handle_codex_websocket(
                _FakeRequest(),
                pool,
                session,
                "rid-ws-partial",
                "/v1/responses",
            ))

        self.assertIs(result, client_ws)
        self.assertTrue(client_ws.closed)
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(account_a.is_rate_limited)
        self.assertFalse(account_b.is_rate_limited)

    def test_codex_websocket_upstream_failure_closes_client_without_http_500(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "token"
        pool.accounts = [account]
        client_ws = _FakeWebSocket()
        session = _FakeWSSession([asyncio.TimeoutError("timeout")])

        with mock.patch("proxy_core.web.WebSocketResponse", return_value=client_ws):
            result = asyncio.run(_handle_codex_websocket(
                _FakeRequest(),
                pool,
                session,
                "rid-ws-fail",
                "/v1/responses",
            ))

        self.assertIs(result, client_ws)
        self.assertTrue(client_ws.prepared)
        self.assertTrue(client_ws.closed)
        self.assertEqual(client_ws.close_args[1]["code"], aiohttp.WSCloseCode.TRY_AGAIN_LATER)
        self.assertIn("ws_handshake_failed", pool.recent_errors[0]["error"])
        self.assertEqual(pool.recent_errors[0]["request_id"], "rid-ws-fail")

    def test_codex_websocket_prepare_disconnect_records_error_without_cooldown(self):
        pool = AccountPool()
        account = Account("a", Path(tempfile.mkdtemp()) / "auth.json")
        account.access_token = "token"
        pool.accounts = [account]
        client_ws = _FakeWebSocket(prepare_error=AssertionError("transport is not None"))
        session = _FakeWSSession([_FakeWebSocket()])

        with mock.patch("proxy_core.web.WebSocketResponse", return_value=client_ws):
            result = asyncio.run(_handle_codex_websocket(
                _FakeRequest(),
                pool,
                session,
                "rid-ws-prepare",
                "/v1/responses",
            ))

        self.assertEqual(result.status, 499)
        self.assertEqual(session.calls, [])
        self.assertFalse(account.is_rate_limited)
        self.assertIn("ws_client_disconnected_before_prepare", pool.recent_errors[0]["error"])
        self.assertEqual(pool.recent_errors[0]["request_id"], "rid-ws-prepare")

    def test_websocket_relay_reports_upstream_close_without_completion(self):
        upstream_ws = _FakeWebSocket([
            aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, "event: response.output_text.delta\n", ""),
        ], close_code=1006)
        client_ws = _FakeWebSocket()

        result = asyncio.run(_relay_websocket_pair(client_ws, upstream_ws))

        self.assertEqual(result.origin, "upstream")
        self.assertFalse(result.completed)
        self.assertEqual(result.messages, 1)
        self.assertGreater(result.bytes_forwarded, 0)
        self.assertEqual(result.close_code, 1006)

    def test_websocket_retry_predicate_allows_only_zero_output_upstream_close(self):
        self.assertTrue(_can_retry_websocket_without_forwarding(_WebSocketRelayResult(
            origin="upstream",
            messages=0,
            bytes_forwarded=0,
            completed=False,
        )))
        self.assertFalse(_can_retry_websocket_without_forwarding(_WebSocketRelayResult(
            origin="upstream",
            messages=1,
            bytes_forwarded=1,
            completed=False,
        )))
        self.assertFalse(_can_retry_websocket_without_forwarding(_WebSocketRelayResult(
            origin="client",
            messages=0,
            bytes_forwarded=0,
            completed=False,
        )))

    def test_websocket_interruption_records_error_and_cools_account(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        result = _WebSocketRelayResult(
            origin="upstream",
            messages=2,
            bytes_forwarded=128,
            completed=False,
            close_code=1006,
            error="closed",
        )

        _record_ws_stream_interrupted(
            pool,
            account,
            "/v1/responses",
            "rid-ws-error",
            0,
            result,
            60,
        )

        self.assertTrue(account.is_rate_limited)
        self.assertEqual(account.cooldown_reason, "ws_stream_interrupted")
        self.assertIn("ws_stream_interrupted", pool.recent_errors[0]["error"])
        self.assertIn("messages=2", pool.recent_errors[0]["error"])

    def test_completed_websocket_clears_previous_ws_interruption_cooldown(self):
        pool = AccountPool()
        account = Account("tmp", Path(tempfile.mkdtemp()) / "auth.json")
        account.rate_limited_until = 1
        account.cooldown_reason = "ws_stream_interrupted"

        _clear_ws_stream_interruption_cooldown(pool, account)

        self.assertEqual(account.rate_limited_until, 0)
        self.assertEqual(account.cooldown_reason, "")


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
            'base_url = "http://127.0.0.1:8800/v1"\n'
            'wire_api = "responses"\n'
            "supports_websockets = true\n"
        )

        values = codex_config._read_values(config_path)
        self.assertEqual(values["model_provider"], "codex-account-pool")
        self.assertTrue(values['plugins."documents@openai-primary-runtime".enabled'])
        self.assertEqual(values["model_providers.codex-account-pool.wire_api"], "responses")
        self.assertTrue(values["model_providers.codex-account-pool.supports_websockets"])

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
        self.assertIn('base_url = "http://127.0.0.1:8800/v1"', text)
        self.assertIn('wire_api = "responses"', text)
        self.assertIn('requires_openai_auth = true', text)
        self.assertIn('supports_websockets = true', text)
        self.assertIn("stream_max_retries = 8", text)
        self.assertIn("stream_idle_timeout_ms = 600000", text)
        codex_config.set_enabled(False, config_path)
        self.assertFalse(codex_config.status(config_path)["enabled"])

    def test_legacy_codex_backend_provider_is_not_current_enabled_mode(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"
        config_path.write_text(
            'model_provider = "codex-account-pool"\n'
            'chatgpt_base_url = "http://127.0.0.1:8800/backend-api/"\n'
            "[model_providers.codex-account-pool]\n"
            'base_url = "http://127.0.0.1:8800/backend-api/codex"\n'
            'wire_api = "responses"\n'
            "requires_openai_auth = true\n"
            "supports_websockets = false\n"
        )

        status = codex_config.status(config_path)

        self.assertFalse(status["enabled"])
        self.assertEqual(status["mode"], "legacy_codex_pool_provider")
        self.assertTrue(status["legacy_provider_mode_enabled"])

    def test_ensure_enabled_rewrites_config_missing_realtime_stream_settings(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"
        config_path.write_text(
            'model_provider = "codex-account-pool"\n'
            'chatgpt_base_url = "http://127.0.0.1:8800/backend-api/"\n'
            "[model_providers.codex-account-pool]\n"
            'base_url = "http://127.0.0.1:8800/v1"\n'
            'wire_api = "responses"\n'
            "requires_openai_auth = true\n"
            "supports_websockets = true\n"
        )

        self.assertFalse(codex_config.status(config_path)["enabled"])
        result = codex_config.ensure_enabled(True, config_path)

        self.assertTrue(result["enabled"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["current"]["stream_max_retries"], 8)
        self.assertEqual(result["current"]["stream_idle_timeout_ms"], 600000)

    def test_ensure_enabled_does_not_rewrite_matching_config(self):
        config_path = Path(tempfile.mkdtemp()) / "config.toml"

        first = codex_config.ensure_enabled(True, config_path)
        second = codex_config.ensure_enabled(True, config_path)

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertIsNone(second["backup_path"])


class ServiceManagerTests(unittest.TestCase):
    def _write_minimal_runtime_source(self, source: Path) -> None:
        for name in ("account_manager.py", "config.py", "proxy.py", "proxy_core.py", "service_manager.py"):
            (source / name).write_text(f"# {name}\n")
        (source / "static").mkdir(exist_ok=True)
        (source / "static" / "index.html").write_text("static\n")

    def test_source_dir_prefers_launchagent_environment(self):
        root = Path(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(root)}):
            self.assertEqual(service_manager._source_dir(), root)

    def test_inside_launchagent_detects_service_name(self):
        with mock.patch.dict(os.environ, {"XPC_SERVICE_NAME": service_manager.LABEL}):
            self.assertTrue(service_manager._inside_launchagent())

    def test_status_marks_old_launchagent_environment_for_repair(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        app = Path(tempfile.mkdtemp()) / "Codex Proxy Control.app"
        old_app = Path(tempfile.mkdtemp()) / "Old Codex Proxy Control.app"
        plist_path = Path(tempfile.mkdtemp()) / "com.fank1ng.codexproxyapi.plist"
        (source / "proxy.py").write_text("# source\n")
        (app / "Contents").mkdir(parents=True)
        (old_app / "Contents").mkdir(parents=True)
        plist_path.write_bytes(plistlib.dumps({
            "Label": service_manager.LABEL,
            "ProgramArguments": [sys.executable, str(runtime / "proxy.py")],
            "WorkingDirectory": str(runtime),
            "EnvironmentVariables": {
                service_manager.SOURCE_DIR_ENV: str(source / "old-runtime"),
                service_manager.APP_BUNDLE_ENV: str(old_app),
            },
        }))

        with mock.patch.object(service_manager, "PLIST_PATH", plist_path), \
                mock.patch.object(service_manager, "OLD_PLIST_PATH", plist_path.parent / "missing-old.plist"), \
                mock.patch.object(service_manager, "RUNTIME_DIR", runtime), \
                mock.patch.object(service_manager, "_launchctl_print", return_value=mock.Mock(returncode=0)), \
                mock.patch.object(service_manager, "_legacy_launchctl_print", return_value=mock.Mock(returncode=3)), \
                mock.patch.dict(os.environ, {
                    service_manager.SOURCE_DIR_ENV: str(source),
                    service_manager.APP_BUNDLE_ENV: str(app),
                }):
            result = service_manager.status()

        self.assertTrue(result["needs_repair"])
        self.assertIn(f"{service_manager.SOURCE_DIR_ENV.lower()}_mismatch", result["repair_reasons"])
        self.assertIn(f"{service_manager.APP_BUNDLE_ENV.lower()}_mismatch", result["repair_reasons"])
        self.assertEqual(result["installed_source_dir"], str(source / "old-runtime"))
        self.assertEqual(result["installed_app_bundle"], str(old_app))

    def test_status_marks_loaded_legacy_launchagent_as_migration_required(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        old_runtime = Path(tempfile.mkdtemp())
        plist_dir = Path(tempfile.mkdtemp())
        plist_path = plist_dir / "com.fank1ng.xiaolachang.plist"
        old_plist_path = plist_dir / "com.fank1ng.codexproxyapi.plist"
        (source / "proxy.py").write_text('APP_VERSION = "0.6.0"\n')
        (old_runtime / "proxy.py").write_text('APP_VERSION = "0.5.4"\n')
        old_plist_path.write_bytes(plistlib.dumps({
            "Label": service_manager.OLD_LABEL,
            "ProgramArguments": [sys.executable, str(old_runtime / "proxy.py")],
            "WorkingDirectory": str(old_runtime),
        }))

        with mock.patch.object(service_manager, "PLIST_PATH", plist_path), \
                mock.patch.object(service_manager, "OLD_PLIST_PATH", old_plist_path), \
                mock.patch.object(service_manager, "RUNTIME_DIR", runtime), \
                mock.patch.object(service_manager, "OLD_RUNTIME_DIR", old_runtime), \
                mock.patch.object(service_manager, "_launchctl_print", return_value=mock.Mock(returncode=3)), \
                mock.patch.object(service_manager, "_legacy_launchctl_print", return_value=mock.Mock(returncode=0)), \
                mock.patch.dict(os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}):
            result = service_manager.status()

        self.assertTrue(result["legacy_loaded"])
        self.assertTrue(result["legacy_running"])
        self.assertTrue(result["migration_required"])
        self.assertTrue(result["version_mismatch"])
        self.assertEqual(result["expected_version"], "0.6.0")
        self.assertEqual(result["running_version"], "0.5.4")

    def test_ensure_running_repairs_installed_launchagent_with_stale_environment(self):
        with mock.patch.object(service_manager, "status", return_value={
            "installed": True,
            "loaded": True,
            "needs_repair": True,
        }), mock.patch.object(service_manager, "install", return_value={"installed": True}) as install:
            result = service_manager.ensure_running()

        self.assertEqual(result, {"installed": True})
        install.assert_called_once_with(sync=False)

    def test_ensure_running_syncs_when_migration_is_required(self):
        with mock.patch.object(service_manager, "status", return_value={
            "installed": False,
            "loaded": False,
            "needs_repair": True,
            "migration_required": True,
        }), mock.patch.object(service_manager, "install", return_value={"installed": True}) as install:
            result = service_manager.ensure_running()

        self.assertEqual(result, {"installed": True})
        install.assert_called_once_with(sync=True)

    def test_sync_runtime_dir_uses_configured_source(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        self._write_minimal_runtime_source(source)
        (source / "proxy.py").write_text("from source")

        with mock.patch.object(service_manager, "RUNTIME_DIR", runtime), mock.patch.dict(
            os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}
        ):
            service_manager._sync_runtime_dir()

        self.assertEqual((runtime / "proxy.py").read_text(), "from source")

    def test_sync_runtime_dir_preserves_existing_config(self):
        source = Path(tempfile.mkdtemp())
        runtime = Path(tempfile.mkdtemp())
        self._write_minimal_runtime_source(source)
        (source / "config.json").write_text('{"port": 9999}\n')
        (runtime / "config.json").write_text('{"port": 8800}\n')

        with mock.patch.object(service_manager, "RUNTIME_DIR", runtime), mock.patch.dict(
            os.environ, {service_manager.SOURCE_DIR_ENV: str(source)}
        ):
            service_manager._sync_runtime_dir()

        self.assertEqual((runtime / "config.json").read_text(), '{"port": 8800}\n')

    def test_legacy_runtime_migration_copies_credentials_and_keeps_old_dir(self):
        runtime = Path(tempfile.mkdtemp()) / "xiaolachang"
        old_runtime = Path(tempfile.mkdtemp()) / "codexproxyapi"
        account_dir = old_runtime / "accounts" / "main"
        account_dir.mkdir(parents=True)
        (account_dir / "auth.json").write_text(json.dumps({"tokens": {"refresh_token": "r"}}))
        (old_runtime / "proxy.py").write_text('APP_VERSION = "0.5.4"\n')

        with mock.patch.object(service_manager, "RUNTIME_DIR", runtime), \
                mock.patch.object(service_manager, "OLD_RUNTIME_DIR", old_runtime):
            service_manager._migrate_legacy_runtime()

        self.assertTrue((runtime / "accounts" / "main" / "auth.json").exists())
        self.assertTrue((old_runtime / "accounts" / "main" / "auth.json").exists())
        self.assertTrue(old_runtime.exists())

    def test_app_bundle_dir_uses_environment(self):
        app = Path(tempfile.mkdtemp()) / "Codex Proxy Control.app"
        (app / "Contents").mkdir(parents=True)
        with mock.patch.dict(os.environ, {service_manager.APP_BUNDLE_ENV: str(app)}):
            self.assertEqual(service_manager._app_bundle_dir(), app)


if __name__ == "__main__":
    unittest.main()
