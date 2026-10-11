# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Port of SpinDoctorCalculators.cs: q.math, q.query, q.resource, q.model, q.lesson.
Bounded classical complex-FP64 calculators (vectors <=4096, matrices <=16x16)."""
import cmath
import math
import re
import time

from .register import GATE_SPECS

TOL = 2e-9
MAX_FULL_QUERY_QUBITS = 16
MAX_ROWS = 4096


def D(*p):
    return {p[i]: p[i + 1] for i in range(0, len(p), 2)}


def _caps(ns, actions, backend, kind):
    out = []
    for a in actions.split(" "):
        out.append({"command": ns + " " + a, "namespace": ns, "action": a, "installed": True, "backend": backend, "resultKind": kind,
                    "limits": "Prefix <=4096; full joint analysis <=16 qubits/65536 states; one-qubit reductions via exact native spin <=298, factor width <=59." if ns == "q.query" else "Vectors <=4096, matrices <=16x16; resource counts are estimates, not allocations.",
                    "validation": "calculator-validation.json"})
    return out


def capabilities():
    r = []
    r += _caps("q.math", "normalize norm probabilities bloch from-bloch validate-bloch density validate-density purity entropy overlap fidelity trace-distance gate-matrix compare-gates unitary tensor commutator eigen expectation canonical-phase", "bounded-complex-FP64", "numerical")
    r += _caps("q.query", "amplitudes probabilities marginal reduced-density purity entropy expectation concurrence negativity stabilizers fidelity", "selected-coherent-register", "analysis")
    r += _caps("q.resource", "memory max-n factor-memory tranche-plan sampling shots grover qec headroom auto", "classical-resource-formulas", "resource-estimate")
    r += _caps("q.model", "spectrum ising qubo-to-ising evolve mbqc", "bounded-complex-FP64", "numerical")
    r += _caps("q.model", "compare compare-codes topology", "documented-theory", "theory")
    r += _caps("q.lesson", "amplitude-vs-probability entanglement complexity parallelism stabilizer magic algorithms pqc", "documented-theory", "theory")
    return r


def supports(ns, action):
    key = ns.lower() + " " + action.lower()
    return any(c["command"] == key for c in capabilities())


# ---------------------------------------------------------------- parsing
def parse_fields(words):
    if words is None or len(words) < 2:
        raise ValueError("Use namespace action key=value.")
    text = " ".join(words[2:])
    if len(text) > 16384:
        raise ValueError("Calculator input exceeds 16 KiB.")
    result = {}; lower = set(); p = 0; n = len(text)
    while p < n:
        while p < n and text[p].isspace(): p += 1
        if p == n: break
        start = p
        while p < n and (text[p].isalnum() or text[p] in "-_"): p += 1
        if p == start or p >= n or text[p] != "=":
            raise ValueError("Expected key=value near " + text[start:start + 32] + ".")
        key = text[start:p]; p += 1; start = p; depth = 0; quote = ""; esc = False
        while p < n:
            c = text[p]
            if quote:
                if esc: esc = False
                elif c == "\\": esc = True
                elif c == quote: quote = ""
                p += 1; continue
            if c in "\"'":
                quote = c; p += 1; continue
            if c in "[(":
                depth += 1
                if depth > 32: raise ValueError("Field nesting exceeds 32.")
            elif c in "])":
                depth -= 1
                if depth < 0: raise ValueError("Unbalanced field brackets.")
            elif c.isspace() and depth == 0:
                break
            p += 1
        if quote or depth != 0:
            raise ValueError("Unclosed quoted/bracketed field.")
        value = text[start:p]
        if not value or key.lower() in lower:
            raise ValueError("Empty or duplicate field " + key + ".")
        lower.add(key.lower()); result[key] = unquote(value)
    return CIDict(result)


class CIDict(dict):
    """Case-insensitive field dictionary (StringComparer.OrdinalIgnoreCase)."""

    def __init__(self, d):
        super().__init__(d)
        self._map = {k.lower(): k for k in d}

    def has(self, k):
        return k.lower() in self._map

    def get_ci(self, k, default=None):
        kk = self._map.get(k.lower())
        return self[kk] if kk is not None else default


def unquote(s):
    s = s.strip()
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1]; b = []; i = 0
        while i < len(s):
            if s[i] == "\\":
                i += 1
                if i >= len(s) or s[i] not in "\\\"'":
                    raise ValueError("Only quote and backslash escapes are accepted.")
            b.append(s[i]); i += 1
        return "".join(b)
    return s


def split_list(s):
    s = s.strip()
    if len(s) < 2 or s[0] != "[" or s[-1] != "]":
        raise ValueError("Expected bracket list.")
    s = s[1:-1]; r = []; begin = 0; depth = 0; quote = ""; esc = False
    for p, c in enumerate(s):
        if quote:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == quote: quote = ""
            continue
        if c in "\"'": quote = c; continue
        if c in "[(": depth += 1
        elif c in "])":
            depth -= 1
            if depth < 0: raise ValueError("List brackets are unbalanced.")
        elif c == "," and depth == 0:
            r.append(s[begin:p].strip()); begin = p + 1
    if depth != 0 or quote:
        raise ValueError("List is unclosed.")
    if s.strip(): r.append(s[begin:].strip())
    for v in r:
        if not v: raise ValueError("List contains an empty item.")
    return r


def required(f, k):
    v = f.get_ci(k)
    if v is None: raise ValueError("Missing field " + k + ".")
    return v


def optional(f, k, fb):
    v = f.get_ci(k)
    return fb if v is None else v


def check_fields(f, allowed):
    names = set(a.lower() for a in allowed.split(" "))
    for k in f:
        if k.lower() not in names:
            raise ValueError("Unknown field " + k + ".")


def choice(f, k, expected):
    v = f.get_ci(k)
    if v is not None and v.lower() != expected.lower():
        raise ValueError(k + " must be " + expected + ".")


def real(s):
    c = complex_expr(s)
    if abs(c.imag) > 1e-12: raise ValueError("Expected a real value.")
    return c.real


def integer(s, lo, hi):
    try:
        x = real(s)
    except ValueError:
        raise ValueError("Expected an integer value.")
    if x != math.floor(x):
        raise ValueError("Expected an integer value.")
    if x < lo or x > hi or x != math.floor(x):
        raise ValueError("Integer must be in " + str(lo) + ".." + str(hi) + ".")
    return int(x)


def big(s, positive):
    if len(s) > 320 or not re.fullmatch(r"\s*[+-]?\d+\s*", s):
        raise ValueError("Expected a nonnegative decimal integer" + (" greater than zero" if positive else "") + ".")
    n = int(s)
    if n < 0 or (positive and n == 0):
        raise ValueError("Expected a nonnegative decimal integer" + (" greater than zero" if positive else "") + ".")
    return n


def boolean(s):
    if s.strip().lower() == "true": return True
    if s.strip().lower() == "false": return False
    raise ValueError("Expected true or false.")


def cpow(c, d):
    if d == 0: return 1 + 0j
    if c == 0: return 0j
    a, b = c.real, c.imag; pr, pi_ = d.real, d.imag
    rho = abs(c); theta = math.atan2(b, a)
    new_rho = pr * theta + pi_ * math.log(rho)
    t = math.pow(rho, pr) * math.exp(-pi_ * theta)
    return complex(t * math.cos(new_rho), t * math.sin(new_rho))


class ComplexParser(object):
    def __init__(self, s):
        self.t = s or ""; self.p = 0; self.depth = 0; self.ops = 0
        if not self.t or len(self.t) > 2048:
            raise ValueError("Expression length must be 1..2048.")

    def space(self):
        while self.p < len(self.t) and self.t[self.p].isspace(): self.p += 1

    def eat(self, c):
        self.space()
        if self.p < len(self.t) and self.t[self.p] == c:
            self.p += 1; return True
        return False

    def chk(self, c):
        self.ops += 1
        if self.ops > 1024 or any(math.isnan(x) or math.isinf(x) for x in (c.real, c.imag)):
            raise ValueError("Expression is nonfinite or exceeds operation bound.")
        return complex(0.0 if c.real == 0 else c.real, 0.0 if c.imag == 0 else c.imag)

    def evaluate(self):
        c = self.add(); self.space()
        if self.p != len(self.t):
            raise ValueError("Unexpected expression token near " + self.t[self.p:self.p + 24] + ".")
        return self.chk(c)

    def add(self):
        c = self.mul()
        while True:
            if self.eat("+"): c = self.chk(c + self.mul())
            elif self.eat("-"): c = self.chk(c - self.mul())
            else: return c

    def mul(self):
        c = self.unary()
        while True:
            if self.eat("*"): c = self.chk(c * self.unary())
            elif self.eat("/"):
                d = self.unary()
                if d == 0: raise ValueError("Division by zero.")
                c = self.chk(c / d)
            else: return c

    def unary(self):
        self.depth += 1
        if self.depth > 32: raise ValueError("Expression depth exceeds 32.")
        try:
            if self.eat("+"): return self.unary()
            if self.eat("-"): return self.chk(-self.unary())
            return self.power()
        finally:
            self.depth -= 1

    def power(self):
        c = self.atom()
        if self.eat("^"):
            try:
                c = self.chk(cpow(c, self.unary()))
            except (OverflowError, ValueError) as e:
                raise ValueError("Expression is nonfinite or exceeds operation bound.") from e
        return c

    def atom(self):
        self.space()
        if self.eat("("):
            c = self.add()
            if not self.eat(")"): raise ValueError("Missing closing parenthesis.")
            return c
        self.space(); t = self.t; b = self.p
        if self.p < len(t) and (t[self.p].isdigit() or t[self.p] == "."):
            while self.p < len(t) and (t[self.p].isdigit() or t[self.p] == "."): self.p += 1
            if self.p < len(t) and t[self.p] in "eE":
                self.p += 1
                if self.p < len(t) and t[self.p] in "+-": self.p += 1
                while self.p < len(t) and t[self.p].isdigit(): self.p += 1
            try:
                d = float(t[b:self.p])
            except ValueError:
                raise ValueError("Invalid numeric literal.")
            return self.chk(complex(d, 0))
        while self.p < len(t) and t[self.p].isalpha(): self.p += 1
        if self.p == b: raise ValueError("Expected a number, constant, or function.")
        n = t[b:self.p].lower()
        if n == "pi": return complex(math.pi, 0)
        if n == "e": return complex(math.e, 0)
        if n == "i": return 1j
        if not self.eat("("): raise ValueError("Unknown constant " + n + ".")
        x = self.add()
        if not self.eat(")"): raise ValueError("Missing function closing parenthesis.")
        fn = {"sqrt": cmath.sqrt, "sin": cmath.sin, "cos": cmath.cos, "tan": cmath.tan, "exp": cmath.exp,
              "log": cmath.log, "asin": cmath.asin, "acos": cmath.acos, "atan": cmath.atan}
        if n == "abs": return complex(abs(x), 0)
        if n not in fn: raise ValueError("Unknown function " + n + ".")
        try:
            return self.chk(fn[n](x))
        except (OverflowError, ValueError) as e:
            raise ValueError("Expression is nonfinite or exceeds operation bound.") from e


def complex_expr(s):
    return ComplexParser(s).evaluate()


def parse_vector(s):
    a = split_list(s)
    if len(a) < 1 or len(a) > 4096: raise ValueError("Vector length must be 1..4096.")
    return [complex_expr(x) for x in a]


def parse_matrix(s):
    s = s.strip()
    if s and s[0] != "[":
        if s.lower() == "i2": return identity(2)
        return gate_matrix(s.lower(), [])
    rows = split_list(s)
    if len(rows) < 1 or len(rows) > 16: raise ValueError("Matrix supports 1..16 rows.")
    m = []; cols = 0
    for i, r in enumerate(rows):
        v = parse_vector(r)
        if i == 0: cols = len(v)
        if len(v) != cols or cols > 16: raise ValueError("Matrix must be rectangular, <=16 columns.")
        m.append(v)
    return m


# ---------------------------------------------------------------- linear algebra
def cj(c): return [c.real, c.imag]
def vj(v): return [cj(c) for c in v]
def mj(m): return [[cj(c) for c in row] for row in m]
def rows(m): return len(m)
def cols(m): return len(m[0]) if m else 0


def identity(n):
    return [[(1 + 0j) if i == j else 0j for j in range(n)] for i in range(n)]


def zeros(r, c):
    return [[0j] * c for _ in range(r)]


def finite_m(m):
    for row in m:
        for z in row:
            if not _fin(z): raise ValueError("Numerical result is nonfinite.")


def _fin(z):
    return not (math.isnan(z.real) or math.isinf(z.real) or math.isnan(z.imag) or math.isinf(z.imag))


def dagger(a):
    return [[a[i][j].conjugate() for i in range(rows(a))] for j in range(cols(a))]


def matmul(a, b):
    if cols(a) != rows(b): raise ValueError("Matrix dimensions do not match.")
    c = zeros(rows(a), cols(b))
    for i in range(rows(a)):
        for j in range(cols(b)):
            s = 0j
            for k in range(cols(a)):
                s += a[i][k] * b[k][j]
            c[i][j] = s
    finite_m(c); return c


def matvec(a, v):
    if cols(a) != len(v): raise ValueError("Matrix/vector dimensions do not match.")
    r = []
    for i in range(rows(a)):
        s = 0j
        for j in range(len(v)): s += a[i][j] * v[j]
        r.append(s)
    for z in r:
        if not _fin(z): raise ValueError("Numerical result is nonfinite.")
    return r


def tensor(a, b):
    n = rows(a) * rows(b); m = cols(a) * cols(b)
    if n > 16 or m > 16: raise ValueError("Tensor output supports <=16x16.")
    r = zeros(n, m)
    for i in range(rows(a)):
        for j in range(cols(a)):
            for k in range(rows(b)):
                for l in range(cols(b)):
                    r[i * rows(b) + k][j * cols(b) + l] = a[i][j] * b[k][l]
    finite_m(r); return r


def square(m):
    if rows(m) != cols(m): raise ValueError("Square matrix required.")


def norm_sq(v):
    s = 0.0
    for z in v: s += z.real * z.real + z.imag * z.imag
    if math.isnan(s) or math.isinf(s): raise ValueError("Norm is nonfinite.")
    return s


def normalize(v):
    # 3.1.x: scale by the largest component first so tiny or huge inputs stay finite.
    for z in v:
        if not (math.isfinite(z.real) and math.isfinite(z.imag)): raise ValueError("Complex values must be finite.")
    scale = 0.0
    for z in v: scale = max(scale, abs(z.real), abs(z.imag))
    if scale == 0: raise ValueError("Cannot normalize a zero vector.")
    r = [complex(z.real / scale, z.imag / scale) for z in v]
    n = math.sqrt(sum(z.real * z.real + z.imag * z.imag for z in r))
    return [z / n for z in r]


def validate_output(value):
    """3.1.x ValidateOutput: refuse nonfinite FP64 numbers anywhere in a result."""
    if isinstance(value, float):
        if not math.isfinite(value): raise ValueError("Numerical result exceeds the finite FP64 range.")
    elif isinstance(value, dict):
        for x in value.values(): validate_output(x)
    elif isinstance(value, (list, tuple)):
        for x in value: validate_output(x)


def bloch_state_metadata(spin, qubit):
    """Port of 3.1.2 SpinDoctorCalculators.BlochStateMetadata."""
    if spin is None or len(spin) != 3: raise ValueError("Single-qubit Bloch data requires three components.")
    ls = 0.0; exact_zero = True
    for v in spin:
        if not math.isfinite(v): raise ValueError("Single-qubit Bloch data is nonfinite.")
        ls += v * v; exact_zero = exact_zero and v == 0
    if ls > 1 + TOL: raise ValueError("Single-qubit Bloch data lies outside the Bloch ball.")
    pure = abs(ls - 1) <= TOL; resolved = math.sqrt(ls) > TOL
    return D("qubit", qubit, "bloch", list(spin), "blochLengthSquared", ls, "purity", (1 + ls) / 2, "pure", pure, "mixed", not pure,
             "exactlyZeroBloch", exact_zero, "directionDefined", not exact_zero, "directionResolvedAtTolerance", resolved,
             "directionTolerance", TOL,
             "stateCharacter", "pure-single-qubit" if pure else ("maximally-mixed-single-qubit" if exact_zero else ("mixed-single-qubit" if resolved else "near-maximally-mixed-single-qubit")),
             "premeasurement", True, "stateSource", "Selected coherent circuit premeasurement output; reduced single-qubit state.",
             "spinScope", "X/Y/Z are reduced Pauli expectations from the actual retained coherent register, not the separately saved procedural model or a postmeasurement shot. Entanglement can give a mixed local state. An exact zero vector has no preferred direction; a nonzero vector below tolerance retains its components and is labelled near-maximally mixed.")


def require_pure(v):
    if abs(norm_sq(v) - 1) > TOL:
        raise ValueError("State must already be normalized; use q.math normalize explicitly.")


def density(v):
    require_pure(v)
    if len(v) > 16: raise ValueError("Density output supports dimension <=16.")
    return [[v[i] * v[j].conjugate() for j in range(len(v))] for i in range(len(v))]


def trace(a):
    square(a); r = 0j
    for i in range(rows(a)): r += a[i][i]
    return r


def herm_err(a):
    square(a); mx = 0.0
    for i in range(rows(a)):
        for j in range(rows(a)):
            mx = max(mx, abs(a[i][j] - a[j][i].conjugate()))
    return mx


def herm_eig(a):
    square(a); finite_m(a); n = rows(a)
    if n > 16 or herm_err(a) > TOL:
        raise ValueError("Hermitian eigensolver requires a Hermitian matrix <=16x16.")
    d = 2 * n; b = [[0.0] * d for _ in range(d)]; scale = 1.0
    for i in range(n):
        for j in range(n):
            c = (a[i][j] + a[j][i].conjugate()) * .5
            b[i][j] = b[i + n][j + n] = c.real; b[i + n][j] = c.imag; b[i][j + n] = -c.imag
            scale = max(scale, abs(c))
    converged = False
    for _ in range(d * d * 128):
        p = q = 0; off = 0.0
        for i in range(d):
            for j in range(i + 1, d):
                if abs(b[i][j]) > off: off = abs(b[i][j]); p = i; q = j
        if off <= 1e-13 * scale:
            converged = True; break
        tau = (b[q][q] - b[p][p]) / (2 * b[p][q])
        t = (1 if tau >= 0 else -1) / (abs(tau) + math.sqrt(1 + tau * tau))
        c = 1 / math.sqrt(1 + t * t); s = t * c; ap = b[p][p]; aq = b[q][q]; pq = b[p][q]
        b[p][p] = ap - t * pq; b[q][q] = aq + t * pq; b[p][q] = b[q][p] = 0.0
        for k in range(d):
            if k != p and k != q:
                x = b[k][p]; y = b[k][q]
                b[k][p] = b[p][k] = c * x - s * y; b[k][q] = b[q][k] = s * x + c * y
    if not converged: raise RuntimeError("Hermitian eigensolver did not converge.")
    eig = sorted(b[i][i] for i in range(d))
    return [(eig[2 * i] + eig[2 * i + 1]) * .5 for i in range(n)]


def density_validation(a):
    square(a); h = herm_err(a); tr = trace(a)
    eig = herm_eig(a) if h <= TOL else []
    mn = eig[0] if eig else float("nan")
    valid = h <= TOL and abs(tr - 1) <= TOL and (eig and mn >= -TOL)
    return D("valid", bool(valid), "hermitianError", h, "trace", cj(tr), "eigenvalues", eig,
             "minimumEigenvalue", mn if eig else None, "tolerance", TOL)


def require_density(a):
    if not density_validation(a)["valid"]:
        raise ValueError("Density matrix must be Hermitian, positive semidefinite, trace one.")


def purity(rho):
    require_density(rho); return trace(matmul(rho, rho)).real


def entropy(rho, base):
    require_density(rho)
    if base <= 0 or base == 1: raise ValueError("Entropy base must be positive and different from one.")
    s = 0.0
    for raw in herm_eig(rho):
        v = max(0.0, raw)
        if v > 0: s -= v * math.log(v) / math.log(base)
    return s


def overlap(a, b):
    if len(a) != len(b): raise ValueError("State dimensions differ.")
    r = 0j
    for x, y in zip(a, b): r += x.conjugate() * y
    return r


def bloch(v):
    require_pure(v)
    if len(v) != 2: raise ValueError("Bloch vector requires exactly two amplitudes.")
    c = v[0].conjugate() * v[1]
    return [2 * c.real, 2 * c.imag, abs(v[0]) * abs(v[0]) - abs(v[1]) * abs(v[1])]


def unitarity_error(a):
    square(a); p = matmul(dagger(a), a); mx = 0.0
    for i in range(rows(p)):
        for j in range(cols(p)):
            mx = max(mx, abs(p[i][j] - (1 if i == j else 0)))
    return mx


def matrix_difference(a, b, up_to_phase):
    if rows(a) != rows(b) or cols(a) != cols(b): raise ValueError("Matrix dimensions differ.")
    phase = 1 + 0j
    if up_to_phase:
        dot = 0j
        for i in range(rows(a)):
            for j in range(cols(a)): dot += b[i][j].conjugate() * a[i][j]
        if abs(dot) > 1e-15: phase = dot / abs(dot)
    mx = 0.0
    for i in range(rows(a)):
        for j in range(cols(a)): mx = max(mx, abs(a[i][j] - phase * b[i][j]))
    return mx, phase


def gate_matrix(name, angles):
    name = (name or "").lower()
    name = {"id": "i", "identity": "i", "u3": "u", "cnot": "cx", "toffoli": "ccx", "fredkin": "cswap"}.get(name, name)
    spec = GATE_SPECS.get(name)
    if spec is None or angles is None or len(angles) != spec["angleCount"]:
        raise ValueError("Unknown gate or wrong angle count.")
    for d in angles:
        if math.isnan(d) or math.isinf(d) or abs(d) > 1e12:
            raise ValueError("Gate angles must be finite, magnitude <=1e12 radians.")
    targets = spec["targetCount"]
    if targets == 1: return local_gate(name, angles)
    if targets > 4: raise ValueError("Explicit gate matrices are bounded to four operands; mcx7 executes through the native controlled-X backend.")
    dim = 1 << targets; r = zeros(dim, dim)
    if name in ("swap", "ccx", "cswap"):
        for x in range(dim):
            y = x
            if name == "swap": y = ((x & 1) << 1) | ((x & 2) >> 1)
            if name == "ccx" and (x & 3) == 3: y = x ^ 4
            if name == "cswap" and (x & 1) == 1: y = (x & 1) | ((x & 2) << 1) | ((x & 4) >> 1)
            r[y][x] = 1 + 0j
        return r
    if name in ("rxx", "ryy", "rzz", "rzx"):
        p = {"rzx": "Z0 X1", "rxx": "X0 X1", "ryy": "Y0 Y1"}.get(name, "Z0 Z1")
        pm = pauli_matrix(p, 2); c = math.cos(angles[0] / 2); s = math.sin(angles[0] / 2)
        for i in range(dim):
            for j in range(dim):
                r[i][j] = (complex(c, 0) if i == j else 0j) - 1j * s * pm[i][j]
        return r
    local = name[1:]; la = angles[:3] if name == "cu" else angles
    u = local_gate(local, la)
    glob = cmath.exp(1j * angles[3]) if name == "cu" else 1 + 0j
    for x in range(4):
        if (x & 1) == 0: r[x][x] = 1 + 0j
        else:
            for y in range(2): r[1 + (y << 1)][x] = glob * u[y][x >> 1]
    return r


def local_gate(name, a):
    m = zeros(2, 2); I = 1j; h = 1 / math.sqrt(2); theta = a[0] if a else 0.0
    c = math.cos(theta / 2); s = math.sin(theta / 2)
    if name == "i": return identity(2)
    if name == "x": m[0][1] = m[1][0] = 1 + 0j
    elif name == "y": m[0][1] = -I; m[1][0] = I
    elif name == "z": m[0][0] = 1 + 0j; m[1][1] = -1 + 0j
    elif name == "h": m[0][0] = m[0][1] = m[1][0] = complex(h, 0); m[1][1] = complex(-h, 0)
    elif name in ("s", "sdg", "t", "tdg", "p"):
        phi = {"s": math.pi / 2, "sdg": -math.pi / 2, "t": math.pi / 4, "tdg": -math.pi / 4}.get(name, theta)
        m[0][0] = 1 + 0j; m[1][1] = cmath.exp(I * phi)
    elif name in ("sx", "sxdg"):
        ii = I if name == "sx" else -I
        m[0][0] = m[1][1] = (1 + ii) / 2; m[0][1] = m[1][0] = (1 - ii) / 2
    elif name == "rx": m[0][0] = m[1][1] = complex(c, 0); m[0][1] = m[1][0] = -I * s
    elif name == "ry": m[0][0] = m[1][1] = complex(c, 0); m[0][1] = complex(-s, 0); m[1][0] = complex(s, 0)
    elif name == "rz": m[0][0] = cmath.exp(-I * theta / 2); m[1][1] = cmath.exp(I * theta / 2)
    elif name == "u":
        m[0][0] = complex(c, 0); m[0][1] = -cmath.exp(I * a[2]) * s; m[1][0] = cmath.exp(I * a[1]) * s
        m[1][1] = cmath.exp(I * (a[1] + a[2])) * c
    else:
        raise ValueError("Unknown local gate.")
    return m


def parse_pauli(s, n):
    p = {}; s = unquote(s).strip()
    if s in ("I", "i", ""): return p
    for tok in re.split(r"\s+", s):
        m = re.match(r"^([IXYZixyz])([0-9]+)$", tok)
        if not m: raise ValueError("Paulis require explicit operands such as X0 Z1.")
        q = integer(m.group(2), 0, n - 1)
        if q in p: raise ValueError("Pauli repeats a qubit.")
        p[q] = m.group(1).upper()
    return p


def pauli_action(p, x):
    y = x; ph = 1 + 0j
    for q, c in p.items():
        one = (x & (1 << q)) != 0
        if c == "X": y ^= 1 << q
        elif c == "Y":
            y ^= 1 << q; ph *= (-1j if one else 1j)
        elif c == "Z" and one: ph = -ph
    return y, ph


def pauli_matrix(s, n):
    if n < 1 or n > 4: raise ValueError("Explicit Pauli matrices support 1..4 qubits.")
    p = parse_pauli(s, n); d = 1 << n; a = zeros(d, d)
    for x in range(d):
        y, ph = pauli_action(p, x); a[y][x] = ph
    return a


def paulis_commute(a, b):
    anti = 0
    for q, c in a.items():
        o = b.get(q)
        if o is not None and o != "I" and c != "I" and o != c: anti += 1
    return anti % 2 == 0


def bits(i, n):
    return "".join("1" if i & (1 << k) else "0" for k in range(n - 1, -1, -1))


def qubit_list(lst, n, mx):
    s = split_list(lst)
    if len(s) < 1 or len(s) > mx: raise ValueError("Qubit list must contain 1.." + str(mx) + " distinct operands.")
    q = []
    for x in s:
        v = integer(x, 0, n - 1)
        if v in q: raise ValueError("Repeated qubit operand.")
        q.append(v)
    return q


def angles_list(s):
    return [real(x) for x in split_list(s)]


def density_from_spin(s):
    ln = s[0] * s[0] + s[1] * s[1] + s[2] * s[2]
    if ln > 1 + TOL: raise RuntimeError("Selected-state spin lies outside Bloch ball.")
    return [[complex((1 + s[2]) / 2, 0), complex(s[0], -s[1]) / 2], [complex(s[0], s[1]) / 2, complex((1 - s[2]) / 2, 0)]]


def reduced(state, n, keep):
    d = 1 << len(keep); rho = zeros(d, d)
    env = [q for q in range(n) if q not in keep]
    for x in range(1 << len(env)):
        base = 0
        for k, q in enumerate(env):
            if x & (1 << k): base |= 1 << q
        idx = []
        for a in range(d):
            i = base
            for k, q in enumerate(keep):
                if a & (1 << k): i |= 1 << q
            idx.append(i)
        for a in range(d):
            for b in range(d):
                rho[a][b] += state[idx[a]] * state[idx[b]].conjugate()
    return rho


def expectation(v, p):
    e = 0j
    for x in range(len(v)):
        y, ph = pauli_action(p, x); e += v[y].conjugate() * ph * v[x]
    return e


def memory(n, rep):
    if n < 0 or n > 1024: raise ValueError("Memory estimate n must be in 0..1024.")
    if rep == "statevector": return 16 << n
    if rep in ("density-matrix", "unitary"): return 16 << (2 * n)
    raise ValueError("representation must be statevector, density-matrix, or unitary.")


def memory_fields(b):
    from .netfmt import fmt_g10
    return D("bytes", str(b), "MiB", fmt_g10(b / 1048576), "GiB", fmt_g10(b / 1073741824))


def theory(expl, *refs):
    return D("resultKind", "theory", "backend", "documented-theory", "explanation", expl, "references", list(refs),
             "executedQuantumGates", 0, "executedMeasurements", 0)


def require_list(f, key, supported):
    items = split_list(required(f, key)); exp = set(x.lower() for x in supported); got = set()
    for it in items:
        u = unquote(it).lower()
        if u not in exp or u in got: raise ValueError("Unsupported or duplicate " + key + " item.")
        got.add(u)
    if len(got) != len(exp): raise ValueError("This theory entry requires the documented complete " + key + " list.")


def available_memory():
    """(total, available) physical bytes without psutil; (0, 0) if unknown."""
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, v = line.split(":", 1); info[k] = int(v.split()[0]) * 1024
        return info.get("MemTotal", 0), info.get("MemAvailable", info.get("MemFree", 0))
    except Exception:
        pass
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return int(m.ullTotalPhys), int(m.ullAvailPhys)
    except Exception:
        pass
    return 0, 0


class Calculators(object):
    def execute(self, words, n=0, amplitude=None, spin=None, descriptor=None):
        if words is None or len(words) < 2: raise ValueError("Calculator command requires an action.")
        ns = words[0].lower(); action = words[1].lower(); f = parse_fields(words); t0 = time.perf_counter()
        if ns == "q.math": r = self.math(action, f)
        elif ns == "q.query": r = self.query(action, f, n, amplitude, spin, descriptor)
        elif ns == "q.resource": r = self.resource(action, f)
        elif ns == "q.model": r = self.model(action, f)
        elif ns == "q.lesson": r = self.lesson(action, f)
        else: raise ValueError("Unknown calculator namespace.")
        r["namespace"] = ns; r["action"] = action; r["elapsedMs"] = (time.perf_counter() - t0) * 1000.0
        r["physicalQuantumOperations"] = 0; r["proceduralFamilyGateCredit"] = 0; r["measurementSeedChanged"] = False
        r["complexLayout"] = "[real,imaginary]"
        r.setdefault("backend", "bounded-classical-complex-FP64"); r.setdefault("resultKind", "numerical")
        validate_output(r)
        return r

    def math(self, a, f):
        if a in ("normalize", "norm", "probabilities", "bloch", "density", "canonical-phase"):
            check_fields(f, "amplitudes preserve-original" if a == "canonical-phase" else "amplitudes")
            v = parse_vector(required(f, "amplitudes")); n = norm_sq(v)
            if a == "norm": return D("normSquared", n, "norm", math.sqrt(n), "normalized", abs(n - 1) <= TOL, "tolerance", TOL)
            if a == "normalize":
                nv = normalize(v); orig = n if (math.isfinite(n) and n != 0) else None
                return D("amplitudes", vj(nv), "originalNormSquared", orig, "originalNormSquaredRepresentable", orig is not None)
            require_pure(v)
            if a == "density": return D("rho", mj(density(v)))
            if a == "bloch": return D("bloch", bloch(v))
            if a == "probabilities": return D("probabilities", [abs(z) * abs(z) for z in v], "sum", n)
            choice(f, "preserve-original", "true"); ph = 1 + 0j
            for z in v:
                if abs(z) > 1e-15: ph = z / abs(z); break
            return D("displayAmplitudes", vj([z / ph for z in v]), "originalAmplitudes", vj(v), "removedDisplayPhase", cj(ph), "originalStatePreserved", True)
        if a == "from-bloch":
            check_fields(f, "theta phi"); th = real(required(f, "theta")); phi = real(required(f, "phi"))
            if th < 0 or th > math.pi or abs(phi) > 1e12: raise ValueError("theta must be 0..pi and phi magnitude <=1e12.")
            v = [complex(math.cos(th / 2), 0), cmath.exp(1j * phi) * math.sin(th / 2)]
            return D("amplitudes", vj(v), "bloch", bloch(v))
        if a == "validate-bloch":
            check_fields(f, "x y z"); x = real(required(f, "x")); y = real(required(f, "y")); z = real(required(f, "z")); r = x * x + y * y + z * z
            return D("valid", r <= 1 + TOL, "lengthSquared", r, "pure", abs(r - 1) <= TOL, "tolerance", TOL)
        if a in ("validate-density", "purity", "entropy"):
            check_fields(f, "rho base" if a == "entropy" else "rho"); rho = parse_matrix(required(f, "rho"))
            if a == "validate-density": return density_validation(rho)
            if a == "purity": return D("purity", purity(rho))
            b = real(optional(f, "base", "2")); return D("entropy", entropy(rho, b), "base", b, "eigenvalues", herm_eig(rho))
        if a in ("overlap", "fidelity"):
            check_fields(f, "a b convention")
            if a == "fidelity": choice(f, "convention", "squared")
            x = parse_vector(required(f, "a")); y = parse_vector(required(f, "b")); require_pure(x); require_pure(y); c = overlap(x, y)
            return D("overlap", cj(c)) if a == "overlap" else D("fidelity", abs(c) * abs(c), "convention", "squared")
        if a == "trace-distance":
            check_fields(f, "rho sigma"); x = parse_matrix(required(f, "rho")); y = parse_matrix(required(f, "sigma"))
            require_density(x); require_density(y)
            if rows(x) != rows(y): raise ValueError("Density dimensions differ.")
            dm = [[x[i][j] - y[i][j] for j in range(rows(x))] for i in range(rows(x))]
            d = 0.0
            for e in herm_eig(dm): d += abs(e) / 2
            return D("traceDistance", d, "definition", "one half trace norm of rho minus sigma")
        if a == "gate-matrix":
            check_fields(f, "gate angles"); g = required(f, "gate"); an = angles_list(optional(f, "angles", "[]")); m = gate_matrix(g, an)
            return D("gate", g, "matrix", mj(m), "unitarityError", unitarity_error(m), "bitOrder", "q0 least significant; controls first")
        if a == "compare-gates":
            check_fields(f, "p rz up-to-global-phase"); up = boolean(optional(f, "up-to-global-phase", "false"))
            x = gate_matrix("p", [real(required(f, "p"))]); y = gate_matrix("rz", [real(required(f, "rz"))]); err, ph = matrix_difference(x, y, up)
            return D("equivalent", err <= 1e-12, "maximumElementError", err, "phaseMultiplier", cj(ph), "upToGlobalPhase", up,
                     "controlledGateWarning", "A phase on the controlled branch is observable: CP and CRZ are generally different.")
        if a == "unitary":
            check_fields(f, "matrix tolerance"); tol = real(optional(f, "tolerance", "1e-12"))
            if tol <= 0 or tol > 1e-3: raise ValueError("tolerance must be in (0,1e-3].")
            err = unitarity_error(parse_matrix(required(f, "matrix")))
            return D("unitary", err <= tol, "maximumElementError", err, "tolerance", tol)
        if a in ("tensor", "commutator"):
            check_fields(f, "left right" if a == "tensor" else "a b")
            x = parse_matrix(required(f, "left" if a == "tensor" else "a")); y = parse_matrix(required(f, "right" if a == "tensor" else "b"))
            if a == "tensor": return D("matrix", mj(tensor(x, y)), "factorOrder", "left tensor right; right factor occupies lower-order indices")
            ab = matmul(x, y); ba = matmul(y, x)
            if rows(ab) != rows(ba) or cols(ab) != cols(ba): raise ValueError("Commutator dimensions differ.")
            return D("matrix", mj([[ab[i][j] - ba[i][j] for j in range(cols(ab))] for i in range(rows(ab))]), "definition", "AB-BA")
        if a == "eigen":
            check_fields(f, "operator"); op = parse_matrix(required(f, "operator")); eig = herm_eig(op)
            r = D("eigenvalues", eig, "method", "converged real-symmetric embedding Jacobi eigensolver")
            if rows(op) == 2:
                vec = []
                for k in range(2):
                    if abs(eig[1] - eig[0]) <= 1e-12: v = [1 + 0j, 0j] if k == 0 else [0j, 1 + 0j]
                    elif abs(op[0][1]) > 1e-14: v = normalize([op[0][1], eig[k] - op[0][0]])
                    else: v = [1 + 0j, 0j] if abs(op[0][0].real - eig[k]) <= 1e-12 else [0j, 1 + 0j]
                    vec.append(vj(v))
                r["eigenvectors"] = vec
            return r
        if a == "expectation":
            check_fields(f, "state operator"); v = parse_vector(required(f, "state")); require_pure(v); m = parse_matrix(required(f, "operator"))
            if herm_err(m) > TOL: raise ValueError("Observable must be Hermitian.")
            c = overlap(v, matvec(m, v)); return D("expectation", c.real, "imaginaryResidual", c.imag)
        raise ValueError("Unsupported q.math action. Use the calculator catalogue.")

    def query(self, a, f, n, get, spin, h):
        if n < 1 or n > 298 or get is None or spin is None:
            raise RuntimeError("q.query requires the current completed circuit's coherent premeasurement output. Run q.circuit first.")
        cnt = [0]

        def amp(i):
            x = get(i); cnt[0] += 1; return complex(x[0], x[1])

        def spq(q):
            s = spin(q); cnt[0] += 1; return s
        full = [None]

        def load():
            if n > MAX_FULL_QUERY_QUBITS:
                raise RuntimeError("This exact joint analysis is bounded to 16 qubits/65536 calculated amplitudes. Single-qubit reductions and bounded prefix dumps support 298 logical qubits with factors <=59.")
            if full[0] is None:
                full[0] = [amp(i) for i in range(1 << n)]; require_pure(full[0])
            return full[0]
        if a in ("amplitudes", "probabilities"):
            check_fields(f, "max start"); mx = integer(optional(f, "max", "16"), 1, MAX_ROWS); length = 1 << n
            start = big(optional(f, "start", "0"), False)
            if start >= length: raise ValueError("start is outside selected register.")
            take = min(mx, length - start); rws = []; mass = 0.0
            for i in range(take):
                idx = start + i; z = amp(idx); p = abs(z) * abs(z); mass += p
                row = D("basisIndex", str(idx), "bitstring", bits(idx, n), "probability", p)
                if a == "amplitudes":
                    row["amplitude"] = cj(z); row["phaseRadians"] = None if p == 0 else math.atan2(z.imag, z.real)
                rws.append(row)
            r = D("rows", rws, "totalStates", str(length), "returnedStates", take, "start", str(start),
                  "complete", start == 0 and take == length, "omittedStates", str(length - take), "returnedProbabilityMass", mass, "renormalized", False)
        elif a == "expectation":
            check_fields(f, "pauli"); p = parse_pauli(required(f, "pauli"), n); e = expectation(load(), p)
            r = D("pauli", required(f, "pauli"), "expectation", e.real, "imaginaryResidual", e.imag)
        elif a == "stabilizers":
            check_fields(f, "generators"); gens = split_list(required(f, "generators"))
            if len(gens) < 1 or len(gens) > 64: raise ValueError("Use 1..64 stabilizer candidates.")
            ps = []; rws = []; comm = True; stab = True; v = load()
            for i, g in enumerate(gens):
                p = parse_pauli(unquote(g), n); ps.append(p); e = expectation(v, p)
                s = abs(e.real - 1) <= TOL and abs(e.imag) <= TOL; stab = stab and s
                rws.append(D("generator", unquote(g), "expectation", e.real, "stabilizes", s))
                for j in range(i): comm = comm and paulis_commute(p, ps[j])
            r = D("rows", rws, "mutuallyCommuting", comm, "allStabilize", stab, "validStabilizers", comm and stab,
                  "scope", "Candidate checks on selected pure output; this is not a phase-aware tableau backend.")
        elif a == "fidelity":
            check_fields(f, "state convention"); choice(f, "convention", "squared"); t = parse_vector(required(f, "state")); require_pure(t)
            c = overlap(load(), t); r = D("fidelity", abs(c) * abs(c), "convention", "squared")
        elif a == "concurrence":
            check_fields(f, "qubits"); q = qubit_list(required(f, "qubits"), n, 2)
            if n != 2 or len(q) != 2:
                raise RuntimeError("This concurrence calculator requires the entire selected pure two-qubit register. Mixed reduced concurrence needs an additional backend.")
            v = load(); r = D("concurrence", 2 * abs(v[0] * v[3] - v[1] * v[2]), "scope", "pure two-qubit state")
        elif a == "negativity":
            check_fields(f, "partition convention"); choice(f, "convention", "trace-norm-minus-one-divided-by-two")
            q = qubit_list(required(f, "partition"), n, 4)
            if len(q) == n: raise ValueError("Partition must leave a nonempty complement.")
            rho = density_from_spin(spq(q[0])) if len(q) == 1 else reduced(load(), n, q)
            s = 0.0
            for e in herm_eig(rho): s += math.sqrt(max(0.0, e))
            r = D("negativity", max(0.0, (s * s - 1) / 2), "partition", q, "convention", "(trace norm of partial transpose minus one)/2",
                  "method", "Schmidt spectrum identity for the globally pure selected output")
        elif a in ("marginal", "reduced-density", "purity", "entropy"):
            check_fields(f, "qubits basis" if a == "marginal" else ("qubits base" if a == "entropy" else "qubits"))
            q = qubit_list(required(f, "qubits"), n, 4)
            local_spin = spq(q[0]) if len(q) == 1 else None
            rho = density_from_spin(local_spin) if local_spin is not None else reduced(load(), n, q)
            if a == "reduced-density":
                r = D("rho", mj(rho), "qubits", q, "dimension", rows(rho))
                if local_spin is not None:
                    for k2, v2 in bloch_state_metadata(local_spin, q[0]).items(): r[k2] = v2
            elif a == "purity": r = D("purity", purity(rho), "qubits", q)
            elif a == "entropy":
                b = real(optional(f, "base", "2")); r = D("entropy", entropy(rho, b), "base", b, "qubits", q)
            else:
                basis = optional(f, "basis", "z").lower()
                if basis not in ("x", "y", "z"): raise ValueError("basis must be x, y, or z.")
                local = gate_matrix("h", []) if basis == "x" else (matmul(gate_matrix("h", []), gate_matrix("sdg", [])) if basis == "y" else identity(2))
                rot = identity(1)
                for _ in q: rot = tensor(local, rot)
                rho = matmul(matmul(rot, rho), dagger(rot))
                r = D("probabilities", [max(0.0, rho[i][i].real) for i in range(1 << len(q))], "qubits", q, "basis", basis,
                      "localBitOrder", "First listed qubit is least significant in each local outcome.")
        else:
            raise ValueError("Unsupported q.query action.")
        r["descriptorHash"] = h; r["selectedQubits"] = n; r["actualStateQueries"] = cnt[0]
        r["backend"] = "selected-coherent-register / classical-FP64 analysis"; r["resultKind"] = "analysis"; r["tolerance"] = TOL
        return r

    def resource(self, a, f):
        if a == "memory":
            check_fields(f, "n representation dtype units"); choice(f, "dtype", "complex128"); choice(f, "units", "binary")
            n = integer(required(f, "n"), 0, 1024); rep = required(f, "representation").lower(); b = memory(n, rep)
            r = memory_fields(b); r["n"] = n; r["representation"] = rep; r["complexBytes"] = 16
            r["transactionalStatevectorPeakBytes"] = str(2 * b) if rep == "statevector" else None
            r["cachedCircuitPlusTransactionalShotBytes"] = str(3 * b) if rep == "statevector" else None
            r["scope"] = "Raw dense payload; container/allocator/OS overhead excluded. No allocation performed."
        elif a == "max-n":
            check_fields(f, "memory-mib representation dtype overhead-mib"); choice(f, "dtype", "complex128")
            mib = real(required(f, "memory-mib")); ov = real(optional(f, "overhead-mib", "0"))
            if mib <= 0 or ov < 0 or mib > 1e18 or ov > mib: raise ValueError("Invalid memory/overhead budget.")
            b = int((mib - ov) * 1048576); rep = required(f, "representation").lower(); n = -1
            while n < 1024 and memory(n + 1, rep) <= b: n += 1
            r = D("maximumRawQubits", n, "availablePayloadBytes", str(b), "representation", rep,
                  "assumption", "Raw payload only, using explicitly supplied overhead; this is not safe automatic allocation.")
        elif a == "factor-memory":
            check_fields(f, "block-sizes dtype"); choice(f, "dtype", "complex128"); blocks = split_list(required(f, "block-sizes"))
            if len(blocks) < 1 or len(blocks) > 1024: raise ValueError("Use 1..1024 factor blocks.")
            total = 0; n = 0; sizes = []
            for bl in blocks:
                s = integer(bl, 1, 1024); sizes.append(s); n += s; total += memory(s, "statevector")
            r = memory_fields(total); r["blockSizes"] = sizes; r["totalQubits"] = n
            r["assumption"] = "Exact independent tensor factors. Connecting entangling gates may merge factors and increase memory exponentially; sparse/container overhead excluded."
        elif a == "tranche-plan":
            check_fields(f, "addresses width semantics"); choice(f, "semantics", "independent-groups")
            ad = big(required(f, "addresses"), True); w = integer(required(f, "width"), 1, 29); g = (ad + w - 1) // w; last = ad % w or w
            r = D("addresses", str(ad), "width", w, "tranches", str(g), "lastTrancheQubits", last, "scope", "Address-group plan only; no tranches allocated or gates executed.")
        elif a == "sampling":
            check_fields(f, "probability shots metric"); choice(f, "metric", "standard-error")
            p = real(required(f, "probability")); s = real(required(f, "shots"))
            if p < 0 or p > 1 or s < 1 or s != math.floor(s) or s > 1e15: raise ValueError("Invalid Bernoulli probability or shot count.")
            r = D("standardError", math.sqrt(p * (1 - p) / s), "shots", s, "probability", p, "assumption", "Independent Bernoulli samples; standard error is not a deterministic error guarantee.")
        elif a == "shots":
            check_fields(f, "epsilon delta bound"); choice(f, "bound", "hoeffding-two-sided")
            ep = real(required(f, "epsilon")); de = real(required(f, "delta"))
            if ep <= 0 or ep >= 1 or de <= 0 or de >= 1: raise ValueError("epsilon and delta must be in (0,1).")
            s = math.ceil(math.log(2 / de) / (2 * ep * ep))
            r = D("minimumShots", str(int(s)), "epsilon", ep, "delta", de, "bound", "Pr(|sample mean - p| >= epsilon) <= 2 exp(-2 n epsilon^2)", "assumption", "Independent bounded Bernoulli samples.")
        elif a == "grover":
            check_fields(f, "database-size marked formula"); choice(f, "formula", "asymptotic")
            N = big(required(f, "database-size"), True); M = big(required(f, "marked"), True)
            if M > N: raise ValueError("marked cannot exceed database-size.")
            r = D("asymptoticQueries", math.pi / 4 * math.sqrt(float(N) / float(M)), "formula", "pi/4 sqrt(N/M)", "databaseSize", str(N), "marked", str(M),
                  "scope", "Oracle-query estimate; oracle implementation and state preparation excluded.")
        elif a == "qec":
            check_fields(f, "logical-qubits physical-per-logical model"); choice(f, "model", "user-supplied-overhead")
            lg = big(required(f, "logical-qubits"), True); ra = big(required(f, "physical-per-logical"), True)
            r = D("logicalQubits", str(lg), "physicalPerLogical", str(ra), "estimatedPhysicalQubits", str(lg * ra),
                  "scope", "User supplied ratio; no code, decoder, distance, or logical error guarantee inferred.")
        elif a in ("headroom", "auto"):
            check_fields(f, "reserve-mib overhead-mib peak-factor representation n")
            total, avail = available_memory()
            if total == 0: raise RuntimeError("Available-memory query is not supported on this platform.")
            res = real(optional(f, "reserve-mib", "2048")); ov = real(optional(f, "overhead-mib", "256")); peak = integer(optional(f, "peak-factor", "3"), 1, 8)
            if res < 512 or ov < 0 or res > 1e9 or ov > 1e9: raise ValueError("Reserve must be >=512 MiB and overhead nonnegative.")
            rb = int(res * 1048576); ob = int(ov * 1048576); usable = max(0, avail - rb - ob)
            rep = optional(f, "representation", "statevector").lower(); mx = -1
            while mx < 1024 and peak * memory(mx + 1, rep) <= usable: mx += 1
            from .register import process_private_bytes
            r = D("totalPhysicalBytes", str(total), "availablePhysicalBytes", str(avail), "osReserveBytes", str(rb), "extraOverheadBytes", str(ob),
                  "plannedPeakFactor", peak, "usablePeakBytes", str(usable), "maximumPlannedDenseQubits", mx, "representation", rep,
                  "processPrivateBytes", str(process_private_bytes()), "allocationPerformed", False,
                  "scope", "Momentary available-RAM plan; headroom can change before allocation. Default factor 3 covers a retained coherent vector plus shot state and its transactional work, excluding already-resident memory from available RAM.")
            if f.has("n"):
                n = integer(f.get_ci("n"), 0, 1024); need = peak * memory(n, rep)
                r["requestedQubits"] = n; r["requiredPeakBytes"] = str(need); r["fitsCurrentPlan"] = need <= usable
        else:
            raise ValueError("Unsupported q.resource action.")
        r["resultKind"] = "resource-estimate"; r["backend"] = "classical-resource-formulas / OS available-memory snapshot"; r["stateAllocations"] = 0
        return r

    def model(self, a, f):
        if a == "spectrum":
            check_fields(f, "hamiltonian n"); n = integer(required(f, "n"), 1, 4); h = hamiltonian(required(f, "hamiltonian"), n)
            return D("hamiltonian", mj(h), "eigenvalues", herm_eig(h), "n", n, "scope", "Explicit small Pauli Hamiltonian spectrum; no hardware energy units inferred.")
        if a == "evolve":
            check_fields(f, "n initial hamiltonian time hbar"); n = integer(required(f, "n"), 1, 1); v = parse_vector(required(f, "initial")); require_pure(v)
            if len(v) != 2: raise ValueError("Evolution supports one qubit.")
            h = hamiltonian(required(f, "hamiltonian"), n); t = real(required(f, "time")); hb = real(optional(f, "hbar", "1"))
            if hb <= 0: raise ValueError("hbar must be positive.")
            h0 = (h[0][0].real + h[1][1].real) / 2; z = (h[0][0].real - h[1][1].real) / 2; x = h[0][1].real; y = -h[0][1].imag
            rr = math.sqrt(x * x + y * y + z * z); ang = rr * t / hb
            if math.isnan(ang) or math.isinf(ang) or abs(ang) > 1e12: raise ValueError("Evolution phase is nonfinite or exceeds 1e12 radians.")
            ph = cmath.exp(-1j * h0 * t / hb); u = identity(2); c = math.cos(ang); sc = 0 if rr == 0 else math.sin(ang) / rr
            for i in range(2):
                for j in range(2):
                    u[i][j] = ph * ((complex(c, 0) if i == j else 0j) - 1j * sc * (h[i][j] - (complex(h0, 0) if i == j else 0j)))
            out = matvec(u, v)
            return D("amplitudes", vj(out), "unitary", mj(u), "bloch", bloch(out), "time", t, "hbar", hb, "equation", "exp(-i H t / hbar) applied to a one-qubit state")
        if a == "ising":
            check_fields(f, "h J energy spins"); choice(f, "energy", "sum_i h_i s_i + sum_i<j J_ij s_i s_j"); choice(f, "spins", "plus-minus-one")
            hc = parse_vector(required(f, "h"))
            if len(hc) > 12: raise ValueError("Ising enumeration supports <=12 spins.")
            jc = parse_matrix(required(f, "J")); n = len(hc)
            if rows(jc) != n or cols(jc) != n: raise ValueError("J must match h dimensions.")
            h = []
            for z in hc:
                if abs(z.imag) > 1e-12: raise ValueError("h must be real.")
                h.append(z.real)
            for i in range(n):
                for j in range(n):
                    if abs(jc[i][j].imag) > 1e-12 or abs(jc[i][j].real - jc[j][i].real) > 1e-12 or (i == j and abs(jc[i][j]) > 1e-12):
                        raise ValueError("J must be real symmetric with zero diagonal.")
            rws = []; mn = math.inf; ground = []
            for idx in range(1 << n):
                sp = [1 if not idx & (1 << q) else -1 for q in range(n)]; e = 0.0
                for i in range(n):
                    e += h[i] * sp[i]
                    for j in range(i + 1, n): e += jc[i][j].real * sp[i] * sp[j]
                if e < mn - 1e-12: mn = e; ground = []
                if abs(e - mn) <= 1e-12: ground.append(bits(idx, n))
                rws.append(D("bitstring", bits(idx, n), "spins", sp, "energy", e))
            return D("rows", rws, "minimumEnergy", mn, "groundBitstrings", ground, "convention", "bit 0 means spin +1, bit 1 means spin -1; each i<j interaction counted once")
        if a == "qubo-to-ising":
            check_fields(f, "Q objective mapping"); choice(f, "objective", "x_transpose_Q_x"); choice(f, "mapping", "x=(1-s)/2")
            q = parse_matrix(required(f, "Q")); square(q); n = rows(q); const = 0.0; h = [0.0] * n; j = zeros(n, n)
            for row in q:
                for c in row:
                    if abs(c.imag) > 1e-12: raise ValueError("Q must be real.")
            for i in range(n):
                const += q[i][i].real / 2; h[i] -= q[i][i].real / 2
                for k in range(i + 1, n):
                    term = (q[i][k].real + q[k][i].real) / 4; const += term; h[i] -= term; h[k] -= term; j[i][k] = j[k][i] = complex(term, 0)
            return D("constant", const, "h", h, "J", mj(j), "mapping", "x=(1-s)/2", "objective", "x transpose Q x; asymmetric off-diagonal entries combined")
        if a == "mbqc":
            check_fields(f, "initial resource entangler measurement branch"); choice(f, "resource", "one plus ancilla"); choice(f, "entangler", "CZ")
            choice(f, "measurement", "X on input"); choice(f, "branch", "all")
            inp = parse_vector(required(f, "initial")); require_pure(inp)
            if len(inp) != 2: raise ValueError("One-bit teleportation requires one input qubit.")
            hv = matvec(gate_matrix("h", []), inp); xh = matvec(gate_matrix("x", []), hv)
            return D("branches", [D("outcome", 0, "probability", .5, "uncorrectedOutput", vj(hv), "correction", "I", "correctedOutput", vj(hv)),
                                  D("outcome", 1, "probability", .5, "uncorrectedOutput", vj(xh), "correction", "X", "correctedOutput", vj(hv))],
                     "equation", "CZ on input tensor plus, X-basis input measurement: output X^m H|psi>",
                     "scope", "Exact analytic branch calculation; probabilities are not sampled measurement counts.")
        if a == "compare":
            check_fields(f, "models"); require_list(f, "models", ["gate-based", "closed-system-adiabatic", "open-system-annealing"])
            return theory("Closed-system adiabatic computation and the circuit model are polynomially equivalent under the theorem's assumptions. A finite-temperature open-system annealer has a different dynamical model; that equivalence does not establish annealer universality.", "https://arxiv.org/abs/quant-ph/0405098")
        if a == "compare-codes":
            check_fields(f, "families assumptions"); require_list(f, "families", ["surface-code", "qldpc"])
            require_list(f, "assumptions", ["connectivity", "decoder", "noise-model", "rate", "distance"])
            return theory("Compare explicit code families using connectivity, decoding, noise assumptions, rate k/n, and distance. The generic names surface-code and qLDPC do not fix a physical-qubit overhead or logical error rate. Specific code and decoder parameters are required for a numerical resource result.", "https://arxiv.org/abs/2111.03654")
        if a == "topology":
            check_fields(f, "braid anyon-model action"); choice(f, "anyon-model", "unspecified"); choice(f, "action", "explain"); choice(f, "braid", "example")
            r = theory("A numerical braid calculation requires an anyon model, fusion channels, basis, and its F/R matrices. Unspecified anyons cannot determine a gate or amplitude. This entry explains the required data without executing a braid.", "https://arxiv.org/abs/quant-ph/9707021")
            r["numericalBackendAvailable"] = False; r["needsBackend"] = "Specify an anyon model and a validated fusion/braid backend."; return r
        raise ValueError("Unsupported q.model action.")

    def lesson(self, a, f):
        if a == "amplitude-vs-probability":
            check_fields(f, "example"); v = parse_vector(required(f, "example")); require_pure(v)
            r = theory("Complex amplitudes include phase; measurement probabilities are their squared magnitudes. Equal probabilities can hide different interference outcomes.", "https://quantum.cloud.ibm.com/learning/en/courses/basics-of-quantum-information/single-systems/quantum-information")
            r["amplitudes"] = vj(v); r["probabilities"] = [abs(z) * abs(z) for z in v]; return r
        if a == "entanglement":
            check_fields(f, "compare"); require_list(f, "compare", ["plus tensor plus", "Bell phi plus"])
            r = theory("Plus tensor plus is separable although it has four nonzero computational amplitudes. Bell phi plus is entangled; its one-qubit reduced state is I/2. Superposition alone does not imply entanglement.", "https://quantum.cloud.ibm.com/learning/en/courses/basics-of-quantum-information/multiple-systems/quantum-information")
            r["productReducedPurity"] = 1; r["bellReducedPurity"] = .5; r["bellReducedEntropyBits"] = 1; return r
        if a == "complexity":
            check_fields(f, "classes distinguish"); require_list(f, "classes", ["P", "BPP", "BQP", "PSPACE", "NP"]); require_list(f, "distinguish", ["proven", "conjectured"])
            r = theory("Known containments include P subset BPP subset BQP subset PP subset PSPACE, and NP subset PSPACE. Strictness of these containments is not established. NP subset BQP is not known; quantum computing is not a general proof that NP-complete problems are easy.", "https://arxiv.org/abs/quant-ph/9701001")
            r["openQuestions"] = ["NP subset BQP?", "BPP equals BQP?", "P equals NP?"]; return r
        if a == "parallelism":
            check_fields(f, "example"); choice(f, "example", "grover")
            return theory("A superposition does not expose all amplitudes in one measurement. Grover gives a quadratic unstructured-search query advantage, with an explicit oracle and repeated coherent iterations; state preparation, oracle cost, and classical readout remain separate costs.", "https://arxiv.org/abs/quant-ph/9701001")
        if a == "stabilizer":
            check_fields(f, "assumptions"); require_list(f, "assumptions", ["stabilizer-input", "clifford-gates", "pauli-measurements"])
            return theory("Stabilizer inputs, Clifford gates and Pauli measurements admit efficient phase-aware stabilizer simulation. This theorem does not apply to arbitrary nonstabilizer inputs or arbitrary non-Clifford gates; this terminal's factorized statevector backend is distinct from a tableau backend.", "https://arxiv.org/abs/quant-ph/0406196")
        if a == "magic":
            check_fields(f, "caveats"); require_list(f, "caveats", ["input-dependent-T", "qubit-Wigner-convention", "nonclifford-not-sufficient-for-advantage"])
            r = theory("T leaves |0> unchanged. Applied to |+>, it produces a nonstabilizer pure qubit with Bloch vector (1/sqrt(2),1/sqrt(2),0). Non-Clifford structure alone does not prove computational advantage. Gross's nonnegative-Wigner theorem uses odd-dimensional systems; transferring it directly to an unspecified qubit convention is invalid.", "https://arxiv.org/abs/quant-ph/0403025", "https://arxiv.org/abs/quant-ph/0602001")
            r["TOnPlusBloch"] = [1 / math.sqrt(2), 1 / math.sqrt(2), 0.0]; return r
        if a == "algorithms":
            check_fields(f, "compare scope"); require_list(f, "compare", ["shor", "grover"]); choice(f, "scope", "toy-calculator")
            return theory("Shor's order-finding algorithm uses coherent modular arithmetic and phase estimation; a classical factor command alone is not its quantum circuit. Grover's unstructured search uses O(sqrt(N/M)) oracle queries. Toy simulations must disclose register, oracle, and classical postprocessing costs.", "https://arxiv.org/abs/quant-ph/9508027", "https://arxiv.org/abs/quant-ph/9605043")
        if a == "pqc":
            check_fields(f, "standards mode"); require_list(f, "standards", ["FIPS203", "FIPS204", "FIPS205"]); choice(f, "mode", "verify-current-primary-sources")
            r = theory("Primary NIST pages were checked on 2026-10-09: FIPS 203 standardizes ML-KEM key establishment, FIPS 204 ML-DSA signatures, and FIPS 205 SLH-DSA signatures. These are classical post-quantum cryptography standards, not quantum gate algorithms. This installed snapshot does not fetch later updates during calculation; use the linked primary pages for their current notices and errata.", "https://csrc.nist.gov/pubs/fips/203/final", "https://csrc.nist.gov/pubs/fips/204/final", "https://csrc.nist.gov/pubs/fips/205/final")
            r["primarySourcesCheckedDate"] = "2026-10-09"; r["liveNetworkLookupPerformed"] = False; return r
        raise ValueError("Unsupported q.lesson action.")


def hamiltonian(text, n):
    if len(text) > 2048: raise ValueError("Hamiltonian text exceeds bound.")
    h = zeros(1 << n, 1 << n)
    if ";" in text: terms = text.split(";")
    else: terms = re.split(r"\s+(?=[+-])|(?<=[0-9A-Za-z)])(?=[+-](?![0-9]+\s*\*))", text.strip())
    if len(terms) > 64: raise ValueError("Use <=64 explicit Pauli terms.")
    for raw in terms:
        t = raw.strip(); star = t.find("*")
        if star < 1: raise ValueError("Hamiltonian terms use real-coefficient*Pauli operands, separated by semicolons (e.g. 0.5*Z0;0.2*X0).")
        c = real(t[:star]); p = pauli_matrix(t[star + 1:].strip(), n)
        for i in range(rows(h)):
            for j in range(cols(h)): h[i][j] += c * p[i][j]
    finite_m(h); return h
