const $ = (s) => document.querySelector(s);
let conversationId = null;

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) k === "class" ? (e.className = v) : e.setAttribute(k, v);
  for (const c of children) if (c != null) e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return e;
}

function renderMarkdown(text) {
  const div = document.createElement("div");
  if (window.marked && window.DOMPurify) div.innerHTML = DOMPurify.sanitize(marked.parse(text || ""));
  else div.textContent = text || "";
  return div;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}

// ---------- config ----------
async function loadConfig() {
  const c = await api("/api/config");
  for (const m of c.di_models) $("#di_model").append(el("option", { value: m }, m));
  for (const m of c.cu_analyzers) $("#cu_analyzer").append(el("option", { value: m }, m));
  $("#agent-info").textContent = `${c.agent_name} · ${c.chat_deployment} · index: ${c.search_index}`;
}

// ---------- ingest ----------
const fileInput = $("#file");
const drop = $("#drop");
fileInput.addEventListener("change", () => ($("#file-label").textContent = fileInput.files[0]?.name || ""));
["dragover", "dragenter"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  fileInput.files = e.dataTransfer.files;
  $("#file-label").textContent = fileInput.files[0]?.name || "";
});

$("#ingest-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!fileInput.files.length) return;
  const status = $("#ingest-status");
  const btn = $("#ingest-btn");
  btn.disabled = true;
  status.className = "status";
  const t0 = performance.now();
  const timer = setInterval(() => (status.textContent = `Extracting & indexing… ${((performance.now() - t0) / 1000).toFixed(0)}s`), 500);
  try {
    const out = await api("/api/ingest", { method: "POST", body: new FormData(e.target) });
    const chunks = out.results.reduce((a, r) => a + r.chunks_indexed, 0);
    status.textContent = `Done: ${chunks} chunks indexed in ${((performance.now() - t0) / 1000).toFixed(1)}s`;
    showResults(out.name, out.results);
    loadDocs();
  } catch (err) {
    status.className = "status err";
    status.textContent = err.message;
  } finally {
    clearInterval(timer);
    btn.disabled = false;
  }
});

// ---------- results ----------
function fieldsTable(fields) {
  const names = Object.keys(fields || {});
  if (!names.length) return el("p", { class: "muted" }, "No structured fields for this model (layout/read/search models return content only).");
  const tbody = el("tbody");
  for (const n of names) {
    const { value, confidence } = fields[n];
    const v = typeof value === "object" && value !== null ? el("pre", {}, JSON.stringify(value, null, 1)) : String(value ?? "");
    tbody.append(el("tr", {}, el("td", {}, n), el("td", {}, v), el("td", { class: "conf" }, confidence != null ? confidence.toFixed(2) : "")));
  }
  return el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Field"), el("th", {}, "Value"), el("th", {}, "Conf."))), tbody);
}

function showResults(name, results) {
  $("#result-title").textContent = name;
  const box = $("#results");
  box.replaceChildren();
  for (const r of results) {
    const isDi = r.engine === "document-intelligence";
    const md = el("div", { class: "md" }, renderMarkdown(r.markdown));
    const raw = el("pre", { class: "md" }, r.markdown);
    box.append(
      el("div", { class: `engine ${isDi ? "di" : "cu"}` },
        el("h3", {}, isDi ? "Azure AI Document Intelligence" : "Azure Content Understanding"),
        el("div", { class: "metrics" },
          el("span", {}, r.model),
          el("span", {}, `${(r.duration_ms / 1000).toFixed(1)}s`),
          el("span", {}, `${r.pages} pages`),
          el("span", {}, `${r.tables} tables`),
          el("span", {}, `${Object.keys(r.fields || {}).length} fields`),
          el("span", {}, `${r.chunks_indexed ?? 0} chunks indexed`)),
        r.summary ? el("div", { class: "summary" }, el("b", {}, "Generative summary: "), r.summary) : null,
        fieldsTable(r.fields),
        el("details", { open: "" }, el("summary", {}, "Markdown (rendered)"), md),
        el("details", {}, el("summary", {}, "Markdown (raw)"), raw))
    );
  }
}

// ---------- library ----------
async function loadDocs() {
  const list = $("#docs");
  const docs = await api("/api/documents");
  list.replaceChildren();
  if (!docs.length) list.append(el("li", { class: "muted" }, "No documents yet."));
  for (const d of docs) {
    const del = el("button", { class: "link", title: "Delete" }, "✕");
    const open = el("a", { href: `/api/documents/${d.blob}`, target: "_blank", title: "Open original" }, "↗");
    const li = el("li", {},
      el("div", {}, d.name, el("div", { class: "meta" }, `${d.engines} · ${(d.size / 1024).toFixed(0)} KB`)),
      el("div", {}, open, del));
    li.addEventListener("click", async (e) => {
      if (e.target === del || e.target === open) return;
      showResults(d.name, await api(`/api/documents/${d.doc_id}/results`));
    });
    del.addEventListener("click", async () => {
      if (!confirm(`Delete ${d.name} from storage and the search index?`)) return;
      await api(`/api/documents/${d.doc_id}`, { method: "DELETE" });
      loadDocs();
    });
    list.append(li);
  }
}
$("#refresh").addEventListener("click", loadDocs);

// ---------- chat ----------
function addMessage(role, content, citations = [], meta = "") {
  const m = el("div", { class: `msg ${role}` });
  m.append(role === "bot" ? renderMarkdown(content) : document.createTextNode(content));
  if (citations.length || meta) {
    const c = el("div", { class: "cites" }, meta ? `${meta} ` : "");
    for (const ci of citations) {
      const href = /^(\/|https?:\/\/)/.test(ci.url || "") ? ci.url : "#";
      c.append(el("a", { href, target: "_blank", rel: "noopener" }, `📄 ${ci.title || ci.url}`));
    }
    m.append(c);
  }
  $("#messages").append(m);
  m.scrollIntoView({ behavior: "smooth" });
  return m;
}

async function send(question) {
  if (!question.trim()) return;
  addMessage("user", question);
  $("#question").value = "";
  const pending = addMessage("bot", "_Thinking… (agent is searching the index)_");
  try {
    const r = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, conversation_id: conversationId }),
    });
    conversationId = r.conversation_id;
    pending.remove();
    const tools = r.tool_calls.length ? `tools: ${[...new Set(r.tool_calls)].join(", ")} ·` : "";
    addMessage("bot", r.answer, r.citations, tools);
  } catch (err) {
    pending.remove();
    addMessage("bot", `**Error:** ${err.message}`);
  }
}

$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); send($("#question").value); });
document.querySelectorAll(".suggestions button").forEach((b) => b.addEventListener("click", () => send(b.textContent)));
$("#new-chat").addEventListener("click", () => { conversationId = null; $("#messages").replaceChildren(); });

loadConfig().catch((e) => ($("#agent-info").textContent = e.message));
loadDocs().catch(() => {});
