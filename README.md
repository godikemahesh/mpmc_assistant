# ⚡ Agentic AI-Based MPMC Lab Manual Assistant

An AI assistant that helps students understand, perform and verify **8086 Microprocessors & Microcontrollers (MPMC)** lab experiments.

It is an **agent**, not a plain chatbot. For each request it:
1. **Plans:** Groq AI (or a rule-based router when no key is set) decides which tool fits the request.
2. **Executes:** it runs one of 7 real Python tools.
3. **Checks:** if the result is empty, it tries another suitable tool (at most **3 tool calls** per request).
4. **Responds:** it builds the answer only from the tool result. The **Agent Activity** panel shows each step.

| # | Tool | What it does |
|---|------|--------------|
| 1 | Experiment Search | Finds an experiment by name, number or topic and returns its aim, requirements, algorithm, procedure and expected result |
| 2 | Manual Q&A | Searches your uploaded PDF manual and the built-in knowledge base, names the source, and says when the information is not available |
| 3 | Program Explainer | Explains 8086 code line by line: registers, operands, flags and common mistakes. This is static analysis; the code is **never executed** |
| 4 | Output Verification | Compares your observed output with values from a Python reference implementation of the algorithm, and explains mismatches |
| 5 | Error Diagnosis | Matches error messages, checks your code and suggests fixes |
| 6 | Viva Generator | Gives easy, medium and challenging questions with answers |
| 7 | Experiment Guide | Walks you through the procedure one step at a time |

**Tech:** HTML/CSS/JavaScript frontend (no build step) · Python Flask backend · Groq API (optional, free tier) · pypdf.
The app works fully **without an API key** (fallback mode).

---

## 📁 Project structure

```
agentic-ai-mpmc-lab-assistant/
├── backend/                  ← Python / Flask API
│   ├── app.py                ← Flask app + all /api routes (also serves the frontend)
│   ├── agent.py              ← Agent: planner, Groq client, tool loop, safety limit
│   ├── tools.py              ← The 7 tools
│   ├── knowledge.py          ← Loads experiment data, search, PDF text extraction
│   ├── config.py             ← Settings read from environment variables
│   ├── data/
│   │   ├── experiments.json  ← 10 experiments (aim, algorithm, program, viva…)
│   │   ├── errors.json       ← Common assembler/emulator errors and fixes
│   │   └── TEMPLATE_experiment.json ← Copy this to add your college's experiments
│   ├── tests/test_app.py     ← 66 automated tests
│   ├── requirements.txt      ← Production dependencies (used by Render)
│   ├── requirements-dev.txt  ← + pytest
│   └── .env.example          ← Placeholder settings (copy to .env)
├── frontend/                 ← Website (HTML/CSS/JS)
│   ├── index.html
│   ├── css/styles.css
│   └── js/config.js, api.js, app.js
├── api/index.py              ← Vercel entry point (loads backend/app.py)
├── vercel.json               ← Vercel settings
├── render.yaml               ← Render settings
├── requirements.txt          ← Dependencies for Vercel (root level)
├── .gitignore
├── README.md
└── TEST_REPORT.md
```

---

## 🧪 Experiments included

1. Addition of two 16-bit numbers · 2. Subtraction (with borrow) · 3. 16-bit multiplication · 4. 16/8 division · 5. Largest in array · 6. Smallest in array · 7. Ascending sort (bubble) · 8. Linear search · 9. Block data transfer · 10. 8255 PPI interfacing

**Assembler assumptions:** the programs use **MASM/TASM syntax** with `.MODEL SMALL` and also assemble in **emu8086**. They are **not** written for DOS `DEBUG`, NASM/GNU `as`, or a trainer kit's own monitor. On a trainer kit, replace `MOV AH,4Ch / INT 21h` with `HLT` (or your kit's return command). The 8255 experiment uses **example port addresses**; check your kit manual for the real ones. Real hardware output cannot be verified by software, so the app labels that experiment "manual estimate only".

