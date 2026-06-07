const SEARCH_FORM_STORAGE_KEY = "job_buddy.search_form";
const AGENT_STEPS_STORAGE_KEY = "job_buddy.agent_steps";
const AGENT_CHAT_STORAGE_KEY = "job_buddy.agent_chat";
const MAX_AGENT_STEPS = 50;
const DEFAULT_LOG_LIMIT = 200;
const VIEW_IDS = ["dashboard", "search", "jobs", "tasks", "conversations", "doctor", "logs", "statistics", "profiles", "agent"];

const state = {
  activeView: "dashboard",
  auth: null,
  doctor: null,
  searchOptionsLoaded: false,
  noticeTimer: null,
  searchUpdateTimer: null,
  jobDetail: null,
  jobDetailLoading: false,
  jobDetailSourceJobId: null,
  jobDetailPageSourceJobId: null,
  jobDetailPageName: null,
  jobDetailPageSourceFriendId: null,
  jobDetailPageSecurityId: null,
  jobDetailPageForceContact: false,
  jobDetailPagePayload: null,
  jobs: [],
  jobsTotal: 0,
  jobsPage: 1,
  jobsLimit: 100,
  workers: [],
  chatHistorySourceFriendId: null,
  chatHistoryPage: 1,
  chatHistoryName: "",
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
    const error = new Error(`${response.status} ${response.statusText}${detail ? ` - ${detail}` : ""}`);
    error.status = response.status;
    throw error;
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

function formatTime(value) {
  if (!value) return "";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
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
    idle: "info",
    waiting: "warn",
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

function renderJobDetailAction(row) {
  const sourceJobId = row.source_job_id;
  if (!sourceJobId) {
    return "-";
  }
  return `<a href="#job-detail/${encodeURIComponent(sourceJobId)}" target="_blank" rel="noopener noreferrer" class="button-link">查看详情</a>`;
}

function renderDetailStateBadge(fetchedAt) {
  return fetchedAt
    ? '<span class="status-badge status-ok">已采集</span>'
    : '<span class="status-badge status-warn">未采集</span>';
}

function formatJson(value) {
  return escapeHtml(JSON.stringify(value ?? {}, null, 2));
}

function getCompanyScale(row) {
  return row.scale || null;
}

function setActiveView(viewId) {
  if (state.activeView === "agent" && viewId !== "agent" && agentEventSource) {
    agentEventSource.close();
    agentEventSource = null;
  }
  state.activeView = (VIEW_IDS.includes(viewId) || viewId === "job-detail") ? viewId : "dashboard";
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
  // Handle job-detail view (not in VIEW_IDS)
  const jobDetailSection = document.querySelector('[data-view="job-detail"]');
  if (jobDetailSection) {
    const active = state.activeView === "job-detail";
    jobDetailSection.hidden = !active;
    jobDetailSection.classList.toggle("is-active", active);
    jobDetailSection.classList.toggle("is-hidden", !active);
  }
}

function getViewFromHash() {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash) return { view: "dashboard", params: {} };
  const detailMatch = hash.match(/^job-detail\/([^/]+)$/);
  if (detailMatch) return { view: "job-detail", params: { sourceJobId: decodeURIComponent(detailMatch[1]) } };
  const viewId = decodeURIComponent(hash);
  return { view: VIEW_IDS.includes(viewId) ? viewId : "dashboard", params: {} };
}

function navigateTo(viewId, params = {}, updateHash = true) {
  const valid = VIEW_IDS.includes(viewId) || viewId === "job-detail";
  const nextView = valid ? viewId : "dashboard";
  let nextHash = nextView;
  if (viewId === "job-detail" && params.sourceJobId) {
    nextHash = `job-detail/${encodeURIComponent(params.sourceJobId)}`;
  }
  if (updateHash && window.location.hash === `#${nextHash}`) {
    setActiveView(nextView);
    loadView(nextView, params).catch((error) => showError(error.message || "页面加载失败"));
    return;
  }
  if (updateHash) {
    window.location.hash = nextHash;
    return;
  }
  setActiveView(nextView);
  loadView(nextView, params).catch((error) => showError(error.message || "页面加载失败"));
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
  const options = await fetchJson("/web/system/search-options");
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
  const summaryText = [status.city, status.ip].filter(Boolean).join(" / ") || status.message || "-";
  document.getElementById("authStripSummary").innerHTML = [
    status.logged_in ? renderStatusBadge("ok") : renderStatusBadge("warn"),
    `<strong>${escapeHtml(status.logged_in ? status.user_name || "已登录" : "未登录")}</strong>`,
    `<span>${escapeHtml(summaryText)}</span>`,
  ].join("");

  const button = document.getElementById("authActionButton");
  button.textContent = status.logged_in ? "退出登录" : "登录";
  button.dataset.idleText = button.textContent;
}

function buildUnavailableAuthStatus(message) {
  return {
    logged_in: false,
    user_name: "",
    city: "",
    ip: "",
    uid: "",
    message: message || "未获取登录状态，请点击登录重试",
  };
}

function renderAuthDetail(status) {
  const html = [
    `<div><strong>状态：</strong>${status.logged_in ? renderStatusBadge("ok") : renderStatusBadge("warn")}</div>`,
    `<div><strong>用户名：</strong>${escapeHtml(status.user_name || "-")}</div>`,
    `<div><strong>城市：</strong>${escapeHtml(status.city || "-")}</div>`,
    `<div><strong>IP：</strong>${escapeHtml(status.ip || "-")}</div>`,
    `<div><strong>UID：</strong>${escapeHtml(status.uid || "-")}</div>`,
    `<div><strong>提示：</strong>${escapeHtml(status.message || "-")}</div>`,
  ].join("");

  document.getElementById("authSummary").innerHTML = html;
  document.getElementById("dashboardAuthSummary").innerHTML = [
    `<div><strong>当前状态：</strong>${status.logged_in ? "已登录" : "未登录"}</div>`,
    `<div><strong>账号：</strong>${escapeHtml(status.user_name || "-")}</div>`,
    `<div><strong>UID：</strong>${escapeHtml(status.uid || "-")}</div>`,
    `<div><strong>城市：</strong>${escapeHtml(status.city || "-")}</div>`,
    `<div><strong>IP：</strong>${escapeHtml(status.ip || "-")}</div>`,
  ].join("");
}

function setJobDetailDrawerOpen(open) {
  const drawer = document.getElementById("jobDetailDrawer");
  if (!drawer) {
    return;
  }
  drawer.hidden = !open;
  document.body.style.overflow = open ? "hidden" : "";
}

function renderJobDetailDrawerLoading(sourceJobId) {
  const container = document.getElementById("jobDetailContent");
  document.getElementById("jobDetailTitle").textContent = "正在获取职位详情";
  container.innerHTML = `
    <div class="detail-loading">
      <span class="status-badge status-warn">加载中</span>
      <strong>正在获取职位详情</strong>
      <span class="hint-text">${escapeHtml(sourceJobId)}</span>
    </div>
  `;
  document.getElementById("jobDetailMeta").innerHTML = "";
}

function renderJobDetailDrawerError(message) {
  const container = document.getElementById("jobDetailContent");
  document.getElementById("jobDetailTitle").textContent = "职位详情获取失败";
  container.innerHTML = `<div class="empty">${escapeHtml(message || "职位详情获取失败。")}</div>`;
  document.getElementById("jobDetailMeta").innerHTML = "";
}

function buildAiMatchingPanel(job) {
  if (!job.ai_evaluated_at) {
    return `
      <div class="detail-panel">
        <h4>AI 匹配评估 <span class="status-badge status-info">未评估</span></h4>
        <p class="hint-text">尚未进行 AI 评估，可在职位列表中点击"AI评估"按钮进行评估。</p>
      </div>`;
  }

  const matchBadge = job.ai_match
    ? '<span class="status-badge status-ok">匹配</span>'
    : '<span class="status-badge status-error">不匹配</span>';

  const hitRate = buildCacheHitRate(job);
  return `
    <div class="detail-panel">
      <h4>AI 匹配评估 ${matchBadge}</h4>
      <div class="detail-list">
        <div><strong>评分</strong><span>${job.ai_score ?? "-"} / 100</span></div>
        <div><strong>评估时间</strong><span>${escapeHtml(formatDate(job.ai_evaluated_at))}</span></div>
        ${job.ai_prompt_tokens != null ? `<div><strong>Token 用量</strong><span>入 ${formatTokenCount(job.ai_prompt_tokens)} / 出 ${formatTokenCount(job.ai_completion_tokens)}${hitRate ? ` | 缓存命中 ${escapeHtml(hitRate)}` : ""}</span></div>` : ""}
      </div>
      ${job.ai_reasoning ? `<div style="margin-top:0.5rem"><strong>评估理由</strong><p style="margin-top:0.25rem;white-space:pre-wrap">${escapeHtml(job.ai_reasoning)}</p></div>` : ""}
      ${job.ai_reasoning_content ? `<details style="margin-top:0.5rem"><summary>思考过程</summary><p style="margin-top:0.25rem;white-space:pre-wrap">${escapeHtml(job.ai_reasoning_content)}</p></details>` : ""}
    </div>`;
}

function updateJobDetailEvalButton(job) {
  const hasDetail = !!(job.detail_text || job.detail_fetched_at);
  const text = job.ai_evaluated_at ? "重新评估" : "AI评估";
  ["jobDetailDrawerEvalButton", "jobDetailPageEvalButton"].forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (hasDetail) {
      btn.textContent = text;
      btn.hidden = false;
    } else {
      btn.hidden = true;
    }
  });
}

async function evaluateJobDetail(buttonId) {
  buttonId = buttonId || "jobDetailDrawerEvalButton";
  const job = state.jobDetail?.job || state.jobDetailPagePayload?.job;
  const sourceJobId = job?.source_job_id || state.jobDetailSourceJobId || state.jobDetailPageSourceJobId;
  if (!sourceJobId) return;

  clearError();
  setButtonBusy(buttonId, true, "评估中");
  try {
    const result = await fetchJson(`/boss/jobs/${encodeURIComponent(sourceJobId)}/ai/evaluate`, { method: "POST" });
    showNotice(`评估完成: ${result.match ? "匹配" : "不匹配"} (${result.score}分)`, 5000);

    // Refresh detail to get updated AI fields
    const detailPayload = await fetchJson(`/boss/jobs/${encodeURIComponent(sourceJobId)}/detail`);
    const jobData = detailPayload?.job || {};

    // Update drawer if open
    if (state.jobDetail) {
      state.jobDetail = detailPayload;
      const { bodyHtml } = buildJobDetailHtml(detailPayload);
      document.getElementById("jobDetailContent").innerHTML = buildAiMatchingPanel(jobData) + bodyHtml;
      updateJobDetailEvalButton(jobData);
    }

    // Update full-page view if active
    if (state.jobDetailPagePayload) {
      state.jobDetailPagePayload = detailPayload;
      document.getElementById("jobDetailAiPanel").innerHTML = buildAiMatchingPanel(jobData);
      updateJobDetailEvalButton(jobData);
    }

    await loadJobs();
  } catch (error) {
    showError(error.message);
  } finally {
    setButtonBusy(buttonId, false);
  }
}

