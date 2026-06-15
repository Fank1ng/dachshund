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
import config as proxy_config
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


def format_epoch(value) -> str:
    try:
        epoch = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    if epoch <= 0:
        return "-"
    return time.strftime("%m-%d %H:%M", time.localtime(epoch))


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
    NAV_ITEMS = (
        ("overview", "总览"),
        ("accounts", "账号"),
        ("quota", "额度与路由"),
        ("codex", "Codex 代理"),
        ("diagnostics", "诊断"),
        ("advanced", "高级"),
    )
    PAGE_META = {
        "overview": ("总览", "只读状态摘要，避免在首页放置高风险操作。"),
        "accounts": ("账号", "左侧查看账号池，右侧处理所选账号和新增账号。"),
        "quota": ("额度与路由", "调整账号选择、冷却和额度权重。"),
        "codex": ("Codex 代理", "管理 Codex 与本地代理的连接方式。"),
        "diagnostics": ("诊断", "查看日志、运行时路径和修复工具。"),
        "advanced": ("高级", "调整端口、流式、超时和低频运行参数。"),
    }
    CONFIG_PAGES = {"quota", "codex", "advanced"}
    CONFIG_FIELDS = {
        "quota": (
            ("rotation_strategy", "账号选择策略", "choice", ("round_robin", "most_available")),
            ("rate_limit_cooldown", "限流冷却秒数", "entry", None),
            ("max_retries", "最大重试次数", "entry", None),
            ("quota_refresh_interval", "额度刷新间隔秒数", "entry", None),
            ("quota_tracker_enabled", "启用额度后台刷新", "check", None),
            ("quota_weight_5h", "5h 额度权重", "entry", None),
            ("quota_weight_7d", "7d 额度权重", "entry", None),
        ),
        "codex": (
            ("codex_stream_mode", "Codex 流模式", "choice", ("realtime", "buffered", "hybrid")),
            ("stream_keepalive_seconds", "SSE 保活秒数", "entry", None),
            ("stream_bootstrap_retries", "首字节重试次数", "entry", None),
            ("codex_hybrid_probe_seconds", "Hybrid 探测秒数", "entry", None),
            ("codex_stream_retry_cooldown", "流式重试冷却秒数", "entry", None),
            ("nonstream_keepalive_interval", "非流式保活间隔秒数", "entry", None),
        ),
        "advanced": (
            ("port", "代理端口", "entry", None),
            ("product_mode", "产品模式", "choice", ("standard", "compatibility", "diagnostic")),
            ("max_request_body_mb", "最大请求体 MB", "entry", None),
            ("upstream_connect_timeout_sec", "上游连接超时秒数", "entry", None),
            ("upstream_transient_retries", "上游瞬时错误重试", "entry", None),
            ("upstream_transient_backoff_ms", "重试退避毫秒", "entry", None),
            ("codex_hybrid_probe_bytes", "Hybrid 探测字节", "entry", None),
            ("websocket_heartbeat_seconds", "WebSocket 心跳秒数", "entry", None),
            ("session_affinity_enabled", "启用会话绑定", "check", None),
            ("session_affinity_ttl_seconds", "会话绑定 TTL 秒数", "entry", None),
            ("log_level", "日志级别", "choice", ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
        ),
    }

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("小腊肠控制中心")
        self.root.geometry("940x620")
        self.root.minsize(940, 620)
        self.root.maxsize(940, 620)
        self.root.resizable(False, False)
        self.accounts: list[dict] = []
        self.current_page = tk.StringVar(value="overview")
        self.status = tk.StringVar(value="正在读取状态...")
        self.nav_buttons: dict[str, tk.Button] = {}
        self.pages: dict[str, ttk.Frame] = {}
        self.metric_vars: dict[str, tk.StringVar] = {}
        self.detail_vars: dict[str, tk.StringVar] = {}
        self.config_vars: dict[str, Union[tk.StringVar, tk.BooleanVar]] = {}
        self.codex_proxy_enabled = tk.BooleanVar(value=False)
        self.account_action_buttons: list[tk.Button] = []
        self._build_shell()
        self._build_pages()
        self._load_config_form()
        self.show_page("overview")
        self.log("原生 App 是主要管理界面；Web UI 只作为状态诊断兜底。")
        self.refresh()

    def _button(self, parent: tk.Widget, text: str, command) -> tk.Button:
        return tk.Button(parent, text=text, command=command, height=2)

    def _build_shell(self) -> None:
        shell = ttk.Frame(self.root, padding=0)
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, width=176, bg="#f4f5f7", highlightthickness=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar,
            text="小腊肠",
            bg="#f4f5f7",
            fg="#111827",
            font=("Helvetica", 17, "bold"),
        ).pack(anchor="w", padx=16, pady=(18, 2))
        tk.Label(
            sidebar,
            text="控制中心",
            bg="#f4f5f7",
            fg="#6b7280",
            font=("Helvetica", 12),
        ).pack(anchor="w", padx=16, pady=(0, 18))

        for key, label in self.NAV_ITEMS:
            button = tk.Button(
                sidebar,
                text=label,
                anchor="w",
                relief="flat",
                bd=0,
                padx=14,
                pady=10,
                bg="#f4f5f7",
                fg="#1f2937",
                activebackground="#e8eefc",
                command=lambda page=key: self.show_page(page),
            )
            button.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = button

        tk.Label(
            sidebar,
            textvariable=self.status,
            bg="#f4f5f7",
            fg="#6b7280",
            justify="left",
            wraplength=138,
        ).pack(side="bottom", fill="x", padx=14, pady=16)

        self.content = ttk.Frame(shell, padding=(22, 18, 22, 18))
        self.content.pack(side="left", fill="both", expand=True)

        header = ttk.Frame(self.content)
        header.pack(side="top", fill="x", pady=(0, 16))
        title_area = ttk.Frame(header)
        title_area.pack(side="left", fill="x", expand=True)
        self.page_title = tk.StringVar()
        self.page_subtitle = tk.StringVar()
        ttk.Label(title_area, textvariable=self.page_title, font=("Helvetica", 20, "bold")).pack(anchor="w")
        ttk.Label(title_area, textvariable=self.page_subtitle, foreground="#6b7280").pack(anchor="w", pady=(3, 0))
        ttk.Button(header, text="刷新", command=self.refresh).pack(side="right")

        self.footer = ttk.Frame(self.content)
        ttk.Separator(self.footer).pack(fill="x", pady=(0, 10))
        footer_actions = ttk.Frame(self.footer)
        footer_actions.pack(fill="x")
        ttk.Button(footer_actions, text="恢复默认值", command=self.restore_current_defaults).pack(side="right", padx=(8, 0))
        ttk.Button(footer_actions, text="保存设置", command=self.save_current_settings).pack(side="right")

        self.page_host = ttk.Frame(self.content)
        self.page_host.pack(side="top", fill="both", expand=True)

    def _build_pages(self) -> None:
        self._build_overview_page()
        self._build_accounts_page()
        self._build_quota_page()
        self._build_codex_page()
        self._build_diagnostics_page()
        self._build_advanced_page()

    def _new_page(self, key: str) -> ttk.Frame:
        page = ttk.Frame(self.page_host)
        self.pages[key] = page
        return page

    def _build_overview_page(self) -> None:
        page = self._new_page("overview")
        metrics = ttk.Frame(page)
        metrics.pack(fill="x")
        for index, (key, label) in enumerate((
            ("proxy", "代理状态"),
            ("service", "服务状态"),
            ("codex", "Codex 配置"),
            ("accounts", "可用账号"),
            ("requests", "总请求"),
            ("runtime", "运行时目录"),
        )):
            card = ttk.LabelFrame(metrics, text=label, padding=(14, 10))
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
            metrics.columnconfigure(index % 3, weight=1)
            self.metric_vars[key] = tk.StringVar(value="-")
            ttk.Label(card, textvariable=self.metric_vars[key], font=("Helvetica", 15, "bold"), wraplength=240).pack(anchor="w")

        body = ttk.PanedWindow(page, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(14, 0))
        main = ttk.Frame(body)
        focus_panel = ttk.LabelFrame(body, text="今日重点", padding=12)
        body.add(main, weight=3)
        body.add(focus_panel, weight=1)

        request_panel = ttk.LabelFrame(main, text="最近请求", padding=12)
        request_panel.pack(fill="both", expand=True, pady=(0, 10))
        error_panel = ttk.LabelFrame(main, text="最近错误 / 提醒", padding=12)
        error_panel.pack(fill="both", expand=True)
        self.recent_box = scrolledtext.ScrolledText(request_panel, height=14, wrap="word", relief="flat")
        self.recent_box.pack(fill="both", expand=True)
        self.alert_box = scrolledtext.ScrolledText(error_panel, height=7, wrap="word", relief="flat")
        self.alert_box.pack(fill="both", expand=True)
        self._set_text(self.recent_box, "暂无请求记录。")
        self._set_text(self.alert_box, "暂无错误。")
        for key, label in (
            ("overview_service", "后台"),
            ("overview_accounts", "账号"),
            ("overview_repair", "修复"),
            ("overview_errors", "错误"),
            ("overview_quota", "额度"),
        ):
            self.detail_vars[key] = tk.StringVar(value=f"{label}：-")
            ttk.Label(focus_panel, textvariable=self.detail_vars[key], wraplength=250, justify="left").pack(anchor="w", fill="x", pady=3)
        ttk.Separator(focus_panel).pack(fill="x", pady=10)
        ttk.Button(focus_panel, text="启动 / 修复", command=self.repair).pack(fill="x", pady=(0, 6))
        ttk.Button(focus_panel, text="打开 Codex", command=self.open_codex).pack(fill="x", pady=(0, 6))
        ttk.Button(focus_panel, text="打开 Web 状态页", command=self.open_web_status).pack(fill="x")

    def _build_accounts_page(self) -> None:
        page = self._new_page("accounts")
        pane = tk.PanedWindow(page, orient=tk.HORIZONTAL, sashwidth=6, sashrelief="flat", bd=0)
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane, padding=(0, 0, 12, 0))
        right = ttk.LabelFrame(pane, text="账号操作", padding=14, width=304)
        right.pack_propagate(False)
        pane.add(left, minsize=560)
        pane.add(right, minsize=300)

        toolbar = ttk.Frame(left)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text="账号列表", font=("Helvetica", 14, "bold")).pack(side="left")
        ttk.Button(toolbar, text="扫描", command=self.scan_accounts).pack(side="right")

        columns = ("name", "email", "state", "cooldown", "expires", "account_id")
        self.account_tree = ttk.Treeview(left, columns=columns, show="headings", height=16)
        headings = {
            "name": "名称",
            "email": "Email",
            "state": "状态",
            "cooldown": "冷却",
            "expires": "Token 过期",
            "account_id": "Account ID",
        }
        widths = {
            "name": 112,
            "email": 220,
            "state": 120,
            "cooldown": 112,
            "expires": 144,
            "account_id": 230,
        }
        for col in columns:
            self.account_tree.heading(col, text=headings[col])
            self.account_tree.column(col, width=widths[col], anchor="w", stretch=col in {"email", "account_id"})
        self.account_tree.pack(fill="both", expand=True)
        self.account_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_account_actions())

        self.account_detail = tk.StringVar(value="未选择账号。")
        ttk.Label(right, textvariable=self.account_detail, justify="left", wraplength=260).pack(anchor="w", fill="x", pady=(0, 14))
        for label, command, needs_selection in (
            ("登录新账号", self.login_command, False),
            ("导入当前账号", self.import_current_account, False),
            ("复制所选登录命令", self.copy_selected_login_command, True),
            ("启用 / 禁用所选账号", self.toggle_selected, True),
            ("刷新所选 Token", self.refresh_selected_token, True),
            ("清除所选冷却", self.clear_selected_cooldown, True),
        ):
            button = self._button(right, label, command)
            button.pack(fill="x", pady=4)
            if needs_selection:
                self.account_action_buttons.append(button)
        self._update_account_actions()

    def _build_quota_page(self) -> None:
        page = self._new_page("quota")
        pane = ttk.PanedWindow(page, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        right = ttk.LabelFrame(pane, text="路由解释", padding=14)
        pane.add(left, weight=2)
        pane.add(right, weight=1)
        self._config_section(left, "额度与路由设置", self.CONFIG_FIELDS["quota"])
        for key, label in (
            ("routing_strategy", "当前策略"),
            ("routing_cooldown", "冷却账号"),
            ("routing_refresh", "额度刷新"),
            ("routing_window", "窗口权重"),
        ):
            self.detail_vars[key] = tk.StringVar(value=f"{label}：-")
            ttk.Label(right, textvariable=self.detail_vars[key], wraplength=300, justify="left").pack(anchor="w", fill="x", pady=4)
        ttk.Label(
            right,
            text="额度优先会先看可用性，再参考 5h 与 7d 剩余额度；数据缺失时自动保持可用账号轮换。",
            foreground="#6b7280",
            wraplength=300,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(12, 0))

    def _build_codex_page(self) -> None:
        page = self._new_page("codex")
        pane = ttk.PanedWindow(page, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        right = ttk.LabelFrame(pane, text="当前生效配置", padding=14)
        pane.add(left, weight=2)
        pane.add(right, weight=1)
        status = ttk.LabelFrame(left, text="Codex 代理状态", padding=14)
        status.pack(fill="x", pady=(0, 14))
        self.detail_vars["codex_proxy"] = tk.StringVar(value="-")
        ttk.Label(status, textvariable=self.detail_vars["codex_proxy"], wraplength=760, justify="left").pack(anchor="w", fill="x")
        ttk.Checkbutton(status, text="让 Codex 使用本地账号池代理", variable=self.codex_proxy_enabled).pack(anchor="w", pady=(10, 0))
        actions = ttk.Frame(status)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="打开 Codex", command=self.open_codex).pack(side="left", padx=(0, 8))
        ttk.Button(actions, text="打开 Web 状态页", command=self.open_web_status).pack(side="left")
        self._config_section(left, "流式兼容设置", self.CONFIG_FIELDS["codex"])
        for key, label in (
            ("codex_openai", "OpenAI"),
            ("codex_chatgpt", "ChatGPT"),
            ("codex_port", "端口"),
            ("codex_restart", "重启"),
        ):
            self.detail_vars[key] = tk.StringVar(value=f"{label}：-")
            ttk.Label(right, textvariable=self.detail_vars[key], wraplength=300, justify="left").pack(anchor="w", fill="x", pady=4)
        ttk.Label(
            right,
            text="端口变更保存后需要通过诊断页确认后台已使用新配置。",
            foreground="#6b7280",
            wraplength=300,
            justify="left",
        ).pack(anchor="w", fill="x", pady=(12, 0))

    def _build_diagnostics_page(self) -> None:
        page = self._new_page("diagnostics")
        top = ttk.PanedWindow(page, orient="horizontal")
        top.pack(fill="both", expand=True)

        left = ttk.Frame(top)
        right = ttk.Frame(top)
        top.add(left, weight=2)
        top.add(right, weight=3)

        service = ttk.LabelFrame(left, text="运行诊断", padding=14)
        service.pack(fill="x", pady=(0, 14))
        self.detail_vars["diagnostics"] = tk.StringVar(value="-")
        ttk.Label(service, textvariable=self.detail_vars["diagnostics"], justify="left", wraplength=330).pack(anchor="w", fill="x")

        tools = ttk.LabelFrame(left, text="修复工具", padding=14)
        tools.pack(fill="x")
        ttk.Button(tools, text="启动 / 修复服务", command=self.repair).pack(fill="x", pady=(0, 8))
        ttk.Button(tools, text="应用运行时更新", command=self.apply_update).pack(fill="x", pady=(0, 8))
        ttk.Button(tools, text="打开日志文件", command=self.open_log).pack(fill="x", pady=(0, 8))
        ttk.Button(tools, text="打开 Web 状态页", command=self.open_web_status).pack(fill="x")

        log_panel = ttk.LabelFrame(right, text="操作日志", padding=10)
        log_panel.pack(fill="both", expand=True)
        self.log_box = scrolledtext.ScrolledText(log_panel, height=18, wrap="word")
        self.log_box.pack(fill="both", expand=True)

    def _build_advanced_page(self) -> None:
        page = self._new_page("advanced")
        pane = ttk.PanedWindow(page, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane)
        right = ttk.LabelFrame(pane, text="变更影响", padding=14)
        pane.add(left, weight=2)
        pane.add(right, weight=1)
        self._config_section(left, "高级运行参数", self.CONFIG_FIELDS["advanced"])
        for key, label in (
            ("advanced_restart", "重启"),
            ("advanced_stream", "流式"),
            ("advanced_session", "会话"),
            ("advanced_save", "保存"),
        ):
            self.detail_vars[key] = tk.StringVar(value=f"{label}：-")
            ttk.Label(right, textvariable=self.detail_vars[key], wraplength=300, justify="left").pack(anchor="w", fill="x", pady=4)
        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Button(right, text="打开日志文件", command=self.open_log).pack(fill="x", pady=(0, 6))
        ttk.Button(right, text="打开 Web 状态页", command=self.open_web_status).pack(fill="x")

    def _config_section(self, parent: tk.Widget, title: str, fields: tuple) -> None:
        section = ttk.LabelFrame(parent, text=title, padding=16)
        section.pack(fill="x", anchor="n")
        for row, (key, label, field_type, choices) in enumerate(fields):
            section.columnconfigure(1, weight=1)
            if field_type == "check":
                var = self._config_var(key)
                ttk.Checkbutton(section, text=label, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
                continue
            ttk.Label(section, text=label).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=6)
            var = self._config_var(key)
            if field_type == "choice":
                widget = ttk.Combobox(section, textvariable=var, values=choices, state="readonly")
            else:
                widget = ttk.Entry(section, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", pady=6)

    def _config_var(self, key: str) -> Union[tk.StringVar, tk.BooleanVar]:
        if key not in self.config_vars:
            default = proxy_config.DEFAULTS.get(key, "")
            if isinstance(default, bool):
                self.config_vars[key] = tk.BooleanVar(value=default)
            else:
                self.config_vars[key] = tk.StringVar(value=str(default))
        return self.config_vars[key]

    def show_page(self, page: str) -> None:
        if page not in self.pages:
            return
        self.current_page.set(page)
        title, subtitle = self.PAGE_META[page]
        self.page_title.set(title)
        self.page_subtitle.set(subtitle)
        for key, frame in self.pages.items():
            frame.pack_forget()
            button = self.nav_buttons.get(key)
            if button:
                active = key == page
                button.configure(
                    bg="#e8eefc" if active else "#f4f5f7",
                    fg="#0b57d0" if active else "#1f2937",
                    font=("Helvetica", 13, "bold" if active else "normal"),
                )
        self.pages[page].pack(fill="both", expand=True)
        if page in self.CONFIG_PAGES:
            if not self.footer.winfo_ismapped():
                self.footer.pack(side="bottom", fill="x", pady=(12, 0))
        else:
            self.footer.pack_forget()

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        if hasattr(self, "log_box"):
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
            if proxy:
                detail = http_json(STATUS_PATH, timeout=2)
                if isinstance(detail, dict) and not detail.get("error"):
                    proxy = {**proxy, **detail}
            accounts = self._read_accounts(proxy_online=bool(proxy))
            self.accounts = accounts
            self._render_accounts(accounts)
            self._render_status(service, codex, proxy, accounts)
            self._load_config_form()
            lines = [
                f"代理：{'在线' if proxy else '离线'}",
                f"账号：{sum(1 for item in accounts if self._is_active(item))}/{len(accounts)} 可用",
                f"Codex：{codex.get('mode')}",
            ]
            if service.get("needs_repair"):
                lines.append("建议修复服务")
            self.status.set("\n".join(lines))
        except Exception as exc:
            self.status.set(f"状态读取失败：{exc}")

    def _render_status(self, service: dict, codex: dict, proxy: Optional[dict], accounts: list[dict]) -> None:
        active_accounts = sum(1 for item in accounts if self._is_active(item))
        try:
            cfg = proxy_config.load()
        except Exception:
            cfg = dict(proxy_config.DEFAULTS)
        self.metric_vars["proxy"].set("在线" if proxy else "离线")
        self.metric_vars["service"].set(
            f"{'运行中' if service.get('loaded') else '已停止'} / {'已安装' if service.get('installed') else '未安装'}"
        )
        self.metric_vars["codex"].set(str(codex.get("mode") or "-"))
        self.metric_vars["accounts"].set(f"{active_accounts} / {len(accounts)}")
        self.metric_vars["requests"].set(str((proxy or {}).get("stats", {}).get("total_requests", "-")))
        self.metric_vars["runtime"].set(str(service.get("runtime_dir") or "-"))
        self.detail_vars["codex_proxy"].set(
            f"当前模式：{codex.get('mode') or '-'}\n"
            f"配置文件：{codex_config.CODEX_CONFIG_PATH}\n"
            f"目标地址：{API_ROOT}"
        )
        self.codex_proxy_enabled.set(bool(codex.get("enabled")))
        repair_line = (
            f"\n建议修复：LaunchAgent 当前指向 {service.get('installed_program')}"
            if service.get("needs_repair")
            else ""
        )
        self.detail_vars["diagnostics"].set(
            f"服务：{'运行中' if service.get('loaded') else '已停止'}\n"
            f"安装：{'已安装' if service.get('installed') else '未安装'}\n"
            f"运行时：{service.get('runtime_dir') or '-'}\n"
            f"日志：{service_manager.LOG_PATH}{repair_line}"
        )
        errors = (proxy or {}).get("recent_errors") or []
        repair_needed = bool(service.get("needs_repair") or (proxy or {}).get("version_mismatch"))
        tracker = (proxy or {}).get("quota_tracker") or {}
        if tracker:
            interval = int(float(tracker.get("interval") or 0))
            interval_text = f"{max(1, interval // 60)} 分钟" if interval >= 60 else f"{interval} 秒"
            last_run = format_epoch(tracker.get("last_run_at")) if tracker.get("last_run_at") else "尚未刷新"
            quota_text = f"{interval_text} · 上次 {last_run}" if tracker.get("enabled") else "自动刷新关闭"
        else:
            quota_text = "等待额度刷新"
        self._set_detail("overview_service", f"后台：{'在线，正在接管本机请求' if proxy else '离线，先启动/修复'}")
        self._set_detail("overview_accounts", f"账号：{active_accounts}/{len(accounts)} 可用")
        self._set_detail("overview_repair", f"修复：{'需要处理，见诊断页' if repair_needed else '无待处理修复'}")
        self._set_detail("overview_errors", f"错误：{len(errors)} 条最近错误" if errors else "错误：暂无最近错误")
        self._set_detail("overview_quota", f"额度：{quota_text}")

        cooldown_count = sum(1 for item in accounts if item.get("rate_limited"))
        strategy = cfg.get("rotation_strategy") or (proxy or {}).get("strategy") or "most_available"
        strategy_label = "额度优先" if strategy == "most_available" else "轮询"
        self._set_detail("routing_strategy", f"当前策略：{strategy_label}")
        self._set_detail("routing_cooldown", f"冷却账号：{cooldown_count} 个")
        self._set_detail("routing_refresh", f"额度刷新：{quota_text}")
        self._set_detail("routing_window", f"窗口权重：5h {float(cfg.get('quota_weight_5h', 0)):.2f} / 7d {float(cfg.get('quota_weight_7d', 0)):.2f}")

        port = int(cfg.get("port") or 8800)
        openai_base = (proxy or {}).get("codex_expected_base_url") or f"http://127.0.0.1:{port}/v1"
        chatgpt_base = f"http://127.0.0.1:{port}/backend-api/"
        self._set_detail("codex_openai", f"OpenAI：{openai_base}")
        self._set_detail("codex_chatgpt", f"ChatGPT：{chatgpt_base}")
        self._set_detail("codex_port", f"端口：{port} · {'后台在线' if proxy else '后台离线'}")
        self._set_detail("codex_restart", f"重启：{'建议修复/重启后确认' if repair_needed else '当前无需重启'}")

        self._set_detail("advanced_restart", f"重启：端口 {port}、请求体和上游网络项保存后以后台状态为准")
        self._set_detail("advanced_stream", f"流式：{cfg.get('codex_stream_mode')} · keepalive {cfg.get('stream_keepalive_seconds')}s")
        session_text = (
            f"开启 · TTL {cfg.get('session_affinity_ttl_seconds')}s"
            if cfg.get("session_affinity_enabled")
            else "关闭，会按策略重新选择账号"
        )
        self._set_detail("advanced_session", f"会话：{session_text}")
        self._set_detail("advanced_save", f"保存：{'保存后尝试热应用' if proxy else '后台离线时写入本地配置'}")
        self._render_recent(proxy or {})

    def _set_detail(self, key: str, value: str) -> None:
        var = self.detail_vars.get(key)
        if var is not None:
            var.set(value)

    def _render_recent(self, proxy: dict) -> None:
        recent = (proxy.get("recent_requests") or [])[:10]
        if recent:
            lines = []
            for row in recent:
                at = time.strftime("%H:%M:%S", time.localtime(float(row.get("at") or 0))) if row.get("at") else "-"
                lines.append(
                    f"{at}  {row.get('account') or '-'}  {row.get('status') or '-'}  "
                    f"{row.get('stream_mode') or row.get('transport') or '-'}  {row.get('path') or '-'}"
                )
            self._set_text(self.recent_box, "\n".join(lines))
        else:
            self._set_text(self.recent_box, "暂无请求记录。")

        errors = (proxy.get("recent_errors") or [])[:8]
        alerts = []
        if errors:
            for row in errors:
                at = time.strftime("%H:%M:%S", time.localtime(float(row.get("at") or 0))) if row.get("at") else "-"
                alerts.append(f"{at}  {row.get('account') or '-'}  {row.get('error') or '-'}  {row.get('path') or '-'}")
        if proxy.get("usage") and not proxy.get("usage", {}).get("observed_columns_ok", True):
            alerts.append("Token 使用量存储需要诊断。")
        self._set_text(self.alert_box, "\n".join(alerts) if alerts else "暂无错误。")

    def _set_text(self, widget: scrolledtext.ScrolledText, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")

    def _read_accounts(self, *, proxy_online: bool) -> list[dict]:
        if proxy_online:
            remote = http_json("/api/accounts", timeout=2)
            if isinstance(remote, list):
                return remote
        return local_accounts()

    def _render_accounts(self, accounts: list[dict]) -> None:
        selected = self.selected_account()
        for item in self.account_tree.get_children():
            self.account_tree.delete(item)
        selected_iid = ""
        for account in accounts:
            name = str(account.get("name") or "")
            iid = self.account_tree.insert(
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
            self.account_tree.selection_set(selected_iid)
        self._update_account_actions()

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
        selection = self.account_tree.selection()
        if not selection:
            return ""
        values = self.account_tree.item(selection[0], "values")
        return str(values[0]) if values else ""

    def require_selected(self) -> str:
        name = self.selected_account()
        if not name:
            raise ValueError("请先选择一个账号。")
        return validate_account_name(name)

    def _selected_account_data(self) -> Optional[dict]:
        name = self.selected_account()
        if not name:
            return None
        return next((item for item in self.accounts if str(item.get("name") or "") == name), None)

    def _update_account_actions(self) -> None:
        account = self._selected_account_data()
        state = "normal" if account else "disabled"
        for button in self.account_action_buttons:
            button.configure(state=state)
        if not hasattr(self, "account_detail"):
            return
        if not account:
            self.account_detail.set("未选择账号。\n请在左侧列表中选择账号后再执行上下文操作。")
            return
        self.account_detail.set(
            f"名称：{account.get('name') or '-'}\n"
            f"Email：{account.get('email') or '-'}\n"
            f"状态：{self._state_label(account)}\n"
            f"冷却：{self._cooldown_label(account)}\n"
            f"Token：{self._expiry_label(account.get('expires_at'))}"
        )

    def repair(self) -> None:
        if not messagebox.askyesno(
            "启动 / 修复服务",
            "这会安装或修复 LaunchAgent，并可能启动代理服务。继续吗？",
        ):
            return

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

        self.run_bg("正在启动或修复代理服务", work)

    def apply_update(self) -> None:
        if not messagebox.askyesno(
            "应用运行时更新",
            "这会同步运行时副本并重启一次代理。正在进行的 Codex 请求可能会中断。继续吗？",
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

        self.run_bg("正在应用运行时更新", work)

    def scan_accounts(self) -> None:
        def work() -> dict:
            proxy = proxy_status()
            if proxy:
                result = http_json("/api/accounts/scan", method="POST", timeout=4)
                return {"action": "remote_scan", "total_accounts": len(result) if isinstance(result, list) else None}
            return {"action": "local_scan", "total_accounts": len(local_accounts()), "running": False}

        self.run_bg("正在扫描账号", work)

    def toggle_selected(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("启用 / 禁用账号", str(exc))
            return

        def work() -> dict:
            if proxy_status():
                result = http_json(f"/api/accounts/{name}/toggle", method="PUT", timeout=4)
                return {"action": "toggle", "running": True, "enabled": result.get("enabled") if isinstance(result, dict) else None}
            account = load_local_account(name)
            account.enabled = not account.enabled
            account.save_meta()
            return {"action": "toggle_local", "running": False, "enabled": account.enabled}

        self.run_bg("正在切换账号状态", work)

    def refresh_selected_token(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("刷新 Token", str(exc))
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

        self.run_bg("正在刷新 Token", work)

    def clear_selected_cooldown(self) -> None:
        try:
            name = self.require_selected()
        except Exception as exc:
            messagebox.showerror("清除冷却", str(exc))
            return

        def work() -> dict:
            if not proxy_status():
                return {"action": "clear_cooldown_skipped", "running": False}
            result = http_json(f"/api/accounts/{name}/cooldown/clear", method="PUT", timeout=4)
            return {"action": "clear_cooldown", "running": True, "enabled": result.get("enabled") if isinstance(result, dict) else None}

        self.run_bg("正在清除冷却", work)

    def login_command(self) -> None:
        name = simpledialog.askstring("登录新账号", "账号名称：")
        if not name:
            return
        try:
            safe_name = validate_account_name(name)
            target = account_dir(safe_name)
            target.mkdir(parents=True, exist_ok=True)
            codex_cli = find_codex_cli() or "/Applications/Codex.app/Contents/Resources/codex"
            command = f"CODEX_HOME={target} {codex_cli} login"
            self.log("在终端运行这条命令，登录完成后点击“扫描”：")
            self.log(command)
            self.root.clipboard_clear()
            self.root.clipboard_append(command)
            messagebox.showinfo("登录新账号", "登录命令已复制到剪贴板，并写入诊断日志。")
        except Exception as exc:
            messagebox.showerror("登录新账号", str(exc))

    def copy_selected_login_command(self) -> None:
        try:
            name = self.require_selected()
            target = account_dir(name)
            codex_cli = find_codex_cli() or "/Applications/Codex.app/Contents/Resources/codex"
            command = f"CODEX_HOME={target} {codex_cli} login"
            self.root.clipboard_clear()
            self.root.clipboard_append(command)
            self.log("所选账号登录命令已复制：")
            self.log(command)
            messagebox.showinfo("复制登录命令", "所选账号的登录命令已复制到剪贴板。")
        except Exception as exc:
            messagebox.showerror("复制登录命令", str(exc))

    def import_current_account(self) -> None:
        name = simpledialog.askstring("导入当前账号", "将当前 ~/.codex/auth.json 保存为账号名称：")
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

        self.run_bg("正在导入当前 Codex 认证", work)

    def enable_codex_proxy(self) -> None:
        def work() -> dict:
            result = codex_config.ensure_enabled(True)
            result["action"] = "enable_codex_proxy"
            return result

        self.run_bg("正在写入 Codex 代理配置", work)

    def open_web_status(self) -> None:
        def work() -> dict:
            proxy = proxy_status()
            if not proxy:
                return {"action": "open_web_skipped", "running": False}
            subprocess.run(["open", APP_URL], check=False)
            return {"action": "open_web_status", "running": True}

        self.run_bg("正在打开 Web 状态页", work)

    def open_codex(self) -> None:
        def work() -> dict:
            codex = codex_config.ensure_enabled(True)
            proxy = proxy_status()
            if not proxy:
                self.root.after(0, self.log, "代理离线；如需账号池流量，请先在诊断页启动 / 修复服务。")
            subprocess.run(["open", "-a", "Codex"], check=False)
            return {"action": "open_codex", "enabled": codex.get("enabled"), "mode": codex.get("mode"), "running": bool(proxy)}

        self.run_bg("正在打开 Codex", work)

    def open_log(self) -> None:
        log_path = Path(service_manager.LOG_PATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if not log_path.exists():
            log_path.touch()
        subprocess.run(["open", str(log_path)], check=False)

    def _load_config_form(self) -> None:
        try:
            cfg = proxy_config.load()
        except Exception as exc:
            self.log(f"配置读取失败：{exc}")
            cfg = dict(proxy_config.DEFAULTS)
        for key, var in self.config_vars.items():
            value = cfg.get(key, proxy_config.DEFAULTS.get(key, ""))
            if isinstance(var, tk.BooleanVar):
                var.set(bool(value))
            else:
                var.set(str(value))
        try:
            self.codex_proxy_enabled.set(bool(codex_config.status().get("enabled")))
        except Exception:
            pass

    def _page_config_keys(self, page: str) -> list[str]:
        return [key for key, *_rest in self.CONFIG_FIELDS.get(page, ())]

    def _coerce_config_value(self, key: str):
        var = self.config_vars[key]
        default = proxy_config.DEFAULTS.get(key)
        value = var.get()
        if isinstance(default, bool):
            return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            return int(str(value).strip())
        if isinstance(default, float):
            return float(str(value).strip())
        return str(value).strip()

    def save_current_settings(self) -> None:
        page = self.current_page.get()
        keys = self._page_config_keys(page)
        if page not in self.CONFIG_PAGES:
            return
        try:
            body = {key: self._coerce_config_value(key) for key in keys}
            if "quota_tracker_enabled" in body:
                body["quota_tracker_user_set"] = True
            if "codex_stream_mode" in body:
                body["codex_stream_mode_user_set"] = True
            if proxy_status():
                result = http_json("/api/config", method="PUT", body=body, timeout=4)
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(str(result.get("error")))
                if not isinstance(result, dict):
                    raise RuntimeError("代理未返回有效配置结果。")
            else:
                cfg = proxy_config.load()
                cfg.update(body)
                proxy_config.save(cfg)
            if page == "codex":
                codex_config.ensure_enabled(bool(self.codex_proxy_enabled.get()))
            self.log(f"已保存设置：{self.PAGE_META[page][0]}")
            messagebox.showinfo("保存设置", "设置已保存。")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("保存设置", str(exc))

    def restore_current_defaults(self) -> None:
        page = self.current_page.get()
        if page not in self.CONFIG_PAGES:
            return
        for key in self._page_config_keys(page):
            default = proxy_config.DEFAULTS.get(key, "")
            var = self.config_vars[key]
            if isinstance(var, tk.BooleanVar):
                var.set(bool(default))
            else:
                var.set(str(default))
        self.log(f"已恢复默认值（未保存）：{self.PAGE_META[page][0]}")


def main() -> None:
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