### ➕ Adding experiments from your college manual
1. Open `backend/data/TEMPLATE_experiment.json`.
2. Copy the object inside `"experiment"` and paste it as a new item in the `"experiments"` list in `backend/data/experiments.json`. Put a comma between items.
3. Give it a unique `id` and `number`. Keep `"verify": null`. Automatic verification needs a reference function in `tools.py` → `REFERENCE`.
4. Restart the server and run the tests. The loader stops with a clear message if a required field is missing.

---

## 🖥️ Stage 1–5: Run on Windows (step by step)

### 0. Install once
- **Python 3.10 or newer**: https://www.python.org/downloads/ (tick **"Add python.exe to PATH"** during install).
- **Git**: https://git-scm.com/download/win
- **VS Code**: https://code.visualstudio.com/

### 1. Open the project
In VS Code: **File → Open Folder…** → choose the `mtmc_assistant` folder (the one with `backend` and `frontend` inside).
Then open a terminal: **Terminal → New Terminal**. It should be **PowerShell**.

### 2. Create the virtual environment and install packages
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```
✅ You should see `(.venv)` at the start of the prompt.
❌ If you see *"running scripts is disabled on this system"*, run this once, then activate again:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. (Optional) Add your free Groq API key
1. Create a free key at https://console.groq.com/keys
2. Copy the example file and edit it:
```powershell
Copy-Item .env.example .env
notepad .env
```
3. Replace `your_groq_api_key_here` with your key (it starts with `gsk_`), then save.

Without a key (or with the placeholder still in place), the app runs in **fallback mode**, and every feature still works.
🔒 `.env` is listed in `.gitignore`, so it is **never uploaded to GitHub**.

### 4. Run the tests
```powershell
python -m pytest -q
```
✅ Expected: `66 passed`.

### 5. Start the app
```powershell
python app.py
```
✅ Expected output includes `Mode: fallback (no GROQ_API_KEY)` (or `Groq AI`) and `Running on http://127.0.0.1:5000`.
Open **http://127.0.0.1:5000** in your browser. Press `Ctrl + C` in the terminal to stop the server.

Next time you only need:
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python app.py
```

### Try these in the AI Assistant
- `Show me experiment 7`
- `Explain MUL BX`
- `I got divide overflow error`
- `Viva questions for block transfer`
- `Guide me step by step through addition`
- `What is the difference between JA and JG?`

---

## 🐙 Stage 6a: Upload to GitHub

1. Sign in to https://github.com → **New repository** → name: `agentic-ai-mpmc-lab-assistant` → Public or Private → **do NOT** tick "Add README" → **Create repository**.
2. In VS Code's terminal, go to the **project root** (the folder that contains `backend` and `frontend`):
```powershell
cd C:\Users\USER\Downloads\mtmc_assistant
git init
git config user.name "Your Name"
git config user.email "you@example.com"
git add .
git status
```
3. **Safety check:** in the `git status` list, make sure **`.env` and `.venv` are NOT listed**. If `.env` appears, stop and check `.gitignore`.
4. Commit and push. Replace `YOUR_USERNAME` with your GitHub username:
```powershell
git commit -m "Initial commit: Agentic AI MPMC Lab Assistant"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/agentic-ai-mpmc-lab-assistant.git
git push -u origin main
```
A browser window opens for GitHub sign-in the first time. **Never type your API key or password into any file.**

Later updates:
```powershell
git add .
git commit -m "Describe your change"
git push
```

**🔒 Using GitHub safely**
- Secrets go only in `.env` (local) or in the Render/Vercel dashboard, never in code.
- If you ever push a key by mistake, **delete that key at console.groq.com right away** and create a new one. Deleting the file afterwards does not remove the key from Git history.
- Don't commit your college's PDF manual unless you have permission. `*.pdf` is ignored by default.

---

## 🚀 Stage 6b: Deploy on Render (free web service)

The `render.yaml` file already contains these settings: root folder `backend`, build `pip install -r requirements.txt`, start `gunicorn app:app --bind 0.0.0.0:$PORT`, and health check `/api/health`.

1. Sign in at https://render.com with GitHub.
2. Click **New → Blueprint** → choose your `agentic-ai-mpmc-lab-assistant` repo → **Apply**.
   *(Or: **New → Web Service** → pick the repo → Root Directory `backend` → Runtime Python → Build Command `pip install -r requirements.txt` → Start Command `gunicorn app:app --bind 0.0.0.0:$PORT` → Instance type Free.)*
3. When asked for **GROQ_API_KEY**, paste your key. You can also add it later under **Environment**. To run in fallback mode, leave it empty.
4. Wait for the build to finish. Logs: **your service → Logs**. Then open `https://<your-service>.onrender.com`.
5. Check `https://<your-service>.onrender.com/api/health`. It should return `"status": "ok"`.

