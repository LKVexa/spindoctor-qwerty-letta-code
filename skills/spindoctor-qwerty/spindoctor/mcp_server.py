# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Minimal stdio MCP server (JSON-RPC 2.0, newline-delimited) exposing the SpinDoctor tools.
Standard library only.  Implements initialize, ping, tools/list, tools/call and ignores notifications."""
import json
import sys

from . import api
from .terminal import CARTRIDGE_VERSION

PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]


READ_ONLY = ("spindoctor_functions", "spindoctor_list_presets", "spindoctor_report")  # pure: no files written


def handle(msg):
    mid = msg.get("id"); method = msg.get("method")
    if mid is None:
        return None  # notification (e.g. notifications/initialized)
    try:
        if method == "initialize":
            req = (msg.get("params") or {}).get("protocolVersion")
            ver = req if req in PROTOCOLS else PROTOCOLS[0]
            res = {"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "spindoctor-qwerty", "version": CARTRIDGE_VERSION},
                   "instructions": "SpinDoctor quantum-circuit SIMULATOR (classical FP64). Use spindoctor_functions (show its Markdown table in chat on first use), spindoctor_run_script, spindoctor_run_preset, spindoctor_list_presets, spindoctor_report and spindoctor_test_theory (theory from a file, pasted text or a confirmed chat summary with quoted excerpts). Never present results as real quantum hardware or quantum advantage."}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"],
                              "annotations": {"readOnlyHint": t["name"] in READ_ONLY, "destructiveHint": False, "openWorldHint": False}}
                             for t in api.TOOLS]}
        elif method == "tools/call":
            p = msg.get("params") or {}
            out = api.call(p.get("name"), p.get("arguments") or {})
            text = out["markdown"] if out.get("ok") and isinstance(out.get("markdown"), str) else api.as_json(out)  # function table: verbatim Markdown
            res = {"content": [{"type": "text", "text": text}], "structuredContent": out, "isError": not out.get("ok", False)}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "Method not found: " + str(method)}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    except Exception as e:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def main():
    import io
    inp = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    sys.stdout = sys.stderr  # nothing but protocol frames may reach the real stdout
    for line in inp:
        line = line.strip()
        if not line: continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n"); out.flush(); continue
        batch = msg if isinstance(msg, list) else [msg]
        for m in batch:
            r = handle(m)
            if r is not None:
                out.write(json.dumps(r, ensure_ascii=False, default=str) + "\n"); out.flush()


if __name__ == "__main__":
    main()
