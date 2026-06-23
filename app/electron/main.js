const { app, BrowserWindow, Menu, Tray, ipcMain, shell, nativeImage } = require("electron");
const { execFile } = require("child_process");
const fs = require("fs");
const http = require("http");
const path = require("path");
const { pathToFileURL } = require("url");

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

function helperEnv() {
  const env = { ...process.env, PYTHONUNBUFFERED: "1" };
  const platformPath = app.isPackaged
    ? path.join(process.resourcesPath, "runtime", "platforms", process.platform === "win32" ? "windows" : process.platform === "darwin" ? "mac" : "linux")
    : PLATFORM_DIR;
  if (app.isPackaged) {
    env.CODEX_PROXY_SOURCE_DIR = path.join(process.resourcesPath, "runtime");
    env.CODEX_PROXY_APP_BUNDLE = appBundlePath();
    env.CODEX_PROXY_APP_EXECUTABLE = process.execPath;
    env.CODEX_PROXY_CONFIG_DIR = app.getPath("userData");
    env.PYTHONPATH = [path.join(process.resourcesPath, "runtime"), platformPath, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
  } else {
    env.CODEX_PROXY_SOURCE_DIR = PROJECT_ROOT;
    env.CODEX_PROXY_APP_EXECUTABLE = process.execPath;
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
  win = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 980,
    minHeight: 640,
    title: "Dachshund",
    show,
    titleBarStyle: "hiddenInset",
    trafficLightPosition: { x: 16, y: 16 },
    vibrancy: "sidebar",
    visualEffectState: "active",
    backgroundColor: "#00000000",
    transparent: true,
    hasShadow: true,
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

const TRAY_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36">
  <defs>
    <mask id="eyes">
      <rect width="36" height="36" fill="white"/>
      <circle cx="14" cy="15.5" r="2.1" fill="black"/>
      <circle cx="22" cy="15.5" r="2.1" fill="black"/>
    </mask>
  </defs>
  <path fill="black" mask="url(#eyes)" d="M8.3 12.3C4.9 13.9 3 17.4 3.7 21.4c.5 3.2 2.5 5.9 5.8 7.9 1.8-2.3 2.5-6.5 1.8-10.9 1.7-1.7 4-2.6 6.7-2.6s5 .9 6.7 2.6c-.7 4.4 0 8.6 1.8 10.9 3.3-2 5.3-4.7 5.8-7.9.7-4-.9-7.5-4.3-9.1C26.6 8.3 22.8 6 18 6s-8.6 2.3-9.7 6.3Zm3.5 7.2c0-5 2.5-8.2 6.2-8.2s6.2 3.2 6.2 8.2c0 5.2-2.5 8.5-6.2 8.5s-6.2-3.3-6.2-8.5Zm3.3 5.7c1.7 1 4.1 1 5.8 0-.5 1.7-1.5 2.6-2.9 2.6s-2.4-.9-2.9-2.6Z"/>
</svg>`;

function iconImage() {
  let image = nativeImage.createFromBuffer(Buffer.from(TRAY_ICON_SVG));
  if (image.isEmpty()) {
    image = nativeImage.createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(TRAY_ICON_SVG)}`);
  }
  const trayIcon = image.isEmpty() ? image : image.resize({ width: 18, height: 18 });
  trayIcon.setTemplateImage(true);
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
    { label: "打开 Web UI", click: () => shell.openExternal(`http://127.0.0.1:${lastStatus?.config?.port || DEFAULT_PORT}/app`) },
    { label: "打开日志", click: () => runAction("open-log") },
    { type: "separator" },
    { label: "退出", click: () => { app.isQuitting = true; app.quit(); } },
  ]);
  tray?.setContextMenu(menu);
  tray?.setToolTip(`Dachshund · ${running}`);
}

async function createTray() {
  tray = new Tray(iconImage());
  lastStatus = await runAction("status");
  lastQuota = await apiRequest("GET", "/api/quota");
  updateMenu();
  setInterval(async () => {
    lastStatus = await runAction("status");
    lastQuota = await apiRequest("GET", "/api/quota");
    updateMenu();
    win?.webContents.send("status:changed", lastStatus);
  }, 30000);
}

function appMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: "appMenu" },
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
  shell.openExternal(url);
  return { opened: true };
});
ipcMain.handle("app:open-path", async (_event, key) => {
  if (!SAFE_PATH_KEYS.has(key)) return { error: "unsupported path" };
  const paths = await runAction("show-paths");
  const target = paths[key];
  if (!target) return { error: "path not available" };
  const result = await shell.openPath(target);
  return result ? { error: result } : { opened: true, path: target };
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
  await createTray();
  if (!process.argv.includes("--menubar-only")) createWindow({ show: true });
});

app.on("window-all-closed", () => {});
app.on("before-quit", () => { app.isQuitting = true; });
