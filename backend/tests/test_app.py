"""Run from the backend folder:  python -m pytest -q"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GROQ_API_KEY"] = ""  # tests always run in fallback mode (no network)

import agent  # noqa: E402
import config  # noqa: E402
import knowledge as kb  # noqa: E402
import tools  # noqa: E402
from app import app  # noqa: E402

config.GROQ_API_KEY = ""


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------- knowledge base

def test_knowledge_base_loads_and_ids_unique():
    assert len(kb.EXPERIMENTS) >= 9
    assert len({e["id"] for e in kb.EXPERIMENTS}) == len(kb.EXPERIMENTS)


@pytest.mark.parametrize("query,expected", [
    ("sorting", "sort_asc"), ("largest number", "largest"), ("block transfer", "block_transfer"),
    ("experiment 3", "mul16"), ("exp 9", "block_transfer"), ("8255", "ppi8255"), ("carry", "add16"),
])
def test_experiment_search(query, expected):
    assert kb.search_experiments(query)[0]["id"] == expected


def test_topic_filter():
    res = kb.search_experiments("", "Arrays")
    assert res and all(e["topic"] == "Arrays" for e in res)


def test_sample_programs_pass_static_checks():
    for e in kb.EXPERIMENTS:
        assert tools.lint_program(e["program"]["code"]) == [], e["id"]


# ---------------------------------------------------------------- agent tool selection

@pytest.mark.parametrize("message,tool", [
    ("Show me experiment 7", "experiment_search"),
    ("What is the aim of block transfer?", "experiment_search"),
    ("algorithm for largest number", "experiment_search"),
    ("Explain MUL BX", "program_explainer"),
    ("MOV AX, @DATA\nMOV DS, AX\nADD AX, BX", "program_explainer"),
    ("what does REP MOVSB do", "program_explainer"),
    ("I got divide overflow error", "error_diagnosis"),
    ("my program gives wrong output for smallest number", "error_diagnosis"),
    ("verify my output for largest number", "output_verification"),
    ("viva questions for sorting", "viva_generator"),
    ("guide me step by step through addition", "experiment_guide"),
    ("What is the difference between JA and JG?", "manual_qa"),
    ("what is the zero flag", "manual_qa"),
])
def test_router_selects_tool(message, tool):
    assert agent.route(message)[0] == tool


def test_agent_runs_in_fallback_mode_with_steps():
    r = agent.run("viva questions for sorting")
    assert r["mode"] == "fallback" and r["tool"] == "viva_generator" and r["status"] == "ok"
    assert [s["phase"] for s in r["steps"]][:2] == ["plan", "execute"]
    assert r["tool_calls"] <= config.MAX_TOOL_CALLS


def test_agent_falls_back_to_other_tool_and_respects_limit():
    r = agent.run("what is a quantum flux capacitor")
    assert r["tool_calls"] == 2 and r["status"] == "not_found"
    assert "not available" in r["answer"]


def test_llm_planner_failure_falls_back(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-key")

    def boom(*a, **k):
        raise agent.LLMError("offline")
    monkeypatch.setattr(agent, "groq_chat", boom)
    r = agent.run("show me experiment 1")
    assert r["mode"] == "fallback" and r["tool"] == "experiment_search"
    assert r["steps"][0]["status"] == "warning"


def test_llm_plan_unknown_tool_rejected(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "fake-key")
    monkeypatch.setattr(agent, "groq_chat", lambda *a, **k: '{"tool": "rm_rf", "reason": "x"}')
    r = agent.run("show me experiment 1")
    assert r["tool"] == "experiment_search" and r["mode"] == "fallback"


# ---------------------------------------------------------------- tools

def test_manual_qa_uses_uploaded_chunks():
    chunks = [{"page": 4, "text": "The stepper motor experiment uses port B of the 8255 to drive four coils."}]
    r = tools.manual_qa(query="which port drives the stepper motor coils", manual_chunks=chunks)
    assert r["status"] == "ok" and "page 4" in r["data"]["sources"][0]["source"]


def test_manual_qa_reports_missing_information():
    r = tools.manual_qa(query="quantum flux capacitor calibration")
    assert r["status"] == "not_found" and "not available" in r["text"]


def test_program_explainer_line_by_line():
    r = tools.program_explainer(code="MOV AX, 1234h\nMUL BX\nREP MOVSB")
    lines = r["data"]["lines"]
    assert r["status"] == "ok" and len(lines) == 3 and r["data"]["executed"] is False
    assert "DX:AX" in lines[1]["explanation"]
    assert "AX" in r["data"]["registers_modified"]


def test_lint_detects_common_mistakes():
    code = ".DATA\nA1 DW 1\nB1 DW 2\n.CODE\nMOV DS, @DATA\nMOV AL, BX\nMOV A1, B1\nMUL 05h\nMOV AX, FFFFh\nLOOP X\nMOVE AX, BX"
    text = " ".join(i["issue"] for i in tools.lint_program(code))
    for needle in ["immediate value directly into DS", "size mismatch", "Memory-to-memory", "MUL cannot",
                   "starts with a letter", "CX was not loaded", "'MOVE'", "No program termination"]:
        assert needle in text, needle


@pytest.mark.parametrize("exp_id,inputs,observed,verdict", [
    ("add16", {"num1": "1234", "num2": "5678"}, {"result": "68ACh", "carry": "0"}, "match"),
    ("add16", {"num1": "FFFF", "num2": "0001"}, {"result": "0000", "carry": "1"}, "match"),
    ("add16", {"num1": "1234", "num2": "5678"}, {"result": "AC68", "carry": "0"}, "mismatch"),
    ("sub16", {"num1": "5678", "num2": "1234"}, {"result": "4444", "borrow": "0"}, "match"),
    ("mul16", {"num1": "1234", "num2": "5678"}, {"dx": "0626", "ax": "0060"}, "match"),
    ("div16", {"dividend": "0064", "divisor": "07"}, {"quotient": "0E", "remainder": "02"}, "match"),
    ("largest", {"array": "12, 45, 07, 89, 34"}, {"largest": "89"}, "match"),
    ("largest", {"array": "12, 45, 07, 89, 34"}, {"largest": "45"}, "mismatch"),
    ("smallest", {"array": "12 45 07 89 34"}, {"smallest": "07h"}, "match"),
    ("sort_asc", {"array": "34,12,89,07,45"}, {"sorted": "07,12,34,45,89"}, "match"),
    ("sort_asc", {"array": "34,12,89,07,45"}, {"sorted": "89,45,34,12,07"}, "mismatch"),
    ("search", {"array": "12,45,07,89,34", "key": "89"}, {"found": "1", "position": "04"}, "match"),
    ("block_transfer", {"array": "11,22,33"}, {"destination": "11,22,33"}, "match"),
])
def test_output_verification(exp_id, inputs, observed, verdict):
    r = tools.output_verification(experiment_id=exp_id, inputs=inputs, observed=observed)
    assert r["status"] == "ok" and r["data"]["verdict"] == verdict and r["data"]["verified"] is True


def test_verification_explains_mismatches():
    hints = " ".join(tools.output_verification("add16", {"num1": "1234", "num2": "5678"}, {"result": "AC68", "carry": "0"})["data"]["hints"])
    assert "little-endian" in hints
    hints = " ".join(tools.output_verification("largest", {"array": "12,45,07,89,34"}, {"largest": "45"})["data"]["hints"])
    assert "SIGNED" in hints
    hints = " ".join(tools.output_verification("sort_asc", {"array": "34,12,89,07,45"}, {"sorted": "89,45,34,12,07"})["data"]["hints"])
    assert "DESCENDING" in hints


def test_verification_divide_error_and_unsupported():
    r = tools.output_verification("div16", {"dividend": "FFFF", "divisor": "01"}, {"quotient": "FF", "remainder": "00"})
    assert r["data"]["verdict"] == "error_expected"
    r = tools.output_verification("ppi8255", {}, {})
    assert r["status"] == "not_supported" and r["data"]["verified"] is False


def test_verification_rejects_bad_hex():
    r = tools.output_verification("add16", {"num1": "XYZ", "num2": "1"}, {"result": "1", "carry": "0"})
    assert r["status"] == "error"
    r = tools.output_verification("add16", {"num1": "12345", "num2": "1"}, {"result": "1", "carry": "0"})
    assert r["status"] == "error"


def test_error_diagnosis():
    r = tools.error_diagnosis(error_message="error A2070: invalid instruction operands", code="MOV VAR1, VAR2")
    assert r["status"] == "ok" and "Invalid operand combination" in r["text"]
    r = tools.error_diagnosis(error_message="Divide overflow")
    assert "DX" in r["text"]


def test_viva_levels():
    r = tools.viva_generator(experiment_id="sort_asc", level="all", count=6)
    assert r["status"] == "ok" and {q["level"] for q in r["data"]["questions"]} == {"easy", "medium", "hard"}
    r = tools.viva_generator(experiment_id="sort_asc", level="hard", count=10)
    assert all(q["level"] == "hard" for q in r["data"]["questions"])


def test_guide_steps():
    r = tools.experiment_guide(experiment_id="add16", step=0)
    assert r["data"]["step"] == 0 and r["data"]["has_next"] and not r["data"]["has_prev"]
    last = r["data"]["total"] - 1
    assert tools.experiment_guide(experiment_id="add16", step=last)["data"]["has_next"] is False
    assert tools.experiment_guide(experiment_id="add16", step=99)["status"] == "error"


# ---------------------------------------------------------------- API

def test_homepage_and_health(client):
    assert b"MPMC Lab Assistant" in client.get("/").data
    h = client.get("/api/health").get_json()
    assert h["status"] == "ok" and h["mode"] == "fallback"


def test_api_experiments(client):
    data = client.get("/api/experiments?q=sorting").get_json()
    assert data["experiments"][0]["id"] == "sort_asc"
    assert client.get("/api/experiments/add16").get_json()["number"] == 1
    assert client.get("/api/experiments/nope").status_code == 404


def test_api_chat(client):
    r = client.post("/api/chat", json={"message": "viva questions for block transfer"})
    assert r.status_code == 200 and r.get_json()["tool"] == "viva_generator"


@pytest.mark.parametrize("path,payload", [
    ("/api/chat", {}), ("/api/chat", {"message": "   "}), ("/api/chat", {"message": "x" * 5000}),
    ("/api/chat", {"message": "hi", "experiment_id": "nope"}), ("/api/explain", {"code": ""}),
    ("/api/verify", {"experiment_id": "add16", "inputs": "bad", "observed": {}}),
    ("/api/verify", {"experiment_id": "add16", "inputs": {"num1": "zz", "num2": "1"}, "observed": {"result": "1", "carry": "0"}}),
    ("/api/diagnose", {}), ("/api/manual/search", {"question": ""}),
])
def test_api_rejects_invalid_input(client, path, payload):
    r = client.post(path, json=payload)
    assert r.status_code in (400, 404) and "error" in r.get_json()


def test_api_non_json_body(client):
    r = client.post("/api/chat", data="hello", content_type="text/plain")
    assert r.status_code == 400


def test_api_verify_and_viva_and_guide(client):
    r = client.post("/api/verify", json={"experiment_id": "add16", "inputs": {"num1": "1234", "num2": "5678"},
                                         "observed": {"result": "68AC", "carry": "0"}})
    assert r.get_json()["data"]["verdict"] == "match"
    assert client.get("/api/viva/add16?level=easy").status_code == 200
    assert client.get("/api/viva/add16?level=extreme").status_code == 400
    assert client.get("/api/guide/add16/1").get_json()["data"]["step"] == 1
    assert client.get("/api/guide/add16/50").status_code == 400
    assert client.get("/api/unknown").status_code == 404


def _make_pdf(text):
    """Build a minimal valid one-page PDF containing `text` (no extra dependencies)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


