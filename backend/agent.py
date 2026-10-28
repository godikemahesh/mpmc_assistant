"""Agent orchestration: plan -> pick tool -> execute -> inspect -> respond.

Planning uses Groq (if GROQ_API_KEY is set) or a rule-based router (always available).
Tool arguments are always extracted by code, never invented by the LLM.
"""
import json
import logging
import re
import urllib.error
import urllib.request

import config
import knowledge as kb
from tools import TOOLS

log = logging.getLogger("agent")

TOOL_INFO = {
    "experiment_search": "Find an experiment by name/number/topic and show its aim, algorithm, procedure and result.",
    "manual_qa": "Answer a question using the uploaded lab manual and the built-in knowledge base.",
    "program_explainer": "Explain 8086 assembly code line by line (registers, operands, flags).",
    "output_verification": "Compare a student's observed output with the expected output of an experiment.",
    "error_diagnosis": "Diagnose an assembler error message, buggy program or wrong output and suggest fixes.",
    "viva_generator": "Generate viva questions and answers for an experiment.",
    "experiment_guide": "Guide the student through an experiment's procedure one step at a time.",
}
# if a tool gives nothing useful, which tool to try next
ALTERNATIVE = {"experiment_search": "manual_qa", "manual_qa": "experiment_search", "program_explainer": "error_diagnosis"}

ASM_LINE = re.compile(r"^\s*(\w+:\s*)?(MOV|ADD|ADC|SUB|SBB|MUL|IMUL|DIV|IDIV|INC|DEC|CMP|JMP|J[A-Z]{1,3}|LOOP\w*|LEA|XCHG|PUSH|POP|INT|"
                      r"HLT|AND|OR|XOR|NOT|NEG|SHL|SHR|SAL|SAR|ROL|ROR|RCL|RCR|REP\w*|MOVS[BW]|CLD|STD|OUT|IN|CALL|RET|TEST|CBW|CWD|DAA)\b"
                      r"|^\s*\.(MODEL|DATA|CODE|STACK)\b", re.I)


# ------------------------------------------------------------------ Groq client (stdlib only)

class LLMError(Exception):
    pass


def llm_available():
    return bool(config.GROQ_API_KEY)


