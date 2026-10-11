# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""CSV report companions (port of SpinDoctor 3.1.1/3.1.2 SpinDoctorReportCsv + SpinDoctorReportEquations).

Every command report gets a lossless long-form CSV: one row per JSON value with an RFC 6901 JSON Pointer path,
presence, value_type, item_count and value_json (an invariant JSON scalar, so spreadsheets never see formulas).
Empirical CSV fits and declared circuits also get an /export/equationRepresentations block.  Export performs no
calculation, measurement or verification.
"""
import json
import math
import re

from .netfmt import dumps, fmt_r

SCHEMA = "SPINDOCTOR/CSV-REPORT/1"
EQ_SCHEMA = "SPINDOCTOR/REPORT-EQUATIONS/1"
MAX_BYTES = 33554432
MAX_ROWS = 1048575
MAX_DEPTH = 100
HEADER = ["schema", "report_kind", "record_id_json", "report_stage_json", "path", "presence", "value_type", "item_count", "value_json"]


def _line(cells):
    return ",".join('"' + (c or "").replace('"', '""') + '"' for c in cells) + "\r\n"


class _Writer(object):
    def __init__(self, renderer_version):
        self.out = []; self.bytes = 0; self.rows = 0; self.kind = ""; self.id = ""; self.stage = ""
        self._emit(HEADER)
        self.context("export", "", "format")
        self.node("/export/schema", SCHEMA, 0)
        self.node("/export/rendererVersion", renderer_version, 0)
        self.node("/export/valueEncoding", "RFC 4180 UTF-8 CSV with CRLF rows. value_json is an invariant JSON scalar, not spreadsheet formula text; decode it to recover each original string or number. Object/array rows contain item_count; child paths use RFC 6901 JSON Pointer escaping. Row order is deterministic. No native calculations or verification are performed by export.", 0)
        self.node("/export/missingFieldRule", "A native path with no row was not returned. A present null is value_type=null and value_json=null; an explicit zero remains numeric zero or its original string. Empty containers have item_count=0. Export provenance that is unavailable is marked presence=missing, never zero.", 0)

    def _emit(self, cells):
        raw = _line(cells); n = len(raw.encode("utf-8"))
        if n > MAX_BYTES - self.bytes:
            raise ValueError("CSV exceeds the bounded export byte budget; export individual files or commands. No native report was changed.")
        self.bytes += n; self.out.append(raw)

    def context(self, kind, rid, stage):
        if not re.match(r"^[a-z][a-z0-9_-]{0,39}$", kind or ""): raise ValueError("Invalid CSV report kind.")
        self.kind = kind; self.id = dumps(rid or ""); self.stage = dumps(stage or "")

    def row(self, path, presence, typ, count, enc):
        self.rows += 1
        if self.rows > MAX_ROWS: raise ValueError("CSV exceeds 1,048,575 data rows; export individual files or commands.")
        self._emit([SCHEMA, self.kind, self.id, self.stage, path, presence, typ, count, enc])

    def node(self, path, v, depth):
        if depth > MAX_DEPTH: raise ValueError("CSV nesting exceeds 100 levels; export a smaller recorded object.")
        if v is None: self.row(path, "present", "null", "", "null"); return
        if isinstance(v, dict):
            keys = sorted((str(k) for k in v.keys()), key=lambda s: s.encode("utf-16-be"))
            self.row(path, "present", "object", str(len(keys)), "")
            for k in keys: self.node(path + "/" + k.replace("~", "~0").replace("/", "~1"), v[k], depth + 1)
            return
        if isinstance(v, (list, tuple)):
            self.row(path, "present", "array", str(len(v)), "")
            for i, x in enumerate(v): self.node(path + "/" + str(i), x, depth + 1)
            return
        if isinstance(v, str): self.row(path, "present", "string", "", dumps(v)); return
        if isinstance(v, bool): self.row(path, "present", "boolean", "", "true" if v else "false"); return
        if isinstance(v, float):
            if not math.isfinite(v): raise ValueError("CSV cannot publish a non-finite native JSON number.")
            self.row(path, "present", "number", "", "-0.0" if v == 0 and math.copysign(1, v) < 0 else fmt_r(v)); return
        if isinstance(v, int): self.row(path, "present", "integer", "", str(v)); return
        self.row(path, "present", "string", "", dumps(str(v)))

    def missing(self, path):
        self.row(path, "missing", "missing", "", "")


def _m(v):
    return v if isinstance(v, dict) else {}


def _n(v):
    if isinstance(v, float): return fmt_r(v)
    if v is None: return "Not returned"
    return str(v)


MATRICES = {
    "i": ("", [["1", "0"], ["0", "1"]]), "h": ("1/sqrt(2)", [["1", "1"], ["1", "-1"]]), "x": ("", [["0", "1"], ["1", "0"]]),
    "y": ("", [["0", "-i"], ["i", "0"]]), "z": ("", [["1", "0"], ["0", "-1"]]),
    "s": ("", [["1", "0"], ["0", "i"]]), "sdg": ("", [["1", "0"], ["0", "-i"]]), "t": ("", [["1", "0"], ["0", "exp(i*pi/4)"]]),
    "tdg": ("", [["1", "0"], ["0", "exp(-i*pi/4)"]]), "p": ("", [["1", "0"], ["0", "exp(i*a1)"]]),
    "sx": ("1/2", [["1+i", "1-i"], ["1-i", "1+i"]]), "sxdg": ("1/2", [["1-i", "1+i"], ["1+i", "1-i"]]),
    "rx": ("", [["cos(a1/2)", "-i sin(a1/2)"], ["-i sin(a1/2)", "cos(a1/2)"]]), "ry": ("", [["cos(a1/2)", "-sin(a1/2)"], ["sin(a1/2)", "cos(a1/2)"]]),
    "rz": ("", [["exp(-i*a1/2)", "0"], ["0", "exp(i*a1/2)"]]),
    "u": ("", [["cos(a1/2)", "-exp(i*a3) sin(a1/2)"], ["exp(i*a2) sin(a1/2)", "exp(i*(a2+a3)) cos(a1/2)"]]),
    "cx": ("", [["1", "0", "0", "0"], ["0", "0", "0", "1"], ["0", "0", "1", "0"], ["0", "1", "0", "0"]]),
    "swap": ("", [["1", "0", "0", "0"], ["0", "0", "1", "0"], ["0", "1", "0", "0"], ["0", "0", "0", "1"]]),
}


def _matrix(name):
    expr = ""; factor = ""; rows = None
    if name in MATRICES: factor, rows = MATRICES[name]
    elif name in ("cy", "cz", "ch", "cp", "crx", "cry", "crz"):
        expr = "P0(control=operand0) I(target=operand1) + P1(control=operand0) " + name[1:].upper() + "(target=operand1; a1 when applicable)"
    elif name == "cu": expr = "P0(control=operand0) I(target=operand1) + P1(control=operand0) exp(i*a4) U(a1,a2,a3; target=operand1)"
    elif name == "ccx": expr = "I8 + P1(operand0) P1(operand1) (X(operand2)-I); labelled operators are embedded on the stated operands and multiplied, not tensor-listed in control-first order."
    elif name == "cswap": expr = "P0(control=operand0) I(targets=operand1,operand2) + P1(control=operand0) SWAP(targets=operand1,operand2); labelled commuting embedded products, not tensor-listed in control-first order."
    elif name == "mcx7": expr = "I256 + P1(operand0) P1(operand1) P1(operand2) P1(operand3) P1(operand4) P1(operand5) P1(operand6) (X(operand7)-I); seven controls followed by target, operand0 is local least-significant bit."
    elif name in ("rxx", "ryy", "rzz", "rzx"): expr = "cos(a1/2) I4 - i sin(a1/2) " + name[1].upper() + "(operand0) " + name[2].upper() + "(operand1)"
    else: return {"available": False, "equationText": "Display formula unavailable for this recorded operator; operands are retained without a guessed matrix."}
    if rows is not None: expr = (factor + " * " if factor else "") + json.dumps(rows, separators=(",", ":"))
    basis = ("|operand7,...,operand0>; operands0..6 control operand7; no full-register matrix." if name == "mcx7" else "|operand2,operand1,operand0>; operand0 is local least-significant bit. Labelled operators act on their stated operands in this embedding; no full-register matrix."
             if name in ("ccx", "cswap") else "|0>,|1>" if rows is not None and len(rows) == 2
             else "|operand1,operand0> = |00>,|01>,|10>,|11>; operand0 is local least-significant bit and control where controlled. No global register matrix.")
    return {"available": True, "equationText": expr, "prefactor": factor, "rows": rows, "basis": basis}


def describe(command, result):
    result = _m(result)
    if result.get("resultKind") == "empirical-csv-fit":
        coefs = result.get("coefficients") or []; var = []
        eq = "y_hat = " + _n(result.get("intercept"))
        for i, c in enumerate(coefs, 1):
            c = _m(c); var.append({"symbol": "x%d" % i, "column": c.get("feature"), "coefficientSymbol": "b%d" % i, "coefficient": c.get("coefficient"), "unit": c.get("unit")})
            eq += " + (" + _n(c.get("coefficient")) + ") * x%d" % i
        lines = [eq, "y_hat is the fitted target: " + str(_m(result.get("target")).get("name", "")) + "; b0 = " + _n(result.get("intercept"))]
        for v in var: lines.append(v["symbol"] + " = CSV column " + dumps(v["column"]) + "; " + v["coefficientSymbol"] + " = " + _n(v["coefficient"]) + "; unit = " + str(v["unit"]))
        lines.append("Recorded input-column equation: " + str(result.get("equation", "")))
        if "centeredEquation" in result: lines.append("Stable centered form: " + str(result["centeredEquation"]))
        src = _m(result.get("source"))
        return {"schema": EQ_SCHEMA, "command": command, "kind": "empirical-fit", "equationText": "\n".join(lines) + "\n",
                "mathNotation": "\\widehat{y}=b_0+\\sum_{j=1}^{p}b_jx_j", "featureCount": len(coefs), "intercept": result.get("intercept"),
                "variables": var, "sourceSha256": src.get("sha256"), "sourceFilename": src.get("filename"),
                "scope": "Empirical in-sample fitted equation. Symbols map only to the actual returned CSV coefficients and column names; no circuit is inferred from measurement data."}
    prog = _m(result.get("programSnapshot"))
    if not prog and isinstance(result.get("program"), dict): prog = result["program"]
    if not prog or "gates" not in prog or "qubits" not in prog: return {}
    gates = prog.get("gates") or []
    initial = str(prog.get("initialBasis", "0")); n = prog.get("qubits")
    try:
        ket = format(int(initial), "b").zfill(int(n)) if 1 <= int(n) <= 298 and 0 <= int(initial) < (1 << int(n)) else "b"
    except (TypeError, ValueError):
        ket = "b"
    m = len(gates)
    product = "" if m == 0 else "U[1] " if m == 1 else "U[2] U[1] " if m == 2 else "U[%d] ... U[1] " % m
    t = ["|psi_out> = " + product + "|" + ket + ">", "Computational-basis index b = " + initial + "; register width n = " + str(n) + "; |b> = |" + ket + ">.",
         "Gate rows are chronological; the first row acts first (rightmost in the operator product). Global bitstrings have qubit0 at the right. Local two-operand matrices use |operand1,operand0> = |00>,|01>,|10>,|11>: the first listed operand is the local least-significant bit, including a controlled gate's control."]
    ops = []
    for i, g in enumerate(gates[:256]):
        g = _m(g); name = str(g.get("name") or g.get("gate") or "").lower(); mx = _matrix(name); angles = g.get("angles") or []
        ops.append({"index": i + 1, "gate": name, "qubits": g.get("qubits"), "all": g.get("all"), "angles": g.get("angles"), "matrix": mx})
        t.append("U[%d] = %s; operands = %s; all = %s; angle radians = %s" % (i + 1, name.upper(), dumps(g.get("qubits")), str(g.get("all")), dumps(angles)))
        t.append("  Local symbolic operator: " + str(mx.get("equationText")))
        for j, a in enumerate(angles): t.append("  a%d = %s radians" % (j + 1, _n(a)))
    if m > 256: t.append("First 256 operator representations shown; %d further actual gate rows remain in the unchanged native program archive." % (m - 256))
    t.append("Born: P(s | basis) = |<s;basis|psi_out>|^2 = |<s| B_basis |psi_out>|^2; B_basis is the measurement rotation (basis-ket matrix adjoint): B_Z = I, B_X = tensor(H), B_Y = tensor(H*S_dagger). These are mathematical basis equivalents, not extra executed gates. Recorded measurement basis: " + str(result.get("basis", "")))
    t.append("Local Bloch: rho_q = partial_trace_other_qubits(|psi_out><psi_out|); x=Tr(rho_q X)=2Re(rho_q[0,1]); y=Tr(rho_q Y)=-2Im(rho_q[0,1]); z=Tr(rho_q Z)=rho_q[0,0]-rho_q[1,1]. Entangled local states can have x=y=z=0.")
    evo = "|\\psi_{\\mathrm{out}}\\rangle=" + ("" if m == 0 else "U_1" if m == 1 else "U_2U_1" if m == 2 else "U_m\\cdots U_1") + "|b\\rangle"
    return {"schema": EQ_SCHEMA, "command": command, "kind": "declared-circuit", "equationText": "\n".join(t) + "\n",
            "mathNotation": evo + ";\\quad P(s\\mid B)=|\\langle s|B|\\psi_{\\mathrm{out}}\\rangle|^2;\\quad r_{q,k}=\\mathrm{Tr}(\\rho_q\\sigma_k)",
            "programHash": result.get("programHash") or prog.get("descriptorHash"), "initialBasis": prog.get("initialBasis"), "computationalBasisKet": ket,
            "qubits": n, "gateCount": m, "gateOperators": ops, "operatorRepresentationsComplete": m <= 256, "omittedOperatorRepresentations": max(0, m - 256),
            "basis": result.get("basis"),
            "scope": "Symbolic declared circuit evolution from actual retained chronological program operands. Local matrices are native-convention formulas with recorded angle bindings; no full-register matrix, numerical state, probability, amplitude or extra shot is calculated by export."}


def equations(payload):
    reps = []
    resp = None; cmd = ""
    if isinstance(payload, dict):
        if "finalResponse" in payload: resp = payload["finalResponse"]; cmd = payload.get("normalizedCommand") or payload.get("command", "")
        elif "response" in payload: resp = payload["response"]; cmd = payload.get("normalizedCommand") or payload.get("command", "")
        elif "result" in payload: resp = payload; cmd = payload.get("command", "")
    res = _m(_m(resp).get("result")); job = _m(res.get("job"))
    if job: res = job
    try:
        d = describe(str(cmd), res)
    except Exception:  # noqa: BLE001 - representation is optional
        d = {}
    if d: d["recordProvenance"] = "Supplied recorded fields; native archive provenance not independently verified by this helper."; reps.append(d)
    return {"schema": EQ_SCHEMA, "representations": reps, "count": len(reps), "omittedRepresentations": 0,
            "scope": "Report-layer symbolic/text representations of returned coefficients or matched retained circuit programs. These are editable text for a local draft, not new native answers, measurements, physical-law discovery or independent verification. Original native archive fields are unchanged."}


def build(payload, kind, rid, stage, renderer_version, source_sha256=""):
    w = _Writer(renderer_version)
    w.context(kind, rid, stage)
    if source_sha256 and re.match(r"^[a-f0-9]{64}$", source_sha256): w.node("/export/sourceArchiveSha256", source_sha256, 0)
    else: w.missing("/export/sourceArchiveSha256")
    w.node("/native", payload, 0)
    eqs = equations(payload)
    if eqs["count"] > 0: w.node("/export/equationRepresentations", eqs, 0)
    return "".join(w.out)
