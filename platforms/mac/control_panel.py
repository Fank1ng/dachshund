#!/usr/bin/env python3
"""Native control panel for Codex Account Pool Proxy.

This app is intentionally independent from the Web UI. It can inspect local
files, repair the LaunchAgent, and manage accounts even when the proxy HTTP
server is offline.
"""

import asyncio
import json
import shutil
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog, ttk
from typing import Optional, Union
import urllib.error
import urllib.request

import codex_config
import service_manager
from account_manager import Account, AccountPool, account_dir, validate_account_name
from login_manager import find_codex_cli


APP_URL = "http://127.0.0.1:8800/app"
API_ROOT = "http://127.0.0.1:8800"
STATUS_PATH = "/api/status"
CODEX_AUTH_PATH = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"


def http_json(path: str, *, method: str = "GET", body: Optional[dict] = None, timeout: float = 2.0) -> Optional[Union[dict, list]]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API_ROOT + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"error": f"HTTP {exc.code}"}
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def proxy_status(timeout: float = 3.0) -> Optional[dict]:
    result = http_json("/api/health", timeout=timeout)
    if isinstance(result, dict) and result.get("running") and not result.get("error"):
        return result
    result = http_json(STATUS_PATH, timeout=timeout)
    return result if isinstance(result, dict) and not result.get("error") else None


def wait_for_proxy(timeout: float = 25.0) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = proxy_status(timeout=2)
        if status:
            return status
        time.sleep(0.5)
    return None


def compact(data: dict) -> str:
    keys = (
        "action",
        "installed",
        "loaded",
        "needs_repair",
        "enabled",
        "mode",
        "running",
        "active_accounts",
        "total_accounts",
        "changed",
        "restart_required",
    )
    return json.dumps({key: data.get(key) for key in keys if key in data}, ensure_ascii=False)


def local_accounts() -> list[dict]:
    pool = AccountPool()
    pool.scan()
    return [account.to_dict() for account in pool.accounts]


def load_local_account(name: str) -> Account:
    safe_name = validate_account_name(name)
    target = account_dir(safe_name)
    account = Account(safe_name, target / "auth.json")
    account.load()
    account.load_meta()
    return account


class ControlPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("小腊肠")
        self.root.geometry("980x680")
        self.root.minsize(860, 560)
        self.accounts: list[dict] = []

        self.status = tk.StringVar(value="Reading status...")
        tk.Label(root, text="Codex Account Pool Proxy", font=("Helvetica", 18, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(root, textvariable=self.status, justify="left", anchor="w").pack(fill="x", padx=18)

        buttons = tk.Frame(root)
        buttons.pack(fill="x", padx=16, pady=12)
        actions = [
            ("Refresh", self.refresh),
            ("Start / Repair", self.repair),
            ("Apply Update", self.apply_update),
            ("Enable Codex Proxy", self.enable_codex_proxy),
            ("Open Codex", self.open_codex),
            ("Open Log", self.open_log),
            ("Open Web Status", self.open_web_status),
            ("Scan Accounts", self.scan_accounts),
            ("Toggle Selected", self.toggle_selected),
            ("Refresh Token", self.refresh_selected_token),
            ("Clear Cooldown", self.clear_selected_cooldown),
            ("Login Command", self.login_command),
            ("Import Current", self.import_current_account),
        ]
        for index, (label, command) in enumerate(actions):
            self._button(buttons, label, command).grid(row=index // 6, column=index % 6, padx=4, pady=4, sticky="ew")
        for col in range(6):
            buttons.columnconfigure(col, weight=1)

        columns = ("name", "email", "state", "cooldown", "expires", "account_id")
        self.tree = ttk.Treeview(root, columns=columns, show="headings", height=10)
        headings = {
            "name": "Name",
            "email": "Email",
            "state": "State",
            "cooldown": "Cooldown",
            "expires": "Token Expiry",
            "account_id": "Account ID",
        }
        widths = {
            "name": 110,
            "email": 220,
            "state": 130,
            "cooldown": 110,
            "expires": 150,
            "account_id": 240,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill="x", padx=18, pady=(0, 10))

        self.log_box = scrolledtext.ScrolledText(root, height=16, wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        self.log("Native app is the primary management surface. Web UI is status-only fallback.")
        self.refresh()

    def _button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(parent, text=text, command=command, height=2)

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{stamp}] {message}\n")
        self.log_box.see("end")

    def run_bg(self, label: str, fn) -> None:
        def runner() -> None:
            self.root.after(0, self.log, f"{label}...")
            try:
                result = fn()
                if result is not None:
                    self.root.after(0, self.log, compact(result) if isinstance(result, dict) else str(result))
            except Exception as exc:
                self.root.after(0, self.log, f"ERROR: {exc}")
                self.root.after(0, messagebox.showerror, label, str(exc))
            finally:
                self.root.after(0, self.refresh)

        threading.Thread(target=runner, daemon=True).start()

    def refresh(self) -> None:
        try:
            service = service_manager.status()
            codex = codex_config.status()
            proxy = proxy_status()
            accounts = self._read_accounts(proxy_online=bool(proxy))
            self.accounts = accounts
            self._render_accounts(accounts)

            lines = [
                f"Proxy: {'online' if proxy else 'offline'}",
                f"Service: {'running' if service.get('loaded') else 'stopped'} ({'installed' if service.get('installed') else 'not installed'})",
                f"Codex config: {codex.get('mode')}",
                f"Accounts: {sum(1 for item in accounts if self._is_active(item))}/{len(accounts)} active",
                f"Runtime: {service.get('runtime_dir')}",
            ]
            if service.get("needs_repair"):
                lines.append(f"Repair recommended: LaunchAgent points at {service.get('installed_program')}")
            if proxy:
                last = proxy.get("last_request") or {}
                if last:
                    lines.append(f"Last request: {last.get('account')} {last.get('status')} {last.get('path')}")
            self.status.set("\n".join(lines))
        except Exception as exc:
            self.status.set(f"Status read failed: {exc}")

    def _read_accounts(self, *, proxy_online: bool) -> list[dict]:
        if proxy_online:
            remote = http_json("/api/accounts", timeout=2)
            if isinstance(remote, list):
                return remote
        return local_accounts()

    def _render_accounts(self, accounts: list[dict]) -> None:
        selected = self.selected_account()
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_iid = ""
        for account in accounts:
            name = str(account.get("name") or "")
            iid = self.tree.insert(
                "",
                "end",
                values=(
                    name,
                    account.get("email") or "-",
                    self._state_label(account),
                    self._cooldown_label(account),
                    self._expiry_label(account.get("expires_at")),
                    account.get("account_id") or "-",
                ),
            )
            if name == selected:
                selected_iid = iid
        if selected_iid:
            self.tree.selection_set(selected_iid)

    def _state_label(self, account: dict) -> str:
        if account.get("auth_error"):
            return f"auth error: {account.get('auth_error')}"
        if not account.get("has_tokens"):
            return "missing token"
        if not account.get("enabled"):
            return "disabled"
        if account.get("rate_limited"):
            return "cooldown"
        return "active"

    def _cooldown_label(self, account: dict) -> str:
        until = float(account.get("rate_limited_until") or 0)
        if until <= time.time():
            return "-"
        seconds = int(until - time.time())
        reason = account.get("cooldown_reason") or "cooldown"
        return f"{reason} {seconds}s"

    def _expiry_label(self, expires_at) -> str:
        try:
            value = float(expires_at or 0)
        except (TypeError, ValueError):
            return "-"
        if value <= 0:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))

    def _is_active(self, account: dict) -> bool:
        return bool(account.get("enabled") and account.get("has_tokens") and not account.get("rate_limited"))

    def selected_account(self) -> str:
        selection = self.tree.selection()
        if not selection:
            return ""
        values = self.tree.item(selection[0], "values")
        return str(values[0]) if values else ""

    def require_selected(self) -> str:
        name = self.selected_account()
        if not name:
            raise ValueError("Select an account first.")
        return validate_account_name(name)

    def repair(self) -> None:
        def work() -> dict:
            before = proxy_status(timeout=2)
            codex = codex_config.ensure_enabled(True)
            service = service_manager.status()
            if before:
                return {
                    "action": "already_running",
                    "installed": service.get("installed"),
                    "loaded": service.get("loaded"),
                    "needs_repair": service.get("needs_repair"),
                    "enabled": codex.get("enabled"),
                    "mode": codex.get("mode"),
                    "running": True,
                    "active_accounts": before.get("active_accounts"),
                    "total_accounts": before.get("total_accounts"),
                }
            service = service_manager.install()
            proxy = wait_for_proxy()
            return {
                "action": "started_or_repaired",
                "installed": service.get("installed"),
                "loaded": service.get("loaded"),
                "needs_repair": service.get("needs_repair"),
                "enabled": codex.get("enabled"),
                "mode": codex.get("mode"),
                "running": bool(proxy),
                "active_accounts": proxy.get("active_accounts") if proxy else None,
                "total_accounts": proxy.get("total_accounts") if proxy else None,
            }

        self.run_bg("Starting or repairing proxy service", work)

    def apply_update(self) -> None:
        if not messagebox.askyesno(
            "Apply Update",
            "This syncs the runtime copy and restarts the proxy once. Active Codex requests may be interrupted. Continue?",
        ):
            return

        def work() -> dict:
            service = service_manager.install()
            proxy = wait_for_proxy()
            return {
                "action": "apply_update",
                "installed": service.get("installed"),
                "loaded": service.get("loaded"),
                "needs_repair": service.get("needs_repair"),
                "running": bool(proxy),
                "active_accounts": proxy.get("active_accounts") if proxy else None,
                "total_accounts": proxy.get("total_accounts") if proxy else None,
            }

        self.run_bg("Applying runtime update", work)

    def scan_accounts(self) -> None:
        def work() -> dict:
            proxy = proxy_status()
            if proxy:
                result = http_json("/api/accounts/scan", method="POST", timeout=4)
                return {"action": "remote_scan", "total_accounts": len(result) if isinstance(result, list) else None}
            return {"action": "local_scan", "total_accounts": len(local_accounts()), "running": False}

        self.run_bg("Scanning accounts", work)

    def toggle_selected(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("Toggle Account", str(exc))
            return

        def work() -> dict:
            if proxy_status():
                result = http_json(f"/api/accounts/{name}/toggle", method="PUT", timeout=4)
                return {"action": "toggle", "running": True, "enabled": result.get("enabled") if isinstance(result, dict) else None}
            account = load_local_account(name)
            account.enabled = not account.enabled
            account.save_meta()
            return {"action": "toggle_local", "running": False, "enabled": account.enabled}

        self.run_bg("Toggling account", work)

    def refresh_selected_token(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("Refresh Token", str(exc))
            return

        def work() -> dict:
            if proxy_status():
                result = http_json(f"/api/accounts/{name}/refresh", method="POST", timeout=40)
                return {
                    "action": "refresh_token",
                    "running": True,
                    "enabled": (result.get("account") or {}).get("enabled") if isinstance(result, dict) else None,
                }
            account = load_local_account(name)
            ok = asyncio.run(account.refresh())
            return {"action": "refresh_token_local", "running": False, "enabled": account.enabled, "changed": ok}

        self.run_bg("Refreshing token", work)

    def clear_selected_cooldown(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("Clear Cooldown", str(exc))
            return

        def work() -> dict:
            if not proxy_status():
                return {"action": "clear_cooldown_skipped", "running": False}
            result = http_json(f"/api/accounts/{name}/cooldown/clear", method="PUT", timeout=4)
            return {"action": "clear_cooldown", "running": True, "enabled": result.get("enabled") if isinstance(result, dict) else None}

        self.run_bg("Clearing cooldown", work)

    def login_command(self) -> None:
        name = simpledialog.askstring("Login Command", "Account name:")
        if not name:
            return
        try:
            safe_name = validate_account_name(name)
            target = account_dir(safe_name)
            target.mkdir(parents=True, exist_ok=True)
            codex_cli = find_codex_cli() or "/Applications/Codex.app/Contents/Resources/codex"
            command = f"CODEX_HOME={target} {codex_cli} login"
            self.log("Run this command in Terminal, then click Scan Accounts:")
            self.log(command)
            self.root.clipboard_clear()
            self.root.clipboard_append(command)
            messagebox.showinfo("Login Command", "Command copied to clipboard and printed in the log.")
        except Exception as exc:
            messagebox.showerror("Login Command", str(exc))

    def import_current_account(self) -> None:
        name = simpledialog.askstring("Import Current", "Save current ~/.codex/auth.json as account name:")
        if not name:
            return

        def work() -> dict:
            safe_name = validate_account_name(name)
            if not CODEX_AUTH_PATH.exists():
                raise FileNotFoundError(f"Missing {CODEX_AUTH_PATH}")
            target = account_dir(safe_name)
            auth_path = target / "auth.json"
            if auth_path.exists():
                raise FileExistsError(f"{safe_name} already has auth.json")
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CODEX_AUTH_PATH, auth_path)
            if proxy_status():
                http_json("/api/accounts/scan", method="POST", timeout=4)
            return {"action": "import_current", "changed": True, "total_accounts": len(local_accounts())}

        self.run_bg("Importing current Codex auth", work)

    def enable_codex_proxy(self) -> None:
        def work() -> dict:
            result = codex_config.ensure_enabled(True)
            result["action"] = "enable_codex_proxy"
            return result

        self.run_bg("Writing Codex proxy config", work)

    def open_web_status(self) -> None:
        def work() -> dict:
            proxy = proxy_status()
            if not proxy:
                return {"action": "open_web_skipped", "running": False}
            subprocess.run(["open", APP_URL], check=False)
            return {"action": "open_web_status", "running": True}

        self.run_bg("Opening Web status page", work)

    def open_codex(self) -> None:
        def work() -> dict:
            codex = codex_config.ensure_enabled(True)
            proxy = proxy_status()
            if not proxy:
                self.root.after(0, self.log, "Proxy is offline; use Start / Repair before opening Codex for pooled traffic.")
            subprocess.run(["open", "-a", "Codex"], check=False)
            return {"action": "open_codex", "enabled": codex.get("enabled"), "mode": codex.get("mode"), "running": bool(proxy)}

        self.run_bg("Opening Codex", work)

    def open_log(self) -> None:
        log_path = Path(service_manager.LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.touch()
        subprocess.run(["open", str(log_path)], check=False)


def main() -> None:
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
