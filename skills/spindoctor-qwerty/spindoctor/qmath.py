# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Ports of QuantumMath (QuantumCore.cs) helpers used by the circuit and grid backends."""
import math

IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
MAX_EXACT_STATES = 9007199254740991
MAX_AXIS = 1000000000


def is_finite(x):
    return not (math.isnan(x) or math.isinf(x))


def matrix_for_gate(gate, p):
    p = list(p or [])
    for a in p:
        if not is_finite(a) or abs(a) > 1e12:
            raise ValueError("Gate angles must be finite and have absolute value at most 1e12 radians.")
    name = gate.lower()
    if name in ("u", "u3"):
        _req(p, 3, name)
        theta, phi, lam = p
        c = math.cos(theta / 2.0); s = math.sin(theta / 2.0)
        return [c, 0.0, -s * math.cos(lam), -s * math.sin(lam), s * math.cos(phi), s * math.sin(phi),
                c * math.cos(phi + lam), c * math.sin(phi + lam)]
    if name == "ry":
        _req(p, 1, name); c = math.cos(p[0] / 2.0); s = math.sin(p[0] / 2.0)
        return [c, 0.0, -s, 0.0, s, 0.0, c, 0.0]
    if name == "rz":
        _req(p, 1, name); c = math.cos(p[0] / 2.0); s = math.sin(p[0] / 2.0)
        return [c, -s, 0.0, 0.0, 0.0, 0.0, c, s]
    _req(p, 0, name)
    if name == "h":
        c = 1.0 / math.sqrt(2.0); return [c, 0.0, c, 0.0, c, 0.0, -c, 0.0]
    if name == "x": return [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    if name == "y": return [0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0, 0.0]
    if name == "z": return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0]
    if name == "s": return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    if name == "t":
        c = 1.0 / math.sqrt(2.0); return [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, c, c]
    if name in ("i", "identity"): return list(IDENTITY)
    raise ValueError("Supported gates are U, RY, RZ, H, X, Y, Z, S, T and I.")


def _req(p, n, g):
    if len(p) != n:
        raise ValueError(g.upper() + " requires " + str(n) + " angle parameter(s).")


def multiply(left, right):
    r = [0.0] * 8
    for row in range(2):
        for col in range(2):
            o = 2 * (2 * row + col)
            for k in range(2):
                a = 2 * (2 * row + k); b = 2 * (2 * k + col)
                r[o] += left[a] * right[b] - left[a + 1] * right[b + 1]
                r[o + 1] += left[a] * right[b + 1] + left[a + 1] * right[b]
    return r


def unitarity_error(m):
    a = complex(m[0], m[1]); b = complex(m[2], m[3]); c = complex(m[4], m[5]); d = complex(m[6], m[7])
    # (M^dagger M) - I
    p00 = a.conjugate() * a + c.conjugate() * c
    p01 = a.conjugate() * b + c.conjugate() * d
    p11 = b.conjugate() * b + d.conjugate() * d
    return max(abs(p00 - 1), abs(p01), abs(p11 - 1))


def validate_grid(m, l):
    if m == 0 or l == 0 or m > MAX_AXIS or l > MAX_AXIS:
        raise ValueError("Each grid axis must be from 1 to 1,000,000,000.")
    if m > MAX_EXACT_STATES // l:
        raise ValueError("The grid must contain at most 2^53-1 states for exact address conversion.")
    return m * l


def grid_state(i, m, l, t, mat):
    """[ar, ai, br, bi, X, Y, Z, norm, P1] for address i (StateUnchecked)."""
    k = i % m; ell = i // m
    q = (float(k) + 0.5) / float(m)
    theta = 2.0 * math.asin(math.sqrt(q))
    phi = 2.0 * math.pi * float(ell) / float(l)
    ar = math.cos(t * theta * 0.5)
    amp = math.sin(t * theta * 0.5)
    br = amp * math.cos(t * phi); bi = amp * math.sin(t * phi)
    oar = mat[0] * ar + mat[2] * br - mat[3] * bi
    oai = mat[1] * ar + mat[2] * bi + mat[3] * br
    obr = mat[4] * ar + mat[6] * br - mat[7] * bi
    obi = mat[5] * ar + mat[6] * bi + mat[7] * br
    pa = oar * oar + oai * oai; pb = obr * obr + obi * obi
    return [oar, oai, obr, obi, 2.0 * (oar * obr + oai * obi), 2.0 * (oar * obi - oai * obr), pa - pb, pa + pb, pb]


def grid_state_reference(i, m, l, t, mat):
    """Independent complex-arithmetic evaluation of the same rule (used as the cartridge's
    second implementation for q.verify samples in place of the OpenCL GPU path)."""
    import cmath
    k = i % m; ell = i // m
    theta = 2.0 * math.asin(math.sqrt((k + 0.5) / m))
    phi = 2.0 * math.pi * ell / l
    alpha = complex(math.cos(t * theta / 2.0), 0.0)
    beta = cmath.exp(1j * t * phi) * math.sin(t * theta / 2.0)
    a = complex(mat[0], mat[1]) * alpha + complex(mat[2], mat[3]) * beta
    b = complex(mat[4], mat[5]) * alpha + complex(mat[6], mat[7]) * beta
    cross = a.conjugate() * b
    pa = abs(a) ** 2; pb = abs(b) ** 2
    return [a.real, a.imag, b.real, b.imag, 2 * cross.real, 2 * cross.imag, pa - pb, pa + pb, pb]