function buildJobDetailHtml(payload) {
  const job = payload?.job || {};
  const detailPayload = job.detail_payload || {};
  const normalizedDetail = detailPayload.detail_payload || detailPayload;
  const jobSection = normalizedDetail.job || {};
  const companySection = normalizedDetail.company || {};
  const bossSection = normalizedDetail.boss || {};
  const rawPayload = normalizedDetail.raw_payload || detailPayload.response_payload || detailPayload.raw_payload || {};
  const cachedBadge = payload.cached
    ? '<span class="status-badge status-ok">已缓存</span>'
    : '<span class="status-badge status-warn">已采集</span>';
  const detailText = job.detail_text || jobSection.description || "暂无职位详情。";
  const bossOnlineText = job.boss_online === true ? "在线" : job.boss_online === false ? "离线" : "-";
  const jobActiveTimeValue = job.job_active_time || jobSection.active_time;
  const jobActiveTimeText = jobActiveTimeValue ? formatDate(jobActiveTimeValue) : "-";

  const metaHtml = [
    cachedBadge,
    `<span>${escapeHtml(job.source_job_id || "-")}</span>`,
    `<span>${escapeHtml(formatDate(job.detail_fetched_at))}</span>`,
  ].join("");

  const bodyHtml = `
    <div class="detail-panel">
      <h4>BOSS 信息</h4>
      <div class="detail-list">
        <div><strong>姓名</strong><span>${escapeHtml(bossSection.name || "-")}</span></div>
        <div><strong>职位</strong><span>${escapeHtml(bossSection.title || "-")}</span></div>
        <div><strong>在线状态</strong><span>${escapeHtml(bossOnlineText)}</span></div>
        <div><strong>活跃情况</strong><span>${escapeHtml(job.boss_active_text || bossSection.active_text || "-")}</span></div>
      </div>
    </div>

    <div class="detail-summary">
      <div>
        <span class="eyebrow">职位详情</span>
        <h3>${escapeHtml(job.title || jobSection.title || "-")}</h3>
        <p>${escapeHtml(job.company || companySection.name || "-")}</p>
      </div>
      <div class="detail-summary-grid">
        <div><strong>城市</strong><span>${escapeHtml(job.city || jobSection.city || "-")}</span></div>
        <div><strong>薪资</strong><span>${escapeHtml(job.salary || jobSection.salary || "-")}</span></div>
        <div><strong>经验</strong><span>${escapeHtml(job.experience || jobSection.experience || "-")}</span></div>
        <div><strong>学历</strong><span>${escapeHtml(jobSection.degree || "-")}</span></div>
        <div><strong>地址</strong><span>${escapeHtml(jobSection.address || "-")}</span></div>
        <div><strong>状态</strong><span>${escapeHtml(jobSection.status || "-")}</span></div>
      </div>
    </div>

    <div class="detail-panel">
      <h4>职位描述</h4>
      <pre class="detail-pre">${escapeHtml(detailText)}</pre>
    </div>

    <div class="detail-panel">
      <h4>公司信息</h4>
      <div class="detail-list">
        <div><strong>公司</strong><span>${escapeHtml(companySection.name || job.company || "-")}</span></div>
        <div><strong>阶段</strong><span>${escapeHtml(companySection.stage || "-")}</span></div>
        <div><strong>规模</strong><span>${escapeHtml(companySection.scale || "-")}</span></div>
        <div><strong>行业</strong><span>${escapeHtml(companySection.industry || "-")}</span></div>
        <div><strong>岗位活跃时间</strong><span>${escapeHtml(jobActiveTimeText)}</span></div>
        <div><strong>简介</strong><span>${escapeHtml(companySection.intro || "-")}</span></div>
      </div>
    </div>

    <details class="detail-panel">
      <summary>原始数据</summary>
      <pre class="detail-pre">${formatJson(rawPayload)}</pre>
    </details>
  `;

  return { title: job.title || jobSection.title || "查看职位详情", metaHtml, bodyHtml };
}

function renderJobDetailDrawer(payload) {
  const { title, metaHtml, bodyHtml } = buildJobDetailHtml(payload);
  const job = payload?.job || {};
  document.getElementById("jobDetailTitle").textContent = title;
  document.getElementById("jobDetailMeta").innerHTML = metaHtml;
  document.getElementById("jobDetailContent").innerHTML =
    buildAiMatchingPanel(job) + bodyHtml;
  updateJobDetailEvalButton(job);
}

async function loadAuthStatus() {
  try {
    const status = await fetchJson("/boss/system/auth");
    state.auth = status;
    renderAuthStrip(status);
    renderAuthDetail(status);
    return status;
  } catch (error) {
    const status = buildUnavailableAuthStatus(error.message || "未获取登录状态，请点击登录重试");
    state.auth = status;
    renderAuthStrip(status);
    renderAuthDetail(status);
    return status;
  }
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
  const doctor = await fetchJson("/boss/system/doctor");
  state.doctor = doctor;
  renderDoctor(doctor);
  return doctor;
}

async function loadSummaryCards() {
  const summary = await fetchJson("/web/dashboard");
  const labels = {
    jobs: "职位线索",
    tasks: "任务记录",
    friends: "沟通记录",
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
  if (Array.isArray(inputPayload.source_job_ids) && inputPayload.source_job_ids.length) {
    return `指定职位 ${inputPayload.source_job_ids.length} 个`;
  }
  if (inputPayload.limit) {
    return `limit=${inputPayload.limit}`;
  }
  return escapeHtml(JSON.stringify(inputPayload));
}

async function loadTasks(limit = 100) {
  const items = await fetchJson(`/boss/tasks?limit=${limit}`);
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

function readJobsPageParams() {
  const params = new URLSearchParams(window.location.search);
  const page = Math.max(1, parseInt(params.get("page") || "1", 10) || 1);
  const limitValues = [20, 50, 100, 200, 500, 1000];
  const rawLimit = parseInt(params.get("limit") || "100", 10) || 100;
  const limit = limitValues.includes(rawLimit) ? rawLimit : 100;
  return { page, limit };
}

function updateJobsPageParams(page, limit) {
  const params = new URLSearchParams(window.location.search);
  params.set("page", String(page));
  params.set("limit", String(limit));
  const newUrl = `${window.location.pathname}?${params.toString()}${window.location.hash}`;
  window.history.replaceState(null, "", newUrl);
  state.jobsPage = page;
  state.jobsLimit = limit;
}

async function loadJobs() {
  const { page, limit } = readJobsPageParams();
  state.jobsPage = page;
  state.jobsLimit = limit;

  const greeted = document.getElementById("jobsGreetedFilter")?.value || "";
  const createdToday = document.getElementById("jobsCreatedTodayFilter")?.value || "";
  const updatedToday = document.getElementById("jobsUpdatedTodayFilter")?.value || "";
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (greeted === "true") params.set("greeted", "true");
  else if (greeted === "false") params.set("greeted", "false");
  if (createdToday === "true") params.set("created_today", "true");
  if (updatedToday === "true") params.set("updated_today", "true");

  const result = await fetchJson(`/boss/jobs?${params.toString()}`);
  state.jobs = result.items || [];
  state.jobsTotal = result.total || 0;
  renderJobsTable();
  return state.jobs;
}

async function goToJobsPage(page) {
  page = Math.max(1, Math.min(page, Math.ceil(state.jobsTotal / state.jobsLimit)));
  updateJobsPageParams(page, state.jobsLimit);
  await loadJobs();
}

async function changeJobsLimit(limit) {
  limit = parseInt(limit, 10) || 100;
  updateJobsPageParams(1, limit);
  await loadJobs();
}

function renderJobsTable() {
  const items = getSortedFilteredJobs();
  const totalPages = Math.max(1, Math.ceil(state.jobsTotal / state.jobsLimit));
  document.getElementById("jobsCount").textContent = `共 ${items.length} 条（全部 ${state.jobsTotal} 条，第 ${state.jobsPage}/${totalPages} 页）`;
  renderTable(
    "jobsTable",
    [
      { label: "职位", render: (row) => escapeHtml(row.title) },
      { label: "公司", render: (row) => escapeHtml(row.company) },
      { label: "规模", render: (row) => escapeHtml(getCompanyScale(row) || "-") },
      { label: "行业", render: (row) => escapeHtml(row.industry || "-") },
      { label: "薪资", render: (row) => escapeHtml(row.salary || "-") },
      { label: "经验", render: (row) => escapeHtml(row.experience || "-") },
      { label: "活跃情况", render: (row) => escapeHtml(row.boss_active_text || "-") },
      { label: "搜索次数", render: (row) => escapeHtml(String(row.search_count ?? 0)) },
      { label: "最近搜索", render: (row) => escapeHtml(formatDate(row.last_searched_at || row.last_seen_at)) },
      { label: "详情状态", render: (row) => renderDetailStateBadge(row.detail_fetched_at) },
      { label: "详情", render: (row) => renderJobDetailAction(row) },
      {
        label: "链接",
        render: (row) => renderJobLinkButton(row),
      },
      {
        label: "状态",
        render: (row) => escapeHtml(`${row.match_status}${row.greeted ? " / 已打招呼" : ""}`),
      },
      { label: "AI评分", render: (row) => renderAiScore(row) },
      { label: "AI匹配", render: (row) => renderAiMatchBadge(row) },
    ],
    items,
  );

  renderJobsPagination();
}

function renderJobsPagination() {
  const paginationBar = document.getElementById("jobsPagination");
  if (!paginationBar) return;
  paginationBar.hidden = false;

  const totalPages = Math.max(1, Math.ceil(state.jobsTotal / state.jobsLimit));
  const page = state.jobsPage;

  document.getElementById("jobsPageInfo").textContent =
    `共 ${state.jobsTotal} 条职位，第 ${page}/${totalPages} 页`;

  document.getElementById("jobsLimitSelect").value = String(state.jobsLimit);
  document.getElementById("jobsCurrentPage").textContent = `第 ${page} 页`;
  document.getElementById("jobsPrevPageButton").disabled = page <= 1;
  document.getElementById("jobsPrevPageButton").classList.toggle("button-disabled", page <= 1);
  document.getElementById("jobsNextPageButton").disabled = page >= totalPages;
  document.getElementById("jobsNextPageButton").classList.toggle("button-disabled", page >= totalPages);
}

function getSortedFilteredJobs() {
  let items = [...state.jobs];

  // filter
  const greeted = document.getElementById("jobsGreetedFilter")?.value || "";
  if (greeted === "true") {
    items = items.filter((row) => row.greeted);
  } else if (greeted === "false") {
    items = items.filter((row) => !row.greeted);
  }
  const aiMatch = document.getElementById("jobsAiMatchFilter")?.value || "";
  if (aiMatch === "true") {
    items = items.filter((row) => row.ai_match === true);
  } else if (aiMatch === "false") {
    items = items.filter((row) => row.ai_match === false);
  } else if (aiMatch === "null") {
    items = items.filter((row) => row.ai_match === null || row.ai_match === undefined);
  }
  const cityFilter = (document.getElementById("jobsCityFilter")?.value || "").trim().toLowerCase();
  if (cityFilter) {
    items = items.filter((row) => (row.city || "").toLowerCase().includes(cityFilter));
  }
  const keyword = (document.getElementById("jobsKeywordFilter")?.value || "").trim().toLowerCase();
  if (keyword) {
    items = items.filter(
      (row) =>
        (row.title || "").toLowerCase().includes(keyword) ||
        (row.company || "").toLowerCase().includes(keyword),
    );
  }

  // sort
  const sortBy = document.getElementById("jobsSortSelect")?.value || "last_searched_at_desc";
  const [field, dir] = sortBy.split(/_(?=[^_]*$)/);
  const direction = dir === "asc" ? 1 : -1;
  items.sort((a, b) => {
    let va, vb;
    switch (field) {
      case "last_searched_at":
        va = a.last_searched_at || a.last_seen_at || "";
        vb = b.last_searched_at || b.last_seen_at || "";
        break;
      case "company":
        va = (a.company || "").toLowerCase();
        vb = (b.company || "").toLowerCase();
        break;
      case "title":
        va = (a.title || "").toLowerCase();
        vb = (b.title || "").toLowerCase();
        break;
      case "search_count":
        va = a.search_count ?? 0;
        vb = b.search_count ?? 0;
        break;
      case "ai_score":
        va = a.ai_score ?? -1;
        vb = b.ai_score ?? -1;
        break;
      default:
        return 0;
    }
    if (va < vb) return -1 * direction;
    if (va > vb) return 1 * direction;
    return 0;
  });

  return items;
}

function renderJobLinkButton(row) {
  if (!row.job_url) return "-";
  return `<button type="button" class="button-link" data-copy-link="${escapeHtml(row.job_url)}" title="复制职位链接">📋 复制链接</button>`;
}

function renderAiScore(row) {
  if (row.ai_evaluated_at) {
    return `<span class="ai-score">${row.ai_score ?? "-"}</span>`;
  }
  return '<span class="hint-text">-</span>';
}

function renderAiMatchBadge(row) {
  if (row.ai_match === true) {
    return '<span class="status-badge status-ok">匹配</span>';
  }
  if (row.ai_match === false) {
    return '<span class="status-badge status-error">不匹配</span>';
  }
  return '<span class="status-badge status-info">未评</span>';
}

function formatTokenCount(n) {
  if (n == null) return "-";
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "m";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function buildCacheHitRate(job) {
  if (job.ai_prompt_tokens == null || job.ai_cache_hit_tokens == null) return null;
  if (job.ai_prompt_tokens === 0) return null;
  return (job.ai_cache_hit_tokens / job.ai_prompt_tokens * 100).toFixed(1) + "%";
}

function renderJobActions(row) {
  if (!row.detail_fetched_at) {
    return '<span class="hint-text">待采集</span>';
  }
  return `<button type="button" class="button-link" data-ai-evaluate="${escapeHtml(row.source_job_id)}">AI评估</button>`;
}

async function copyJobLink(url, button) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(url);
    ok = true;
  } catch {
    // Fallback for browsers that block clipboard API
  }

  if (!ok) {
    try {
      const textarea = document.createElement("textarea");
      textarea.value = url;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      ok = true;
    } catch {
      // Both methods failed
    }
  }

  if (ok) {
    if (button) {
      const original = button.textContent;
      button.textContent = "✅ 已复制!";
      button.disabled = true;
      setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
      }, 2000);
    }
  } else {
    showError("复制失败，请手动复制链接");
  }
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

