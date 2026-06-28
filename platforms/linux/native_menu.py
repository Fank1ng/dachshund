#!/usr/bin/env python3
"""KDE Wayland native tray/menu helper for Dachshund."""

from __future__ import annotations

import json
import os
import fcntl
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
except (ImportError, ValueError) as exc:
    print(f"native menu unavailable: {exc}", file=sys.stderr)
    raise SystemExit(1)


ROOT = Path(os.environ.get("CODEX_PROXY_SOURCE_DIR") or Path(__file__).resolve().parents[2])
CONTROL_ACTIONS = ROOT / "control_actions.py"
if not CONTROL_ACTIONS.exists():
    CONTROL_ACTIONS = ROOT / "app" / "platform" / "control_actions.py"
RUNTIME_DIR = Path(os.environ.get("CODEX_PROXY_CONFIG_DIR") or Path.home() / ".config" / "dachshund")
APP_EXECUTABLE = os.environ.get("CODEX_PROXY_APP_EXECUTABLE") or "/usr/bin/dachshund"
BUS_NAME = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
DEFAULT_PORT = 18800
LOCK_FILE = RUNTIME_DIR / "native-menu.lock"
LOCK_HANDLE = None
MENU_CACHE_SECONDS = 30
MENU_REVISION = 1
MENU_LABELS: tuple[str, ...] = ()
MENU_REFRESHED_AT = 0.0


SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
    <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
  </interface>
</node>
"""

DBUSMENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg name="id" type="i" direction="in"/>
      <arg name="name" type="s" direction="in"/>
      <arg name="value" type="v" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg name="events" type="a(isvu)" direction="in"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="updatesNeeded" type="ai" direction="out"/>
      <arg name="idErrors" type="ai" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
"""


def helper_env() -> dict[str, str]:
    runtime = str(ROOT)
    linux = str(ROOT / "platforms" / "linux")
    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "CODEX_PROXY_SOURCE_DIR": str(ROOT),
        "CODEX_PROXY_CONFIG_DIR": str(RUNTIME_DIR),
        "CODEX_PROXY_APP_EXECUTABLE": APP_EXECUTABLE,
        "PYTHONPATH": os.pathsep.join([runtime, linux, os.environ.get("PYTHONPATH", "")]),
    }


