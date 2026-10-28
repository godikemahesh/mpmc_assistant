// MPMC Lab Assistant – single-page app (hash routing, no build step).
const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

const state = {
  experiments: [],   // summaries from /api/experiments
  topics: [],
  note: "",
  manual: loadManual(), // {filename, pages, chunks} – kept only in this browser tab
  chat: [],          // [{role, text, meta}]
  chatExp: "",
};

// ------------------------------------------------------------------ helpers
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
    if ((m = t.match(/^(#{1,4})\s+(.*)$/))) { closeList(); out.push(`<h${Math.min(m[1].length + 1, 4)}>${inline(m[2])}</h${Math.min(m[1].length + 1, 4)}>`); continue; }
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

function loading(text = "Loading…") { return `<div class="state"><span class="spinner"></span>${esc(text)}</div>`; }
function errorBox(msg) { return `<div class="state error">⚠️ ${esc(msg)}</div>`; }
function empty(msg) { return `<div class="state">${esc(msg)}</div>`; }

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

function expOptions(selected = "", { onlyVerifiable = false, placeholder = "— choose an experiment —" } = {}) {
  return `<option value="">${esc(placeholder)}</option>` + state.experiments
    .filter((e) => !onlyVerifiable || e.verifiable)
    .map((e) => `<option value="${esc(e.id)}" ${e.id === selected ? "selected" : ""}>Exp ${e.number}: ${esc(e.title)}</option>`).join("");
}

// Show what the agent (or a directly used tool) did.
function showActivity({ title, mode, steps }) {
  const body = $("#activityBody");
  const modeTag = mode ? `<span class="tag ${mode === "groq" ? "ok" : "warn"}">${mode === "groq" ? "Groq AI" : "Fallback (rule-based)"}</span>` : "";
  body.innerHTML = `<p><strong>${esc(title)}</strong> ${modeTag}</p>` + steps.map((s) => `
    <div class="step ${esc(s.status)}">
      <b>${esc(s.phase)}</b> ${s.tool ? `<span class="step-tool">${esc(s.tool)}</span>` : ""}
      <div>${esc(s.detail)}</div>
    </div>`).join("") + `<p class="muted small">${new Date().toLocaleTimeString()}</p>`;
}

function directTool(tool, why, status) {
  showActivity({
    title: "Direct tool call",
    steps: [
      { phase: "select", tool, status: "ok", detail: `Selected by you on this page: ${why}` },
      { phase: "execute", tool, status, detail: `Backend ran ${tool} → status '${status}'.` },
    ],
  });
}

// ------------------------------------------------------------------ views
const views = {};

views.home = async () => {
  const health = await API.health().catch(() => null);
  view.innerHTML = `
    <div class="card hero">
      <h1>Agentic AI-Based MPMC Lab Manual Assistant</h1>
      <p>Understand, perform and verify 8086 microprocessor lab experiments. The agent picks the right tool for your question and shows you what it did.</p>
      <a class="btn" href="#/chat">🤖 Ask the AI Assistant</a>
    </div>
    ${health ? "" : errorBox("Backend not reachable. Start it with: python app.py (inside the backend folder).")}
    ${health && health.mode === "fallback" ? `<div class="state" style="margin-bottom:16px">Running in <strong>fallback mode</strong> (no GROQ_API_KEY). All tools work; answers are rule-based instead of AI-written.</div>` : ""}
    <h2>Quick actions</h2>
    <div class="grid">
      ${[
        ["📚", "Experiment Library", "Search experiments by name, number or topic.", "#/library"],
        ["🧭", "Step-by-step Guide", "Perform an experiment one step at a time.", "#/guide"],
        ["🧩", "Explain a Program", "Line-by-line 8086 code explanation.", "#/explain"],
        ["✅", "Verify Output", "Compare your observed output with the expected one.", "#/verify"],
        ["🩺", "Diagnose an Error", "Find causes and fixes for errors.", "#/diagnose"],
        ["🎓", "Viva Practice", "Easy, medium and hard questions.", "#/viva"],
        ["📄", "Lab Manual", "Upload your college PDF manual and search it.", "#/manual"],
        ["🤖", "AI Assistant", "Ask anything about your MPMC lab.", "#/chat"],
      ].map(([i, t, d, h]) => `<a class="card action-card" href="${h}"><div class="ico">${i}</div><h3>${t}</h3><p class="muted small">${d}</p></a>`).join("")}
    </div>
    <div class="card" style="margin-top:16px">
      <h3>How the agent works</h3>
      <ol class="small">
        <li><strong>Understand</strong> – Groq AI (or the rule-based router) reads your request.</li>
        <li><strong>Select a tool</strong> – one of 7 tools: search, manual Q&amp;A, explainer, verifier, diagnosis, viva, guide.</li>
        <li><strong>Execute</strong> – the tool runs on the real knowledge base / your input.</li>
        <li><strong>Check</strong> – if the result is empty it tries another tool (max 3 calls).</li>
        <li><strong>Respond</strong> – the answer is built only from the tool result. See the <em>Agent Activity</em> panel.</li>
      </ol>
      <p class="muted small">${health ? `${health.experiments} experiments loaded · mode: ${esc(health.mode)}` : ""}</p>
    </div>`;
};

views.library = async () => {
  view.innerHTML = `
    <div class="page-head"><h1>📚 Experiment Library</h1><p>Search by name, number (e.g. “exp 5”) or topic.</p></div>
    <input type="search" id="libSearch" placeholder="Search experiments… e.g. sorting, carry, 8255" aria-label="Search experiments">
    <div class="chips" id="libTopics"></div>
    <div id="libResults">${loading()}</div>
    <p class="muted small" id="libNote"></p>`;
  let topic = "";
  const run = async () => {
    const box = $("#libResults");
    box.innerHTML = loading("Searching…");
    try {
      const data = await API.experiments($("#libSearch").value, topic);
      $("#libTopics").innerHTML = ["", ...data.topics].map((t) => `<button class="chip ${t === topic ? "active" : ""}" data-topic="${esc(t)}">${t ? esc(t) : "All"}</button>`).join("");
      $("#libNote").textContent = data.assembler_note;
      box.innerHTML = data.experiments.length ? `<div class="grid">${data.experiments.map((e) => `
        <div class="card exp-card" data-id="${esc(e.id)}" tabindex="0" role="button">
          <span class="tag">Exp ${e.number} · ${esc(e.topic)}</span>
          <h3>${esc(e.title)}</h3>
          <p>${esc(e.aim)}</p>
          ${e.verifiable ? '<span class="tag ok" style="align-self:flex-start">Auto-verifiable</span>' : ""}
        </div>`).join("")}</div>` : empty("No experiments match your search. Try a different word.");
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
    const list = (items, tag = "ol") => `<${tag}>${items.map((i) => `<li>${esc(i)}</li>`).join("")}</${tag}>`;
    view.innerHTML = `
      <p><a href="#/library">← Back to library</a></p>
      <div class="page-head"><span class="tag">Exp ${e.number} · ${esc(e.topic)}</span><h1>${esc(e.title)}</h1></div>
      <div class="row" style="margin-bottom:16px">
        <a class="btn" href="#/guide/${e.id}">🧭 Guide me</a>
        <a class="btn secondary" href="#/explain/${e.id}">🧩 Explain program</a>
        ${e.verify ? `<a class="btn secondary" href="#/verify/${e.id}">✅ Verify output</a>` : ""}
        <a class="btn secondary" href="#/viva/${e.id}">🎓 Viva</a>
      </div>
      <div class="card"><h3>Aim</h3><p>${esc(e.aim)}</p>
        <h3>Apparatus / Requirements</h3>${list(e.apparatus || [], "ul")}
        <h3>Theory</h3><p>${esc(e.theory || "")}</p></div>
      <div class="card"><h3>Algorithm</h3>${list(e.algorithm)}</div>
      <div class="card"><h3>Procedure</h3>${list(e.procedure)}</div>
      <div class="card"><h3>Program <span class="tag">${esc(e.program.assembler)}</span></h3>
        ${codeBlock(e.program.code)}
        <p class="small"><strong>Assumptions:</strong></p>${list(e.program.assumptions || [], "ul")}</div>
      <div class="card"><h3>Expected Result</h3>
        <p><strong>Input:</strong> ${esc(e.sample_input || "-")}</p>
        <p><strong>Output:</strong> ${esc(e.expected_output)}</p></div>
      <div class="card"><h3>Common Errors</h3>${list(e.common_errors || [], "ul")}</div>`;
  } catch (err) { view.innerHTML = errorBox(err.message) + `<p><a href="#/library">← Back to library</a></p>`; }
};

views.chat = async () => {
  await ensureExperiments().catch(() => {});
  const suggestions = ["Show me experiment 7", "Explain MUL BX", "Viva questions for block transfer",
    "I got divide overflow error", "Guide me step by step through addition", "What is the difference between JA and JG?"];
  view.innerHTML = `
    <div class="chat">
      <div class="page-head"><h1>🤖 AI Assistant</h1>
        <div class="row small">
          <label for="chatExp" style="margin:0">Context:</label>
          <select id="chatExp" style="max-width:340px">${expOptions(state.chatExp, { placeholder: "No experiment selected (auto-detect)" })}</select>
          <span class="muted">${state.manual ? `📄 Using manual: ${esc(state.manual.filename)}` : "No manual uploaded"}</span>
        </div>
      </div>
      <div class="messages" id="messages"></div>
      <form class="chat-form" id="chatForm">
        <textarea id="chatInput" placeholder="Ask about an experiment, paste code, describe an error… (Enter to send, Shift+Enter for new line)" maxlength="4000" aria-label="Message"></textarea>
        <button class="btn" type="submit" id="chatSend">Send</button>
      </form>
    </div>`;
  const box = $("#messages");
  const render = () => {
    box.innerHTML = state.chat.length ? state.chat.map((m) => m.role === "user"
      ? `<div class="msg user">${esc(m.text)}</div>`
      : `<div class="msg bot">${m.meta ? `<div class="meta">🛠 <span class="tag">${esc(m.meta.tool)}</span> <span class="tag ${m.meta.mode === "groq" ? "ok" : "warn"}">${m.meta.mode === "groq" ? "Groq AI" : "Fallback"}</span> ${esc(m.meta.reason || "")}</div>` : ""}${m.error ? errorBox(m.text) : md(m.text)}</div>`).join("")
      : `<div class="state"><p>Try one of these:</p><div class="suggestions" style="justify-content:center">${suggestions.map((s) => `<button class="chip" type="button" data-s="${esc(s)}">${esc(s)}</button>`).join("")}</div></div>`;
    box.scrollTop = box.scrollHeight;
  };
  render();
  box.addEventListener("click", (ev) => { const s = ev.target.closest("[data-s]"); if (s) { $("#chatInput").value = s.dataset.s; send(); } });
  $("#chatExp").addEventListener("change", (ev) => { state.chatExp = ev.target.value; });
  $("#chatInput").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); send(); } });
  $("#chatForm").addEventListener("submit", (ev) => { ev.preventDefault(); send(); });

  async function send() {
    const input = $("#chatInput");
    const text = input.value.trim();
    if (!text) { toast("Type a message first."); return; }
    input.value = "";
    state.chat.push({ role: "user", text });
    render();
    box.insertAdjacentHTML("beforeend", `<div class="msg bot" id="thinking">${loading("Agent is choosing a tool…")}</div>`);
    box.scrollTop = box.scrollHeight;
    $("#chatSend").disabled = true;
    try {
      const r = await API.chat(text, state.chatExp || null, state.manual ? state.manual.chunks : []);
      state.chat.push({ role: "bot", text: r.answer, meta: r });
      showActivity({ title: `Agent run · ${r.tool_calls} tool call(s)`, mode: r.mode, steps: r.steps });
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
    <div class="page-head"><h1>🧩 Program Explainer</h1><p>Paste 8086 code. Each line is explained using static analysis — the program is <strong>not executed</strong>.</p></div>
    <div class="card">
      <div class="row"><div class="grow"><label for="exSel">Load a sample program</label><select id="exSel">${expOptions(id || "", { placeholder: "— or paste your own code below —" })}</select></div></div>
      <label for="exCode">Assembly code</label>
      <textarea id="exCode" class="mono" rows="12" placeholder="MOV AX, 1234h&#10;ADD AX, BX"></textarea>
      <div class="row" style="margin-top:10px"><button class="btn" id="exBtn">Explain</button><button class="btn secondary" id="exClear">Clear</button></div>
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
    if (!code) { out.innerHTML = errorBox("Please paste some assembly code first."); return; }
    out.innerHTML = loading("Analysing…");
    try {
      const r = await API.explain(code);
      directTool("program_explainer", "explain the pasted code", r.status);
      if (r.status !== "ok") { out.innerHTML = empty(r.text); return; }
      const d = r.data;
      out.innerHTML = `
        <div class="card"><h3>Line-by-line explanation</h3><div class="table-wrap"><table>
          <tr><th>Code</th><th>Explanation</th><th>Changes</th><th>Flags</th></tr>
          ${d.lines.map((l) => `<tr><td class="mono">${esc(l.code)}</td><td>${inline(esc(l.explanation))}${l.kind === "unknown" ? ' <span class="tag err">unknown</span>' : ""}</td><td class="mono">${esc(l.changes.join(", "))}</td><td class="small muted">${esc(l.flags)}</td></tr>`).join("")}
        </table></div>
        ${d.registers_modified.length ? `<p><strong>Registers modified:</strong> ${esc(d.registers_modified.join(", "))}</p>` : ""}</div>
        ${d.issues.length ? `<div class="card"><h3>⚠️ Possible problems</h3><ul>${d.issues.map((i) => `<li>${i.line ? `<strong>Line ${i.line}:</strong> ` : ""}${esc(i.issue)}<br><span class="muted">Fix: ${esc(i.fix)}</span></li>`).join("")}</ul></div>`
          : `<div class="state success">No common mistakes detected by the static checks.</div>`}`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
  if (id) load(id);
};

views.verify = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    <div class="page-head"><h1>✅ Output Verification</h1><p>Enter the inputs you used and the output you observed. Values are in <strong>hex</strong> (e.g. 68AC or 68ACh).</p></div>
    <div class="card">
      <label for="vSel">Experiment</label>
      <select id="vSel">${expOptions(id || "", { onlyVerifiable: true })}<option value="custom" ${id === "custom" ? "selected" : ""}>✏️ My own experiment (enter the expected output from your manual)</option></select>
      <p class="muted small">The listed experiments are checked by a built-in reference calculation. For any other experiment from your college manual, choose <strong>My own experiment</strong>. Hardware experiments (e.g. 8255) can't be checked by software.</p>
      <form id="vForm"></form>
    </div>
    <div id="vOut"></div>
    <p class="muted small">How it works: the expected output is computed by a Python reference implementation of the experiment's algorithm for <em>your</em> inputs, then compared with your observed values. Your assembly program itself is not run.</p>`;
  const build = async (eid) => {
    const form = $("#vForm");
    $("#vOut").innerHTML = "";
    if (!eid) { form.innerHTML = ""; return; }
    if (eid === "custom") {
      form.innerHTML = `
        <label for="in_expected">Expected output (hex, from your lab manual – one value or a list)</label>
        <input type="text" id="in_expected" name="in.expected" placeholder="e.g. 68AC   or   07, 12, 34, 45, 89" autocomplete="off" required>
        <label for="obs_observed">Observed output (hex, what you got)</label>
        <input type="text" id="obs_observed" name="obs.observed" placeholder="same format as above" autocomplete="off" required>
        <div class="row" style="margin-top:12px"><button class="btn" type="submit">Compare</button></div>`;
      return;
    }
    form.innerHTML = loading();
    try {
      const e = await API.experiment(eid);
      const spec = e.verify;
      const field = (f, group, val = "") => `<label for="${group}_${f.name}">${esc(f.label)}</label><input type="text" id="${group}_${f.name}" name="${group}.${f.name}" value="${esc(val)}" autocomplete="off" required>`;
      form.innerHTML = `
        <h3 style="margin-top:14px">Inputs</h3>${spec.inputs.map((f) => field(f, "in", spec.sample[f.name])).join("")}
        <h3 style="margin-top:14px">Observed output</h3>${spec.outputs.map((f) => field(f, "obs")).join("")}
        <p class="small muted">Sample expected output for the default input: ${esc(e.expected_output)}</p>
        <div class="row"><button class="btn" type="submit">Verify</button></div>`;
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
    out.innerHTML = loading("Verifying…");
    try {
      const r = await API.verify($("#vSel").value, inputs, observed);
      directTool("output_verification", "compare observed vs expected", r.status);
      const d = r.data;
      if (d.verdict === "error_expected") { out.innerHTML = `<div class="card">${md(r.text)}</div>`; return; }
      out.innerHTML = `
        <div class="state ${d.verdict === "match" ? "success" : "error"}" style="margin-bottom:12px">
          ${d.verdict === "match" ? "✅ Output matches the expected result." : "❌ Output does not match."}
          <span class="tag ${d.verified ? "ok" : "warn"}">${d.verified ? "Verified by reference computation" : "Compared with your expected values (not independently verified)"}</span></div>
        <div class="card"><div class="table-wrap"><table><tr><th>Field</th><th>Expected</th><th>Observed</th><th></th></tr>
          ${d.comparison.map((c) => `<tr><td>${esc(c.field)}</td><td class="mono">${esc(c.expected)}</td><td class="mono">${esc(c.observed)}</td><td>${c.match ? "✔" : "✘"}</td></tr>`).join("")}
        </table></div>
        ${d.hints.length ? `<h3 style="margin-top:14px">Possible reasons</h3><ul>${d.hints.map((h) => `<li>${inline(esc(h))}</li>`).join("")}</ul>` : ""}</div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
  if (id) build(id);
};

views.diagnose = async () => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    <div class="page-head"><h1>🩺 Error Diagnosis</h1><p>Paste the error message, your program, or both.</p></div>
    <div class="card">
      <label for="dSel">Experiment (optional)</label><select id="dSel">${expOptions("", { placeholder: "— not specific —" })}</select>
      <label for="dMsg">Error message or unexpected output</label>
      <textarea id="dMsg" rows="3" style="min-height:70px" placeholder="e.g. error A2070: invalid instruction operands  /  divide overflow  /  wrong output"></textarea>
      <label for="dCode">Your program (optional)</label>
      <textarea id="dCode" class="mono" rows="10" placeholder="Paste your 8086 program here"></textarea>
      <div class="row" style="margin-top:10px"><button class="btn" id="dBtn">Diagnose</button></div>
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
      out.innerHTML = `<div class="card">${md(r.text)}</div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  });
};

views.viva = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    <div class="page-head"><h1>🎓 Viva Practice</h1><p>Think of your answer first, then reveal it.</p></div>
    <div class="card"><div class="row">
      <div class="grow"><label for="vvSel">Experiment</label><select id="vvSel">${expOptions(id || "")}</select></div>
      <div><label for="vvLevel">Level</label><select id="vvLevel"><option value="all">All levels</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Challenging</option></select></div>
      <div><label for="vvCount">Questions</label><input type="number" id="vvCount" value="6" min="1" max="30" style="width:90px"></div>
    </div><div class="row" style="margin-top:12px"><button class="btn" id="vvBtn">Generate questions</button></div></div>
    <div id="vvOut"></div>`;
  const gen = async () => {
    const eid = $("#vvSel").value, out = $("#vvOut");
    if (!eid) { out.innerHTML = errorBox("Choose an experiment first."); return; }
    out.innerHTML = loading("Generating…");
    try {
      const r = await API.viva(eid, $("#vvLevel").value, $("#vvCount").value || 6);
      directTool("viva_generator", "generate viva questions", r.status);
      const qs = r.data.questions || [];
      out.innerHTML = qs.length ? qs.map((q, i) => `
        <div class="qa"><div class="row"><span class="tag ${q.level === "easy" ? "ok" : q.level === "hard" ? "err" : "warn"}">${q.level === "hard" ? "Challenging" : esc(q.level)}</span><strong>Q${i + 1}. ${esc(q.q)}</strong></div>
        <button class="btn secondary sm reveal" style="margin-top:8px">Show answer</button>
        <div class="answer" hidden>${esc(q.a)}</div></div>`).join("") : empty("No questions available.");
    } catch (e) { out.innerHTML = errorBox(e.message); }
  };
  $("#vvBtn").addEventListener("click", gen);
  $("#vvOut").addEventListener("click", (ev) => {
    const b = ev.target.closest(".reveal");
    if (b) { const a = b.nextElementSibling; a.hidden = !a.hidden; b.textContent = a.hidden ? "Show answer" : "Hide answer"; }
  });
  if (id) gen();
};

views.guide = async (id) => {
  await ensureExperiments().catch(() => {});
  view.innerHTML = `
    <div class="page-head"><h1>🧭 Step-by-step Guide</h1><p>Read each step, do it, then move on.</p></div>
    <div class="card"><label for="gSel">Experiment</label><select id="gSel">${expOptions(id || "")}</select></div>
    <div id="gOut"></div>`;
  let step = 0;
  const show = async () => {
    const eid = $("#gSel").value, out = $("#gOut");
    if (!eid) { out.innerHTML = empty("Choose an experiment to start."); return; }
    out.innerHTML = loading();
    try {
      const r = await API.guide(eid, step);
      const d = r.data;
      directTool("experiment_guide", `show step ${d.step + 1}`, r.status);
      out.innerHTML = `
        <div class="card">
          <div class="row"><strong>Step ${d.step + 1} of ${d.total}</strong><span class="muted small">${esc(d.experiment.title)}</span></div>
          <div class="progress"><div style="width:${((d.step + 1) / d.total) * 100}%"></div></div>
          <p class="step-card">${esc(d.instruction)}</p>
          <div class="row">
            <button class="btn secondary" id="gPrev" ${d.has_prev ? "" : "disabled"}>← Previous</button>
            ${d.has_next ? `<button class="btn" id="gNext">I've done this – Next →</button>` : `<span class="tag ok">🎉 All steps complete</span> <a class="btn secondary" href="#/verify/${esc(eid)}">Verify my output</a>`}
          </div>
        </div>
        <p><a href="#/experiment/${esc(eid)}">View full experiment (program, algorithm, expected result)</a></p>`;
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
    <div class="page-head"><h1>📄 Lab Manual</h1><p>Upload your college's MPMC lab manual (PDF, max 4 MB, text-based) and search it. The file is read once and <strong>not stored on the server</strong>; the extracted text stays in this browser tab.</p></div>
    <div class="card">
      <div id="mStatus">${m ? `<div class="state success">📄 <strong>${esc(m.filename)}</strong> – ${m.pages} pages, ${m.chunks.length} text sections loaded. The AI Assistant also uses it.</div>` : empty("No manual uploaded. Searches use the built-in knowledge base only.")}</div>
      <div class="row" style="margin-top:12px">
        <input type="file" id="mFile" accept="application/pdf,.pdf" aria-label="Choose PDF">
        <button class="btn" id="mUpload">Upload &amp; extract</button>
        ${m ? `<button class="btn danger" id="mClear">Remove manual</button>` : ""}
      </div>
    </div>
    <div class="card">
      <label for="mQ">Ask a question about the manual</label>
      <div class="row"><input type="text" id="mQ" class="grow" placeholder="e.g. What is the aim of the sorting experiment?" maxlength="500"><button class="btn" id="mAsk">Search</button></div>
    </div>
    <div id="mOut"></div>`;
  $("#mUpload").addEventListener("click", async () => {
    const f = $("#mFile").files[0];
    const status = $("#mStatus");
    if (!f) { status.innerHTML = errorBox("Choose a PDF file first."); return; }
    if (!f.name.toLowerCase().endsWith(".pdf")) { status.innerHTML = errorBox("Only PDF files are allowed."); return; }
    if (f.size > 4 * 1024 * 1024) { status.innerHTML = errorBox("File is larger than 4 MB. Split the PDF or compress it."); return; }
    status.innerHTML = loading("Extracting text…");
    try {
      const r = await API.uploadManual(f);
      saveManual({ filename: r.filename, pages: r.pages, chunks: r.chunks });
      toast(r.truncated ? "Manual loaded (very long – only the first part was indexed)." : "Manual loaded.");
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
          { phase: "select", tool: "manual_qa", status: "ok", detail: "Selected by you on this page: search the manual" },
          { phase: "execute", tool: "manual_qa", status: r.status, detail: `Backend ran manual_qa → status '${r.status}'.` },
          { phase: "respond", tool: "manual_qa", status: "ok", detail: r.mode === "groq" ? "Groq wrote the answer from the retrieved text." : "Showing retrieved text directly." },
        ],
      });
      const tag = `<span class="tag ${r.mode === "groq" ? "ok" : "warn"}">${r.mode === "groq" ? "Groq AI answer" : "Search result"}</span>`;
      out.innerHTML = r.status === "ok" ? `<div class="card">${tag}${md(r.text)}</div>` : `<div class="state">${md(r.text)}</div>`;
    } catch (e) { out.innerHTML = errorBox(e.message); }
  };
  $("#mAsk").addEventListener("click", ask);
  $("#mQ").addEventListener("keydown", (ev) => { if (ev.key === "Enter") ask(); });
};

// ------------------------------------------------------------------ router & shell
async function router() {
  const parts = (location.hash.replace(/^#\/?/, "") || "home").split("/");
  const name = views[parts[0]] ? parts[0] : "home";
  document.querySelectorAll(".sidebar a").forEach((a) => a.classList.toggle("active", a.dataset.route === (name === "experiment" ? "library" : name)));
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

$("#menuBtn").addEventListener("click", () => { $("#sidebar").classList.toggle("open"); $("#backdrop").classList.toggle("show", $("#sidebar").classList.contains("open")); });
$("#activityBtn").addEventListener("click", () => { $("#activity").classList.add("open"); $("#backdrop").classList.add("show"); });
$("#activityClose").addEventListener("click", closePanels);
$("#backdrop").addEventListener("click", closePanels);
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest(".copy-btn");
  if (!b) return;
  try { await navigator.clipboard.writeText(b.nextElementSibling.textContent); toast("Copied!"); }
  catch (e) { toast("Copy not allowed in this browser."); }
});

API.health().then((h) => {
  const badge = $("#modeBadge");
  badge.textContent = h.mode === "groq" ? "Groq AI" : "Fallback mode";
  badge.className = `badge ${h.mode}`;
  badge.title = h.mode === "groq" ? `Model: ${h.model}` : "No GROQ_API_KEY set – rule-based answers";
}).catch(() => { $("#modeBadge").textContent = "Offline"; });

window.addEventListener("hashchange", router);
router();
