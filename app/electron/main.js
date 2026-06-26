const ORIGINAL_XDG_SESSION_TYPE = String(process.env.XDG_SESSION_TYPE || "").toLowerCase();
const ORIGINAL_XDG_DESKTOP = `${process.env.XDG_CURRENT_DESKTOP || ""}:${process.env.XDG_SESSION_DESKTOP || ""}`.toLowerCase();
const WRAPPER_KDE_WAYLAND = process.env.DACHSHUND_KDE_WAYLAND === "1";
const FORCE_NATIVE_WAYLAND = process.env.DACHSHUND_NATIVE_WAYLAND === "1";
const IS_KDE_WAYLAND = process.platform === "linux"
  && (WRAPPER_KDE_WAYLAND || (ORIGINAL_XDG_SESSION_TYPE === "wayland" && /\b(kde|plasma)\b/.test(ORIGINAL_XDG_DESKTOP)));
const FORCE_ENABLE_TRAY = process.env.DACHSHUND_ENABLE_TRAY === "1";
const USE_XWAYLAND = IS_KDE_WAYLAND && !FORCE_NATIVE_WAYLAND && process.env.DACHSHUND_FORCE_XWAYLAND === "1";
const USE_NATIVE_WAYLAND = IS_KDE_WAYLAND && !USE_XWAYLAND;

if (USE_XWAYLAND) {
  process.env.DACHSHUND_KDE_WAYLAND = "1";
  process.env.GDK_BACKEND = "x11";
  process.env.ELECTRON_OZONE_PLATFORM_HINT = "x11";
  delete process.env.WAYLAND_DISPLAY;
  delete process.env.WAYLAND_SOCKET;
  process.env.XDG_SESSION_TYPE = "x11";
  process.env.DESKTOP_SESSION = "plasma";
}

const { app, BrowserWindow, Menu, Tray, ipcMain, shell, nativeImage, clipboard } = require("electron");
const { execFile } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");
const { pathToFileURL } = require("url");

if (USE_XWAYLAND) app.commandLine.appendSwitch("ozone-platform", "x11");
if (USE_NATIVE_WAYLAND) app.commandLine.appendSwitch("ozone-platform", "wayland");

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
}

const PROJECT_ROOT = path.resolve(__dirname, "../..");
const MAC_DIR = path.join(PROJECT_ROOT, "platforms", "mac");
const PLATFORM_DIR = path.join(PROJECT_ROOT, "platforms", process.platform === "win32" ? "windows" : process.platform === "darwin" ? "mac" : "linux");
const DEV_CORE_DIR = path.join(PROJECT_ROOT, "src", "core");
const DEFAULT_PORT = 18800;
const APP_SUPPORT_NAME = "dachshund";
const ACCOUNT_RE = /^[A-Za-z0-9_-]{1,64}$/;
const NAME_ACTIONS = new Set([
  "login-command",
  "start-login",
  "login-status",
  "import-current",
  "toggle-account",
  "delete-account",
  "refresh-token",
  "clear-cooldown",
  "clear-auth-error",
]);
const CONFIG_KEYS = new Set([
  "port",
  "rate_limit_cooldown",
  "rotation_strategy",
  "product_mode",
  "max_retries",
  "quota_refresh_interval",
  "quota_tracker_enabled",
  "max_request_body_mb",
  "upstream_connect_timeout_sec",
  "upstream_transient_retries",
  "upstream_transient_backoff_ms",
  "codex_stream_mode",
  "codex_hybrid_probe_seconds",
  "codex_hybrid_probe_bytes",
  "codex_stream_retry_cooldown",
  "stream_keepalive_seconds",
  "stream_bootstrap_retries",
  "nonstream_keepalive_interval",
  "websocket_heartbeat_seconds",
  "session_affinity_enabled",
  "session_affinity_ttl_seconds",
  "quota_weight_5h",
  "quota_weight_7d",
  "log_level",
]);
const ACTIONS = new Set([
  "status",
  "repair",
  "repair-open-web",
  "repair-open-codex",
  "restart-proxy",
  "apply-update",
  "enable-codex-proxy",
  "disable-codex-proxy",
  "open-log",
  "show-paths",
  "scan-accounts",
  "list-accounts",
  "login-command",
  "start-login",
  "import-current",
  "toggle-account",
  "delete-account",
  "refresh-token",
  "clear-cooldown",
  "clear-auth-error",
  "set-rotation-strategy",
  "set-codex-stream-mode",
  "set-config",
  "menubar-login-status",
  "enable-menubar-login",
  "disable-menubar-login",
]);
const API_PATHS = new Set([
  "/api/status",
  "/api/config",
  "/api/quota",
  "/api/quota/refresh",
  "/api/token-usage",
  "/api/token-usage/events?limit=80",
  "/api/status/recent/clear",
]);
const SAFE_PATH_KEYS = new Set([
  "log_path",
  "result_path",
  "runtime_dir",
  "accounts_dir",
  "config_path",
  "source_dir",
  "app_bundle",
]);

