# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""TXT / JSON / PDF report writers.  The PDF writer is a minimal built-in PDF 1.4 generator
(Courier, Flate-compressed content streams, automatic wrapping and pagination); no ReportLab."""
import json
import os
import zlib

from .netfmt import dumps, fmt_r

PAGE_W, PAGE_H = 612, 792
FONT_SIZE = 6.5
LEADING = 7.6
MARGIN = 36
WRAP = 132           # characters per line at 6.5pt Courier inside the margins

_TRANSLIT = {"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2026": "...",
             "\u2264": "<=", "\u2265": ">=", "\u00d7": "x", "\u2192": "->", "\u03c0": "pi", "\u221a": "sqrt", "\u27e9": ">", "\u27e8": "<"}


def atomic_write(path, data, binary=False):
    d = os.path.dirname(path)
    if d: os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8", "newline": "\n"})) as fh:
        fh.write(data)
        fh.flush()
        try: os.fsync(fh.fileno())
        except OSError: pass
    os.replace(tmp, path)


def scalar(v):
    if v is None: return ""
    if v is True: return "True"
    if v is False: return "False"
    if isinstance(v, float): return fmt_r(v)
    return str(v)


def structured(obj, indent=0, out=None):
    """Indented 'key: value' rendering used by 3.0.3 command-result TXT reports."""
    if out is None: out = []
    pad = "  " * indent
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.append(pad + str(k) + ":"); structured(v, indent + 1, out)
            else:
                out.append(pad + str(k) + ": " + scalar(v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.append(pad + "[" + str(i) + "]")
            if isinstance(v, (dict, list)): structured(v, indent + 1, out)
            else: out.append(pad + "  " + scalar(v))
    else:
        out.append(pad + scalar(obj))
    return out


def _pdf_text(s):
    s = "".join(_TRANSLIT.get(ch, ch) for ch in s)
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_lines(text):
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        raw = raw.expandtabs(4)
        if not raw:
            lines.append(""); continue
        while len(raw) > WRAP:
            lines.append(raw[:WRAP]); raw = "  " + raw[WRAP:]
        lines.append(raw)
    return lines


def pdf_bytes(text, title="SpinDoctor report"):
    lines = wrap_lines(text)
    per_page = int((PAGE_H - 2 * MARGIN) // LEADING)
    pages = [lines[i:i + per_page] for i in range(0, max(1, len(lines)), per_page)] or [[]]
    objs = []

    def add(b):
        objs.append(b); return len(objs)
    catalog = add(None); pages_id = add(None); font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    info = add(("<< /Title (" + _pdf_text(title) + ") /Producer (SpinDoctor Scripter Cartridge 1.1.0 built-in PDF writer) >>").encode("latin-1"))
    kids = []
    total = len(pages)
    for n, pl in enumerate(pages, 1):
        body = ["BT", "/F1 %.1f Tf" % FONT_SIZE, "%.1f TL" % LEADING, "%d %d Td" % (MARGIN, PAGE_H - MARGIN)]
        for ln in pl:
            body.append("(" + _pdf_text(ln) + ") '")
        body.append("ET")
        body.append("BT /F1 6 Tf %d %d Td (%s) Tj ET" % (MARGIN, MARGIN // 2, _pdf_text("%s - page %d of %d - classical simulation report" % (title, n, total))))
        raw = "\n".join(body).encode("latin-1")
        comp = zlib.compress(raw, 9)
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(comp) + comp + b"\nendstream")
        page = add(("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                    % (pages_id, PAGE_W, PAGE_H, font, content)).encode("latin-1"))
        kids.append(page)
    objs[catalog - 1] = ("<< /Type /Catalog /Pages %d 0 R >>" % pages_id).encode("latin-1")
    objs[pages_id - 1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids))).encode("latin-1")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offsets = []
    for i, b in enumerate(objs, 1):
        offsets.append(len(out)); out += b"%d 0 obj\n" % i + b + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets: out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref)
    return bytes(out)


def check_pdf(data):
    """Structural self-check: header, EOF, xref offsets point at 'N 0 obj', pages decode."""
    if not data.startswith(b"%PDF-1.") or not data.rstrip().endswith(b"%%EOF"):
        return False, "bad header/trailer"
    sx = data.rfind(b"startxref"); xref = int(data[sx + 9:].split()[0])
    if data[xref:xref + 4] != b"xref": return False, "startxref mismatch"
    lines = data[xref:].split(b"\n"); n = int(lines[1].split()[1])
    for i in range(1, n):
        off = int(lines[2 + i][:10])
        if not data[off:].startswith(b"%d 0 obj" % i): return False, "xref offset %d wrong" % i
    import re
    pages = 0
    for m in re.finditer(rb"stream\n(.*?)\nendstream", data, re.S):
        zlib.decompress(m.group(1)); pages += 1
    return True, "ok (%d content streams)" % pages


def write_bundle(base, text, payload, title):
    """Write base.txt, base.json, base.csv (3.1.x CSV companion) and base.pdf atomically; return paths."""
    import hashlib
    from . import csvreport
    js = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
    atomic_write(base + ".txt", text)
    atomic_write(base + ".json", js)
    paths = [base + ".txt", base + ".json"]
    try:
        safe = json.loads(json.dumps(payload, default=str))
        csv_text = csvreport.build(safe, "command", os.path.basename(base), "native", "3.1.2", hashlib.sha256(js.encode("utf-8")).hexdigest())
        atomic_write(base + ".csv", csv_text)
        paths.append(base + ".csv")
    except ValueError as e:  # CSV bounds never block the authoritative TXT/JSON/PDF
        atomic_write(base + ".csv.txt", "CSV companion not written: " + str(e) + "\n")
    atomic_write(base + ".pdf", pdf_bytes(text, title), binary=True)
    paths.append(base + ".pdf")
    return paths
