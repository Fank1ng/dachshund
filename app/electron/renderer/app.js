const state = {
  data: null,
  operations: [],
  loginWatch: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const fmt = (value) => value === undefined || value === null || value === "" ? "-" : String(value);
const pct = (value) => Math.max(0, Math.min(100, Number(value) || 0));

function showNotice(message, kind = "info") {
  const box = $("#notice");
  box.textContent = message;
  box.classList.toggle("hidden", !message);
  box.style.borderLeftColor = kind === "error" ? "var(--danger)" : "var(--accent-2)";
}

function logOp(action, result) {
  state.operations.unshift({
    at: new Date().toLocaleTimeString(),
    action,
    result: result?.error ? result.error : "ok",
  });
  state.operations = state.operations.slice(0, 30);
  renderOps();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function loginStatusMessage(status) {
  if (!status) return "";
  if (status.error_message) return status.error_message;
  if (status.error === "rate_limited") return "设备授权被 OpenAI 限流，请等待 10-15 分钟后再试，不要反复点击开始登录。";
  if (status.state === "expired" || status.error === "expired") return "设备码已过期，请重新开始登录并使用新的验证码。";
  if (status.error === "device_auth_failed") return "设备授权失败，请确认浏览器已登录 ChatGPT/OpenAI 后重新开始登录。";
  if (status.error) return status.error;
  return "";
}

function loginStartedMessage(result) {
  const codeText = result?.device_code ? `，验证码：${result.device_code}` : "";
  const urlText = result?.login_url ? `，登录链接：${result.login_url}` : "";
  if (result?.open_error) return `登录已启动，打开网页登录失败：${result.open_error}${urlText}${codeText}`;
  if (result?.copy_error) return `登录页已打开，验证码复制失败：${result.copy_error}${codeText}${urlText}`;
  if (result?.login_url && result?.device_code) return `登录页已打开，验证码已复制：${result.device_code}`;
  if (result?.login_url) return `登录页已打开，请查看日志获取验证码：${result.login_url}`;
  if (result?.started) return `登录已启动，请查看日志：${result.log_path || ""}`;
  return "完成";
}

async function waitForLoginImport(account, startedMessage) {
  if (!account) return;
  const watch = Symbol(account);
  state.loginWatch = watch;
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await sleep(2000);
    if (state.loginWatch !== watch) return;
    const result = await window.dachshund.action("list-accounts", {});
    const row = (result?.accounts || []).find((item) => item.name === account);
    const loginStatus = (result?.login_status || []).find((item) => item.account === account);
    const loginError = loginStatusMessage(loginStatus);
    if (loginError && (loginStatus?.state === "error" || loginStatus?.state === "expired" || loginStatus?.error)) {
      state.loginWatch = null;
      showNotice(loginError, "error");
      return;
    }
    if (row?.has_tokens) {
      await window.dachshund.action("scan-accounts", {});
      await refresh();
      if (state.loginWatch !== watch) return;
      showNotice(`账号 ${account} 已导入`);
      state.loginWatch = null;
      return;
    }
    showNotice(`${startedMessage} · 等待授权完成...`);
  }
  if (state.loginWatch !== watch) return;
  state.loginWatch = null;
  showNotice(`${startedMessage} · 未检测到账号令牌，请确认网页登录验证码已提交`, "error");
}

async function refresh() {
  showNotice("刷新中...");
  state.data = await window.dachshund.snapshot();
  render();
  showNotice("");
}

async function runAction(action, payload = {}) {
  showNotice(`执行 ${action}...`);
  const result = await window.dachshund.action(action, payload);
  logOp(action, result);
  if (action === "start-login" && result?.login_url && !result?.error) {
    const opened = await window.dachshund.openExternal(result.login_url);
    if (opened?.error) result.open_error = opened.error;
  }
  if (action === "start-login" && result?.device_code && !result?.error) {
    const copied = await window.dachshund.writeClipboard(result.device_code);
    if (copied?.error) result.copy_error = copied.error;
  }
  const message = result?.error
    ? (result.error_message || result.error)
    : action === "start-login"
      ? loginStartedMessage(result)
      : action === "delete-account" && result?.deleted
          ? `账号 ${result.deleted} 已移到 ${result.trashed_to || ".trash"}`
          : action === "toggle-account" && result?.account
            ? `账号 ${result.account} 已${result.enabled ? "启用" : "停用"}`
            : "完成";
  showNotice(message, result?.error || result?.open_error ? "error" : "info");
  await refresh();
  if (action === "start-login") {
    showNotice(message, result?.error || result?.open_error || result?.copy_error ? "error" : "info");
    if (result?.started && !result?.error) waitForLoginImport(result.account || payload.name, message);
  }
  return result;
}

function activeConfig() {
  return state.data?.status?.config || state.data?.apiStatus?.config || {};
}

function render() {
  const data = state.data || {};
  const status = data.status || {};
  const apiStatus = data.apiStatus || {};
  const running = Boolean(status.running || apiStatus.running);
  $("#runDot").className = `dot ${running ? "ok" : "bad"}`;
  $("#runText").textContent = running ? "代理在线" : "代理离线";
  $("#runtimeLine").textContent = `127.0.0.1:${activeConfig().port || 18800}`;
  $("#metricStatus").textContent = running ? "在线" : "离线";
  $("#metricAccounts").textContent = `${fmt(status.active_accounts ?? apiStatus.active_accounts)} / ${fmt(status.total_accounts ?? apiStatus.total_accounts)}`;
  $("#metricRequests").textContent = fmt(apiStatus.stats?.requests_total ?? apiStatus.stats?.total_requests ?? 0);
  $("#metricVersion").textContent = fmt(status.version || status.expected_version || apiStatus.version);
  renderQuota();
  renderTokenUsage();
  renderAccounts();
  renderConfig();
  renderLogs();
  renderDiagnostics();
}

function renderQuota() {
  const host = $("#quotaList");
  const quota = state.data?.quota || {};
  const accounts = state.data?.accounts?.accounts || [];
  const names = accounts.length ? accounts.map((account) => account.name) : Object.keys(quota);
  const rows = names.map((name) => [name, quota[name]]);
  if (!rows.length) {
    host.innerHTML = `<div class="muted">暂无配额数据</div>`;
    return;
  }
  host.innerHTML = rows.map(([name, item]) => {
    const summary = quotaSummary(item);
    const tip = quotaTip(summary);
    const fiveHour = summary.fiveHour.value == null ? "-" : `${Math.round(summary.fiveHour.value)}%`;
    const sevenDay = summary.sevenDay.value == null ? "-" : `${Math.round(summary.sevenDay.value)}%`;
    return `<div class="quotaItem">
      <div class="quotaTop tip" title="${esc(tip)}" data-tip="${esc(tip)}"><strong>${esc(name)}</strong></div>
      <div class="quotaLines">
        <div class="quotaLine"><span>5h ${fiveHour}</span>${quotaBar(summary.fiveHour.value)}</div>
        <div class="quotaLine"><span>7d ${sevenDay}</span>${quotaBar(summary.sevenDay.value)}</div>
      </div>
    </div>`;
  }).join("");
}

function quotaSummary(data) {
  if (data?.error) {
    const note = data.message || data.error || "刷新中";
    return { fiveHour: { value: null, note }, sevenDay: { value: null, note } };
  }
  const rateLimit = data?.rate_limit || {};
  const primary = rateLimit.primary_window || null;
  const secondary = rateLimit.secondary_window || null;
  const fiveHour = quotaWindow(primary, data?.["5h_usage"]);
  let sevenDay = quotaWindow(secondary, data?.weekly_usage);
  if (usesSharedCodexWindow(data, primary, secondary)) sevenDay = { ...quotaWindow(primary, data?.["5h_usage"]), note: "共享窗口" };
  return { fiveHour, sevenDay };
}

function quotaWindow(windowData, fallbackUsed) {
  const used = numberOrNull(windowData?.used_percent ?? fallbackUsed);
  return {
    value: used == null ? null : pct(100 - used),
    used,
    resetAt: numberOrNull(windowData?.reset_at),
    note: "",
  };
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

function quotaTip(summary) {
  return [`5h ${quotaLine(summary.fiveHour)}`, `7d ${quotaLine(summary.sevenDay)}`].join("\n");
}

function quotaLine(item) {
  if (item.value == null) return item.note || "无数据";
  const reset = item.resetAt ? ` · 重置 ${new Date(item.resetAt * 1000).toLocaleString()}` : "";
  const note = item.note ? ` · ${item.note}` : "";
  return `剩余 ${Math.round(item.value)}% · 已用 ${Math.round(item.used)}%${reset}${note}`;
}

function quotaBar(value) {
  if (value == null) return `<div class="barTrack"><div class="barFill mutedFill"></div></div>`;
  const cls = value <= 5 ? "bad" : value <= 25 ? "warn" : "";
  return `<div class="barTrack"><div class="barFill ${cls}" style="width:${pct(value)}%"></div></div>`;
}

function bar(value) {
  const cls = value > 90 ? "bad" : value > 70 ? "warn" : "";
  return `<div class="barTrack"><div class="barFill ${cls}" style="width:${pct(value)}%"></div></div>`;
}

function numberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function tokenRows() {
  const usage = state.data?.tokenUsage || {};
  return usage.daily || usage.history || usage.rows || [];
}

function renderTokenUsage() {
  const rows = tokenRows().slice(-14);
  const events = (state.data?.tokenEvents?.events || []).slice(0, 5);
  $$(".tokenEvents").forEach((item) => item.remove());
  const total = rows.reduce((sum, row) => sum + Number(row.total_tokens || 0), 0);
  $("#tokenSummary").textContent = rows.length ? `${compact(total)} tokens` : "-";
  const max = Math.max(...rows.map((row) => Number(row.total_tokens || 0)), 1);
  $("#tokenBars").innerHTML = rows.slice(-7).map((row) => {
    const value = Number(row.total_tokens || 0);
    const tip = tokenTip(row);
    return `<div class="tip" title="${esc(tip)}" data-tip="${esc(tip)}"><div class="quotaTop"><span>${fmt(row.date || row.period_label || row.week_start)}</span><span>${compact(value)}</span></div>${bar(value / max * 100)}</div>`;
  }).join("") || `<div class="muted">暂无 token 统计</div>`;
  $("#tokenHeatmap").innerHTML = rows.map((row) => {
    const value = Number(row.total_tokens || 0);
    const alpha = 0.15 + (value / max) * 0.75;
    const tip = tokenTip(row);
    return `<div class="heat tip" title="${esc(tip)}" data-tip="${esc(tip)}" style="background: color-mix(in srgb, var(--accent) ${Math.round(alpha * 100)}%, transparent)"></div>`;
  }).join("");
  $("#tokenHeatmap").insertAdjacentHTML("afterend", events.length ? `<div class="tokenEvents">${
    events.map((row) => {
      const tip = tokenTip(row);
      return `<div class="tokenEvent tip" title="${esc(tip)}" data-tip="${esc(tip)}">
        <span>${esc(row.account)} · ${esc(row.model || row.resolved_model || row.requested_model)}</span><strong>${compact(row.total_tokens || 0)}</strong>
      </div>`;
    }).join("")
  }</div>` : "");
}

function compact(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(Math.round(n || 0));
}

function tokenTip(row) {
  const label = row.date || row.period_label || row.week_start || new Date((row.at || 0) * 1000).toLocaleString();
  return [
    `${label}`,
    `总计 ${compact(row.total_tokens || 0)} tokens`,
    `输入 ${compact(row.input_tokens || 0)} · 输出 ${compact(row.output_tokens || 0)}`,
    `缓存 ${tokenObserved(row, "cache") ? compact(cacheTokens(row)) : "-"} · 推理 ${tokenObserved(row, "reasoning") ? compact(row.reasoning_tokens || 0) : "-"}`,
    `请求 ${row.requests ?? 1} · 未知 ${row.unknown_requests || 0}`,
  ].join("\n");
}

function tokenObserved(row, kind) {
  if (kind === "cache") return row.cache_tokens_observed || row.cache_tokens_observed_requests > 0 || row.cache_capture_state?.startsWith("observed");
  return row.reasoning_tokens_observed || row.reasoning_tokens_observed_requests > 0 || row.reasoning_capture_state?.startsWith("observed");
}

function cacheTokens(row) {
  return Number(row.cache_read_tokens || 0) + Number(row.cache_creation_tokens || 0) || Math.max(Number(row.cached_tokens || 0), Number(row.cache_tokens || 0));
}

function esc(value) {
  return fmt(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char]));
}

