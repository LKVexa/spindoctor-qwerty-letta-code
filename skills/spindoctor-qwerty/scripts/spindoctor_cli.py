#!/usr/bin/env python3
# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""SpinDoctor Scripter Cartridge CLI.

  spindoctor_cli.py run "q.circuit new bell 2" "q.circuit add h 0" ...   run commands
  spindoctor_cli.py script FILE.q                                          run a script file (one command per line)
  spindoctor_cli.py preset qc-061 [shots=500 ...]                          run a preset
  spindoctor_cli.py presets [FILTER]                                       list presets
  spindoctor_cli.py report [NAME]                                          list/show reports
  spindoctor_cli.py functions [commands|gates|tools|presets|all] [FILTER]  print the in-chat function table (Markdown)
  spindoctor_cli.py theory ARGS.json                                       test a theory (fields of spindoctor_test_theory)
  spindoctor_cli.py tool TOOL_NAME  < args.json                            host bridge: one tool call, JSON in/out
Options: --workspace DIR (default ~/spindoctor-workspace), --json (raw JSON output)."""
import argparse, json, os, sys
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):  # engine package lives next to scripts/ (or beside this file)
    if os.path.isdir(os.path.join(_p, "spindoctor")) and _p not in sys.path: sys.path.insert(0, _p)
from spindoctor import api  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace"); ap.add_argument("--json", action="store_true")
    ap.add_argument("action", choices=["run", "script", "preset", "presets", "report", "tool", "functions", "theory"]); ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.action == "tool":  # bridge used by the companion exe and the JS/TS host modules
        raw = sys.stdin.buffer.read().decode("utf-8-sig").strip() if not sys.stdin.isatty() else ""
        try:
            args = json.loads(raw) if raw else {}
        except ValueError as e:
            args = None; out = {"ok": False, "error": "Tool arguments must be a JSON object: " + str(e)}
        if args is not None:
            if a.workspace and "workspace" not in args: args["workspace"] = a.workspace
            out = api.call(a.args[0] if a.args else "", args)
        sys.stdout.buffer.write((api.as_json(out) + "\n").encode("utf-8")); sys.stdout.flush()
        return 0 if out.get("ok") else 1
    if a.action == "functions":  # functions [commands|gates|tools|presets|all] [filter]
        out = api.functions_table(a.args[0] if a.args else None, a.args[1] if len(a.args) > 1 else None)
        if out.get("ok") and not a.json:
            sys.stdout.buffer.write((out["markdown"] + "\n").encode("utf-8")); return 0
    elif a.action == "theory":  # theory ARGS.json  (same fields as the spindoctor_test_theory tool)
        with open(a.args[0], encoding="utf-8-sig") as fh: targs = json.load(fh)
        if a.workspace and "workspace" not in targs: targs["workspace"] = a.workspace
        out = api.test_theory(targs)
    elif a.action == "run": out = api.run_script("\n".join(a.args), a.workspace)
    elif a.action == "script":
        with open(a.args[0], encoding="utf-8") as fh: out = api.run_script(fh.read(), a.workspace)
    elif a.action == "preset":
        ov = dict(x.split("=", 1) for x in a.args[1:]); out = api.run_preset(a.args[0], ov, a.workspace)
    elif a.action == "presets": out = api.list_presets(a.args[0] if a.args else None)
    else: out = api.report(a.args[0] if a.args else None, 20, a.workspace)
    if a.json or a.action in ("presets",):
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str)); return 0 if out.get("ok") else 1
    if a.action == "report" and out.get("text"): print(out["text"]); return 0
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str)[:20000])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
