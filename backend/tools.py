"""The 7 agent tools. Each returns {"status", "text", "data"}.

status: "ok" | "not_found" | "needs_input" | "not_supported" | "error"
text:   beginner-friendly markdown answer used directly in fallback mode
data:   structured result for the UI / LLM
None of these tools execute assembly code. They analyse it or compare values.
"""
import random
import re

import knowledge as kb

REG8 = {"AL", "AH", "BL", "BH", "CL", "CH", "DL", "DH"}
REG16 = {"AX", "BX", "CX", "DX", "SI", "DI", "SP", "BP"}
SREG = {"CS", "DS", "ES", "SS"}
ARITH_FLAGS = "Updates CF, ZF, SF, OF, PF and AF."
LOGIC_FLAGS = "Clears CF and OF; updates ZF, SF and PF."

JCC = {
    "JE": "equal (ZF=1)", "JZ": "zero (ZF=1)", "JNE": "not equal (ZF=0)", "JNZ": "not zero (ZF=0)",
    "JC": "carry (CF=1)", "JNC": "no carry (CF=0)", "JA": "above – unsigned > (CF=0 and ZF=0)",
    "JAE": "above or equal – unsigned >= (CF=0)", "JB": "below – unsigned < (CF=1)",
    "JBE": "below or equal – unsigned <= (CF=1 or ZF=1)", "JNB": "not below – unsigned >= (CF=0)",
    "JNA": "not above – unsigned <= (CF=1 or ZF=1)", "JG": "greater – signed >", "JGE": "greater or equal – signed >=",
    "JL": "less – signed <", "JLE": "less or equal – signed <=", "JS": "sign (SF=1)", "JNS": "no sign (SF=0)",
    "JO": "overflow (OF=1)", "JNO": "no overflow (OF=0)", "JP": "parity even (PF=1)", "JNP": "parity odd (PF=0)",
    "JCXZ": "CX = 0",
}

# mnemonic -> (explanation template, flags note). {d}=destination, {s}=source
INSTR = {
    "MOV": ("Copies {s} into {d}. {s} is not changed.", "No flags affected."),
    "ADD": ("Adds {s} to {d} and stores the sum in {d}.", ARITH_FLAGS),
    "ADC": ("Adds {s} plus the Carry Flag to {d} (used for multi-word addition).", ARITH_FLAGS),
    "SUB": ("Subtracts {s} from {d} and stores the difference in {d}.", ARITH_FLAGS),
    "SBB": ("Subtracts {s} and the Carry Flag (borrow) from {d}.", ARITH_FLAGS),
    "INC": ("Adds 1 to {d}.", "Updates ZF, SF, OF, PF, AF. CF is NOT changed."),
    "DEC": ("Subtracts 1 from {d}.", "Updates ZF, SF, OF, PF, AF. CF is NOT changed."),
    "CMP": ("Compares {d} with {s} by calculating {d} - {s}. The result is NOT stored; only flags change.", ARITH_FLAGS + " The next conditional jump uses these flags."),
    "NEG": ("Replaces {d} with its two's complement (0 - {d}).", ARITH_FLAGS),
    "AND": ("Bitwise AND of {d} and {s}; result in {d}.", LOGIC_FLAGS),
    "OR": ("Bitwise OR of {d} and {s}; result in {d}.", LOGIC_FLAGS),
    "XOR": ("Bitwise XOR of {d} and {s}; result in {d}. XOR of a register with itself clears it to 0.", LOGIC_FLAGS),
    "NOT": ("Inverts every bit of {d} (one's complement).", "No flags affected."),
    "TEST": ("Bitwise AND of {d} and {s} only to set flags; the result is not stored.", LOGIC_FLAGS),
    "SHL": ("Shifts {d} left by {s} bit(s); each shift multiplies an unsigned value by 2.", "The bit shifted out goes into CF."),
    "SAL": ("Shifts {d} left by {s} bit(s) (same as SHL).", "The bit shifted out goes into CF."),
    "SHR": ("Shifts {d} right by {s} bit(s), filling with 0; divides an unsigned value by 2 per shift.", "The bit shifted out goes into CF."),
    "SAR": ("Shifts {d} right by {s} bit(s), keeping the sign bit (signed divide by 2).", "The bit shifted out goes into CF."),
    "ROL": ("Rotates {d} left by {s} bit(s).", "CF gets the bit rotated out."),
    "ROR": ("Rotates {d} right by {s} bit(s).", "CF gets the bit rotated out."),
    "RCL": ("Rotates {d} left through the Carry Flag by {s} bit(s).", "CF is part of the rotation."),
    "RCR": ("Rotates {d} right through the Carry Flag by {s} bit(s).", "CF is part of the rotation."),
    "LEA": ("Loads the address (offset) of {s} into {d} — not the data stored there.", "No flags affected."),
    "XCHG": ("Swaps the contents of {d} and {s}.", "No flags affected."),
    "PUSH": ("Saves {d} on the stack (SP decreases by 2).", "No flags affected."),
    "POP": ("Restores {d} from the top of the stack (SP increases by 2).", "No flags affected."),
    "JMP": ("Always jumps to {d}.", "No flags affected."),
    "LOOP": ("Decrements CX by 1; if CX is not 0, jumps back to {d}.", "No flags affected (CX is not a flag)."),
    "LOOPE": ("Decrements CX; jumps to {d} if CX != 0 and ZF = 1.", "No flags affected."),
    "LOOPZ": ("Decrements CX; jumps to {d} if CX != 0 and ZF = 1.", "No flags affected."),
    "LOOPNE": ("Decrements CX; jumps to {d} if CX != 0 and ZF = 0.", "No flags affected."),
    "LOOPNZ": ("Decrements CX; jumps to {d} if CX != 0 and ZF = 0.", "No flags affected."),
    "CALL": ("Calls procedure {d}: pushes the return address and jumps to it.", "No flags affected."),
    "RET": ("Returns from a procedure by popping the return address.", "No flags affected."),
    "HLT": ("Halts the processor until an interrupt or reset (used to stop on trainer kits).", "No flags affected."),
    "NOP": ("Does nothing for one instruction cycle.", "No flags affected."),
    "CLC": ("Clears the Carry Flag (CF = 0).", "CF = 0."),
    "STC": ("Sets the Carry Flag (CF = 1).", "CF = 1."),
    "CMC": ("Complements (inverts) the Carry Flag.", "CF inverted."),
    "CLD": ("Clears the Direction Flag so string instructions move forward (SI/DI increase).", "DF = 0."),
    "STD": ("Sets the Direction Flag so string instructions move backward (SI/DI decrease).", "DF = 1."),
    "CLI": ("Disables maskable interrupts.", "IF = 0."),
    "STI": ("Enables maskable interrupts.", "IF = 1."),
    "CBW": ("Sign-extends AL into AX (copies bit 7 of AL into all of AH).", "No flags affected."),
    "CWD": ("Sign-extends AX into DX:AX (copies bit 15 of AX into all of DX).", "No flags affected."),
    "DAA": ("Decimal-adjusts AL after a BCD addition.", "Updates CF, AF, ZF, SF, PF."),
    "DAS": ("Decimal-adjusts AL after a BCD subtraction.", "Updates CF, AF, ZF, SF, PF."),
    "AAA": ("ASCII-adjusts AL after addition of unpacked BCD digits.", "Updates CF and AF."),
    "AAM": ("ASCII-adjusts AX after multiplication: AH = AL / 10, AL = AL mod 10.", "Updates ZF, SF, PF."),
    "XLAT": ("Replaces AL with the byte at DS:[BX + AL] (table lookup).", "No flags affected."),
    "LAHF": ("Copies the low byte of the flag register into AH.", "No flags affected."),
    "SAHF": ("Copies AH into the low byte of the flag register.", "Updates SF, ZF, AF, PF, CF."),
    "PUSHF": ("Pushes the flag register on the stack.", "No flags affected."),
    "POPF": ("Pops the flag register from the stack.", "All flags restored."),
    "IN": ("Reads data from I/O port {s} into {d}.", "No flags affected."),
    "OUT": ("Sends the data in {s} to I/O port {d}.", "No flags affected."),
    "MOVSB": ("Copies a byte from DS:[SI] to ES:[DI], then SI and DI change by 1 (direction set by DF).", "No flags affected."),
    "MOVSW": ("Copies a word from DS:[SI] to ES:[DI], then SI and DI change by 2.", "No flags affected."),
    "CMPSB": ("Compares byte DS:[SI] with ES:[DI] and updates SI and DI.", ARITH_FLAGS),
    "CMPSW": ("Compares word DS:[SI] with ES:[DI] and updates SI and DI.", ARITH_FLAGS),
    "SCASB": ("Compares AL with byte ES:[DI] and updates DI.", ARITH_FLAGS),
    "SCASW": ("Compares AX with word ES:[DI] and updates DI.", ARITH_FLAGS),
    "LODSB": ("Loads byte DS:[SI] into AL and updates SI.", "No flags affected."),
    "LODSW": ("Loads word DS:[SI] into AX and updates SI.", "No flags affected."),
    "STOSB": ("Stores AL into ES:[DI] and updates DI.", "No flags affected."),
    "STOSW": ("Stores AX into ES:[DI] and updates DI.", "No flags affected."),
}
PREFIXES = {"REP": "Repeats the following string instruction CX times.",
            "REPE": "Repeats while CX != 0 and ZF = 1.", "REPZ": "Repeats while CX != 0 and ZF = 1.",
            "REPNE": "Repeats while CX != 0 and ZF = 0.", "REPNZ": "Repeats while CX != 0 and ZF = 0."}
