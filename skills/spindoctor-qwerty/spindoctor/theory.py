# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Theory testing (v1.1.0): attachment/text/chat-history in -> hypothesis -> measurable prediction -> q.* script -> run
-> compare -> TXT + JSON + PDF 'theory test report' with verdict (supported / not supported / inconclusive) and limits.

The plugin never sees the chat or the host's attachments by itself: the AI (which sees the conversation) must pass the
file path, the pasted text, or a confirmed theory summary plus quoted excerpts."""
import datetime
import html
import json
import math
import os
import re
import zlib

from .reports import write_bundle
from .terminal import Session, GUARDRAIL, CARTRIDGE_VERSION

MAX_IN = 5 * 1024 * 1024
MAX_TEXT = 60000
THEORY_EXT = (".txt", ".md", ".markdown", ".pdf", ".py", ".json", ".csv", ".q", ".qs", ".text")
CHAT_EXT = (".txt", ".md", ".markdown", ".json", ".html", ".htm")
LIMITS = [
    "Classical FP64 simulation of an ideal (noise-free unless q.noise is used) quantum circuit model; not a quantum computer and no quantum-advantage claim.",
    "Registers up to 298 logical qubits, at most 59 qubits per entangled factor; dense factors are limited by the memory guard (22 qubits stdlib / 26 with NumPy) and the configured budget. Registers wider than 29 qubits sample in basis z only.",
    "Sampled histograms carry shot noise (standard error ~ sqrt(p(1-p)/shots)); seeded sampling is reproducible in one workspace.",
    "The verdict only covers what the q.* script encodes and the checks state; it is not evidence about physical hardware or about claims outside the model.",
    "The plugin cannot read chat history or host attachments directly; it tests the summary, excerpts or file content the AI passed in.",
]

# ---------------------------------------------------------------- PDF text extraction (pypdf if present, else pure Python)
def _pdf_unescape(s):
    """PDF literal string body (latin-1 str) -> raw bytes as latin-1 str."""
    out = []; i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]; m = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "(": "(", ")": ")", "\\": "\\"}
            if n in m: out.append(m[n]); i += 2; continue
            if n in "01234567":
                j = i + 1; o = ""
                while j < len(s) and len(o) < 3 and s[j] in "01234567": o += s[j]; j += 1
                out.append(chr(int(o, 8) & 0xFF)); i = j; continue
            if n in "\r\n": i += 2; continue
            out.append(n); i += 2; continue
        out.append(c); i += 1
    return "".join(out)


def _parse_cmap(text):
    """ToUnicode CMap -> (code width in bytes, {code:int -> str})."""
    m = {}; width = 1
    cs = re.search(r"begincodespacerange\s*<([0-9A-Fa-f]+)>", text)
    if cs: width = max(1, len(cs.group(1)) // 2)
    def u(h):
        b = bytes.fromhex(h if len(h) % 2 == 0 else "0" + h)
        try: return b.decode("utf-16-be")
        except UnicodeDecodeError: return b.decode("latin-1")
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", blk): m[int(a, 16)] = u(b)
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for a, b, rest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)", blk):
            lo, hi = int(a, 16), int(b, 16)
            if rest.startswith("["):
                for k, h in enumerate(re.findall(r"<([0-9A-Fa-f]+)>", rest)): m[lo + k] = u(h)
            else:
                base = int(rest[1:-1], 16); n = len(rest[1:-1])
                for k in range(hi - lo + 1):
                    m[lo + k] = u(format(base + k, "0%dx" % n))
    return width, m


def _decode(raw, cmap):
    if not cmap: return raw
    width, m = cmap; b = raw.encode("latin-1"); out = []
    for i in range(0, len(b) - width + 1, width):
        code = int.from_bytes(b[i:i + width], "big"); out.append(m.get(code, "" if width > 1 else chr(code)))
    return "".join(out)


_TOK = re.compile(r"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)|<[0-9A-Fa-f\s]*>|/[^\s/<>\[\]()]+|\[|\]|T\*|Tj|TJ|Tf|'|\"|Td|TD|Tm|ET|BT|-?\d*\.?\d+", re.S)


def _content_text(stream, fonts):
    s = stream.decode("latin-1"); out = []; cur = []; cmap = None; last_name = None
    for m in _TOK.finditer(s):
        t = m.group(0)
        if t.startswith("("): cur.append(_decode(_pdf_unescape(t[1:-1]), cmap))
        elif t.startswith("<"):
            h = re.sub(r"\s", "", t[1:-1]); h += "0" * (len(h) % 2)
            cur.append(_decode(bytes.fromhex(h).decode("latin-1"), cmap))
        elif t.startswith("/"): last_name = t[1:]
        elif t == "Tf": cmap = fonts.get(last_name)
        elif t in ("Tj", "TJ", "'", '"'):
            if t in ("'", '"'): out.append("\n")
            out.append("".join(cur)); cur = []
        elif t in ("T*", "Td", "TD", "Tm", "ET"):
            if out and not out[-1].endswith("\n"): out.append("\n")
            cur = []
        elif t[0] in "-.0123456789" and cur:
            try:
                if float(t) < -200: cur.append(" ")  # TJ kerning gap = word space
            except ValueError: pass
    return "".join(out)


def _inflate(d, raw):
    if b"FlateDecode" in d:
        try: return zlib.decompress(raw)
        except zlib.error:
            try: return zlib.decompressobj().decompress(raw)
            except zlib.error: return None
    return None if b"/Filter" in d else raw


def pdf_text(data):
    try:
        import io, pypdf  # optional
        r = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in r.pages), "pypdf " + getattr(pypdf, "__version__", "")
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - fall back to the built-in extractor
        pass
    objs = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", data, re.S):
        body = m.group(2); sm = re.search(rb"stream\r?\n", body)
        if sm:
            d = body[:sm.start()]; raw = body[sm.end():]
            raw = re.sub(rb"\r?\n?endstream\s*$", b"", raw.rstrip()) if raw.rstrip().endswith(b"endstream") else raw
            objs[int(m.group(1))] = (d, _inflate(d, raw))
        else:
            objs[int(m.group(1))] = (body, None)
    cmaps = {}
    for n, (d, st) in objs.items():
        tu = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", d)
        if b"/Font" in d and tu and int(tu.group(1)) in objs and objs[int(tu.group(1))][1]:
            cmaps[n] = _parse_cmap(objs[int(tu.group(1))][1].decode("latin-1"))
    fonts = {}
    for n, (d, st) in objs.items():
        for fm in re.finditer(rb"/Font\s*(<<.*?>>|(\d+)\s+0\s+R)", d, re.S):
            fd = fm.group(1)
            if fm.group(2): fd = objs.get(int(fm.group(2)), (b"", None))[0]
            for name, ref in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R", fd):
                if int(ref) in cmaps: fonts[name.decode("latin-1")] = cmaps[int(ref)]
    parts = []
    for n, (d, st) in sorted(objs.items()):
        if st and b"/Image" not in d and b"BT" in st and b"ET" in st and b"/ToUnicode" not in d and b"begincmap" not in st:
            parts.append(_content_text(st, fonts))
    text = "\n".join(p.strip("\n") for p in parts if p.strip())
    return text, "built-in pure-Python extractor (FlateDecode, Tj/TJ, ToUnicode CMaps; no OCR)"

# ---------------------------------------------------------------- chat transcripts
ROLE = r"(user|you|human|me|assistant|chatgpt|gpt|claude|grok|ai|model|bot|system|gemini|copilot)"
_LINE = re.compile(r"^\s*(?:#{1,6}\s*|\*\*|__)?" + ROLE + r"(?:\s*\([^)]*\))?\s*(?:\*\*|__)?\s*[:：]?\s*(?:\*\*|__)?\s*(.*)$", re.I)


def _norm_role(r):
    r = r.lower()
    return "user" if r in ("user", "you", "human", "me") else "system" if r == "system" else "assistant"


def _turns_from_text(text):
    turns = []; cur = None
    for line in text.splitlines():
        m = _LINE.match(line)
        if m and (line.strip().endswith(":") or ":" in line[:40] or "：" in line[:40] or line.lstrip().startswith(("#", "**", "__"))):
            if cur and cur["text"].strip(): turns.append(cur)
            cur = {"role": _norm_role(m.group(1)), "text": m.group(2).strip()}
        elif cur is not None: cur["text"] += ("\n" if cur["text"] else "") + line
    if cur and cur["text"].strip(): turns.append(cur)
    for t in turns: t["text"] = t["text"].strip()
    return turns


def _content_str(c):
    if isinstance(c, str): return c
    if isinstance(c, list): return "\n".join(_content_str(x) for x in c)
    if isinstance(c, dict):
        for k in ("parts", "text", "content", "value"):
            if k in c: return _content_str(c[k])
    return ""


def _turns_from_json(obj):
    convs = obj if isinstance(obj, list) else [obj]
    turns = []
    for cv in convs:
        if not isinstance(cv, dict):
            continue
        if "mapping" in cv:  # ChatGPT export (conversations.json / single conversation)
            nodes = cv["mapping"]; order = []
            node = cv.get("current_node")
            while node and node in nodes:
                order.append(node); node = nodes[node].get("parent")
            ids = list(reversed(order)) if order else list(nodes)
            for i in ids:
                msg = (nodes.get(i) or {}).get("message") or {}
                role = ((msg.get("author") or {}).get("role")) or ""
                text = _content_str(msg.get("content") or {}).strip()
                if role in ("user", "assistant") and text: turns.append({"role": role, "text": text})
        elif "chat_messages" in cv:  # Claude export
            for m in cv["chat_messages"]:
                text = (m.get("text") or _content_str(m.get("content"))).strip()
                if text: turns.append({"role": "user" if m.get("sender") in ("human", "user") else "assistant", "text": text})
        elif "messages" in cv:
            turns += _turns_from_json(cv["messages"])
        else:
            role = cv.get("role") or cv.get("author") or cv.get("sender") or cv.get("from")
            if isinstance(role, dict): role = role.get("role")
            text = _content_str(cv.get("content") if "content" in cv else cv.get("text", "")).strip()
            if role and text: turns.append({"role": _norm_role(str(role)) if str(role).lower() not in ("user", "assistant") else str(role).lower(), "text": text})
    return turns


def _strip_html(h):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", h)
    return html.unescape(re.sub(r"<[^>]+>", "", h))


def parse_transcript(path, raw):
    ext = os.path.splitext(path)[1].lower(); text = raw.decode("utf-8-sig", "replace")
    if ext == ".json":
        return _turns_from_json(json.loads(text)), "json chat export"
    if ext in (".html", ".htm"):
        m = re.search(r"(?:var|let|const)\s+jsonData\s*=\s*(\[.*?\]|\{.*?\})\s*;?\s*\n", text, re.S)
        if m:
            try: return _turns_from_json(json.loads(m.group(1))), "html chat export (embedded jsonData)"
            except ValueError: pass
        return _turns_from_text(_strip_html(text)), "html chat export (text)"
    return _turns_from_text(text), "text/markdown chat transcript"


def parse_excerpts(ex):
    if not ex: return []
    if isinstance(ex, str):
        t = _turns_from_text(ex)
        return t if t else [{"role": "unknown", "text": p.strip()} for p in re.split(r"\n\s*\n", ex) if p.strip()]
    out = []
    for e in ex:
        if isinstance(e, dict): out.append({"role": str(e.get("role", "unknown")), "text": str(e.get("text") or e.get("content") or "").strip()})
        else:
            t = _turns_from_text(str(e)); out += t if t else [{"role": "unknown", "text": str(e).strip()}]
    return [x for x in out if x["text"]]

# ---------------------------------------------------------------- source extraction
def _read(path):
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(p): raise ValueError("File not found: " + p + " (the host app must pass a real local path or the file content).")
    if os.path.getsize(p) > MAX_IN: raise ValueError("File is larger than 5 MiB.")
    with open(p, "rb") as fh: return p, fh.read()


def q_lines(text):
    out = []
    for line in text.splitlines():
        s = line.strip().strip("`").strip()
        s = re.sub(r"^(?:#|//|>|-|\*|\d+[.)])\s*", "", s).strip().strip("\"'`,")
        if re.match(r"^q\.[a-z]+(\s|$)", s): out.append(s)
    return out


def extract(source="text", path=None, text=None, excerpts=None):
    source = (source or ("file" if path else "text")).lower()
    info = {"source": source}
    if source == "chat":
        turns = parse_excerpts(excerpts); info["excerptCount"] = len(turns)
        if path:
            p, raw = _read(path)
            if os.path.splitext(p)[1].lower() not in CHAT_EXT: raise ValueError("Chat transcript must be .txt, .md, .json or .html.")
            tt, kind = parse_transcript(p, raw)
            info.update({"transcriptPath": p, "transcriptKind": kind, "transcriptTurns": len(tt)})
            if not turns: turns = tt
            info["transcript"] = [{"role": t["role"], "text": t["text"][:4000]} for t in tt[:400]]
        info["summary"] = (text or "").strip(); info["excerpts"] = turns
        body = info["summary"] + "\n" + "\n".join(t["text"] for t in turns) + "\n" + "\n".join(t["text"] for t in info.get("transcript", []))
        if not body.strip(): raise ValueError("source='chat' needs the confirmed theory summary in 'text', quoted 'excerpts', or an exported transcript 'path'.")
        info["text"] = body.strip()[:MAX_TEXT]
    elif source == "file":
        if not path: raise ValueError("source='file' needs 'path' (the host app must pass the attachment's local path).")
        p, raw = _read(path); ext = os.path.splitext(p)[1].lower()
        if ext not in THEORY_EXT: raise ValueError("Supported theory files: " + ", ".join(THEORY_EXT))
        if ext == ".pdf":
            t, how = pdf_text(raw)
        else:
            t, how = raw.decode("utf-8-sig", "replace"), "utf-8 text"
            if ext == ".json":
                try:
                    obj = json.loads(t); how = "json"
                    if isinstance(obj, dict):
                        for k in ("script", "commands"):
                            if k in obj: info["embeddedScript"] = "\n".join(obj[k]) if isinstance(obj[k], list) else str(obj[k])
                except ValueError: how = "json (unparsable, read as text)"
            elif ext == ".csv":
                info["csvRows"] = max(0, len([l for l in t.splitlines() if l.strip()]) - 1)
        info.update({"path": p, "fileType": ext, "extractor": how, "bytes": len(raw)})
        info["text"] = t[:MAX_TEXT]; info["truncated"] = len(t) > MAX_TEXT
    else:
        if not (text or "").strip(): raise ValueError("source='text' needs the theory text in 'text'.")
        info["text"] = text.strip()[:MAX_TEXT]
    info["qLines"] = q_lines(info.get("embeddedScript", "") + "\n" + info["text"])
    if info["source"] == "file" and info.get("fileType") in (".q", ".qs"): info["qLines"] = q_lines(info["text"])
    return info

# ---------------------------------------------------------------- run + compare
def _get(obj, path):
    cur = obj
    for part in [p for p in re.split(r"\.|\[(\d+)\]", path or "") if p]:
        if isinstance(cur, list): cur = cur[int(part)]
        elif isinstance(cur, dict): cur = cur[part]
        else: raise KeyError(path)
    return cur


def _num(v):
    return float(v) if isinstance(v, (int, float, str)) and not isinstance(v, bool) else None


def _hist_source(results, idx):
    cand = [results[idx - 1]] if idx else list(reversed(results))
    for r in cand:
        res = r.get("result") if isinstance(r, dict) else None
        if not isinstance(res, dict): continue
        if isinstance(res.get("histogram"), list):
            h = {x["bitstring"]: int(x["count"]) for x in res["histogram"]}
            return h, int(res.get("completedShots") or sum(h.values())), r["command"]
        if "zero" in res and "one" in res:
            h = {"0": int(res["zero"]), "1": int(res["one"])}; return h, sum(h.values()), r["command"]
    return None, 0, None


def evaluate(check, results):
    kind = (check.get("kind") or "value").lower(); idx = int(check.get("command") or 0)
    row = {"check": check, "kind": kind}
    try:
        if kind == "probability":
            h, shots, cmd = _hist_source(results, idx)
            if not h: return dict(row, status="inconclusive", detail="No histogram/zero-one counts found in the script results.")
            out = str(check["outcome"]); exp = float(check["expected"]); tol = float(check.get("tolerance", 0.05))
            obs = h.get(out, 0) / shots if shots else 0.0
            se = math.sqrt(max(exp * (1 - exp), 1e-12) / shots) if shots else float("inf")
            ok = abs(obs - exp) <= tol
            note = " Tolerance is tighter than 2 standard errors (%.4f): increase shots." % (2 * se) if tol < 2 * se else ""
            return dict(row, status="pass" if ok else "fail", observed=obs, expected=exp, tolerance=tol, shots=shots, standardError=se, source=cmd,
                        detail="P(%s) observed %.4f vs predicted %.4f +/- %.4f over %d shots (%s).%s" % (out, obs, exp, tol, shots, cmd, note))
        if kind == "ok":
            r = results[idx - 1]; exp = bool(check.get("expected", True))
            return dict(row, status="pass" if r["ok"] == exp else "fail", observed=r["ok"], expected=exp, detail="%s ok=%s (expected %s)%s" % (r["command"], r["ok"], exp, "; error: " + str(r["error"]) if r["error"] else ""))
        r = results[(idx or len(results)) - 1]
        if not r["ok"]: return dict(row, status="inconclusive", detail="Command %d failed: %s" % (idx or len(results), r["error"]))
        v = _get({"result": r["result"]}, check.get("path") or "result"); op = (check.get("op") or "approx").lower(); want = check.get("value"); tol = float(check.get("tolerance", 1e-6))
        fv, fw = _num(v), _num(want)
        if op == "approx": ok = fv is not None and fw is not None and abs(fv - fw) <= tol
        elif op in ("eq", "=="): ok = (fv == fw) if fv is not None and fw is not None else v == want
        elif op in ("ne", "!="): ok = (fv != fw) if fv is not None and fw is not None else v != want
        elif op in ("lt", "le", "gt", "ge"): ok = fv is not None and fw is not None and {"lt": fv < fw, "le": fv <= fw, "gt": fv > fw, "ge": fv >= fw}[op]
        elif op == "contains": ok = str(want) in json.dumps(v, default=str)
        elif op == "true": ok = v is True
        elif op == "false": ok = v is False
        else: return dict(row, status="inconclusive", detail="Unknown op " + op)
        return dict(row, status="pass" if ok else "fail", observed=v, expected=want, detail="%s %s %s %r (tolerance %g) -> observed %r" % (r["command"], check.get("path") or "result", op, want, tol, v))
    except (KeyError, IndexError, ValueError, TypeError) as e:
        return dict(row, status="inconclusive", detail="Check could not be evaluated: %s: %s" % (type(e).__name__, e))


def _compact(v, n=3000):
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + " ...[truncated; full JSON in the per-command reports]"


def _slug(s):
    return (re.sub(r"[^a-z0-9]+", "-", (s or "theory").lower()).strip("-") or "theory")[:40]


def test_theory(args, workspace):
    a = dict(args or {}); action = (a.get("action") or "run").lower()
    info = extract(a.get("source"), a.get("path"), a.get("text"), a.get("excerpts"))
    if action == "extract":
        view = dict(info); view["transcript"] = info.get("transcript", [])[:60]
        return {"ok": True, "action": "extract", "extracted": view,
                "next": "Restate the hypothesis, state a measurable prediction with checks, write a q.* script, show the user, then call again with action='run'.",
                "guardrail": GUARDRAIL}
    hyp = (a.get("hypothesis") or "").strip(); pred = (a.get("prediction") or "").strip()
    script = a.get("script") or "\n".join(info["qLines"])
    if not hyp or not pred: raise ValueError("action='run' needs 'hypothesis' and 'prediction' (restate the theory and make a measurable prediction first).")
    if not script.strip(): raise ValueError("action='run' needs a q.* 'script' (none was supplied or found in the source).")
    checks = a.get("checks") or []
    if isinstance(checks, str): checks = json.loads(checks)
    if isinstance(checks, dict): checks = [checks]
    now = datetime.datetime.now(datetime.timezone.utc); title = a.get("title") or hyp[:80]
    run_id = now.strftime("%Y%m%d-%H%M%S-%f") + "-" + _slug(title)
    # Each theory runs in its own fresh sub-workspace so circuit names never collide and the run is reproducible.
    run_ws = workspace if a.get("isolate") is False else os.path.join(workspace, "theory-runs", run_id)
    s = Session(run_ws); results = []
    for line in script.splitlines():
        c = line.strip()
        if not c or c.startswith("#"): continue
        r = s.run_command(c); resp = r.get("response", {})
        results.append({"index": len(results) + 1, "command": c, "ok": bool(r["ok"]), "error": None if r["ok"] else resp.get("error", r.get("error")),
                        "result": resp.get("result"), "reports": r.get("reports", [])})
        if len(results) >= 200: break
    s.save()
    evals = [evaluate(c, results) for c in checks]
    failed_cmds = [r for r in results if not r["ok"]]
    if not evals:
        verdict, why = "inconclusive", "No machine-checkable prediction ('checks') was given, so the result cannot be compared automatically; see the raw results."
    elif any(e["status"] == "inconclusive" for e in evals):
        verdict, why = "inconclusive", "At least one check could not be evaluated (missing data or a failed command)."
    elif all(e["status"] == "pass" for e in evals):
        verdict, why = "supported", "Every prediction check passed within its stated tolerance in the simulated model."
    else:
        verdict, why = "not supported", "At least one prediction check failed: the simulated result contradicts the prediction."
    L = ["SPINDOCTOR QWERTY - THEORY TEST REPORT", "=" * 40, "Title: " + title, "Created (UTC): " + now.strftime("%Y-%m-%d %H:%M:%S"),
         "Engine: SpinDoctor Qwerty cartridge " + CARTRIDGE_VERSION + " (SpinDoctor 3.1.2 parity)", "Run workspace: " + s.workspace, ""]
    if info["source"] == "chat":
        L += ["Source: chat history", "-" * 20, "Theory summary (written by the AI from the conversation and confirmed by the user):", info.get("summary") or "(none given)", ""]
        if info.get("transcriptPath"): L += ["Exported transcript: %s (%s, %d turns)" % (info["transcriptPath"], info["transcriptKind"], info["transcriptTurns"])]
        L += ["Quoted excerpts (%d):" % len(info["excerpts"])]
        for i, t in enumerate(info["excerpts"][:50], 1):
            L += ['  [%d] %s: "%s"' % (i, t["role"], t["text"].replace("\n", "\n      ")[:2000])]
        L += ["Note: the plugin cannot read chat history itself; long chats may have been truncated by the host's context window.", ""]
    elif info["source"] == "file":
        L += ["Source: attachment file", "-" * 23, "Path: %s" % info["path"], "Type: %s, %d bytes, extractor: %s%s" % (info["fileType"], info["bytes"], info["extractor"], ", text truncated to 60000 chars" if info.get("truncated") else ""),
              "Excerpt:", info["text"][:1500], ""]
    else:
        L += ["Source: pasted text", "-" * 19, info["text"][:3000], ""]
    def lst(x): return x if isinstance(x, list) else [x] if x else []
    L += ["Hypothesis", "-" * 10, hyp, ""]
    if a.get("assumptions"): L += ["Assumptions:"] + ["  - " + str(x) for x in lst(a["assumptions"])] + [""]
    if a.get("variables"): L += ["Variables:"] + ["  - " + str(x) for x in lst(a["variables"])] + [""]
    L += ["Measurable prediction", "-" * 21, pred, ""]
    L += ["Script (q.*)", "-" * 12] + ["  %2d  %s" % (r["index"], r["command"]) for r in results] + [""]
    L += ["Raw results", "-" * 11]
    for r in results:
        L += ["[%d] %s -> %s" % (r["index"], r["command"], "ok" if r["ok"] else "ERROR: " + str(r["error"]))]
        if r["ok"]: L += ["     " + _compact(r["result"])]
    L += ["", "Prediction vs result", "-" * 20]
    L += ["  [%s] %s" % (e["status"].upper(), e["detail"]) for e in evals] or ["  (no machine checks supplied)"]
    L += ["", "VERDICT: " + verdict.upper(), why]
    if failed_cmds: L += ["Commands that failed: " + ", ".join("%d" % r["index"] for r in failed_cmds)]
    L += ["", "Limits", "-" * 6] + ["  - " + x for x in LIMITS] + ["", GUARDRAIL]
    text = "\n".join(L) + "\n"
    d = os.path.join(workspace, "reports", "theory"); os.makedirs(d, exist_ok=True)
    base = os.path.join(d, "theory-" + run_id)
    payload = {"schema": "SPINDOCTOR-QWERTY/THEORY-TEST/1", "title": title, "createdUtc": now.isoformat(), "cartridge": CARTRIDGE_VERSION,
               "source": {k: v for k, v in info.items() if k not in ("text",)}, "hypothesis": hyp, "assumptions": a.get("assumptions"), "variables": a.get("variables"),
               "prediction": pred, "checks": evals, "script": [r["command"] for r in results], "results": results, "verdict": verdict, "verdictReason": why, "limits": LIMITS}
    paths = write_bundle(base, text, payload, "SpinDoctor theory test - " + title)
    return {"ok": True, "action": "run", "verdict": verdict, "reason": why, "checks": [{k: v for k, v in e.items() if k != "check"} for e in evals],
            "commands": [{"index": r["index"], "command": r["command"], "ok": r["ok"], "error": r["error"]} for r in results],
            "source": info["source"], "excerptsRecorded": len(info.get("excerpts", [])), "reports": paths, "workspace": workspace, "runWorkspace": s.workspace, "limits": LIMITS, "guardrail": GUARDRAIL}
