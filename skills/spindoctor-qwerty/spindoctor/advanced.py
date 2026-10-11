# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Port of SpinDoctorAdvanced.cs: q.noise, q.qec, q.compile, q.algorithm (bounded models)."""
import math
import re
import time

from . import calculators as C
from .register import GATE_SPECS

TOL = 2e-9
D = C.D


def _caps(ns, actions, backend, kind):
    return [{"command": ns + " " + a, "namespace": ns, "action": a, "installed": True, "backend": backend, "resultKind": kind,
             "limits": "Noise/circuit matrices<=4qubits; compile matrix identity<=4qubits, logical analysis<=29; repetition code3qubits; phase-estimation1..8countingqubits, controlled phase eigenstates only.",
             "validation": "advanced-validation.json"} for a in actions.split(" ")]


def capabilities():
    r = []
    r += _caps("q.noise", "apply circuit t1 t2 readout zne", "bounded-density-FP64", "numerical")
    r += _caps("q.qec", "repetition3 phase-repetition3 validate parameters correction-budget", "bounded-code-analysis", "numerical")
    r += _caps("q.qec", "compare", "documented-theory", "theory")
    r += _caps("q.compile", "identity simplify count depth classify", "bounded-matrix / logical-analysis", "analysis")
    r += _caps("q.compile", "universality", "documented-theory", "theory")
    r += _caps("q.algorithm", "phase-estimation", "bounded-coherent-FP64", "numerical")
    return r


def supports(ns, action):
    key = ns.lower() + " " + action.lower()
    return any(c["command"] == key for c in capabilities())


def alias(s):
    s = s.lower()
    return {"id": "i", "identity": "i", "u3": "u", "cnot": "cx", "toffoli": "ccx", "fredkin": "cswap"}.get(s, s)


class Ins(object):
    def __init__(self, name, angles, qubits, text=""):
        self.name = name; self.angles = angles; self.qubits = qubits; self.text = text


def parse_gates(script, n):
    if len(script) > 12000: raise ValueError("Gate script exceeds12000characters.")
    cmds = script.split(";")
    if len(cmds) > 256: raise ValueError("Bounded gate script supports<=256instructions.")
    out = []
    for raw in cmds:
        t = raw.strip()
        if not t: continue
        w = re.split(r"\s+", t); name = alias(w[0]); spec = GATE_SPECS.get(name)
        if spec is None: raise ValueError("Unsupported gate " + name + ".")
        ac = spec["angleCount"]; tc = spec["targetCount"]
        all_ = len(w) == ac + 2 and w[-1].lower() == "all"
        if all_ and not spec["local"]: raise ValueError("all applies only to local gates.")
        if not all_ and len(w) != 1 + ac + tc: raise ValueError("Wrong operands/angles for " + name + ".")
        an = [C.real(w[1 + a]) for a in range(ac)]
        C.gate_matrix(name, an)
        if all_:
            for q in range(n): out.append(Ins(name, an, [q], t))
        else:
            qs = []
            for k in range(tc):
                q = C.integer(w[1 + ac + k], 0, n - 1)
                if q in qs: raise ValueError("Gate operands must be distinct.")
                qs.append(q)
            out.append(Ins(name, an, qs, t))
    return out


def embed(local, qs, n):
    if n < 1 or n > 4: raise ValueError("Explicit matrices support1..4qubits.")
    d = 1 << n; ld = 1 << len(qs); r = C.zeros(d, d); mask = 0
    for q in qs: mask |= 1 << q
    for x in range(d):
        lx = 0
        for k, q in enumerate(qs):
            if x & (1 << q): lx |= 1 << k
        for ly in range(ld):
            y = x & ~mask
            for k, q in enumerate(qs):
                if ly & (1 << k): y |= 1 << q
            r[y][x] = local[ly][lx]
    return r


def circuit_matrix(ins, n):
    u = C.identity(1 << n)
    for g in ins:
        u = C.matmul(embed(C.gate_matrix(g.name, g.angles), g.qubits, n), u)
    return u


def unit(f, k):
    p = C.real(C.required(f, k))
    if p < 0 or p > 1: raise ValueError(k + " must be in0..1.")
    return p


