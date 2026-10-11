// SpinDoctor Qwerty 1.1.0 - SpinDoctor Qwerty for Letta Code: mod (6 tools + /spindoctor command)
// Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
// Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
// option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
//
// Letta Code mod (docs.letta.com/configuration/mods): the default export is the activation function. It registers six tools with
// letta.tools.register and one output-only command with letta.commands.register, each guarded by letta.capabilities, and returns
// a disposer. Each tool call runs the bundled stdlib-only Python engine once (`spindoctor_cli.py tool NAME`, JSON on stdin, one JSON
// line on stdout) in ctx.cwd. No events, no permission overlays, no providers, no network, nothing runs at activation.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const VERSION = "1.1.0";
// package layout (mods/ + skills/spindoctor-qwerty/), or a single mod file next to a spindoctor-qwerty-engine/ folder
const CLI_CANDIDATES = [path.resolve(HERE, "../skills/spindoctor-qwerty/scripts/spindoctor_cli.py"), path.resolve(HERE, "spindoctor-qwerty-engine/scripts/spindoctor_cli.py")];
export const ENGINE_CLI = process.env.SPINDOCTOR_QWERTY_CLI || CLI_CANDIDATES.find((p) => existsSync(p)) || CLI_CANDIDATES[0];

// Python: $SPINDOCTOR_PYTHON (a command, may include arguments such as "py -3"), else the first of these that runs Python 3.
const PY_CANDIDATES = process.platform === "win32" ? [["py", "-3"], ["python"], ["python3"]] : [["python3"], ["python"]];
let PY = null;
export function python() {
  if (PY) return PY;
  if (process.env.SPINDOCTOR_PYTHON) return (PY = process.env.SPINDOCTOR_PYTHON.trim().split(/\s+/));
  for (const c of PY_CANDIDATES) {
    try {
      const r = spawnSync(c[0], [...c.slice(1), "-c", "import sys; print(sys.version_info[0])"], { encoding: "utf8", windowsHide: true, timeout: 20000 });
      if (r.status === 0 && String(r.stdout).trim() === "3") return (PY = c);
    } catch { /* next */ }
  }
  return (PY = PY_CANDIDATES[0]);
}

const S = (d) => ({ type: "string", description: d });
const WS = S("Optional workspace folder (absolute path); default ~/spindoctor-workspace");
const STRS = (d) => ({ type: "array", items: { type: "string" }, description: d });
// readOnly tools need no approval and may run in parallel; the others write reports and state, so Letta asks first (unless the
// session's permission mode allows it).
export const TOOL_DEFS = [
  { name: "spindoctor_functions", readOnly: true,
    description: "Return the in-chat Markdown table of every SpinDoctor function (Function | What it does | Command to type), grouped by family with runnable examples; section='presets' lists the 241 presets. Show it to the user verbatim on first use or when asked for help/functions. Read-only.",
    parameters: { type: "object", properties: { section: { type: "string", enum: ["commands", "gates", "tools", "presets", "all"], description: "Section (default: commands)" }, filter: S("Optional filter text") }, additionalProperties: false } },
  { name: "spindoctor_list_presets", readOnly: true,
    description: "List SpinDoctor presets (id, category, label, availability, commands); optional case-insensitive filter text. Read-only.",
    parameters: { type: "object", properties: { filter: S("Optional filter text, e.g. ghz") }, additionalProperties: false } },
  { name: "spindoctor_report", readOnly: true,
    description: "Show a SpinDoctor TXT report from the workspace, or list the newest reports when no name is given. Read-only.",
    parameters: { type: "object", properties: { name: S("Report file name; omit to list the newest"), limit: { type: "integer", description: "How many reports to list" }, workspace: WS }, additionalProperties: false } },
  { name: "spindoctor_run_script",
    description: "Run SpinDoctor q.* commands (one per line) in the persistent simulator workspace; returns results and TXT/JSON/CSV/PDF report paths. 1-298 logical qubits (59 per entangled factor). Classical FP64 simulation, not a quantum computer.",
    parameters: { type: "object", properties: { script: S("q.* commands, one per line"), workspace: WS }, required: ["script"], additionalProperties: false } },
  { name: "spindoctor_run_preset",
    description: "Run one of the 241 built-in SpinDoctor presets (qc-001..qc-241) with optional name=value overrides; returns per-step results and report paths.",
    parameters: { type: "object", properties: { preset_id: S("Preset id, e.g. qc-061"), overrides: { type: "object", additionalProperties: { type: "string" }, description: "Optional overrides (shots, basis, qubits, input, angle)" }, workspace: WS }, required: ["preset_id"], additionalProperties: false } },
  { name: "spindoctor_test_theory",
    description: "Test a theory with the SpinDoctor simulator and write a TXT+JSON+PDF theory report (hypothesis, script, raw results, verdict supported/not supported/inconclusive, limits). source='file' (path of a txt/md/pdf/py/json/csv/q file; relative paths resolve against the working directory), 'text' (pasted), or 'chat' (confirmed theory summary from the conversation + quoted excerpts and/or an exported chat transcript path). action='extract' reads the source; action='run' needs hypothesis, prediction, script and checks.",
    parameters: { type: "object", properties: { action: { type: "string", enum: ["extract", "run"] }, source: { type: "string", enum: ["file", "text", "chat"] }, path: S("Theory file or chat export"), text: S("Pasted theory text or confirmed chat summary"),
      excerpts: STRS("Quoted chat excerpts"), hypothesis: S("Hypothesis"), prediction: S("Measurable prediction"), checks: { type: "array", items: { type: "object" }, description: "Checks, e.g. {kind: probability, outcome: '11', expected: 0.5, tolerance: 0.05}" },
      script: S("q.* script, one command per line"), assumptions: STRS("Assumptions"), variables: STRS("Variables"), title: S("Report title"), workspace: WS, isolate: { type: "boolean", description: "Run in a fresh simulator state" } }, additionalProperties: false } },
];

