// MPMC Lab Copilot – single-page app (hash routing, no build step).
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

const state = {
  experiments: [],   // summaries from /api/experiments
  topics: [],
  note: "",
  health: null,
  manual: loadManual(), // {filename, pages, chunks} – kept only in this browser tab
  chat: [],          // [{role, text, meta}]
  chatExp: "",
};

const PAGES = {
  home: "Dashboard", library: "Experiment Library", experiment: "Experiment", chat: "AI Lab Copilot",
  guide: "Procedure Walkthrough", explain: "Code Analyzer", verify: "Result Validator",
  diagnose: "Debug Assistant", viva: "Viva Prep", manual: "Manual Search",
};

// ------------------------------------------------------------------ helpers
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const icon = (name, cls = "") => `<svg class="i ${cls}"><use href="#i-${name}"/></svg>`;

function pageHead(eyebrow, title, lead = "") {
  return `<div class="page-head"><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1>${lead ? `<p class="lead">${lead}</p>` : ""}</div>`;
}

function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])_([^_]+)_(?=[\s.,:;)]|$)/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])\*([^*\s][^*]*)\*(?=[\s.,:;)]|$)/g, "$1<em>$2</em>");
}

// Tiny, safe markdown renderer (input is escaped first).
function md(src) {
  const blocks = [];
  src = String(src || "").replace(/```\w*\n?([\s\S]*?)```/g, (_, code) => { blocks.push(code); return `\u0000${blocks.length - 1}\u0000`; });
  const out = [];
  let list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of esc(src).split("\n")) {
    const line = raw.trimEnd();
    const t = line.trim();
    let m;
    if ((m = t.match(/^\u0000(\d+)\u0000$/))) { closeList(); out.push(codeBlock(blocks[+m[1]])); continue; }
    if (!t) { closeList(); continue; }
    if (/^-{3,}$/.test(t)) { closeList(); continue; }
    if ((m = t.match(/^(#{1,4})\s+(.*)$/))) { closeList(); const h = Math.min(m[1].length + 1, 4); out.push(`<h${h}>${inline(m[2])}</h${h}>`); continue; }
    if ((m = t.match(/^&gt;\s?(.*)$/))) { closeList(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if ((m = t.match(/^[-*]\s+(.*)$/)) || (m = t.match(/^\d+\.\s+(.*)$/))) {
      const type = /^\d/.test(t) ? "ol" : "ul";
      if (list && list !== type && !/^\s/.test(line)) closeList();
      if (!list) { list = type; out.push(`<${type}>`); }
      out.push(`<li>${inline(m[1])}</li>`);
      continue;
    }
    closeList();
    out.push(`<p>${inline(t)}</p>`);
  }
  closeList();
  return `<div class="md">${out.join("")}</div>`;
}

function codeBlock(code) {
  return `<pre class="code"><button class="copy-btn" type="button">Copy</button><code>${esc(code)}</code></pre>`;
}

function loading(text = "Loading…") { return `<div class="state center"><span class="spinner"></span>${esc(text)}</div>`; }
function errorBox(msg) { return `<div class="state error">${icon("alert")}<div>${esc(msg)}</div></div>`; }
function empty(msg) { return `<div class="state center">${esc(msg)}</div>`; }

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 2500);
}

function loadManual() {
  try { return JSON.parse(sessionStorage.getItem("manual") || "null"); } catch (e) { return null; }
}
function saveManual(m) {
  state.manual = m;
  try { m ? sessionStorage.setItem("manual", JSON.stringify(m)) : sessionStorage.removeItem("manual"); }
  catch (e) { /* storage full or blocked – keep in memory only */ }
}

async function ensureExperiments() {
  if (state.experiments.length) return;
  const data = await API.experiments();
  state.experiments = data.experiments;
  state.topics = data.topics;
  state.note = data.assembler_note;
}

function expOptions(selected = "", { onlyVerifiable = false, placeholder = "Select an experiment" } = {}) {
  return `<option value="">${esc(placeholder)}</option>` + state.experiments
    .filter((e) => !onlyVerifiable || e.verifiable)
    .map((e) => `<option value="${esc(e.id)}" ${e.id === selected ? "selected" : ""}>${String(e.number).padStart(2, "0")} · ${esc(e.title)}</option>`).join("");
}

const TOOL_NAMES = {
  experiment_search: "Experiment Search", manual_qa: "Manual Q&A", program_explainer: "Code Analyzer",
  output_verification: "Result Validator", error_diagnosis: "Debug Assistant", viva_generator: "Viva Generator",
  experiment_guide: "Procedure Guide",
};
const toolName = (t) => TOOL_NAMES[t] || t;

// Show what the agent (or a directly used tool) did.
function showActivity({ title, mode, steps }) {
  const modeTag = mode ? `<span class="tag ${mode === "groq" ? "ok" : "warn"}">${mode === "groq" ? "Groq AI" : "Rule-based"}</span>` : "";
  $("#activityBody").innerHTML = `<div class="trace-title"><span>${esc(title)}</span>${modeTag}</div>` + steps.map((s) => `
    <div class="step ${esc(s.status)}">
      <span class="step-phase">${esc(s.phase)}</span>${s.tool ? `<span class="step-tool">${esc(s.tool)}</span>` : ""}
      <div class="step-detail">${esc(s.detail)}</div>
    </div>`).join("") + `<p class="trace-time">${new Date().toLocaleTimeString()}</p>`;
}

function directTool(tool, why, status, mode) {
  showActivity({
    title: "Direct tool call", mode,
    steps: [
      { phase: "select", tool, status: "ok", detail: `Selected on this page: ${why}.` },
      { phase: "execute", tool, status, detail: `Backend ran ${tool} → status '${status}'.` },
    ],
  });
}

// ------------------------------------------------------------------ views
const views = {};

views.home = async () => {
  view.innerHTML = loading();
  const [health] = await Promise.all([API.health().catch(() => null), ensureExperiments().catch(() => {})]);
  const verifiable = state.experiments.filter((e) => e.verifiable).length;
  const actions = [
    ["library", "", "Experiment Library", "Browse aims, algorithms, programs and expected results.", "#/library"],
    ["steps", "cyan", "Procedure Walkthrough", "Perform any experiment one guided step at a time.", "#/guide"],
    ["code", "", "Code Analyzer", "Line-by-line breakdown of 8086 programs with register and flag effects.", "#/explain"],
    ["check", "green", "Result Validator", "Check observed outputs against reference computations.", "#/verify"],
    ["bug", "rose", "Debug Assistant", "Map assembler errors and faulty code to causes and fixes.", "#/diagnose"],
    ["cap", "amber", "Viva Prep", "Graded questions from fundamentals to challenging.", "#/viva"],
  ];
  view.innerHTML = `
    <section class="hero"><div class="hero-grid"><div>
      <p class="eyebrow">Agentic AI · 8086 Microprocessor Lab</p>
      <h1>Your intelligent copilot for the <span>MPMC laboratory</span></h1>
      <p>Understand experiments, analyze assembly code, validate results and prepare for viva — with an AI agent that selects the right tool for every request and shows its reasoning.</p>
      <div class="row">
        <a class="btn" href="#/chat">${icon("spark")} Open AI Copilot</a>
        <a class="btn ghost" href="#/library">Browse experiments ${icon("arrow")}</a>
      </div></div>
      <pre class="hero-code"><i>; 16-bit addition</i>
<b>MOV</b> AX, <em>NUM1</em>
<b>ADD</b> AX, <em>NUM2</em>
<b>MOV</b> RESULT, AX
<b>JNC</b> SKIP   <i>; CF = 0</i></pre>
    </div></section>
    ${health ? "" : errorBox("Backend not reachable. Start it with: python app.py (inside the backend folder).")}
    <div class="stats">
      <div class="stat"><div class="stat-value">${state.experiments.length || "—"}</div><div class="stat-label">Lab experiments</div></div>
      <div class="stat"><div class="stat-value">7</div><div class="stat-label">Agent tools</div></div>
      <div class="stat"><div class="stat-value">${verifiable || "—"}</div><div class="stat-label">Auto-verifiable</div></div>
      <div class="stat"><div class="stat-value" style="font-size:1.15rem;padding-top:6px">${health ? (health.mode === "groq" ? "Groq AI" : "Rule-based") : "Offline"}</div><div class="stat-label">Reasoning engine</div></div>
    </div>
    <p class="section-title">Lab tools</p>
    <div class="grid" style="margin-bottom:30px">
      ${actions.map(([ic, tone, t, d, h]) => `
        <a class="card action-card" href="${h}">
          <span class="tile ${tone}">${icon(ic)}</span>
          <div><h3>${t}</h3><p>${d}</p></div>
          <span class="go">Open ${icon("arrow")}</span>
        </a>`).join("")}
    </div>
    <p class="section-title">How the agent works</p>
    <div class="card">
      <div class="pipeline">
        ${[["Understand", "Groq AI or the rule router interprets the request."],
           ["Select", "Chooses one of 7 specialised tools."],
           ["Execute", "Runs the tool on real lab data and your input."],
           ["Validate", "Retries with another tool if needed (max 3 calls)."],
           ["Respond", "Answers only from the tool's result."]]
          .map(([t, d], i) => `<div class="pipe"><div class="pipe-num">0${i + 1}</div><div><h4>${t}</h4><p>${d}</p></div></div>`).join("")}
      </div>
    </div>`;
};

views.library = async () => {
  view.innerHTML = `
    ${pageHead("Workspace", "Experiment Library", "Search by name, experiment number (e.g. “exp 5”) or concept.")}
    <div class="search-box">${icon("search")}<input type="search" id="libSearch" placeholder="Search experiments — sorting, carry, 8255…" aria-label="Search experiments"></div>
    <div class="chips" id="libTopics"></div>
    <div id="libResults">${loading()}</div>
    <p class="hint" id="libNote" style="margin-top:20px"></p>`;
  let topic = "";
  const run = async () => {
    const box = $("#libResults");
    box.innerHTML = loading("Searching…");
    try {
      const data = await API.experiments($("#libSearch").value, topic);
      $("#libTopics").innerHTML = ["", ...data.topics].map((t) => `<button class="chip ${t === topic ? "active" : ""}" data-topic="${esc(t)}">${t ? esc(t) : "All topics"}</button>`).join("");
      $("#libNote").textContent = data.assembler_note;
      box.innerHTML = data.experiments.length ? `<div class="grid">${data.experiments.map((e) => `
        <div class="card exp-card" data-id="${esc(e.id)}" tabindex="0" role="button" aria-label="Open ${esc(e.title)}">
          <div class="exp-top"><span class="exp-num">EXP ${String(e.number).padStart(2, "0")}</span><span class="tag neutral">${esc(e.topic)}</span></div>
          <h3>${esc(e.title)}</h3>
          <p>${esc(e.aim)}</p>
          <div class="exp-foot">${e.verifiable ? `<span class="tag ok">${icon("ok")} Auto-verifiable</span>` : `<span class="tag warn">Hardware</span>`}</div>
        </div>`).join("")}</div>` : empty("No experiments match your search. Try a different keyword.");
    } catch (e) { box.innerHTML = errorBox(e.message); }
  };
  let timer;
  $("#libSearch").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 250); });
  $("#libTopics").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-topic]");
    if (b) { topic = b.dataset.topic; run(); }
  });
  const open = (ev) => { const c = ev.target.closest(".exp-card"); if (c) location.hash = `#/experiment/${c.dataset.id}`; };
  $("#libResults").addEventListener("click", open);
  $("#libResults").addEventListener("keydown", (ev) => { if (ev.key === "Enter") open(ev); });
  run();
};

