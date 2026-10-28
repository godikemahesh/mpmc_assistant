# Test Report

Environment: Windows 10, Python 3.10.11, Flask 3.0.3. Date: 2026-10-28.

## ✅ Tests actually executed

### Automated: `python -m pytest -q` (in `backend/`) → **66 passed**
| Area | What is checked |
|---|---|
| Knowledge base | Loads, unique ids, search by name/number/topic, topic filter, all sample programs pass the static checker |
| Agent tool selection | 13 example requests are each routed to the correct tool |
| Agent loop | Fallback mode works with no key; switches to another tool when the first finds nothing; stays within the 3-call limit |
| Groq failure handling | Simulated Groq outage → falls back to the rule router; an invalid tool name from the LLM is rejected |
| Manual Q&A | Finds text in uploaded manual chunks (with page number); says "not available" when nothing matches |
| Program explainer | Line-by-line output, MUL → DX:AX, registers modified, `executed = False` |
| Static checks | Detects immediate→DS, size mismatch, memory-to-memory, MUL immediate, `FFFFh` without a leading 0, LOOP without CX, misspelled instruction, missing exit |
| Output verification | 13 match/mismatch cases across 9 experiments; mismatch hints (little-endian, signed jumps, descending sort); divide error; 8255 marked unsupported; bad hex / too-large values rejected |
| Error diagnosis, viva, guide | Error patterns matched; viva levels filter; guide step bounds |
| API | Homepage, health, experiments, chat, verify, viva, guide, unknown endpoint 404, 9 invalid-input cases → 400/404, non-JSON body, PDF upload + search, non-PDF / fake PDF rejected, file > 4 MB → 413 |

### Manual checks performed against the running server (`python app.py`)
- `GET /` and every CSS/JS file → 200; unknown page paths fall back to `index.html`.
- `/api/health`, `/api/experiments?topic=Arrays`, `/api/verify` (mul16 mismatch hint), `/api/diagnose` (missing DX before 16-bit DIV), `/api/chat` → all correct.
- A real PDF was uploaded via `/api/manual/upload`, then a chat question about it → the agent chose `manual_qa` and cited "Uploaded manual – page 1".
- **Real Groq request:** while `.env` still held the placeholder key, Groq answered `HTTP 401 Invalid API Key`. The agent logged it in the activity steps and finished in fallback mode. The placeholder is now treated as "no key".
- `api/index.py` (Vercel entry) imports the app from the repo root and serves `/api/health`.
- `node --check` passes for `frontend/js/app.js` and `api.js`.
- `git add --dry-run` confirms `.env` and `.venv/` are not committed.

## ⏳ Still to be tested manually (could not be done here)
| Test | How |
|---|---|
| Visual check in a browser (desktop + phone width) | Open http://127.0.0.1:5000, click every menu item; resize the window or use DevTools device mode |
| Groq AI mode with a **valid** key | Put your key in `backend/.env`, restart, check the badge shows "Groq AI" and the Agent Activity panel shows "AI planner (Groq)" |
| `gunicorn` start command | Runs on Linux only (Render); check Render's deploy logs |
| GitHub push | Follow README Stage 6a |
| Render deployment | Follow README Stage 6b; open `/api/health` |
| Vercel deployment | Follow README Stage 6c; open `/api/health` |
| Programs on a real assembler | Assemble the sample programs in your lab's MASM/TASM or emu8086 |