let tray = null;
let win = null;
let lastStatus = null;
let lastQuota = null;
let trayStatusTimer = null;

function shouldSkipTray() {
  return IS_KDE_WAYLAND && !FORCE_ENABLE_TRAY;
}

function shouldUseNativeKdeMenu() {
  return IS_KDE_WAYLAND && !FORCE_ENABLE_TRAY;
}

function runtimeDir() {
  if (process.platform === "darwin" && !app.isPackaged) return MAC_DIR;
  return app.getPath("userData");
}

function helperPath() {
  if (app.isPackaged) return path.join(process.resourcesPath, "runtime", "control_actions.py");
  return path.join(PROJECT_ROOT, "app", "platform", "control_actions.py");
}

function pythonPath() {
  return process.env.PYTHON || "/usr/bin/python3";
}

function appBundlePath() {
  if (!app.isPackaged) return "";
  if (process.platform !== "darwin") return path.dirname(process.execPath);
  return path.resolve(process.execPath, "../../..");
}

function appExecutablePath() {
  if (app.isPackaged && process.platform === "linux" && fs.existsSync("/usr/bin/dachshund")) {
    return "/usr/bin/dachshund";
  }
  return process.execPath;
}

function helperEnv() {
  const env = { ...process.env, PYTHONUNBUFFERED: "1" };
  const platformPath = app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "platforms", process.platform === "win32" ? "windows" : process.platform === "darwin" ? "mac" : "linux")
    : PLATFORM_DIR;
  if (app.isPackaged) {
    env.CODEX_PROXY_SOURCE_DIR = path.join(process.resourcesPath, "runtime");
    env.CODEX_PROXY_APP_BUNDLE = appBundlePath();
    env.CODEX_PROXY_APP_EXECUTABLE = appExecutablePath();
    env.CODEX_PROXY_CONFIG_DIR = app.getPath("userData");
    env.PYTHONPATH = [path.join(process.resourcesPath, "runtime"), platformPath, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  } else {
    env.CODEX_PROXY_SOURCE_DIR = PROJECT_ROOT;
    env.CODEX_PROXY_APP_EXECUTABLE = appExecutablePath();
    env.CODEX_PROXY_CONFIG_DIR = app.getPath("userData");
    env.PYTHONPATH = [DEV_CORE_DIR, platformPath, PROJECT_ROOT, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  }
  return env;
}

function actionArgs(action, payload = {}) {
  if (!ACTIONS.has(action)) throw new Error("unsupported action");
  const args = [helperPath(), action, "--format", "json"];
  if (NAME_ACTIONS.has(action)) {
    if (!ACCOUNT_RE.test(String(payload.name || ""))) throw new Error("invalid account name");
    args.push("--name", payload.name);
  }
  if (action === "set-rotation-strategy") {
    if (!["round_robin", "most_available"].includes(payload.strategy)) throw new Error("invalid strategy");
    args.push("--strategy", payload.strategy);
  }
  if (action === "set-codex-stream-mode") {
    if (!["realtime", "buffered", "hybrid"].includes(payload.mode)) throw new Error("invalid stream mode");
    args.push("--stream-mode", payload.mode);
  }
  if (action === "set-config") {
    const updates = payload.config || {};
    if (!updates || typeof updates !== "object" || Array.isArray(updates)) throw new Error("invalid config");
    for (const key of Object.keys(updates)) {
      if (!CONFIG_KEYS.has(key)) throw new Error(`unsupported config key: ${key}`);
    }
    args.push("--config-json", JSON.stringify(updates));
  }
  return args;
}

function runAction(action, payload = {}) {
  return new Promise((resolve) => {
    let args;
    try {
      args = actionArgs(action, payload);
    } catch (error) {
      resolve({ error: error.message });
      return;
    }
    execFile(pythonPath(), args, { cwd: runtimeDir(), env: helperEnv(), timeout: 90000 }, (error, stdout, stderr) => {
      const text = String(stdout || "").trim();
      try {
        const data = text ? JSON.parse(text) : {};
        if (error && !data.error) data.error = stderr || error.message;
        resolve(data);
      } catch (parseError) {
        resolve({ error: stderr || error?.message || parseError.message, raw: text });
      }
    });
  });
}

function openWithXdg(target) {
  return new Promise((resolve) => {
    execFile("xdg-open", [target], { env: helperEnv(), timeout: 15000 }, (error, _stdout, stderr) => {
      resolve(error ? { error: stderr || error.message } : { opened: true, path: target });
    });
  });
}

async function openExternalSafe(url) {
  if (IS_KDE_WAYLAND && process.platform === "linux") return openWithXdg(url);
  await shell.openExternal(url);
  return { opened: true };
}

async function openPathSafe(target) {
  if (IS_KDE_WAYLAND && process.platform === "linux") return openWithXdg(target);
  const result = await shell.openPath(target);
  return result ? { error: result } : { opened: true, path: target };
}

function apiRequest(method, apiPath, body) {
  if (!API_PATHS.has(apiPath)) return Promise.resolve({ error: "unsupported api path" });
  const port = Number(lastStatus?.config?.port || lastStatus?.port || DEFAULT_PORT);
  const data = body ? Buffer.from(JSON.stringify(body)) : null;
  return new Promise((resolve) => {
    const req = http.request({
      hostname: "127.0.0.1",
      port,
      path: apiPath,
      method,
      headers: data ? { "Content-Type": "application/json", "Content-Length": data.length } : {},
      timeout: 5000,
    }, (res) => {
      let text = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => { text += chunk; });
      res.on("end", () => {
        try {
          resolve(text ? JSON.parse(text) : { ok: true });
        } catch {
          resolve({ error: `invalid json from ${apiPath}`, status: res.statusCode, raw: text });
        }
      });
    });
    req.on("error", (error) => resolve({ error: error.message }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ error: "request timed out" });
    });
    if (data) req.write(data);
    req.end();
  });
}