views.experiment = async (id) => {
  view.innerHTML = loading();
  try {
    const e = await API.experiment(id);
    $("#crumb").textContent = e.title;
    const ul = (items) => `<ul class="clean">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`;
    const ol = (items) => `<ol class="steps-list">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ol>`;
    view.innerHTML = `
      <a class="back-link" href="#/library">${icon("back")} Experiment Library</a>
      <div class="detail-head">
        <div>
          <div class="meta-line"><span class="tag mono">EXP ${String(e.number).padStart(2, "0")}</span><span class="tag neutral">${esc(e.topic)}</span>${e.verify ? `<span class="tag ok">Auto-verifiable</span>` : ""}</div>
          <h1 style="margin:0">${esc(e.title)}</h1>
        </div>
        <div class="row">
          <a class="btn" href="#/guide/${e.id}">${icon("steps")} Start walkthrough</a>
          <a class="btn secondary" href="#/explain/${e.id}">${icon("code")} Analyze code</a>
          ${e.verify ? `<a class="btn secondary" href="#/verify/${e.id}">${icon("check")} Validate</a>` : ""}
          <a class="btn secondary" href="#/viva/${e.id}">${icon("cap")} Viva</a>
        </div>
      </div>
      <div class="card"><p class="section-title">Aim</p><p style="margin:0;font-size:15px">${esc(e.aim)}</p></div>
      <div class="grid-2">
        <div class="card"><p class="section-title">Apparatus</p>${ul(e.apparatus || [])}</div>
        <div class="card"><p class="section-title">Theory</p><p style="margin:0">${esc(e.theory || "")}</p></div>
      </div>
      <div class="grid-2">
        <div class="card"><p class="section-title">Algorithm</p>${ol(e.algorithm)}</div>
        <div class="card"><p class="section-title">Procedure</p>${ol(e.procedure)}</div>
      </div>
      <div class="card">
        <div class="row" style="justify-content:space-between"><p class="section-title" style="margin:0">Program</p><span class="tag neutral">${esc(e.program.assembler)}</span></div>
        ${codeBlock(e.program.code)}
        <p class="section-title" style="margin-top:14px">Assumptions</p>${ul(e.program.assumptions || [])}
      </div>
      <div class="grid-2">
        <div class="card"><p class="section-title">Expected result</p>
          <dl class="kv"><dt>Input</dt><dd>${esc(e.sample_input || "-")}</dd><dt>Output</dt><dd>${esc(e.expected_output)}</dd></dl></div>
        <div class="card"><p class="section-title">Common errors</p>${ul(e.common_errors || [])}</div>
      </div>`;
  } catch (err) { view.innerHTML = errorBox(err.message) + `<p><a class="back-link" href="#/library">${icon("back")} Experiment Library</a></p>`; }
};