function getWorker(name) {
  return state.workers.find((item) => item.worker_name === name) || null;
}

function renderWorkerMeta(containerId, worker, lines) {
  const container = document.getElementById(containerId);
  if (!container) {
    return;
  }
  if (!worker) {
    container.innerHTML = '<div class="empty">暂无配置。</div>';
    return;
  }
  container.innerHTML = lines.map((line) => `<div>${line}</div>`).join("");
}

function renderWorkers() {
  const scrollAndCollectWorker = getWorker("scroll_and_collect");
  const scrollAndCollectReleaseButton = document.getElementById("releaseScrollAndCollectWorkerButton");

  if (scrollAndCollectWorker) {
    document.getElementById("scrollAndCollectWorkerBatchSizeInput").value = String(scrollAndCollectWorker.batch_size || 100);
    document.getElementById("scrollAndCollectWorkerJitterInput").value = String(scrollAndCollectWorker.query?.schedule_jitter_minutes ?? 30);
    const scheduleTimes = scrollAndCollectWorker.query?.schedule_times || ["09:00", "14:00", "18:00"];
    document.getElementById("scrollAndCollectWorkerScheduleInput").value = Array.isArray(scheduleTimes) ? scheduleTimes.join(",") : "";
    if (scrollAndCollectReleaseButton) {
      scrollAndCollectReleaseButton.disabled = !(scrollAndCollectWorker.enabled && scrollAndCollectWorker.status === "error");
      scrollAndCollectReleaseButton.classList.toggle("button-disabled", scrollAndCollectReleaseButton.disabled);
    }
    const summary = scrollAndCollectWorker.last_result_summary || {};
    const statsLine = [
      summary.scroll_collected ? `列表 ${summary.scroll_collected}` : null,
      summary.detail_collected != null ? `详情 ${summary.detail_collected}` : null,
      summary.detail_created != null ? `新建 ${summary.detail_created}` : null,
      summary.detail_updated != null ? `更新 ${summary.detail_updated}` : null,
      summary.detail_skipped != null ? `跳过 ${summary.detail_skipped}` : null,
    ].filter(Boolean).join(" / ") || "无记录";
    renderWorkerMeta("scrollAndCollectWorkerMeta", scrollAndCollectWorker, [
      `<strong>状态</strong> ${renderStatusBadge(scrollAndCollectWorker.enabled ? scrollAndCollectWorker.status : "idle")} ${scrollAndCollectWorker.enabled ? "" : '<span class="hint-text">未启动</span>'}`,
      `<strong>最大采集数</strong> ${escapeHtml(scrollAndCollectWorker.batch_size || 100)}`,
      `<strong>时间点</strong> ${escapeHtml((scrollAndCollectWorker.query?.schedule_times || []).join(", "))}`,
      `<strong>随机偏移</strong> ±${escapeHtml(scrollAndCollectWorker.query?.schedule_jitter_minutes ?? 30)} 分钟`,
      `<strong>下次执行</strong> ${escapeHtml(formatDate(scrollAndCollectWorker.next_run_at))}`,
      `<strong>最近完成</strong> ${escapeHtml(formatDate(scrollAndCollectWorker.last_finished_at))}`,
      `<strong>最近统计</strong> ${statsLine}`,
      `<strong>最近错误</strong> ${escapeHtml(scrollAndCollectWorker.last_error || "-")}`,
    ]);
  }

  renderAiMatchingWorker();
  renderAgentWorker();
}

function renderAgentWorker() {
  const worker = getWorker("agent");
  const releaseButton = document.getElementById("releaseAgentWorkerButton");
  const meta = document.getElementById("agentWorkerMeta");
  if (!worker) {
    if (meta) meta.innerHTML = "";
    return;
  }
  document.getElementById("agentScheduleTimes").value = (worker.query.schedule_times || ["09:00", "14:00", "18:00"]).join(", ");
  document.getElementById("agentScheduleJitterMinutes").value = String(worker.query.schedule_jitter_minutes ?? 60);
  document.getElementById("agentGreetLimit").value = String(worker.query.greet_limit ?? 10);
  if (releaseButton) {
    releaseButton.disabled = !(worker.enabled && worker.status === "error");
    releaseButton.classList.toggle("button-disabled", releaseButton.disabled);
  }
  if (meta) {
    const parts = [
      `<span>${renderStatusBadge(worker.enabled ? worker.status : "idle")}${worker.enabled ? "" : " <span class='hint-text'>未启动</span>"}</span>`,
      worker.next_run_at ? `<span>下次: ${escapeHtml(formatDate(worker.next_run_at))}</span>` : null,
      worker.last_finished_at ? `<span>上次: ${escapeHtml(formatDate(worker.last_finished_at))}</span>` : null,
      worker.last_error ? `<span class="hint-text">错误: ${escapeHtml(worker.last_error)}</span>` : null,
    ].filter(Boolean);
    meta.innerHTML = parts.join(" · ");
  }
}

function renderAiMatchingWorker() {
  const worker = getWorker("ai_matching");
  const releaseButton = document.getElementById("releaseAiMatchingWorkerButton");
  if (!worker) {
    if (document.getElementById("aiMatchingWorkerMeta")) {
      renderWorkerMeta("aiMatchingWorkerMeta", null, []);
    }
    return;
  }
  document.getElementById("aiMatchingWorkerIntervalInput").value = String(worker.interval_seconds || 3600);
  document.getElementById("aiMatchingWorkerBatchSizeInput").value = String(worker.batch_size || 10);
  if (releaseButton) {
    releaseButton.disabled = !(worker.enabled && worker.status === "error");
    releaseButton.classList.toggle("button-disabled", releaseButton.disabled);
  }
  renderWorkerMeta("aiMatchingWorkerMeta", worker, [
    `<strong>状态</strong> ${renderStatusBadge(worker.enabled ? worker.status : "idle")} ${worker.enabled ? "" : '<span class="hint-text">未启动</span>'}`,
    `<strong>下一次执行</strong> ${escapeHtml(formatDate(worker.next_run_at))}`,
    `<strong>最近错误</strong> ${escapeHtml(worker.last_error || "-")}`,
    `<strong>最近结果</strong> ${escapeHtml(JSON.stringify(worker.last_result_summary || {}))}`,
  ]);
}

async function loadWorkers() {
  state.workers = await fetchJson("/boss/workers");
  renderWorkers();
  return state.workers;
}

function getSearchPageValue() {
  return Math.max(1, Number(document.getElementById("searchPageInput").value || 1));
}

function setSearchPageValue(page) {
  document.getElementById("searchPageInput").value = String(Math.max(1, page));
  persistSearchFormState();
}

async function loadCurrentSearchResults() {
  const tasks = await fetchJson("/boss/tasks?limit=100");
  const latestSearchTask = tasks.find((item) => item.task_type === "search");
  if (!latestSearchTask) {
    renderLatestSearchMeta(null, []);
    renderEmpty("searchResultsTable", "暂无搜索结果，请先执行一次职位搜索。");
    return [];
  }

  const rows = await fetchJson(`/boss/jobs/collections?task_id=${encodeURIComponent(latestSearchTask.id)}&limit=200`);
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
      { label: "详情", render: (row) => renderJobDetailAction(row) },
      {
        label: "链接",
        render: (row) => renderJobLinkButton(row),
      },
    ],
    rows,
  );
  return rows;
}

async function openJobDetail(sourceJobId) {
  if (!sourceJobId) {
    return;
  }
  clearError();
  state.jobDetailSourceJobId = sourceJobId;
  state.jobDetailLoading = true;
  setJobDetailDrawerOpen(true);
  renderJobDetailDrawerLoading(sourceJobId);
  try {
    const payload = await fetchJson(`/boss/jobs/${encodeURIComponent(sourceJobId)}/detail`);
    state.jobDetail = payload;
    renderJobDetailDrawer(payload);
    if (payload.cached) {
      showNotice("职位详情已从缓存读取", 5000);
    } else {
      showNotice("职位详情已从 BOSS 采集并保存", 5000);
    }
    loadJobs().catch((error) => showError(error.message || "职位列表刷新失败"));
  } catch (error) {
    renderJobDetailDrawerError(error.message || "职位详情获取失败");
    if (error.status && error.status >= 500) {
      showError(error.message || "职位详情获取失败");
    }
  } finally {
    state.jobDetailLoading = false;
  }
}