async function snapshot() {
  const [status, accounts, paths] = await Promise.all([
    runAction("status"),
    runAction("list-accounts"),
    runAction("show-paths"),
  ]);
  lastStatus = status && !status.error ? status : lastStatus;
  const [apiStatus, quota, tokenUsage, tokenEvents] = await Promise.all([
    apiRequest("GET", "/api/status"),
    apiRequest("GET", "/api/quota"),
    apiRequest("GET", "/api/token-usage"),
    apiRequest("GET", "/api/token-usage/events?limit=80"),
  ]);
  if (quota && !quota.error) lastQuota = quota;
  return { status, accounts, paths, apiStatus, quota, tokenUsage, tokenEvents };
}

function createWindow({ show = true } = {}) {
  if (win) {
    if (show) win.show();
    return win;
  }
  const macWindowOptions = process.platform === "darwin" ? {
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    vibrancy: "sidebar",
    visualEffectState: "active",
    backgroundColor: "#00000000",
    transparent: true,
  } : {
    backgroundColor: "#f7f3ea",
  };
  win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 980,
    minHeight: 640,
    title: "Dachshund",
    show,
    hasShadow: true,
    ...macWindowOptions,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadFile(path.join(__dirname, "renderer", "index.html"));
  win.on("close", (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      win.hide();
    }
  });
  win.on("closed", () => { win = null; });
  return win;
}