DIRECTIVES = {
    ".MODEL": "Assembler directive: selects the memory model (SMALL = one code and one data segment).",
    ".STACK": "Assembler directive: reserves stack space of the given size.",
    ".DATA": "Assembler directive: starts the data segment (variables).",
    ".CODE": "Assembler directive: starts the code segment (instructions).",
    "ASSUME": "Assembler directive: tells the assembler which segment register points to which segment.",
    "ORG": "Assembler directive: sets the starting address (offset) for the following code/data.",
    "END": "Assembler directive: end of the source file; the label after it is the program's entry point.",
    "DB": "Reserves byte(s) of memory with the given value(s).",
    "DW": "Reserves word(s) of memory with the given value(s).",
}
ALL_MNEMONICS = set(INSTR) | set(JCC) | {"MUL", "IMUL", "DIV", "IDIV", "INT"} | set(PREFIXES)


def _result(status, text, **data):
    return {"status": status, "text": text, "data": data}


# ---------------------------------------------------------------- Tool 1: Experiment Search

def experiment_search(query="", experiment_id=None, **_):
    exp = kb.get_experiment(experiment_id) if experiment_id else None
    matches = [exp] if exp else kb.search_experiments(query)
    if not matches or not (query or "").strip() and not exp:
        return _result("not_found", "I could not find a matching experiment in the knowledge base. "
                       "Try words like *addition*, *sorting*, *largest*, *block transfer* or *experiment 3*.",
                       matches=[])
    top = matches[0]
    text = (f"### Experiment {top['number']}: {top['title']}\n"
            f"**Aim:** {top['aim']}\n\n"
            f"**Requirements:** {', '.join(top.get('apparatus', []))}\n\n"
            "**Algorithm:**\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(top["algorithm"], 1)) +
            "\n\n**Procedure:**\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(top["procedure"], 1)) +
            f"\n\n**Expected result:** {top['expected_output']} (for input {top.get('sample_input', '-')})")
    if len(matches) > 1:
        text += "\n\nOther related experiments: " + ", ".join(f"Exp {m['number']} – {m['title']}" for m in matches[1:4])
    return _result("ok", text, experiment=kb.summary(top), matches=[kb.summary(m) for m in matches[:5]])


# ---------------------------------------------------------------- Tool 2: Manual Q&A

OVERVIEW_RE = re.compile(r"\b(summar|overview|outline|contents|what is (in|inside)|about)\w*|\b(explain|describe|tell)\b.*\b(manual|pdf|document|file)\b", re.I)
MANUAL_WORDS = {"manual", "lab", "pdf", "document", "uploaded", "file", "summary", "summarize", "summarise", "overview"}