def qubit(text):
    v = C.parse_vector(text); C.require_pure(v)
    if len(v) != 2: raise ValueError("A qubit requires exactly two normalized amplitudes.")
    return v


def scale_m(m, s):
    return [[z * s for z in row] for row in m]


def channel(rho, n, target, ch, f):
    kr = []
    if ch in ("bit-flip", "phase-flip"):
        p = unit(f, "p")
        kr = [scale_m(C.identity(2), math.sqrt(1 - p)), scale_m(C.gate_matrix("x" if ch == "bit-flip" else "z", []), math.sqrt(p))]
    elif ch == "depolarizing":
        C.choice(f, "convention", "mix-with-I-over-2"); p = unit(f, "p")
        for nm in ("i", "x", "y", "z"):
            kr.append(scale_m(C.gate_matrix(nm, []), math.sqrt(1 - 3 * p / 4 if nm == "i" else p / 4)))
    elif ch == "amplitude-damping":
        g = unit(f, "gamma")
        kr = [[[1 + 0j, 0j], [0j, complex(math.sqrt(1 - g), 0)]], [[0j, complex(math.sqrt(g), 0)], [0j, 0j]]]
    elif ch == "dephasing":
        C.choice(f, "convention", "offdiagonal-times-one-minus-lambda"); lam = unit(f, "lambda")
        kr = [scale_m(C.identity(2), math.sqrt(1 - lam / 2)), scale_m(C.gate_matrix("z", []), math.sqrt(lam / 2))]
    else:
        raise ValueError("Unsupported named channel.")
    out = C.zeros(1 << n, 1 << n)
    for e in kr:
        full = embed(e, [target], n); term = C.matmul(C.matmul(full, rho), C.dagger(full))
        for i in range(len(out)):
            for j in range(len(out)): out[i][j] += term[i][j]
    C.require_density(out)
    return out


def error_mask(errors, phase):
    mask = 0
    for raw in errors:
        e = C.unquote(raw).upper()
        if e == "I": continue
        if not re.match(r"^Z[012]$" if phase else r"^X[012]$", e):
            raise ValueError("This code demonstration accepts only I and " + ("Z" if phase else "X") + "0..2 factors.")
        mask ^= 1 << (ord(e[1]) - 48)
    return mask


def syndrome(mask):
    return [((mask >> 0) ^ (mask >> 1)) & 1, ((mask >> 1) ^ (mask >> 2)) & 1]


def recovery(s):
    if s == [1, 0]: return 0
    if s == [1, 1]: return 1
    if s == [0, 1]: return 2
    return -1


def apply_mask(v, mask, phase):
    r = [0j] * len(v)
    for i in range(len(v)):
        if phase:
            par = 0
            for q in range(3):
                if mask & (1 << q) and i & (1 << q): par ^= 1
            r[i] = v[i] if par == 0 else -v[i]
        else:
            r[i ^ mask] = v[i]
    return r


class Pauli(object):
    def __init__(self, terms=None, phase=1 + 0j, highest=0):
        self.terms = dict(terms or {}); self.phase = phase; self.highest = highest

    def clone(self):
        return Pauli(self.terms, self.phase, self.highest)

    def binary(self):
        b = 0
        for q, c in self.terms.items():
            if c in "XY": b |= 1 << q
            if c in "ZY": b |= 1 << (29 + q)
        return b


def read_pauli(text):
    ph = 1 + 0j; text = text.strip()
    if text.startswith("-"): ph = -1 + 0j; text = text[1:].strip()
    elif text.startswith("+"): text = text[1:].strip()
    t = C.parse_pauli(text, 29); p = Pauli(t, ph)
    for q in t: p.highest = max(p.highest, q)
    return p


def mul_pauli(a, b):
    r = a.clone(); r.phase *= b.phase
    for q, c in b.terms.items():
        prior = r.terms.get(q)
        if prior is None or prior == "I": r.terms[q] = c; continue
        if c == "I": continue
        if prior == c: del r.terms[q]; continue
        cc = "X" if (prior != "X" and c != "X") else ("Y" if (prior != "Y" and c != "Y") else "Z")
        pos = (prior == "X" and c == "Y") or (prior == "Y" and c == "Z") or (prior == "Z" and c == "X")
        r.terms[q] = cc; r.phase *= (1j if pos else -1j)
    r.highest = max(a.highest, b.highest)
    return r