def groq_chat(messages, json_mode=False, max_tokens=800):
    body = {"model": config.GROQ_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        config.GROQ_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json",
                 "User-Agent": "mpmc-lab-assistant/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=config.GROQ_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            pass
        raise LLMError(f"Groq HTTP {e.code}: {detail[:150]}") from None
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
        raise LLMError(f"Groq request failed: {type(e).__name__}") from None


# ------------------------------------------------------------------ helpers

def extract_code(text):
    fenced = re.search(r"```(?:asm|assembly|nasm|masm)?\s*\n?([\s\S]*?)```", text or "")
    if fenced:
        return fenced.group(1).strip()
    lines = [l for l in (text or "").splitlines() if ASM_LINE.match(l) or re.match(r"^\s*\w+\s+(DB|DW|EQU|PROC|ENDP)\b|^\s*END\b|^\s*\w+:\s*$", l, re.I)]
    if len(lines) >= 2:
        return "\n".join(lines)
    text = text or ""
    # "mov ax, bx" in any case (two operands), or an UPPERCASE mnemonic like "MUL BX" / "REP MOVSB"
    m = re.search(r"\b(MOV|ADD|ADC|SUB|SBB|CMP|LEA|XCHG|AND|OR|XOR|TEST|SHL|SHR|IN|OUT)\s+[\w@\[\]+]+\s*,\s*[\w@\[\]+]+", text, re.I) \
        or re.search(r"\b(REP[NEZ]*\s+(MOVS|CMPS|SCAS|STOS|LODS)[BW]|(MOVS|CMPS|SCAS|STOS|LODS)[BW]|CBW|CWD|CLD|STD|HLT|XLAT|DAA)\b", text) \
        or re.search(r"\b(MUL|IMUL|DIV|IDIV|INC|DEC|NEG|NOT|PUSH|POP|INT|LOOP|JMP|J[A-Z]{1,3})\s+(\[[\w+]+\]|[A-D][XLH]|[SD]I|[BS]P|[0-9][0-9A-F]*H?)\b", text)
    return m.group(0) if m else ""


def route(message, experiment_id=None, has_manual=False):
    """Rule-based planner. Returns (tool, reason)."""
    t = message.lower()
    code = extract_code(message)
    has_error_words = re.search(r"\b(error|errors|not working|doesn'?t work|wrong|problem|issue|fix|debug|overflow|illegal|undefined|mismatch|fails?|hang)", t)
    if re.search(r"\b(verify|verification|check (my|the) (output|result))\b", t) or \
            (re.search(r"\b(observed|i got|my output|my result)\b", t) and not has_error_words):
        return "output_verification", "The message asks to check an observed output against the expected result."
    if has_error_words:
        return "error_diagnosis", "The message mentions an error or something not working."
    if re.search(r"\bviva\b|interview questions|practice questions|quiz", t):
        return "viva_generator", "The message asks for viva/practice questions."
    if re.search(r"step[- ]by[- ]step|guide me|walk me through|how (do|to|can) i (perform|do|conduct|start)|next step", t):
        return "experiment_guide", "The message asks to be guided through an experiment."
    if code and (len(code.splitlines()) >= 2 or re.search(r"\b(explain|meaning|what does|line by line)\b", t)):
        return "program_explainer", "The message contains 8086 assembly code to explain."
    if has_manual and re.search(r"\b(manual|according to|as per|pdf|document|uploaded|summar\w*)\b", t):
        return "manual_qa", "The question refers to the uploaded lab manual."
    if kb.find_by_number(message) or re.search(r"\b(aim|algorithm|procedure|apparatus|requirements?|expected (output|result)|experiment|program for|show)\b", t):
        if kb.detect_experiment(message) or experiment_id:
            return "experiment_search", "The message asks about a specific experiment's details."
    if code:
        return "program_explainer", "The message contains an 8086 instruction."
    if kb.detect_experiment(message) and len(t.split()) <= 6 and not re.search(r"\b(what|why|how|difference|define|meaning)\b", t):
        return "experiment_search", "The message names an experiment topic."
    return "manual_qa", "General question – searching the manual and knowledge base."


def llm_plan(message, experiment_id, has_manual):
    tools = "\n".join(f"- {k}: {v}" for k, v in TOOL_INFO.items())
    exps = ", ".join(f"{e['id']} ({e['title']})" for e in kb.EXPERIMENTS)
    sys = ("You are the planner of an 8086 MPMC lab assistant. Choose exactly ONE tool for the student's message.\n"
           f"Tools:\n{tools}\nExperiment ids: {exps}\n"
           f"A lab manual PDF is {'uploaded' if has_manual else 'NOT uploaded'}. Currently selected experiment: {experiment_id or 'none'}.\n"
           'Reply ONLY with JSON: {"tool": "<tool name>", "experiment_id": "<id or null>", "reason": "<one short sentence>"}')
    raw = groq_chat([{"role": "system", "content": sys}, {"role": "user", "content": message}], json_mode=True, max_tokens=150)
    plan = json.loads(raw)
    tool = plan.get("tool")
    if tool not in TOOLS:
        raise LLMError(f"Planner chose unknown tool {tool!r}")
    exp_id = plan.get("experiment_id")
    return tool, str(plan.get("reason") or "Chosen by the AI planner.")[:200], exp_id if exp_id in kb.BY_ID else None


def build_args(tool, message, experiment_id, manual_chunks):
    exp = kb.get_experiment(experiment_id) if experiment_id else kb.detect_experiment(message)
    exp_id = exp["id"] if exp else None
    code = extract_code(message)
    args = {"query": message, "experiment_id": exp_id, "manual_chunks": manual_chunks}
    if tool == "program_explainer":
        args["code"] = code or message
    if tool == "error_diagnosis":
        args["code"] = code
        args["error_message"] = message
    if tool == "experiment_search" and not kb.find_by_number(message) and exp_id is None:
        args["experiment_id"] = None
    return args


def inspect(result):
    """Is the tool result useful enough to answer with?"""
    return result.get("status") in ("ok", "needs_input", "not_supported")


def compose_with_llm(message, tool, result):
    sys = ("You are a friendly 8086 MPMC lab assistant for beginner engineering students. "
           "Answer using ONLY the TOOL RESULT below. Keep code, numbers and hex values exactly as given. "
           "Never claim a program was executed. Use short markdown (headings, bullet lists, `code`). "
           "If the tool result is an overview of an uploaded document, summarise what that document actually contains; "
           "if it is not an MPMC lab manual (e.g. a resume or notes), say what it appears to be and do NOT invent lab content. "
           "If the tool result says information is not available and the question is a general 8086/MPMC concept, say so first, "
           "then you may add a brief general explanation starting with '⚠️ Not from the manual – general explanation:'. "
           "Never invent experiments, page numbers or manual content.")
    payload = f"STUDENT QUESTION:\n{message}\n\nTOOL USED: {tool}\nTOOL RESULT:\n{result['text'][:6000]}"
    return groq_chat([{"role": "system", "content": sys}, {"role": "user", "content": payload}], max_tokens=900)


# ------------------------------------------------------------------ main loop

def run(message, experiment_id=None, manual_chunks=None):
    message = (message or "").strip()
    has_manual = bool(manual_chunks)
    steps, mode = [], "fallback"
    tool = reason = None

    if llm_available():
        try:
            tool, reason, llm_exp = llm_plan(message, experiment_id, has_manual)
            experiment_id = experiment_id or llm_exp
            mode = "groq"
            steps.append({"phase": "plan", "tool": tool, "status": "ok", "detail": f"AI planner (Groq): {reason}"})
        except (LLMError, ValueError) as e:
            log.warning("LLM planning failed: %s", e)
            steps.append({"phase": "plan", "tool": None, "status": "warning", "detail": f"AI planner unavailable ({e}); using rule-based router."})
    if not tool:
        tool, reason = route(message, experiment_id, has_manual)
        steps.append({"phase": "plan", "tool": tool, "status": "ok", "detail": f"Rule-based router: {reason}"})

    tried, result, first = [], None, None
    for _ in range(config.MAX_TOOL_CALLS):
        args = build_args(tool, message, experiment_id, manual_chunks)
        try:
            result = TOOLS[tool](**args)
        except Exception:  # a tool bug must not crash the request
            log.exception("Tool %s failed", tool)
            result = {"status": "error", "text": f"The {tool} tool failed unexpectedly.", "data": {}}
        tried.append(tool)
        first = first or (tool, result)
        steps.append({"phase": "execute", "tool": tool, "status": result["status"],
                      "detail": f"Executed {tool} → status '{result['status']}'."})
        if inspect(result):
            steps.append({"phase": "check", "tool": tool, "status": "ok", "detail": "Result is usable."})
            break
        nxt = ALTERNATIVE.get(tool)
        if not nxt or nxt in tried:
            steps.append({"phase": "check", "tool": tool, "status": "warning", "detail": "No useful result and no other suitable tool."})
            break
        steps.append({"phase": "check", "tool": tool, "status": "retry", "detail": f"No useful result; trying {nxt}."})
        tool = nxt
    else:
        steps.append({"phase": "check", "tool": tool, "status": "warning", "detail": f"Stopped after {config.MAX_TOOL_CALLS} tool calls (safety limit)."})
    if not inspect(result):  # nothing useful anywhere: answer with the originally planned tool's message
        tool, result = first

    answer = result["text"]
    if mode == "groq":
        try:
            answer = compose_with_llm(message, tool, result)
            steps.append({"phase": "respond", "tool": tool, "status": "ok", "detail": "Groq wrote the answer from the tool result."})
        except LLMError as e:
            log.warning("LLM compose failed: %s", e)
            steps.append({"phase": "respond", "tool": tool, "status": "warning", "detail": f"Groq unavailable ({e}); showing the tool result directly."})
    else:
        steps.append({"phase": "respond", "tool": tool, "status": "ok", "detail": "Answer built directly from the tool result (fallback mode)."})

    return {"answer": answer, "tool": tool, "reason": reason, "mode": mode, "steps": steps,
            "tool_calls": len(tried), "status": result["status"], "data": _safe_data(result.get("data", {}))}


def _safe_data(data):
    return {k: v for k, v in data.items() if k != "lines"} if isinstance(data, dict) else {}
