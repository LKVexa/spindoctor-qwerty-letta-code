#!/usr/bin/env python3
# SpinDoctor Qwerty 1.1.0 - host check for the Letta Code mod package (static checks + the real Letta Code CLI)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Usage: python3 tests/letta_host_check.py [--letta PATH_TO_letta] [--source DIR|git:github.com/OWNER/REPO] [--out FILE]

Static: package.json#letta manifest, SKILL.md, GPL headers, tests/mod_smoke.mjs, every CLI command in SKILL.md, tools/install_skill.py.
Real host (needs the `letta` CLI from npm @letta-ai/letta-code; no account): a throwaway HOME, local backend, and an
"openai-compatible" provider pointing at tests/stub_llm.py (a scripted local model, no network, no key). Then: `letta install SOURCE`,
headless runs where the stub calls all 6 tools, approval behaviour under --permission-mode standard, /spindoctor typed into the TUI
(pseudo-terminal), the skill + Bash fallback, `letta mods disable/enable/remove`, --no-mods, and the shared end-to-end suite through
the installed package's engine. What it cannot show: a real model choosing tools, Letta Cloud, the Desktop app, Windows/macOS."""
import json, os, re, shutil, signal, socket, subprocess, sys, tempfile, time
sys.dont_write_bytecode = True; os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TOOLS = ["spindoctor_functions", "spindoctor_list_presets", "spindoctor_report", "spindoctor_run_preset", "spindoctor_run_script", "spindoctor_test_theory"]
CAP_IDS = {"tools", "commands", "providers", "permissions", "events.lifecycle", "events.turns", "events.tools", "events.compact", "events.llm", "ui.panels"}
R = []
OK = lambda s: bool(re.search(r'"ok":\s*true', s or ""))


def T(name, ok, detail=""):
    R.append({"check": name, "pass": bool(ok), "detail": str(detail)[:600]})
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -- " + str(detail)[:500])); sys.stdout.flush()