function renderAccounts() {
  const rows = state.data?.accounts?.accounts || [];
  $("#accountRows").innerHTML = rows.map((account) => {
    const status = account.auth_error ? `<span class="badText">认证异常</span>` : account.enabled ? `<span class="okText">启用</span>` : "停用";
    return `<tr>
      <td>${account.name}</td>
      <td>${fmt(account.email)}</td>
      <td>${status}${account.rate_limited ? " · 冷却" : ""}</td>
      <td>${account.has_tokens ? "有" : "无"}</td>
      <td><div class="rowActions">
        <button data-row-action="toggle-account" data-name="${account.name}">${account.enabled ? "停用" : "启用"}</button>
        <button data-row-action="refresh-token" data-name="${account.name}">刷新令牌</button>
        <button data-row-action="clear-cooldown" data-name="${account.name}">清冷却</button>
        <button data-row-action="clear-auth-error" data-name="${account.name}">清异常</button>
        <button data-delete-account="${account.name}">删除</button>
      </div></td>
    </tr>`;
  }).join("") || `<tr><td colspan="5" class="muted">暂无账号</td></tr>`;
}

function renderConfig() {
  const cfg = activeConfig();
  for (const input of Array.from($("#configForm").elements)) {
    if (!input.name || cfg[input.name] === undefined) continue;
    if (input.type === "checkbox") input.checked = Boolean(cfg[input.name]);
    else input.value = cfg[input.name];
  }
}