views.chat = async () => {
  await ensureExperiments().catch(() => {});
  const suggestions = [
    ["Lookup", "Show me experiment 7"], ["Code", "Explain MUL BX"],
    ["Debug", "I got a divide overflow error"], ["Viva", "Viva questions for block transfer"],
    ["Guide", "Guide me step by step through addition"], ["Concept", "What is the difference between JA and JG?"],
  ];
  view.innerHTML = `
    <div class="chat">
      <div class="chat-head">
        <div><p class="eyebrow">Workspace</p><h1>AI Lab Copilot</h1></div>
        <div class="context-bar">
          <select id="chatExp" aria-label="Experiment context">${expOptions(state.chatExp, { placeholder: "Context: auto-detect" })}</select>
          <span class="tag ${state.manual ? "ok" : "neutral"}">${icon("file")} ${state.manual ? esc(state.manual.filename) : "No manual"}</span>
        </div>
      </div>
      <div class="messages" id="messages"></div>
      <form id="chatForm">
        <div class="composer">
          <textarea id="chatInput" rows="1" placeholder="Ask about an experiment, paste 8086 code, or describe an error…" maxlength="4000" aria-label="Message"></textarea>
          <button class="btn" type="submit" id="chatSend" aria-label="Send">${icon("send")}</button>
        </div>
        <p class="composer-note">Enter to send · Shift+Enter for a new line · The agent's tool choice appears in the activity panel</p>
      </form>
    </div>`;
  const box = $("#messages");
  const render = () => {
    box.innerHTML = state.chat.length ? state.chat.map((m) => m.role === "user"
      ? `<div class="msg user">${esc(m.text)}</div>`
      : `<div class="msg bot">${m.meta ? `<div class="meta">${icon("tool")}<span class="tag">${esc(toolName(m.meta.tool))}</span><span class="tag ${m.meta.mode === "groq" ? "ok" : "warn"}">${m.meta.mode === "groq" ? "Groq AI" : "Rule-based"}</span><span>${esc(m.meta.reason || "")}</span></div>` : ""}${m.error ? errorBox(m.text) : md(m.text)}</div>`).join("")
      : `<div class="welcome">
          <span class="tile">${icon("spark")}</span>
          <h2>How can I help with your lab today?</h2>
          <p class="muted">I pick the right tool for each request — experiment lookup, code analysis, debugging, validation, viva or manual search.</p>
          <div class="suggestions">${suggestions.map(([k, s]) => `<button class="suggestion" type="button" data-s="${esc(s)}"><small>${k}</small>${esc(s)}</button>`).join("")}</div>
        </div>`;
    box.scrollTop = box.scrollHeight;
  };
  render();
  const input = $("#chatInput");
  const grow = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 180) + "px"; };
  input.addEventListener("input", grow);
  box.addEventListener("click", (ev) => { const s = ev.target.closest("[data-s]"); if (s) { input.value = s.dataset.s; send(); } });
  $("#chatExp").addEventListener("change", (ev) => { state.chatExp = ev.target.value; });
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); } });
  $("#chatForm").addEventListener("submit", (ev) => { ev.preventDefault(); send(); });

  async function send() {
    const text = input.value.trim();
    if (!text) { toast("Type a message first."); return; }
    input.value = "";
    grow();
    state.chat.push({ role: "user", text });
    render();
    box.insertAdjacentHTML("beforeend", `<div class="msg bot">${loading("Selecting a tool…")}</div>`);
    box.scrollTop = box.scrollHeight;
    $("#chatSend").disabled = true;
    try {
      const r = await API.chat(text, state.chatExp || null, state.manual ? state.manual.chunks : []);
      state.chat.push({ role: "bot", text: r.answer, meta: r });
      showActivity({ title: `Agent run · ${r.tool_calls} tool call${r.tool_calls === 1 ? "" : "s"}`, mode: r.mode, steps: r.steps });
    } catch (e) {
      state.chat.push({ role: "bot", text: e.message, error: true });
    }
    $("#chatSend").disabled = false;
    render();
    input.focus();
  }
};

