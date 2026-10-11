#!/usr/bin/env python3
# SpinDoctor Qwerty - end-to-end test through the host entry point (stdio MCP server)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Black-box E2E test: launches the plugin's MCP server exactly as the host would (command + args), then
checks tools, the function table, one script per command family, a preset run compared with the updated
SpinDoctor 3.1.2 reference, q.folder on a mixed folder, theory testing from a file, a chat summary and a
chat transcript, and TXT+PDF report validity.  Standard library only (Python 3.8+).

usage: python3 e2e_mcp.py --server "<command>" [args...] [--examples DIR] [--out e2e.json]
"""
import json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "reference", "ref_qc001_025.json")
# Documented engine differences (CPU-only reference instead of OpenCL GPU fields; tranche checkpoint text; state file name).
WORK = ("actualPreparedQubits", "executedCircuitInstructions", "queryCount", "backendGateApplications", "actualAmplitudeWrites",
        "actualTensorProducts", "exactCPReductions", "coherentOutputExecutions", "uniformDraws")
KNOWN = {"qc-006", "qc-008", "qc-009", "qc-016", "qc-019"}
VOL = set("""elapsedMs id jobId receivedUtc completedUtc status totalMs cpuMs gpuMs referenceMs gpuKernelMs ruleCheckMs
processPrivateBytes managedHeapBytes availablePhysicalBytes totalPhysicalBytes usablePeakBytes maximumPlannedDenseQubits
fitsCurrentPlan requiredPeakBytes gpuAvailable gpuDevice gpuError comparisonBackend gpuStates actualGpuStates job reportSnapshot
programSnapshot capturedUtc coherentOutputStatus snapshot statusSnapshot productVersion cartridge numericBackend record""".split())


class Server(object):
    def __init__(self, cmd, env):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.n = 0

    def rpc(self, method, params=None, timeout=900):
        self.n += 1
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line: raise RuntimeError("server closed: " + self.p.stderr.read().decode("utf-8", "replace")[-800:])
        msg = json.loads(line.decode("utf-8"))
        if "error" in msg: raise RuntimeError(str(msg["error"]))
        return msg["result"]

    def tool(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r.get("structuredContent") or {}, r

    def close(self):
        try: self.p.stdin.close(); self.p.wait(10)
        except Exception: self.p.kill()


def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items() if k not in VOL}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, float) and o == int(o) and abs(o) < 2 ** 53: return int(o)
    return o


def diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a or k not in b: out.append(path + "." + k + (" missing" if k not in b else " extra")); continue
            diff(a[k], b[k], path + "." + k, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): out.append(path + " len"); return
        for x, y in zip(a, b): diff(x, y, path + "[]", out)
    elif isinstance(a, float) or isinstance(b, float):
        try:
            if abs(float(a) - float(b)) > 1e-9 * max(1.0, abs(float(a)), abs(float(b))): out.append(path)
        except (TypeError, ValueError): out.append(path)
    elif a != b: out.append(path)


def pdf_ok(path):
    try: b = open(path, "rb").read()
    except OSError as e: return False, str(e)
    if not b.startswith(b"%PDF-1.") or b"%%EOF" not in b[-1024:] or b"startxref" not in b or b"xref" not in b: return False, "structure"
    pages = len(re.findall(rb"/Type\s*/Page[^s]", b))
    if pages < 1: return False, "no pages"
    m = re.search(rb"startxref\s+(\d+)", b[-256:])
    if not m or not b[int(m.group(1)):int(m.group(1)) + 4] == b"xref": return False, "bad startxref offset"
    if shutil.which("pdftotext"):
        t = subprocess.run(["pdftotext", "-q", path, "-"], stdout=subprocess.PIPE).stdout.decode("utf-8", "replace")
        if "SpinDoctor" not in t and "SPINDOCTOR" not in t: return False, "pdftotext: no SpinDoctor text"
    return True, "%d page(s)" % pages


def main():
    a = sys.argv[1:]
    if "--server" not in a: print(__doc__); return 2
    i = a.index("--server"); rest = a[i + 1:]; stop = [j for j, x in enumerate(rest) if x in ("--examples", "--out")]
    cmd = rest[:stop[0]] if stop else rest
    opt = dict(zip(rest[stop[0]::2], rest[stop[0] + 1::2])) if stop else {}
    examples = opt.get("--examples"); outp = opt.get("--out", "e2e_results.json")
    tmp = tempfile.mkdtemp(prefix="sdq_e2e_"); res = []; pdfs = []; t0 = time.time()

    def T(name, ok, detail=""):
        res.append({"check": name, "pass": bool(ok), "detail": str(detail)[:400]}); print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  -- " + str(detail)[:300])); sys.stdout.flush()

    def collect(o):
        if isinstance(o, dict):
            for v in o.values(): collect(v)
        elif isinstance(o, list):
            for v in o: collect(v)
        elif isinstance(o, str) and o.lower().endswith(".pdf") and os.path.isabs(o): pdfs.append(o)

    env = dict(os.environ, SPINDOCTOR_WORKSPACE=os.path.join(tmp, "ws"))
    env.pop("SPINDOCTOR_MEASUREMENT_SEED", None); env.pop("SPINDOCTOR_FIELD_SEED", None)
    s = Server(cmd, env)
    init = s.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "spindoctor-e2e", "version": "1"}})
    s.p.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'); s.p.stdin.flush()
    T("initialize (server %s %s)" % (init["serverInfo"]["name"], init["serverInfo"]["version"]), init["serverInfo"]["version"] == "1.1.0", init["serverInfo"])
    names = sorted(t["name"] for t in s.rpc("tools/list")["tools"])
    T("tools/list exposes the 6 tools", names == sorted(["spindoctor_run_script", "spindoctor_run_preset", "spindoctor_list_presets", "spindoctor_report", "spindoctor_functions", "spindoctor_test_theory"]), names)

    out, raw = s.tool("spindoctor_functions", {})
    md = raw["content"][0]["text"]
    fam = re.split(r"^#{2,3} ", md, flags=re.M)
    T("function table (Markdown, %d sections, 298-qubit limits listed)" % len(fam), md.count("| Function |") >= 1 and len(fam) >= 15 and "298" in md, md[:200])
    pres, _ = s.tool("spindoctor_list_presets", {})
    T("241 presets listed", pres.get("count") == 241 or len(pres.get("presets", [])) == 241, {k: pres.get(k) for k in ("count", "error")})

    # one script per command family (examples straight from the table)
    fams = 0; failed = []; bytitle = {}
    for sec in fam[1:]:
        title = sec.split("\n", 1)[0].strip()
        cmds = [m.group(1) for m in re.finditer(r"\|\s*`(q\.[^`]+)`\s*\|\s*$", sec, re.M)]
        if not cmds: continue
        bytitle[title.split(" ", 1)[0]] = cmds
        pre = []
        if "first build and run a circuit" in title:  # follow the table's own instruction
            pre = ["q.circuit new bell 2", "q.circuit add h 0", "q.circuit add cx 0 1", "q.circuit run shots 1000 basis z"]
        if title.startswith("Gate set"): pre = ["q.circuit new gates 8"]  # gates need a selected circuit
        fams += 1
        o, _ = s.tool("spindoctor_run_script", {"script": "\n".join(pre + cmds), "workspace": os.path.join(tmp, "fam%02d" % fams)})
        bad = [r["command"] + ": " + str(r["error"]) for r in o.get("results", []) if not r["ok"]]
        if not o.get("results") or bad: failed.append((title, bad[:3] or o.get("error")))
        collect(o)
    T("one script per command family (%d families, every table example)" % fams, fams >= 12 and not failed, failed)

    # wide 298-qubit circuit (3.1.2-298)
    o, _ = s.tool("spindoctor_run_script", {"script": "q.circuit new wide_e2e 298\nq.circuit add h 297\nq.circuit add cx 297 0\nq.circuit add mcx7 0 1 2 3 4 5 6 7\nq.circuit run shots 256 basis z\nq.circuit result", "workspace": os.path.join(tmp, "wide")})
    rr = (o.get("results") or [{}])[-1].get("result") or {}
    T("298-qubit circuit with mcx7 (prepared-factor-Born-Z)", o.get("ok") and rr.get("samplingMode") == "prepared-factor-Born-Z" and set(h["bitstring"][0] + h["bitstring"][-1] for h in rr.get("histogram", [])) <= {"00", "11"}, rr.get("samplingMode") or o.get("error"))

    # q.folder on a small mixed folder
    fd = os.path.join(tmp, "mixed"); os.makedirs(fd)
    open(os.path.join(fd, "a_steps.txt"), "w").write("# SPINDOCTOR-SEQUENCE\nq.circuit new fa 2\nq.circuit add h 0\nq.circuit add cx 0 1\nq.circuit run shots 64 basis z\n")
    open(os.path.join(fd, "b_math.csv"), "w").write("command\n\"q.math normalize amplitudes=[1,i]\"\n")
    json.dump({"name": "fc", "qubits": 2, "gates": [{"name": "x", "qubits": [1]}], "shots": 32}, open(os.path.join(fd, "c_circuit.json"), "w"))
    open(os.path.join(fd, "d_ghz.qasm"), "w").write('OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\nh q[0];\ncx q[0],q[1];\ncx q[1],q[2];\nmeasure q -> c;\n')
    open(os.path.join(fd, "notes.md"), "w").write("# not a command file\n")
    o, _ = s.tool("spindoctor_run_script", {"script": 'q.folder run path="%s" downloads=false verify=false' % fd.replace("\\", "/"), "workspace": os.path.join(tmp, "folder")})
    r0 = (o.get("results") or [{}])[0]; job = (r0.get("result") or {}).get("job") or r0.get("result") or {}
    T("q.folder on mixed .txt/.csv/.json/.qasm folder (+ .md skipped)", o.get("ok") and job.get("phase") == "completed" and job.get("skippedFiles") == ["notes.md"] and len(job.get("files", [])) == 4,
      {k: job.get(k) for k in ("phase", "error", "skippedFiles")} if job else o.get("error"))
    collect(o)

    # theory testing: file, chat summary + excerpts, chat transcript file
    if examples and os.path.isdir(examples):
        th = lambda **k: s.tool("spindoctor_test_theory", dict(k, workspace=os.path.join(tmp, "theory")))[0]
        P1 = lambda out_, exp, tol=0.05: {"kind": "probability", "outcome": out_, "expected": exp, "tolerance": tol}
        r = th(source="file", path=os.path.join(examples, "hadamard_theory.txt"), hypothesis="H|0> gives 50/50", prediction="P(1)=0.5", checks=[P1("1", 0.5, 0.04)])
        T("theory from a file -> supported, TXT+PDF report", r.get("verdict") == "supported" and any(p.endswith(".pdf") for p in r.get("reports", [])), r.get("error") or r.get("verdict"))
        collect(r)
        script = "q.circuit new g2b 2\nq.circuit add h 0\nq.circuit add h 1\nq.circuit add cz 0 1\nq.circuit add h 1\nq.circuit run shots 4000 basis z"
        r = th(source="chat", text="Theory: H on both qubits, CZ, then H on qubit 1 gives a Bell state. Prediction: only 00 and 11, ~0.5 each.",
               excerpts=["User: if I put a Hadamard on both qubits and then a CZ, do I get an entangled state?", "Assistant: Yes, a graph state."],
               hypothesis="H-H-CZ-H(1) prepares a Bell state", prediction="only 00/11", script=script, checks=[P1("00", 0.5), P1("11", 0.5)])
        T("theory from a chat summary + quoted excerpts -> supported", r.get("verdict") == "supported" and r.get("excerptsRecorded") == 2, r.get("error") or r.get("verdict"))
        collect(r)
        r = th(source="chat", path=os.path.join(examples, "chat_transcript.md"), text="Bell theory from the exported chat", hypothesis="Bell state", prediction="only 00/11",
               script=script.replace("g2b", "g2c"), checks=[P1("00", 0.5), P1("11", 0.5)])
        T("theory from an exported chat transcript -> supported", r.get("verdict") == "supported", r.get("error") or r.get("verdict"))
        collect(r)
    else:
        T("theory examples folder found", False, examples)
    s.close()

    # preset run vs the updated SpinDoctor 3.1.2 reference (fresh workspace, reference seeds)
    ref = json.load(open(REF, encoding="utf-8"))
    env2 = dict(env, SPINDOCTOR_WORKSPACE=os.path.join(tmp, "presets"), SPINDOCTOR_MEASUREMENT_SEED=ref["seeds"]["measurementSeed"], SPINDOCTOR_FIELD_SEED=ref["seeds"]["fieldSeed"])
    s2 = Server(cmd, env2); s2.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "e2e", "version": "1"}})
    same = known = 0; bad = []
    for pid in sorted(ref["presets"]):
        o, _ = s2.tool("spindoctor_run_preset", {"preset_id": pid})
        collect(o)
        steps = {st["index"]: st for st in o.get("steps", [])}; d = []
        for k, rs in ref["presets"][pid].items():
            st = steps.get(int(k))
            if st is None or bool(st["ok"]) != bool(rs["ok"]): d.append("step %s ok" % k); continue
            dd = []; diff(clean(rs["result"]), clean(st.get("result")), "", dd)
            # work-accounting counters differ by design (documented in the parity report); everything else must match
            d += [x for x in dd if not (x.rsplit(".", 1)[-1].split()[0] in WORK and (".counts." in x or ".lifetime." in x))]
        if pid in KNOWN: known += 1
        elif d: bad.append((pid, d[:4]))
        else: same += 1
    s2.close()
    T("presets qc-001..qc-025 match the updated 3.1.2 reference (%d identical, %d documented differences)" % (same, known), not bad, bad)

    # reports
    pdfs = sorted(set(p for p in pdfs if os.path.exists(p)))
    badpdf = [(p, why) for p in pdfs for ok, why in [pdf_ok(p)] if not ok]
    txt = [p[:-4] + ".txt" for p in pdfs if os.path.exists(p[:-4] + ".txt") and os.path.getsize(p[:-4] + ".txt") > 0]
    T("TXT+PDF reports valid (%d PDFs, %d TXT twins)" % (len(pdfs), len(txt)), len(pdfs) >= 10 and not badpdf and len(txt) >= len(pdfs) * 0.9, badpdf[:3])

    summary = {"passed": sum(r["pass"] for r in res), "total": len(res), "seconds": round(time.time() - t0, 1), "python": sys.version.split()[0], "checks": res}
    json.dump(summary, open(outp, "w"), indent=1)
    print("SUMMARY %d/%d passed in %.1fs" % (summary["passed"], summary["total"], summary["seconds"]))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