function formConfig() {
  const out = {};
  for (const input of Array.from($("#configForm").elements)) {
    if (!input.name) continue;
    if (input.type === "checkbox") out[input.name] = input.checked;
    else if (input.type === "number") out[input.name] = Number(input.value);
    else out[input.name] = input.value;
  }
  return out;
}

function renderLogs() {
  const apiStatus = state.data?.apiStatus || {};
  const requests = apiStatus.recent_requests || [];
  const errors = apiStatus.recent_errors || [];
  $("#requestList").innerHTML = requests.slice(0, 40).map(requestRow).join("") || `<div class="muted">暂无请求</div>`;
  $("#errorList").innerHTML = errors.slice(0, 30).map(requestRow).join("") || `<div class="muted">暂无错误</div>`;
  renderOps();
}

function requestRow(row) {
  return `<div class="requestItem">
    <div class="requestTop"><strong>${fmt(row.method)} ${fmt(row.path)}</strong><span>${fmt(row.status)}</span></div>
    <div class="muted">${fmt(row.account)} · ${fmt(row.model)} · ${fmt(row.error || row.route_class)}</div>
  </div>`;
}

function renderOps() {
  $("#opLog").innerHTML = state.operations.map((row) => (
    `<div class="requestItem"><div class="requestTop"><strong>${row.action}</strong><span>${row.at}</span></div><div class="muted">${row.result}</div></div>`
  )).join("") || `<div class="muted">暂无操作</div>`;
}

