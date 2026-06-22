const state = {
  data: null,
  operations: [],
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
  showNotice(result?.error ? result.error : "完成", result?.error ? "error" : "info");
  await refresh();
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
  const rows = Object.entries(state.data?.quota || {}).filter(([, value]) => value && typeof value === "object");
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
  if (data?.error) return { fiveHour: { value: null, note: "刷新中" }, sevenDay: { value: null, note: "刷新中" } };
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
        <button data-row-action="delete-account" data-name="${account.name}">删除</button>
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
    if (button.dataset.action) await runAction(button.dataset.action);
    if (button.dataset.accountAction) await runAction(button.dataset.accountAction, { name: accountName() });
    if (button.dataset.rowAction) await runAction(button.dataset.rowAction, { name: button.dataset.name });
    if (button.dataset.apiPost) {
      const result = await window.dachshund.api("POST", button.dataset.apiPost);
      logOp(button.dataset.apiPost, result);
      await refresh();
    }
    if (button.dataset.openPath) await window.dachshund.openPath(button.dataset.openPath);
    if (button.dataset.openExternal) await window.dachshund.openExternal(button.dataset.openExternal);
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
