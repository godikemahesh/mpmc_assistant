"""Flask REST API for the MPMC Lab Manual Assistant.

Run locally:  python app.py          (http://127.0.0.1:5000)
Production:   gunicorn app:app       (Render)   |   api/index.py (Vercel)
"""
import logging
import os

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import agent
import config
import knowledge as kb
import tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024
CORS(app, resources={r"/api/*": {"origins": "*"}})


class BadRequest(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequest("Request body must be JSON.")
    return data


def text_field(data, name, max_len, required=True):
    value = data.get(name, "")
    if not isinstance(value, str):
        raise BadRequest(f"'{name}' must be text.")
    value = value.strip()
    if required and not value:
        raise BadRequest(f"'{name}' is required.")
    if len(value) > max_len:
        raise BadRequest(f"'{name}' is too long (max {max_len} characters).")
    return value


def experiment_or_404(exp_id):
    exp = kb.get_experiment(exp_id)
    if not exp:
        raise BadRequest(f"Experiment '{exp_id}' not found.", 404)
    return exp


def manual_chunks_from(data):
    chunks = data.get("manual_chunks") or []
    if not isinstance(chunks, list) or len(chunks) > config.MAX_MANUAL_CHUNKS:
        raise BadRequest("'manual_chunks' must be a list (max %d items)." % config.MAX_MANUAL_CHUNKS)
    clean = []
    for c in chunks:
        if isinstance(c, dict) and isinstance(c.get("text"), str):
            clean.append({"page": c.get("page", "?"), "text": c["text"][:2000]})
    return clean


@app.errorhandler(BadRequest)
def handle_bad_request(e):
    return jsonify(error=e.message), e.code


@app.errorhandler(HTTPException)
def handle_http(e):
    if e.code == 413:
        return jsonify(error=f"File too large. Maximum size is {config.MAX_UPLOAD_MB} MB."), 413
    if request.path.startswith("/api/"):
        return jsonify(error=e.description or e.name), e.code
    return e


@app.errorhandler(Exception)
def handle_unexpected(e):
    log.exception("Unhandled error on %s", request.path)
    return jsonify(error="Internal server error. Check the server logs."), 500


# ------------------------------------------------------------------ API

@app.get("/api/health")
def health():
    return jsonify(status="ok", mode="groq" if agent.llm_available() else "fallback",
                   model=config.GROQ_MODEL if agent.llm_available() else None,
                   experiments=len(kb.EXPERIMENTS))


@app.get("/api/experiments")
def list_experiments():
    q = request.args.get("q", "")[:200]
    topic = request.args.get("topic", "")[:50]
    results = kb.search_experiments(q, topic)
    return jsonify(experiments=[dict(kb.summary(e), verifiable=bool(e.get("verify"))) for e in results],
                   topics=kb.topics(), assembler_note=kb.ASSEMBLER_NOTE)


@app.get("/api/experiments/<exp_id>")
def get_experiment(exp_id):
    return jsonify(experiment_or_404(exp_id))


@app.post("/api/chat")
def chat():
    data = body()
    message = text_field(data, "message", config.MAX_MESSAGE_CHARS)
    exp_id = data.get("experiment_id") or None
    if exp_id:
        experiment_or_404(exp_id)
    result = agent.run(message, exp_id, manual_chunks_from(data))
    log.info("chat tool=%s mode=%s status=%s calls=%s", result["tool"], result["mode"], result["status"], result["tool_calls"])
    return jsonify(result)


@app.post("/api/explain")
def explain():
    code = text_field(body(), "code", config.MAX_CODE_CHARS)
    return jsonify(tools.program_explainer(code=code))


@app.post("/api/verify")
def verify():
    data = body()
    exp_id = text_field(data, "experiment_id", 50)
    if exp_id != "custom":
        experiment_or_404(exp_id)
    inputs, observed = data.get("inputs"), data.get("observed")
    if not isinstance(inputs, dict) or not isinstance(observed, dict):
        raise BadRequest("'inputs' and 'observed' must be objects.")
    result = tools.output_verification(experiment_id=exp_id, inputs=inputs, observed=observed)
    if result["status"] == "error":
        raise BadRequest(result["text"])
    return jsonify(result)


@app.post("/api/diagnose")
def diagnose():
    data = body()
    msg = text_field(data, "error_message", config.MAX_MESSAGE_CHARS, required=False)
    code = text_field(data, "code", config.MAX_CODE_CHARS, required=False)
    exp_id = data.get("experiment_id") or None
    if exp_id:
        experiment_or_404(exp_id)
    if not msg and not code:
        raise BadRequest("Enter an error message, a program, or both.")
    return jsonify(tools.error_diagnosis(error_message=msg, code=code, experiment_id=exp_id))


@app.get("/api/viva/<exp_id>")
def viva(exp_id):
    experiment_or_404(exp_id)
    level = request.args.get("level", "all")
    if level not in ("all", "easy", "medium", "hard"):
        raise BadRequest("level must be all, easy, medium or hard.")
    try:
        count = int(request.args.get("count", 6))
    except ValueError:
        raise BadRequest("count must be a number.")
    return jsonify(tools.viva_generator(experiment_id=exp_id, level=level, count=count))


@app.get("/api/guide/<exp_id>/<int:step>")
def guide(exp_id, step):
    experiment_or_404(exp_id)
    result = tools.experiment_guide(experiment_id=exp_id, step=step)
    if result["status"] == "error":
        raise BadRequest(result["text"])
    return jsonify(result)


@app.post("/api/manual/upload")
def manual_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        raise BadRequest("Choose a PDF file to upload.")
    if not f.filename.lower().endswith(".pdf"):
        raise BadRequest("Only PDF files are allowed.")
    raw = f.read()
    if not raw.startswith(b"%PDF"):
        raise BadRequest("This file is not a valid PDF.")
    try:
        chunks, pages, truncated = kb.extract_pdf_chunks(raw)
    except Exception as e:
        log.warning("PDF extraction failed: %s", type(e).__name__)
        raise BadRequest("Could not read this PDF. It may be encrypted or damaged.")
    if not chunks:
        raise BadRequest("No text found in this PDF. Scanned (image-only) PDFs need OCR first.")
    log.info("Manual extracted: %d pages, %d chunks (not stored on server)", pages, len(chunks))
    return jsonify(filename=f.filename[:100], pages=pages, chunks=chunks, truncated=truncated)


@app.post("/api/manual/search")
def manual_search():
    data = body()
    q = text_field(data, "question", 500)
    result = tools.manual_qa(query=q, manual_chunks=manual_chunks_from(data))
    result["mode"] = "fallback"
    if agent.llm_available() and result["status"] in ("ok", "not_found"):
        try:
            result["text"] = agent.compose_with_llm(q, "manual_qa", result)
            result["mode"] = "groq"
        except agent.LLMError as e:
            log.warning("LLM compose failed on manual search: %s", e)
    return jsonify(result)


@app.route("/api/<path:_unused>", methods=["GET", "POST", "PUT", "DELETE"])
def api_not_found(_unused):
    raise BadRequest("API endpoint not found.", 404)


# ------------------------------------------------------------------ Frontend (local + Render)

@app.get("/")
def index():
    return send_from_directory(config.FRONTEND_DIR, "index.html")


@app.get("/<path:path>")
def frontend_files(path):
    if os.path.isfile(os.path.join(config.FRONTEND_DIR, path)):
        return send_from_directory(config.FRONTEND_DIR, path)
    return send_from_directory(config.FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    log.info("Mode: %s", "Groq AI" if agent.llm_available() else "fallback (no GROQ_API_KEY)")
    app.run(host="0.0.0.0" if os.getenv("PORT") else "127.0.0.1", port=port, debug=config.DEBUG)