function closeJobDetailDrawer() {
  state.jobDetail = null;
  state.jobDetailLoading = false;
  state.jobDetailSourceJobId = null;
  setJobDetailDrawerOpen(false);
}

// ── Chat History Drawer ──

function setChatHistoryDrawerOpen(open) {
  const drawer = document.getElementById("chatHistoryDrawer");
  if (!drawer) return;
  drawer.hidden = !open;
  document.body.style.overflow = open ? "hidden" : "";
}

function renderChatHistoryDrawerLoading(name) {
  document.getElementById("chatHistoryTitle").textContent = "正在获取聊天记录";
  document.getElementById("chatHistoryContent").innerHTML =
    `<div class="detail-loading"><span class="status-badge status-warn">加载中</span><strong>正在获取与 ${escapeHtml(name)} 的聊天记录</strong></div>`;
  document.getElementById("chatHistoryMeta").innerHTML = "";
}

function renderChatHistoryDrawerError(message) {
  document.getElementById("chatHistoryTitle").textContent = "聊天记录获取失败";
  document.getElementById("chatHistoryContent").innerHTML = `<div class="empty">${escapeHtml(message || "聊天记录获取失败。")}</div>`;
  document.getElementById("chatHistoryMeta").innerHTML = "";
}

function messageTypeLabel(type) {
  const map = { 1: "文本", 2: "图片", 3: "语音", 7: "简历", 8: "招呼", 9: "交换微信", 10: "交换电话" };
  return map[type] || `类型${type}`;
}

function messageSenderLabel(message, sourceFriendId, friendName) {
  if (message?.from_name) {
    return escapeHtml(message.from_name);
  }
  const fromId = message?.from_id;
  if (!sourceFriendId) return "对方";
  if (fromId && String(fromId) === String(sourceFriendId)) {
    return escapeHtml(friendName || "对方");
  }
  return "我";
}

function renderChatHistoryMessages(messages, sourceFriendId, friendName) {
  if (!messages.length) {
    return '<div class="empty">暂无聊天记录。</div>';
  }
  return messages
    .slice()
    .reverse()
    .map((m) => {
      const sender = messageSenderLabel(m, sourceFriendId, friendName);
      const isSelf = sender === "我";
      const typeLabel = messageTypeLabel(m.type);
      const time = m.created_at ? formatDate(m.created_at) : "-";
      return `
        <div class="chat-message-card${isSelf ? " chat-message-self" : ""}">
          <div class="chat-message-header">
            <span class="chat-message-sender">${sender}</span>
            <span>${escapeHtml(typeLabel)} &middot; ${escapeHtml(time)}</span>
          </div>
          <div class="chat-message-body">${escapeHtml(m.content || "")}</div>
        </div>`;
    })
    .join("");
}

async function loadFriendMessages(sourceFriendId, page) {
  return await fetchJson(
    `/boss/friends/${encodeURIComponent(sourceFriendId)}/messages?page=${page || 1}&count=100`
  );
}

async function openFriendChat(sourceFriendId, name) {
  if (!sourceFriendId) return;
  clearError();
  state.chatHistorySourceFriendId = sourceFriendId;
  state.chatHistoryPage = 1;
  state.chatHistoryName = name;
  setChatHistoryDrawerOpen(true);
  renderChatHistoryDrawerLoading(name);

  try {
    const payload = await loadFriendMessages(sourceFriendId, 1);
    renderChatHistoryDrawer(payload);
  } catch (error) {
    renderChatHistoryDrawerError(error.message || "聊天记录获取失败");
  }
}

function renderChatHistoryDrawer(payload) {
  const name = state.chatHistoryName;
  const sourceFriendId = state.chatHistorySourceFriendId;
  document.getElementById("chatHistoryTitle").textContent = `与 ${escapeHtml(name)} 的聊天记录`;
  document.getElementById("chatHistoryMeta").innerHTML = [
    `<span>共 ${payload.total} 条消息</span>`,
  ].join("");

  document.getElementById("chatHistoryContent").innerHTML = renderChatHistoryMessages(
    payload.messages || [],
    sourceFriendId,
    name
  );
}

async function goChatHistoryPage(delta) {
  const nextPage = state.chatHistoryPage + delta;
  if (nextPage < 1) return;
  const { chatHistorySourceFriendId } = state;
  if (!chatHistorySourceFriendId) return;

  setButtonBusy("chatHistoryPrevPageButton", true, "加载中");
  setButtonBusy("chatHistoryNextPageButton", true, "加载中");
  try {
    const payload = await loadFriendMessages(chatHistorySourceFriendId, nextPage);
    state.chatHistoryPage = nextPage;
    renderChatHistoryDrawer(payload);
  } catch (error) {
    showError(error.message || "翻页失败");
    setButtonBusy("chatHistoryPrevPageButton", false);
    setButtonBusy("chatHistoryNextPageButton", false);
  }
}

function closeChatHistoryDrawer() {
  state.chatHistorySourceFriendId = null;
  state.chatHistoryPage = 1;
  state.chatHistoryName = "";
  setChatHistoryDrawerOpen(false);
}

// ── Job Detail Page ──

async function loadJobDetailPage(sourceJobId, options = {}) {
  if (!sourceJobId) {
    showError("缺少职位主键");
    return;
  }
  const forceRefresh = options.forceRefresh === true;

  state.jobDetailPageSourceJobId = sourceJobId;
  state.jobDetailPagePayload = null;
  clearError();

  // Job detail: fetch first (uses cache, or triggers BOSS fetch if missing)
  document.getElementById("jobDetailPageTitle").textContent = "正在加载";
  document.getElementById("jobDetailPageMeta").innerHTML = "";
  document.getElementById("jobDetailPageContent").innerHTML =
    '<div class="empty">正在加载职位详情</div>';
  document.getElementById("jobDetailGreetButton").hidden = true;

  // Chat: show cached messages only (no BOSS fetch)
  document.getElementById("jobDetailChatTitle").textContent = "聊天记录";
  document.getElementById("jobDetailChatMeta").textContent = "";
  document.getElementById("jobDetailChatContent").innerHTML =
    '<div class="empty">暂无缓存，点击"同步聊天记录"获取</div>';
  document.getElementById("jobDetailMessageInput").value = "";

  const securityId = state.jobDetailPageSecurityId || "";
  const params = new URLSearchParams();
  if (securityId) {
    params.set("security_id", securityId);
  }
  if (forceRefresh) {
    params.set("force_refresh", "true");
  }
  const detailUrl = params.size > 0
    ? `/boss/jobs/${encodeURIComponent(sourceJobId)}/detail?${params.toString()}`
    : `/boss/jobs/${encodeURIComponent(sourceJobId)}/detail`;

  try {
    const detailResult = await fetchJson(detailUrl);
    if (state.jobDetailPageForceContact && detailResult?.job) {
      detailResult.job.contact = true;
    }
    state.jobDetailPagePayload = detailResult;
    renderJobDetailPageDetail(detailResult);
  } catch (error) {
    document.getElementById("jobDetailPageTitle").textContent = "职位详情加载失败";
    document.getElementById("jobDetailPageContent").innerHTML =
      `<div class="empty">${escapeHtml(error.message || "职位详情加载失败")}</div>`;
    return;
  }

  // After job detail loaded, try loading cached chat messages
  loadJobDetailPageCachedChat(sourceJobId);
}

function getCurrentJobDetailSourceFriendId() {
  return state.jobDetailPageSourceFriendId || state.jobDetailPagePayload?.job?.source_friend_id || "";
}

function canLoadJobDetailChat() {
  return state.jobDetailPagePayload?.job?.contact === true;
}

function renderJobDetailChatUnavailable() {
  document.getElementById("jobDetailChatTitle").textContent = "聊天记录";
  document.getElementById("jobDetailChatMeta").textContent = "";
  document.getElementById("jobDetailChatContent").innerHTML =
    '<div class="empty">尚未沟通，无需加载聊天记录</div>';
  document.getElementById("jobDetailMessageInput").value = "";
}

async function loadJobDetailPageCachedChat(sourceJobId) {
  if (!canLoadJobDetailChat()) {
    renderJobDetailChatUnavailable();
    return;
  }
  const sourceFriendId = getCurrentJobDetailSourceFriendId();
  if (!sourceFriendId) return;
  try {
    const chatPayload = await fetchJson(
      `/boss/friends/${encodeURIComponent(sourceFriendId)}/messages?page=1&count=100&cached_only=true`
    );
    if (chatPayload.messages && chatPayload.messages.length > 0) {
      renderJobDetailPageChat(chatPayload);
    }
  } catch (_) {
    // No cached messages is fine — user can sync
  }
}

function renderJobDetailPageChat(payload) {
  const name = state.jobDetailPageName || "";
  const sourceFriendId = state.jobDetailPageSourceFriendId || "";
  const messages = payload?.messages || [];
  const total = payload?.total || messages.length;

  document.getElementById("jobDetailChatTitle").textContent = name
    ? `与 ${escapeHtml(name)} 的聊天记录`
    : "聊天记录";
  document.getElementById("jobDetailChatMeta").textContent = `共 ${total} 条消息`;
  document.getElementById("jobDetailChatContent").innerHTML = renderChatHistoryMessages(
    messages,
    sourceFriendId,
    name
  );
}

function renderJobDetailPageDetail(payload) {
  const { title, metaHtml, bodyHtml } = buildJobDetailHtml(payload);
  const job = payload?.job || {};
  document.getElementById("jobDetailPageTitle").textContent = title;
  document.getElementById("jobDetailPageMeta").innerHTML = metaHtml;
  document.getElementById("jobDetailPageContent").innerHTML = bodyHtml;
  document.getElementById("jobDetailAiPanel").innerHTML = buildAiMatchingPanel(job);
  updateJobDetailEvalButton(job);
  const contact = job.contact;
  document.getElementById("jobDetailGreetButton").hidden = contact === true;
  document.getElementById("jobDetailSyncChatButton").hidden = contact !== true;
  document.getElementById("jobDetailMessageInput").hidden = contact !== true;
  document.getElementById("jobDetailSendMessageButton").hidden = contact !== true;
  document.getElementById("jobDetailAiMessageButton").hidden = contact !== true;
  clearAiMessageInfo();
  if (contact !== true) {
    renderJobDetailChatUnavailable();
  }
}

async function greetCurrentJobDetail() {
  const job = state.jobDetailPagePayload?.job;
  if (!job?.source_job_id) {
    showError("缺少职位主键");
    return;
  }

  clearError();
  setButtonBusy("jobDetailGreetButton", true, "打招呼中");
  try {
    const result = await fetchJson("/boss/tasks/greet", {
      method: "POST",
      body: JSON.stringify({ source_job_ids: [job.source_job_id], limit: 1 }),
    });
    showNotice(`已触发打招呼任务 ${result.task_id}`, 5000);
    await Promise.all([loadJobDetailPage(state.jobDetailPageSourceJobId), loadJobs(), loadTasks(), loadSummaryCards()]);
  } finally {
    setButtonBusy("jobDetailGreetButton", false);
  }
}

async function syncJobDetailPageDetail() {
  const sourceJobId = state.jobDetailPageSourceJobId;
  if (!sourceJobId) {
    showError("缺少职位主键");
    return;
  }

  clearError();
  setButtonBusy("jobDetailSyncDetailButton", true, "同步中");
  try {
    await loadJobDetailPage(sourceJobId, { forceRefresh: true });
    showNotice("职位详情已同步", 3000);
  } finally {
    setButtonBusy("jobDetailSyncDetailButton", false);
  }
}