def manual_qa(query="", manual_chunks=None, **_):
    if not (query or "").strip():
        return _result("needs_input", "Please type a question about the lab manual.")
    if manual_chunks and OVERVIEW_RE.search(query):
        picked = manual_chunks[:8]
        text = f"**Overview of the uploaded document** (first {len(picked)} of {len(manual_chunks)} sections):\n\n" + "\n\n".join(
            f"**Page {c.get('page', '?')}**\n> {c['text'][:600]}{'…' if len(c['text']) > 600 else ''}" for c in picked)
        return _result("ok", text, overview=True,
                       sources=[{"source": f"Uploaded manual – page {c.get('page', '?')}", "text": c["text"][:600], "score": None} for c in picked])
    # words like "manual"/"lab" appear in the question but not in the content, so don't count them
    focused = " ".join(w for w in kb.tokenize(query) if w not in MANUAL_WORDS) or query
    hits = kb.search_all(focused, manual_chunks)
    good = [(s, cov, d) for s, cov, d in hits if cov >= 0.34 and s >= 1.0]
    if not good:
        where = "the uploaded manual or the built-in knowledge base" if manual_chunks else "the built-in knowledge base (no manual uploaded)"
        return _result("not_found", f"This information is **not available** in {where}.", sources=[])
    text = "Here is what I found:\n\n" + "\n\n".join(
        f"**{d['source']}**\n> {d['text'][:600]}{'…' if len(d['text']) > 600 else ''}" for _, _, d in good)
    return _result("ok", text, sources=[{"source": d["source"], "text": d["text"][:1200], "score": s} for s, _, d in good])


# ---------------------------------------------------------------- Tool 3: Program Explainer

def _strip_comment(line):
    return line.split(";", 1)[0].rstrip()


def _symbols(code):
    """Collect variables (DB/DW/DD) and constants (EQU) declared in the program."""
    variables, constants = {}, {}
    for raw in code.splitlines():
        line = _strip_comment(raw).strip()
        m = re.match(r"^([A-Za-z_]\w*)\s+(DB|DW|DD|EQU)\b\s*(.*)$", line, re.I)
        if m:
            name, kind = m.group(1).upper(), m.group(2).upper()
            if kind == "EQU":
                constants[name] = m.group(3).strip()
            else:
                variables[name] = {"DB": "byte", "DW": "word", "DD": "doubleword"}[kind]
    return variables, constants


def _is_number(tok):
    return bool(re.fullmatch(r"[0-9][0-9A-F]*H|[0-9]+D?|[01]+B|'.'", tok.upper()))


def classify(op, variables, constants):
    """Return (kind, size_bits or None, description)."""
    u = op.strip().upper()
    if u in REG8:
        return "reg8", 8, f"8-bit register {u}"
    if u in REG16:
        return "reg16", 16, f"16-bit register {u}"
    if u in SREG:
        return "sreg", 16, f"segment register {u}"
    if u.startswith("@") or u.startswith("OFFSET "):
        return "imm", None, f"address constant {op.strip()}"
    size = 8 if "BYTE PTR" in u else 16 if "WORD PTR" in u else None
    if "[" in u:
        return "mem", size, f"memory location {op.strip()}"
    base = re.split(r"[\s\[+]", u)[0]
    if base in variables:
        bits = {"byte": 8, "word": 16, "doubleword": 32}[variables[base]]
        return "mem", size or bits, f"{variables[base]} variable {op.strip()}"
    if base in constants:
        return "imm", None, f"constant {op.strip()} (= {constants[base]})"
    if _is_number(u):
        return "imm", None, f"immediate value {op.strip()}"
    return "label", None, f"label/symbol {op.strip()}"


def _split_operands(rest):
    parts, depth, cur = [], 0, ""
    for ch in rest:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_line(raw):
    """Split a source line into (label, mnemonic, operands, is_directive_line)."""
    line = _strip_comment(raw).strip()
    label = None
    m = re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line)
    if m:
        label, line = m.group(1), m.group(2)
    if not line:
        return label, None, [], line
    parts = line.split(None, 1)
    mnem = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""
    if mnem in PREFIXES and rest:
        inner = rest.split(None, 1)
        return label, mnem + " " + inner[0].upper(), _split_operands(inner[1]) if len(inner) > 1 else [], line
    return label, mnem, _split_operands(rest), line


def _explain_muldiv(mnem, ops, variables, constants):
    if not ops:
        return f"{mnem} needs one operand.", ""
    kind, size, desc = classify(ops[0], variables, constants)
    if kind == "imm":
        return f"{mnem} cannot use an immediate operand ({desc}). Load it into a register first.", ""
    signed = "signed" if mnem.startswith("I") else "unsigned"
    if mnem in ("MUL", "IMUL"):
        if size == 8:
            return f"{signed.capitalize()} multiply: AX = AL × {desc}.", "Changes AX. CF/OF = 1 if AH is not zero (upper half used)."
        if size == 16:
            return f"{signed.capitalize()} multiply: DX:AX = AX × {desc} (DX = upper word, AX = lower word).", "Changes AX and DX. CF/OF = 1 if DX is not zero."
        return f"{signed.capitalize()} multiply by {desc}. Byte operand: AX = AL × op. Word operand: DX:AX = AX × op.", "CF/OF show if the upper half is used."
    if size == 8:
        return f"{signed.capitalize()} divide: AX ÷ {desc}. Quotient → AL, remainder → AH.", "Flags undefined. Divide error if the divisor is 0 or the quotient > FFh."
    if size == 16:
        return f"{signed.capitalize()} divide: DX:AX ÷ {desc}. Quotient → AX, remainder → DX. (DX must be prepared first!)", "Flags undefined. Divide error if the divisor is 0 or the quotient > FFFFh."
    return f"{signed.capitalize()} divide by {desc}. Byte operand: AX ÷ op (AL = quotient, AH = remainder). Word operand: DX:AX ÷ op.", "Flags undefined."


