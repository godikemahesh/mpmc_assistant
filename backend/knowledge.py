"""Knowledge base: experiment data, keyword search and PDF manual text extraction."""
import io
import json
import math
import os
import re
from collections import Counter

import config

STOPWORDS = set("""a an the is are was were be to of in on for and or with by at as it this that
what which how why when where do does did i me my we you your can please tell about give show
explain from into using use used will should would could""".split())

REQUIRED_FIELDS = ["id", "number", "title", "topic", "aim", "algorithm", "procedure", "program",
                   "expected_output", "viva"]


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def _load_json(name):
    with open(os.path.join(config.DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _validate(experiments):
    seen = set()
    for exp in experiments:
        missing = [k for k in REQUIRED_FIELDS if k not in exp]
        if missing:
            raise ValueError(f"Experiment {exp.get('id', '?')} is missing fields: {missing}")
        if exp["id"] in seen:
            raise ValueError(f"Duplicate experiment id: {exp['id']}")
        seen.add(exp["id"])
    return experiments


_kb = _load_json("experiments.json")
EXPERIMENTS = _validate(_kb["experiments"])
ASSEMBLER_NOTE = _kb.get("assembler_note", "")
ERRORS = _load_json("errors.json")["errors"]
BY_ID = {e["id"]: e for e in EXPERIMENTS}


def summary(exp):
    return {k: exp[k] for k in ("id", "number", "title", "topic", "aim")}


def topics():
    return sorted({e["topic"] for e in EXPERIMENTS})


def get_experiment(exp_id):
    return BY_ID.get(exp_id)


def find_by_number(text):
    m = re.search(r"\b(?:exp(?:eriment)?|ex|program|lab)\s*(?:no\.?|number|#)?\s*(\d{1,2})\b", text or "", re.I)
    if m:
        n = int(m.group(1))
        for e in EXPERIMENTS:
            if e["number"] == n:
                return e
    return None


def search_experiments(query="", topic=""):
    """Rank experiments by keyword overlap. Empty query returns all (optionally filtered by topic)."""
    pool = [e for e in EXPERIMENTS if not topic or e["topic"].lower() == topic.lower()]
    if not (query or "").strip():
        return pool
    by_num = find_by_number(query)
    if by_num and by_num in pool:
        return [by_num]
    q = set(tokenize(query))
    scored = []
    for e in pool:
        title = set(tokenize(e["title"]))
        keys = set(tokenize(" ".join(e.get("keywords", []))))
        body = set(tokenize(e["aim"] + " " + e["topic"]))
        score = 3 * len(q & keys) + 2 * len(q & title) + len(q & body)
        if score:
            scored.append((score, e))
    scored.sort(key=lambda s: (-s[0], s[1]["number"]))
    return [e for _, e in scored]


def detect_experiment(text):
    """Best single experiment mentioned in free text, or None."""
    hit = find_by_number(text)
    if hit:
        return hit
    results = search_experiments(text)
    if not results:
        return None
    q = set(tokenize(text))
    top = results[0]
    # require at least one keyword/title match, not just generic words
    strong = set(tokenize(" ".join(top.get("keywords", [])) + " " + top["title"])) - {"array", "number", "numbers", "16", "bit"}
    return top if q & strong else None


# ---------- documents for retrieval (knowledge base + uploaded manual) ----------

def kb_documents():
    docs = []
    for e in EXPERIMENTS:
        src = f"Knowledge base – Exp {e['number']}: {e['title']}"
        docs.append({"source": src + " (Aim & Theory)", "text": f"{e['title']}. Aim: {e['aim']} Theory: {e.get('theory', '')}"})
        docs.append({"source": src + " (Algorithm)", "text": " ".join(e["algorithm"])})
        docs.append({"source": src + " (Procedure)", "text": " ".join(e["procedure"])})
        docs.append({"source": src + " (Expected result)", "text": f"Sample input: {e.get('sample_input', '')}. Expected output: {e['expected_output']}"})
        docs.append({"source": src + " (Common errors)", "text": " ".join(e.get("common_errors", []))})
        for level, qs in e["viva"].items():
            for qa in qs:
                docs.append({"source": src + f" (Viva – {level})", "text": f"{qa['q']} {qa['a']}"})
    return docs


_KB_DOCS = kb_documents()


def rank_documents(question, docs, top_k=3):
    """Simple TF-IDF scoring. Returns [(score, doc)] best first; pure Python, no heavy deps."""
    q = tokenize(question)
    if not q or not docs:
        return []
    doc_tokens = [Counter(tokenize(d["text"])) for d in docs]
    n = len(docs)
    df = Counter()
    for toks in doc_tokens:
        df.update(set(toks))
    results = []
    for d, toks in zip(docs, doc_tokens):
        if not toks:
            continue
        length = sum(toks.values())
        score = 0.0
        for w in set(q):
            if toks[w]:
                idf = math.log(1 + n / df[w])
                score += (1 + math.log(toks[w])) * idf
        score /= math.sqrt(length) ** 0.5  # mild length normalisation
        matched = sum(1 for w in set(q) if toks[w])
        if matched:
            results.append((round(score, 3), matched / len(set(q)), d))
    results.sort(key=lambda r: -r[0])
    return [(s, cov, d) for s, cov, d in results[:top_k]]


def search_all(question, manual_chunks=None, top_k=3):
    docs = list(_KB_DOCS)
    for c in manual_chunks or []:
        docs.append({"source": f"Uploaded manual – page {c.get('page', '?')}", "text": c.get("text", "")})
    return rank_documents(question, docs, top_k)


# ---------- PDF ----------

def extract_pdf_chunks(file_bytes, chunk_chars=900):
    """Extract text from a PDF (in memory, never saved) and split into page-tagged chunks."""
    from pypdf import PdfReader  # imported lazily to keep startup fast

    reader = PdfReader(io.BytesIO(file_bytes))
    chunks = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = re.sub(r"\s+", " ", page.extract_text() or "").strip()
        while text:
            if len(text) <= chunk_chars:
                piece, text = text, ""
            else:
                cut = text.rfind(". ", 0, chunk_chars)
                cut = cut + 1 if cut > chunk_chars // 2 else chunk_chars
                piece, text = text[:cut], text[cut:].strip()
            chunks.append({"page": page_no, "text": piece})
            if len(chunks) >= config.MAX_MANUAL_CHUNKS:
                return chunks, len(reader.pages), True
    return chunks, len(reader.pages), False