async function generateAiMessageForJobDetail() {
  if (!canLoadJobDetailChat()) {
    showError("当前未建立沟通，无法生成 AI 消息");
    return;
  }
  const sourceJobId = state.jobDetailPageSourceJobId;
  const sourceFriendId = getCurrentJobDetailSourceFriendId();
  if (!sourceJobId) {
    showError("缺少职位主键");
    return;
  }

  clearError();
  showNotice("正在同步聊天记录并生成 AI 消息…", 8000);
  setButtonBusy("jobDetailAiMessageButton", true, "生成中");
  try {
    try {
      await fetchJson("/boss/friends/sync", { method: "POST" });
      const chatPayload = await fetchJson(
        `/boss/friends/${encodeURIComponent(sourceFriendId)}/messages?page=1&count=100`
      );
      renderJobDetailPageChat(chatPayload);
    } catch (syncError) {
      console.warn("Chat sync failed, continuing with cached messages:", syncError);
    }

    const input = document.getElementById("jobDetailMessageInput");
    const result = await fetchJson(`/boss/jobs/${encodeURIComponent(sourceJobId)}/ai/message`, {
      method: "POST",
      body: JSON.stringify({ context: input.value || null }),
    });
    if (result.message) {
      input.value = result.message;
    }
    renderAiMessageInfo(result);
    showNotice("AI 消息已生成，可修改后发送", 5000);
  } catch (error) {
    showError(error.message || "AI 消息生成失败");
    clearAiMessageInfo();
  } finally {
    setButtonBusy("jobDetailAiMessageButton", false);
  }
}

function renderAiMessageInfo(result) {
  const container = document.getElementById("jobDetailAiMessageInfo");
  if (!container) return;
  const hitRate = result.prompt_tokens != null && result.cache_hit_tokens != null && result.prompt_tokens > 0
    ? ` | 缓存命中 ${(result.cache_hit_tokens / result.prompt_tokens * 100).toFixed(1)}%`
    : "";
  container.innerHTML = [
    result.reasoning ? `<div><span class="label">生成理由</span><p style="margin-top:0.25rem;white-space:pre-wrap">${escapeHtml(result.reasoning)}</p></div>` : "",
    result.reasoning_content ? `<details style="margin-top:0.5rem"><summary>思考过程</summary><p style="margin-top:0.25rem;white-space:pre-wrap">${escapeHtml(result.reasoning_content)}</p></details>` : "",
    result.prompt_tokens != null
      ? `<hr class="divider"><div><span class="label">Token 用量</span> 入 ${escapeHtml(formatTokenCount(result.prompt_tokens))} / 出 ${escapeHtml(formatTokenCount(result.completion_tokens))}${hitRate}</div>`
      : "",
  ].filter(Boolean).join("\n");
  container.hidden = !(result.reasoning || result.reasoning_content || result.prompt_tokens != null);
}

function clearAiMessageInfo() {
  const container = document.getElementById("jobDetailAiMessageInfo");
  if (container) {
    container.innerHTML = "";
    container.hidden = true;
  }
}

async function syncChatHistoryForJobDetail() {
  if (!canLoadJobDetailChat()) {
    renderJobDetailChatUnavailable();
    return;
  }
  const sourceFriendId = getCurrentJobDetailSourceFriendId();
  if (!sourceFriendId) {
    showError("缺少好友主键");
    return;
  }
  clearError();
  setButtonBusy("jobDetailSyncChatButton", true, "同步中");
  try {
    await fetchJson("/boss/friends/sync", { method: "POST" });
    const payload = await fetchJson(
      `/boss/friends/${encodeURIComponent(sourceFriendId)}/messages?page=1&count=100`
    );
    renderJobDetailPageChat(payload);
    showNotice("聊天记录已同步", 3000);
  } catch (error) {
    showError(error.message || "同步聊天记录失败");
  } finally {
    setButtonBusy("jobDetailSyncChatButton", false);
  }
}

async function sendMessageForJobDetail() {
  if (!canLoadJobDetailChat()) {
    renderJobDetailChatUnavailable();
    return;
  }
  const sourceFriendId = getCurrentJobDetailSourceFriendId();
  const input = document.getElementById("jobDetailMessageInput");
  const content = input.value.trim();
  if (!sourceFriendId) {
    showError("缺少好友主键");
    return;
  }
  if (!content) {
    showError("消息内容不能为空");
    return;
  }

  clearError();
  setButtonBusy("jobDetailSendMessageButton", true, "发送中");
  try {
    await fetchJson(`/boss/friends/${encodeURIComponent(sourceFriendId)}/messages/send`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    input.value = "";
    clearAiMessageInfo();
    const payload = await fetchJson(
      `/boss/friends/${encodeURIComponent(sourceFriendId)}/messages?page=1&count=100`
    );
    renderJobDetailPageChat(payload);
    showNotice("消息已发送", 3000);
  } finally {
    setButtonBusy("jobDetailSendMessageButton", false);
  }
}

async function loadFriends() {
  const items = await fetchJson("/boss/friends");
  document.getElementById("conversationsCount").textContent = `共 ${items.length} 条`;
  renderTable(
    "conversationsTable",
    [
      { label: "姓名", render: (row) => escapeHtml(row.name || row.title) },
      { label: "职位", render: (row) => escapeHtml(row.title) },
      { label: "公司", render: (row) => escapeHtml(row.company || "-") },
      { label: "发起方", render: (row) => renderRelationType(row.relation_type) },
      { label: "未读", render: (row) => renderUnreadBadge(row.unread_count) },
      { label: "状态", render: (row) => renderReadStatus(row.read_status_label || row.read_status) },
      { label: "最近消息", render: (row) => escapeHtml(row.last_message || "-") },
      { label: "最近时间", render: (row) => escapeHtml(row.last_message_at || "-") },
      { label: "聊天", render: (row) => renderChatHistoryAction(row) },
      { label: "详情", render: (row) => renderJobDetailPageAction(row) },
    ],
    items,
  );
  return items;
}

function renderRelationType(relationType) {
  if (!relationType) return "-";
  const map = { 1: "对方主动", 2: "我主动", 3: "投递" };
  return escapeHtml(map[relationType] || "-");
}

function renderUnreadBadge(count) {
  if (count > 0) {
    return `<span class="status-badge status-warn">${escapeHtml(String(count))}</span>`;
  }
  return `<span class="status-badge status-ok">0</span>`;
}

function renderReadStatus(value) {
  if (value == null) return "-";
  if (String(value) === "1") return "送达";
  if (String(value) === "2") return "已读";
  return String(value);
}

function renderChatHistoryAction(row) {
  const sourceFriendId = row.source_friend_id;
  if (!sourceFriendId) return "-";
  const name = row.name || "";
  return `<button type="button" class="button-link" data-chat-history="${escapeHtml(sourceFriendId)}|${escapeHtml(name)}">查看聊天</button>`;
}

function renderJobDetailPageAction(row) {
  const sourceJobId = row.source_job_id;
  if (!sourceJobId) return "-";
  const name = row.name || "";
  const sourceFriendId = row.source_friend_id || "";
  const securityId = row.security_id || "";
  return `<button type="button" class="button-link" data-job-detail-page="${escapeHtml(sourceJobId)}|${escapeHtml(name)}|${escapeHtml(sourceFriendId)}|${escapeHtml(securityId)}">职位详情</button>`;
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
  const payload = await fetchJson(`/web/system/logs?limit=${DEFAULT_LOG_LIMIT}`);
  renderLogs(payload);
  return payload;
}

async function loadDashboardView() {
  const [, auth, doctor, tasks] = await Promise.all([
    loadSummaryCards(),
    loadAuthStatus(),
    loadDoctor(),
    fetchJson("/boss/tasks?limit=5"),
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

function collectScrollSearchPayload() {
  persistSearchFormState();
  const keywordsText = document.getElementById("searchKeywordsInput").value.trim();
  const keywords = keywordsText
    .split(/[\s,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);

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

  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== null && value !== "" && (!Array.isArray(value) || value.length > 0)),
  );
}

function collectScrollAndCollectWorkerPayload() {
  const raw = document.getElementById("scrollAndCollectWorkerScheduleInput").value || "";
  const scheduleTimes = raw
    .split(",")
    .map((s) => s.trim())
    .filter((s) => /^\d{2}:\d{2}$/.test(s));
  return {
    batch_size: Math.max(1, Number(document.getElementById("scrollAndCollectWorkerBatchSizeInput").value || 100)),
    query: {
      schedule_times: scheduleTimes.length > 0 ? scheduleTimes : ["09:00", "14:00", "18:00"],
      schedule_jitter_minutes: Math.max(0, Math.min(120, Number(document.getElementById("scrollAndCollectWorkerJitterInput").value || 30))),
    },
  };
}

function collectAiMatchingWorkerPayload() {
  return {
    interval_seconds: Math.max(1, Number(document.getElementById("aiMatchingWorkerIntervalInput").value || 3600)),
    batch_size: Math.max(1, Number(document.getElementById("aiMatchingWorkerBatchSizeInput").value || 10)),
  };
}

async function saveScrollAndCollectWorkerConfig() {
  clearError();
  setButtonBusy("saveScrollAndCollectWorkerButton", true, "保存中");
  try {
    await fetchJson("/boss/workers/scroll_and_collect", {
      method: "PUT",
      body: JSON.stringify(collectScrollAndCollectWorkerPayload()),
    });
    await loadWorkers();
    showNotice("滚动采集 worker 配置已保存", 3000);
  } finally {
    setButtonBusy("saveScrollAndCollectWorkerButton", false);
  }
}

async function startScrollAndCollectWorker() {
  clearError();
  setButtonBusy("startScrollAndCollectWorkerButton", true, "启动中");
  try {
    await fetchJson("/boss/workers/scroll_and_collect", {
      method: "PUT",
      body: JSON.stringify(collectScrollAndCollectWorkerPayload()),
    });
    await fetchJson("/boss/workers/scroll_and_collect/start", { method: "POST" });
    await loadWorkers();
    showNotice("滚动采集 worker 已启动", 3000);
  } finally {
    setButtonBusy("startScrollAndCollectWorkerButton", false);
  }
}

async function stopScrollAndCollectWorker() {
  clearError();
  setButtonBusy("stopScrollAndCollectWorkerButton", true, "停止中");
  try {
    await fetchJson("/boss/workers/scroll_and_collect/stop", { method: "POST" });
    await loadWorkers();
    showNotice("滚动采集 worker 已停止", 3000);
  } finally {
    setButtonBusy("stopScrollAndCollectWorkerButton", false);
  }
}

async function releaseScrollAndCollectWorker() {
  clearError();
  setButtonBusy("releaseScrollAndCollectWorkerButton", true, "解除中");
  try {
    await fetchJson("/boss/workers/scroll_and_collect/release", { method: "POST" });
    await loadWorkers();
    showNotice("滚动采集 worker 已解除限制", 3000);
  } finally {
    setButtonBusy("releaseScrollAndCollectWorkerButton", false);
  }
}

async function executeScrollAndCollectWorker() {
  clearError();
  setButtonBusy("executeScrollAndCollectWorkerButton", true, "执行中");
  try {
    await fetchJson("/boss/workers/scroll_and_collect/execute", { method: "POST" });
    await loadWorkers();
    showNotice("滚动采集执行中", 5000);
  } finally {
    setButtonBusy("executeScrollAndCollectWorkerButton", false);
  }
}

async function saveAiMatchingWorkerConfig() {
  clearError();
  setButtonBusy("saveAiMatchingWorkerButton", true, "保存中");
  try {
    await fetchJson("/boss/workers/ai_matching", {
      method: "PUT",
      body: JSON.stringify(collectAiMatchingWorkerPayload()),
    });
    await loadWorkers();
    showNotice("AI匹配 worker 配置已保存", 3000);
  } finally {
    setButtonBusy("saveAiMatchingWorkerButton", false);
  }
}

async function startAiMatchingWorker() {
  clearError();
  setButtonBusy("startAiMatchingWorkerButton", true, "启动中");
  try {
    await fetchJson("/boss/workers/ai_matching", {
      method: "PUT",
      body: JSON.stringify(collectAiMatchingWorkerPayload()),
    });
    await fetchJson("/boss/workers/ai_matching/start", { method: "POST" });
    await loadWorkers();
    showNotice("AI匹配 worker 已启动", 3000);
  } finally {
    setButtonBusy("startAiMatchingWorkerButton", false);
  }
}

async function stopAiMatchingWorker() {
  clearError();
  setButtonBusy("stopAiMatchingWorkerButton", true, "停止中");
  try {
    await fetchJson("/boss/workers/ai_matching/stop", { method: "POST" });
    await loadWorkers();
    showNotice("AI匹配 worker 已停止", 3000);
  } finally {
    setButtonBusy("stopAiMatchingWorkerButton", false);
  }
}

async function releaseAiMatchingWorker() {
  clearError();
  setButtonBusy("releaseAiMatchingWorkerButton", true, "解除中");
  try {
    await fetchJson("/boss/workers/ai_matching/release", { method: "POST" });
    await loadWorkers();
    showNotice("AI匹配 worker 已解除限制", 3000);
  } finally {
    setButtonBusy("releaseAiMatchingWorkerButton", false);
  }
}

async function toggleAuth() {
  clearError();
  setButtonBusy("authActionButton", true, "处理中");
  try {
    const endpoint = state.auth?.logged_in ? "/boss/system/auth/logout" : "/boss/system/auth/login";
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
    endpoint: "/boss/tasks/search",
    payload: collectSearchFormPayload(),
  });
}

async function triggerScrollSearch() {
  showSearchUpdate("滚动采集已开始，正在等待页面滚动并收集职位，请稍候。", 0);
  return triggerSearchWithPayload({
    buttonId: "scrollSearchButton",
    busyText: "滚动采集中",
    endpoint: "/boss/tasks/search/scroll",
    payload: collectScrollSearchPayload(),
    onSuccess: (rows) => {
      showSearchUpdate(`滚动采集完成，当前展示 ${rows.length} 条记录。`);
    },
  });
}

async function triggerDetailClick() {
  showSearchUpdate("点击采集详情已开始，正在逐一点击职位并收集详情，请稍候。", 0);
  clearError();
  setButtonBusy("detailClickButton", true, "采集中");
  try {
    const result = await fetchJson("/boss/tasks/search/detail-click", {
      method: "POST",
      body: JSON.stringify({ query_override: {} }),
    });
    const [rows] = await Promise.all([
      loadCurrentSearchResults(),
      loadJobs(),
      loadTasks(),
      loadSummaryCards(),
      fetchJson("/boss/tasks?limit=5").then(renderDashboardTasks),
    ]);
    showSearchUpdate(`点击采集详情完成，当前展示 ${rows.length} 条记录。`);
    showNotice(`已触发点击采集详情任务 ${result.task_id}`, 5000);
  } finally {
    setButtonBusy("detailClickButton", false);
  }
}

async function triggerScrollAndDetail() {
  showSearchUpdate("滚动+详情采集已开始，正在滚动页面并逐一点击职位收集详情，请稍候。", 0);
  clearError();
  setButtonBusy("scrollAndDetailButton", true, "采集中");
  try {
    const result = await fetchJson("/boss/tasks/search/scroll-and-detail", {
      method: "POST",
      body: JSON.stringify({ query_override: {} }),
    });
    const [rows] = await Promise.all([
      loadCurrentSearchResults(),
      loadJobs(),
      loadTasks(),
      loadSummaryCards(),
      fetchJson("/boss/tasks?limit=5").then(renderDashboardTasks),
    ]);
    showSearchUpdate(`滚动+详情采集完成，当前展示 ${rows.length} 条记录。`);
    showNotice(`已触发滚动+详情采集任务 ${result.task_id}`, 5000);
  } finally {
    setButtonBusy("scrollAndDetailButton", false);
  }
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
    endpoint: "/boss/tasks/search",
    payload,
    onSuccess: (rows) => {
      setSearchPageValue(nextPage);
      showSearchUpdate(`第 ${nextPage} 页搜索完成，搜索结果已更新，当前展示 ${rows.length} 条记录。`);
    },
  });
}