def explain_line(raw, variables, constants, last_ah=None):
    label, mnem, ops, clean = parse_line(raw)
    if not clean.strip() and not label:
        return None
    entry = {"code": raw.strip(), "label": label, "kind": "instruction", "explanation": "", "flags": "", "changes": []}
    if label and not mnem:
        entry.update(kind="label", explanation=f"Label **{label}** marks this position so jumps/loops can come here.")
        return entry
    upper = clean.upper()
    m = re.match(r"^([A-Za-z_]\w*)\s+(DB|DW|DD|EQU)\b\s*(.*)$", clean, re.I)
    if m:
        kind = m.group(2).upper()
        meaning = {"DB": "byte(s) (8-bit)", "DW": "word(s) (16-bit)", "DD": "doubleword(s) (32-bit)"}.get(kind)
        val = m.group(3).strip()
        entry["kind"] = "data"
        if kind == "EQU":
            entry["explanation"] = f"Defines constant **{m.group(1)}** = {val}. No memory is used."
        else:
            init = "uninitialised (?)" if val == "?" else val
            entry["explanation"] = f"Declares variable **{m.group(1)}** as {meaning} with value(s): {init}."
        return entry
    words = upper.split()
    if words[0] in DIRECTIVES or (len(words) > 1 and words[1] in ("PROC", "ENDP", "SEGMENT", "ENDS")):
        entry["kind"] = "directive"
        if len(words) > 1 and words[1] in ("PROC", "ENDP", "SEGMENT", "ENDS"):
            entry["explanation"] = {"PROC": f"Starts procedure {words[0]}.", "ENDP": f"Ends procedure {words[0]}.",
                                    "SEGMENT": f"Starts segment {words[0]}.", "ENDS": f"Ends segment {words[0]}."}[words[1]]
        else:
            entry["explanation"] = DIRECTIVES[words[0]]
        return entry

    d = ops[0] if ops else "?"
    s = ops[1] if len(ops) > 1 else ("1" if mnem in ("SHL", "SHR", "SAL", "SAR", "ROL", "ROR", "RCL", "RCR") else "?")
    base = mnem.split()[-1]
    if " " in mnem:  # REP MOVSB etc.
        pre = mnem.split()[0]
        info = INSTR.get(base, ("Unknown string instruction.", ""))
        entry["explanation"] = f"{PREFIXES[pre]} {info[0]}"
        entry["flags"] = info[1]
        entry["changes"] = ["CX", "SI", "DI"]
    elif mnem in ("MUL", "IMUL", "DIV", "IDIV"):
        entry["explanation"], entry["flags"] = _explain_muldiv(mnem, ops, variables, constants)
        entry["changes"] = ["AX", "DX"]
    elif mnem == "INT":
        n = d.upper().rstrip("H")
        if n == "21" and last_ah == "4C":
            entry["explanation"] = "Calls DOS interrupt 21h with AH = 4Ch: terminates the program and returns to DOS."
        elif n == "21":
            entry["explanation"] = f"Calls DOS interrupt 21h. The service performed depends on AH ({last_ah + 'h' if last_ah else 'set earlier'})."
        elif n == "3":
            entry["explanation"] = "Breakpoint interrupt (INT 3) — stops in the debugger/monitor."
        else:
            entry["explanation"] = f"Calls software interrupt {d}."
        entry["flags"] = "Clears IF and TF while the interrupt routine runs."
    elif mnem in JCC:
        entry["explanation"] = f"Conditional jump: goes to **{d}** only if the last comparison/result was {JCC[mnem]}; otherwise continues to the next line."
        entry["flags"] = "Reads flags; does not change them."
    elif mnem in INSTR:
        tmpl, flags = INSTR[mnem]
        dk = classify(d, variables, constants)[2] if ops else d
        sk = classify(s, variables, constants)[2] if len(ops) > 1 else s
        entry["explanation"] = tmpl.format(d=dk, s=sk)
        entry["flags"] = flags
        if ops and mnem not in ("CMP", "TEST", "JMP", "LOOP", "CALL", "PUSH", "OUT") and not mnem.startswith("LOOP"):
            entry["changes"] = [d.upper()]
        if mnem == "XCHG" and len(ops) > 1:
            entry["changes"] = [d.upper(), s.upper()]
        if mnem.startswith("LOOP"):
            entry["changes"] = ["CX"]
    else:
        entry.update(kind="unknown", explanation=f"'{mnem}' is not a recognised 8086 instruction or directive. Check the spelling.")
    return entry