function renderDiagnostics() {
  const status = state.data?.status || {};
  const paths = state.data?.paths || {};
  const items = [
    ["LaunchAgent", `${fmt(status.installed)} / ${fmt(status.loaded)}`],
    ["Manifest", status.manifest_ok ? "ok" : fmt(status.manifest_error)],
    ["Codex CLI", status.codex_cli_found ? status.codex_cli : status.codex_cli_error],
    ["Codex App", status.codex_app_found ? "found" : "missing"],
    ["运行目录", paths.runtime_dir || status.runtime_dir],
    ["配置文件", paths.config_path],
    ["账号目录", paths.accounts_dir],
    ["日志", paths.log_path],
    ["Python", paths.python],
    ["App", paths.app_bundle],
  ];
  $("#diagGrid").innerHTML = items.map(([key, value]) => (
    `<div class="diagItem"><strong>${key}</strong><code>${fmt(value)}</code></div>`
  )).join("");
}

function accountName() {
  return $("#accountName").value.trim();
}

function setRowBusy(button, busy) {
  const row = button.closest("tr");
  if (!row) return;
  row.querySelectorAll("button").forEach((item) => {
    item.disabled = busy;
  });
}

async function runRowAction(button) {
  const action = button.dataset.rowAction;
  const name = button.dataset.name;
  if (!action || !name) return;
  setRowBusy(button, true);
  try {
    await runAction(action, { name });
  } finally {
    setRowBusy(button, false);
  }
}