async function triggerSearchWithPayload({ buttonId, busyText, endpoint, payload, onSuccess = null }) {
  clearError();
  setButtonBusy(buttonId, true, busyText);
  try {
    const result = await fetchJson(endpoint, {
      method: "POST",
      body: JSON.stringify({ query_override: payload }),
    });
    const [rows] = await Promise.all([
      loadCurrentSearchResults(),
      loadJobs(),
      loadTasks(),
      loadSummaryCards(),
      fetchJson("/boss/tasks?limit=5").then(renderDashboardTasks),
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
    const result = await fetchJson("/boss/tasks/greet", {
      method: "POST",
      body: JSON.stringify({ limit: 5 }),
    });
    await Promise.all([loadJobs(), loadTasks(), loadSummaryCards(), fetchJson("/boss/tasks?limit=5").then(renderDashboardTasks)]);
    showNotice(`已触发打招呼任务 ${result.task_id}`);
  } finally {
    setButtonBusy("greetButton", false);
  }
}

async function syncFriends() {
  clearError();
  setButtonBusy("syncConversationsButton", true, "同步中");
  try {
    const result = await fetchJson("/boss/friends/sync", { method: "POST" });
    await Promise.all([loadFriends(), loadSummaryCards()]);
    showNotice(`已同步 ${result.count} 条会话`, 5000);
  } finally {
    setButtonBusy("syncConversationsButton", false);
  }
}

async function clearData() {
  const confirmed = window.confirm("确认清除目标、职位、任务、沟通和聊天等业务数据？此操作不可恢复。");
  if (!confirmed) {
    return;
  }

  clearError();
  setButtonBusy("clearDataButton", true, "清除中");
  try {
    const result = await fetchJson("/web/system/data/clear", { method: "POST" });
    state.jobs = [];
    await Promise.all([
      loadSummaryCards(),
      fetchJson("/boss/tasks?limit=5").then(renderDashboardTasks),
      state.activeView === "jobs" ? loadJobs() : Promise.resolve(),
      state.activeView === "tasks" ? loadTasks() : Promise.resolve(),
      state.activeView === "conversations" ? loadFriends() : Promise.resolve(),
      state.activeView === "search" ? loadCurrentSearchResults() : Promise.resolve(),
    ]);
    showNotice(`已清除 ${result.total_deleted} 条数据`, 5000);
  } finally {
    setButtonBusy("clearDataButton", false);
  }
}

async function evaluateSingleJob(sourceJobId) {
  clearError();
  try {
    const result = await fetchJson(`/boss/jobs/${encodeURIComponent(sourceJobId)}/ai/evaluate`, { method: "POST" });
    showNotice(`AI评估完成: ${result.match ? "匹配" : "不匹配"} (${result.score}分)`, 5000);
  } catch (error) {
    showError(error.message);
  } finally {
    await loadJobs();
  }
}

async function triggerAiEvaluate() {
  clearError();
  setButtonBusy("aiEvaluateButton", true, "评估中");
  try {
    const result = await fetchJson("/boss/jobs/ai/evaluate", { method: "POST" });
    showNotice(`已触发AI评估任务 ${result.task_id}`, 5000);
  } finally {
    setButtonBusy("aiEvaluateButton", false);
  }
}

async function clearAiMarks() {
  const confirmed = window.confirm("确认清除所有AI评分和匹配标记？此操作不可恢复。");
  if (!confirmed) return;
  clearError();
  setButtonBusy("aiClearMarksButton", true, "清除中");
  try {
    const result = await fetchJson("/boss/jobs/ai/clear", { method: "POST" });
    await loadJobs();
    showNotice(`已清除 ${result.cleared_count} 条AI标记`, 5000);
  } finally {
    setButtonBusy("aiClearMarksButton", false);
  }
}

function renderStatisticsCounts(containerId, stats) {
  const container = document.getElementById(containerId);
  const items = [
    { label: "AI 匹配", value: stats.matched, className: "status-ok" },
    { label: "AI 不匹配", value: stats.unmatched, className: "status-error" },
    { label: "未分析", value: stats.unanalyzed, className: "status-warn" },
    { label: "合计", value: stats.total, className: "" },
  ];
  container.innerHTML = items
    .map(
      (item) =>
        `<div><span>${escapeHtml(item.label)}</span> <span class="${item.className ? `status-badge ${item.className}` : ""}">${item.value}</span></div>`
    )
    .join("");
}

async function executeStatistics() {
  clearError();
  setButtonBusy("executeStatisticsButton", true, "统计中");
  try {
    const stats = await fetchJson("/web/statistics/today/send", { method: "POST" });
    renderStatisticsCounts("statsUpdatedToday", stats.updated_today);
    renderStatisticsCounts("statsCreatedToday", stats.created_today);
    showNotice("统计已发送到飞书", 5000);
  } finally {
    setButtonBusy("executeStatisticsButton", false);
  }
}

// ── Profiles view ────────────────────────────────────────────────

let profilesData = {};
let activeProfileName = "resume";

function renderMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/^### (.+)$/gm, "<h4>$1</h4>");
  html = html.replace(/^## (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^# (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");
  html = html.replace(/^\d+\. (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, function(m) {
    if (m.indexOf("<ul>") === -1) return "<ol>" + m + "</ol>";
    return m;
  });
  html = html.replace(/\n\n/g, "</p><p>");
  html = html.replace(/\n/g, "<br>");
  html = "<p>" + html + "</p>";
  html = html.replace(/<p>\s*<\/p>/g, "");
  html = html.replace(/<\/p><br>/g, "</p>");
  html = html.replace(/<br><p>/g, "<p>");
  return html;
}

function updateProfilePreview() {
  const input = document.getElementById("profileEditorInput");
  const preview = document.getElementById("profilePreview");
  if (input && preview) {
    preview.innerHTML = renderMarkdown(input.value);
  }
}

function switchProfileTab(name) {
  activeProfileName = name;
  document.querySelectorAll(".profile-tab").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.profile === name);
  });
  const input = document.getElementById("profileEditorInput");
  if (input) {
    input.value = profilesData[name] || "";
    updateProfilePreview();
  }
}

async function loadProfiles() {
  try {
    const items = await fetchJson("/web/profiles");
    profilesData = {};
    for (const item of items) {
      profilesData[item.name] = item.content;
    }
    switchProfileTab(activeProfileName);
  } catch (error) {
    showError(error.message);
  }
}