def lint_program(code):
    """Static checks for common 8086 mistakes. Returns [{line, issue, fix}]."""
    issues = []
    variables, constants = _symbols(code)
    lines = code.splitlines()
    upper_all = code.upper()
    labels = set(re.findall(r"^\s*([A-Z_]\w*)\s*(?::|\s+PROC\b)", upper_all, re.M))
    has_data = ".DATA" in upper_all or "DATA SEGMENT" in upper_all
    if has_data and not re.search(r"MOV\s+DS\s*,", upper_all):
        issues.append({"line": None, "issue": "DS is never initialised although the program has a data segment.",
                       "fix": "Add MOV AX, @DATA and MOV DS, AX at the start of the code."})
    if re.search(r"\b(MOVS[BW]|CMPS[BW]|SCAS[BW]|STOS[BW])\b", upper_all):
        if not re.search(r"MOV\s+ES\s*,", upper_all):
            issues.append({"line": None, "issue": "A string instruction uses ES:DI but ES is never loaded.",
                           "fix": "Add MOV ES, AX after MOV DS, AX (when source and destination are in the same data segment)."})
        if "CLD" not in upper_all and "STD" not in upper_all:
            issues.append({"line": None, "issue": "Direction flag is not set before string instructions.",
                           "fix": "Add CLD before REP MOVSB/MOVSW so SI and DI increase."})
    is_program = len([l for l in lines if _strip_comment(l).strip()]) >= 3
    if is_program and not re.search(r"(MOV\s+AH\s*,\s*4CH[\s\S]*INT\s+21H|MOV\s+AX\s*,\s*4C00H[\s\S]*INT\s+21H|\bHLT\b|\bRET\b|INT\s+3\b)", upper_all):
        issues.append({"line": None, "issue": "No program termination found.",
                       "fix": "End with MOV AH, 4Ch then INT 21h (DOS/emu8086) or HLT (trainer kit)."})
    if (".CODE" in upper_all or "PROC" in upper_all) and not re.search(r"^\s*END\b", upper_all, re.M):
        issues.append({"line": None, "issue": "Missing END directive.", "fix": "Add END MAIN as the last line."})

    cx_set = False
    for n, raw in enumerate(lines, 1):
        label, mnem, ops, clean = parse_line(raw)
        if not mnem:
            continue
        if re.search(r"\b0X[0-9A-F]+", clean.upper()):
            issues.append({"line": n, "issue": "C-style hex (0x..) is not valid in MASM/TASM.", "fix": "Write hex as 0..h, e.g. 0x1F → 1Fh."})
        for tok in re.findall(r"(?<![\w@])([A-F][0-9A-F]*H)\b", clean.upper()):
            if tok not in variables and tok not in constants and tok not in labels and tok not in REG8 | REG16:
                issues.append({"line": n, "issue": f"Hex number {tok} starts with a letter, so the assembler reads it as a symbol name.",
                               "fix": f"Add a leading zero: 0{tok}."})
        if ops and ops[0].upper() in ("CX", "CL") and mnem in ("MOV", "XOR", "SUB", "POP"):
            cx_set = True
        if mnem.startswith("LOOP") and not cx_set:
            issues.append({"line": n, "issue": "LOOP is used but CX was not loaded before it.", "fix": "Load the loop count, e.g. MOV CX, 5, before the loop label."})
        if len(ops) == 2 and mnem in ("MOV", "ADD", "SUB", "ADC", "SBB", "CMP", "AND", "OR", "XOR", "XCHG", "TEST"):
            k1, s1, _ = classify(ops[0], variables, constants)
            k2, s2, _ = classify(ops[1], variables, constants)
            if k1 == "mem" and k2 == "mem":
                issues.append({"line": n, "issue": f"Memory-to-memory operation ({clean.strip()}) is not allowed on the 8086.",
                               "fix": "Move one operand into a register first, e.g. MOV AL, src then MOV dest, AL."})
            if k1 == "sreg" and k2 in ("imm", "label"):
                issues.append({"line": n, "issue": f"Cannot load an immediate value directly into {ops[0].upper()}.",
                               "fix": f"Use MOV AX, {ops[1]} then MOV {ops[0].upper()}, AX."})
            if k1 == "sreg" and k2 == "sreg":
                issues.append({"line": n, "issue": "Segment register to segment register move is not allowed.", "fix": "Copy through AX."})
            if k1 == "imm":
                issues.append({"line": n, "issue": "The destination cannot be an immediate value.", "fix": "Use a register or memory location as destination."})
            if s1 and s2 and s1 != s2 and "PTR" not in (ops[0] + ops[1]).upper():
                issues.append({"line": n, "issue": f"Operand size mismatch: {ops[0]} is {s1}-bit but {ops[1]} is {s2}-bit.",
                               "fix": "Use operands of the same size (AL with BL, AX with BX, DB with 8-bit, DW with 16-bit)."})
            if k1 == "mem" and k2 == "imm" and s1 is None:
                issues.append({"line": n, "issue": "The assembler cannot know whether to store a byte or a word.",
                               "fix": "Write BYTE PTR or WORD PTR, e.g. MOV BYTE PTR [SI], 05h."})
        if mnem in ("MUL", "IMUL", "DIV", "IDIV") and ops and classify(ops[0], variables, constants)[0] == "imm":
            issues.append({"line": n, "issue": f"{mnem} cannot take an immediate operand.", "fix": f"Load the value into a register (e.g. MOV BL, {ops[0]}) and use {mnem} BL."})
        if mnem in ("DIV", "IDIV") and ops and classify(ops[0], variables, constants)[1] == 16:
            before = "\n".join(lines[:n - 1]).upper()
            if not re.search(r"(MOV\s+DX\s*,|XOR\s+DX\s*,\s*DX|SUB\s+DX\s*,\s*DX|CWD)", before):
                issues.append({"line": n, "issue": "16-bit DIV divides DX:AX, but DX is never set.",
                               "fix": "Add XOR DX, DX (unsigned) or CWD (signed) before the DIV."})
        if mnem in ("OUT", "IN") and ops:
            port = ops[0] if mnem == "OUT" else (ops[1] if len(ops) > 1 else "")
            if port.upper() != "DX" and _is_number(port.upper()):
                val = int(port.upper().rstrip("H"), 16) if port.upper().endswith("H") else int(re.sub(r"\D", "", port) or 0)
                if val > 0xFF:
                    issues.append({"line": n, "issue": f"Port address {port} is above FFh; direct addressing only allows 00h–FFh.",
                                   "fix": f"Use MOV DX, {port} and then {mnem} with DX."})
        if re.search(r"\b(E[A-D]X|E[SD]I|MOVZX|MOVSX)\b", clean.upper()):
            issues.append({"line": n, "issue": "32-bit (80386+) registers or instructions are used.", "fix": "Use only 16-bit 8086 registers and instructions."})
        base = mnem.split()[-1]
        if base not in ALL_MNEMONICS and base not in DIRECTIVES and not re.match(r"^\w+\s+(PROC|ENDP|SEGMENT|ENDS|DB|DW|DD|EQU)\b", clean, re.I) \
                and base not in (".MODEL", ".STACK", ".DATA", ".CODE", "ASSUME", "END", "ORG"):
            issues.append({"line": n, "issue": f"'{base}' is not a recognised 8086 instruction.", "fix": "Check the spelling (e.g. MOV not MOVE)."})
    # de-duplicate
    seen, unique = set(), []
    for i in issues:
        key = (i["line"], i["issue"])
        if key not in seen:
            seen.add(key)
            unique.append(i)
    return unique