def gate_record(g):
    return D("name", g.name, "angles", list(g.angles), "qubits", list(g.qubits))


def is_clifford(u, n):
    count = 1 << (2 * n); ud = C.dagger(u)
    for q in range(n):
        for axis in "XZ":
            test = C.matmul(C.matmul(u, C.pauli_matrix(axis + str(q), n)), ud); found = False
            for code in range(count):
                parts = []
                for k in range(n):
                    a = (code >> (2 * k)) & 3
                    if a > 0: parts.append(("X" if a == 1 else "Y" if a == 2 else "Z") + str(k))
                p = C.pauli_matrix(" ".join(parts), n)
                err, ph = C.matrix_difference(test, p, True)
                if err <= 1e-10 and abs(ph.imag) <= 1e-10 and abs(abs(ph.real) - 1) <= 1e-10:
                    found = True; break
            if not found: return False
    return True


def apply_dense(state, gate, qs):
    local = 1 << len(qs); mask = 0
    for q in qs: mask |= 1 << q
    r = [0j] * len(state)
    for y in range(len(r)):
        ly = 0
        for k, q in enumerate(qs):
            if y & (1 << q): ly |= 1 << k
        base = y & ~mask; val = 0j
        for lx in range(local):
            x = base
            for k, q in enumerate(qs):
                if lx & (1 << k): x |= 1 << q
            val += gate[ly][lx] * state[x]
        r[y] = val
    return r, len(state), len(state) * local


SYNTH_MSG = ("Needs backend: validated Clifford+T synthesis and requested operator-norm error bound are not installed.")