def run_action(action: str) -> dict:
    try:
        result = subprocess.run(
            [sys.executable, str(CONTROL_ACTIONS), action, "--format", "json"],
            cwd=str(RUNTIME_DIR),
            env=helper_env(),
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        return json.loads((result.stdout or "{}").strip() or "{}")
    except Exception as exc:
        return {"error": str(exc)}


def current_port() -> int:
    status = run_action("status")
    try:
        return int((status.get("config") or {}).get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def api_get(path: str, port: int | None = None) -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port or current_port()}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return {"error": str(exc)}


def number_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def quota_window(window_data, fallback_used) -> dict[str, float | None]:
    data = window_data or {}
    used = number_or_none(data.get("used_percent"))
    if used is None:
        used = number_or_none(fallback_used)
    if used is None:
        return {"value": None, "used": None}
    return {"value": max(0, min(100, 100 - used)), "used": used}


def has_distinct_weekly_window(primary, secondary) -> bool:
    secondary_seconds = number_or_none((secondary or {}).get("limit_window_seconds"))
    if secondary_seconds is None or secondary_seconds < 604800 * 0.9:
        return False
    primary_seconds = number_or_none((primary or {}).get("limit_window_seconds"))
    return primary_seconds is None or abs(secondary_seconds - primary_seconds) >= 60


def uses_shared_codex_window(data: dict, primary, secondary) -> bool:
    plan = str(data.get("plan_type") or "").lower()
    return plan in {"free", "go"} and not has_distinct_weekly_window(primary, secondary)


def quota_summary(data: dict) -> dict[str, dict[str, float | None]]:
    rate_limit = data.get("rate_limit") or {}
    primary = rate_limit.get("primary_window") or None
    secondary = rate_limit.get("secondary_window") or None
    five_hour = quota_window(primary, data.get("5h_usage"))
    seven_day = quota_window(secondary, data.get("weekly_usage"))
    if uses_shared_codex_window(data, primary, secondary):
        seven_day = quota_window(primary, data.get("5h_usage"))
    return {"five_hour": five_hour, "seven_day": seven_day}


def quota_menu_labels(quota: dict | None) -> tuple[str, str]:
    rows = []
    for data in (quota or {}).values():
        if not isinstance(data, dict):
            continue
        summary = quota_summary(data)
        if summary["five_hour"]["value"] is not None and summary["seven_day"]["value"] is not None:
            rows.append(summary)
    if not rows:
        return ("5h -", "7d -")
    five_hour = js_round(sum(row["five_hour"]["value"] or 0 for row in rows))
    seven_day = js_round(sum(row["seven_day"]["value"] or 0 for row in rows))
    total = len(rows) * 100
    return (f"5h {five_hour}/{total}%", f"7d {seven_day}/{total}%")


def js_round(value: float) -> int:
    return int(value + 0.5)


def status_label(status: dict | None) -> str:
    status = status or {}
    running = "在线" if status.get("running") else "离线"
    proxy = "代理" if status.get("enabled") else "直连"
    return f"Dachshund {running} · {proxy}"


def current_menu_labels() -> tuple[str, ...]:
    global MENU_LABELS, MENU_REFRESHED_AT
    now = time.monotonic()
    if MENU_LABELS and now - MENU_REFRESHED_AT < MENU_CACHE_SECONDS:
        return MENU_LABELS
    return refresh_menu_labels()


def refresh_menu_labels() -> tuple[str, ...]:
    global MENU_LABELS, MENU_REFRESHED_AT
    status = run_action("status")
    port = DEFAULT_PORT
    try:
        port = int((status.get("config") or {}).get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        pass
    quota = api_get("/api/quota", port=port) if status and not status.get("error") else {}
    quota_labels = quota_menu_labels(quota)
    MENU_LABELS = (status_label(status), *quota_labels)
    MENU_REFRESHED_AT = time.monotonic()
    return MENU_LABELS


def refresh_menu(connection: Gio.DBusConnection | None = None, *, force: bool = False) -> bool:
    global MENU_REVISION, MENU_REFRESHED_AT
    previous = MENU_LABELS
    if force:
        MENU_REFRESHED_AT = 0
    labels = current_menu_labels()
    changed = labels != previous
    if changed:
        MENU_REVISION += 1
        if connection is not None:
            connection.emit_signal(None, MENU_PATH, "com.canonical.dbusmenu", "LayoutUpdated", GLib.Variant("(ui)", (MENU_REVISION, 0)))
    return changed


def open_url(url: str) -> None:
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_control_center() -> None:
    subprocess.Popen([APP_EXECUTABLE, "--show-window"], env=helper_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def quit_apps(loop: GLib.MainLoop) -> None:
    subprocess.Popen([APP_EXECUTABLE, "--quit"], env=helper_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    loop.quit()


def menu_rows(loop: GLib.MainLoop) -> list[tuple[int, str, str]]:
    status, five_hour, seven_day = current_menu_labels()
    return [
        (9, status, ""),
        (10, five_hour, ""),
        (11, seven_day, ""),
        (0, "", ""),
        (1, "打开控制中心", "open-window"),
        (0, "", ""),
        (2, "启动/修复", "repair"),
        (3, "重启代理", "restart-proxy"),
        (0, "", ""),
        (4, "Codex 代理", "enable-codex-proxy"),
        (5, "Codex 直连", "disable-codex-proxy"),
        (6, "打开 Web UI", "open-web"),
        (7, "打开日志", "open-log"),
        (0, "", ""),
        (8, "退出", "quit"),
    ]


def item_properties(item_id: int, label: str) -> dict[str, GLib.Variant]:
    if item_id == 0:
        return {"type": GLib.Variant("s", "separator")}
    return {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True), "visible": GLib.Variant("b", True)}


def menu_layout(loop: GLib.MainLoop) -> GLib.Variant:
    children = [GLib.Variant("(ia{sv}av)", (item_id, item_properties(item_id, label), [])) for item_id, label, _ in menu_rows(loop)]
    return GLib.Variant("(ia{sv}av)", (0, {}, children))


def activate(action: str, loop: GLib.MainLoop) -> None:
    if action == "open-window":
        open_control_center()
    elif action in {"repair", "restart-proxy", "enable-codex-proxy", "disable-codex-proxy", "open-log"}:
        run_action(action)
    elif action == "open-web":
        open_url(f"http://127.0.0.1:{current_port()}/app")
    elif action == "quit":
        quit_apps(loop)


def action_for_id(item_id: int, loop: GLib.MainLoop) -> str:
    for row_id, _label, action in menu_rows(loop):
        if row_id == item_id:
            return action
    return ""


def sni_method(_connection, _sender, _object_path, _interface, method, _params, invocation, loop: GLib.MainLoop) -> None:
    if method in {"Activate", "SecondaryActivate"}:
        open_control_center()
    invocation.return_value(None)


def sni_property(_connection, _sender, _object_path, _interface, prop):
    values = {
        "Category": GLib.Variant("s", "ApplicationStatus"),
        "Id": GLib.Variant("s", "dachshund"),
        "Title": GLib.Variant("s", "Dachshund"),
        "Status": GLib.Variant("s", "Active"),
        "WindowId": GLib.Variant("u", 0),
        "IconName": GLib.Variant("s", "dachshund"),
        "IconThemePath": GLib.Variant("s", ""),
        "Menu": GLib.Variant("o", MENU_PATH),
        "ItemIsMenu": GLib.Variant("b", True),
    }
    return values.get(prop)


def dbusmenu_method(connection, _sender, _object_path, _interface, method, params, invocation, loop: GLib.MainLoop) -> None:
    if method == "GetLayout":
        refresh_menu(connection)
        invocation.return_value(GLib.Variant.new_tuple(GLib.Variant("u", MENU_REVISION), menu_layout(loop)))
    elif method == "GetGroupProperties":
        refresh_menu(connection)
        ids = params.unpack()[0]
        rows = [(item_id, item_properties(item_id, label)) for item_id, label, _ in menu_rows(loop) if not ids or item_id in ids]
        invocation.return_value(GLib.Variant("(a(ia{sv}))", (rows,)))
    elif method == "GetProperty":
        refresh_menu(connection)
        item_id, name = params.unpack()
        props = {}
        for row_id, label, _action in menu_rows(loop):
            if row_id == item_id:
                props = item_properties(row_id, label)
                break
        invocation.return_value(GLib.Variant("(v)", (props.get(name, GLib.Variant("s", "")),)))
    elif method == "Event":
        item_id, event_id, _data, _timestamp = params.unpack()
        if event_id == "clicked":
            activate(action_for_id(item_id, loop), loop)
            refresh_menu(connection, force=True)
        invocation.return_value(None)
    elif method == "EventGroup":
        events = params.unpack()[0]
        for item_id, event_id, _data, _timestamp in events:
            if event_id == "clicked":
                activate(action_for_id(item_id, loop), loop)
        refresh_menu(connection, force=True)
        invocation.return_value(GLib.Variant("(ai)", ([],)))
    elif method == "AboutToShow":
        changed = refresh_menu(connection, force=True)
        invocation.return_value(GLib.Variant("(b)", (changed,)))
    elif method == "AboutToShowGroup":
        ids = params.unpack()[0]
        changed = refresh_menu(connection, force=True)
        invocation.return_value(GLib.Variant("(aiai)", (ids if changed else [], [])))
    else:
        invocation.return_dbus_error("com.fank1ng.dachshund.Unsupported", f"unsupported method: {method}")


def dbusmenu_property(_connection, _sender, _object_path, _interface, prop):
    values = {
        "Version": GLib.Variant("u", 4),
        "TextDirection": GLib.Variant("s", "ltr"),
        "Status": GLib.Variant("s", "normal"),
        "IconThemePath": GLib.Variant("as", []),
    }
    return values.get(prop)


def register_watcher(connection: Gio.DBusConnection, *, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while True:
        try:
            proxy = Gio.DBusProxy.new_sync(
                connection,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                None,
            )
            proxy.call_sync("RegisterStatusNotifierItem", GLib.Variant("(s)", (BUS_NAME,)), Gio.DBusCallFlags.NONE, 5000, None)
            return True
        except Exception as exc:
            last_error = str(exc)
            if time.monotonic() >= deadline:
                print(f"status notifier watcher unavailable: {last_error}", file=sys.stderr)
                return False
            time.sleep(1)


def main() -> int:
    global LOCK_HANDLE
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_HANDLE = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(LOCK_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    LOCK_HANDLE.write(str(os.getpid()))
    LOCK_HANDLE.flush()
    loop = GLib.MainLoop()
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    owner_id = Gio.bus_own_name_on_connection(connection, BUS_NAME, Gio.BusNameOwnerFlags.DO_NOT_QUEUE, None, None)
    if owner_id == 0:
        return 0
    sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
    menu_info = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML).interfaces[0]
    connection.register_object(ITEM_PATH, sni_info, lambda *args: sni_method(*args, loop), lambda *args: sni_property(*args), None)
    connection.register_object(MENU_PATH, menu_info, lambda *args: dbusmenu_method(*args, loop), lambda *args: dbusmenu_property(*args), None)
    if not register_watcher(connection):
        return 1
    loop.run()
    Gio.bus_unown_name(owner_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
