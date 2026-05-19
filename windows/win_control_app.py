"""Minimal Windows control app for Codex Proxy Control."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog, ttk


ROOT = Path(__file__).resolve().parents[1] if not getattr(sys, "frozen", False) else Path(sys.executable).resolve().parent
SOURCE_RUNTIME = ROOT / "runtime" if getattr(sys, "frozen", False) else ROOT
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

import codex_config  # noqa: E402
import win_service_manager  # noqa: E402


APP_URL = "http://127.0.0.1:8800/app"
API_ROOT = "http://127.0.0.1:8800"
ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ACCOUNTS_DIR = win_service_manager.RUNTIME_DIR / "accounts"
TRASH_DIR = ACCOUNTS_DIR / ".trash"
CODEX_AUTH_PATH = codex_config.CODEX_CONFIG_PATH.parent / "auth.json"
PYTHON_BOOT_ENV_KEYS = ("PYTHONHOME", "PYTHONPATH", "PYTHONPLATLIBDIR", "PYTHONSAFEPATH")


def clean_python_boot_env(env: dict[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    for key in PYTHON_BOOT_ENV_KEYS:
        cleaned.pop(key, None)
    return cleaned


def service_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("CodexProxyService.exe")), *args]
    return [sys.executable, str(ROOT / "windows" / "codex_proxy_service.py"), *args]


def validate_account_name(name: str) -> str:
    value = (name or "").strip()
    if not ACCOUNT_NAME_RE.fullmatch(value):
        raise ValueError("Account name must be 1-64 letters, numbers, dashes, or underscores.")
    return value


def account_dir(name: str) -> Path:
    safe_name = validate_account_name(name)
    root = ACCOUNTS_DIR.resolve()
    target = (ACCOUNTS_DIR / safe_name).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Account path escapes accounts directory.")
    return target


def http_json(path: str, *, method: str = "GET", body: dict | None = None, timeout: float = 4.0):
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


def proxy_online() -> bool:
    result = http_json("/api/health", timeout=2)
    return isinstance(result, dict) and bool(result.get("running")) and not result.get("error")


def local_accounts() -> list[dict]:
    rows = []
    if not ACCOUNTS_DIR.exists():
        return rows
    for path in sorted(ACCOUNTS_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        auth_path = path / "auth.json"
        meta_path = path / "account.json"
        if not auth_path.exists():
            continue
        enabled = True
        auth_error = ""
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                enabled = bool(meta.get("enabled", True))
                auth_error = str(meta.get("auth_error", ""))
            except (OSError, json.JSONDecodeError):
                pass
        email = ""
        account_id = ""
        expires_at = 0
        has_tokens = False
        try:
            data = json.loads(auth_path.read_text(encoding="utf-8"))
            tokens = data.get("tokens", {})
            access_token = tokens.get("access_token") or ""
            has_tokens = bool(access_token)
            claims = decode_jwt_claims(access_token)
            email = (
                claims.get("email")
                or claims.get("https://api.openai.com/profile", {}).get("email", "")
                or claims.get("https://api.openai.com/profile.email", "")
            )
            account_id = tokens.get("account_id") or claims.get("https://api.openai.com/auth.chatgpt_account_id", "")
            expires_at = float(claims.get("exp") or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            auth_error = auth_error or "invalid auth.json"
        rows.append({
            "name": path.name,
            "email": email,
            "account_id": account_id,
            "enabled": enabled,
            "auth_error": auth_error,
            "rate_limited": False,
            "rate_limited_until": 0,
            "cooldown_reason": "",
            "expires_at": expires_at,
            "has_tokens": has_tokens,
        })
    return rows


def decode_jwt_claims(token: str) -> dict:
    if not token or "." not in token:
        return {}
    try:
        import base64

        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def find_codex_cli() -> str | None:
    return shutil.which("codex")


class ControlApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Codex Proxy Control")
        self.root.geometry("980x680")
        self.root.minsize(860, 560)
        self.accounts: list[dict] = []
        self.status_var = tk.StringVar(value="Ready")
        self._build()
        self.refresh_status()

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(frame, text="Codex Proxy Control", font=("Segoe UI", 16, "bold"))
        title.pack(anchor=tk.W)

        actions = ttk.Frame(frame)
        actions.pack(fill=tk.X, pady=(12, 8))
        buttons = (
            ("Start / Repair", self.install_service),
            ("Stop", self.stop_service),
            ("Restart", self.restart_service),
            ("Open Web UI", self.open_web),
            ("Open Log", self.open_log),
            ("Enable Proxy", self.enable_proxy),
            ("Disable Proxy", self.disable_proxy),
            ("Status", self.refresh_status),
        )
        for index, (label, command) in enumerate(buttons):
            ttk.Button(actions, text=label, command=command).grid(row=index // 4, column=index % 4, padx=4, pady=4, sticky="ew")
        for column in range(4):
            actions.columnconfigure(column, weight=1)

        account_actions = ttk.Frame(frame)
        account_actions.pack(fill=tk.X, pady=(2, 8))
        account_buttons = (
            ("Scan Accounts", self.scan_accounts),
            ("Add Account", self.add_account),
            ("Import Current", self.import_current_account),
            ("Delete Selected", self.delete_selected_account),
            ("Enable / Disable", self.toggle_selected_account),
            ("Refresh Token", self.refresh_selected_token),
        )
        for index, (label, command) in enumerate(account_buttons):
            ttk.Button(account_actions, text=label, command=command).grid(
                row=0,
                column=index,
                padx=4,
                pady=4,
                sticky="ew",
            )
        for column in range(len(account_buttons)):
            account_actions.columnconfigure(column, weight=1)

        columns = ("name", "email", "state", "expires", "account_id")
        self.account_tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        headings = {
            "name": "Name",
            "email": "Email",
            "state": "State",
            "expires": "Token Expiry",
            "account_id": "Account ID",
        }
        widths = {
            "name": 110,
            "email": 220,
            "state": 130,
            "expires": 150,
            "account_id": 250,
        }
        for column, heading in headings.items():
            self.account_tree.heading(column, text=heading)
            self.account_tree.column(column, width=widths[column], anchor=tk.W)
        self.account_tree.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame, textvariable=self.status_var).pack(anchor=tk.W, pady=(0, 8))
        self.output = scrolledtext.ScrolledText(frame, height=12, wrap=tk.WORD)
        self.output.pack(fill=tk.BOTH, expand=True)

    def run_bg(self, label: str, func) -> None:
        self.status_var.set(label)

        def work() -> None:
            try:
                result = func()
                self.root.after(0, self.render, result)
            except Exception as exc:
                self.root.after(0, self.show_error, str(exc))

        threading.Thread(target=work, daemon=True).start()

    def run_service(self, *args: str) -> dict:
        env = {
            **clean_python_boot_env(os.environ),
            "CODEX_PROXY_SOURCE_DIR": str(SOURCE_RUNTIME),
            "CODEX_PROXY_CONFIG_DIR": str(win_service_manager.RUNTIME_DIR),
        }
        result = subprocess.run(
            service_command(*args, "--json"),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        text = result.stdout.strip() or result.stderr.strip()
        if result.returncode != 0:
            raise RuntimeError(text or f"service command failed: {' '.join(args)}")
        return json.loads(text) if text else {}

    def install_service(self) -> None:
        self.run_bg("Starting proxy", lambda: self.run_service("--install"))

    def stop_service(self) -> None:
        self.run_bg("Stopping proxy", lambda: self.run_service("--stop"))

    def restart_service(self) -> None:
        self.run_bg("Restarting proxy", lambda: self.run_service("--restart"))

    def refresh_status(self) -> None:
        def work() -> dict:
            service = self.run_service("--status")
            accounts = self.read_accounts()
            service["accounts"] = accounts
            return service

        self.run_bg("Checking status", work)

    def scan_accounts(self) -> None:
        def work() -> dict:
            if proxy_online():
                result = http_json("/api/accounts/scan", method="POST", timeout=5)
                accounts = result if isinstance(result, list) else self.read_accounts()
            else:
                accounts = local_accounts()
            return {"action": "scan_accounts", "total_accounts": len(accounts), "accounts": accounts}

        self.run_bg("Scanning accounts", work)

    def add_account(self) -> None:
        name = simpledialog.askstring("Add Account", "Account name:", parent=self.root)
        if not name:
            return
        try:
            safe_name = validate_account_name(name)
        except Exception as exc:
            messagebox.showerror("Add Account", str(exc))
            return

        def work() -> dict:
            target = account_dir(safe_name)
            auth_path = target / "auth.json"
            if auth_path.exists():
                raise FileExistsError(f"{safe_name} already has auth.json")
            codex_cli = find_codex_cli()
            if not codex_cli:
                raise FileNotFoundError("Codex CLI not found in PATH")
            target.mkdir(parents=True, exist_ok=True)
            log_path = win_service_manager.RUNTIME_DIR / "login.log"
            env = {
                **clean_python_boot_env(os.environ),
                "CODEX_HOME": str(target),
            }
            with open(log_path, "a", encoding="utf-8", buffering=1) as log:
                log.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] starting login for {safe_name}\n")
                process = subprocess.Popen(
                    [codex_cli, "login"],
                    cwd=str(win_service_manager.RUNTIME_DIR),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
            return {
                "action": "login_started",
                "account": safe_name,
                "account_dir": str(target),
                "log_path": str(log_path),
                "pid": process.pid,
                "hint": "Complete the browser sign-in, then click Scan Accounts.",
            }

        self.run_bg("Starting account login", work)

    def import_current_account(self) -> None:
        name = simpledialog.askstring("Import Current", "Save current Codex auth as account name:", parent=self.root)
        if not name:
            return
        try:
            safe_name = validate_account_name(name)
        except Exception as exc:
            messagebox.showerror("Import Current", str(exc))
            return

        def work() -> dict:
            if not CODEX_AUTH_PATH.exists():
                raise FileNotFoundError(f"Missing {CODEX_AUTH_PATH}")
            target = account_dir(safe_name)
            auth_path = target / "auth.json"
            if auth_path.exists():
                raise FileExistsError(f"{safe_name} already has auth.json")
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CODEX_AUTH_PATH, auth_path)
            if proxy_online():
                http_json("/api/accounts/scan", method="POST", timeout=5)
            return {"action": "import_current", "account": safe_name, "accounts": self.read_accounts()}

        self.run_bg("Importing current account", work)

    def delete_selected_account(self) -> None:
        try:
            name = self.require_selected_account()
        except Exception as exc:
            messagebox.showerror("Delete Account", str(exc))
            return
        if not messagebox.askyesno("Delete Account", f"Delete account {name}? It will be moved to .trash."):
            return

        def work() -> dict:
            if proxy_online():
                result = http_json(f"/api/accounts/{name}", method="DELETE", timeout=5)
                if isinstance(result, dict) and not result.get("error"):
                    result["accounts"] = self.read_accounts()
                    return result
            target = account_dir(name)
            if not target.exists():
                raise FileNotFoundError(f"Account not found: {name}")
            TRASH_DIR.mkdir(parents=True, exist_ok=True)
            trashed = TRASH_DIR / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
            shutil.move(str(target), str(trashed))
            if proxy_online():
                http_json("/api/accounts/scan", method="POST", timeout=5)
            return {"action": "delete_account", "deleted": name, "trashed_to": str(trashed), "accounts": self.read_accounts()}

        self.run_bg("Deleting account", work)

    def toggle_selected_account(self) -> None:
        try:
            name = self.require_selected_account()
        except Exception as exc:
            messagebox.showerror("Enable / Disable", str(exc))
            return

        def work() -> dict:
            if proxy_online():
                result = http_json(f"/api/accounts/{name}/toggle", method="PUT", timeout=5)
                if isinstance(result, dict) and not result.get("error"):
                    return {"action": "toggle_account", "account": name, "enabled": result.get("enabled"), "accounts": self.read_accounts()}
            target = account_dir(name)
            meta_path = target / "account.json"
            meta = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    meta = {}
            meta["enabled"] = not bool(meta.get("enabled", True))
            meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime())
            meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            return {"action": "toggle_account_local", "account": name, "enabled": meta["enabled"], "accounts": self.read_accounts()}

        self.run_bg("Toggling account", work)

    def refresh_selected_token(self) -> None:
        try:
            name = self.require_selected_account()
        except Exception as exc:
            messagebox.showerror("Refresh Token", str(exc))
            return

        def work() -> dict:
            if not proxy_online():
                raise RuntimeError("Proxy must be running to refresh a token from the Control App.")
            result = http_json(f"/api/accounts/{name}/refresh", method="POST", timeout=45)
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(str(result.get("error")))
            return {"action": "refresh_token", "account": name, "result": result, "accounts": self.read_accounts()}

        self.run_bg("Refreshing token", work)

    def enable_proxy(self) -> None:
        def work() -> dict:
            result = codex_config.ensure_enabled(True)
            result["action"] = "enable_proxy"
            return result

        self.run_bg("Enabling Codex proxy", work)

    def disable_proxy(self) -> None:
        def work() -> dict:
            result = codex_config.ensure_enabled(False)
            result["action"] = "disable_proxy"
            return result

        self.run_bg("Disabling Codex proxy", work)

    def open_web(self) -> None:
        webbrowser.open(APP_URL)
        self.render({"action": "open_web", "url": APP_URL})

    def open_log(self) -> None:
        log_path = win_service_manager.LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        os.startfile(log_path)  # type: ignore[attr-defined]
        self.render({"action": "open_log", "log_path": str(log_path)})

    def render(self, result: dict) -> None:
        self.status_var.set("Ready")
        if "accounts" in result and isinstance(result["accounts"], list):
            self.accounts = result["accounts"]
            self.render_accounts(self.accounts)
            result = {key: value for key, value in result.items() if key != "accounts"}
        self.output.insert(tk.END, json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n\n")
        self.output.see(tk.END)

    def read_accounts(self) -> list[dict]:
        if proxy_online():
            result = http_json("/api/accounts", timeout=4)
            if isinstance(result, list):
                return result
        return local_accounts()

    def render_accounts(self, accounts: list[dict]) -> None:
        selected = self.selected_account()
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        selected_iid = ""
        for account in accounts:
            name = str(account.get("name") or "")
            iid = self.account_tree.insert(
                "",
                tk.END,
                values=(
                    name,
                    account.get("email") or "-",
                    self.account_state(account),
                    self.expiry_label(account.get("expires_at")),
                    account.get("account_id") or "-",
                ),
            )
            if name == selected:
                selected_iid = iid
        if selected_iid:
            self.account_tree.selection_set(selected_iid)

    def selected_account(self) -> str:
        selection = self.account_tree.selection()
        if not selection:
            return ""
        values = self.account_tree.item(selection[0], "values")
        return str(values[0]) if values else ""

    def require_selected_account(self) -> str:
        name = self.selected_account()
        if not name:
            raise ValueError("Select an account first.")
        return validate_account_name(name)

    def account_state(self, account: dict) -> str:
        if account.get("auth_error"):
            return f"auth error: {account.get('auth_error')}"
        if not account.get("has_tokens"):
            return "missing token"
        if not account.get("enabled"):
            return "disabled"
        if account.get("rate_limited"):
            return account.get("cooldown_reason") or "cooldown"
        return "active"

    def expiry_label(self, expires_at) -> str:
        try:
            value = float(expires_at or 0)
        except (TypeError, ValueError):
            return "-"
        if value <= 0:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(value))

    def show_error(self, message: str) -> None:
        self.status_var.set("Error")
        self.output.insert(tk.END, f"ERROR: {message}\n\n")
        self.output.see(tk.END)
        messagebox.showerror("Codex Proxy Control", message)


def main() -> None:
    root = tk.Tk()
    ControlApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