def static():
    pj = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8")); m = pj.get("letta") or {}
    T("package.json#letta: manifestVersion 1, mod entries exist, known capabilities, GPL-3.0-or-later, version 1.1.0",
      m.get("manifestVersion") == 1 and m.get("mods") and all(os.path.isfile(os.path.join(ROOT, x)) and not x.startswith(("/", "..")) for x in m["mods"])
      and set(m.get("capabilities", [])) <= CAP_IDS and pj.get("license") == "GPL-3.0-or-later" and pj.get("version") == "1.1.0"
      and {"letta-package", "letta-mod"} <= set(pj.get("keywords", [])), m)
    src = [os.path.join(d, f) for d, _, fs in os.walk(ROOT) if ".git" not in d and "node_modules" not in d for f in fs if f.endswith((".py", ".mjs", ".js"))]
    bad = [x for x in src if "SPDX-License-Identifier: GPL-3.0-or-later" not in open(x, encoding="utf-8").read(2500)]
    T("every .py/.mjs file has a GPL-3.0-or-later SPDX header (%d files)" % len(src), not bad, bad[:3])
    sk = os.path.join(ROOT, "skills", "spindoctor-qwerty"); t = open(os.path.join(sk, "SKILL.md"), encoding="utf-8").read()
    fm = re.match(r"---\n(.*?)\n---\n", t, re.S)
    T("SKILL.md: frontmatter name/description, guardrail, mod tools + /spindoctor, no other host's variables",
      fm and "name: spindoctor-qwerty" in fm.group(1) and "description:" in fm.group(1) and "not a\nquantum computer" in t
      and "/spindoctor" in t and not re.search(r"\$\{[A-Z_]+\}", t), fm.group(1)[:200] if fm else t[:200])
    cmds = [ln.split("  #")[0].strip() for blk in re.findall(r"```bash\n(.*?)```", t, re.S) for ln in blk.splitlines() if ln.startswith("python3 scripts/")]
    ws = tempfile.mkdtemp(prefix="sdq_cli_"); bad = []
    for c in cmds:
        argv = c.split(" ", 2); rest = re.findall(r'"[^"]*"|\S+', argv[2])
        r = subprocess.run([sys.executable, argv[1], "--workspace", ws] + [x.strip('"') for x in rest], cwd=sk, capture_output=True, timeout=300)
        if r.returncode: bad.append((c, r.stderr[-200:]))
    T("Bash fallback: every CLI command in SKILL.md runs as written from the skill folder (%d commands, bundled files only)" % len(cmds), cmds and not bad, bad)
    shutil.rmtree(ws, ignore_errors=True)
    r = subprocess.run(["node", os.path.join(HERE, "mod_smoke.mjs")], capture_output=True, text=True, timeout=600, cwd=ROOT)
    try: d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception: d = {"ok": False, "checks": [], "err": r.stderr[-300:]}
    T("tests/mod_smoke.mjs (fake host: capability guards, approval flags, all tools, /spindoctor, disposer): %d checks" % len(d["checks"]), d["ok"],
      [c for c in d["checks"] if not c["ok"]] or d.get("err"))
    home = tempfile.mkdtemp(prefix="sdq_skill_"); env = dict(os.environ, HOME=home, USERPROFILE=home); inst = os.path.join(ROOT, "tools", "install_skill.py")
    a = subprocess.run([sys.executable, inst], env=env, capture_output=True, text=True)
    g = os.path.join(home, ".letta", "skills", "spindoctor-qwerty", "SKILL.md")
    b = subprocess.run([sys.executable, inst, "--project", os.path.join(home, "proj")], env=env, capture_output=True, text=True)
    p = os.path.join(home, "proj", ".agents", "skills", "spindoctor-qwerty", "SKILL.md")
    ok1 = os.path.isfile(g) and os.path.isfile(p)
    subprocess.run([sys.executable, inst, "--uninstall"], env=env, capture_output=True)
    T("tools/install_skill.py: global (~/.letta/skills) and --project (.agents/skills) installs, --uninstall removes", ok1 and not os.path.exists(g), (a.stdout, b.stdout))
    shutil.rmtree(home, ignore_errors=True)


class Host:
    """A throwaway Letta Code home: local backend + openai-compatible provider -> the scripted stub."""
    def __init__(self, letta):
        self.letta = letta; self.home = tempfile.mkdtemp(prefix="sdq_letta_"); self.proj = os.path.join(self.home, "proj"); os.makedirs(self.proj)
        self.env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, PWD=self.proj, PYTHONDONTWRITEBYTECODE="1", NO_COLOR="1")
        for k in [k for k in self.env if k.startswith("LETTA_")]: self.env.pop(k)
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.stub = None; self.n = 0
    def L(self, *args, timeout=240, cwd=None):
        return subprocess.run([self.letta] + list(args), env=self.env, cwd=cwd or self.proj, capture_output=True, text=True, timeout=timeout)
    def start_stub(self, steps):
        self.stop_stub(); self.n += 1
        sp = os.path.join(self.home, "steps%d.json" % self.n); self.log = os.path.join(self.home, "log%d.jsonl" % self.n)
        json.dump(steps, open(sp, "w"))
        self.stub = subprocess.Popen([sys.executable, os.path.join(HERE, "stub_llm.py"), str(self.port), self.log, sp])
        for _ in range(50):
            try: socket.create_connection(("127.0.0.1", self.port), 0.2).close(); return
            except OSError: time.sleep(0.1)
    def stop_stub(self):
        if self.stub: self.stub.terminate(); self.stub.wait(); self.stub = None
    def records(self):
        return [json.loads(l) for l in open(self.log)] if os.path.exists(self.log) else []
    def run(self, steps, *extra, prompt="go"):
        self.start_stub(steps)
        r = self.L("-p", prompt, "--new-agent", "-m", "openai-compatible/stub", "--backend", "local", "--output-format", "stream-json", *extra)
        ev = []
        for line in r.stdout.splitlines():
            try: ev.append(json.loads(line))
            except ValueError: pass
        returns = [e for e in ev if e.get("message_type") == "tool_return_message"]
        return r, ev, returns
    def close(self):
        self.stop_stub(); shutil.rmtree(self.home, ignore_errors=True)


