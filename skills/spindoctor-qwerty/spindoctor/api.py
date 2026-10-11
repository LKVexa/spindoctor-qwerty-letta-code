# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Host-neutral tool API shared by the CLI, the stdio MCP server, the Hermes plugin and the skills.
Every function returns a JSON-serialisable dict and never raises."""
import json
import os

from .terminal import Session, GUARDRAIL, CARTRIDGE_VERSION, ENGINE_VERSION

DEFAULT_WORKSPACE = os.environ.get("SPINDOCTOR_WORKSPACE") or os.path.join(os.path.expanduser("~"), "spindoctor-workspace")
MAX_TEXT = 60000

TOOLS = [
    {"name": "spindoctor_run_script",
     "description": ("Run one or more SpinDoctor q.* commands (one per line) in the persistent simulator workspace and return each "
                     "result plus TXT/JSON/PDF report paths. Classical FP64 simulation only; not a quantum computer. "
                     "Example: 'q.circuit new bell 2\\nq.circuit add h 0\\nq.circuit add cx 0 1\\nq.circuit run shots 1000 basis z'."),
     "parameters": {"type": "object", "properties": {
         "script": {"type": "string", "description": "q.* commands, one per line; blank lines and # comments are ignored."},
         "workspace": {"type": "string", "description": "Optional workspace folder (default ~/spindoctor-workspace or $SPINDOCTOR_WORKSPACE)."}},
         "required": ["script"]}},
    {"name": "spindoctor_run_preset",
     "description": "Run one of the 241 built-in SpinDoctor presets (qc-001..qc-241) with optional name=value overrides; returns per-step results and report paths.",
     "parameters": {"type": "object", "properties": {
         "preset_id": {"type": "string", "description": "Preset id such as qc-061."},
         "overrides": {"type": "object", "description": "Optional overrides (shots, basis, qubits, input, angle).", "additionalProperties": {"type": "string"}},
         "workspace": {"type": "string"}}, "required": ["preset_id"]}},
    {"name": "spindoctor_list_presets",
     "description": "List the SpinDoctor presets (id, category, label, availability, commands). Optional case-insensitive filter text.",
     "parameters": {"type": "object", "properties": {"filter": {"type": "string"}, "workspace": {"type": "string"}}}},
    {"name": "spindoctor_report",
     "description": "Return the text of a SpinDoctor report (TXT) from the workspace, or list the newest reports when no name is given.",
     "parameters": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Report file name or path relative to <workspace>/reports (e.g. qc-061.txt)."},
         "limit": {"type": "integer", "description": "How many recent reports to list (default 20)."},
         "workspace": {"type": "string"}}}},
    {"name": "spindoctor_functions",
     "description": ("Return the in-chat Markdown table of EVERY SpinDoctor function: columns Function | What it does | Command to type, grouped by "
                     "command family, with real runnable examples (plus the 241 presets with section='presets'). Show the table to the user "
                     "verbatim when they ask what the plugin can do, ask for help/functions, or on first use."),
     "parameters": {"type": "object", "properties": {
         "section": {"type": "string", "enum": ["commands", "gates", "tools", "presets", "all"], "description": "commands (default: tools + every q.* family + gates), gates, tools, presets (241 rows) or all."},
         "filter": {"type": "string", "description": "Optional case-insensitive text filter (e.g. 'tranche', 'noise', 'grover')."}}}},
    {"name": "spindoctor_test_theory",
     "description": ("Test a theory/experiment with the simulator and write a TXT+JSON+PDF theory test report (hypothesis, script, raw results, "
                     "verdict supported / not supported / inconclusive, limits). source='file': a .txt/.md/.pdf/.py/.json/.csv/.q attachment by local path; "
                     "source='text': pasted text; source='chat': a theory summary the AI wrote from the conversation and the user confirmed, plus optional "
                     "quoted excerpts and/or an exported chat transcript (.txt/.md/.json/.html). Use action='extract' first to read the source, then "
                     "action='run' with hypothesis, prediction, checks and a q.* script. The plugin cannot read chat history or host attachments by itself."),
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["extract", "run"], "description": "extract = read/parse the source only; run (default) = run the script, compare, write the report."},
         "source": {"type": "string", "enum": ["file", "text", "chat"], "description": "Where the theory comes from."},
         "path": {"type": "string", "description": "Local path of the attachment (source=file) or of an exported chat transcript (source=chat)."},
         "text": {"type": "string", "description": "Pasted theory text (source=text) or the confirmed theory summary: claims, assumptions, variables, measurable prediction (source=chat)."},
         "excerpts": {"type": "array", "items": {"type": "string"}, "description": "source=chat: verbatim quotes from the conversation, e.g. 'User: ...', 'Assistant: ...'."},
         "hypothesis": {"type": "string", "description": "The hypothesis restated in one or two sentences (required for run)."},
         "prediction": {"type": "string", "description": "The measurable prediction in words (required for run)."},
         "checks": {"type": "array", "items": {"type": "object"}, "description": ("Machine checks. {kind:'probability', outcome:'00', expected:0.5, tolerance:0.05, command?:N} "
                    "(bitstrings: qubit 0 is the RIGHTMOST bit; uses the last histogram or zero/one counts) | {kind:'value', command:N, path:'result.fidelity', op:'approx|eq|ne|lt|le|gt|ge|contains|true|false', value:X, tolerance?:T} | {kind:'ok', command:N, expected:true}.")},
         "script": {"type": "string", "description": "q.* commands, one per line (defaults to q.* lines found in the source)."},
         "assumptions": {"type": "array", "items": {"type": "string"}}, "variables": {"type": "array", "items": {"type": "string"}},
         "title": {"type": "string"}, "workspace": {"type": "string"},
         "isolate": {"type": "boolean", "description": "Default true: run in a fresh sub-workspace (<workspace>/theory-runs/<id>) so names never collide; false = use the shared workspace state."}}}},
]


def _session(ws):
    """Open the workspace session.  Optional reproducibility: SPINDOCTOR_MEASUREMENT_SEED / SPINDOCTOR_FIELD_SEED
    (64 hex chars) seed a NEW workspace only; an existing workspace always keeps its own saved seeds."""
    ws = ws or DEFAULT_WORKSPACE
    ms = os.environ.get("SPINDOCTOR_MEASUREMENT_SEED") or None; fs = os.environ.get("SPINDOCTOR_FIELD_SEED") or None
    if (ms or fs) and not os.path.exists(os.path.join(ws, "spindoctor-cartridge-session.json")):
        for v in (ms, fs):
            if v is not None and not (len(v) == 64 and all(c in "0123456789abcdef" for c in v)):
                raise ValueError("SPINDOCTOR_MEASUREMENT_SEED / SPINDOCTOR_FIELD_SEED must be 64 lowercase hex characters.")
        return Session(ws, measurement_seed=ms, field_seed=fs)
    return Session(ws)


def _slim(result):
    """Keep tool output compact: drop embedded status blocks."""
    if isinstance(result, dict):
        return {k: _slim(v) for k, v in result.items() if k not in ("status", "record")}
    if isinstance(result, list):
        return [_slim(v) for v in result]
    return result


def run_script(script, workspace=None):
    try:
        s = _session(workspace); out = []
        for line in (script or "").splitlines():
            c = line.strip()
            if not c or c.startswith("#") or c.startswith("//"): continue
            r = s.run_command(c)
            resp = r.get("response", {})
            out.append({"command": c, "ok": r["ok"], "result": _slim(resp.get("result")) if r["ok"] else None,
                        "error": None if r["ok"] else resp.get("error", r.get("error")), "reports": r.get("reports", []),
                        "steps": [{"index": x["index"], "command": x["command"], "ok": x["ok"], "error": x["error"]} for x in r.get("steps", [])] or None})
            if len(out) >= 200: break
        return {"ok": all(x["ok"] for x in out) if out else False, "results": out, "workspace": s.workspace, "guardrail": GUARDRAIL,
                "error": None if out else "No commands supplied."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "guardrail": GUARDRAIL}


def run_preset(preset_id, overrides=None, workspace=None):
    try:
        s = _session(workspace)
        r = s.run_sequence(None, preset_id, dict(overrides or {}), "q.preset run " + preset_id)
        s.save()
        return {"ok": r["ok"], "preset": preset_id, "phase": r["phase"], "error": r["error"], "reports": r["reports"],
                "steps": [{"index": x["index"], "command": x["command"], "ok": x["ok"], "error": x["error"], "result": _slim(x["result"]), "reports": x["reports"]}
                          for x in r["steps"]], "workspace": s.workspace, "guardrail": GUARDRAIL}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "guardrail": GUARDRAIL}


def list_presets(filter=None, workspace=None):  # noqa: A002 - tool argument name
    try:
        s = Session(None, write_reports=False)
        f = (filter or "").lower(); rows = []
        for p in s.presets["presets"]:
            c = s.preset_card(p["id"])
            text = " ".join([c["id"], c["category"], c["label"]] + c["commands"]).lower()
            if f and f not in text: continue
            rows.append({"id": c["id"], "category": c["category"], "label": c["label"], "availability": c["runtimeAvailability"],
                         "reason": c["runtimeReason"], "commands": c["commands"]})
        return {"ok": True, "count": len(rows), "presets": rows}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def report(name=None, limit=20, workspace=None):
    try:
        base = os.path.join(os.path.abspath(workspace or DEFAULT_WORKSPACE), "reports")
        if not name:
            files = []
            for root, _, fs in os.walk(base):
                for f in fs:
                    if f.endswith(".txt"):
                        p = os.path.join(root, f); files.append((os.path.getmtime(p), os.path.relpath(p, base)))
            files.sort(reverse=True)
            return {"ok": True, "reportsDir": base, "reports": [f for _, f in files[:max(1, int(limit or 20))]]}
        p = os.path.abspath(os.path.join(base, name))
        if not p.startswith(base + os.sep): return {"ok": False, "error": "Report path must stay inside the workspace reports folder."}
        if not os.path.exists(p) and os.path.exists(p + ".txt"): p += ".txt"
        with open(p, encoding="utf-8") as fh: text = fh.read()
        trunc = len(text) > MAX_TEXT
        return {"ok": True, "path": p, "pdf": p[:-4] + ".pdf" if p.endswith(".txt") else None, "truncated": trunc,
                "text": text[:MAX_TEXT] + ("\n...[truncated; open the file for the full report]" if trunc else "")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def functions_table(section=None, filter=None):  # noqa: A002
    try:
        from . import functions
        md = functions.table(section or "commands", filter)
        return {"ok": True, "format": "markdown", "display": "Show this Markdown table to the user verbatim.", "markdown": md}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def test_theory(args):
    try:
        from . import theory
        a = dict(args or {})
        return theory.test_theory(a, os.path.abspath(a.get("workspace") or DEFAULT_WORKSPACE))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "guardrail": GUARDRAIL}


def call(name, args):
    args = dict(args or {})
    if name == "spindoctor_run_script": return run_script(args.get("script", ""), args.get("workspace"))
    if name == "spindoctor_run_preset": return run_preset(args.get("preset_id", ""), args.get("overrides"), args.get("workspace"))
    if name == "spindoctor_list_presets": return list_presets(args.get("filter"), args.get("workspace"))
    if name == "spindoctor_report": return report(args.get("name"), args.get("limit", 20), args.get("workspace"))
    if name in ("spindoctor_functions", "spindoctor_help"): return functions_table(args.get("section"), args.get("filter"))
    if name == "spindoctor_test_theory": return test_theory(args)
    return {"ok": False, "error": "Unknown tool " + str(name)}


def as_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)