def program_explainer(code="", **_):
    code = (code or "").strip()
    if not code:
        return _result("needs_input", "Paste an 8086 assembly program (or a single instruction) to explain.")
    variables, constants = _symbols(code)
    lines, last_ah = [], None
    for raw in code.splitlines():
        e = explain_line(raw, variables, constants, last_ah)
        _, mnem, ops, _ = parse_line(raw)
        if mnem == "MOV" and len(ops) == 2 and ops[0].upper() == "AH":
            last_ah = ops[1].upper().rstrip("H").lstrip("0") or "0"
            last_ah = last_ah.zfill(2)
        if e:
            lines.append(e)
    instr = [l for l in lines if l["kind"] in ("instruction", "unknown")]
    if not instr and not any(l["kind"] in ("data", "directive") for l in lines):
        return _result("not_found", "I could not find any 8086 instructions in that text.", lines=[])
    regs = sorted({c for l in lines for c in l["changes"] if c in REG8 | REG16 | SREG})
    issues = lint_program(code)
    text = "**Line-by-line explanation** (static analysis – the program was NOT executed):\n\n" + "\n".join(
        f"- `{l['code']}` → {l['explanation']}" + (f" _Flags: {l['flags']}_" if l["flags"] else "") for l in lines)
    if regs:
        text += f"\n\n**Registers modified:** {', '.join(regs)}"
    if issues:
        text += "\n\n**Possible problems found:**\n" + "\n".join(
            f"- {'Line ' + str(i['line']) + ': ' if i['line'] else ''}{i['issue']} → {i['fix']}" for i in issues)
    return _result("ok", text, lines=lines, registers_modified=regs, issues=issues, executed=False)


# ---------------------------------------------------------------- Tool 4: Output Verification

def parse_hex(value, bits, name):
    s = str(value).strip().upper().replace(" ", "")
    if s.startswith("0X"):
        s = s[2:]
    if s.endswith("H"):
        s = s[:-1]
    if not s or not re.fullmatch(r"[0-9A-F]+", s):
        raise ValueError(f"'{value}' is not a valid hex value for {name}.")
    n = int(s, 16)
    if n >= 1 << bits:
        raise ValueError(f"{name} = {value} is too large for {bits} bits (max {'FF' if bits == 8 else 'FFFF'}h).")
    return n


def parse_bytes(value, name):
    parts = [p for p in re.split(r"[\s,]+", str(value).strip()) if p]
    if not parts:
        raise ValueError(f"{name} must contain at least one hex byte, e.g. 12, 45, 07.")
    if len(parts) > 64:
        raise ValueError(f"{name} has too many elements (max 64).")
    return [parse_hex(p, 8, name) for p in parts]


def parse_field(value, ftype, name):
    if ftype == "word":
        return parse_hex(value, 16, name)
    if ftype == "byte":
        return parse_hex(value, 8, name)
    if ftype == "flag":
        v = parse_hex(value, 8, name)
        if v not in (0, 1):
            raise ValueError(f"{name} must be 0 or 1.")
        return v
    if ftype == "bytes":
        return parse_bytes(value, name)
    raise ValueError(f"Unknown field type {ftype}")


def _search(arr, key):
    return {"found": 1, "position": arr.index(key) + 1} if key in arr else {"found": 0, "position": 0}


def _div(i):
    if i["divisor"] == 0:
        raise ArithmeticError("Divisor is 0 – the 8086 raises a divide error (INT 0).")
    q, r = divmod(i["dividend"], i["divisor"])
    if q > 0xFF:
        raise ArithmeticError(f"Quotient {q:X}h does not fit in AL – the 8086 raises a divide overflow error (INT 0).")
    return {"quotient": q, "remainder": r}


# Python reference implementations of each experiment's algorithm (used to compute expected values).
REFERENCE = {
    "add16": lambda i: {"result": (i["num1"] + i["num2"]) & 0xFFFF, "carry": int(i["num1"] + i["num2"] > 0xFFFF)},
    "sub16": lambda i: {"result": (i["num1"] - i["num2"]) & 0xFFFF, "borrow": int(i["num1"] < i["num2"])},
    "mul16": lambda i: {"dx": (i["num1"] * i["num2"]) >> 16, "ax": (i["num1"] * i["num2"]) & 0xFFFF},
    "div16": _div,
    "largest": lambda i: {"largest": max(i["array"])},
    "smallest": lambda i: {"smallest": min(i["array"])},
    "sort_asc": lambda i: {"sorted": sorted(i["array"])},
    "search": lambda i: _search(i["array"], i["key"]),
    "block_transfer": lambda i: {"destination": list(i["array"])},
}


def fmt(v, ftype):
    if ftype == "bytes":
        return ", ".join(f"{b:02X}h" for b in v)
    if ftype == "flag":
        return str(v)
    return f"{v:02X}h" if ftype == "byte" else f"{v:04X}h"


def _signed8(b):
    return b - 256 if b > 127 else b