class Advanced(object):
    def execute(self, words):
        if words is None or len(words) < 2: raise ValueError("Use namespace action key=value.")
        ns = words[0].lower(); action = words[1].lower(); sub = None; parse = words
        if ns == "q.qec" and action in ("repetition3", "phase-repetition3"):
            if len(words) < 3: raise ValueError("Use q.qec repetition3 encode|simulate|syndrome-table key=value.")
            sub = words[2].lower(); parse = [words[0], words[1]] + list(words[3:])
        f = C.parse_fields(parse); t0 = time.perf_counter()
        if ns == "q.noise": r = self.noise(action, f)
        elif ns == "q.qec": r = self.qec(action, sub, f)
        elif ns == "q.compile": r = self.compile(action, f)
        elif ns == "q.algorithm": r = self.algorithm(action, f)
        else: raise ValueError("Unknown advanced calculator namespace.")
        r["namespace"] = ns; r["action"] = action
        if sub is not None: r["subaction"] = sub
        r["elapsedMs"] = (time.perf_counter() - t0) * 1000.0; r["physicalQuantumOperations"] = 0; r["proceduralFamilyGateCredit"] = 0
        r["measurementSeedChanged"] = False; r["measurementCounterChanged"] = False; r["complexLayout"] = "[real,imaginary]"
        r.setdefault("backend", "bounded-classical-complex-FP64"); r.setdefault("resultKind", "numerical")
        from .calculators import validate_output
        validate_output(r)
        return r

    def noise(self, a, f):
        if a in ("apply", "circuit"):
            ch = C.required(f, "channel").lower()
            par = "gamma" if ch == "amplitude-damping" else ("lambda" if ch == "dephasing" else "p")
            perm = ("state rho" if a == "apply" else "n input gates targets independent") + " channel " + par
            if ch in ("depolarizing", "dephasing"): perm += " convention"
            C.check_fields(f, perm); n = 1; gc = 0
            if a == "apply":
                if f.has("state") == f.has("rho"): raise ValueError("Supply exactly one state or rho.")
                rho = C.density(qubit(f.get_ci("state"))) if f.has("state") else C.parse_matrix(f.get_ci("rho"))
                if len(rho) != 2 or len(rho[0]) != 2: raise ValueError("q.noise apply uses a one-qubit density matrix.")
                C.require_density(rho); targets = [0]
            else:
                n = C.integer(C.required(f, "n"), 1, 4); inp = C.integer(C.required(f, "input"), 0, (1 << n) - 1)
                gates = parse_gates(C.required(f, "gates"), n); gc = len(gates)
                v = [0j] * (1 << n); v[inp] = 1 + 0j; v = C.matvec(circuit_matrix(gates, n), v); rho = C.density(v)
                targets = C.qubit_list(C.required(f, "targets"), n, n)
                if f.has("independent") and not C.boolean(f.get_ci("independent")):
                    raise ValueError("Multiple-target channel applies independent local channels; independent must be true.")
            for q in targets: rho = channel(rho, n, q, ch, f)
            r = D("rho", C.mj(rho), "purity", C.purity(rho), "entropyBits", C.entropy(rho, 2), "trace", C.cj(C.trace(rho)), "channel", ch,
                  "parameter", par, "parameterValue", C.real(f.get_ci(par)), "targets", targets, "independentLocalChannels", len(targets),
                  "simulatedCircuitGateApplications", gc, "sampledShots", 0,
                  "scope", "Explicit density evolution of named local channels; output probabilities are not measurement counts.")
            if ch == "depolarizing": r["convention"] = "(1-p)rho + p(I_target/2 tensor partial trace over target); local Kraus realization"
            if n == 1: r["bloch"] = [2 * rho[0][1].real, -2 * rho[0][1].imag, rho[0][0].real - rho[1][1].real]
            return r
        if a in ("t1", "t2"):
            C.check_fields(f, "excited-probability time-us t1-us" if a == "t1" else "coherence time-us t2-us")
            t = C.real(C.required(f, "time-us")); k = C.real(C.required(f, "t1-us" if a == "t1" else "t2-us"))
            if t < 0 or k <= 0: raise ValueError("Time must be nonnegative and relaxation constant positive, both in microseconds.")
            dec = math.exp(-t / k)
            if a == "t1":
                ex = unit(f, "excited-probability")
                return D("excitedProbability", ex * dec, "groundProbability", 1 - ex * dec, "decayFactor", dec, "units", "microseconds",
                         "assumption", "Zero-temperature Markovian population relaxation; leakage and non-Markovian effects excluded.")
            co = C.complex_expr(C.required(f, "coherence"))
            if abs(co) > .5 + TOL: raise ValueError("A qubit's off-diagonal coherence magnitude cannot exceed1/2.")
            return D("coherence", C.cj(co * dec), "magnitude", abs(co) * dec, "decayFactor", dec, "units", "microseconds",
                     "assumption", "Exponential off-diagonal decay; supplied T2, with no T1 or pure-dephasing rate inferred.")
        if a == "readout":
            C.check_fields(f, "probabilities confusion orientation"); C.choice(f, "orientation", "rows-observed-columns-true")
            p = C.parse_vector(C.required(f, "probabilities")); c = C.parse_matrix(C.required(f, "confusion"))
            if len(c) != len(p) or len(c[0]) != len(p): raise ValueError("Square confusion matrix must match probability count.")
            s = 0.0
            for v in p:
                if v.real < 0 or abs(v.imag) > 1e-12: raise ValueError("Probabilities must be real nonnegative.")
                s += v.real
            if abs(s - 1) > TOL: raise ValueError("Probabilities must sum to one.")
            for j in range(len(p)):
                col = 0.0
                for i in range(len(p)):
                    if c[i][j].real < 0 or c[i][j].real > 1 or abs(c[i][j].imag) > 1e-12: raise ValueError("Confusion entries must be real probabilities.")
                    col += c[i][j].real
                if abs(col - 1) > TOL: raise ValueError("Each true-state confusion column must sum to one.")
            out = C.matvec(c, p)
            return D("observedProbabilities", [z.real for z in out], "orientation", "rows-observed-columns-true",
                     "scope", "Classical forward model; no inverse mitigation or sampled readout performed.")
        if a == "zne":
            C.check_fields(f, "scales expectations model"); C.choice(f, "model", "linear")
            sc = C.angles_list(C.required(f, "scales")); vals = C.angles_list(C.required(f, "expectations"))
            if len(sc) < 2 or len(sc) > 64 or len(sc) != len(vals): raise ValueError("Use2..64 matched noise scales and expectations.")
            x = 0.0; y = 0.0
            for s in sc:
                if s <= 0: raise ValueError("Noise scales must be positive.")
                x += s
            for v in vals: y += v
            x /= len(sc); y /= len(vals); xx = 0.0; xy = 0.0
            for i in range(len(sc)):
                xx += (sc[i] - x) * (sc[i] - x); xy += (sc[i] - x) * (vals[i] - y)
            if xx <= 1e-24: raise ValueError("Noise scales must not all coincide.")
            slope = xy / xx; est = y - slope * x; vf = 0.0; res = 0.0; w = []
            for i in range(len(sc)):
                wi = 1.0 / len(sc) - x * (sc[i] - x) / xx; w.append(wi); vf += wi * wi
                e = vals[i] - (est + slope * sc[i]); res += e * e
            return D("zeroNoiseEstimate", est, "slope", slope, "weights", w, "residualSumSquares", res, "independentEqualVarianceAmplification", vf,
                     "resultKind", "resource-estimate",
                     "scope", "Ordinary least-squares linear extrapolation to scale0; may amplify variance or leave physical bounds. No extra experiments performed and no physical noise-scaling guarantee inferred.")
        raise ValueError("Unsupported q.noise action.")

    def qec(self, a, sub, f):
        if a in ("repetition3", "phase-repetition3"):
            phase = a == "phase-repetition3"
            if sub == "syndrome-table":
                C.check_fields(f, "errors stabilizers")
                if phase: raise ValueError("The supplied syndrome-table command uses the bit repetition code.")
                st = C.split_list(C.required(f, "stabilizers"))
                if len(st) != 2 or C.unquote(st[0]) != "Z0 Z1" or C.unquote(st[1]) != "Z1 Z2":
                    raise ValueError("repetition3 syndrome table uses stabilizers Z0 Z1 and Z1 Z2.")
                te = C.split_list(C.required(f, "errors"))
                if len(te) < 1 or len(te) > 8: raise ValueError("Use1..8 explicit tableErrors.")
                rws = []
                for e in te:
                    syn = syndrome(error_mask([C.unquote(e)], False)); rc = recovery(syn)
                    rws.append(D("error", C.unquote(e), "syndromeBits", syn, "stabilizerEigenvalues", [1 if syn[0] == 0 else -1, 1 if syn[1] == 0 else -1],
                                 "recovery", "I" if rc < 0 else "X" + str(rc)))
                return D("rows", rws, "scope", "Exact deterministic syndrome calculation for specified Pauli tableErrors; no syndrome shots sampled.")
            if sub not in ("encode", "simulate"): raise ValueError("Use encode, simulate, or syndrome-table.")
            C.check_fields(f, "state" if sub == "encode" else "state error errors recover")
            lg = qubit(C.required(f, "state")); enc = [0j] * 8; enc[0] = lg[0]; enc[7] = lg[1]
            h = C.gate_matrix("h", []); hhh = C.tensor(h, C.tensor(h, h))
            if phase: enc = C.matvec(hhh, enc)
            if sub == "encode":
                return D("encodedAmplitudes", C.vj(enc), "logicalAmplitudes", C.vj(lg), "code", "three-qubit phase repetition" if phase else "three-qubit bit repetition",
                         "scope", "Actual8-component ideal encoding calculation; this code protects only its declared error class.")
            if f.has("error") == f.has("errors"): raise ValueError("Supply exactly one error or errors list.")
            errs = [f.get_ci("error")] if f.has("error") else C.split_list(f.get_ci("errors"))
            if len(errs) < 1 or len(errs) > 32: raise ValueError("Use1..32 specified Pauli error factors.")
            mask = error_mask(errs, phase); syn = syndrome(mask); rc = recovery(syn)
            rec = C.boolean(C.optional(f, "recover", "true"))
            cm = mask ^ ((1 << rc) if rec and rc >= 0 else 0)
            cor = apply_mask(enc, mask, phase); fixed = apply_mask(cor, 1 << rc, phase) if rec and rc >= 0 else cor
            dec = C.matvec(hhh, fixed) if phase else fixed; dl = [dec[0], dec[7]]
            mass = abs(dl[0]) * abs(dl[0]) + abs(dl[1]) * abs(dl[1]); ov = C.overlap(enc, fixed)
            return D("encodedAmplitudes", C.vj(enc), "erroredAmplitudes", C.vj(cor), "correctedAmplitudes", C.vj(fixed), "syndromeBits", syn,
                     "recovery", (("Z" if phase else "X") + str(rc)) if rec and rc >= 0 else "I", "recoveryApplied", rec and rc >= 0,
                     "decoderEnabled", rec, "residualErrorMask", cm, "logicalBitFlip", cm == 7, "inCodeSpace", abs(mass - 1) <= TOL,
                     "decodedLogicalAmplitudes", C.vj(dl) if mass > 1 - TOL else None, "stateFidelity", abs(ov) * abs(ov),
                     "code", "phase repetition" if phase else "bit repetition",
                     "scope", "Specified Pauli errors have a deterministic syndrome. Ideal decoder corrects one declared-class error, while two can induce a logical error; no stochastic syndrome or hardware correction is credited.")
        if a == "validate":
            C.check_fields(f, "stabilizers"); lst = C.split_list(C.required(f, "stabilizers"))
            if len(lst) < 1 or len(lst) > 64: raise ValueError("Use1..64 stabilizer generators.")
            ps = []; n = 1
            for raw in lst:
                p = read_pauli(C.unquote(raw)); ps.append(p); n = max(n, p.highest + 1)
            comm = True
            for i in range(len(ps)):
                for j in range(i): comm = comm and C.paulis_commute(ps[i].terms, ps[j].terms)
            piv = {}; inc = False; rank = 0
            if comm:
                for ini in ps:
                    row = ini.clone()
                    while True:
                        b = row.binary()
                        if b == 0:
                            if abs(row.phase - 1) > TOL: inc = True
                            break
                        pv = 0
                        while not b & (1 << pv): pv += 1
                        if pv in piv: row = mul_pauli(row, piv[pv])
                        else: piv[pv] = row; rank += 1; break
            return D("valid", comm and not inc, "mutuallyCommuting", comm, "containsNegativeIdentityRelation", inc, "independentRank", rank,
                     "inferredPhysicalQubits", n, "encodedQubits", (n - rank) if comm and not inc else None,
                     "scope", "Phase-aware algebraic generator consistency over named operands; inferred n includes every index0..highest. This is not a tableau circuit simulator or a distance proof.")
        if a == "parameters":
            C.check_fields(f, "n independent-stabilizers"); n = C.integer(C.required(f, "n"), 1, 1000000); rk = C.integer(C.required(f, "independent-stabilizers"), 0, n)
            return D("n", n, "independentStabilizers", rk, "encodedQubits", n - rk, "distance", None, "resultKind", "resource-estimate",
                     "assumption", "User asserts commuting, independent, consistent stabilizer checks. Rank alone does not determine distance or logical error rate.")
        if a == "correction-budget":
            C.check_fields(f, "distance"); d = C.integer(C.required(f, "distance"), 1, 1000000)
            return D("distance", d, "maximumArbitraryUnknownLocationErrors", (d - 1) // 2, "maximumKnownLocationErasures", d - 1, "resultKind", "resource-estimate",
                     "scope", "Ideal code-distance bounds; no fault-tolerant syndrome circuit or noise threshold inferred.")
        if a == "compare":
            C.check_fields(f, "mitigation correction"); C.choice(f, "mitigation", "zne"); C.choice(f, "correction", "stabilizer-code")
            return D("resultKind", "theory", "backend", "documented-theory",
                     "explanation", "ZNE extrapolates noisy expectation estimates under a noise-scaling model; a stabilizer error-correcting code uses redundancy, syndrome information and recovery under a specified error model. Mitigation is not general fault tolerance, and code protection also requires suitable fault-tolerant operations and decoding.",
                     "references", ["https://arxiv.org/abs/2005.10921", "https://arxiv.org/abs/quant-ph/9611025"])
        raise ValueError("Unsupported q.qec action.")

    def compile(self, a, f):
        if a == "synthesize": raise RuntimeError(SYNTH_MSG)
        if a == "universality":
            C.check_fields(f, "set semantics"); C.choice(f, "semantics", "approximate")
            s = set(C.unquote(x).lower() for x in C.split_list(C.required(f, "set")))
            if s != {"h", "t", "cx"}: raise ValueError("This reference entry is for {H,T,CX}.")
            return D("resultKind", "theory", "backend", "documented-theory", "approximatelyUniversal", True,
                     "explanation", "Repeated H,T and CX generate approximately universal qubit circuits; one circuit containing a T gate alone is neither universal computation nor a proof of speedup. No synthesized sequence or hardware error guarantee is returned.",
                     "references", ["https://arxiv.org/abs/quant-ph/0403025"])
        if a == "identity":
            C.check_fields(f, "left right n equivalence"); n = C.integer(C.required(f, "n"), 1, 4); eqv = C.optional(f, "equivalence", "exact")
            if eqv not in ("exact", "global-phase"): raise ValueError("equivalence is exact or global-phase.")
            le = parse_gates(C.required(f, "left"), n); ri = parse_gates(C.required(f, "right"), n)
            x = circuit_matrix(le, n); y = circuit_matrix(ri, n); err, ph = C.matrix_difference(x, y, eqv == "global-phase")
            return D("equivalent", err <= 1e-12, "maximumElementError", err, "tolerance", 1e-12, "equivalence", eqv, "phaseMultiplier", C.cj(ph),
                     "leftGateApplications", len(le), "rightGateApplications", len(ri), "leftMatrix", C.mj(x), "rightMatrix", C.mj(y),
                     "scope", "Full small-register matrices composed chronologically; no gate sequence committed to selected circuit.")
        if a == "simplify":
            C.check_fields(f, "n gates preserve-global-phase"); C.choice(f, "preserve-global-phase", "true")
            n = C.integer(C.required(f, "n"), 1, 29); inp = parse_gates(C.required(f, "gates"), n); st = []; rem = 0
            for cur in inp:
                cancel = False
                if st:
                    prev = st[-1]
                    if prev.qubits == cur.qubits:
                        prod = C.matmul(C.gate_matrix(cur.name, cur.angles), C.gate_matrix(prev.name, prev.angles))
                        cancel = C.matrix_difference(prod, C.identity(len(prod)), False)[0] <= 1e-12
                if cancel: st.pop(); rem += 2
                else: st.append(cur)
            return D("originalGateApplications", len(inp), "remainingGateApplications", len(st), "removedGateApplications", rem,
                     "gates", [gate_record(g) for g in st], "preserveGlobalPhase", True,
                     "scope", "Only adjacent same-operand exact inverse pairs canceled at1e-12 element tolerance; no commuting or approximate rewrite guessed.")
        if a in ("count", "depth", "classify"):
            C.check_fields(f, "n gates counting" if a == "count" else ("n gates connectivity scheduling" if a == "depth" else "n gates input"))
            n = C.integer(C.required(f, "n"), 1, 29); gates = parse_gates(C.required(f, "gates"), n)
            if a == "count":
                C.choice(f, "counting", "logical"); t = two = three = 0; names = {}
                for g in gates:
                    if g.name in ("t", "tdg"): t += 1
                    if len(g.qubits) == 2: two += 1
                    if len(g.qubits) == 3: three += 1
                    names[g.name] = names.get(g.name, 0) + 1
                return D("logicalGateApplications", len(gates), "TCount", t, "twoQubitCount", two, "threeQubitCount", three, "perGate", names,
                         "resultKind", "resource-estimate", "scope", "Logical expanded gate count; not simulator arithmetic or hardware duration.")
            if a == "depth":
                C.choice(f, "connectivity", "all-to-all"); C.choice(f, "scheduling", "earliest-dependencies")
                ends = [0] * n; depth = 0; sch = []
                for g in gates:
                    layer = 1
                    for q in g.qubits: layer = max(layer, ends[q] + 1)
                    for q in g.qubits: ends[q] = layer
                    depth = max(depth, layer); sch.append(D("gate", gate_record(g), "layer", layer))
                return D("idealLogicalDepth", depth, "schedule", sch, "connectivity", "all-to-all", "resultKind", "resource-estimate",
                         "scope", "Unit-duration logical gates, no crosstalk/routing/measurement/control latency. Disjoint operands may share a layer.")
            C.choice(f, "input", "computational-basis"); cl = True; non = []
            for g in gates:
                if not is_clifford(C.gate_matrix(g.name, g.angles), len(g.qubits)): cl = False; non.append(g.name)
            return D("classification", "Clifford-compatible" if cl else "contains-non-Clifford", "cliffordAtTolerance", cl, "tolerance", 1e-10,
                     "nonCliffordInstructions", non, "recommendedBackend", "phase-aware stabilizer tableau if installed" if cl else "selected coherent statevector/factors",
                     "installedExecutionBackend", "selected coherent statevector/factors", "tableauBackendInstalled", False,
                     "scope", "Checked conjugation of local Pauli generators. Classification is not an executed circuit or a computational-advantage proof.")
        raise ValueError("Unsupported q.compile action.")

    def algorithm(self, a, f):
        if a != "phase-estimation": raise ValueError("Unsupported q.algorithm action.")
        C.check_fields(f, "counting-qubits unitary eigenstate power-map inverse-qft"); C.choice(f, "power-map", "qj-controls-U^(2^j)")
        C.choice(f, "inverse-qft", "include-final-swaps"); m = C.integer(C.required(f, "counting-qubits"), 1, 8); n = m + 1
        u = re.split(r"\s+", C.required(f, "unitary").strip())
        if len(u) != 3 or alias(u[0]) != "p" or C.integer(u[2], m, m) != m:
            raise ValueError("This validated phase-estimation toy backend requires unitary='p ANGLE TARGET' with TARGET=counting-qubits.")
        th = C.real(u[1])
        if abs(th) > 1e9: raise ValueError("Phase-estimation base angle magnitude<=1e9.")
        eig = qubit(C.required(f, "eigenstate")); zero = abs(eig[1]) <= 1e-12; one = abs(eig[0]) <= 1e-12
        if not zero and not one:
            raise ValueError("The supplied vector must be a computational eigenstate of P; arbitrary eigenstate/unitary phase estimation needs another backend.")
        st = [0j] * (1 << n); st[0] = eig[0]; st[1 << m] = eig[1]
        gates = [Ins("h", [], [q]) for q in range(m)] + [Ins("cp", [th * math.pow(2, q)], [q, m]) for q in range(m)]
        qft = []
        for q in range(m - 1, -1, -1):
            qft.append(Ins("h", [], [q]))
            for lo in range(q - 1, -1, -1): qft.append(Ins("cp", [math.pi / math.pow(2, q - lo)], [q, lo]))
        for q in range(m // 2): qft.append(Ins("swap", [], [q, m - 1 - q]))
        for g in reversed(qft): gates.append(Ins(g.name, [-x for x in g.angles], g.qubits))
        writes = 2; prods = 0
        for g in gates:
            st, pw, pp = apply_dense(st, C.gate_matrix(g.name, g.angles), g.qubits); writes += pw; prods += pp
        C.require_pure(st)
        probs = [0.0] * (1 << m)
        for x in range(len(st)): probs[x & ((1 << m) - 1)] += abs(st[x]) * abs(st[x])
        likely = 0
        for x in range(1, len(probs)):
            if probs[x] > probs[likely]: likely = x
        ep = th / (2 * math.pi) if one else 0.0; ep -= math.floor(ep)
        return D("countingQubits", m, "targetQubit", m, "probabilities", probs, "mostLikelyOutcome", likely, "mostLikelyBitstring", C.bits(likely, m),
                 "mostLikelyPhase", likely / float(1 << m), "eigenphaseModuloOne", ep, "premeasurementAmplitudes", C.vj(st),
                 "simulatedGateApplications", len(gates), "actualAmplitudeWrites", writes, "actualComplexMultiplications", prods,
                 "actualPreparedStateVectors", 1, "sampledShots", 0,
                 "scope", "Actual bounded coherent statevector evolution; no measurement draws. Counts are source-level simulator work, not physical quantum operations.",
                 "powerMap", "qj controls U^(2^j)", "qftConvention", "Inverse positive-exponent QFT with final bit-reversal swaps; q0 least significant.")
