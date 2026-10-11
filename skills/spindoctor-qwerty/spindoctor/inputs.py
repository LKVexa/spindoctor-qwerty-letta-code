# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Structured input attachments (q.input) and folder-file compilation - a port of SpinDoctor 3.1.2
SpinDoctorInputs.cs and SpinDoctorPdfInputs.cs.

Attachments are inert UTF-8 (or PDF) data.  Parsing never executes terminal commands, source code,
includes, shell statements or instructions found in document text.  Classical simulation only.
"""
import hashlib
import json
import math
import os
import re
import uuid
import zlib
import datetime

from .register import GATE_SPECS
from .calculators import parse_fields, check_fields, split_list, unquote

MAX_BYTES = 5 * 1024 * 1024
MAX_FILES = 32
MAX_TOTAL_BYTES = 30 * 1024 * 1024
MAX_PDF_BYTES = 4194304
FOLDER_FILE_BYTES = 4194304
MAX_SEQUENCE_COMMANDS = 128
MAX_COMMAND_CHARS = 4096


class MissingVariable(ValueError):
    def __init__(self, name):
        ValueError.__init__(self, "Missing parameter binding: " + name)


def _utc():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f0Z")


def sha256_hex(b):
    return hashlib.sha256(b).hexdigest()


def _finite(v):
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError("Equation result must be finite.")


# ----------------------------------------------------------------------------- safe arithmetic
class SafeExpression(object):
    FUNCS = ("sin", "cos", "tan", "sqrt", "exp", "log", "abs", "asin", "acos", "atan")

    def __init__(self, text, variables, syntax_only):
        if text is None or not str(text).strip() or len(text) > 1024:
            raise ValueError("Arithmetic expressions require 1..1024 characters.")
        self.t = text; self.vars = variables; self.syntax = syntax_only; self.p = 0; self.depth = 0; self.ops = 0

    @staticmethod
    def validate(expr):
        SafeExpression(expr, None, True).parse()

    @staticmethod
    def evaluate(expr, bindings):
        return SafeExpression(expr, bindings, False).parse()

    def parse(self):
        v = self.add(); self.white()
        if self.p != len(self.t): raise ValueError("Unexpected arithmetic token at character " + str(self.p) + ".")
        if not self.syntax: _finite(v)
        return v

    def add(self):
        v = self.mul()
        while True:
            if self.eat("+"): r = self.mul(); v = self.val(v + r)
            elif self.eat("-"): r = self.mul(); v = self.val(v - r)
            else: return v

    def mul(self):
        v = self.unary()
        while True:
            if self.eat("*"): r = self.unary(); v = self.val(v * r)
            elif self.eat("/"):
                r = self.unary()
                if self.syntax: v = self.val(0.0)
                else:
                    if r == 0: raise ValueError("Equation result must be finite.")
                    v = self.val(v / r)
            else: return v

    def unary(self):
        self.depth += 1
        if self.depth > 32: raise ValueError("Arithmetic expression nesting limit exceeded.")
        try:
            if self.eat("+"): return self.unary()
            if self.eat("-"): return self.val(-self.unary())
            return self.power()
        finally:
            self.depth -= 1

    def power(self):
        v = self.atom()
        if self.eat("^"):
            pw = self.unary()
            if self.syntax: v = self.val(0.0)
            else:
                try: v = self.val(math.pow(v, pw))
                except (OverflowError, ValueError): raise ValueError("Equation result must be finite.")
        return v

    def atom(self):
        self.white()
        if self.eat("("):
            v = self.add()
            if not self.eat(")"): raise ValueError("Missing arithmetic closing parenthesis.")
            return v
        if self.p >= len(self.t): raise ValueError("Unexpected end of arithmetic expression.")
        ch = self.t[self.p]
        if ch.isdigit() or ch == ".":
            start = self.p; digit = False
            while self.p < len(self.t) and self.t[self.p].isdigit(): digit = True; self.p += 1
            if self.p < len(self.t) and self.t[self.p] == ".":
                self.p += 1
                while self.p < len(self.t) and self.t[self.p].isdigit(): digit = True; self.p += 1
            if not digit: raise ValueError("Invalid numeric literal.")
            if self.p < len(self.t) and self.t[self.p] in "eE":
                self.p += 1
                if self.p < len(self.t) and self.t[self.p] in "+-": self.p += 1
                e = self.p
                while self.p < len(self.t) and self.t[self.p].isdigit(): self.p += 1
                if self.p == e: raise ValueError("Invalid numeric exponent.")
            try: n = float(self.t[start:self.p])
            except ValueError: raise ValueError("Invalid numeric literal.")
            _finite(n); return n
        if ch.isalpha() or ch == "_":
            start = self.p; self.p += 1
            while self.p < len(self.t) and (self.t[self.p].isalnum() or self.t[self.p] == "_"): self.p += 1
            name = self.t[start:self.p]
            if self.eat("("):
                v = self.add()
                if not self.eat(")"): raise ValueError("Function requires one arithmetic argument.")
                fn = name.lower()
                if fn not in self.FUNCS: raise ValueError("Unsupported arithmetic function: " + name)
                if self.syntax: return 0.0
                try:
                    if fn == "sin": r = math.sin(v)
                    elif fn == "cos": r = math.cos(v)
                    elif fn == "tan": r = math.tan(v)
                    elif fn == "sqrt": r = math.sqrt(v)
                    elif fn == "exp": r = math.exp(v)
                    elif fn == "log": r = math.log(v)
                    elif fn == "abs": r = abs(v)
                    elif fn == "asin": r = math.asin(v)
                    elif fn == "acos": r = math.acos(v)
                    else: r = math.atan(v)
                except (ValueError, OverflowError):
                    raise ValueError("Equation result must be finite.")
                return self.val(r)
            if name == "pi": return math.pi
            if name == "e": return math.e
            if self.syntax: parameter_name(name); return 0.0
            if self.vars is None or name not in self.vars: raise MissingVariable(name)
            _finite(self.vars[name]); return self.vars[name]
        raise ValueError("Unsupported arithmetic character: " + ch)

    def val(self, v):
        self.ops += 1
        if self.ops > 512: raise ValueError("Arithmetic expression operation limit exceeded.")
        if not self.syntax: _finite(v)
        return 0.0 if self.syntax else v

    def white(self):
        while self.p < len(self.t) and self.t[self.p].isspace(): self.p += 1

    def eat(self, tok):
        self.white()
        if self.p < len(self.t) and self.t[self.p] == tok:
            self.p += 1; return True
        return False


# ----------------------------------------------------------------------------- small validators
def circuit_name(name):
    if name is None or not re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,31}\Z", name):
        raise ValueError("Circuit names use an ASCII letter followed by up to 31 letters/digits/-/_.")
    return name


def parameter_name(name):
    if name is None or not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}\Z", name) or name in ("pi", "e"):
        raise ValueError("Parameter names are identifiers up to 64 characters; pi/e are reserved constants.")
    return name


def _int(value, lo, hi):
    s = str(value)
    if not re.match(r"^[0-9]+\Z", s) or not (lo <= int(s) <= hi):
        raise ValueError("Integer is outside the supported range.")
    return int(s)


def _basis_index(value):
    s = str(value)
    if not s or not re.match(r"^[0-9]+\Z", s): raise ValueError("Expected a nonnegative decimal basis index.")
    return int(s)


def _unsigned(value):
    s = str(value)
    if not re.match(r"^[0-9]+\Z", s) or int(s) > 18446744073709551615:
        raise ValueError("Expected an unsigned decimal integer.")
    return int(s)


def _basis(b):
    b = str(b).lower()
    if b not in ("x", "y", "z"): raise ValueError("Measurement basis must be x/y/z.")
    return b


def _text(v):
    if v is None: raise ValueError("Required value is null.")
    if isinstance(v, bool): return "True" if v else "False"
    if isinstance(v, float):
        return repr(v) if v != int(v) or abs(v) >= 1e16 else str(int(v))
    return str(v)


def _expr_text(v):
    if v is None or isinstance(v, (bool, dict, list)):
        raise ValueError("Angle/parameter must be a finite number or safe arithmetic expression string.")
    return _text(v)


def _alias(name):
    name = name.lower()
    return {"cnot": "cx", "toffoli": "ccx", "fredkin": "cswap", "id": "i", "identity": "i", "u3": "u"}.get(name, name)


def _gate_spec(name):
    s = GATE_SPECS.get(name)
    if s is None: raise ValueError("Unsupported gate name: " + name)
    return s


def known_text_gate(word):
    try:
        _gate_spec(_alias(word)); return True
    except Exception:  # noqa: BLE001
        return False


def _clip(word):
    v = word or ""
    if len(v) > 40: v = v[:40] + "..."
    return "'" + v + "'"


def validate_filename(filename):
    if not filename or len(filename) > 180 or filename != os.path.basename(filename) or filename in (".", ".."):
        raise ValueError("Filename must be a plain attachment name without a path.")
    for ch in filename:
        if ord(ch) < 32 or ch in '/\\:<>"|?*' or ord(ch) == 127:
            raise ValueError("Invalid attachment filename character.")


def _ext(name):
    return os.path.splitext(name)[1].lower()


class Plan(object):
    def __init__(self, fmt, name=None):
        self.format = fmt; self.name = name; self.qubits = 0; self.shots = 1; self.initial = 0; self.basis = "z"
        self.parameters = {}; self.gates = []; self.warnings = []; self.columns = None; self.rows = None; self.script = None


def _gate(name, angles, qubits, all_, n):
    name = _alias(name); spec = _gate_spec(name)
    if len(angles) != spec["angleCount"]: raise ValueError("Incorrect angle count for gate " + name + ".")
    if all_ and not spec["local"]: raise ValueError("all applies only to local gates.")
    if (not all_ and len(qubits) != spec["targetCount"]) or (all_ and len(qubits) != 0):
        raise ValueError("Incorrect qubit count for gate " + name + ".")
    seen = set()
    for q in qubits:
        if q < 0 or q >= n or q in seen: raise ValueError("Gate targets must be distinct and within the selected register.")
        seen.add(q)
    for a in angles: SafeExpression.validate(a)
    return {"name": name, "angles": list(angles), "qubits": list(qubits), "all": bool(all_)}


def _validate_plan(p):
    if p.qubits < 1 or p.qubits > 298 or p.initial >= (1 << p.qubits):
        raise ValueError("Circuit requires1..298 qubits and initialBasis below2^qubits.")
    if len(p.gates) > 8192: raise ValueError("Circuit exceeds 8192 instructions.")


def _default_name(filename, entry_id):
    base = os.path.splitext(filename)[0]
    try:
        return circuit_name(base)
    except ValueError:
        return "imported-" + entry_id[:8]


ALLOWED_SCRIPT = set("q.prepare q.migrate q.state q.gate q.verify q.measure q.status q.export q.tranche q.circuit q.math q.query q.noise q.qec q.compile q.resource q.model q.lesson q.algorithm q.preset q.help".split())


def script(commands, fmt):
    if len(commands) < 1 or len(commands) > MAX_SEQUENCE_COMMANDS:
        raise ValueError("Input sequences contain 1..128 commands.")
    out = []
    for c in commands:
        c = c.strip()
        if len(c) < 1 or len(c) > MAX_COMMAND_CHARS or "\n" in c or "\r" in c:
            raise ValueError("Each sequence entry is one bounded terminal command.")
        w = c.split()
        if w[0].lower() not in ALLOWED_SCRIPT:
            raise ValueError("Input sequences accept documented quantum commands only; shell, file-management and nested folder/input commands are refused.")
        if len(w) > 1 and w[1].lower() in ("delete", "reset"):
            raise ValueError("Input sequences do not delete/reset existing user state.")
        out.append(c)
    p = Plan(fmt); p.script = out
    return p


def parse_json(content, filename, entry_id):
    try:
        data = json.loads(content)
    except ValueError as e:
        raise ValueError("Invalid JSON: " + str(e))
    if not isinstance(data, dict): raise ValueError("JSON circuit must be an object.")
    if "commands" in data:
        for k in data:
            if k not in ("commands", "schema", "description"):
                raise ValueError("Sequence JSON only accepts commands, schema and description.")
        if not isinstance(data["commands"], list): raise ValueError("Expected an array.")
        cmds = []
        for v in data["commands"]:
            if not isinstance(v, str): raise ValueError("Sequence commands must be strings.")
            cmds.append(v)
        return script(cmds, "json-sequence")
    for k in data:
        if k not in ("name", "qubits", "initialBasis", "parameters", "gates", "shots", "basis", "description", "hints", "schema"):
            raise ValueError("Unsupported JSON circuit field: " + k)
    if "qubits" not in data: raise ValueError("Missing field: qubits")
    p = Plan("json", circuit_name(_text(data["name"])) if "name" in data else _default_name(filename, entry_id))
    p.qubits = _int(_text(data["qubits"]), 1, 298)
    if "initialBasis" in data: p.initial = _basis_index(_text(data["initialBasis"]))
    if "shots" in data: p.shots = _int(_text(data["shots"]), 1, 100000)
    if "basis" in data: p.basis = _basis(_text(data["basis"]))
    if "hints" in data:
        h = data["hints"]
        if not isinstance(h, dict): raise ValueError("hints must be a JSON object.")
        for k in h:
            if k not in ("shots", "basis"): raise ValueError("Unsupported circuit hint: " + k)
        if "shots" in h: p.shots = _int(_text(h["shots"]), 1, 100000)
        if "basis" in h: p.basis = _basis(_text(h["basis"]))
    if "parameters" in data:
        params = data["parameters"]
        if not isinstance(params, dict): raise ValueError("parameters must be a JSON object.")
        if len(params) > 64: raise ValueError("At most 64 declared parameters are supported.")
        for k, v in params.items():
            name = parameter_name(k); expr = None if v is None else _expr_text(v)
            if expr is not None: SafeExpression.validate(expr)
            p.parameters[name] = expr
    if "gates" not in data: raise ValueError("Missing field: gates")
    if not isinstance(data["gates"], list): raise ValueError("Expected an array.")
    for g in data["gates"]:
        if len(p.gates) >= 8192: raise ValueError("At most 8192 circuit instructions are supported.")
        if not isinstance(g, dict): raise ValueError("gate must be a JSON object.")
        for k in g:
            if k not in ("name", "angles", "qubits", "all"): raise ValueError("Unsupported gate field: " + k)
        angles = [_expr_text(a) for a in (g["angles"] if isinstance(g.get("angles"), list) else ([] if "angles" not in g else _bad_array()))]
        qubits = [_int(_text(q), 0, p.qubits - 1) for q in (g["qubits"] if isinstance(g.get("qubits"), list) else ([] if "qubits" not in g else _bad_array()))]
        all_ = False
        if "all" in g:
            if not isinstance(g["all"], bool): raise ValueError("all must be a JSON boolean.")
            all_ = g["all"]
        if all_ and qubits: raise ValueError("Gate all and explicit qubits are mutually exclusive.")
        if "name" not in g: raise ValueError("Missing field: name")
        p.gates.append(_gate(_text(g["name"]), angles, qubits, all_, p.qubits))
    _validate_plan(p)
    return p


def _bad_array():
    raise ValueError("Expected an array.")


def parse_text(content, filename, entry_id):
    p = Plan("text-circuit", _default_name(filename, entry_id)); gates = []; declared = named = False
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    line_no = content_lines = first_line = 0; first_word = None
    for raw in lines:
        line_no += 1; line = raw.strip()
        if not line or line.startswith("#") or line.startswith("//"): continue
        content_lines += 1
        if len(line) > 8192: raise ValueError("Text circuit line exceeds 8192 characters.")
        w = re.split(r"\s+", line); start = 0; head = w[0].lower()
        if head == "q.circuit":
            if len(w) < 2: raise ValueError("Incomplete q.circuit data line.")
            sub = w[1].lower()
            if sub == "new":
                if len(w) != 4 or declared: raise ValueError("Use exactly one q.circuit new NAME QUBITS declaration.")
                p.name = circuit_name(w[2]); p.qubits = _int(w[3], 1, 298); declared = named = True; continue
            if sub == "input":
                if len(w) != 3: raise ValueError("Use q.circuit input BASIS_INDEX.")
                p.initial = _basis_index(w[2]); continue
            if sub != "add":
                raise ValueError("Text attachments permit q.circuit new/input/add data only; run, delete, other terminal commands and shell statements are rejected.")
            start = 2
        elif head == "qubits":
            if len(w) != 2 or declared: raise ValueError("Declare qubits exactly once.")
            p.qubits = _int(w[1], 1, 298); declared = True; continue
        elif head == "name":
            if len(w) != 2 or named: raise ValueError("Declare a circuit name at most once.")
            p.name = circuit_name(w[1]); named = True; continue
        elif head == "input":
            if len(w) != 2: raise ValueError("Use input BASIS_INDEX.")
            p.initial = _basis_index(w[1]); continue
        elif head == "shots":
            if len(w) != 2: raise ValueError("Use shots N.")
            p.shots = _int(w[1], 1, 100000); continue
        elif head == "basis":
            if len(w) != 2: raise ValueError("Use basis x|y|z.")
            p.basis = _basis(w[1]); continue
        elif head in ("param", "parameter"):
            decl = line[len(w[0]):].strip(); eqi = decl.find("=")
            if eqi < 1 or eqi == len(decl) - 1: raise ValueError("Use param NAME=EXPRESSION.")
            name = parameter_name(decl[:eqi].strip()); expr = decl[eqi + 1:].strip(); SafeExpression.validate(expr)
            if len(p.parameters) >= 64 or name in p.parameters: raise ValueError("Duplicate parameter or parameter limit exceeded.")
            p.parameters[name] = expr; continue
        elif head == "gate":
            start = 1
        if len(gates) >= 8192: raise ValueError("At most 8192 text gate instructions are supported.")
        ops = w[start:]; gates.append(ops)
        if first_word is None:
            first_word = ops[0] if ops else ""; first_line = line_no
    if not declared and content_lines == 0:
        raise ValueError("Text input is empty: every line is blank or a # or // comment. Add q.* command lines (command file) or qubits N plus gate lines (text circuit).")
    if not declared and first_word is not None and not known_text_gate(first_word):
        raise ValueError("Text input line " + str(first_line) + " is neither a q.* command nor a known gate (" + _clip(first_word) + "). Command files need q.* lines; text circuits need qubits N (or q.circuit new NAME N) and gate lines. Prose and Markdown fences are not accepted.")
    if not declared: raise ValueError("Text circuit requires qubits N or q.circuit new NAME N.")
    for w in gates:
        if not w: raise ValueError("Missing gate name.")
        name = _alias(w[0]); spec = _gate_spec(name); ac = spec["angleCount"]; qc = spec["targetCount"]
        all_ = len(w) == ac + 2 and w[-1].lower() == "all"
        if len(w) != 1 + ac + (1 if all_ else qc):
            raise ValueError("Incorrect gate angle/target count. Text angle expressions must be single tokens; angles precede targets.")
        angles = w[1:1 + ac]; qubits = [] if all_ else [_int(w[1 + ac + j], 0, p.qubits - 1) for j in range(qc)]
        p.gates.append(_gate(name, angles, qubits, all_, p.qubits))
    _validate_plan(p)
    return p


def _strip_comments(content):
    out = []; quote = False; j = 0; n = len(content)
    while j < n:
        ch = content[j]
        if ch == '"':
            quote = not quote; out.append(ch); j += 1; continue
        if not quote and ch == "/" and j + 1 < n and content[j + 1] == "/":
            while j < n and content[j] != "\n": j += 1
            out.append("\n"); j += 1; continue
        if not quote and ch == "/" and j + 1 < n and content[j + 1] == "*":
            j += 2; ended = False
            while j + 1 < n:
                if content[j] == "*" and content[j + 1] == "/":
                    j += 1; ended = True; break
                j += 1
            if not ended: raise ValueError("Unterminated QASM block comment.")
            out.append(" "); j += 1; continue
        out.append(ch); j += 1
    if quote: raise ValueError("Unterminated QASM quote.")
    return "".join(out)


def _qasm_index(operand, name, width):
    m = re.match("^" + re.escape(name) + r"\s*\[\s*([0-9]+)\s*\]$", operand)
    if not m: raise ValueError("Only the declared register and indexed qubits are accepted: " + operand)
    return _int(m.group(1), 0, width - 1)


def _split_args(value):
    args = []; depth = 0; start = 0
    for j, ch in enumerate(value):
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        elif ch == "," and depth == 0:
            args.append(value[start:j].strip()); start = j + 1
        if depth < 0: raise ValueError("Unbalanced QASM parameter parentheses.")
    if depth != 0: raise ValueError("Unbalanced QASM parameter parentheses.")
    args.append(value[start:].strip())
    return args


def parse_qasm(content, filename, entry_id):
    p = Plan("openqasm2", _default_name(filename, entry_id))
    p.warnings.append("Supported QASM gates use SpinDoctor/Qiskit standard-gate matrix phase conventions. Alternate include definitions and custom gate definitions are unsupported.")
    stm = _strip_comments(content).split(";")
    quantum = classical = None; header = started = measuring = False; measured = set()
    for idx, s in enumerate(stm):
        s = s.strip()
        if not s: continue
        if idx == len(stm) - 1: raise ValueError("OpenQASM2 statements must end with semicolons.")
        if not header:
            if s != "OPENQASM 2.0": raise ValueError("Require OPENQASM 2.0 header.")
            header = True; continue
        if s.startswith("include"):
            if started or not re.match(r'^include\s+"qelib1\.inc"$', s):
                raise ValueError('Only include "qelib1.inc" is recognized symbolically; external includes are never read.')
            continue
        m = re.match(r"^(qreg|creg)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*([0-9]+)\s*\]$", s)
        if m:
            if started: raise ValueError("Registers must be declared before gates.")
            width = _int(m.group(3), 1, 298)
            if m.group(1) == "qreg":
                if quantum is not None: raise ValueError("Supported QASM2 subset has one qreg of1..298 qubits.")
                quantum = m.group(2); p.qubits = width
            else:
                if classical is not None or quantum is None or width != p.qubits or m.group(2) == quantum:
                    raise ValueError("Supported creg must follow qreg and have the same width and a distinct name.")
                classical = m.group(2)
            continue
        if quantum is None: raise ValueError("Declare qreg before gate or measurement statements.")
        started = True
        if s.startswith("measure"):
            if classical is None: raise ValueError("Final measurement requires a matching creg.")
            measuring = True
            mm = re.match(r"^measure\s+(.+?)\s*->\s*(.+)$", s)
            if not mm: raise ValueError("Invalid measure statement.")
            q = mm.group(1).strip(); c = mm.group(2).strip()
            if q == quantum and c == classical:
                if measured: raise ValueError("Duplicate final measurement.")
                measured.update(range(p.qubits))
            else:
                qb = _qasm_index(q, quantum, p.qubits); cb = _qasm_index(c, classical, p.qubits)
                if qb != cb or qb in measured:
                    raise ValueError("Final indexed measurements must map each qubit to the same classical index exactly once.")
                measured.add(qb)
            continue
        if measuring: raise ValueError("Mid-circuit measurement is unsupported; measurements must form the final complete group.")
        if s.startswith("barrier"):
            args = s[7:].strip()
            if not args: raise ValueError("Barrier needs a register/targets.")
            for t in args.split(","):
                if t.strip() != quantum: _qasm_index(t.strip(), quantum, p.qubits)
            msg = "QASM barriers are presentation markers and produce no state-operation credit."
            if msg not in p.warnings: p.warnings.append(msg)
            continue
        if re.match(r"^(reset|if|gate|opaque|snapshot)\b", s):
            raise ValueError("Unsupported QASM2 statement (reset/if/custom gate/opaque/snapshot). Only supported unitary gates and final complete measurements are accepted.")
        op = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?\s+(.+)$", s, re.S)
        if not op: raise ValueError("Invalid or unsupported QASM2 gate statement.")
        name = _alias(op.group(1)); angles = _split_args(op.group(2)) if op.group(2) is not None else []
        if name == "u1": name = "p"
        elif name == "u2":
            if len(angles) != 2: raise ValueError("u2 requires two angles.")
            name = "u"; angles.insert(0, "pi/2")
        elif name == "cu1": name = "cp"
        elif name == "cu3":
            if len(angles) != 3: raise ValueError("cu3 requires three angles.")
            name = "cu"; angles.append("0")
        operands = op.group(3).split(","); all_ = len(operands) == 1 and operands[0].strip() == quantum
        qubits = [] if all_ else [_qasm_index(o.strip(), quantum, p.qubits) for o in operands]
        if len(p.gates) >= 8192: raise ValueError("At most 8192 QASM gate instructions are supported.")
        p.gates.append(_gate(name, angles, qubits, all_, p.qubits))
    if not header or quantum is None: raise ValueError("Missing QASM2 header/qreg.")
    if measuring and len(measured) != p.qubits: raise ValueError("Final measurements must cover every qubit exactly once.")
    if measuring: p.warnings.append("Final QASM Z measurements are recorded as a basis hint; importing never runs or measures the circuit.")
    _validate_plan(p)
    return p


def csv_rows(content, max_cell):
    rows = []; row = []; cell = []; quoted = closed = False; j = 0; n = len(content)
    while j <= n:
        ch = "\n" if j == n else content[j]
        if quoted:
            if j == n: raise ValueError("Unterminated CSV quoted cell.")
            if ch == '"':
                if j + 1 < n and content[j + 1] == '"':
                    cell.append('"'); j += 1
                else:
                    quoted = False; closed = True
            else:
                cell.append(ch)
        elif ch == '"':
            if cell or closed: raise ValueError("CSV quote must begin a cell.")
            quoted = True
        elif ch in ",\n\r":
            row.append("".join(cell)); cell = []; closed = False
            if ch != ",":
                if not (len(row) == 1 and not row[0].strip()): rows.append(row)
                row = []
                if ch == "\r" and j + 1 < n and content[j + 1] == "\n": j += 1
                if len(rows) > 4097: raise ValueError("CSV parameter sweep exceeds 4096 rows.")
        else:
            if closed and not ch.isspace(): raise ValueError("Unexpected data after a CSV closing quote.")
            if not closed: cell.append(ch)
        if len(cell) > max_cell: raise ValueError("CSV cell exceeds " + str(max_cell) + " characters.")
        if len(row) > 64: raise ValueError("CSV has more than 64 columns.")
        j += 1
    return rows


def _cell_list(text, label):
    text = text.strip()
    if len(text) < 2 or text[0] != "[" or text[-1] != "]": raise ValueError(label + " requires a bracketed comma-separated list.")
    cells = split_list(text)
    if not cells: raise ValueError(label + " cannot be empty.")
    out = []
    for c in cells:
        c = unquote(c.strip())
        if not c: raise ValueError(label + " contains an empty entry.")
        out.append(c)
    return out


def _gate_csv_list(text):
    text = text.strip()
    if not text: return []
    return _cell_list(text if text[0] == "[" else "[" + text + "]", "CSV gate operand list")


def parse_gate_csv(rows, filename, entry_id):
    if len(rows) < 2: raise ValueError("Gate-list CSV requires header gate,n,targets,angles and at least one gate row.")
    cols = {}; allowed = set("gate n targets angles name initialbasis shots basis".split())
    for j, h in enumerate(rows[0]):
        name = h.strip()
        if name.lower() not in allowed:
            raise ValueError("Unknown gate-list CSV column: " + name + ". Use gate,n,targets,angles with optional name,initialBasis,shots,basis.")
        if name.lower() in cols: raise ValueError("Duplicate gate-list CSV header: " + name + ".")
        cols[name.lower()] = j
    for k in ("gate", "n", "targets", "angles"):
        if k not in cols: raise ValueError("Gate-list CSV requires columns gate,n,targets,angles.")
    for r in rows[1:]:
        if len(r) != len(rows[0]): raise ValueError("Gate-list CSV row width differs from its header.")
    if not rows[1][cols["n"]].strip(): raise ValueError("Declare the register size n in the first gate-list CSV row.")
    p = Plan("csv-gates", _default_name(filename, entry_id)); p.shots = 1024; p.qubits = _int(rows[1][cols["n"]].strip(), 1, 298)
    meta = {}
    for r in rows[1:]:
        for f in ("n", "name", "initialbasis", "shots", "basis"):
            if f not in cols: continue
            v = r[cols[f]].strip()
            if not v: continue
            if f == "n": c = str(_int(v, 1, 298))
            elif f == "name": c = circuit_name(v)
            elif f == "initialbasis": c = str(_basis_index(v))
            elif f == "shots": c = str(_int(v, 1, 100000))
            else: c = _basis(v)
            if f in meta and meta[f] != c: raise ValueError("Gate-list CSV circuit metadata must be consistent across rows: " + f + ".")
            meta[f] = c
    if "name" in meta: p.name = meta["name"]
    if "initialbasis" in meta: p.initial = int(meta["initialbasis"])
    if "shots" in meta: p.shots = int(meta["shots"])
    if "basis" in meta: p.basis = meta["basis"]
    for r in rows[1:]:
        name = r[cols["gate"]].strip(); tt = r[cols["targets"]].strip()
        angles = _gate_csv_list(r[cols["angles"]]); all_ = tt.lower() == "all"
        targets = [] if all_ else _gate_csv_list(tt)
        p.gates.append(_gate(name, angles, [_int(t, 0, p.qubits - 1) for t in targets], all_, p.qubits))
    _validate_plan(p)
    p.warnings.append("CSV gate rows are explicit ordered circuit data. Upload and import do not run; q.input run uses declared shots/basis (default 1024 shots in Z), with native job barriers. Classical simulation, not physical quantum hardware.")
    return p


def parse_param_csv(content):
    rows = csv_rows(content, 1024)
    if len(rows) < 2:
        raise ValueError("CSV requires a command header and command rows, or a parameter header and at least one data row with an explicit base circuit.")
    cols = rows[0]
    if not cols or len(cols) > 64: raise ValueError("CSV supports 1..64 parameter columns.")
    seen = set()
    for j in range(len(cols)):
        cols[j] = parameter_name(cols[j].strip())
        if cols[j] in seen: raise ValueError("Duplicate CSV parameter column.")
        seen.add(cols[j])
    rows = rows[1:]
    if len(rows) > 4096: raise ValueError("CSV parameter sweeps support at most 4096 rows.")
    for r in rows:
        if len(r) != len(cols): raise ValueError("CSV row width differs from the header.")
        for j in range(len(r)):
            r[j] = r[j].strip(); SafeExpression.validate(r[j])
    p = Plan("csv-parameters"); p.columns = cols; p.rows = rows
    return p


def parse_content(filename, content, entry_id, pdf_bytes=None):
    """Port of InputAttachmentManager.Parse: dispatch by extension."""
    if content and content[0] == "\ufeff": content = content[1:]
    ext = _ext(filename)
    if ext == ".pdf":
        ex = pdf_extract(pdf_bytes)
        p = parse_content(ex["filename"], ex["content"], entry_id)
        p.format = "pdf/" + p.format; p.warnings.append("PDF source imported using " + ex["method"] + ". Only the explicit program is interpreted.")
        return p
    if ext == ".json": return parse_json(content, filename, entry_id)
    if ext in (".qasm", ".qasm2"): return parse_qasm(content, filename, entry_id)
    if ext == ".csv":
        rows = csv_rows(content, 4096)
        if rows and len(rows[0]) == 1 and rows[0][0].strip().lower() == "command":
            cmds = []
            for r in rows[1:]:
                if len(r) != 1:
                    raise ValueError("Command CSV requires exactly one column headed command. Quote any command containing commas, and double each literal quote.")
                cmds.append(r[0])
            return script(cmds, "csv-sequence")
        if rows:
            headers = set(c.strip().lower() for c in rows[0])
            if {"gate", "n", "targets", "angles"} <= headers: return parse_gate_csv(rows, filename, entry_id)
        return parse_param_csv(content)
    if ext in (".txt", ".circuit"):
        is_script = "spindoctor-sequence" in content.lower()
        for raw in content.replace("\r", "\n").split("\n"):
            line = raw.strip(); low = line.lower()
            if low.startswith("q.") and not low.startswith("q.circuit new ") and not low.startswith("q.circuit add ") and not low.startswith("q.circuit input "):
                is_script = True
        if is_script:
            cmds = [l.strip() for l in content.replace("\r", "\n").split("\n") if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("//")]
            return script(cmds, "txt-sequence")
        return parse_text(content, filename, entry_id)
    raise ValueError("Unsupported input format. Use JSON, QASM, TXT, CSV, or a PDF containing one embedded/explicitly tagged program. Scans and prose are not executable equations.")


def resolve(defs, bindings, allow_missing):
    values = dict(bindings or {})
    for v in values.values(): _finite(v)
    pending = [k for k in defs if k not in values]
    for _ in range(len(defs) + 1):
        if not pending: break
        changed = False
        for name in list(pending):
            if defs[name] is None: continue
            try:
                values[name] = SafeExpression.evaluate(defs[name], values); pending.remove(name); changed = True
            except MissingVariable:
                pass
        if not changed: break
    if pending and not allow_missing:
        raise MissingVariable(",".join(pending) + " (undefined or cyclic parameter equations)")
    return values


def resolved_gates(plan, params, limit=None):
    out = []
    for i, g in enumerate(plan.gates):
        angles = []
        for a in g["angles"]:
            v = SafeExpression.evaluate(a, params)
            if abs(v) > 1e12: raise ValueError("Gate angle exceeds +/-1e12 radians.")
            angles.append(v)
        if limit is None or i < limit:
            out.append({"name": g["name"], "angles": angles, "qubits": g["qubits"], "all": g["all"]})
    return out


# ----------------------------------------------------------------------------- PDF (bounded reader)
def _latin(b):
    return b.decode("latin-1")


def _decode_literal(raw):
    out = []; i = 0; n = len(raw)
    while i < n:
        c = raw[i]
        if c != "\\":
            out.append(c); i += 1; continue
        i += 1
        if i >= n: break
        c = raw[i]
        if c == "n": out.append("\n")
        elif c == "r": out.append("\r")
        elif c == "t": out.append("\t")
        elif c in "\r\n":
            if c == "\r" and i + 1 < n and raw[i + 1] == "\n": i += 1
        elif "0" <= c <= "7":
            v = ord(c) - 48
            for _ in range(2):
                if i + 1 < n and "0" <= raw[i + 1] <= "7":
                    i += 1; v = v * 8 + ord(raw[i]) - 48
            out.append(chr(v & 0xFF))
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _stream_bytes(body, budget):
    m = re.search(r"\bstream(?=\r|\n)", body)
    if not m: raise ValueError("PDF stream missing.")
    at = m.start(); start = at + 6
    if start < len(body) and body[start] == "\r": start += 1
    if start < len(body) and body[start] == "\n": start += 1
    end = body.rfind("endstream")
    if end < start: raise ValueError("PDF stream terminator missing.")
    length = end - start
    d = re.search(r"/Length\s+(\d+)\s*(?:/|>>|\r|\n)", body[:at])
    if d:
        exact = int(d.group(1))
        if exact > length: raise ValueError("PDF declared stream length is invalid.")
        length = exact
        if not body[start + length:].lstrip("\r\n").startswith("endstream"):
            raise ValueError("PDF stream length does not reach its terminator.")
    else:
        if length > 0 and body[start + length - 1] == "\n": length -= 1
        if length > 0 and body[start + length - 1] == "\r": length -= 1
    data = body[start:start + length].encode("latin-1"); dct = body[:at]
    if "/Filter" not in dct:
        budget[0] += len(data)
        if budget[0] > 16777216: raise ValueError("PDF aggregate decoded-stream budget exceeds 16MiB. Export a smaller program-only PDF.")
        if len(data) > 2097152: raise ValueError("PDF program/text stream exceeds 2MiB.")
        return data
    f = re.search(r"/Filter\s*(/\w+|\[[^]]*\])", dct)
    if not f or not re.match(r"^(?:/FlateDecode|\[\s*/FlateDecode\s*\])\Z", f.group(1)):
        raise ValueError("PDF stream filter unsupported. Use one FlateDecode filter or an uncompressed embedded program.")
    if "/DecodeParms" in dct and not re.search(r"/DecodeParms\s+null\b", dct):
        raise ValueError("PDF stream predictors/decode parameters are unsupported.")
    if len(data) < 6: raise ValueError("Invalid compressed PDF stream.")
    if (data[0] & 15) != 8 or (data[0] >> 4) > 7 or ((data[0] << 8) + data[1]) % 31 != 0 or (data[1] & 32) != 0:
        raise ValueError("Invalid/unsupported zlib PDF stream header.")
    dec = zlib.decompressobj()
    try:
        out = dec.decompress(data, 2097153)
    except zlib.error:
        raise ValueError("PDF compressed stream checksum mismatch.")
    if len(out) > 2097152 or dec.unconsumed_tail: raise ValueError("Decompressed PDF stream exceeds 2MiB.")
    if not dec.eof: raise ValueError("PDF compressed stream checksum mismatch.")
    budget[0] += len(out)
    if budget[0] > 16777216: raise ValueError("PDF aggregate decoded-stream budget exceeds 16MiB. Export a smaller program-only PDF.")
    return out


def _text_literals(decoded):
    result = []; objects = 0; in_text = False; p = 0; n = len(decoded)
    while p < n:
        c = decoded[p]
        if c.isspace(): p += 1; continue
        if c == "%":
            while p < n and decoded[p] not in "\r\n": p += 1
            continue
        if c == "/":
            p += 1
            while p < n and not decoded[p].isspace() and decoded[p] not in "()[]<>{}/%": p += 1
            continue
        if c == "(":
            p += 1; begin = p; depth = 1
            while p < n and depth > 0:
                c = decoded[p]
                if c == "\\": p += 2; continue
                if c == "(":
                    depth += 1
                    if depth > 32: raise ValueError("PDF literal nesting exceeds 32.")
                elif c == ")": depth -= 1
                p += 1
            if depth != 0: raise ValueError("PDF text literal is unclosed.")
            if in_text: result.append(_decode_literal(decoded[begin:p - 1]))
            continue
        if c == "<" and p + 1 < n and decoded[p + 1] != "<":
            p += 1
            while p < n and decoded[p] != ">": p += 1
            if p < n: p += 1
            continue
        if c in "[]<>{}": p += 1; continue
        start = p
        while p < n and not decoded[p].isspace() and decoded[p] not in "()[]<>{}/%": p += 1
        if p == start: p += 1; continue
        tok = decoded[start:p]
        if tok == "BT": in_text = True; objects += 1
        elif tok == "ET": in_text = False
    return result, objects


def pdf_extract(data):
    """Port of SpinDoctorPdfInputs.Extract: one embedded UTF-8 program or one SPINDOCTOR-*-BEGIN/END block."""
    if data is None or len(data) < 8 or len(data) > MAX_PDF_BYTES or data[:5] != b"%PDF-":
        raise ValueError("PDF inputs require a valid PDF header and at most 4MiB.")
    src = _latin(data)
    if not re.match(r"^%PDF-[12]\.[0-9](?:\r|\n)", src) or not src.rstrip(" \t\r\n\0").endswith("%%EOF"):
        raise ValueError("PDF version/header or final EOF marker is missing.")
    if re.search(r"/Encrypt\b", src): raise ValueError("Encrypted PDFs cannot be imported. Export an unencrypted tagged equation/circuit PDF.")
    objects = {}; search = 0; hdr = re.compile(r"(?m)(\d+)\s+\d+\s+obj\b")
    while search < len(src):
        m = hdr.search(src, search)
        if not m: break
        bs = m.end()
        if len(objects) >= 20000: raise ValueError("PDF object count exceeds the bounded reader.")
        be = src.find("endobj", bs)
        if be < 0: raise ValueError("PDF object terminator is missing.")
        prefix = src[bs:be]; sh = re.search(r"\bstream(?=\r|\n)", prefix)
        if sh:
            ln = re.search(r"/Length\s+(\d+)\s*(?:/|>>|\r|\n)", prefix[:sh.start()])
            if ln:
                exact = int(ln.group(1)); ds = bs + sh.start() + 6
                if ds < len(src) and src[ds] == "\r": ds += 1
                if ds < len(src) and src[ds] == "\n": ds += 1
                if exact > len(src) - ds: raise ValueError("PDF stream length exceeds source bytes.")
                be = src.find("endobj", ds + exact)
                if be < 0: raise ValueError("PDF streamed object terminator is missing.")
        oid = int(m.group(1))
        if oid in objects or oid > 2147483647: raise ValueError("PDF object IDs must be unique bounded integers. Flatten incremental revisions before import.")
        objects[oid] = src[bs:be]; search = be + 6
    if not objects: raise ValueError("PDF contains no readable objects. Compressed object streams are not supported by this bounded program reader.")
    budget = [0]; attached = []
    for body in objects.values():
        if not re.search(r"/Type\s*/Filespec\b", body): continue
        f = re.search(r"/F\s*\(((?:\\.|[^)\\])*)\)", body); ref = re.search(r"/EF\s*<<.*?/F\s+(\d+)\s+\d+\s+R", body, re.S)
        if not f or not ref: continue
        name = _decode_literal(f.group(1))
        if os.path.basename(name) != name or _ext(name) not in (".json", ".qasm", ".txt", ".csv"): continue
        emb = objects.get(int(ref.group(1)))
        if emb is None: raise ValueError("PDF embedded program reference is missing.")
        try:
            content = _stream_bytes(emb, budget).decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("Embedded PDF program is not valid UTF-8.")
        attached.append({"filename": name, "content": content, "method": "embedded UTF-8 program", "textStreams": 0})
    if len(attached) > 1: raise ValueError("PDF has multiple supported embedded programs. Export one program per PDF.")
    if attached: return attached[0]
    text = []; size = 0; streams = 0
    for body in objects.values():
        if re.search(r"/Subtype\s*/Image\b", body) or "stream" not in body: continue
        try:
            d = _stream_bytes(body, budget)
        except ValueError as e:
            if "budget" in str(e): raise
            continue
        lits, objs = _text_literals(_latin(d))
        for lit in lits:
            text.append(lit); size += len(lit) + 1
            if size > 2097152: raise ValueError("PDF extracted text exceeds 2MiB.")
        streams += objs
    content = "\n".join(text) + ("\n" if text else "")
    tagged = []
    for typ in ("JSON", "QASM", "TXT", "CSV"):
        begin = "SPINDOCTOR-" + typ + "-BEGIN"; end = "SPINDOCTOR-" + typ + "-END"; s = 0
        while s < len(content):
            at = content.find(begin, s)
            if at < 0: break
            stop = content.find(end, at + len(begin))
            if stop < 0: raise ValueError("PDF tagged program is missing its END marker.")
            tagged.append({"filename": "pdf-program." + typ.lower(), "content": content[at + len(begin):stop].strip(),
                           "method": "explicit tagged ASCII text", "textStreams": streams})
            s = stop + len(end)
    if len(tagged) > 1: raise ValueError("PDF has multiple tagged programs. Export one explicit program per PDF.")
    if tagged: return tagged[0]
    raise ValueError("No explicit quantum program found. PDF must embed one UTF-8 JSON/QASM/TXT/CSV file or contain SPINDOCTOR-JSON-BEGIN/END (or QASM/TXT/CSV) text blocks. Scanned images, prose and untagged equations require transcription; no OCR or guessed execution is performed.")


def strict_utf8(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError as e:
        bad = "".join("[%02X]" % x for x in b[e.start:e.end])
        # .NET Framework's DecoderFallbackException reports the index one byte before the offending byte.
        raise ValueError("Unable to translate bytes " + bad + " at index " + str(max(0, e.start - 1)) + " from specified code page to Unicode.")


# ----------------------------------------------------------------------------- data tables and fitting
def _numeric(text):
    try:
        v = float(text.strip())
    except ValueError:
        return None
    if text.strip().lower() in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity", "+infinity"): return None
    if v != v or abs(v) == float("inf") or abs(v) > 1e150: return None
    return v


def parse_table(content):
    if content and content[0] == "\ufeff": content = content[1:]
    rows = csv_rows(content, 4096)
    if len(rows) < 2: raise ValueError("A data CSV requires one header row and at least one data row.")
    names = rows[0]
    if len(names) < 1 or len(names) > 64: raise ValueError("Data CSV supports 1..64 columns.")
    seen = set()
    for j in range(len(names)):
        names[j] = names[j].strip()
        if not (1 <= len(names[j]) <= 128): raise ValueError("Data CSV headers require 1..128 characters.")
        if any(ord(c) < 32 or ord(c) == 127 for c in names[j]): raise ValueError("Data CSV headers cannot contain control characters or line breaks.")
        if names[j].lower() in seen: raise ValueError("Data CSV headers must be unique, ignoring case.")
        seen.add(names[j].lower())
    rows = rows[1:]
    if len(rows) > 4096: raise ValueError("Data CSV supports at most 4096 rows.")
    for i, r in enumerate(rows):
        if len(r) != len(names): raise ValueError("Data CSV row " + str(i) + " has a different width from its header.")
    return names, rows


def table_view(source, names, rows):
    cols = []; numeric_cols = []
    for j, name in enumerate(names):
        num = miss = bad = 0; mn = float("inf"); mx = float("-inf"); mean = 0.0
        for r in rows:
            if not r[j].strip(): miss += 1; continue
            v = _numeric(r[j])
            if v is None: bad += 1; continue
            num += 1; mn = min(mn, v); mx = max(mx, v); mean += (v - mean) / num
        if num: numeric_cols.append(j)
        cols.append({"name": name, "index": j, "numericCount": num, "missingCount": miss, "invalidCount": bad,
                     "min": mn if num else None, "max": mx if num else None, "mean": mean if num else None, "unit": "unknown"})
    return {"resultKind": "csv-data-table", "columns": cols, "numericColumns": numeric_cols, "rowCount": len(rows),
            "rowsPreview": rows[:8], "rowsPreviewComplete": len(rows) <= 8, "source": source, "fittingPerformed": False,
            "physicalQuantumOperations": 0, "measurementShots": 0,
            "numericPolicy": "Invariant finite decimal/scientific numbers with absolute magnitude <= 1e150. Empty, nonnumeric and nonfinite selected cells are excluded from fitting with recorded reasons.",
            "scope": "Inert CSV data inspection. Header labels and units are not inferred as equations, causality, dates or future predictions. Choose target/features explicitly with q.input fit."}


def _column(names, sel):
    if re.match(r"^[0-9]+\Z", sel):
        i = int(sel)
        if i >= len(names): raise ValueError("CSV column index is outside the header.")
        return i
    for j, n in enumerate(names):
        if n.lower() == sel.lower(): return j
    raise ValueError("CSV column was not found: " + sel + ". Use the exact header name or a zero-based index.")


def _unit(u):
    if not (1 <= len(u) <= 64): raise ValueError("Unit labels require 1..64 characters.")
    if any(ord(c) < 32 for c in u): raise ValueError("Unit labels cannot contain control characters.")
    return u


def _norm(values):
    scale = 0.0; s = 1.0
    for x in values:
        v = abs(x)
        if v == 0: continue
        if scale < v:
            r = scale / v; s = 1 + s * r * r; scale = v
        else:
            r = v / scale; s += r * r
    return 0.0 if scale == 0 else scale * math.sqrt(s)


def _solve_qr(A, rhs, n, p):
    perm = list(range(p)); thr = math.sqrt(n) * 1e-12; largest = 0.0; smallest = float("inf")
    for k in range(p):
        pivot = k; best = -1.0
        for j in range(k, p):
            nm = _norm([A[i][j] for i in range(k, n)])
            if nm > best: best = nm; pivot = j
        if best <= thr:
            raise ValueError("Selected CSV features are rank deficient or numerically indistinguishable. Remove constant/duplicate/collinear predictors; no unique fitted equation is published.")
        if pivot != k:
            for i in range(n): A[i][k], A[i][pivot] = A[i][pivot], A[i][k]
            perm[k], perm[pivot] = perm[pivot], perm[k]
        init = A[k][k]; diag = -best if init >= 0 else best; div = init - diag; tau = (diag - init) / diag
        A[k][k] = diag
        for i in range(k + 1, n): A[i][k] /= div
        for j in range(k + 1, p):
            proj = A[k][j]
            for i in range(k + 1, n): proj += A[i][k] * A[i][j]
            proj *= tau; A[k][j] -= proj
            for i in range(k + 1, n): A[i][j] -= A[i][k] * proj
        dot = rhs[k]
        for i in range(k + 1, n): dot += A[i][k] * rhs[i]
        dot *= tau; rhs[k] -= dot
        for i in range(k + 1, n): rhs[i] -= A[i][k] * dot
        largest = max(largest, abs(diag)); smallest = min(smallest, abs(diag))
    piv = [0.0] * p
    for k in range(p - 1, -1, -1):
        v = rhs[k]
        for j in range(k + 1, p): v -= A[k][j] * piv[j]
        piv[k] = v / A[k][k]; _finite(piv[k])
    ans = [0.0] * p
    for j in range(p): ans[perm[j]] = piv[j]
    return ans, largest / smallest


def _r(v):
    from .netfmt import fmt_r
    return fmt_r(v)


def fit_table(source, names, rows, options):
    """Port of FitTable: centered/scaled column-pivoted Householder QR ordinary least squares."""
    target = _column(names, options["target"]); sels = _cell_list(options["features"], "features")
    if len(sels) > 16: raise ValueError("CSV linear fits support 1..16 predictors.")
    sel = []
    for s in sels:
        c = _column(names, s)
        if c == target: raise ValueError("The target column cannot also be a feature.")
        if c in sel: raise ValueError("Duplicate CSV feature selection.")
        sel.append(c)
    tunit = _unit(options["target-unit"]) if "target-unit" in options else "unknown"
    units = ["unknown"] * len(sel)
    if "feature-units" in options:
        units = _cell_list(options["feature-units"], "feature-units")
        if len(units) != len(sel): raise ValueError("feature-units must match the feature count and order.")
        units = [_unit(u) for u in units]
    vals = []; idx = []; excluded = []
    for i, r in enumerate(rows):
        row = [0.0] * (len(sel) + 1); reasons = []
        v = _numeric(r[target])
        if v is None: reasons.append("target " + names[target] + " is missing, nonnumeric, nonfinite or outside +/-1e150")
        else: row[0] = v
        for j, c in enumerate(sel):
            v = _numeric(r[c])
            if v is None: reasons.append("feature " + names[c] + " is missing, nonnumeric, nonfinite or outside +/-1e150")
            else: row[j + 1] = v
        if reasons: excluded.append({"rowIndex": i, "reason": "; ".join(reasons)})
        else: vals.append(row); idx.append(i)
    n = len(vals); p = len(sel) + 1
    if n <= p:
        raise ValueError("CSV linear fit needs more complete numeric rows than fitted parameters (intercept plus predictors). Used " + str(n) + ", required at least " + str(p + 1) + ".")
    means = [0.0] * p; mins = [float("inf")] * p; maxs = [float("-inf")] * p; scales = [0.0] * p
    for j in range(p):
        for i in range(n):
            v = vals[i][j]; means[j] += (v - means[j]) / (i + 1); mins[j] = min(mins[j], v); maxs[j] = max(maxs[j], v)
        for i in range(n): scales[j] = max(scales[j], abs(vals[i][j] - means[j]))
    for j in range(1, p):
        if scales[j] == 0:
            raise ValueError("CSV feature is constant: " + names[sel[j - 1]] + ". Remove it before fitting; the intercept already represents a constant.")
    A = [[1.0] + [(vals[i][j] - means[j]) / scales[j] for j in range(1, p)] for i in range(n)]
    rhs = [vals[i][0] - means[0] for i in range(n)]
    centered, ratio = _solve_qr(A, rhs, n, p)
    intercept = means[0] + centered[0]; slopes = []; feats = []; coefs = []; fstats = []
    for j, c in enumerate(sel):
        s = centered[j + 1] / scales[j + 1]; _finite(s); slopes.append(s); intercept -= s * means[j + 1]
        feats.append({"name": names[c], "columnIndex": c, "unit": units[j]})
        coefs.append({"feature": names[c], "coefficient": s, "unit": "unknown" if tunit == "unknown" or units[j] == "unknown" else tunit + "/(" + units[j] + ")"})
        fstats.append({"name": names[c], "min": mins[j + 1], "max": maxs[j + 1], "mean": means[j + 1], "scale": scales[j + 1], "unit": units[j]})
    _finite(intercept)
    data_rows = []; sabs = 0.0; res = []; dev = []
    for i in range(n):
        fitted = means[0] + centered[0]; fv = []
        for j in range(len(sel)):
            fv.append(vals[i][j + 1]); fitted += centered[j + 1] * ((fv[j] - means[j + 1]) / scales[j + 1])
        obs = vals[i][0]; r = obs - fitted; _finite(fitted); _finite(r)
        res.append(r); dev.append(obs - means[0]); sabs += abs(r)
        data_rows.append({"rowIndex": idx[i], "observed": obs, "fitted": fitted, "residual": r, "features": fv})
    rn = _norm(res); tn = _norm(dev); ss = rn * rn; _finite(ss); _finite(sabs)
    const = maxs[0] == mins[0]; rmse = rn / math.sqrt(n); mae = sabs / n
    rel = 0.0 if const else rn / tn; r2 = None if const else 1 - rel * rel
    if r2 is not None: _finite(r2)
    eq = names[target] + " = " + _r(intercept) + "".join(" + (" + _r(slopes[j]) + ") * [" + names[sel[j]] + "]" for j in range(len(sel)))
    ceq = names[target] + " = " + _r(means[0] + centered[0]) + "".join(" + (" + _r(slopes[j]) + ") * ([" + names[sel[j]] + "] - (" + _r(means[j + 1]) + "))" for j in range(len(sel)))
    warn = ["Coefficients describe an empirical linear relationship in the supplied rows. They do not establish physical causality or validated future forecasts.",
            "R-squared, RMSE and MAE use the same rows used to fit the model; no independent holdout validation was performed."]
    if excluded: warn.append("Rows with missing, nonnumeric, nonfinite or out-of-range selected cells were excluded; see every row index and reason.")
    if const: warn.append("Target is constant. R-squared is undefined and is returned as null, rather than an invented zero or perfect score.")
    if tunit == "unknown" or "unknown" in units: warn.append("At least one unit is unknown. Units are user-supplied labels and are not inferred from the data.")
    if rn > 0 and ss == 0: warn.append("Residual sum of squares is below the representable FP64 range and rounds to zero; RMSE and R-squared were computed using scaled norms.")
    if ratio > 1e8: warn.append("QR diagonal ratio is large; fitted coefficients may be sensitive to rounding or small input changes. This ratio is a diagnostic, not a full condition-number estimate.")
    return {"resultKind": "empirical-csv-fit", "model": "ordinary-least-squares-linear", "equation": eq, "centeredEquation": ceq,
            "equationConvention": "target = intercept + sum(coefficients[i].coefficient * features[i]); fitted rows are evaluated in centered/scaled coordinates to reduce cancellation.",
            "target": {"name": names[target], "columnIndex": target, "unit": tunit}, "features": feats, "intercept": intercept, "coefficients": coefs,
            "metrics": {"rSquared": r2, "rmse": rmse, "mae": mae, "residualSumSquares": ss, "residualSumSquaresRepresentable": rn == 0 or ss > 0,
                        "targetMean": means[0], "constantTarget": const, "trainingOnly": True, "holdoutRows": 0},
            "rowCount": len(rows), "usedRows": n, "excludedRows": len(excluded), "excluded": excluded, "dataRows": data_rows, "dataRowsComplete": True,
            "featureStatistics": fstats, "targetStatistics": {"min": mins[0], "max": maxs[0], "mean": means[0], "unit": tunit}, "source": source,
            "method": "centered/scaled column-pivoted Householder QR", "rank": p, "parameterCount": p, "qrDiagonalRatio": ratio,
            "residualDegreesOfFreedom": n - p, "warnings": warn, "fittingPerformed": True, "physicalQuantumOperations": 0, "measurementShots": 0,
            "scope": "Bounded classical empirical CSV regression using actual supplied numeric rows. In-sample diagnostics only; no physical-law discovery, causal proof, quantum computation, holdout validation or future prediction is claimed."}


# ----------------------------------------------------------------------------- attachment manager
SUMMARY_KEYS = ("format", "parseValid", "executable", "requiresBase", "requiresBindings", "warnings", "error", "name", "qubits",
                "initialBasis", "gateCount", "columns", "rowCount", "tableValid", "tableError")


def input_help():
    return {"commands": ["q.input list", "q.input show ID", "q.input table ID",
                         "q.input fit ID target=COLUMN features=[COLUMN,...] [target-unit=UNIT] [feature-units=[UNIT,...]]",
                         "q.input evaluate ID [row N] [base BASE_ID] [name=expression...]",
                         "q.input import ID [row N] [base BASE_ID] [name=NUMERIC_VALUE...]", "q.input run ID", "q.input delete ID",
                         "q.input export ID", "q.input help", "q.input add path=\"FILE\"  (cartridge: attach a local file)"],
            "formats": "UTF-8 JSON circuit specs or explicit commands arrays; OpenQASM2 unitary subset with one qreg and optional final complete Z measurement; TXT circuit configuration or documented q.commands; CSV parameter sweeps with an explicit base attachment, an explicit gate-list circuit, numeric measurement tables with explicit empirical fitting, or a single command column. PDF binary sources must embed one UTF-8 program or contain one explicit SPINDOCTOR-JSON/QASM/TXT/CSV-BEGIN and matching END tagged text block. Prose, scanned images and unsupported PDF encodings are not guessed or OCRed.",
            "jsonExample": "{\"name\":\"my-equation\",\"qubits\":2,\"initialBasis\":\"0\",\"parameters\":{\"theta\":\"pi/4*sqrt(2)\"},\"gates\":[{\"name\":\"ry\",\"angles\":[\"theta\"],\"qubits\":[0]},{\"name\":\"cx\",\"qubits\":[0,1]}],\"shots\":100,\"basis\":\"z\"}",
            "expressions": "Case-sensitive declared parameters; pi,e,+,-,*,/,^; sin,cos,tan,sqrt,exp,log,abs,asin,acos,atan. Angles are radians. No code execution or external includes.",
            "csv": "A single command header accepts 1..128 documented q.commands, each 1..4096 characters. Quote cells containing commas; double literal quotes. For parameter sweeps, header names must be declared parameters in an explicit base circuit: 1..64 columns, 1..4096 rows, expressions up to 1024 characters, zero-based row indices. Generic tables and arbitrary algebra are not inferred as equations.",
            "sequenceExample": "{\"commands\":[\"q.math norm amplitudes=[1,0]\",\"q.status\"]}",
            "dataCsv": "Measurement tables are inert data. Inspect with q.input table ID, then explicitly choose one target and 1..16 predictors with q.input fit. Select headers by name or zero-based column index. Up to 4096 rows; selected values must be invariant finite numbers with magnitude <=1e150. Missing/invalid selected cells are excluded with recorded row reasons. Units remain unknown unless supplied. Result is an empirical in-sample linear fit with native coefficients, diagnostics and residuals; no physical causality or validated forecasting is inferred.",
            "gateCsv": "Header gate,n,targets,angles; optional name,initialBasis,shots,basis. Declare n=1..298 in the first gate row; circuit metadata may be blank later or repeat consistently. Targets and angles use comma-separated lists, optionally bracketed and CSV-quoted; target all is allowed only for local gates. Angles use supported safe expressions in radians. q.input import defines; q.input run or folder mode executes explicitly with declared shots/basis, default 1024 Z shots, maximum 100000 shots.",
            "limits": {"fileBytes": MAX_BYTES, "pdfBytes": MAX_PDF_BYTES, "folderFileBytes": FOLDER_FILE_BYTES, "sequenceCommands": 128,
                       "files": MAX_FILES, "totalBytes": MAX_TOTAL_BYTES, "qubits": 298, "circuitInstructions": 8192, "parameters": 64},
            "scope": "Upload, preview, evaluate and transient compilation read data only. Import atomically creates/selects a circuit. q.input run explicitly executes an attachment program or structured commands in order. Attachments never execute automatically. The cartridge attaches local files with q.input add path=... or the attach API/tool."}


class InputManager(object):
    def __init__(self, workspace):
        self.dir = os.path.join(workspace, "inputs") if workspace else None
        self.entries = []
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)
            self._load()

    # persistence
    def _catalog_path(self):
        return os.path.join(self.dir, "catalog.json")

    def _save(self):
        if not self.dir: return
        rows = [{"id": e["id"], "filename": e["filename"], "sha256": e["sha256"], "bytes": e["bytes"], "uploadedUtc": e["uploadedUtc"]} for e in self.entries]
        payload = json.dumps(rows, separators=(",", ":"))
        data = json.dumps({"schema": "SPINDOCTOR/INPUTS/1", "entries": rows, "entriesSha256": sha256_hex(payload.encode("utf-8"))})
        tmp = self._catalog_path() + "." + uuid.uuid4().hex + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f: f.write(data)
            os.replace(tmp, self._catalog_path())
        finally:
            if os.path.exists(tmp): os.remove(tmp)

    def _load(self):
        p = self._catalog_path()
        if not os.path.exists(p): return
        if os.path.getsize(p) > 262144: raise ValueError("Attachment catalog exceeds its bounded read size.")
        with open(p, encoding="utf-8") as f: data = json.load(f)
        if not isinstance(data, dict) or data.get("schema") != "SPINDOCTOR/INPUTS/1": raise ValueError("Unsupported attachment catalog.")
        rows = data.get("entries") or []
        if len(rows) > MAX_FILES or sha256_hex(json.dumps(rows, separators=(",", ":")).encode("utf-8")) != data.get("entriesSha256"):
            raise ValueError("Attachment catalog checksum/count mismatch.")
        for r in rows:
            e = dict(r); self._validate_id(e["id"]); validate_filename(e["filename"])
            e["preview"] = self._preview(e, self._read_bytes(e))
            self.entries.append(e)

    @staticmethod
    def _validate_id(i):
        if not isinstance(i, str) or not re.match(r"^[0-9a-f]{32}\Z", i): raise ValueError("Expected an opaque 32-character attachment ID.")

    def _path(self, i):
        self._validate_id(i)
        return os.path.join(self.dir, i + ".utf8")

    def _read_bytes(self, e):
        if "_mem" in e: b = e["_mem"]
        else:
            with open(self._path(e["id"]), "rb") as f: b = f.read(MAX_BYTES + 1)
        if len(b) != e["bytes"] or sha256_hex(b) != e["sha256"]: raise ValueError("Stored attachment content/hash mismatch.")
        return b

    def _find(self, i):
        self._validate_id(i)
        for e in self.entries:
            if e["id"] == i: return e
        raise ValueError("Unknown attachment ID.")

    def _content(self, e):
        b = self._read_bytes(e)
        if _ext(e["filename"]) == ".pdf": return pdf_extract(b)["content"]
        return strict_utf8(b)

    def _parse(self, e):
        b = self._read_bytes(e)
        if _ext(e["filename"]) == ".pdf": return parse_content(e["filename"], "", e["id"], b)
        return parse_content(e["filename"], strict_utf8(b), e["id"])

    # preview / metadata
    def _preview(self, e, b):
        pv = {"parseValid": False, "executable": False, "requiresBase": False, "requiresBindings": False, "format": "unsupported", "warnings": [], "error": ""}
        pdf = _ext(e["filename"]) == ".pdf"; content = ""
        try:
            if pdf:
                ex = pdf_extract(b)
                plan = parse_content(ex["filename"], ex["content"], e["id"])
                pv["pdfExtraction"] = {"method": ex["method"], "programFilename": ex["filename"],
                                       "programSha256": sha256_hex(ex["content"].encode("utf-8")), "textStreams": ex["textStreams"]}
                plan.format = "pdf/" + plan.format
            else:
                content = strict_utf8(b)
                plan = parse_content(e["filename"], content, e["id"])
            pv["parseValid"] = True; pv["format"] = plan.format; pv["warnings"] = list(plan.warnings)
            if plan.script is not None:
                pv["executable"] = True; pv["commandCount"] = len(plan.script); pv["commandsPreview"] = plan.script
                pv["note"] = "Explicit structured command data. q.input run executes in order; upload alone never executes."
            elif plan.rows is not None:
                pv["requiresBase"] = True; pv["columns"] = plan.columns; pv["rowCount"] = len(plan.rows); pv["rowsPreview"] = plan.rows[:8]
                pv["note"] = "Choose a base circuit attachment and a zero-based row, then evaluate/import explicitly."
            else:
                pv["name"] = plan.name; pv["qubits"] = plan.qubits; pv["initialBasis"] = str(plan.initial); pv["gateCount"] = len(plan.gates)
                pv["parameters"] = plan.parameters; pv["hints"] = {"shots": plan.shots, "basis": plan.basis}
                params = resolve(plan.parameters, None, False)
                pv["gatesPreview"] = resolved_gates(plan, params, 32); pv["parameterValues"] = params; pv["executable"] = True
        except MissingVariable as ex:
            pv["requiresBindings"] = True; pv["error"] = str(ex)
        except Exception as ex:  # noqa: BLE001
            pv["error"] = str(ex)
            if pdf: pv["format"] = "pdf"
        if pdf: pv["sourceEncoding"] = "binary-pdf"
        if _ext(e["filename"]) == ".csv":
            try:
                names, rows = parse_table(content)
                pv["tableValid"] = True; pv["dataTable"] = table_view(self._source(e), names, rows)
                pv["tableNote"] = "Numeric data can be inspected with q.input table and fitted only after an explicit target/features choice. Upload does not execute or fit a model."
            except Exception as ex:  # noqa: BLE001
                pv["tableValid"] = False; pv["tableError"] = str(ex)
        return pv

    @staticmethod
    def _source(e):
        return {"id": e["id"], "filename": e["filename"], "sha256": e["sha256"], "bytes": e["bytes"]}

    def _metadata(self, e):
        r = dict(e["preview"])
        r.update({"id": e["id"], "filename": e["filename"], "sha256": e["sha256"], "bytes": e["bytes"], "uploadedUtc": e["uploadedUtc"],
                  "preview": dict(e["preview"]), "fullExportAvailable": True,
                  "scope": "Inert original source with SHA256. PDF imports require an embedded or explicitly tagged circuit program; document prose is data. No shell, document instructions, external includes, guessed equations or automatic execution."})
        return r

    def _summary(self, e):
        r = {"id": e["id"], "filename": e["filename"], "sha256": e["sha256"], "bytes": e["bytes"], "uploadedUtc": e["uploadedUtc"], "fullPreviewAvailable": True}
        for k in SUMMARY_KEYS:
            if k in e["preview"]:
                v = e["preview"][k]
                r[k] = v[:1024] if k == "error" and len(v) > 1024 else v
        return r

    def total_bytes(self):
        return sum(e["bytes"] for e in self.entries)

    def status(self):
        return {"attachments": [self._summary(e) for e in self.entries], "count": len(self.entries), "maxFileBytes": MAX_BYTES,
                "maxPdfBytes": MAX_PDF_BYTES, "maxFiles": MAX_FILES, "totalBytes": self.total_bytes(), "maxTotalBytes": MAX_TOTAL_BYTES,
                "formats": ["json", "openqasm2", "text-circuit", "csv-parameters", "csv-gates", "csv-data-table", "json-sequence", "txt-sequence", "csv-sequence", "pdf-embedded-or-tagged-program"],
                "scope": "Original UTF-8 and binary PDF source data with preserved SHA256. Preview and compilation do not execute. Explicit import selects a circuit; q.input run executes a validated program or command sequence. q.input table inspects CSV measurements; q.input fit performs a bounded empirical linear regression only after explicit target/features selection."}

    # upload
    def upload(self, filename, data):
        """Attach one file (bytes or str).  Non-PDF content must be strict UTF-8."""
        validate_filename(filename)
        b = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        pdf = _ext(filename) == ".pdf"
        if pdf:
            if len(b) > MAX_PDF_BYTES: raise ValueError("PDF source limit is 4MiB.")
        else:
            if len(b) > MAX_BYTES: raise ValueError("Attachment limit is 5 MiB of UTF-8 data.")
            strict_utf8(b)
        if len(self.entries) >= MAX_FILES: raise RuntimeError("At most 32 input attachments are supported. Delete an attachment first.")
        if self.total_bytes() > MAX_TOTAL_BYTES - len(b): raise RuntimeError("Input attachments exceed the 30 MiB combined UTF-8 source limit. Delete an attachment first.")
        e = {"id": uuid.uuid4().hex, "filename": filename, "sha256": sha256_hex(b), "bytes": len(b), "uploadedUtc": _utc()}
        if not self.dir: e["_mem"] = b
        e["preview"] = self._preview(e, b)
        if self.dir:
            with open(self._path(e["id"]), "wb") as f: f.write(b)
        self.entries.append(e)
        try:
            self._save()
        except Exception:
            self.entries.remove(e)
            if self.dir and os.path.exists(self._path(e["id"])): os.remove(self._path(e["id"]))
            raise
        return self._metadata(e)

    def upload_path(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isfile(path) or os.path.islink(path): raise ValueError("Attachment path must be an existing regular file (symlinks refused).")
        if os.path.getsize(path) > MAX_BYTES: raise ValueError("Attachment limit is 5 MiB of UTF-8 data.")
        with open(path, "rb") as f: b = f.read(MAX_BYTES + 1)
        return self.upload(os.path.basename(path), b)

    # commands
    def execute(self, w, session=None):
        if len(w) < 2 or w[0].lower() != "q.input": raise ValueError("Use q.input help.")
        c = w[1].lower()

        def exact(k):
            if len(w) != k: raise ValueError("Incorrect q.input argument count.")
        if c == "help": exact(2); return input_help()
        if c == "list": exact(2); return self.status()
        if c == "add":
            f = parse_fields(w)
            check_fields(f, "path")
            if "path" not in f: raise ValueError('Use q.input add path="FILE".')
            return self.upload_path(f["path"])
        if c == "table":
            exact(3); e = self._find(w[2]); return self._table(e)
        if c == "fit":
            if len(w) < 5: raise ValueError("Use q.input fit ID target=COLUMN features=[COLUMN,...] [target-unit=UNIT] [feature-units=[UNIT,...]].")
            e = self._find(w[2]); opts = parse_fields(["q.input", "fit"] + w[3:])
            check_fields(opts, "target features target-unit feature-units")
            if "target" not in opts or "features" not in opts:
                raise ValueError("Choose target and features explicitly; no equation is inferred during upload.")
            if _ext(e["filename"]) != ".csv": raise ValueError("Data-table inspection and fitting require an original CSV attachment.")
            names, rows = parse_table(strict_utf8(self._read_bytes(e)))
            return fit_table(self._source(e), names, rows, opts)
        if c == "show":
            exact(3); e = self._find(w[2])
            if _ext(e["filename"]) == ".pdf" and not e["preview"]["parseValid"]:
                return {"attachment": self._metadata(e), "sourcePreview": None, "sourcePreviewComplete": False, "fullExportAvailable": True,
                        "note": "The stored original PDF remains available as a binary download. No supported program could be extracted."}
            content = self._content(e)
            return {"attachment": self._metadata(e), "sourcePreview": content[:32768], "sourcePreviewComplete": len(content) <= 32768, "fullExportAvailable": True}
        if c == "export":
            exact(3); e = self._find(w[2])
            if _ext(e["filename"]) == ".pdf":
                return {"attachment": self._metadata(e), "fullExportAvailable": True, "contentIncluded": False, "mediaType": "application/pdf",
                        "note": "The original PDF bytes are kept in the workspace inputs folder. q.input show displays only the safely extracted program preview."}
            content = self._content(e); r = {"attachment": self._metadata(e), "fullExportAvailable": True, "contentIncluded": e["bytes"] <= 524288}
            if e["bytes"] <= 524288: r["content"] = content
            else: r["note"] = "Use the stored original source in the workspace inputs folder for the complete content."
            return r
        if c == "delete":
            exact(3); e = self._find(w[2]); i = self.entries.index(e); self.entries.pop(i)
            try:
                self._save()
            except Exception:
                self.entries.insert(i, e); raise
            if self.dir and os.path.exists(self._path(e["id"])): os.remove(self._path(e["id"]))
            return {"deleted": e["id"], "filename": e["filename"]}
        if c == "evaluate":
            if len(w) < 3: raise ValueError("Use q.input evaluate ID [row N] [base ID] [name=expression...].")
            e = self._find(w[2]); row = None; base = None; defs = {}; j = 3
            while j < len(w):
                if w[j].lower() == "row":
                    j += 1
                    if row is not None or j >= len(w): raise ValueError("Specify one row index.")
                    row = _int(w[j], 0, 4095)
                elif w[j].lower() == "base":
                    j += 1
                    if base is not None or j >= len(w): raise ValueError("Specify one base attachment.")
                    base = w[j]
                else:
                    eq = w[j].find("=")
                    if eq <= 0 or eq == len(w[j]) - 1: raise ValueError("Bindings use name=expression without spaces.")
                    name = parameter_name(w[j][:eq]); expr = w[j][eq + 1:]
                    if name in defs: raise ValueError("Duplicate parameter override.")
                    SafeExpression.validate(expr); defs[name] = expr
                j += 1
            plan = self._parse(e)
            if plan.rows is not None and base is None: raise ValueError("CSV evaluation requires base BASE_ID and a zero-based row index.")
            bp = plan if plan.rows is None else self._parse(self._find(base))
            defaults = resolve(bp.parameters, None, True)
            for k in defs: defaults.pop(k, None)
            bound = resolve(defs, defaults, False)
            spec = self.import_spec(w[2], row, {k: bound[k] for k in defs}, base)
            return {"validated": True, "spec": spec, "parameterValues": spec["parameters"], "attachment": self._metadata(e)}
        if c == "import":
            if len(w) < 3: raise ValueError("Use q.input import ID [row N] [base BASE_ID] [name=value ...].")
            row = None; base = None; binds = {}; j = 3
            while j < len(w):
                if w[j].lower() == "row":
                    j += 1
                    if row is not None or j >= len(w) or not re.match(r"^[0-9]+\Z", w[j]): raise ValueError("Supply one nonnegative CSV row index.")
                    row = int(w[j])
                elif w[j].lower() == "base":
                    j += 1
                    if base is not None or j >= len(w): raise ValueError("Supply one base attachment ID.")
                    base = w[j]
                else:
                    eq = w[j].find("=")
                    if eq <= 0: raise ValueError("Import bindings use name=NUMERIC_VALUE.")
                    name = parameter_name(w[j][:eq])
                    try: v = float(w[j][eq + 1:])
                    except ValueError: raise ValueError("Import bindings use name=NUMERIC_VALUE.")
                    _finite(v)
                    if name in binds: raise ValueError("Duplicate import binding.")
                    binds[name] = v
                j += 1
            spec = self.import_spec(w[2], row, binds, base)
            if session is None: raise ValueError("Import needs a session.")
            return session.circuit.import_circuit(spec)
        raise ValueError("Unknown input command. Use q.input help.")

    def _table(self, e):
        if _ext(e["filename"]) != ".csv": raise ValueError("Data-table inspection and fitting require an original CSV attachment.")
        names, rows = parse_table(strict_utf8(self._read_bytes(e)))
        return table_view(self._source(e), names, rows)

    def import_spec(self, i, row, bindings, base):
        e = self._find(i); plan = self._parse(e)
        if plan.script is not None: raise ValueError("This attachment contains a command sequence. Use q.input run ID to execute it.")
        combined = dict(bindings or {})
        for k, v in combined.items(): parameter_name(k); _finite(v)
        source = {"id": e["id"], "filename": e["filename"], "sha256": e["sha256"], "format": plan.format, "row": row, "baseId": base}
        if plan.rows is not None:
            if row is None or row < 0 or row >= len(plan.rows): raise ValueError("CSV import requires a valid zero-based row index.")
            if base is None: raise ValueError("CSV import requires base BASE_ID pointing to a circuit attachment.")
            be = self._find(base); circ = self._parse(be)
            if circ.rows is not None: raise ValueError("A CSV cannot serve as its own circuit base.")
            defaults = resolve(circ.parameters, combined, True); cells = {}
            for j, col in enumerate(plan.columns):
                if col not in circ.parameters: raise ValueError("CSV column is not a declared base-circuit parameter: " + col)
                cells[col] = plan.rows[row][j]
            for k in cells:
                if k not in combined: defaults.pop(k, None)
            values = resolve(cells, defaults, False)
            for k in cells:
                if k not in combined: combined[k] = values[k]
            source["baseSha256"] = be["sha256"]; source["baseFilename"] = be["filename"]; plan = circ
        elif row is not None or base is not None:
            raise ValueError("row/base options apply only to CSV parameter sweeps.")
        for k in combined:
            if k not in plan.parameters: raise ValueError("Override is not a declared circuit parameter: " + k)
        params = resolve(plan.parameters, combined, False)
        return {"name": plan.name, "qubits": plan.qubits, "initialBasis": str(plan.initial), "parameters": params,
                "gates": resolved_gates(plan, params), "hints": {"shots": plan.shots, "basis": plan.basis}, "source": source,
                "equations": dict(plan.parameters), "warnings": list(plan.warnings),
                "scope": "Validated classical coherent-circuit input data. Import creates/selects a program; running and measuring remain explicit actions."}

    def attachment_bytes(self, i):
        e = self._find(i); return e["filename"], self._read_bytes(e)


def compile_source(filename, data):
    """Port of CompileSource + CompileBytes: one folder/attachment file -> ordered q.* commands (never executed here)."""
    if data is None or len(data) > FOLDER_FILE_BYTES: raise ValueError("Folder input exceeds 4 MiB.")
    parse_name = filename
    if _ext(filename) == ".pdf":
        ex = pdf_extract(data); parse_name = ex["filename"]; content = ex["content"]
    else:
        content = strict_utf8(data)
    sha = sha256_hex(data)
    plan = parse_content(parse_name, content, "transient")
    if plan.script is not None:
        cmds = list(plan.script); fmt = plan.format
    else:
        if plan.rows is not None:
            raise ValueError("A parameter CSV needs an explicit base circuit. Folder CSVs instead use a command column; see Input formats page.")
        params = resolve(plan.parameters, None, False); gates = resolved_gates(plan, params)
        from .netfmt import fmt_r
        name = "file_" + uuid.uuid4().hex[:16]
        cmds = ["q.circuit memory auto", "q.circuit new " + name + " " + str(plan.qubits), "q.circuit input " + str(plan.initial)]
        for g in gates:
            line = "q.circuit add " + g["name"] + "".join(" " + fmt_r(a) for a in g["angles"])
            line += " all" if g["all"] else "".join(" " + str(q) for q in g["qubits"])
            cmds.append(line)
        cmds.append("q.circuit run shots " + str(plan.shots) + " basis " + plan.basis)
        fmt = plan.format
    if len(cmds) > 128:
        raise ValueError("Folder circuit expands to more than 128 commands. Import the larger circuit directly with q.input import, or split the sequence into files.")
    return {"commands": cmds, "sourceSha256": sha, "inputName": filename, "sourceFormat": fmt}
