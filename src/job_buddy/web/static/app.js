async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`${response.status} ${response.statusText}${message ? ` - ${message}` : ""}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

let authState = null;
let authBusy = false;
let searchOptions = null;
const SEARCH_FORM_STORAGE_KEY = "job_buddy.search_form";
let searchFormCacheApplied = false;

function renderTable(containerId, columns, rows) {
  const container = document.getElementById(containerId);
  if (!rows.length) {
    container.innerHTML = `<div class="empty">暂无数据。</div>`;
    return;
  }

  const header = columns.map((column) => `<th>${column.label}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((column) => `<td>${column.render(row)}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  container.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

async function loadSummary() {
  const summary = await fetchJson("/api/dashboard");
  const labels = {
    targets: "目标岗位",
    jobs: "职位线索",
    tasks: "任务记录",
    conversations: "沟通记录",
  };
  const cards = Object.entries(summary)
    .map(([key, value]) => `<div class="card"><span>${labels[key] || key}</span><strong>${value}</strong></div>`)
    .join("");
  document.getElementById("summaryCards").innerHTML = cards;
}

function renderStatusBadge(status) {
  return `<span class="status-badge status-${status}">${status}</span>`;
}

function setButtonBusy(buttonId, busy) {
  const button = document.getElementById(buttonId);
  button.disabled = busy;
  button.classList.toggle("button-disabled", busy);
}

function showPageError(message) {
  const panel = document.getElementById("pageErrorPanel");
  const box = document.getElementById("pageErrorMessage");
  panel.hidden = false;
  box.innerHTML = `<div><strong>错误：</strong>${message}</div>`;
}

function clearPageError() {
  const panel = document.getElementById("pageErrorPanel");
  const box = document.getElementById("pageErrorMessage");
  panel.hidden = true;
  box.innerHTML = "";
}

function buildSelectOptions(selectId, values) {
  const select = document.getElementById(selectId);
  const options = ['<option value="">不限</option>']
    .concat(values.map((item) => `<option value="${item}">${item}</option>`))
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
  window.localStorage.setItem(SEARCH_FORM_STORAGE_KEY, JSON.stringify(readSearchFormState()));
}

function loadCachedSearchFormState() {
  try {
    const raw = window.localStorage.getItem(SEARCH_FORM_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function applyCachedSearchFormState() {
  if (searchFormCacheApplied) {
    return;
  }

  const cached = loadCachedSearchFormState();
  if (!cached) {
    searchFormCacheApplied = true;
    return;
  }

  const elements = getSearchFormElements();
  elements.keywords.value = cached.keywords || "";
  elements.welfare.value = cached.welfare || "";
  elements.page.value = cached.page || "1";

  const selectMappings = [
    [elements.city, cached.city],
    [elements.salary, cached.salary],
    [elements.experience, cached.experience],
    [elements.education, cached.education],
    [elements.industry, cached.industry],
    [elements.scale, cached.scale],
    [elements.stage, cached.stage],
    [elements.jobType, cached.job_type],
  ];

  selectMappings.forEach(([element, value]) => {
    if (!value) {
      element.value = "";
      return;
    }
    const hasOption = Array.from(element.options).some((option) => option.value === value);
    element.value = hasOption ? value : "";
  });
  searchFormCacheApplied = true;
}

function bindSearchFormPersistence() {
  const elements = Object.values(getSearchFormElements());
  elements.forEach((element) => {
    element.addEventListener("change", persistSearchFormState);
    if (element.tagName === "INPUT") {
      element.addEventListener("input", persistSearchFormState);
    }
  });
}

async function loadSearchOptions() {
  const options = await fetchJson("/api/system/search-options");
  searchOptions = options;
  buildSelectOptions("searchCitySelect", options.cities || []);
  buildSelectOptions("searchSalarySelect", options.salary_ranges || []);
  buildSelectOptions("searchExperienceSelect", options.experience_levels || []);
  buildSelectOptions("searchEducationSelect", options.education_levels || []);
  buildSelectOptions("searchIndustrySelect", options.industries || []);
  buildSelectOptions("searchScaleSelect", options.scales || []);
  buildSelectOptions("searchStageSelect", options.stages || []);
  buildSelectOptions("searchJobTypeSelect", options.job_types || []);
  applyCachedSearchFormState();
}

function renderAuthSummary(status) {
  authState = status;
  const button = document.getElementById("authActionButton");
  button.textContent = status.logged_in ? "退出登录" : "登录";

  document.getElementById("authSummary").innerHTML = [
    `<div><strong>状态：</strong>${status.logged_in ? renderStatusBadge("ok") : renderStatusBadge("warn")}</div>`,
    `<div><strong>用户名：</strong>${status.user_name || "-"}</div>`,
    `<div><strong>登录方式：</strong>${status.login_method || "-"}</div>`,
    `<div><strong>浏览器：</strong>${status.browser || "-"}</div>`,
    `<div><strong>最近登录：</strong>${status.last_login_at ? new Date(status.last_login_at).toLocaleString() : "-"}</div>`,
    `<div><strong>最近退出：</strong>${status.last_logout_at ? new Date(status.last_logout_at).toLocaleString() : "-"}</div>`,
    `<div><strong>提示：</strong>${status.message || "-"}</div>`,
    `<div><strong>错误：</strong>${status.last_error || "-"}</div>`,
  ].join("");
}

async function loadAuthStatus() {
  const status = await fetchJson("/api/system/auth");
  renderAuthSummary(status);
}

async function toggleAuth() {
  if (authBusy) {
    return;
  }

  authBusy = true;
  setButtonBusy("authActionButton", true);

  try {
    const endpoint = authState?.logged_in ? "/api/system/auth/logout" : "/api/system/auth/login";
    const status = await fetchJson(endpoint, { method: "POST" });
    renderAuthSummary(status);
    await loadDoctor();
  } finally {
    authBusy = false;
    setButtonBusy("authActionButton", false);
  }
}

async function loadDoctor() {
  const doctor = await fetchJson("/api/system/doctor");
  const summaryLines = [
    `<strong>诊断结果：</strong>${doctor.summary}`,
    `<strong>命令状态：</strong>${doctor.ok ? "成功" : "失败"}`,
    `<strong>退出码：</strong>${doctor.exit_code}`,
    `<strong>数据目录：</strong>${doctor.data_dir || "-"}`,
  ];

  if (doctor.stderr) {
    summaryLines.push(`<strong>标准错误：</strong><pre>${doctor.stderr}</pre>`);
  }
  if (doctor.error) {
    summaryLines.push(`<strong>错误信息：</strong>${doctor.error.code} - ${doctor.error.message}`);
  }

  document.getElementById("doctorSummary").innerHTML =
    `<div class="doctor-summary">${summaryLines.map((line) => `<div>${line}</div>`).join("")}</div>`;

  document.getElementById("doctorActions").innerHTML = doctor.next_actions?.length
    ? `<ul class="doctor-actions">${doctor.next_actions.map((item) => `<li>${item}</li>`).join("")}</ul>`
    : `<div class="empty">暂无下一步建议。</div>`;

  renderTable(
    "doctorChecks",
    [
      { label: "检查项", render: (row) => row.name },
      { label: "状态", render: (row) => renderStatusBadge(row.status) },
      { label: "详情", render: (row) => row.detail },
      { label: "建议", render: (row) => row.hint || "-" },
    ],
    doctor.checks || [],
  );
}

async function loadTargets() {
  const items = await fetchJson("/api/targets");
  renderTable(
    "targetsTable",
    [
      { label: "名称", render: (row) => row.name },
      { label: "关键词", render: (row) => row.keywords.join(", ") },
      { label: "城市", render: (row) => row.city || "-" },
      { label: "招呼语", render: (row) => row.greeting_template || "-" },
    ],
    items,
  );
}

async function loadJobs() {
  const items = await fetchJson("/api/jobs");
  renderTable(
    "jobsTable",
    [
      { label: "职位", render: (row) => row.title },
      { label: "公司", render: (row) => row.company },
      { label: "城市", render: (row) => row.city || "-" },
      { label: "薪资", render: (row) => row.salary || "-" },
      {
        label: "跳转",
        render: (row) => (row.job_url ? `<a href="${row.job_url}" target="_blank" rel="noreferrer">查看职位</a>` : "-"),
      },
      { label: "状态", render: (row) => `${row.match_status}${row.greeted ? " / 已打招呼" : ""}` },
    ],
    items,
  );
}

async function loadTasks() {
  const items = await fetchJson("/api/tasks");
  renderTable(
    "tasksTable",
    [
      { label: "类型", render: (row) => row.task_type },
      { label: "状态", render: (row) => row.status },
      { label: "结果摘要", render: (row) => JSON.stringify(row.result_summary || {}) },
      { label: "错误信息", render: (row) => row.error_message || "-" },
      { label: "更新时间", render: (row) => new Date(row.updated_at).toLocaleString() },
    ],
    items,
  );
}

async function loadConversations() {
  const items = await fetchJson("/api/conversations");
  renderTable(
    "conversationsTable",
    [
      { label: "职位", render: (row) => row.title },
      { label: "公司", render: (row) => row.company || "-" },
      { label: "最近消息", render: (row) => row.last_message || "-" },
      { label: "未读数", render: (row) => row.unread_count },
    ],
    items,
  );
}

async function refreshAll() {
  clearPageError();
  const results = await Promise.allSettled([
    loadSummary(),
    loadDoctor(),
    loadAuthStatus(),
    loadSearchOptions(),
    loadTargets(),
    loadJobs(),
    loadTasks(),
    loadConversations(),
  ]);

  const failed = results.find((item) => item.status === "rejected");
  if (failed) {
    showPageError(failed.reason?.message || "页面数据加载失败");
  }
}

async function createDemoTarget() {
  await fetchJson("/api/targets", {
    method: "POST",
    body: JSON.stringify({
      name: "Python Backend",
      keywords: ["Python", "FastAPI"],
      city: "上海",
      salary: "20-30K",
      greeting_template: "你好，我有 Python 后端开发经验，希望进一步了解这个岗位。",
    }),
  });
  await refreshAll();
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
    page: Number(document.getElementById("searchPageInput").value || 1),
  };

  return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== null && value !== ""));
}

async function triggerSearch() {
  clearPageError();
  try {
    await fetchJson("/api/tasks/search", {
      method: "POST",
      body: JSON.stringify({ query_override: collectSearchFormPayload() }),
    });
    await refreshAll();
  } catch (error) {
    showPageError(error.message || "触发采集失败");
    throw error;
  }
}

async function triggerGreeting() {
  await fetchJson("/api/tasks/greet", {
    method: "POST",
    body: JSON.stringify({ limit: 5 }),
  });
  await refreshAll();
}

async function syncConversations() {
  await fetchJson("/api/conversations/sync", {
    method: "POST",
  });
  await refreshAll();
}

document.getElementById("refreshButton").addEventListener("click", () => refreshAll().catch((error) => showPageError(error.message)));
document.getElementById("doctorButton").addEventListener("click", () => loadDoctor().catch((error) => showPageError(error.message)));
document.getElementById("authActionButton").addEventListener("click", () => toggleAuth().catch((error) => showPageError(error.message)));
document.getElementById("seedTargetButton").addEventListener("click", () => createDemoTarget().catch((error) => showPageError(error.message)));
document.getElementById("searchButton").addEventListener("click", () => triggerSearch().catch(() => {}));
document.getElementById("greetButton").addEventListener("click", () => triggerGreeting().catch((error) => showPageError(error.message)));
document.getElementById("syncConversationsButton").addEventListener("click", () => syncConversations().catch((error) => showPageError(error.message)));
bindSearchFormPersistence();

refreshAll().catch((error) => showPageError(error.message));