**Render notes:** free services **sleep after inactivity**, so the first visit can take about 30–60 seconds. Free-tier limits and policies can change; check Render's pricing page. The app stores nothing on disk, so restarts and redeploys lose no data. An uploaded manual stays only in the user's browser tab.

---

## ▲ Stage 6c: Deploy on Vercel (alternative)

`vercel.json` serves `frontend/` as a static site and sends `/api/*` to the Flask function in `api/index.py`.

1. Sign in at https://vercel.com with GitHub → **Add New → Project** → import the repo.
2. Framework Preset: **Other**. Leave the root directory as the repository root. Don't change the build settings; `vercel.json` sets them.
3. **Environment Variables** → add `GROQ_API_KEY` (optional) → **Deploy**.
4. Open `https://<project>.vercel.app/api/health` to check the API.

**Vercel notes:** uploads must be **under 4 MB** (Vercel's request limit is 4.5 MB). Each request runs in a fresh serverless function, which is why the app keeps nothing on the server. Limits for the Hobby plan can change.

---

## ▲ Stage 6d: Frontend on Vercel + backend on Render (separate)

1. Deploy the backend on Render (Stage 6b) and copy its URL, e.g. `https://agentic-ai-mpmc-lab-assistant.onrender.com`.
2. On Vercel: **Add New → Project** → import the repo → set **Root Directory** to `frontend`. Framework Preset: **Other**. `frontend/vercel.json` runs `node build.js` and publishes `dist/`.
3. **Environment Variables** → add `BACKEND_URL` = your Render URL (no trailing `/`, no `/api`) → **Deploy**.
4. Back on Render → **Environment** → set `ALLOWED_ORIGINS` = your Vercel URL (e.g. `https://my-app.vercel.app`) → save. Render redeploys automatically.
5. Open the Vercel site. The badge at the top right should show **Groq AI** or **Rule-based**, not **Offline**.

If you change `BACKEND_URL` later, **redeploy** on Vercel, because the URL is written in at build time.
To test the build locally: `cd frontend`, `Copy-Item .env.example .env`, edit it, then run `node build.js` and check `dist/js/config.js`.

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognized | Reinstall Python with "Add to PATH" ticked, then reopen VS Code |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `ModuleNotFoundError: flask` | Activate the venv first (`(.venv)` must show), then `pip install -r requirements-dev.txt` |
| Page says "Backend not reachable" | Start `python app.py` inside `backend` and open http://127.0.0.1:5000 (not the HTML file directly) |
| Agent Activity says "Groq HTTP 401" | The API key is wrong. Fix it in `.env` or the dashboard; the app keeps working in fallback mode |
| "Groq HTTP 429" | Free-tier rate limit reached. Wait a minute; fallback answers are used meanwhile |
| Groq model error (model decommissioned) | Set `GROQ_MODEL` to a current model from https://console.groq.com/docs/models |
| PDF "No text found" | Scanned PDFs contain images, not text. Use a text-based PDF or run OCR first |
| Render build fails | Check **Logs**; make sure Root Directory is `backend` |
| Render: "Application exited early" / port error | The start command must bind to `0.0.0.0:$PORT` (already in `render.yaml`) |
| Vercel 404 on `/api/...` | Make sure `vercel.json`, `api/index.py` and the root `requirements.txt` were pushed |

---

## ⚠️ Honest limitations
- The assistant **does not run** your assembly code. Explanations come from static analysis, and verification compares your values against a Python reference implementation of each algorithm.
- Hardware interfacing results (8255) cannot be verified by software.
- Free hosting and free AI API quotas, sleep behaviour and model availability are set by Render, Vercel and Groq, and can change at any time.
