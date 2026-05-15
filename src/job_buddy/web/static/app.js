async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

let cdpState = null;
let cdpBusy = false;
let cdpPollHandle = null;

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

function renderCdpSummary(status) {
  const button = document.getElementById("cdpToggleButton");
  button.textContent = status.running ? "关闭浏览器" : "启动浏览器";

  document.getElementById("cdpSummary").innerHTML = [
    `<div><strong>状态：</strong>${status.running ? renderStatusBadge("ok") : renderStatusBadge("warn")}</div>`,
    `<div><strong>端口：</strong>${status.port}</div>`,
    `<div><strong>CDP 地址：</strong>${status.cdp_url}</div>`,
    `<div><strong>浏览器：</strong>${status.browser || "-"}</div>`,
    `<div><strong>WebSocket：</strong>${status.websocket_url || "-"}</div>`,
    `<div><strong>提示：</strong>${status.message || "-"}</div>`,
  ].join("");
}

async function loadCdpStatus() {
  const status = await fetchJson("/api/system/cdp");
  cdpState = status;
  renderCdpSummary(status);
}

async function toggleCdpBrowser() {
  if (cdpBusy) {
    return;
  }

  cdpBusy = true;
  setButtonBusy("cdpToggleButton", true);

  try {
    const endpoint = cdpState?.running ? "/api/system/cdp/stop" : "/api/system/cdp/start";
    const status = await fetchJson(endpoint, { method: "POST" });
    cdpState = status;
    renderCdpSummary(status);
    await loadDoctor();
  } finally {
    cdpBusy = false;
    setButtonBusy("cdpToggleButton", false);
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
  await Promise.all([loadSummary(), loadDoctor(), loadCdpStatus(), loadTargets(), loadJobs(), loadTasks(), loadConversations()]);
}

async function createDemoTarget() {
  await fetchJson("/api/targets", {
    method: "POST",
    body: JSON.stringify({
      name: "Python Backend",
      keywords: ["Python", "FastAPI"],
      city: "Shanghai",
      salary: "20-30K",
      greeting_template: "你好，我有 Python 后端开发经验，希望进一步了解这个岗位。",
    }),
  });
  await refreshAll();
}

async function triggerSearch() {
  const targets = await fetchJson("/api/targets");
  const firstTarget = targets[0];
  await fetchJson("/api/tasks/search", {
    method: "POST",
    body: JSON.stringify(
      firstTarget
        ? { target_profile_id: firstTarget.id }
        : { query_override: { keywords: ["Python"], city: "Shanghai" } },
    ),
  });
  await refreshAll();
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

document.getElementById("refreshButton").addEventListener("click", () => refreshAll().catch(console.error));
document.getElementById("doctorButton").addEventListener("click", () => loadDoctor().catch(console.error));
document.getElementById("cdpToggleButton").addEventListener("click", () => toggleCdpBrowser().catch(console.error));
document.getElementById("seedTargetButton").addEventListener("click", () => createDemoTarget().catch(console.error));
document.getElementById("searchButton").addEventListener("click", () => triggerSearch().catch(console.error));
document.getElementById("greetButton").addEventListener("click", () => triggerGreeting().catch(console.error));
document.getElementById("syncConversationsButton").addEventListener("click", () => syncConversations().catch(console.error));

cdpPollHandle = window.setInterval(() => {
  loadCdpStatus().catch(console.error);
}, 1000);

refreshAll().catch(console.error);
