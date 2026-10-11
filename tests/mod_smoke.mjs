// SpinDoctor Qwerty 1.1.0 - mod smoke test without Letta Code (fake `letta` host object)
// Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
// SPDX-License-Identifier: GPL-3.0-or-later
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
// Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
// option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
// Usage: node tests/mod_smoke.mjs   (from the repo root; prints one JSON line {ok, checks})
import path from "node:path";
import os from "node:os";
import fs from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const mod = await import(pathToFileURL(path.join(ROOT, "mods/spindoctor-qwerty.mjs")).href);
const checks = []; const ck = (name, ok, detail = "") => checks.push({ name, ok: !!ok, detail: String(detail).slice(0, 200) });
function host(caps) {
  const tools = new Map(), cmds = new Map(), diags = [];
  const reg = (m) => (d) => { m.set(d.name || d.id, d); return () => m.delete(d.name || d.id); };
  return { tools, cmds, diags, letta: { capabilities: caps, tools: { register: reg(tools) }, commands: { register: reg(cmds) }, diagnostics: { report: (x) => diags.push(x) } } };
}
// 1. no capabilities -> nothing registered, no throw
{ const h = host({}); const d = mod.default(h.letta); ck("no capabilities: nothing registered", h.tools.size === 0 && h.cmds.size === 0 && typeof d === "function"); }
// 2. commands only
{ const h = host({ commands: true }); mod.default(h.letta); ck("commands only: /spindoctor, no tools", h.cmds.has("spindoctor") && h.tools.size === 0); }
// 3. full
const h = host({ tools: true, commands: true }); const dispose = mod.default(h.letta);
const names = [...h.tools.keys()].sort();
ck("6 tools registered", names.join() === "spindoctor_functions,spindoctor_list_presets,spindoctor_report,spindoctor_run_preset,spindoctor_run_script,spindoctor_test_theory", names);
const ro = ["spindoctor_functions", "spindoctor_list_presets", "spindoctor_report"];
ck("read-only tools: no approval, parallel-safe", ro.every((n) => h.tools.get(n).requiresApproval === false && h.tools.get(n).parallelSafe === true));
ck("writing tools: approval, not parallel", ["spindoctor_run_script", "spindoctor_run_preset", "spindoctor_test_theory"].every((n) => h.tools.get(n).requiresApproval === true && h.tools.get(n).parallelSafe === false));
ck("schemas are closed object schemas with descriptions", [...h.tools.values()].every((t) => t.parameters.type === "object" && t.parameters.additionalProperties === false && t.description.length > 40));
ck("engine CLI resolved inside the package", fs.existsSync(mod.ENGINE_CLI) && mod.ENGINE_CLI.startsWith(ROOT), mod.ENGINE_CLI);
const ws = fs.mkdtempSync(path.join(os.tmpdir(), "sdq-smoke-"));
const run = (n, args, cwd = ws) => h.tools.get(n).run({ args, cwd, signal: new AbortController().signal });
const t1 = await run("spindoctor_functions", { section: "gates" });
ck("functions returns the Markdown table verbatim", typeof t1 === "string" && t1.includes("| Function | What it does | Command to type |"), t1.slice(0, 80));
const t2 = await run("spindoctor_run_preset", { preset_id: "qc-001", workspace: ws });
ck("run_preset qc-001 completes with reports", typeof t2 === "string" && /"ok": true/.test(t2) && /qc-001\.txt/.test(t2), t2.slice(0, 120));
fs.writeFileSync(path.join(ws, "my.q"), "q.circuit new w 2\nq.circuit add h 0\nq.circuit add cx 0 1\nq.circuit run shots=64\n");
const t3 = await run("spindoctor_test_theory", { action: "extract", source: "file", path: "my.q" });
ck("relative theory path resolves against ctx.cwd", typeof t3 === "string" && /"ok": true/.test(t3), t3.slice(0, 160));
const t4 = await run("spindoctor_run_script", { script: "q.circuit new big 300", workspace: ws });
ck("300 qubits rejected as an error result", t4 && t4.status === "error" && /outside the supported range/.test(t4.content), JSON.stringify(t4).slice(0, 160));
const c1 = await h.cmds.get("spindoctor").run({ args: "presets", cwd: ws });
ck("/spindoctor presets -> output with qc-241", c1.type === "output" && c1.output.includes("qc-241"));
const c2 = await h.cmds.get("spindoctor").run({ args: "", cwd: ws });
ck("/spindoctor (no args) -> commands table", c2.type === "output" && c2.output.includes("| Function |"));
dispose();
ck("disposer unregisters everything", h.tools.size === 0 && h.cmds.size === 0);
fs.rmSync(ws, { recursive: true, force: true });
console.log(JSON.stringify({ ok: checks.every((c) => c.ok), checks }));