views.explain = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    ${pageHead("Lab Tools", "Code Analyzer", "Line-by-line static analysis of 8086 assembly — operands, register changes, flag effects and common mistakes. Code is analysed, never executed.")}
    <div class="card">
      <label for="exSel">Start from a lab program</label>
      <select id="exSel">${expOptions(id || "", { placeholder: "Or paste your own code below" })}</select>
      <label for="exCode">Assembly source</label>
      <textarea id="exCode" class="mono" rows="12" placeholder="MOV AX, 1234h&#10;ADD AX, BX"></textarea>
      <div class="row" style="margin-top:14px"><button class="btn" id="exBtn">${icon("code")} Analyze</button><button class="btn ghost" id="exClear">Clear</button></div>
    </div>
    <div id="exOut"></div>`;
  const load = async (eid) => {
    if (!eid) return;
    try { $("#exCode").value = (await API.experiment(eid)).program.code; } catch (e) { toast(e.message); }
  };
  $("#exSel").addEventListener("change", (ev) => load(ev.target.value));
  $("#exClear").addEventListener("click", () => { $("#exCode").value = ""; $("#exOut").innerHTML = ""; });
  $("#exBtn").addEventListener("click", async () => {
    const code = $("#exCode").value.trim();
    const out = $("#exOut");
    if (!code) { out.innerHTML = errorBox("Paste some assembly code first."); return; }
    out.innerHTML = loading("Analysing…");
    try {
      const r = await API.explain(code);
      directTool("program_explainer", "analyze the pasted code", r.status);
      if (r.status !== "ok") { out.innerHTML = empty(r.text); return; }
      const d = r.data;
      out.innerHTML = `
        <div class="card">
          <div class="row" style="justify-content:space-between;margin-bottom:12px"><p class="section-title" style="margin:0">Line-by-line breakdown</p><span class="tag neutral">Static analysis</span></div>
          <div class="table-wrap"><table>
            <tr><th>Code</th><th>What it does</th><th>Changes</th><th>Flags</th></tr>
            ${d.lines.map((l) => `<tr><td class="mono">${esc(l.code)}</td><td>${inline(esc(l.explanation))}${l.kind === "unknown" ? ' <span class="tag err">unknown</span>' : ""}</td><td class="mono">${esc(l.changes.join(", "))}</td><td class="small muted">${esc(l.flags)}</td></tr>`).join("")}
          </table></div>
          ${d.registers_modified.length ? `<p style="margin:14px 0 0"><span class="section-title">Registers modified</span><br>${d.registers_modified.map((r) => `<span class="tag mono">${esc(r)}</span>`).join(" ")}</p>` : ""}
        </div>
        ${d.issues.length ? `<div class="card"><div class="card-title"><span class="tile amber">${icon("alert")}</span><h3 style="margin:0">Potential issues (${d.issues.length})</h3></div><ul class="clean">${d.issues.map((i) => `<li>${i.line ? `<span class="tag mono">L${i.line}</span> ` : ""}${esc(i.issue)}<br><span class="muted small">Fix: ${esc(i.fix)}</span></li>`).join("")}</ul></div>`
          : `<div class="state success">${icon("ok")}<div>No common mistakes detected by the static checks.</div></div>`}`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
  if (id) load(id);
};

views.verify = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    ${pageHead("Lab Tools", "Result Validator", "Enter the inputs you used and the output you observed, in <strong>hex</strong> (e.g. 68AC or 68ACh).")}
    <div class="card">
      <label for="vSel">Experiment</label>
      <select id="vSel">${expOptions(id || "", { onlyVerifiable: true })}<option value="custom" ${id === "custom" ? "selected" : ""}>Custom · Experiment from my own manual</option></select>
      <p class="hint">Listed experiments are checked against a built-in reference computation. For anything else, choose <strong>Custom</strong> and enter the expected output from your manual. Hardware experiments (e.g. 8255) can't be validated in software.</p>
      <form id="vForm"></form>
    </div>
    <div id="vOut"></div>`;
  const build = async (eid) => {
    const form = $("#vForm");
    $("#vOut").innerHTML = "";
    if (!eid) { form.innerHTML = ""; return; }
    if (eid === "custom") {
      form.innerHTML = `
        <div class="grid-2" style="margin-top:6px">
          <div><label for="in_expected">Expected output (from your manual)</label>
            <input type="text" id="in_expected" name="in.expected" class="mono" placeholder="68AC  or  07, 12, 34, 45, 89" autocomplete="off" required></div>
          <div><label for="obs_observed">Observed output</label>
            <input type="text" id="obs_observed" name="obs.observed" class="mono" placeholder="same format" autocomplete="off" required></div>
        </div>
        <div class="row" style="margin-top:16px"><button class="btn" type="submit">${icon("check")} Compare</button></div>`;
      return;
    }
    form.innerHTML = loading();
    try {
      const e = await API.experiment(eid);
      const spec = e.verify;
      const field = (f, group, val = "") => `<label for="${group}_${f.name}">${esc(f.label)}</label><input type="text" class="mono" id="${group}_${f.name}" name="${group}.${f.name}" value="${esc(val)}" autocomplete="off" required>`;
      form.innerHTML = `
        <div class="grid-2" style="margin-top:6px">
          <div><p class="section-title" style="margin-top:14px">Inputs</p>${spec.inputs.map((f) => field(f, "in", spec.sample[f.name])).join("")}</div>
          <div><p class="section-title" style="margin-top:14px">Observed output</p>${spec.outputs.map((f) => field(f, "obs")).join("")}</div>
        </div>
        <p class="hint">Reference for the default input: <span class="mono">${esc(e.expected_output)}</span></p>
        <div class="row" style="margin-top:14px"><button class="btn" type="submit">${icon("check")} Validate</button></div>`;
    } catch (err) { form.innerHTML = errorBox(err.message); }
  };
  $("#vSel").addEventListener("change", (ev) => build(ev.target.value));
  $("#vForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const inputs = {}, observed = {};
    for (const el of ev.target.querySelectorAll("input")) {
      const [g, n] = el.name.split(".");
      (g === "in" ? inputs : observed)[n] = el.value.trim();
    }
    const out = $("#vOut");
    out.innerHTML = loading("Validating…");
    try {
      const r = await API.verify($("#vSel").value, inputs, observed);
      directTool("output_verification", "validate observed output", r.status);
      const d = r.data;
      if (d.verdict === "error_expected") { out.innerHTML = `<div class="card">${md(r.text)}</div>`; return; }
      const ok = d.verdict === "match";
      out.innerHTML = `
        <div class="card">
          <div class="result-banner">
            <div class="row"><span class="tile ${ok ? "green" : "rose"}">${icon(ok ? "ok" : "x")}</span><span style="font-size:16px">${ok ? "Output matches the expected result" : "Output does not match"}</span></div>
            <span class="tag ${d.verified ? "ok" : "warn"}">${d.verified ? "Verified · reference computation" : "Compared with your expected values"}</span>
          </div>
          <div class="table-wrap"><table><tr><th>Field</th><th>Expected</th><th>Observed</th><th>Status</th></tr>
            ${d.comparison.map((c) => `<tr><td>${esc(c.field)}</td><td class="mono">${esc(c.expected)}</td><td class="mono">${esc(c.observed)}</td><td class="${c.match ? "match-yes" : "match-no"}">${icon(c.match ? "ok" : "x")}</td></tr>`).join("")}
          </table></div>
          ${d.hints.length ? `<p class="section-title" style="margin-top:18px">Likely causes</p><ul class="clean">${d.hints.map((h) => `<li>${inline(esc(h))}</li>`).join("")}</ul>` : ""}
        </div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
  if (id) build(id);
};

views.diagnose = async () => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    ${pageHead("Lab Tools", "Debug Assistant", "Paste an assembler error, a program that misbehaves, or both — get likely causes and concrete fixes.")}
    <div class="card">
      <label for="dSel">Experiment <span class="muted" style="font-weight:400">(optional)</span></label>
      <select id="dSel">${expOptions("", { placeholder: "Not specific to an experiment" })}</select>
      <label for="dMsg">Error message or symptom</label>
      <textarea id="dMsg" rows="3" style="min-height:76px" placeholder="error A2070: invalid instruction operands · divide overflow · wrong output"></textarea>
      <label for="dCode">Program <span class="muted" style="font-weight:400">(optional)</span></label>
      <textarea id="dCode" class="mono" rows="10" placeholder="Paste your 8086 program"></textarea>
      <div class="row" style="margin-top:14px"><button class="btn" id="dBtn">${icon("bug")} Diagnose</button></div>
    </div>
    <div id="dOut"></div>`;
  $("#dBtn").addEventListener("click", async () => {
    const msg = $("#dMsg").value.trim(), code = $("#dCode").value.trim();
    const out = $("#dOut");
    if (!msg && !code) { out.innerHTML = errorBox("Enter an error message, a program, or both."); return; }
    out.innerHTML = loading("Diagnosing…");
    try {
      const r = await API.diagnose(msg, code, $("#dSel").value || null);
      directTool("error_diagnosis", "diagnose the error/program", r.status);
      out.innerHTML = `<div class="card"><div class="card-title"><span class="tile rose">${icon("bug")}</span><h3 style="margin:0">Diagnosis</h3></div>${md(r.text)}</div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
};

views.viva = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    ${pageHead("Lab Tools", "Viva Prep", "Graded questions for each experiment. Answer in your head first, then reveal.")}
    <div class="card"><div class="row" style="align-items:flex-end">
      <div class="grow"><label for="vvSel">Experiment</label><select id="vvSel">${expOptions(id || "")}</select></div>
      <div><label for="vvLevel">Difficulty</label><select id="vvLevel"><option value="all">All levels</option><option value="easy">Fundamental</option><option value="medium">Intermediate</option><option value="hard">Challenging</option></select></div>
      <div><label for="vvCount">Questions</label><input type="number" id="vvCount" value="6" min="1" max="30" style="width:96px"></div>
      <button class="btn" id="vvBtn">${icon("cap")} Generate</button>
    </div></div>
    <div id="vvOut"></div>`;
  const LEVEL = { easy: ["Fundamental", "ok"], medium: ["Intermediate", "warn"], hard: ["Challenging", "err"] };
  const gen = async () => {
    const eid = $("#vvSel").value, out = $("#vvOut");
    if (!eid) { out.innerHTML = errorBox("Choose an experiment first."); return; }
    out.innerHTML = loading("Generating…");
    try {
      const r = await API.viva(eid, $("#vvLevel").value, $("#vvCount").value || 6);
      directTool("viva_generator", "generate viva questions", r.status);
      const qs = r.data.questions || [];
      out.innerHTML = qs.length ? qs.map((q, i) => `
        <div class="qa">
          <div class="qa-q"><span class="qa-num">Q${String(i + 1).padStart(2, "0")}</span><div><span class="tag ${LEVEL[q.level][1]}" style="margin-bottom:6px">${LEVEL[q.level][0]}</span><br><strong>${esc(q.q)}</strong></div></div>
          <button class="btn secondary sm reveal">Reveal answer</button>
          <div class="answer" hidden>${esc(q.a)}</div>
        </div>`).join("") : empty("No questions available.");
    } catch (e) { out.innerHTML = errorBox(e.message); }
  };
  $("#vvBtn").addEventListener("click", gen);
  $("#vvOut").addEventListener("click", (ev) => {
    const b = ev.target.closest(".reveal");
    if (b) { const a = b.nextElementSibling; a.hidden = !a.hidden; b.textContent = a.hidden ? "Reveal answer" : "Hide answer"; }
  });
  if (id) gen();
};

views.guide = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    ${pageHead("Lab Tools", "Procedure Walkthrough", "Work through the experiment one step at a time. Complete each step before moving on.")}
    <div class="card"><label for="gSel">Experiment</label><select id="gSel">${expOptions(id || "")}</select></div>
    <div id="gOut"></div>`;
  let step = 0;
  const show = async () => {
    const eid = $("#gSel").value, out = $("#gOut");
    if (!eid) { out.innerHTML = empty("Select an experiment to begin the walkthrough."); return; }
    out.innerHTML = loading();
    try {
      const r = await API.guide(eid, step);
      const d = r.data;
      directTool("experiment_guide", `show step ${d.step + 1}`, r.status);
      out.innerHTML = `
        <div class="card">
          <div class="row" style="justify-content:space-between">
            <span class="eyebrow" style="margin:0">Step ${d.step + 1} of ${d.total}</span>
            <span class="muted small">${esc(d.experiment.title)}</span>
          </div>
          <div class="progress"><div style="width:${((d.step + 1) / d.total) * 100}%"></div></div>
          <p class="step-card">${esc(d.instruction)}</p>
          <div class="row" style="justify-content:space-between">
            <div class="step-dots">${Array.from({ length: d.total }, (_, i) => `<span class="${i < d.step ? "done" : i === d.step ? "now" : ""}">${i + 1}</span>`).join("")}</div>
            <div class="row">
              <button class="btn secondary" id="gPrev" ${d.has_prev ? "" : "disabled"}>${icon("back")} Previous</button>
              ${d.has_next ? `<button class="btn" id="gNext">Mark done · Next ${icon("arrow")}</button>` : `<a class="btn" href="#/verify/${esc(eid)}">${icon("check")} Validate result</a>`}
            </div>
          </div>
        </div>
        <a class="back-link" href="#/experiment/${esc(eid)}">View full experiment — program, algorithm and expected result ${icon("arrow")}</a>`;
      $("#gPrev").addEventListener("click", () => { step--; show(); });
      const n = $("#gNext");
      if (n) n.addEventListener("click", () => { step++; show(); });
    } catch (e) { out.innerHTML = errorBox(e.message); }
  };
  $("#gSel").addEventListener("change", () => { step = 0; show(); });
  show();
};

views.manual = async () => {
  const m = state.manual;
  view.innerHTML = `
    ${pageHead("Resources", "Manual Search", "Upload your college's MPMC lab manual and ask questions about it. The PDF is processed once and <strong>never stored on the server</strong>; extracted text stays in this browser tab.")}
    <div class="card">
      <p class="section-title">Document</p>
      ${m ? `<div class="dropzone" style="background:var(--success-soft);border-color:transparent">
              <span class="tile green">${icon("file")}</span>
              <div class="grow"><strong>${esc(m.filename)}</strong><div class="small muted">${m.pages} pages · ${m.chunks.length} indexed sections · also used by the AI Copilot</div></div>
              <button class="btn danger sm" id="mClear">Remove</button>
            </div>` : ""}
      <div class="dropzone" style="${m ? "margin-top:12px" : ""}">
        <span class="tile">${icon("upload")}</span>
        <div class="grow"><input type="file" id="mFile" accept="application/pdf,.pdf" aria-label="Choose PDF"><div class="hint">PDF · max 4 MB · text-based (scanned images need OCR)</div></div>
        <button class="btn" id="mUpload">${m ? "Replace" : "Upload & index"}</button>
      </div>
      <div id="mStatus" style="margin-top:12px"></div>
    </div>
    <div class="card">
      <label for="mQ">Ask the manual</label>
      <div class="row"><div class="search-box grow">${icon("search")}<input type="text" id="mQ" placeholder="What is the aim of the sorting experiment?" maxlength="500"></div><button class="btn" id="mAsk" style="height:44px">Search</button></div>
      <p class="hint">${m ? "Searches your uploaded manual and the built-in knowledge base." : "No manual uploaded — searching the built-in knowledge base only."}</p>
    </div>
    <div id="mOut"></div>`;
  $("#mUpload").addEventListener("click", async () => {
    const f = $("#mFile").files[0];
    const status = $("#mStatus");
    if (!f) { status.innerHTML = errorBox("Choose a PDF file first."); return; }
    if (!f.name.toLowerCase().endsWith(".pdf")) { status.innerHTML = errorBox("Only PDF files are allowed."); return; }
    if (f.size > 4 * 1024 * 1024) { status.innerHTML = errorBox("File is larger than 4 MB. Split or compress the PDF."); return; }
    status.innerHTML = loading("Extracting text…");
    try {
      const r = await API.uploadManual(f);
      saveManual({ filename: r.filename, pages: r.pages, chunks: r.chunks });
      toast(r.truncated ? "Manual indexed (very long — only the first part was indexed)." : "Manual indexed.");
      views.manual();
    } catch (e) { status.innerHTML = errorBox(e.message); }
  });
  const clear = $("#mClear");
  if (clear) clear.addEventListener("click", () => { saveManual(null); toast("Manual removed."); views.manual(); });
  const ask = async () => {
    const q = $("#mQ").value.trim(), out = $("#mOut");
    if (!q) { out.innerHTML = errorBox("Type a question first."); return; }
    out.innerHTML = loading("Searching…");
    try {
      const r = await API.manualSearch(q, state.manual ? state.manual.chunks : []);
      showActivity({
        title: "Direct tool call", mode: r.mode, steps: [
          { phase: "select", tool: "manual_qa", status: "ok", detail: "Selected on this page: search the manual." },
          { phase: "execute", tool: "manual_qa", status: r.status, detail: `Backend ran manual_qa → status '${r.status}'.` },
          { phase: "respond", tool: "manual_qa", status: "ok", detail: r.mode === "groq" ? "Groq wrote the answer from the retrieved text." : "Showing retrieved text directly." },
        ],
      });
      const tag = `<span class="tag ${r.mode === "groq" ? "ok" : "neutral"}">${r.mode === "groq" ? "Groq AI answer" : "Search result"}</span>`;
      out.innerHTML = r.status === "ok"
        ? `<div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><p class="section-title" style="margin:0">Answer</p>${tag}</div>${md(r.text)}</div>`
        : `<div class="state">${md(r.text)}</div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  };
  $("#mAsk").addEventListener("click", ask);
  $("#mQ").addEventListener("keydown", (ev) => { if (ev.key === "Enter") ask(); });
};

// ------------------------------------------------------------------ router & shell
async function router() {
  const parts = (location.hash.replace(/^#\/?/, "") || "home").split("/");
  const name = views[parts[0]] ? parts[0] : "home";
  document.querySelectorAll(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (name === "experiment" ? "library" : name)));
  $("#crumb").textContent = PAGES[name];
  document.title = `${PAGES[name]} · MPMC Lab Copilot`;
  closePanels();
  try { await views[name](parts[1] ? decodeURIComponent(parts[1]) : undefined); }
  catch (e) { view.innerHTML = errorBox(e.message); }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

function closePanels() {
  $("#sidebar").classList.remove("open");
  $("#activity").classList.remove("open");
  $("#backdrop").classList.remove("show");
}

$("#menuBtn").addEventListener("click", () => { $("#sidebar").classList.add("open"); $("#backdrop").classList.add("show"); });
$("#activityBtn").addEventListener("click", () => { $("#activity").classList.add("open"); $("#backdrop").classList.add("show"); });
$("#activityClose").addEventListener("click", closePanels);
$("#backdrop").addEventListener("click", closePanels);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closePanels(); });
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest(".copy-btn");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.nextElementSibling.textContent); toast("Copied to clipboard"); }
  catch (e) { toast("Copy is blocked in this browser."); }
});

API.health().then((h) => {
  state.health = h;
  const groq = h.mode === "groq";
  const badge = $("#modeBadge");
  badge.textContent = groq ? "Groq AI" : "Rule-based";
  badge.className = `badge ${h.mode}`;
  badge.title = groq ? `Model: ${h.model}` : "No GROQ_API_KEY set – rule-based answers";
  $("#engineDot").className = `dot ${h.mode}`;
  $("#engineName").textContent = groq ? "Groq AI online" : "Rule-based mode";
  $("#engineInfo").textContent = groq ? h.model : "Add GROQ_API_KEY to enable AI";
}).catch(() => {
  $("#modeBadge").textContent = "Offline";
  $("#engineDot").className = "dot off";
  $("#engineName").textContent = "Backend offline";
  $("#engineInfo").textContent = "Run python app.py";
});

window.addEventListener("hashchange", router);
router();