function iconImage() {
  const trayIconPath = app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "static", "icons", "tray-dog-template.png")
    : path.join(DEV_CORE_DIR, "static", "icons", "tray-dog-template.png");
  const fallbackIconPath = app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "static", "icons", "dog-head.png")
    : path.join(DEV_CORE_DIR, "static", "icons", "dog-head.png");
  const icon = fs.existsSync(trayIconPath) ? trayIconPath : fallbackIconPath;
  const image = fs.existsSync(icon) ? nativeImage.createFromPath(icon) : nativeImage.createEmpty();
  const trayIcon = image.isEmpty() ? image : image.resize({ width: 18, height: 18 });
  trayIcon.setTemplateImage(false);
  return trayIcon;
}

function quotaMenuLabels(quota) {
  const rows = Object.values(quota || {}).map(quotaSummary).filter((row) => row.fiveHour.value != null && row.sevenDay.value != null);
  if (!rows.length) return ["5h -", "7d -"];
  const fiveHour = Math.round(rows.reduce((sum, row) => sum + row.fiveHour.value, 0));
  const sevenDay = Math.round(rows.reduce((sum, row) => sum + row.sevenDay.value, 0));
  const total = rows.length * 100;
  return [`5h ${fiveHour}/${total}%`, `7d ${sevenDay}/${total}%`];
}

function quotaSummary(data) {
  const rateLimit = data?.rate_limit || {};
  const primary = rateLimit.primary_window || null;
  const secondary = rateLimit.secondary_window || null;
  const fiveHour = quotaWindow(primary, data?.["5h_usage"]);
  let sevenDay = quotaWindow(secondary, data?.weekly_usage);
  if (usesSharedCodexWindow(data, primary, secondary)) sevenDay = quotaWindow(primary, data?.["5h_usage"]);
  return { fiveHour, sevenDay };
}

function quotaWindow(windowData, fallbackUsed) {
  const used = numberOrNull(windowData?.used_percent ?? fallbackUsed);
  return { value: used == null ? null : Math.max(0, Math.min(100, 100 - used)), used };
}

function usesSharedCodexWindow(data, primary, secondary) {
  const plan = String(data?.plan_type || "").toLowerCase();
  return ["free", "go"].includes(plan) && !hasDistinctWeeklyWindow(primary, secondary);
}

