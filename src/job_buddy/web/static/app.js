const SEARCH_FORM_STORAGE_KEY = "job_buddy.search_form";
const DEFAULT_LOG_LIMIT = 200;
const VIEW_IDS = ["dashboard", "search", "jobs", "tasks", "conversations", "doctor", "logs"];

const state = {
  activeView: "dashboard",
  auth: null,
  doctor: null,
  searchOptionsLoaded: false,
  noticeTimer: null,
  searchUpdateTimer: null,
};

function getSafeStorage() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function safeStorageRead(key) {
  try {
    return getSafeStorage()?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

function safeStorageWrite(key, value) {
  try {
    getSafeStorage()?.setItem(key, value);
  } catch {
    // Ignore storage access failures in restricted documents.
  }
}

function safeStorageRemove(key) {
  try {
    getSafeStorage()?.removeItem(key);
  } catch {
    // Ignore storage access failures in restricted documents.
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const rawMessage = await response.text();
    let detail = rawMessage;
    try {
      const payload = rawMessage ? JSON.parse(rawMessage) : null;
      detail = payload?.detail || rawMessage;
    } catch {
      detail = rawMessage;
    }
    throw new Error(`${response.status} ${response.statusText}${detail ? ` - ${detail}` : ""}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

function renderStatusBadge(status) {
  const normalized = String(status || "info").toLowerCase();
  const mappedStatus = {
    succeeded: "ok",
    success: "ok",
    running: "warn",
    pending: "warn",
    partial_success: "warn",
    failed: "error",
    error: "error",
    ok: "ok",
    warn: "warn",
    debug: "debug",
    info: "info",
  }[normalized] || "info";
  return `<span class="status-badge status-${mappedStatus}">${escapeHtml(status || mappedStatus)}</span>`;
}

function showError(message) {
  document.getElementById("pageErrorPanel").hidden = false;
  document.getElementById("pageErrorMessage").innerHTML = `<strong>错误：</strong>${escapeHtml(message)}`;
}

function clearError() {
  document.getElementById("pageErrorPanel").hidden = true;
  document.getElementById("pageErrorMessage").innerHTML = "";
}

function showNotice(message, durationMs = 0) {
  if (state.noticeTimer) {
    window.clearTimeout(state.noticeTimer);
    state.noticeTimer = null;
  }
  document.getElementById("pageNoticePanel").hidden = false;
  document.getElementById("pageNoticeMessage").innerHTML = escapeHtml(message);
  if (durationMs > 0) {
    state.noticeTimer = window.setTimeout(() => {
      clearNotice();
      state.noticeTimer = null;
    }, durationMs);
  }
}

function clearNotice() {
  if (state.noticeTimer) {
    window.clearTimeout(state.noticeTimer);
    state.noticeTimer = null;
  }
  document.getElementById("pageNoticePanel").hidden = true;
  document.getElementById("pageNoticeMessage").innerHTML = "";
}

function showSearchUpdate(message, durationMs = 5000) {
  const panel = document.getElementById("searchUpdateNotice");
  if (!panel) {
    return;
  }
  if (state.searchUpdateTimer) {
    window.clearTimeout(state.searchUpdateTimer);
    state.searchUpdateTimer = null;
  }
  panel.hidden = false;
  panel.textContent = message;
  if (durationMs > 0) {
    state.searchUpdateTimer = window.setTimeout(() => {
      clearSearchUpdate();
      state.searchUpdateTimer = null;
    }, durationMs);
  }
}

function clearSearchUpdate() {
  if (state.searchUpdateTimer) {
    window.clearTimeout(state.searchUpdateTimer);
    state.searchUpdateTimer = null;
  }
  const panel = document.getElementById("searchUpdateNotice");
  if (!panel) {
    return;
  }
  panel.hidden = true;
  panel.textContent = "";
}

function setButtonBusy(buttonId, busy, busyText = "处理中") {
  const button = document.getElementById(buttonId);
  if (!button) {
    return;
  }
  if (!button.dataset.idleText) {
    button.dataset.idleText = button.textContent;
  }
  button.disabled = busy;
  button.classList.toggle("button-disabled", busy);
  button.textContent = busy ? busyText : button.dataset.idleText;
}

function renderEmpty(containerId, text = "暂无数据。") {
  document.getElementById(containerId).innerHTML = `<div class="empty">${escapeHtml(text)}</div>`;
}

function renderTable(containerId, columns, rows) {
  const container = document.getElementById(containerId);
  if (!rows.length) {
    container.innerHTML = `<div class="empty">暂无数据。</div>`;
    return;
  }

  const header = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((column) => `<td>${column.render(row)}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  container.innerHTML = `<div class="table-shell"><table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function setActiveView(viewId) {
  state.activeView = VIEW_IDS.includes(viewId) ? viewId : "dashboard";
  VIEW_IDS.forEach((view) => {
    const section = document.querySelector(`[data-view="${view}"]`);
    const active = view === state.activeView;
    if (section) {
      section.hidden = !active;
      section.classList.toggle("is-active", active);
      section.classList.toggle("is-hidden", !active);
    }
    document.querySelectorAll(`[data-view-target="${view}"]`).forEach((element) => {
      element.classList.toggle("is-active", active);
      if (element.classList.contains("nav-link")) {
        element.setAttribute("aria-current", active ? "page" : "false");
      }
    });
  });
}

function getViewFromHash() {
  const view = window.location.hash.replace(/^#/, "");
  return VIEW_IDS.includes(view) ? view : "dashboard";
}

function navigateTo(viewId, updateHash = true) {
  const nextView = VIEW_IDS.includes(viewId) ? viewId : "dashboard";
  if (updateHash && window.location.hash === `#${nextView}`) {
    setActiveView(nextView);
    loadView(nextView).catch((error) => showError(error.message || "页面加载失败"));
    return;
  }
  if (updateHash) {
    window.location.hash = nextView;
    return;
  }
  setActiveView(nextView);
  loadView(nextView).catch((error) => showError(error.message || "页面加载失败"));
}

function buildSelectOptions(selectId, values) {
  const select = document.getElementById(selectId);
  const options = ['<option value="">不限</option>']
    .concat(values.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`))
    .join("");
  select.innerHTML = options;
}

function getSearchFormElements() {
  return {
    keywords: document.getElementById("searchKeywordsInput"),
    city: document.getElementById("searchCitySelect"),
    salary: document.getElementById("searchSalarySelect"),
    experience: document.getElementById("searchExperienceSelect"),
    education: document.getElementById("searchEducationSelect"),
    industry: document.getElementById("searchIndustrySelect"),
    scale: document.getElementById("searchScaleSelect"),
    stage: document.getElementById("searchStageSelect"),
    jobType: document.getElementById("searchJobTypeSelect"),
    welfare: document.getElementById("searchWelfareInput"),
    page: document.getElementById("searchPageInput"),
  };
}

function readSearchFormState() {
  const elements = getSearchFormElements();
  return {
    keywords: elements.keywords.value.trim(),
    city: elements.city.value || "",
    salary: elements.salary.value || "",
    experience: elements.experience.value || "",
    education: elements.education.value || "",
    industry: elements.industry.value || "",
    scale: elements.scale.value || "",
    stage: elements.stage.value || "",
    job_type: elements.jobType.value || "",
    welfare: elements.welfare.value.trim(),
    page: elements.page.value || "1",
  };
}

function persistSearchFormState() {
  safeStorageWrite(SEARCH_FORM_STORAGE_KEY, JSON.stringify(readSearchFormState()));
}

function applyCachedSearchFormState() {
  try {
    const raw = safeStorageRead(SEARCH_FORM_STORAGE_KEY);
    if (!raw) {
      return;
    }
    const cached = JSON.parse(raw);
    const elements = getSearchFormElements();
    elements.keywords.value = cached.keywords || "";
    elements.welfare.value = cached.welfare || "";
    elements.page.value = cached.page || "1";

    [
      [elements.city, cached.city],
      [elements.salary, cached.salary],
      [elements.experience, cached.experience],
      [elements.education, cached.education],
      [elements.industry, cached.industry],
      [elements.scale, cached.scale],
      [elements.stage, cached.stage],
      [elements.jobType, cached.job_type],
    ].forEach(([element, value]) => {
      if (!value) {
        element.value = "";
        return;
      }
      const hasOption = Array.from(element.options).some((option) => option.value === value);
      element.value = hasOption ? value : "";
    });
  } catch {
    safeStorageRemove(SEARCH_FORM_STORAGE_KEY);
  }
}

function bindSearchFormPersistence() {
  Object.values(getSearchFormElements()).forEach((element) => {
    element.addEventListener("change", persistSearchFormState);
    if (element.tagName === "INPUT") {
      element.addEventListener("input", persistSearchFormState);
    }
  });
}

async function loadSearchOptions() {
  if (state.searchOptionsLoaded) {
    return;
  }
  const options = await fetchJson("/api/system/search-options");
  buildSelectOptions("searchCitySelect", options.cities || []);
  buildSelectOptions("searchSalarySelect", options.salary_ranges || []);
  buildSelectOptions("searchExperienceSelect", options.experience_levels || []);
  buildSelectOptions("searchEducationSelect", options.education_levels || []);
  buildSelectOptions("searchIndustrySelect", options.industries || []);
  buildSelectOptions("searchScaleSelect", options.scales || []);
  buildSelectOptions("searchStageSelect", options.stages || []);
  buildSelectOptions("searchJobTypeSelect", options.job_types || []);
  applyCachedSearchFormState();
  state.searchOptionsLoaded = true;
}

function renderAuthStrip(status) {
  document.getElementById("authStripSummary").innerHTML = [
    status.logged_in ? renderStatusBadge("ok") : renderStatusBadge("warn"),
    `<strong>${escapeHtml(status.logged_in ? status.user_name || "已登录" : "未登录")}</strong>`,
    `<span>${escapeHtml(status.browser || status.message || "-")}</span>`,
  ].join("");

  const button = document.getElementById("authActionButton");
  button.textContent = status.logged_in ? "退出登录" : "登录";
  button.dataset.idleText = button.textContent;
}

function renderAuthDetail(status) {
  const html = [
    `<div><strong>状态：</strong>${status.logged_in ? renderStatusBadge("ok") : renderStatusBadge("warn")}</div>`,
    `<div><strong>用户名：</strong>${escapeHtml(status.user_name || "-")}</div>`,
    `<div><strong>登录方式：</strong>${escapeHtml(status.login_method || "-")}</div>`,
    `<div><strong>浏览器：</strong>${escapeHtml(status.browser || "-")}</div>`,
    `<div><strong>最近登录：</strong>${escapeHtml(formatDate(status.last_login_at))}</div>`,
    `<div><strong>最近退出：</strong>${escapeHtml(formatDate(status.last_logout_at))}</div>`,
    `<div><strong>提示：</strong>${escapeHtml(status.message || "-")}</div>`,
    `<div><strong>错误：</strong>${escapeHtml(status.last_error || "-")}</div>`,
  ].join("");

  document.getElementById("authSummary").innerHTML = html;
  document.getElementById("dashboardAuthSummary").innerHTML = [
    `<div><strong>当前状态：</strong>${status.logged_in ? "已登录" : "未登录"}</div>`,
    `<div><strong>账号：</strong>${escapeHtml(status.user_name || "-")}</div>`,
    `<div><strong>环境：</strong>${escapeHtml(status.browser || "-")}</div>`,
  ].join("");
}

async function loadAuthStatus() {
  const status = await fetchJson("/api/system/auth");
  state.auth = status;
  renderAuthStrip(status);
  renderAuthDetail(status);
  return status;
}

function renderDoctor(doctor) {
  const summaryLines = [
    `<div><strong>诊断结果：</strong>${escapeHtml(doctor.summary)}</div>`,
    `<div><strong>命令状态：</strong>${doctor.ok ? "成功" : "失败"}</div>`,
    `<div><strong>退出码：</strong>${doctor.exit_code}</div>`,
    `<div><strong>数据目录：</strong>${escapeHtml(doctor.data_dir || "-")}</div>`,
  ];
  if (doctor.stderr) {
    summaryLines.push(`<div><strong>标准错误：</strong><pre>${escapeHtml(doctor.stderr)}</pre></div>`);
  }
  if (doctor.error) {
    summaryLines.push(
      `<div><strong>错误信息：</strong>${escapeHtml(`${doctor.error.code} - ${doctor.error.message}`)}</div>`,
    );
  }

  document.getElementById("doctorSummary").innerHTML = summaryLines.join("");
  document.getElementById("dashboardDoctorSummary").innerHTML = [
    `<div><strong>诊断摘要：</strong>${escapeHtml(doctor.summary)}</div>`,
    `<div><strong>状态：</strong>${doctor.ok ? "正常" : "异常"}</div>`,
    `<div><strong>建议数：</strong>${doctor.next_actions?.length || 0}</div>`,
  ].join("");

  document.getElementById("doctorActions").innerHTML = doctor.next_actions?.length
    ? `<ul class="bullet-list">${doctor.next_actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
    : `<div class="empty">暂无下一步建议。</div>`;

  renderTable(
    "doctorChecks",
    [
      { label: "检查项", render: (row) => escapeHtml(row.name) },
      { label: "状态", render: (row) => renderStatusBadge(row.status) },
      { label: "详情", render: (row) => escapeHtml(row.detail) },
      { label: "建议", render: (row) => escapeHtml(row.hint || "-") },
    ],
    doctor.checks || [],
  );
}

async function loadDoctor() {
  const doctor = await fetchJson("/api/system/doctor");
  state.doctor = doctor;
  renderDoctor(doctor);
  return doctor;
}

async function loadSummaryCards() {
  const summary = await fetchJson("/api/dashboard");
  const labels = {
    targets: "目标岗位",
    jobs: "职位线索",
    tasks: "任务记录",
    conversations: "沟通记录",
  };
  document.getElementById("summaryCards").innerHTML = Object.entries(summary)
    .map(
      ([key, value]) => `
        <div class="summary-card">
          <span>${escapeHtml(labels[key] || key)}</span>
          <strong>${escapeHtml(String(value))}</strong>
        </div>
      `,
    )
    .join("");
}

function summarizeTaskInput(inputPayload) {
  if (!inputPayload) {
    return "-";
  }
  if (Array.isArray(inputPayload.keywords)) {
    return inputPayload.keywords.join(", ");
  }
  if (Array.isArray(inputPayload.job_ids) && inputPayload.job_ids.length) {
    return `指定职位 ${inputPayload.job_ids.length} 个`;
  }
  if (inputPayload.limit) {
    return `limit=${inputPayload.limit}`;
  }
  return escapeHtml(JSON.stringify(inputPayload));
}

async function loadTasks(limit = 100) {
  const items = await fetchJson(`/api/tasks?limit=${limit}`);
  renderTable(
    "tasksTable",
    [
      { label: "类型", render: (row) => renderStatusBadge(row.task_type) },
      { label: "状态", render: (row) => renderStatusBadge(row.status) },
      { label: "输入摘要", render: (row) => escapeHtml(summarizeTaskInput(row.input_payload)) },
      { label: "结果摘要", render: (row) => escapeHtml(JSON.stringify(row.result_summary || {})) },
      { label: "错误信息", render: (row) => escapeHtml(row.error_message || "-") },
      { label: "更新时间", render: (row) => escapeHtml(formatDate(row.updated_at)) },
    ],
    items,
  );
  return items;
}

function renderDashboardTasks(items) {
  renderTable(
    "dashboardTasksTable",
    [
      { label: "类型", render: (row) => escapeHtml(row.task_type) },
      { label: "状态", render: (row) => renderStatusBadge(row.status) },
      { label: "结果摘要", render: (row) => escapeHtml(JSON.stringify(row.result_summary || {})) },
      { label: "更新时间", render: (row) => escapeHtml(formatDate(row.updated_at)) },
    ],
    items,
  );
}

async function loadJobs() {
  const items = await fetchJson("/api/jobs");
  renderTable(
    "jobsTable",
    [
      { label: "职位", render: (row) => escapeHtml(row.title) },
      { label: "公司", render: (row) => escapeHtml(row.company) },
      { label: "城市", render: (row) => escapeHtml(row.city || "-") },
      { label: "薪资", render: (row) => escapeHtml(row.salary || "-") },
      { label: "经验", render: (row) => escapeHtml(row.experience || "-") },
      { label: "搜索次数", render: (row) => escapeHtml(String(row.search_count ?? 0)) },
      { label: "最近搜索", render: (row) => escapeHtml(formatDate(row.last_searched_at || row.last_seen_at)) },
      {
        label: "跳转",
        render: (row) =>
          row.job_url
            ? `<a href="${escapeHtml(row.job_url)}" target="_blank" rel="noreferrer">查看职位</a>`
            : "-",
      },
      {
        label: "状态",
        render: (row) => escapeHtml(`${row.match_status}${row.greeted ? " / 已打招呼" : ""}`),
      },
    ],
    items,
  );
  return items;
}

function renderLatestSearchMeta(task, rows) {
  const meta = document.getElementById("latestSearchMeta");
  if (!task) {
    meta.textContent = "暂无搜索任务";
    return;
  }

  const query = Array.isArray(task.input_payload?.keywords) ? task.input_payload.keywords.join(", ") : "-";
  meta.textContent = `关键词: ${query} | 时间: ${formatDate(task.finished_at || task.updated_at)} | 结果: ${rows.length} 条`;
}

function getSearchPageValue() {
  return Math.max(1, Number(document.getElementById("searchPageInput").value || 1));
}

function setSearchPageValue(page) {
  document.getElementById("searchPageInput").value = String(Math.max(1, page));
  persistSearchFormState();
}

async function loadCurrentSearchResults() {
  const tasks = await fetchJson("/api/tasks?limit=100");
  const latestSearchTask = tasks.find((item) => item.task_type === "search");
  if (!latestSearchTask) {
    renderLatestSearchMeta(null, []);
    renderEmpty("searchResultsTable", "暂无搜索结果，请先执行一次职位搜索。");
    return [];
  }

  const rows = await fetchJson(`/api/jobs/collections?task_id=${encodeURIComponent(latestSearchTask.id)}&limit=200`);
  renderLatestSearchMeta(latestSearchTask, rows);
  renderTable(
    "searchResultsTable",
    [
      { label: "职位", render: (row) => escapeHtml(row.title) },
      { label: "公司", render: (row) => escapeHtml(row.company) },
      { label: "城市", render: (row) => escapeHtml(row.city || "-") },
      { label: "薪资", render: (row) => escapeHtml(row.salary || "-") },
      { label: "经验", render: (row) => escapeHtml(row.experience || "-") },
      { label: "采集时间", render: (row) => escapeHtml(formatDate(row.collected_at || row.updated_at)) },
      {
        label: "跳转",
        render: (row) =>
          row.job_url
            ? `<a href="${escapeHtml(row.job_url)}" target="_blank" rel="noreferrer">查看职位</a>`
            : "-",
      },
    ],
    rows,
  );
  return rows;
}

async function loadConversations() {
  const items = await fetchJson("/api/conversations");
  renderTable(
    "conversationsTable",
    [
      { label: "职位", render: (row) => escapeHtml(row.title) },
      { label: "公司", render: (row) => escapeHtml(row.company || "-") },
      { label: "最近消息", render: (row) => escapeHtml(row.last_message || "-") },
      { label: "未读数", render: (row) => escapeHtml(String(row.unread_count)) },
      { label: "最近时间", render: (row) => escapeHtml(formatDate(row.last_message_at)) },
    ],
    items,
  );
  return items;
}

function renderLogs(payload) {
  document.getElementById("logsMeta").innerHTML = [
    `<div><strong>日志文件：</strong>${escapeHtml(payload.source)}</div>`,
    `<div><strong>读取时间：</strong>${escapeHtml(formatDate(payload.updated_at))}</div>`,
    `<div><strong>是否截断：</strong>${payload.truncated ? "是" : "否"}</div>`,
  ].join("");

  if (!payload.lines.length) {
    renderEmpty("logsViewer", "当前没有可展示的日志内容。");
    return;
  }

  const html = payload.lines
    .map(
      (line) =>
        `<div class="log-line log-${escapeHtml(line.level_hint)}"><span>${escapeHtml(line.text)}</span></div>`,
    )
    .join("");
  document.getElementById("logsViewer").innerHTML = html;
}

async function loadLogs() {
  const payload = await fetchJson(`/api/system/logs?limit=${DEFAULT_LOG_LIMIT}`);
  renderLogs(payload);
  return payload;
}

async function loadDashboardView() {
  const [, auth, doctor, tasks] = await Promise.all([
    loadSummaryCards(),
    loadAuthStatus(),
    loadDoctor(),
    fetchJson("/api/tasks?limit=5"),
  ]);
  renderDashboardTasks(tasks);
  return { auth, doctor, tasks };
}

function collectSearchFormPayload() {
  persistSearchFormState();
  const keywordsText = document.getElementById("searchKeywordsInput").value.trim();
  const keywords = keywordsText
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);

  if (!keywords.length) {
    throw new Error("请先填写至少一个搜索关键词");
  }

  const payload = {
    keywords,
    city: document.getElementById("searchCitySelect").value || null,
    salary: document.getElementById("searchSalarySelect").value || null,
    experience: document.getElementById("searchExperienceSelect").value || null,
    education: document.getElementById("searchEducationSelect").value || null,
    industry: document.getElementById("searchIndustrySelect").value || null,
    scale: document.getElementById("searchScaleSelect").value || null,
    stage: document.getElementById("searchStageSelect").value || null,
    job_type: document.getElementById("searchJobTypeSelect").value || null,
    welfare: document.getElementById("searchWelfareInput").value.trim() || null,
    page: getSearchPageValue(),
  };

  return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== null && value !== ""));
}

async function toggleAuth() {
  clearError();
  setButtonBusy("authActionButton", true, "处理中");
  try {
    const endpoint = state.auth?.logged_in ? "/api/system/auth/logout" : "/api/system/auth/login";
    const status = await fetchJson(endpoint, { method: "POST" });
    state.auth = status;
    renderAuthStrip(status);
    renderAuthDetail(status);
    await Promise.all([loadDoctor(), loadSummaryCards()]);
    showNotice(status.message || "登录状态已更新");
  } finally {
    setButtonBusy("authActionButton", false);
  }
}

async function triggerSearch() {
  return triggerSearchWithPayload({
    buttonId: "searchButton",
    busyText: "搜索中",
    payload: collectSearchFormPayload(),
  });
}

async function triggerNextPageSearch() {
  const currentPage = getSearchPageValue();
  const nextPage = currentPage + 1;
  const payload = {
    ...collectSearchFormPayload(),
    page: nextPage,
  };

  await triggerSearchWithPayload({
    buttonId: "nextPageSearchButton",
    busyText: "翻页中",
    payload,
    onSuccess: (rows) => {
      setSearchPageValue(nextPage);
      showSearchUpdate(`第 ${nextPage} 页搜索完成，搜索结果已更新，当前展示 ${rows.length} 条记录。`);
    },
  });
}

async function triggerSearchWithPayload({ buttonId, busyText, payload, onSuccess = null }) {
  clearError();
  setButtonBusy(buttonId, true, busyText);
  try {
    const result = await fetchJson("/api/tasks/search", {
      method: "POST",
      body: JSON.stringify({ query_override: payload }),
    });
    const [rows] = await Promise.all([
      loadCurrentSearchResults(),
      loadJobs(),
      loadTasks(),
      loadSummaryCards(),
      fetchJson("/api/tasks?limit=5").then(renderDashboardTasks),
    ]);
    if (onSuccess) {
      onSuccess(rows);
    } else {
      showSearchUpdate(
        `搜索完成，结果已更新。关键词：${(payload.keywords || []).join(", ")}，页码：${payload.page || 1}，当前展示 ${rows.length} 条记录。`,
      );
    }
    showNotice(`已触发搜索任务 ${result.task_id}`, 5000);
  } finally {
    setButtonBusy(buttonId, false);
  }
}

async function triggerGreeting() {
  clearError();
  setButtonBusy("greetButton", true, "执行中");
  try {
    const result = await fetchJson("/api/tasks/greet", {
      method: "POST",
      body: JSON.stringify({ limit: 5 }),
    });
    await Promise.all([loadJobs(), loadTasks(), loadSummaryCards(), fetchJson("/api/tasks?limit=5").then(renderDashboardTasks)]);
    showNotice(`已触发打招呼任务 ${result.task_id}`);
  } finally {
    setButtonBusy("greetButton", false);
  }
}

async function syncConversations() {
  clearError();
  setButtonBusy("syncConversationsButton", true, "同步中");
  try {
    const result = await fetchJson("/api/conversations/sync", { method: "POST" });
    await Promise.all([loadConversations(), loadSummaryCards()]);
    showNotice(`已同步 ${result.count} 条会话`);
  } finally {
    setButtonBusy("syncConversationsButton", false);
  }
}

async function loadView(viewId) {
  clearError();
  switch (viewId) {
    case "dashboard":
      await loadDashboardView();
      break;
    case "search":
      clearSearchUpdate();
      await Promise.all([loadSearchOptions(), loadCurrentSearchResults()]);
      break;
    case "jobs":
      await loadJobs();
      break;
    case "tasks":
      await loadTasks();
      break;
    case "conversations":
      await loadConversations();
      break;
    case "doctor":
      await Promise.all([loadAuthStatus(), loadDoctor()]);
      break;
    case "logs":
      await loadLogs();
      break;
    default:
      await loadDashboardView();
  }
}

async function refreshCurrentView() {
  clearNotice();
  await loadView(state.activeView);
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => navigateTo(button.dataset.viewTarget));
  });

  window.addEventListener("hashchange", () => {
    setActiveView(getViewFromHash());
    loadView(state.activeView).catch((error) => showError(error.message || "页面加载失败"));
  });

  document
    .getElementById("refreshCurrentButton")
    .addEventListener("click", () => refreshCurrentView().catch((error) => showError(error.message)));
  document
    .getElementById("dashboardDoctorRefreshButton")
    .addEventListener("click", () => loadDoctor().catch((error) => showError(error.message)));
  document
    .getElementById("authActionButton")
    .addEventListener("click", () => toggleAuth().catch((error) => showError(error.message)));
  document
    .getElementById("doctorButton")
    .addEventListener("click", () => loadDoctor().catch((error) => showError(error.message)));
  document
    .getElementById("searchButton")
    .addEventListener("click", () => triggerSearch().catch((error) => showError(error.message)));
  document
    .getElementById("nextPageSearchButton")
    .addEventListener("click", () => triggerNextPageSearch().catch((error) => showError(error.message)));
  document
    .getElementById("refreshSearchButton")
    .addEventListener("click", () => loadCurrentSearchResults().catch((error) => showError(error.message)));
  document
    .getElementById("refreshJobsButton")
    .addEventListener("click", () => loadJobs().catch((error) => showError(error.message)));
  document
    .getElementById("greetButton")
    .addEventListener("click", () => triggerGreeting().catch((error) => showError(error.message)));
  document
    .getElementById("syncConversationsButton")
    .addEventListener("click", () => syncConversations().catch((error) => showError(error.message)));
  document
    .getElementById("refreshTasksButton")
    .addEventListener("click", () => loadTasks().catch((error) => showError(error.message)));
  document
    .getElementById("refreshConversationsButton")
    .addEventListener("click", () => loadConversations().catch((error) => showError(error.message)));
  document
    .getElementById("refreshLogsButton")
    .addEventListener("click", () => loadLogs().catch((error) => showError(error.message)));
}

bindSearchFormPersistence();
bindEvents();
setActiveView(getViewFromHash());

Promise.all([loadAuthStatus(), loadView(state.activeView)])
  .then(() => clearNotice())
  .catch((error) => showError(error.message || "页面初始化失败"));
