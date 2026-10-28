// Small wrapper around fetch() that always returns JSON or throws a readable Error.
const API = (() => {
  const base = (window.APP_CONFIG && window.APP_CONFIG.API_BASE) || "";

  async function request(path, options = {}) {
    let res;
    try {
      res = await fetch(base + path, options);
    } catch (e) {
      throw new Error("Cannot reach the server. Is the backend running?");
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (!res.ok) {
      throw new Error((data && data.error) || `Server error (${res.status}).`);
    }
    if (data === null) throw new Error("The server returned an invalid response.");
    return data;
  }

  const post = (path, body) => request(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });

  return {
    health: () => request("/api/health"),
    experiments: (q = "", topic = "") => request(`/api/experiments?q=${encodeURIComponent(q)}&topic=${encodeURIComponent(topic)}`),
    experiment: (id) => request(`/api/experiments/${encodeURIComponent(id)}`),
    chat: (message, experiment_id, manual_chunks) => post("/api/chat", { message, experiment_id, manual_chunks }),
    explain: (code) => post("/api/explain", { code }),
    verify: (experiment_id, inputs, observed) => post("/api/verify", { experiment_id, inputs, observed }),
    diagnose: (error_message, code, experiment_id) => post("/api/diagnose", { error_message, code, experiment_id }),
    viva: (id, level, count) => request(`/api/viva/${encodeURIComponent(id)}?level=${level}&count=${count}`),
    guide: (id, step) => request(`/api/guide/${encodeURIComponent(id)}/${step}`),
    manualSearch: (question, manual_chunks) => post("/api/manual/search", { question, manual_chunks }),
    uploadManual: (file) => {
      const form = new FormData();
      form.append("file", file);
      return request("/api/manual/upload", { method: "POST", body: form });
    },
  };
})();