def real(letta, source):
    if not letta or not (os.path.isfile(letta) and os.access(letta, os.X_OK)):
        T("real Letta Code CLI available (npm @letta-ai/letta-code; pass --letta)", False, letta); return
    h = Host(letta)
    try:
        v = h.L("--version").stdout.strip(); T("Letta Code CLI runs without an account: " + v, "Letta Code" in v or re.match(r"\d", v), v)
        h.start_stub([{"text": "hi"}])
        c = h.L("connect", "openai-compatible", "--base-url", "http://127.0.0.1:%d/v1" % h.port, "--api-key", "local-stub", "--backend", "local")
        b = h.L("backend", "local")
        T("local backend + openai-compatible provider -> local stub (no login, no key)", "Connected" in c.stdout and b.returncode == 0, c.stdout + c.stderr)
        ins = h.L("install", source, timeout=600)
        ls = h.L("mods", "list").stdout
        T("letta install %s -> package enabled with tools, commands" % ("<local folder>" if os.path.isdir(source) else source),
          ins.returncode == 0 and re.search(r"enabled\s+\S*spindoctor-qwerty-letta-code\S*\s+tools, commands", ls), (ins.stdout + ins.stderr)[-300:] + ls)
        pk = json.load(open(os.path.join(h.home, ".letta", "mods", "packages.json")))["packages"]
        root = os.path.join(h.home, ".letta", "mods", pk[0]["root"]) if pk else ""
        T("installed package carries the engine + skill (self-contained)", root and os.path.isfile(os.path.join(root, "skills", "spindoctor-qwerty", "scripts", "spindoctor_cli.py")), root)
        before = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs) if root else []
        open(os.path.join(h.proj, "my_theory.txt"), "w").write("Theory: a Hadamard on |0> gives 0 and 1 with equal probability.\n")
        steps = [{"tool": "spindoctor_functions", "args": {}},
                 {"tool": "spindoctor_list_presets", "args": {"filter": "ghz"}},
                 {"tool": "spindoctor_run_script", "args": {"script": "q.circuit new bell 2\nq.circuit add h 0\nq.circuit add cx 0 1\nq.circuit run shots 1000 basis z"}},
                 {"tool": "spindoctor_run_preset", "args": {"preset_id": "qc-001"}},
                 {"tool": "spindoctor_report", "args": {}},
                 {"tool": "spindoctor_run_script", "args": {"script": "q.circuit new big 298\nq.circuit add h 0\nq.circuit add mcx7 0 1 2 3 4 5 6 297\nq.circuit run shots 64 basis z"}},
                 {"tool": "spindoctor_run_script", "args": {"script": "q.circuit new toobig 300"}},
                 {"tool": "spindoctor_test_theory", "args": {"action": "extract", "source": "file", "path": "my_theory.txt"}},
                 {"tool": "spindoctor_test_theory", "args": {"action": "run", "source": "chat",
                  "text": "From our chat: H then CX makes a Bell state, so 00 and 11 each appear about half the time.",
                  "excerpts": ["User: does H then CNOT give 50/50 on 00 and 11?", "Assistant: yes, that is a Bell state."],
                  "hypothesis": "H(0) then CX(0,1) gives P(00) = P(11) = 0.5", "prediction": "P(11) = 0.5 +/- 0.05 over 4000 shots",
                  "script": "q.circuit new bt 2\nq.circuit add h 0\nq.circuit add cx 0 1\nq.circuit run shots 4000 basis z",
                  "checks": [{"kind": "probability", "outcome": "11", "expected": 0.5, "tolerance": 0.05}]}},
                 {"text": "done"}]
        r, ev, rets = h.run(steps)
        recs = h.records(); offered = recs[0]["tools"] if recs else []
        T("the model is offered the 6 mod tools alongside Letta's own", all(t in offered for t in TOOLS), offered)
        sch = recs[0]["schemas"] if recs else {}
        T("tool schemas reach the model as registered (closed objects; preset_id/script required)",
          sch.get("spindoctor_run_preset", {}).get("required") == ["preset_id"] and sch.get("spindoctor_run_script", {}).get("required") == ["script"]
          and all(sch.get(t, {}).get("additionalProperties") is False for t in TOOLS), {k: v.get("required") for k, v in sch.items()})
        got = [x.get("tool_return", "") for x in rets]; st = [x.get("status") for x in rets]
        T("9 tool calls returned (headless, default permission mode)", len(got) == 9, (len(got), r.stderr[-300:]))
        if len(got) == 9:
            T("spindoctor_functions: the Markdown function table, verbatim", "| Function | What it does | Command to type |" in got[0], got[0][:150])
            T("spindoctor_list_presets ghz", OK(got[1]) and "ghz" in got[1].lower(), got[1][:150])
            T("spindoctor_run_script: Bell ok, reports under ~/spindoctor-workspace", OK(got[2]) and os.path.join(h.home, "spindoctor-workspace") in got[2], got[2][:200])
            T("spindoctor_run_preset qc-001", OK(got[3]) and "qc-001" in got[3], got[3][:150])
            T("spindoctor_report lists the newest reports", OK(got[4]) and ".txt" in got[4], got[4][:150])
            T("298-qubit wide register with mcx7 runs (3.1.2 parity)", OK(got[5]), got[5][:200])
            T("300 qubits -> error status, 'outside the supported range'", st[6] == "error" and "outside the supported range" in got[6], (st[6], got[6][:200]))
            T("theory extract: relative path resolves against the session's working directory (ctx.cwd)", OK(got[7]) and os.path.join(h.proj, "my_theory.txt") in got[7], got[7][:250])
            pdf = re.findall(r'"([^"]+theory[^"]*\.pdf)"', got[8])
            T("spindoctor_test_theory from the chat: supported, 2 excerpts, valid PDF", '"verdict": "supported"' in got[8] and '"excerptsRecorded": 2' in got[8]
              and pdf and open(pdf[0], "rb").read(5) == b"%PDF-", got[8][:300])
        res = [e for e in ev if e.get("type") == "result"]
        T("turn finishes with the model's final answer", res and res[-1].get("result") == "done", res[-1:] or r.stderr[-300:])
        r, ev, rets = h.run([{"tool": "spindoctor_list_presets", "args": {"filter": "bell"}}, {"tool": "spindoctor_run_preset", "args": {"preset_id": "qc-002"}}, {"text": "ok"}],
                            "--permission-mode", "standard")
        st = [(x.get("status"), x.get("tool_return", "")[:90]) for x in rets]
        T("--permission-mode standard: read-only tool runs, report-writing tool needs approval (denied headless)",
          len(st) == 2 and st[0][0] == "success" and st[1][0] == "error" and "requires approval" in st[1][1], st)
        tui = os.path.join(h.home, "tui.txt"); h.start_stub([{"text": "ok"}])
        subprocess.run([sys.executable, os.path.join(HERE, "tui_probe.py"), tui, "/spindoctor gates", "--", letta, "--new-agent", "-m", "openai-compatible/stub", "--backend", "local"],
                       env=h.env, cwd=h.proj, timeout=120, capture_output=True)
        s = open(tui, "rb").read().decode("utf-8", "replace") if os.path.exists(tui) else ""
        T("/spindoctor gates typed into the real TUI prints the gate table (no model call)", "Gate set" in s and re.search(r"gate h\s+Append gate h\s+q\.circuit add h 0", s)
          and not h.records(), s[-400:])
        subprocess.run([sys.executable, os.path.join(root, "tools", "install_skill.py")], env=h.env, capture_output=True, timeout=60)
        r, ev, rets = h.run([{"tool": "Skill", "args": {"skill": "spindoctor-qwerty"}},
                             {"tool": "Bash", "args": {"command": "cd $SKILLDIR && python3 scripts/spindoctor_cli.py presets ghz", "description": "List GHZ presets"}}, {"text": "ok"}])
        recs = h.records(); sysmsg = json.dumps(recs[0]["system"]) if recs else ""
        T("skill installed with the package's tools/install_skill.py is listed in available_skills", "`spindoctor-qwerty`" in sysmsg, sysmsg[:200])
        out = rets[-1].get("tool_return", "") if rets else ""
        T("Skill loads SKILL.md, then the Bash fallback runs the CLI from the skill folder", len(rets) == 2 and "qc-097" in out, [x.get("tool_return", "")[:150] for x in rets])
        after = sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs) if root else []
        # Letta itself keeps a loader copy of each entry next to it (mods/.letta-mod-<name>-<hash>.mjs); that is the host's, not ours
        hostcopy = lambda xs: [x for x in xs if not os.path.basename(x).startswith(".letta-mod-")]
        T("installed package folder unchanged by tool use (no __pycache__, reports outside; Letta's own .letta-mod-* loader copy ignored)",
          hostcopy(before) == hostcopy(after) and not any("__pycache__" in x for x in after), set(after) ^ set(before))
        r, ev, rets = h.run([{"text": "ok"}], "--no-mods"); off = h.records()[0]["tools"] if h.records() else ["?"]
        T("--no-mods: no SpinDoctor tools offered", not any(t in off for t in TOOLS), off)
        spec = re.search(r"(\S*spindoctor-qwerty-letta-code)", h.L("mods", "list").stdout).group(1)
        h.L("mods", "disable", spec); r, ev, rets = h.run([{"text": "ok"}]); off1 = h.records()[0]["tools"] if h.records() else ["?"]
        h.L("mods", "enable", spec); r, ev, rets = h.run([{"text": "ok"}]); off2 = h.records()[0]["tools"] if h.records() else []
        T("letta mods disable hides the tools, enable brings them back", not any(t in off1 for t in TOOLS) and all(t in off2 for t in TOOLS), (spec, off1[:3]))
        e2e = os.path.join(HERE, "e2e_results.json")
        rr = subprocess.run([sys.executable, os.path.join(HERE, "e2e_mcp.py"), "--server", sys.executable, os.path.join(root, "skills", "spindoctor-qwerty", "scripts", "spindoctor_mcp.py"),
                             "--examples", os.path.join(root, "skills", "spindoctor-qwerty", "examples", "theory"), "--out", e2e], env=h.env, cwd=h.proj, capture_output=True, text=True, timeout=3600)
        last = [l for l in rr.stdout.splitlines() if l.strip()][-1:] or [""]
        T("shared end-to-end suite through the installed package's engine: " + last[0][:60], rr.returncode == 0, rr.stdout[-400:])
        rm = h.L("mods", "remove", spec); ls = h.L("mods", "list").stdout
        T("letta mods remove uninstalls the package", rm.returncode == 0 and "spindoctor-qwerty-letta-code" not in ls and not os.path.exists(root), ls)
    finally:
        h.close()


def main():
    a = sys.argv[1:]; opt = dict(zip(a[::2], a[1::2]))
    letta = opt.get("--letta") or shutil.which("letta")
    static(); real(letta, opt.get("--source", ROOT))
    v = ""
    try: v = subprocess.run([letta, "--version"], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception: pass
    json.dump({"python": sys.version.split()[0], "host": "real Letta Code CLI (%s), local backend, scripted local stub model" % v, "checks": R},
              open(opt.get("--out", os.path.join(HERE, "host_check.json")), "w"), indent=1)
    n = sum(r["pass"] for r in R); print("%d/%d passed" % (n, len(R))); return 0 if n == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