def _mismatch_hints(exp_id, inputs, expected, observed, raw_observed, spec):
    hints = []
    for f in spec["outputs"]:
        name, ftype = f["name"], f["type"]
        o, e, raw = observed[name], expected[name], str(raw_observed.get(name, "")).strip()
        if o == e:
            continue
        if ftype in ("word", "byte") and re.fullmatch(r"\d+", raw) and int(raw) == e:
            hints.append(f"{f['label']}: you entered {raw}, which equals the expected value in **decimal**. Enter values in hex.")
        if ftype == "word" and ((o & 0xFF) << 8 | o >> 8) == e:
            hints.append(f"{f['label']}: the two bytes are swapped. Memory stores the LOW byte first (little-endian), so read the word as high byte + low byte.")
    if exp_id == "sub16" and observed["result"] == (inputs["num2"] - inputs["num1"]) & 0xFFFF and expected["result"] != observed["result"]:
        hints.append("Your result equals NUM2 − NUM1: the operands of SUB are probably reversed.")
    if exp_id in ("add16", "sub16"):
        key = "carry" if exp_id == "add16" else "borrow"
        if observed["result"] == expected["result"] and observed[key] != expected[key]:
            hints.append(f"The result is right but {key.upper()} is wrong: check the JNC/JC condition and that {key.upper()} starts at 00h.")
    if exp_id == "mul16":
        if observed["ax"] == expected["ax"] and observed["dx"] != expected["dx"]:
            hints.append("AX is correct but DX is wrong: the upper word of the product is in DX — store/read DX too.")
        if observed["ax"] == expected["dx"] and observed["dx"] == expected["ax"]:
            hints.append("DX and AX are swapped: DX holds the UPPER word, AX the LOWER word.")
    if exp_id == "div16" and observed["quotient"] == expected["remainder"] and observed["remainder"] == expected["quotient"]:
        hints.append("Quotient and remainder are swapped: after 8-bit DIV, AL = quotient and AH = remainder.")
    arr = inputs.get("array")
    if exp_id == "largest":
        if observed["largest"] == max(arr, key=_signed8):
            hints.append("Your answer is the largest SIGNED value: use JAE/JA (unsigned) instead of JGE/JG.")
        elif observed["largest"] == min(arr):
            hints.append("You got the smallest value: the jump condition is reversed (use JAE to skip).")
        elif observed["largest"] == arr[0]:
            hints.append("You got the first element: the loop may not run (CX not loaded) or the update MOV AL,[SI] is skipped.")
    if exp_id == "smallest":
        if observed["smallest"] == min(arr, key=_signed8):
            hints.append("Your answer is the smallest SIGNED value: use JBE/JB (unsigned) instead of JLE/JL.")
        elif observed["smallest"] == max(arr):
            hints.append("You got the largest value: the jump condition is reversed (use JBE to skip).")
    if exp_id == "sort_asc":
        o = observed["sorted"]
        if o == sorted(arr, reverse=True):
            hints.append("Array is in DESCENDING order: change JAE to JBE.")
        elif o == arr:
            hints.append("Array is unchanged: the swap never happened — check DS initialisation and the XCHG/MOV swap lines.")
        elif sorted(o) == sorted(arr):
            hints.append("Same elements but not fully sorted: not enough passes. Outer loop must run N−1 times; keep the outer count in a register other than CX.")
        elif len(o) != len(arr):
            hints.append(f"You entered {len(o)} elements but the input has {len(arr)}.")
    if exp_id == "search" and observed["position"] == expected["position"] - 1 and expected["found"]:
        hints.append("Position is one less than expected: you counted from 0. This program counts positions from 1.")
    if exp_id == "block_transfer":
        o = observed["destination"]
        if all(b == 0 for b in o):
            hints.append("Destination is all 00h: ES was not loaded, CX was 0, or you looked at the wrong address.")
        elif o == list(reversed(arr)):
            hints.append("Data is reversed: the Direction Flag was set. Add CLD before REP MOVSB.")
    return hints


def parse_values(value, name):
    parts = [p for p in re.split(r"[\s,]+", str(value or "").strip()) if p]
    if not parts:
        raise ValueError(f"{name} must contain at least one hex value, e.g. 68AC or 12, 45, 07.")
    if len(parts) > 64:
        raise ValueError(f"{name} has too many values (max 64).")
    return [parse_hex(p, 16, name) for p in parts]


def custom_verification(expected_raw, observed_raw):
    """Compare against expected values typed by the student (e.g. from their own manual)."""
    try:
        expected = parse_values(expected_raw, "Expected output")
        observed = parse_values(observed_raw, "Observed output")
    except ValueError as err:
        return _result("error", f"Input problem: {err}")
    n = max(len(expected), len(observed))
    comparison, all_ok = [], len(expected) == len(observed)
    for i in range(n):
        e = expected[i] if i < len(expected) else None
        o = observed[i] if i < len(observed) else None
        ok = e == o
        all_ok &= ok
        comparison.append({"field": f"Value {i + 1}", "expected": "—" if e is None else f"{e:02X}h",
                           "observed": "—" if o is None else f"{o:02X}h", "match": ok})
    hints = []
    if not all_ok:
        if len(expected) != len(observed):
            hints.append(f"You entered {len(expected)} expected value(s) but {len(observed)} observed value(s).")
        if observed == list(reversed(expected)) and len(expected) > 1:
            hints.append("The values are in reverse order: check the loop direction (DF/CLD) or sort condition.")
        if sorted(observed) == sorted(expected) and observed != expected:
            hints.append("Same values but in a different order: check sorting passes or the order you read memory.")
        raw_obs = [p for p in re.split(r"[\s,]+", str(observed_raw).strip()) if p]
        for i, (e, o) in enumerate(zip(expected, observed)):
            if e != o and ((o & 0xFF) << 8 | o >> 8) == e and o > 0xFF:
                hints.append(f"Value {i + 1}: bytes are swapped (little-endian). Memory stores the low byte first.")
            if e != o and i < len(raw_obs) and re.fullmatch(r"\d+", raw_obs[i]) and int(raw_obs[i]) == e:
                hints.append(f"Value {i + 1}: you entered {raw_obs[i]} in decimal; enter it in hex.")
        if not hints:
            hints.append("No specific pattern recognised. Check DS initialisation, operand order, signed vs unsigned jumps and that you read the right memory address.")
    text = ("✅ **Output matches your expected values.**" if all_ok else "❌ **Output does not match your expected values.**") + \
        " (Compared against the expected output YOU entered — not independently verified.)"
    return _result("ok", text, verdict="match" if all_ok else "mismatch", verified=False, comparison=comparison, hints=hints)


