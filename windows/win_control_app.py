"""Minimal Windows control app for Codex Proxy Control."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk


ROOT = Path(__file__).resolve().parents[1] if not getattr(sys, "frozen", False) else Path(sys.executable).resolve().parent
SOURCE_RUNTIME = ROOT / "runtime" if getattr(sys, "frozen", False) else ROOT
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

import codex_config  # noqa: E402
import win_service_manager  # noqa: E402


APP_URL = "http://127.0.0.1:8800/app"


def service_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("CodexProxyService.exe")), *args]
    return [sys.executable, str(ROOT / "windows" / "codex_proxy_service.py"), *args]


class ControlApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Codex Proxy Control")
        self.root.geometry("760x520")
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

        ttk.Label(frame, textvariable=self.status_var).pack(anchor=tk.W, pady=(0, 8))
        self.output = scrolledtext.ScrolledText(frame, height=20, wrap=tk.WORD)
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
            **os.environ,
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
        self.run_bg("Checking status", lambda: self.run_service("--status"))

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
        self.output.insert(tk.END, json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n\n")
        self.output.see(tk.END)

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