async function saveProfile() {
  clearError();
  setButtonBusy("saveProfileButton", true, "保存中");
  try {
    const content = document.getElementById("profileEditorInput").value;
    await fetchJson(`/web/profiles/${encodeURIComponent(activeProfileName)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    });
    profilesData[activeProfileName] = content;
    document.getElementById("profileStatus").textContent = "已保存";
    setTimeout(() => {
      const el = document.getElementById("profileStatus");
      if (el) el.textContent = "";
    }, 3000);
  } catch (error) {
    showError(error.message);
  } finally {
    setButtonBusy("saveProfileButton", false);
  }
}

async function resetProfile() {
  if (!confirm("确认重置？将从示例文件重新加载当前档案内容。")) return;
  clearError();
  setButtonBusy("resetProfileButton", true, "重置中");
  try {
    const result = await fetchJson(`/web/profiles/${encodeURIComponent(activeProfileName)}/reset`, {
      method: "POST",
    });
    profilesData[activeProfileName] = result.content;
    document.getElementById("profileEditorInput").value = result.content;
    updateProfilePreview();
    document.getElementById("profileStatus").textContent = "已重置";
    setTimeout(() => {
      const el = document.getElementById("profileStatus");
      if (el) el.textContent = "";
    }, 3000);
  } catch (error) {
    showError(error.message);
  } finally {
    setButtonBusy("resetProfileButton", false);
  }
}

// ── Agent view ──────────────────────────────────────────────────

let agentEventSource = null;
let agentSteps = [];
let agentChats = [];

function saveAgentHistory() {
  try {
    const storage = getSafeStorage();
    if (!storage) return;
    storage.setItem(AGENT_STEPS_STORAGE_KEY, JSON.stringify(agentSteps.slice(-MAX_AGENT_STEPS)));
    storage.setItem(AGENT_CHAT_STORAGE_KEY, JSON.stringify(agentChats.slice(-200)));
  } catch {
    // ignore storage errors
  }
}

function loadAgentHistory() {
  try {
    const storage = getSafeStorage();
    if (!storage) return { steps: [], chats: [] };
    const stepsRaw = storage.getItem(AGENT_STEPS_STORAGE_KEY);
    const chatsRaw = storage.getItem(AGENT_CHAT_STORAGE_KEY);
    return {
      steps: stepsRaw ? JSON.parse(stepsRaw) : [],
      chats: chatsRaw ? JSON.parse(chatsRaw) : [],
    };
  } catch {
    return { steps: [], chats: [] };
  }
}

function initAgentView() {
  if (agentEventSource) {
    agentEventSource.close();
    agentEventSource = null;
  }
  const history = loadAgentHistory();
  agentSteps = history.steps;
  agentChats = history.chats;
  renderAgentTimeline();
  agentEventSource = new EventSource("/web/agent/events");

  agentEventSource.addEventListener("step_start", (e) => {
    const data = JSON.parse(e.data);
    const stepId = data.step + "_" + Date.now();
    const step = {
      id: stepId,
      step: data.step,
      title: data.text || data.step,
      status: "active",
      events: [],
      startTime: data.ts || new Date().toISOString(),
    };
    agentSteps.push(step);
    renderAgentTimeline();
    saveAgentHistory();
  });

  agentEventSource.addEventListener("step_end", (e) => {
    const data = JSON.parse(e.data);
    const active = agentSteps.filter((s) => s.step === data.step && s.status === "active");
    if (active.length > 0) {
      active[active.length - 1].status = "done";
      active[active.length - 1].title = data.text || active[active.length - 1].title;
      renderAgentTimeline();
      saveAgentHistory();
      setTimeout(() => collapseCompletedSteps(), 3000);
    }
  });

  agentEventSource.addEventListener("tool_call", (e) => {
    const data = JSON.parse(e.data);
    appendToActiveStep(data.step || "", {
      icon: "🛠",
      text: `${data.tool}\n输入: ${data.input}\n输出: ${data.output}`,
    });
  });

  agentEventSource.addEventListener("reasoning", (e) => {
    const data = JSON.parse(e.data);
    appendToActiveStep(data.step || "", {
      icon: "💭",
      text: data.text,
      reasoning: true,
    });
  });

  agentEventSource.addEventListener("chat", (e) => {
    const data = JSON.parse(e.data);
    appendChatMessage(data.source, data.text, data.ts);
  });

  agentEventSource.addEventListener("error", (e) => {
    const data = JSON.parse(e.data);
    appendToActiveStep(data.step || "", {
      icon: "❌",
      text: data.text,
      error: true,
    });
  });

  agentEventSource.addEventListener("error", () => {
    setTimeout(() => {
      if (agentEventSource && agentEventSource.readyState === EventSource.CLOSED) {
        initAgentView();
      }
    }, 3000);
  });
}

function appendToActiveStep(stepName, eventData) {
  const candidates = agentSteps.filter((s) => s.step === stepName && s.status === "active");
  const target = candidates.length > 0 ? candidates[candidates.length - 1] : agentSteps[agentSteps.length - 1];
  if (!target) return;
  target.events.push(eventData);
  renderAgentTimeline();
  saveAgentHistory();
}

function appendChatMessage(source, text, ts) {
  agentChats.push({ source, text, ts: ts || new Date().toISOString() });
  if (agentChats.length > 200) agentChats.shift();
  saveAgentHistory();
  renderAgentTimeline();
}

function renderAgentTimeline() {
  renderAgentSteps();
  renderAgentChats();
}

function renderAgentSteps() {
  const container = document.getElementById("agentStepsContent");
  if (!container) return;
  container.innerHTML = "";

  for (const step of agentSteps) {
    const el = document.createElement("div");
    el.className = "agent-step";
    el.dataset.stepId = step.id;

    const isActive = step.status === "active";
    const isError = step.status === "error";
    const statusClass = isActive ? "active" : isError ? "error" : "done";
    const statusText = isActive ? "执行中" : isError ? "失败" : "完成";
    const toggleIcon = isActive ? "▼" : "▶";

    const timeStr = step.startTime ? formatTime(step.startTime) : "";

    el.innerHTML = `<div class="agent-step-header" onclick="toggleAgentStep(this)">
      <span class="agent-step-toggle">${toggleIcon}</span>
      <span class="agent-step-title">${escapeHtml(step.title)}</span>
      <span class="agent-step-status ${statusClass}">${statusText}</span>
      ${timeStr ? `<span class="agent-step-time">${escapeHtml(timeStr)}</span>` : ""}
    </div>
    <div class="agent-step-body" ${isActive ? "" : "hidden"}>${
      step.events.map((ev) =>
        `<div class="agent-event-row${ev.reasoning ? " agent-reasoning" : ""}">
          <span class="agent-event-icon">${ev.icon || ""}</span>
          <span class="agent-event-text">${escapeHtml(ev.text)}</span>
        </div>`
      ).join("")
    }</div>`;

    container.appendChild(el);
  }
  container.scrollTop = container.scrollHeight;
}

function renderAgentChats() {
  const container = document.getElementById("agentChatsContent");
  if (!container) return;

  container.innerHTML = "";
  for (const chat of agentChats) {
    const source = chat.source === "user" ? "user" : chat.source === "agent" ? "agent" : "feishu";
    const bubble = document.createElement("div");
    bubble.className = `agent-chat-bubble ${source}`;
    const label = source === "user" ? "你" : source === "agent" ? "Agent" : "飞书";
    const timeStr = chat.ts ? formatTime(chat.ts) : "";
    bubble.innerHTML = `<div class="bubble-content">${source !== "user" ? `<div class="bubble-label">${escapeHtml(label)}</div>` : ""}${escapeHtml(chat.text)}</div>${timeStr ? `<div class="bubble-time">${escapeHtml(timeStr)}</div>` : ""}`;
    container.appendChild(bubble);
  }
  container.scrollTop = container.scrollHeight;
}

function toggleAgentStep(header) {
  const body = header.nextElementSibling;
  const toggle = header.querySelector(".agent-step-toggle");
  if (body) {
    body.hidden = !body.hidden;
    toggle.textContent = body.hidden ? "▶" : "▼";
  }
}

function collapseCompletedSteps() {
  for (const step of agentSteps) {
    if (step.status === "done") {
      const el = document.querySelector(`.agent-step[data-step-id="${step.id}"] .agent-step-body`);
      const toggle = document.querySelector(`.agent-step[data-step-id="${step.id}"] .agent-step-toggle`);
      if (el && !el.hidden) {
        el.hidden = true;
        if (toggle) toggle.textContent = "▶";
      }
    }
  }
}

function collectAgentWorkerPayload() {
  return {
    query: {
      schedule_times: (document.getElementById("agentScheduleTimes")?.value || "09:00, 14:00, 18:00")
        .split(",").map((s) => s.trim()).filter(Boolean),
      schedule_jitter_minutes: parseInt(document.getElementById("agentScheduleJitterMinutes")?.value || "60", 10) || 60,
      greet_limit: parseInt(document.getElementById("agentGreetLimit")?.value || "10", 10) || 10,
    },
  };
}

async function saveAgentWorkerConfig() {
  clearError();
  setButtonBusy("saveAgentWorkerButton", true, "保存中");
  try {
    await fetchJson("/boss/workers/agent", {
      method: "PUT",
      body: JSON.stringify(collectAgentWorkerPayload()),
    });
    await loadWorkers();
    showNotice("Agent 配置已保存", 3000);
  } finally {
    setButtonBusy("saveAgentWorkerButton", false);
  }
}

async function startAgentWorker() {
  clearError();
  setButtonBusy("startAgentWorkerButton", true, "启动中");
  try {
    await fetchJson("/boss/workers/agent", {
      method: "PUT",
      body: JSON.stringify(collectAgentWorkerPayload()),
    });
    await fetchJson("/boss/workers/agent/start", { method: "POST" });
    await loadWorkers();
    showNotice("Agent 已启动", 3000);
  } finally {
    setButtonBusy("startAgentWorkerButton", false);
  }
}

async function stopAgentWorker() {
  clearError();
  setButtonBusy("stopAgentWorkerButton", true, "停止中");
  try {
    await fetchJson("/boss/workers/agent/stop", { method: "POST" });
    await loadWorkers();
    showNotice("Agent 已停止", 3000);
  } finally {
    setButtonBusy("stopAgentWorkerButton", false);
  }
}

async function releaseAgentWorker() {
  clearError();
  setButtonBusy("releaseAgentWorkerButton", true, "解除中");
  try {
    await fetchJson("/boss/workers/agent/release", { method: "POST" });
    await loadWorkers();
    showNotice("Agent 已解除限制", 3000);
  } finally {
    setButtonBusy("releaseAgentWorkerButton", false);
  }
}

async function executeAgentWorker() {
  clearError();
  setButtonBusy("executeAgentWorkerButton", true, "执行中");
  try {
    await fetchJson("/boss/workers/agent/execute", { method: "POST" });
    await loadWorkers();
    showNotice("Agent 工作流执行中", 5000);
  } finally {
    setButtonBusy("executeAgentWorkerButton", false);
  }
}

async function sendAgentChat() {
  const input = document.getElementById("agentChatInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  autoResizeAgentInput();
  try {
    await fetchJson("/web/agent/chat", { method: "POST", body: JSON.stringify({ text }) });
  } catch (error) {
    showError(error.message);
  }
}

function autoResizeAgentInput() {
  const input = document.getElementById("agentChatInput");
  if (!input) return;
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + "px";
}

async function loadView(viewId, params = {}) {
  clearError();
  switch (viewId) {
    case "dashboard":
      await loadDashboardView();
      break;
    case "search":
      clearSearchUpdate();
      await Promise.all([loadSearchOptions(), loadCurrentSearchResults(), loadWorkers()]);
      break;
    case "jobs":
      await Promise.all([loadJobs(), loadWorkers()]);
      break;
    case "tasks":
      await loadTasks();
      break;
    case "conversations":
      await loadFriends();
      break;
    case "doctor":
      await Promise.all([loadAuthStatus(), loadDoctor()]);
      break;
    case "logs":
      await loadLogs();
      break;
    case "statistics":
      break;
    case "profiles":
      await loadProfiles();
      break;
    case "agent":
      await loadWorkers();
      initAgentView();
      break;
    case "job-detail":
      await loadJobDetailPage(params.sourceJobId);
      break;
    default:
      await loadDashboardView();
  }
}

async function refreshCurrentView() {
  clearNotice();
  if (state.activeView === "job-detail") {
    await loadView(state.activeView, { sourceJobId: state.jobDetailPageSourceJobId });
  } else {
    await loadView(state.activeView);
  }
}

function bindEvents() {
  document.querySelectorAll("[data-view-target]").forEach((button) => {
    button.addEventListener("click", () => navigateTo(button.dataset.viewTarget));
  });

  document.addEventListener("click", (event) => {
    const copyButton = event.target.closest("[data-copy-link]");
    if (copyButton) {
      event.preventDefault();
      copyJobLink(copyButton.dataset.copyLink, copyButton);
      return;
    }

    const closeButton = event.target.closest("[data-close-job-detail]");
    if (closeButton) {
      event.preventDefault();
      closeJobDetailDrawer();
    }

    const chatButton = event.target.closest("[data-chat-history]");
    if (chatButton) {
      event.preventDefault();
      const parts = chatButton.dataset.chatHistory.split("|");
      openFriendChat(parts[0], decodeURIComponent(parts[1] || "")).catch(
        (error) => showError(error.message || "聊天历史获取失败")
      );
      return;
    }

    const jobDetailPageButton = event.target.closest("[data-job-detail-page]");
    if (jobDetailPageButton) {
      event.preventDefault();
      const parts = jobDetailPageButton.dataset.jobDetailPage.split("|");
      state.jobDetailPageName = decodeURIComponent(parts[1] || "");
      state.jobDetailPageSourceFriendId = parts[2] || "";
      state.jobDetailPageSecurityId = parts[3] || "";
      state.jobDetailPageForceContact = true;
      navigateTo("job-detail", { sourceJobId: parts[0] });
      return;
    }

    const closeChatButton = event.target.closest("[data-close-chat-history]");
    if (closeChatButton) {
      event.preventDefault();
      closeChatHistoryDrawer();
    }

    const aiEvaluateButton = event.target.closest("[data-ai-evaluate]");
    if (aiEvaluateButton) {
      event.preventDefault();
      const sourceJobId = aiEvaluateButton.dataset.aiEvaluate;
      evaluateSingleJob(sourceJobId).catch((error) => showError(error.message));
      return;
    }
  });

  window.addEventListener("hashchange", () => {
    const { view, params } = getViewFromHash();
    state.activeView = view;
    setActiveView(view);
    loadView(view, params).catch((error) => showError(error.message || "页面加载失败"));
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
    .getElementById("clearDataButton")
    .addEventListener("click", () => clearData().catch((error) => showError(error.message)));
  document
    .getElementById("aiEvaluateButton")
    .addEventListener("click", () => triggerAiEvaluate().catch((error) => showError(error.message)));
  document
    .getElementById("aiClearMarksButton")
    .addEventListener("click", () => clearAiMarks().catch((error) => showError(error.message)));
  document
    .getElementById("searchButton")
    .addEventListener("click", () => triggerSearch().catch((error) => showError(error.message)));
  document
    .getElementById("scrollSearchButton")
    .addEventListener("click", () => triggerScrollSearch().catch((error) => showError(error.message)));
  document
    .getElementById("detailClickButton")
    .addEventListener("click", () => triggerDetailClick().catch((error) => showError(error.message)));
  document
    .getElementById("scrollAndDetailButton")
    .addEventListener("click", () => triggerScrollAndDetail().catch((error) => showError(error.message)));
  document
    .getElementById("nextPageSearchButton")
    .addEventListener("click", () => triggerNextPageSearch().catch((error) => showError(error.message)));
  document
    .getElementById("refreshSearchButton")
    .addEventListener("click", () => loadCurrentSearchResults().catch((error) => showError(error.message)));
  document
    .getElementById("saveScrollAndCollectWorkerButton")
    .addEventListener("click", () => saveScrollAndCollectWorkerConfig().catch((error) => showError(error.message)));
  document
    .getElementById("startScrollAndCollectWorkerButton")
    .addEventListener("click", () => startScrollAndCollectWorker().catch((error) => showError(error.message)));
  document
    .getElementById("stopScrollAndCollectWorkerButton")
    .addEventListener("click", () => stopScrollAndCollectWorker().catch((error) => showError(error.message)));
  document
    .getElementById("releaseScrollAndCollectWorkerButton")
    .addEventListener("click", () => releaseScrollAndCollectWorker().catch((error) => showError(error.message)));
  document
    .getElementById("executeScrollAndCollectWorkerButton")
    .addEventListener("click", () => executeScrollAndCollectWorker().catch((error) => showError(error.message)));
  document
    .getElementById("saveAiMatchingWorkerButton")
    .addEventListener("click", () => saveAiMatchingWorkerConfig().catch((error) => showError(error.message)));
  document
    .getElementById("startAiMatchingWorkerButton")
    .addEventListener("click", () => startAiMatchingWorker().catch((error) => showError(error.message)));
  document
    .getElementById("stopAiMatchingWorkerButton")
    .addEventListener("click", () => stopAiMatchingWorker().catch((error) => showError(error.message)));
  document
    .getElementById("releaseAiMatchingWorkerButton")
    .addEventListener("click", () => releaseAiMatchingWorker().catch((error) => showError(error.message)));
  document
    .getElementById("refreshJobsButton")
    .addEventListener("click", () => loadJobs().catch((error) => showError(error.message)));

  document
    .getElementById("jobsPrevPageButton")
    .addEventListener("click", () => goToJobsPage(state.jobsPage - 1).catch((error) => showError(error.message)));
  document
    .getElementById("jobsNextPageButton")
    .addEventListener("click", () => goToJobsPage(state.jobsPage + 1).catch((error) => showError(error.message)));
  document
    .getElementById("jobsLimitSelect")
    .addEventListener("change", (event) => changeJobsLimit(event.target.value).catch((error) => showError(error.message)));

  ["jobsSortSelect", "jobsAiMatchFilter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", renderJobsTable);
  });
  ["jobsGreetedFilter", "jobsCreatedTodayFilter", "jobsUpdatedTodayFilter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      updateJobsPageParams(1, state.jobsLimit);
      loadJobs().catch((error) => showError(error.message));
    });
  });
  ["jobsCityFilter", "jobsKeywordFilter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", renderJobsTable);
  });
  document
    .getElementById("greetButton")
    .addEventListener("click", () => triggerGreeting().catch((error) => showError(error.message)));
  document
    .getElementById("syncConversationsButton")
    .addEventListener("click", () => syncFriends().catch((error) => showError(error.message)));
  document
    .getElementById("refreshTasksButton")
    .addEventListener("click", () => loadTasks().catch((error) => showError(error.message)));
  document
    .getElementById("refreshConversationsButton")
    .addEventListener("click", () => loadFriends().catch((error) => showError(error.message)));
  document
    .getElementById("refreshLogsButton")
    .addEventListener("click", () => loadLogs().catch((error) => showError(error.message)));
  document
    .getElementById("executeStatisticsButton")
    .addEventListener("click", () => executeStatistics().catch((error) => showError(error.message)));
  document.querySelectorAll(".profile-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchProfileTab(btn.dataset.profile));
  });
  document.getElementById("profileEditorInput").addEventListener("input", updateProfilePreview);
  document
    .getElementById("saveProfileButton")
    .addEventListener("click", () => saveProfile().catch((error) => showError(error.message)));
  document
    .getElementById("resetProfileButton")
    .addEventListener("click", () => resetProfile().catch((error) => showError(error.message)));
  document
    .getElementById("saveAgentWorkerButton")
    .addEventListener("click", () => saveAgentWorkerConfig().catch((error) => showError(error.message)));
  document
    .getElementById("startAgentWorkerButton")
    .addEventListener("click", () => startAgentWorker().catch((error) => showError(error.message)));
  document
    .getElementById("stopAgentWorkerButton")
    .addEventListener("click", () => stopAgentWorker().catch((error) => showError(error.message)));
  document
    .getElementById("releaseAgentWorkerButton")
    .addEventListener("click", () => releaseAgentWorker().catch((error) => showError(error.message)));
  document
    .getElementById("executeAgentWorkerButton")
    .addEventListener("click", () => executeAgentWorker().catch((error) => showError(error.message)));
  document
    .getElementById("agentChatSendButton")
    .addEventListener("click", () => sendAgentChat().catch((error) => showError(error.message)));
  document.getElementById("agentChatInput").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      sendAgentChat().catch((error) => showError(error.message));
    }
  });
  document.getElementById("agentChatInput").addEventListener("input", autoResizeAgentInput);
  document
    .getElementById("syncConversationsFromChatButton")
    .addEventListener("click", () => syncFriends().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailSyncChatButton")
    .addEventListener("click", () => syncChatHistoryForJobDetail().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailSyncDetailButton")
    .addEventListener("click", () => syncJobDetailPageDetail().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailGreetButton")
    .addEventListener("click", () => greetCurrentJobDetail().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailSendMessageButton")
    .addEventListener("click", () => sendMessageForJobDetail().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailAiMessageButton")
    .addEventListener("click", () => generateAiMessageForJobDetail().catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailDrawerEvalButton")
    .addEventListener("click", () => evaluateJobDetail("jobDetailDrawerEvalButton").catch((error) => showError(error.message)));
  document
    .getElementById("jobDetailPageEvalButton")
    .addEventListener("click", () => evaluateJobDetail("jobDetailPageEvalButton").catch((error) => showError(error.message)));
  document.getElementById("jobDetailMessageInput").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      sendMessageForJobDetail().catch((error) => showError(error.message));
    }
  });
  document.getElementById("jobDetailMessageInput").addEventListener("input", () => {
    clearAiMessageInfo();
  });
  document.getElementById("jobDetailDrawer").addEventListener("click", (event) => {
    if (event.target?.dataset?.close === "true") {
      closeJobDetailDrawer();
    }
  });
  document.getElementById("chatHistoryDrawer").addEventListener("click", (event) => {
    if (event.target?.dataset?.close === "true") {
      closeChatHistoryDrawer();
    }
  });
}

bindSearchFormPersistence();
bindEvents();
const initialRoute = getViewFromHash();
setActiveView(initialRoute.view);

Promise.all([loadAuthStatus(), loadView(initialRoute.view, initialRoute.params)])
  .then(() => clearNotice())
  .catch((error) => showError(error.message || "页面初始化失败"));