def output_verification(experiment_id=None, inputs=None, observed=None, **_):
    if experiment_id == "custom":
        return custom_verification((inputs or {}).get("expected"), (observed or {}).get("observed"))
    exp = kb.get_experiment(experiment_id) if experiment_id else None
    if not exp:
        return _result("needs_input", "Choose an experiment to verify. Open the **Verify Output** page, select the experiment, "
                       "and enter your input values and observed output.", supported=[e["id"] for e in kb.EXPERIMENTS if e.get("verify")])
    spec = exp.get("verify")
    if not spec or experiment_id not in REFERENCE:
        return _result("not_supported",
                       f"Automatic verification is not available for **{exp['title']}** (e.g. hardware output cannot be checked by software). "
                       f"Compare manually with the expected output: **{exp['expected_output']}**. This is a manual estimate, not a verified result.",
                       expected_output=exp["expected_output"], verified=False)
    if not inputs or not observed:
        return _result("needs_input", f"To verify **{exp['title']}**, enter the input values and your observed output on the Verify Output page.",
                       spec=spec)
    try:
        parsed_in = {f["name"]: parse_field(inputs.get(f["name"], ""), f["type"], f["label"]) for f in spec["inputs"]}
        parsed_obs = {f["name"]: parse_field(observed.get(f["name"], ""), f["type"], f["label"]) for f in spec["outputs"]}
    except ValueError as err:
        return _result("error", f"Input problem: {err}")
    try:
        expected = REFERENCE[experiment_id](parsed_in)
    except ArithmeticError as err:
        return _result("ok", f"**Expected behaviour:** {err} A correct program cannot produce a normal result for these inputs.",
                       verdict="error_expected", verified=True, comparison=[], hints=[str(err)])
    comparison, all_ok = [], True
    for f in spec["outputs"]:
        ok = parsed_obs[f["name"]] == expected[f["name"]]
        all_ok &= ok
        comparison.append({"field": f["label"], "expected": fmt(expected[f["name"]], f["type"]),
                           "observed": fmt(parsed_obs[f["name"]], f["type"]), "match": ok})
    hints = [] if all_ok else _mismatch_hints(experiment_id, parsed_in, expected, parsed_obs, observed, spec)
    if not all_ok and not hints:
        hints = ["No specific pattern recognised. Common causes for this experiment:"] + exp.get("common_errors", [])
    verdict = "match" if all_ok else "mismatch"
    text = ("✅ **Output matches.**" if all_ok else "❌ **Output does not match.**") + \
           " (Verified against a Python reference calculation of this experiment's algorithm — your assembly program itself was not run.)\n\n" + \
           "\n".join(f"- {c['field']}: expected **{c['expected']}**, observed **{c['observed']}** {'✔' if c['match'] else '✘'}" for c in comparison)
    if hints:
        text += "\n\n**Possible reasons:**\n" + "\n".join(f"- {h}" for h in hints)
    return _result("ok", text, verdict=verdict, verified=True, comparison=comparison, hints=hints)


# ---------------------------------------------------------------- Tool 5: Error Diagnosis

def error_diagnosis(error_message="", code="", experiment_id=None, **_):
    error_message, code = (error_message or "").strip(), (code or "").strip()
    if not error_message and not code:
        return _result("needs_input", "Paste the error message, your program, or describe the unexpected output.")
    matched = [e for e in kb.ERRORS if error_message and re.search(e["pattern"], error_message, re.I)]
    issues = lint_program(code) if code else []
    exp = kb.get_experiment(experiment_id) if experiment_id else None
    if not matched and not issues and not exp:
        return _result("not_found",
                       "I could not match this to a known error. General checklist:\n"
                       "- Is DS initialised (MOV AX,@DATA / MOV DS,AX)?\n- Do operand sizes match (AL with BL, AX with BX)?\n"
                       "- Do hex numbers end with 'h' and start with a digit (0FFh)?\n- Is CX loaded before LOOP?\n"
                       "- Does the program end with MOV AH,4Ch / INT 21h or HLT?\n\nPaste your full program for a detailed check.",
                       matched=[], issues=[])
    parts = []
    for e in matched:
        parts.append(f"### {e['title']}\n**Possible causes:**\n" + "\n".join(f"- {c}" for c in e["causes"]) +
                     "\n\n**How to fix:**\n" + "\n".join(f"- {f}" for f in e["fixes"]))
    if issues:
        parts.append("### Problems found in your program\n" + "\n".join(
            f"- {'**Line ' + str(i['line']) + ':** ' if i['line'] else ''}{i['issue']}\n  → Fix: {i['fix']}" for i in issues))
    elif code:
        parts.append("### Program check\nNo common static mistakes were detected in the code (this does not guarantee it is correct — it was not executed).")
    if exp:
        parts.append(f"### Common mistakes in “{exp['title']}”\n" + "\n".join(f"- {c}" for c in exp.get("common_errors", [])))
    return _result("ok", "\n\n".join(parts), matched=[e["title"] for e in matched], issues=issues)


# ---------------------------------------------------------------- Tool 6: Viva Generator

def viva_generator(experiment_id=None, level="all", count=6, query="", **_):
    exp = kb.get_experiment(experiment_id) if experiment_id else kb.detect_experiment(query)
    if not exp:
        return _result("needs_input", "Which experiment do you want viva questions for? e.g. *viva questions for sorting*.")
    levels = ["easy", "medium", "hard"] if level in (None, "", "all") else [level]
    if any(l not in exp["viva"] for l in levels):
        return _result("error", "Level must be easy, medium, hard or all.")
    qs = [dict(qa, level=l) for l in levels for qa in exp["viva"][l]]
    random.shuffle(qs)
    qs = sorted(qs[:max(1, min(int(count or 6), 30))], key=lambda q: ["easy", "medium", "hard"].index(q["level"]))
    text = f"### Viva questions – {exp['title']}\n" + "\n".join(
        f"{i}. **[{q['level'].title()}]** {q['q']}\n   - _Answer:_ {q['a']}" for i, q in enumerate(qs, 1))
    return _result("ok", text, experiment=kb.summary(exp), questions=qs)


# ---------------------------------------------------------------- Tool 7: Experiment Guide

def experiment_guide(experiment_id=None, step=0, query="", **_):
    exp = kb.get_experiment(experiment_id) if experiment_id else kb.detect_experiment(query)
    if not exp:
        return _result("needs_input", "Which experiment should I guide you through? e.g. *guide me through block transfer*.")
    steps = exp["procedure"]
    try:
        step = int(step)
    except (TypeError, ValueError):
        return _result("error", "Step must be a number.")
    if not 0 <= step < len(steps):
        return _result("error", f"Step must be between 1 and {len(steps)}.")
    text = (f"### {exp['title']} – Step {step + 1} of {len(steps)}\n{steps[step]}\n\n"
            + ("Open the **Guide** page to move to the next step." if step + 1 < len(steps) else "This is the last step. 🎉"))
    return _result("ok", text, experiment=kb.summary(exp), step=step, total=len(steps), instruction=steps[step],
                   has_next=step + 1 < len(steps), has_prev=step > 0)


TOOLS = {
    "experiment_search": experiment_search,
    "manual_qa": manual_qa,
    "program_explainer": program_explainer,
    "output_verification": output_verification,
    "error_diagnosis": error_diagnosis,
    "viva_generator": viva_generator,
    "experiment_guide": experiment_guide,
}