function hasDistinctWeeklyWindow(primary, secondary) {
  const secondarySeconds = numberOrNull(secondary?.limit_window_seconds);
  if (secondarySeconds == null || secondarySeconds < 604800 * 0.9) return false;
  const primarySeconds = numberOrNull(primary?.limit_window_seconds);
  return primarySeconds == null || Math.abs(secondarySeconds - primarySeconds) >= 60;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function updateMenu() {
  const running = lastStatus?.running ? "在线" : "离线";
  const proxy = lastStatus?.enabled ? "代理" : "直连";
  const quotaLabels = quotaMenuLabels(lastQuota);
  const menu = Menu.buildFromTemplate([
    { label: `Dachshund ${running} · ${proxy}`, click: () => {} },
    { label: quotaLabels[0], click: () => {} },
    { label: quotaLabels[1], click: () => {} },
    { type: "separator" },
    { label: "打开控制中心", click: () => createWindow({ show: true }) },
    { label: "启动或修复后台", click: async () => { lastStatus = await runAction("repair"); updateMenu(); } },
    { label: "重启代理", click: async () => { await runAction("restart-proxy"); lastStatus = await runAction("status"); updateMenu(); } },
    { type: "separator" },
    { label: "Codex 代理", click: async () => { lastStatus = await runAction("enable-codex-proxy"); updateMenu(); } },
    { label: "Codex 直连", click: async () => { lastStatus = await runAction("disable-codex-proxy"); updateMenu(); } },
    { label: "打开 Web UI", click: () => openExternalSafe(`http://127.0.0.1:${lastStatus?.config?.port || DEFAULT_PORT}/app`) },
    { label: "打开日志", click: () => runAction("open-log") },
    { type: "separator" },
    { label: "退出", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray?.setContextMenu(menu);
  tray?.setToolTip(`Dachshund · ${running}`);
}

async function createTray() {
  if (shouldSkipTray()) {
    console.warn("Dachshund tray disabled on KDE Wayland; set DACHSHUND_ENABLE_TRAY=1 to test tray support.");
    return false;
  }
  try {
    tray = new Tray(iconImage());
  } catch (error) {
    console.warn("Dachshund tray unavailable:", error.message);
    tray = null;
    return false;
  }
  lastStatus = await runAction("status");
  lastQuota = await apiRequest("GET", "/api/quota");
  updateMenu();
  trayStatusTimer = setInterval(async () => {
    lastStatus = await runAction("status");
    lastQuota = await apiRequest("GET", "/api/quota");
    updateMenu();
    win?.webContents.send("status:changed", lastStatus);
  }, 30000);
  return true;
}

function appMenu() {
  if (shouldUseNativeKdeMenu()) {
    return;
  }
  const firstMenu = process.platform === "darwin"
    ? { role: "appMenu" }
    : {
      label: "Dachshund",
      submenu: [
        { label: "Open Control Center", click: () => createWindow({ show: true }) },
        { type: "separator" },
        { label: "Quit", click: () => { app.isQuitting = true; app.quit(); } },
      ],
    };
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    firstMenu,
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
      ],
    },
    { role: "windowMenu" },
  ]));
}

ipcMain.handle("app:snapshot", () => snapshot());
ipcMain.handle("app:action", (_event, action, payload) => runAction(action, payload));
ipcMain.handle("app:api", (_event, method, apiPath, body) => apiRequest(method, apiPath, body));
ipcMain.handle("app:open-external", (_event, url) => {
  if (!/^https?:\/\//.test(String(url))) return { error: "unsupported url" };
  return openExternalSafe(url);
});
ipcMain.handle("app:open-path", async (_event, key) => {
  if (!SAFE_PATH_KEYS.has(key)) return { error: "unsupported path" };
  const paths = await runAction("show-paths");
  const target = paths[key];
  if (!target) return { error: "path not available" };
  return openPathSafe(target);
});
ipcMain.handle("app:clipboard-write", (_event, text) => {
  clipboard.writeText(String(text || ""));
  return { copied: true };
});
ipcMain.handle("app:asset", (_event, name) => {
  if (name !== "dog-head") return "";
  const icon = app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "static", "icons", "dog-head.png")
    : path.join(DEV_CORE_DIR, "static", "icons", "dog-head.png");
  return fs.existsSync(icon) ? pathToFileURL(icon).href : "";
});

app.whenReady().then(async () => {
  app.setName("Dachshund");
  const userDataPath = path.join(app.getPath("appData"), APP_SUPPORT_NAME);
  fs.mkdirSync(userDataPath, { recursive: true });
  app.setPath("userData", userDataPath);
  appMenu();
  const trayCreated = await createTray();
  if (!process.argv.includes("--menubar-only") || (!trayCreated && shouldSkipTray())) createWindow({ show: true });
  if (process.argv.includes("--show-window")) createWindow({ show: true });
  if (process.argv.includes("--quit")) {
    app.isQuitting = true;
    app.quit();
  }
});

app.on("second-instance", (_event, argv) => {
  if (argv.includes("--quit")) {
    app.isQuitting = true;
    app.quit();
    return;
  }
  if (argv.includes("--show-window") || !argv.includes("--menubar-only")) {
    const window = createWindow({ show: true });
    if (window.isMinimized()) window.restore();
    window.focus();
  }
});

app.on("window-all-closed", () => {});
app.on("before-quit", () => { app.isQuitting = true; });
