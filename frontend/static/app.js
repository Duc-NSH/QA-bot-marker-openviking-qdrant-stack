// frontend/static/app.js
const API_BASE = "";  // same origin via Traefik, or set to "http://api.localhost"

const statusEl = document.getElementById("status");
const questionEl = document.getElementById("question");
const submitEl = document.getElementById("submit");
const formEl = document.getElementById("form");
const answerSection = document.getElementById("answer-section");
const answerEl = document.getElementById("answer");
const sourcesSection = document.getElementById("sources-section");
const sourcesSummary = document.getElementById("sources-summary");
const sourcesList = document.getElementById("sources-list");

// ── Health poll ──────────────────────────────────────────────────────────────
async function pollHealth() {
  try {
    const resp = await fetch(`${API_BASE}/health`);
    const data = await resp.json();
    if (data.status === "ready") {
      setStatus("ready", "sẵn sàng");
      questionEl.disabled = false;
      submitEl.disabled = false;
    } else {
      setStatus("indexing", "đang lập chỉ mục…");
      setTimeout(pollHealth, 3000);
    }
  } catch {
    setStatus("checking", "đang kết nối…");
    setTimeout(pollHealth, 3000);
  }
}

function setStatus(cls, label) {
  statusEl.className = `status ${cls}`;
  statusEl.textContent = label;
}

// ── Mini markdown renderer (bold + newlines only) ────────────────────────
function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br/>");
}

// ── Form submit ───────────────────────────────────────────────────────────────
formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionEl.value.trim();
  if (!question) return;

  submitEl.disabled = true;
  questionEl.disabled = true;
  answerEl.innerHTML = '<span class="thinking">Đang tìm kiếm tài liệu liên quan…</span>';
  answerSection.hidden = false;
  sourcesSection.hidden = true;
  sourcesList.innerHTML = "";
  firstToken = true;
  fullText = "";

  try {
    await streamQuery(question);
  } catch (err) {
    answerEl.innerHTML = `<em style="color:red">Lỗi: ${err.message}</em>`;
  } finally {
    submitEl.disabled = false;
    questionEl.disabled = false;
  }
});

let firstToken = true;
let fullText = "";

async function streamQuery(question) {
  const resp = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, limit: 5 }),
  });

  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    let eventType = "message";
    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        // SSE spec: strip exactly one leading space (field-value separator).
        const data = line.slice(5).replace(/^ /, "");
        handleEvent(eventType, data);
        eventType = "message";
      }
    }
  }
}

const STATUS_LABELS = {
  searching:  "Đang tìm kiếm tài liệu liên quan…",
  generating: "Đang tạo câu trả lời…",
};

function handleEvent(type, data) {
  if (type === "status") {
    if (firstToken) {
      const label = STATUS_LABELS[data] ?? data;
      answerEl.innerHTML = `<span class="thinking">${label}</span>`;
    }
  } else if (type === "token") {
    if (firstToken) {
      firstToken = false;
      fullText = "";
    }
    fullText += data;
    answerEl.innerHTML = renderMarkdown(fullText);
    answerEl.scrollIntoView({ block: "nearest" });
  } else if (type === "done") {
    try {
      const payload = JSON.parse(data);
      renderSources(payload.sources || []);
    } catch { /* ignore parse error */ }
  } else if (type === "error") {
    try {
      const payload = JSON.parse(data);
      answerEl.innerHTML += `<br/><em style="color:red">${payload.message}</em>`;
    } catch { /* ignore */ }
  }
}

function renderSources(sources) {
  if (!sources.length) return;
  sourcesSummary.textContent = `Nguồn tham khảo (${sources.length})`;
  sourcesList.innerHTML = "";
  sources.forEach((src) => {
    const score = src.score ?? 0;
    const color = score > 0.75 ? "var(--score-hi)" : score > 0.5 ? "#e65100" : "var(--score-lo)";
    const li = document.createElement("li");
    li.className = "source-item";
    const filename = (src.uri || "").split("/").pop();
    li.innerHTML = `
      <div class="source-meta">
        <span class="score-badge" style="background:${color}">${(score * 100).toFixed(0)}%</span>
        ${src.section_heading ? `<span class="source-section">${escHtml(src.section_heading)}</span>` : ""}
        ${src.page_number != null ? `<span class="source-page">trang ${src.page_number}</span>` : ""}
        ${filename ? `<span class="source-file">${escHtml(filename)}</span>` : ""}
      </div>
      <p class="source-text">${escHtml(src.text)}</p>
    `;
    li.querySelector(".source-text").addEventListener("click", (e) => {
      e.target.classList.toggle("expanded");
    });
    sourcesList.appendChild(li);
  });
  sourcesSection.hidden = false;
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

pollHealth();