def test_api_manual_upload_and_search(client):
    pdf = _make_pdf("Experiment 12 traffic light controller uses port A of 8255")
    r = client.post("/api/manual/upload", data={"file": (io.BytesIO(pdf), "manual.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    chunks = r.get_json()["chunks"]
    assert "traffic light" in chunks[0]["text"]
    s = client.post("/api/manual/search", json={"question": "traffic light controller port", "manual_chunks": chunks}).get_json()
    assert s["status"] == "ok" and "Uploaded manual" in s["data"]["sources"][0]["source"]


def test_api_manual_upload_rejects_bad_files(client):
    r = client.post("/api/manual/upload", data={"file": (io.BytesIO(b"hello"), "notes.txt")}, content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post("/api/manual/upload", data={"file": (io.BytesIO(b"not a pdf"), "fake.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 400
    big = b"%PDF" + b"0" * (config.MAX_UPLOAD_MB * 1024 * 1024 + 10)
    r = client.post("/api/manual/upload", data={"file": (io.BytesIO(big), "big.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 413


# ---------------------------------------------------------------- manual overview & custom verification

def test_manual_overview_request_returns_first_sections():
    chunks = [{"page": 1, "text": "Mahesh Kumar. Skills: Python, embedded systems."}, {"page": 2, "text": "Projects: line follower robot."}]
    r = tools.manual_qa(query="explain the mahesh lab manual", manual_chunks=chunks)
    assert r["status"] == "ok" and r["data"]["overview"] is True and "Page 2" in r["text"]


def test_manual_words_do_not_block_matches():
    chunks = [{"page": 3, "text": "The traffic light experiment uses port A."}]
    r = tools.manual_qa(query="in the lab manual which port is used for traffic light", manual_chunks=chunks)
    assert r["status"] == "ok" and "page 3" in r["data"]["sources"][0]["source"]


def test_custom_verification():
    r = tools.output_verification("custom", {"expected": "07, 12, 34"}, {"observed": "07 12 34"})
    assert r["data"]["verdict"] == "match" and r["data"]["verified"] is False
    r = tools.output_verification("custom", {"expected": "68AC"}, {"observed": "AC68"})
    assert r["data"]["verdict"] == "mismatch" and "little-endian" in " ".join(r["data"]["hints"])
    r = tools.output_verification("custom", {"expected": "1,2,3"}, {"observed": "3,2,1"})
    assert "reverse order" in " ".join(r["data"]["hints"])
    assert tools.output_verification("custom", {"expected": "zz"}, {"observed": "1"})["status"] == "error"


def test_api_custom_verify(client):
    r = client.post("/api/verify", json={"experiment_id": "custom", "inputs": {"expected": "0E 02"}, "observed": {"observed": "0E 02"}})
    assert r.status_code == 200 and r.get_json()["data"]["verdict"] == "match"