export function callEngine(name, args, cwd, signal, timeoutMs = 600000) {
  return new Promise((resolve) => {
    let out = "", err = "", child;
    const [cmd, ...pre] = python();
    try {
      child = spawn(cmd, [...pre, ENGINE_CLI, "tool", name], { cwd: cwd && existsSync(cwd) ? cwd : undefined, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
        env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" } });
    } catch (e) { resolve({ ok: false, error: "Could not start Python (" + cmd + "): " + e.message + ". Set SPINDOCTOR_PYTHON." }); return; }
    const timer = setTimeout(() => child.kill(), timeoutMs);
    const onAbort = () => child.kill();
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    child.stdout.on("data", (d) => { out += d; });
    child.stderr.on("data", (d) => { err += d; });
    child.on("error", (e) => { clearTimeout(timer); resolve({ ok: false, error: "Python 3.8+ is required (set SPINDOCTOR_PYTHON): " + e.message }); });
    child.on("close", () => {
      clearTimeout(timer); if (signal) signal.removeEventListener("abort", onAbort);
      const line = out.trim().split("\n").pop() || "";
      try { resolve(JSON.parse(line)); } catch { resolve({ ok: false, error: (err || out || "no output").slice(-2000) }); }
    });
    child.stdin.end(JSON.stringify(args || {}));
  });
}

export function asText(result) {
  if (result && result.ok && typeof result.markdown === "string") return result.markdown; // function table: show verbatim
  const s = JSON.stringify(result, null, 1);
  return s.length > 60000 ? s.slice(0, 60000) + "\n...[truncated; open the report files for full output]" : s;
}

export default function activate(letta) {
  const disposers = [];
  const caps = (letta && letta.capabilities) || {};
  const diag = (message) => { try { letta.diagnostics && letta.diagnostics.report({ message, severity: "error" }); } catch { /* host without diagnostics */ } };
  if (caps.tools) {
    for (const def of TOOL_DEFS) {
      disposers.push(letta.tools.register({
        name: def.name, description: def.description, parameters: def.parameters,
        requiresApproval: !def.readOnly, parallelSafe: !!def.readOnly,
        async run(ctx) {
          const result = await callEngine(def.name, (ctx && ctx.args) || {}, ctx && ctx.cwd, ctx && ctx.signal);
          if (!result.ok && /Python 3\.8\+ is required|Could not start Python/.test(String(result.error))) diag("SpinDoctor Qwerty: " + result.error);
          return result.ok ? asText(result) : { status: "error", content: asText(result) };
        },
      }));
    }
  }
  if (caps.commands) {
    disposers.push(letta.commands.register({
      id: "spindoctor",
      description: "Show the SpinDoctor function table (optional: commands | gates | tools | presets | all, or filter text)",
      args: "[section|filter]",
      async run(ctx) {
        const a = String((ctx && ctx.args) || "").trim();
        const sections = ["commands", "gates", "tools", "presets", "all"];
        const args = !a ? {} : sections.includes(a) ? { section: a } : { section: "all", filter: a };
        const r = await callEngine("spindoctor_functions", args, ctx && ctx.cwd);
        return { type: "output", output: r.ok ? r.markdown : asText(r) };
      },
    }));
  }
  return () => { for (const d of disposers.reverse()) { try { typeof d === "function" ? d() : d && d.dispose && d.dispose(); } catch { /* already gone */ } } };
}
