# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Formatting helpers that reproduce the SpinDoctor 3.1.2 (.NET Framework) wire format.

* fmt_r(x)  -> Double.ToString("R", InvariantCulture) as produced by .NET Framework 4.x
               (15 significant digits when that round-trips, otherwise 17; '-0' prints '0').
* dumps(o)  -> System.Web.Script.Serialization.JavaScriptSerializer compact JSON
               (insertion-ordered objects, R-formatted doubles, <>&' escaped as \\u00xx).
"""
import math

__all__ = ["fmt_r", "dumps", "hex_sha256", "fmt_g10"]


def fmt_r(x):
    x = float(x)
    if x != x:
        return "NaN"
    if x == math.inf:
        return "Infinity"
    if x == -math.inf:
        return "-Infinity"
    if x == 0.0:
        return "0"
    s = "%.15G" % x
    if float(s) != x:
        s = "%.17G" % x
    return s


def fmt_g10(x):
    """Double.ToString("G10", InvariantCulture)."""
    x = float(x)
    if x == 0.0:
        return "0"
    return "%.10G" % x


_ESC = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f', '\n': '\\n', '\r': '\\r', '\t': '\\t',
        '<': '\\u003c', '>': '\\u003e', '&': '\\u0026', "'": '\\u0027'}


def _quote(s):
    out = ['"']
    for ch in s:
        e = _ESC.get(ch)
        if e is not None:
            out.append(e)
        elif ch < ' ':
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def dumps(o):
    parts = []
    _emit(o, parts)
    return ''.join(parts)


def _emit(o, out):
    if o is None:
        out.append('null')
    elif o is True:
        out.append('true')
    elif o is False:
        out.append('false')
    elif isinstance(o, int):
        out.append(str(o))
    elif isinstance(o, float):
        out.append(fmt_r(o))
    elif isinstance(o, str):
        out.append(_quote(o))
    elif isinstance(o, dict):
        out.append('{')
        first = True
        for k, v in o.items():
            if not first:
                out.append(',')
            first = False
            out.append(_quote(str(k)))
            out.append(':')
            _emit(v, out)
        out.append('}')
    elif isinstance(o, (list, tuple)):
        out.append('[')
        for i, v in enumerate(o):
            if i:
                out.append(',')
            _emit(v, out)
        out.append(']')
    elif isinstance(o, complex):
        _emit([o.real, o.imag], out)
    else:
        # numpy scalars and other numerics
        try:
            if float(o) == int(o) and not hasattr(o, 'dtype') or str(getattr(o, 'dtype', '')).startswith(('int', 'uint')):
                out.append(str(int(o)))
                return
        except Exception:
            pass
        try:
            out.append(fmt_r(float(o)))
        except Exception:
            out.append(_quote(str(o)))


def hex_sha256(text):
    import hashlib
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