async function deleteAccount(button) {
  const name = button.dataset.deleteAccount;
  if (!name) return;
  if (!window.confirm(`删除账号 ${name}？账号目录会移到 .trash。`)) return;
  setRowBusy(button, true);
  try {
    const result = await runAction("delete-account", { name });
    if (!result?.error && result?.deleted === name) {
      const accounts = state.data?.accounts?.accounts;
      if (Array.isArray(accounts)) {
        state.data.accounts.accounts = accounts.filter((account) => account.name !== name);
        state.data.accounts.total_accounts = state.data.accounts.accounts.length;
        state.data.accounts.active_accounts = state.data.accounts.accounts.filter((account) => account.enabled && account.has_tokens).length;
        render();
      }
    } else if (!result?.error) {
      showNotice(`删除账号 ${name} 未返回确认结果`, "error");
    }
  } finally {
    setRowBusy(button, false);
  }
}

function bind() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab").forEach((item) => item.classList.remove("active"));
      $$(".panel").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.tab}`).classList.add("active");
      $("#pageTitle").textContent = button.textContent;
    });
  });
  $("#refreshBtn").addEventListener("click", refresh);
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (button.dataset.deleteAccount) {
      event.preventDefault();
      event.stopPropagation();
      await deleteAccount(button);
    } else if (button.dataset.rowAction) {
      event.preventDefault();
      event.stopPropagation();
      await runRowAction(button);
    } else if (button.dataset.action) {
      await runAction(button.dataset.action);
    } else if (button.dataset.accountAction) {
      await runAction(button.dataset.accountAction, { name: accountName() });
    } else if (button.dataset.apiPost) {
      const result = await window.dachshund.api("POST", button.dataset.apiPost);
      logOp(button.dataset.apiPost, result);
      if (result?.quota && state.data) {
        state.data.quota = result.quota;
        render();
      }
      await refresh();
    } else if (button.dataset.openPath) {
      await window.dachshund.openPath(button.dataset.openPath);
    } else if (button.dataset.openExternal) {
      await window.dachshund.openExternal(button.dataset.openExternal);
    }
  });
  $("#saveConfig").addEventListener("click", () => runAction("set-config", { config: formConfig() }));
  $("#clearRecent").addEventListener("click", async () => {
    const result = await window.dachshund.api("POST", "/api/status/recent/clear");
    logOp("clear-recent-requests", result);
    await refresh();
  });
  window.dachshund.onStatus((status) => {
    if (!state.data) return;
    state.data.status = { ...state.data.status, ...status };
    render();
  });
}

bind();
window.dachshund.asset("dog-head").then((url) => {
  if (url) $("#brandIcon").src = url;
});
refresh();
