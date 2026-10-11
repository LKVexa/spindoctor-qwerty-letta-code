# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""SpinDoctor Scripter Cartridge session: q.* dispatch, workspace persistence, presets/sequences
(3.1.2 auto-prune + ownership rules, q.folder, q.input, q.history) and per-command TXT/JSON/CSV/PDF reports."""
import datetime
import json
import os
import re
import secrets
import time
import uuid

from . import backend, register, reports
from .advanced import Advanced, supports as adv_supports, capabilities as adv_caps
from .calculators import Calculators, supports as calc_supports, capabilities as calc_caps
from .circuits import CircuitTerminal, check_name, program_hash, alias as gate_alias
from .netfmt import dumps, fmt_r
from .procedural import Grid, TrancheTerminal
from .inputs import InputManager
from . import folder as folder_mod
from . import history as history_mod

ENGINE_VERSION = "3.1.2"
CARTRIDGE_VERSION = "1.1.0"
ENGINE_UPDATE_ID = "3.1.2-298-20261010"  # parity target: SpinDoctor 3.1.2 with the 298-qubit update
HERE = os.path.dirname(os.path.abspath(__file__))
MAX_SEQUENCE = 128
GUARDRAIL = ("Classical simulation on this computer (FP64 statevector/factor blocks). Not a quantum computer; no quantum "
             "speed-up or advantage is claimed. Memory grows as 2^n x 16 bytes for an entangled n-qubit block.")
SYNTH_REASON = ("Proposed command is not implemented and validated: q.compile synthesize. Clifford+T approximate synthesis to a stated "
                "operator-norm tolerance needs a number-theoretic synthesizer (for example Ross-Selinger gridsynth) with independent error "
                "verification; SpinDoctor does not include one, so no sequence is fabricated. Installed alternatives: q.compile identity, "
                "q.compile classify, q.compile count, q.math gate-matrix.")
LEGACY = ("q.circuit", "q.tranche", "q.prepare", "q.migrate", "q.gate", "q.state", "q.verify", "q.measure", "q.status", "q.export", "q.reset", "q.help")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"


def words_of(command):
    return command.strip().split()


def command_text(command):
    if not command or not command.strip() or len(command) > 4096:
        raise ValueError("Each command is 1..4096 characters.")
    quoted = esc = False
    for c in command:
        if esc: esc = False; continue
        if c == "\\" and quoted: esc = True; continue
        if c == '"': quoted = not quoted; continue
        if c in ";\r\n" and not quoted:
            raise ValueError("Submit ordinary commands as an array; unquoted macro separators are unsupported.")
        if c == "\0": raise ValueError("NUL is not valid command data.")
    if quoted: raise ValueError("Unterminated command quote.")
    if not command.lstrip().lower().startswith("q."):
        raise ValueError("Only native q.* commands are accepted.")


def _exact(w, n):
    if len(w) != n: raise ValueError("Incorrect argument count for " + w[0] + ".")


def _need(t, word):
    if t.lower() != word: raise ValueError("Expected " + word + ".")


def seq_gate(w, at, n):
    """3.1.2 SpinDoctorSequences.Gate: syntax preflight for one gate step."""
    from .register import GATE_SPECS
    from .circuits import alias, integer as num
    name = alias(w[at]); spec = GATE_SPECS.get(name)
    if spec is None: raise ValueError("Unsupported gate: " + name)
    ac = spec["angleCount"]; qc = spec["targetCount"]
    all_ = len(w) == at + ac + 2 and w[-1].lower() == "all"
    if all_ and not spec["local"]: raise ValueError("all accepts local gates only.")
    if len(w) != at + 1 + ac + (1 if all_ else qc): raise ValueError("Incorrect gate operand count.")
    for i in range(ac): float(w[at + 1 + i])
    if not all_:
        seen = set()
        for i in range(qc):
            q = num(w[at + 1 + ac + i], 0, n - 1)
            if q in seen: raise ValueError("Gate qubits must be distinct.")
            seen.add(q)


def _count(t):
    if not t or not t.isdigit() or not t.isascii(): raise ValueError("Invalid nonnegative sequence counter.")
    return int(t)


def validate_legacy(w):
    """Port of 3.1.2 SpinDoctorSequences.ValidateLegacy: syntax preflight for circuit/tranche/procedural steps."""
    from .circuits import integer as num, unsigned, basis_of, check_name, parse_preset_options, MAX_LOGICAL_QUBITS as ML
    first = w[0].lower()
    if first == "q.circuit":
        if len(w) < 2: raise ValueError("Missing circuit action.")
        a = w[1].lower()
        if a == "new": _exact(w, 4); check_name(w[2]); num(w[3], 1, ML); return
        if a == "add": seq_gate(w, 2, ML); return
        if a == "preset": parse_preset_options(w); return
        if a == "run": _exact(w, 6); _need(w[2], "shots"); num(w[3], 1, 100000); _need(w[4], "basis"); basis_of(w[5]); return
        if a in ("state", "input"): _exact(w, 3); _count(w[2]); return
        if a == "spin": _exact(w, 3); num(w[2], 0, ML - 1); return
        if a == "select": _exact(w, 3); check_name(w[2]); return
        if a == "memory":
            _exact(w, 3)
            if w[2].lower() != "auto" and unsigned(w[2]) < 2: raise ValueError("Circuit memory minimum is 2 MiB.")
            return
        if a == "delete":
            if len(w) not in (2, 3): raise ValueError("Invalid delete arguments.")
            if len(w) == 3: check_name(w[2])
            return
        if a in ("clear", "show", "list", "status", "result", "cancel", "export", "help"): _exact(w, 2); return
        raise ValueError("Unknown circuit action.")
    if first == "q.tranche":
        if len(w) < 2: raise ValueError("Missing tranche action.")
        a = w[1].lower()
        if a == "prepare": _exact(w, 4); num(w[2], 1, ML); _need(w[3], "zero"); return
        if a == "from": _exact(w, 3); unsigned(w[2]); return
        if a == "gate": seq_gate(w, 2, ML); return
        if a == "state": _exact(w, 3); _count(w[2]); return
        if a == "spin": _exact(w, 3); num(w[2], 0, ML - 1); return
        if a == "measure":
            if len(w) not in (7, 8): raise ValueError("Invalid tranche measure arguments.")
            num(w[2], 0, ML - 1); _need(w[3], "basis"); basis_of(w[4]); _need(w[5], "shots"); n = num(w[6], 1, 100000)
            if len(w) == 8:
                _need(w[7], "collapse")
                if n != 1: raise ValueError("Collapse requires one shot.")
            return
        if a == "memory":
            _exact(w, 3)
            if w[2].lower() != "auto": unsigned(w[2])
            return
        if a == "save":
            if len(w) not in (2, 3): raise ValueError("Invalid tranche save arguments.")
            if len(w) == 3: _need(w[2], "dense")
            return
        if a in ("status", "cancel", "export", "resume", "reset", "release", "help"): _exact(w, 2); return
        raise ValueError("Unknown tranche action.")
    if first == "q.prepare": _exact(w, 4); _need(w[1], "grid"); unsigned(w[2]); unsigned(w[3]); return
    if first == "q.migrate": _exact(w, 3); _need(w[1], "t"); float(w[2]); return
    if first == "q.gate":
        name = w[1].lower() if len(w) > 1 else ""
        ac = 3 if name in ("u", "u3") else 1 if name in ("ry", "rz") else 0
        _exact(w, 3 + ac); _need(w[-1], "all")
        if name not in ("h", "x", "y", "z", "s", "t", "sdg", "tdg", "ry", "rz", "u", "u3", "i", "id"): raise ValueError("Unsupported procedural gate.")
        return
    if first == "q.state": _exact(w, 2); unsigned(w[1]); return
    if first == "q.verify":
        if len(w) == 2 and w[1].lower() in ("rule", "status", "cancel"): return
        if len(w) == 4 and w[1].lower() == "samples" and w[3].lower() == "errors-only":
            if not w[2].isdigit() or int(w[2]) <= 0: raise ValueError("Sample count must be positive.")
            return
        raise ValueError("Invalid verification command.")
    if first == "q.measure": _exact(w, 6); unsigned(w[1]); _need(w[2], "basis"); basis_of(w[3]); _need(w[4], "shots"); num(w[5], 1, 100000); return
    if first == "q.export": _exact(w, 2); _need(w[1], "descriptor"); return
    _exact(w, 1)


def load_presets():
    with open(os.path.join(HERE, "data", "SPINDOCTOR_PRESETS.json"), encoding="utf-8-sig") as fh:
        return json.load(fh)


class Session(object):
    def __init__(self, workspace=None, measurement_seed=None, field_seed=None, write_reports=True):
        self.workspace = os.path.abspath(workspace) if workspace else None
        self.write_reports = write_reports and self.workspace is not None
        st = None
        if self.workspace:
            os.makedirs(self.workspace, exist_ok=True)
            p = os.path.join(self.workspace, "spindoctor-cartridge-session.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as fh: st = json.load(fh)
        if st is not None and measurement_seed and st["measurementSeed"] != measurement_seed:
            raise ValueError("This workspace already has a different measurement seed; use a fresh workspace folder.")
        self.measurement_seed = st["measurementSeed"] if st else (measurement_seed or secrets.token_hex(32))
        self.field_seed = st["fieldSeed"] if st else (field_seed or secrets.token_hex(32))
        self.circuit = CircuitTerminal(self.measurement_seed)
        self.grid = Grid(self.field_seed, self.measurement_seed, ENGINE_VERSION)
        self.tranche = TrancheTerminal(self.measurement_seed)
        self.calc = Calculators(); self.adv = Advanced()
        self.command_index = 0; self.sequence = None; self.folder_job = None; self.sequence_jobs = []
        self.inputs = InputManager(self.workspace)
        self.history = history_mod.History(self._report_dir() if self.write_reports else None)
        self.presets = load_presets()
        if st:
            self.circuit.load_state(st["circuit"]); self.grid.load_state(st["grid"]); self.tranche.load_state(st["tranche"])
            self.command_index = st.get("commandIndex", 0)
            lim = st.get("limits")
            if lim: register.LIMITS.update(lim)

    # ------------------------------------------------------------------ persistence
    def save(self):
        if not self.workspace: return
        st = {"schema": "SPINDOCTOR-CARTRIDGE/SESSION/1", "cartridgeVersion": CARTRIDGE_VERSION, "engineVersion": ENGINE_VERSION,
              "measurementSeed": self.measurement_seed, "fieldSeed": self.field_seed, "commandIndex": self.command_index,
              "limits": dict(register.LIMITS), "circuit": self.circuit.to_state(), "grid": self.grid.to_state(), "tranche": self.tranche.to_state()}
        reports.atomic_write(os.path.join(self.workspace, "spindoctor-cartridge-session.json"), json.dumps(st, default=str))

    # ------------------------------------------------------------------ status
    def status(self):
        return {"productName": "SpinDoctor", "productVersion": ENGINE_VERSION, "cartridge": "SpinDoctor Scripter Cartridge " + CARTRIDGE_VERSION,
                "numericBackend": backend.name(), "measurementSeed": self.measurement_seed, "measurementCounter": str(self.grid.counter),
                "circuitCounter": str(self.circuit.counter), "programCount": len(self.circuit.programs), "programCapacity": self.circuit.capacity,
                "presetOwnedCount": len(self.circuit.owned_serial), "selectedCircuit": self.circuit.selected,
                "denseQubitCap": register.LIMITS["max_dense_qubits"], "quantumHardwareGates": "0", "guardrail": GUARDRAIL,
                "inputs": {"count": len(self.inputs.entries), "totalBytes": self.inputs.total_bytes()},
                "history": {"count": self.history.count()},
                "sequence": {"latestJobId": self.sequence["id"] if self.sequence else "", "folderJobId": self.folder_job["id"] if self.folder_job else ""},
                "coherentRegisterCapabilities": {"updateId": "3.1.2-298-20261010", "maximumLogicalQubits": 298, "maximumJointFactorQubits": 59,
                                                 "globalIndexEncoding": "BigInteger (Python int)", "wideCircuitMeasurementBasis": "z", "wideCircuitSampling": "prepared-factor-Born-Z"},
                "statusScope": "Compact cartridge status (the SpinDoctor 3.1.2 desktop terminal embeds its full status block here)."}

    def help(self):
        return {"productName": "SpinDoctor", "cartridge": CARTRIDGE_VERSION,
                "namespaces": ["q.circuit", "q.query", "q.math", "q.resource", "q.model", "q.lesson", "q.noise", "q.qec", "q.compile", "q.algorithm",
                               "q.prepare/q.migrate/q.gate/q.state/q.verify/q.measure/q.status/q.export/q.reset (procedural grid)", "q.tranche",
                               "q.preset list|show ID|run ID [name=value ...]", "q.sequence help|status|cancel|export [JOB_ID]",
                               "q.folder run path=\"/abs/folder\" [verify=true|false] [samples=N]|status|cancel|help",
                               "q.input list|add path=FILE|show|table|fit|evaluate|import|run|delete|export|help ID", "q.history list|show ID|export ID|help",
                               "q.cartridge info|limit dense-qubits N|backend numpy|stdlib"],
                "circuit": CircuitTerminal.help()["commands"], "calculatorCapabilities": calc_caps(), "advancedCapabilities": adv_caps(),
                "guardrail": GUARDRAIL}

    # ------------------------------------------------------------------ support / preflight
    def support(self, command):
        try:
            command_text(command); w = words_of(command); first = w[0].lower()
        except Exception as e:
            return {"available": False, "reason": str(e)}
        if first in ("q.sequence", "q.preset", "q.folder"):
            return {"available": False, "reason": "Nested sequence/preset/folder commands are not accepted inside a sequence."}
        if first in LEGACY:
            try:
                validate_legacy(w)
            except Exception as e:  # noqa: BLE001
                return {"available": False, "reason": str(e)}
            return {"available": True}
        if first == "q.cartridge":
            return {"available": True}
        if len(w) >= 2:
            ns = first; action = w[1].lower()
            if calc_supports(ns, action) or adv_supports(ns, action):
                return {"available": True}
            if ns == "q.compile" and action == "synthesize":
                return {"available": False, "validated": False, "backend": "uninstalled", "reason": SYNTH_REASON}
            return {"available": False, "validated": False, "backend": "uninstalled",
                    "reason": "Proposed command is not implemented and validated: " + ns + " " + action + ". Installed commands are listed by q.help and the preset menu; proposed extensions stay disabled until implemented and validated."}
        return {"available": False, "reason": "Unknown command."}

    def preset_card(self, pid):
        for p in self.presets["presets"]:
            if p["id"].lower() == pid.lower():
                card = dict(p); avail = "available"; reason = ""
                for c in p["commands"]:
                    s = self.support(c)
                    if not s["available"]:
                        avail = "needs-backend"; reason = s["reason"]; break
                card["runtimeAvailability"] = avail; card["runtimeReason"] = reason
                return card
        raise ValueError("Unknown preset id.")

    # ------------------------------------------------------------------ dispatch
    def native(self, command):
        """Execute one ordinary command; returns the response dict {ok, command, result|error, status}."""
        try:
            command_text(command)
            w = words_of(command); first = w[0].lower()
            if first in ("q.circuit", "q.tranche") and len(w) == 3 and w[1].lower() == "memory" and w[2].lower() == "auto":
                result = self.auto_memory(first == "q.tranche")
            elif first == "q.circuit": result = self.circuit.execute(w)
            elif first == "q.input":
                if len(w) >= 2 and w[1].lower() == "run":
                    raise ValueError("q.input run is handled by the sequence runner; call Session.run_command.")
                result = self.inputs.execute(w, self)
            elif first == "q.history": result = self.history.execute(w)
            elif first in ("q.math", "q.resource", "q.model", "q.lesson"): result = self.calc.execute(w)
            elif first == "q.query": result = self.query(w)
            elif first in ("q.noise", "q.qec", "q.compile", "q.algorithm"):
                if first == "q.compile" and len(w) > 1 and w[1].lower() == "synthesize":
                    raise RuntimeError(SYNTH_REASON)
                result = self.adv.execute(w)
            elif first in ("q.prepare", "q.migrate", "q.gate", "q.state", "q.verify", "q.measure", "q.export", "q.reset"): result = self.grid.execute(w)
            elif first == "q.status":
                if len(w) != 1: raise ValueError("Incorrect number of command arguments. Use q.help.")
                result = self.grid.status(); result["circuit"] = self.circuit.status(); result["tranche"] = self.tranche.status()
                result["coherentRegisterCapabilities"] = self.status()["coherentRegisterCapabilities"]
            elif first == "q.help": result = self.help()
            elif first == "q.tranche": result = self.tranche.execute(w, self.grid)
            elif first == "q.cartridge": result = self.cartridge(w)
            elif first in ("q.preset", "q.sequence", "q.folder"):
                raise ValueError("q.preset/q.sequence/q.folder are handled by the sequence runner; call Session.run_command.")
            else:
                raise ValueError("Unknown quantum command. Use q.help.")
            return {"ok": True, "command": command, "result": result, "status": self.status()}
        except Exception as e:  # noqa: BLE001 - every rejection is reported, never raised to the caller
            return {"ok": False, "command": command, "error": str(e), "status": self.status()}

    def auto_memory(self, use_tranche):
        plan = self.calc.execute(["q.resource", "auto"])
        mib = int(plan["usablePeakBytes"]) // 1048576
        if mib < 2: raise RuntimeError("Available RAM does not leave 2 MiB after the OS/overhead reserve.")
        w = ["q.tranche" if use_tranche else "q.circuit", "memory", str(mib)]
        applied = self.tranche.execute(w, self.grid) if use_tranche else self.circuit.execute(w)
        return {"mode": "auto", "plan": plan, "applied": applied, "allocationPerformed": False,
                "scope": "Momentary measured usable-RAM budget; only arrays required for actual computation are allocated. Physical memory is never credited as simulated work."}

    def expand_presets(self, commands):
        """3.1.x ExpandPresets: q.preset run ID [k=v] steps inside a sequence/folder file expand to the preset's commands."""
        out = []
        for c in commands:
            command_text(c); w = words_of(c)
            if w[0].lower() == "q.preset":
                if len(w) < 3 or w[1].lower() != "run": raise ValueError("A preset sequence step must use q.preset run ID.")
                card = self.preset_card(w[2])
                if card["runtimeAvailability"] == "needs-backend": raise ValueError("Preset unavailable: " + card["runtimeReason"])
                params = {}
                for t in w[3:]:
                    e = t.find("=")
                    if e <= 0 or e == len(t) - 1 or t[:e] in params: raise ValueError("Invalid preset override.")
                    params[t[:e]] = t[e + 1:]
                out += self.normalize(list(card["commands"]), params)
            else:
                out.append(c)
        return out

    def query(self, w):
        c = self.circuit
        if c.coherent is None or c.coherent_hash != program_hash(c.current()):
            raise RuntimeError("Run the selected circuit before querying its retained coherent state.")
        reg = c.coherent
        r = self.calc.execute(w, reg.qubits, reg.amplitude, reg.spin, c.coherent_hash)
        c.coherent_snapshot = reg.status()
        return r

    def cartridge(self, w):
        if len(w) == 2 and w[1].lower() == "info" or len(w) == 1:
            return {"cartridgeVersion": CARTRIDGE_VERSION, "engineVersion": ENGINE_VERSION, "engineUpdateId": ENGINE_UPDATE_ID, "numericBackend": backend.name(),
                    "numpyAvailable": backend.np is not None, "limits": dict(register.LIMITS), "maxCircuitQubits": 298, "maxJointFactorQubits": 59,
                    "denseMemoryForCapBytes": str((1 << register.LIMITS["max_dense_qubits"]) * 16), "guardrail": GUARDRAIL,
                    "presets": len(self.presets["presets"]), "workspace": self.workspace}
        if len(w) == 4 and w[1].lower() == "limit" and w[2].lower() == "dense-qubits":
            if not w[3].isdigit() or not (1 <= int(w[3]) <= 29): raise ValueError("dense-qubits must be 1..29.")
            register.LIMITS["max_dense_qubits"] = int(w[3])
            return {"maxDenseQubits": int(w[3]), "denseStatevectorBytesAtCap": str((1 << int(w[3])) * 16),
                    "warning": "Each extra qubit doubles memory. Make sure this machine has the RAM before raising the cap."}
        if len(w) == 3 and w[1].lower() == "backend" and w[2].lower() in ("numpy", "stdlib"):
            ok = backend.set_numpy(w[2].lower() == "numpy")
            return {"numericBackend": backend.name(), "numpyEnabled": ok}
        raise ValueError("Use q.cartridge info | q.cartridge limit dense-qubits N | q.cartridge backend numpy|stdlib.")

    # ------------------------------------------------------------------ reports
    def _report_dir(self):
        return os.path.join(self.workspace, "reports")

    def step_text(self, data):
        cmd = data["normalizedCommand"]
        cu = data.get("completedUtc") or ("(" + data["completionNote"] + ")" if data.get("completionNote") else "")
        lines = ["SPINDOCTOR \u2014 COMPLETE NATIVE COMMAND REPORT", "Sequence: " + data["sequenceId"] + "; command index: " + str(data["index"]),
                 "Received UTC: " + data["receivedUtc"], "Completed UTC: " + cu, "Original command: " + data["command"], "Normalized command: " + cmd,
                 "Convention: q0 is the least-significant bit; chronological gates compose leftward; radians; classical FP64 coherent simulation where stated by the native backend."]
        lc = cmd.lower()
        meas = lc.startswith("q.circuit run ") or lc.startswith("q.tranche measure ") or lc.startswith("q.measure ")
        lines.append("Measurement: requested classical Born sampling; requested/completed counts and partial work are in the native responses below." if meas else "Measurement: not performed by this command.")
        lines.append("Physical quantum hardware gates: 0. Represented family credits, actual classical queries/gates and samples are separate native counters.")
        lines.append("Simulator: SpinDoctor Scripter Cartridge %s (%s). %s" % (CARTRIDGE_VERSION, backend.name(), GUARDRAIL))
        if data.get("memoryEstimate"):
            lines.append("Memory estimate before run: " + dumps(data["memoryEstimate"]))
        lines.append("COMPLETE ACCEPTED NATIVE RESPONSE:"); lines.append(dumps(data["response"]))
        if "finalResponse" in data:
            lines.append("COMPLETE MATCHED ASYNCHRONOUS COMPLETION RESPONSE:"); lines.append(dumps(data["finalResponse"]))
        lines.append("JSON companion is retained. No successful individual verification sample rows are generated by this report.")
        return "\n".join(lines) + "\n"

    def execute_step(self, seq_id, index, original, normalized):
        """Execute one command as a sequence step, including asynchronous completion capture."""
        rec = {"schema": "SPINDOCTOR/SEQUENCE-COMMAND/1", "sequenceId": seq_id, "index": index, "command": original,
               "normalizedCommand": normalized, "receivedUtc": utc()}
        resp = self.native(normalized)
        res = resp.get("result") if resp["ok"] else None
        queued = isinstance(res, dict) and res.get("queued") is True
        nl = " ".join(normalized.lower().split())
        if resp["ok"] and queued and (nl.startswith("q.circuit run") or nl.startswith("q.circuit preset")):
            rec["memoryEstimate"] = self.circuit.last_memory_estimate
            job = self.circuit.job
            final_job = self.circuit.capture_job_report(job.id)
            ok = final_job["phase"] == "completed" and not final_job["error"] and not final_job["checkpointError"]
            final = {"ok": ok, "command": normalized, "result": final_job, "status": self.status()}
            if not ok: final["error"] = "Native job ended " + final_job["phase"] + ". " + final_job["error"] + " " + final_job["checkpointError"]
            rec["completedUtc"] = utc(); rec["response"] = resp; rec["finalResponse"] = final
            rec["completionNote"] = "pending: asynchronous job accepted; see the completed-stage report"
            return rec, final
        rec["completedUtc"] = utc() if resp["ok"] else ""
        rec["completionNote"] = "returned synchronously" if resp["ok"] else "not completed: command rejected"
        rec["response"] = resp
        return rec, resp

    def write_step(self, base, rec):
        if not self.write_reports: return []
        text = self.step_text(rec)
        return reports.write_bundle(base, text, rec, os.path.basename(base))

    # ------------------------------------------------------------------ public entry points
    def run_command(self, command, report_name=None):
        """Run any q.* command (including q.preset run / q.sequence); writes reports; returns summary dict."""
        t0 = time.perf_counter()
        w = words_of(command) if command.strip() else [""]
        first = w[0].lower()
        if first in ("q.preset", "q.sequence"):
            out = self.preset_or_sequence(command, w, report_name)
        elif first == "q.folder":
            out = self.folder_command(command, w, report_name)
        elif first == "q.input" and len(w) == 3 and w[1].lower() == "run":
            out = self.input_run(command, w, report_name)
        else:
            self.command_index += 1
            seq_id = uuid.uuid4().hex
            rec, final = self.execute_step(seq_id, 0, command, command)
            paths = []
            if self.write_reports:
                name = report_name or ("%05d-%s" % (self.command_index, re.sub(r"[^A-Za-z0-9]+", "-", command.strip())[:48].strip("-")))
                paths = self.write_step(os.path.join(self._report_dir(), name), rec)
                self.history.add(command, final["ok"], paths, rec)
            out = {"ok": final["ok"], "command": command, "response": rec.get("finalResponse", rec["response"]),
                   "accepted": rec["response"], "reports": paths, "record": rec}
        out["elapsedMs"] = (time.perf_counter() - t0) * 1000.0
        self.save()
        return out

    def run_script(self, lines, report_prefix=None):
        results = []
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith("//"): continue
            results.append(self.run_command(s))
        return results

    # ------------------------------------------------------------------ folders / input runs
    def folder_command(self, command, w, report_name):
        if len(w) == 2 and w[1].lower() == "help": return self._simple(command, True, dict(folder_mod.FOLDER_HELP), report_name)
        if len(w) == 2 and w[1].lower() == "status":
            return self._simple(command, True, {"job": folder_mod.compact_job(self.folder_job) if self.folder_job else None,
                                               "statusForm": "compact"}, report_name)
        if len(w) == 2 and w[1].lower() == "cancel":
            return self._simple(command, True, {"cancelRequested": False, "active": False, "job": folder_mod.compact_job(self.folder_job) if self.folder_job else None,
                                               "note": "Cartridge folder jobs run synchronously; there is no running folder job to cancel."}, report_name)
        if len(w) >= 2 and w[1].lower() == "run":
            try:
                self.command_index += 1
                job = folder_mod.run_folder(self, command, (report_name or "%05d-folder" % self.command_index))
            except Exception as e:  # noqa: BLE001 - rejected at q.folder run (nothing started)
                return self._simple(command, False, str(e), report_name)
            self.folder_job = job
            return self._simple(command, job["phase"] == "completed", {"queued": False, "job": job} if job["phase"] == "completed" else job["error"], report_name, extra={"job": job})
        return self._simple(command, False, "Unknown sequence/preset/folder command. Use q.sequence help.", report_name)

    def input_run(self, command, w, report_name):
        try:
            from .inputs import compile_source
            name, data = self.inputs.attachment_bytes(w[2])
            compiled = compile_source(name, data)
            cmds = self.expand_presets(compiled["commands"])
        except Exception as e:  # noqa: BLE001
            return self._simple(command, False, str(e), report_name)
        return self.run_sequence(cmds, None, {}, command, report_name,
                                 source={"sha256": compiled["sourceSha256"], "filename": name, "format": compiled["sourceFormat"]})

    def remember_job(self, job):
        self.sequence_jobs = [j for j in self.sequence_jobs if j["id"] != job["id"]][-19:] + [job]

    # ------------------------------------------------------------------ presets
    def preset_or_sequence(self, command, w, report_name):
        if w[0].lower() == "q.sequence":
            if len(w) == 2 and w[1].lower() == "help":
                result = {"commands": ["q.sequence status", "q.sequence cancel", "q.sequence export [JOB_ID]", "q.sequence help", "q.preset list", "q.preset show ID", "q.preset run ID [name=value ...]"],
                          "sequenceSubmission": "Use a .q script file (one command per line) or Session.run_sequence([...]). Unquoted semicolons/newlines are rejected. Quoted restricted mathematical gate-sequence fields are data.",
                          "jobBarriers": "A dependent command runs only after the previous command completed successfully (the cartridge executes sequences synchronously).",
                          "reports": "Every accepted command has a preserved TXT/JSON/CSV/PDF report, including individual failures. Measurement is not invented for read-only commands."}
            elif len(w) == 2 and w[1].lower() == "status":
                result = {"job": self.sequence, "statusForm": "compact", "recentJobIds": [j["id"] for j in self.sequence_jobs], "maximumCommands": MAX_SEQUENCE}
            elif len(w) == 2 and w[1].lower() == "cancel":
                result = {"cancelRequested": False, "active": False, "note": "Cartridge sequences run synchronously; there is no active sequence to cancel."}
            elif len(w) in (2, 3) and w[1].lower() == "export":
                if len(w) == 2:
                    if self.sequence is None: return self._simple(command, False, "No sequence exists.", report_name)
                    result = self.sequence
                else:
                    if not re.match(r"^[0-9a-f]{32}$", w[2]): return self._simple(command, False, "Invalid sequence job ID.", report_name)
                    found = [j for j in self.sequence_jobs if j["id"] == w[2]]
                    if not found: return self._simple(command, False, "Unknown sequence job ID.", report_name)
                    result = found[0]
            else:
                return self._simple(command, False, "Unknown sequence/preset/folder command. Use q.sequence help.", report_name)
            return self._simple(command, True, result, report_name)
        if len(w) == 2 and w[1].lower() == "list":
            cards = []
            for p in self.presets["presets"]:
                c = self.preset_card(p["id"])
                cards.append({"id": c["id"], "category": c["category"], "label": c["label"], "runtimeAvailability": c["runtimeAvailability"],
                              "runtimeReason": c["runtimeReason"], "commands": c["commands"]})
            return self._simple(command, True, {"presets": cards, "count": len(cards)}, report_name)
        if len(w) == 3 and w[1].lower() == "show":
            try:
                return self._simple(command, True, self.preset_card(w[2]), report_name)
            except Exception as e:
                return self._simple(command, False, str(e), report_name)
        if len(w) >= 3 and w[1].lower() == "run":
            params = {}
            for t in w[3:]:
                eqi = t.find("=")
                if eqi <= 0 or eqi == len(t) - 1 or t[:eqi] in params:
                    return self._simple(command, False, "Preset overrides use unique name=value arguments.", report_name)
                params[t[:eqi]] = t[eqi + 1:]
            return self.run_sequence(None, w[2], params, command, report_name)
        return self._simple(command, False, "Unknown sequence/preset/folder command. Use q.sequence help.", report_name)

    def _simple(self, command, ok, payload, report_name, extra=None):
        self.command_index += 1
        resp = {"ok": ok, "command": command, ("result" if ok else "error"): payload, "status": self.status()}
        if extra: resp.update(extra)
        paths = []
        if self.write_reports:
            name = report_name or ("%05d-%s" % (self.command_index, re.sub(r"[^A-Za-z0-9]+", "-", command)[:48].strip("-")))
            text = self.result_text(command, resp, "Recorded classical calculation or command response. Represented procedural family operations are not executed gates. A status/help/error report does not imply a measurement.")
            paths = reports.write_bundle(os.path.join(self._report_dir(), name), text, resp, name)
            self.history.add(command, ok, paths, resp)
        return {"ok": ok, "command": command, "response": resp, "reports": paths}

    def result_text(self, command, resp, note):
        lines = ["SPINDOCTOR - COMMAND RESULT", "Report ID: " + uuid.uuid4().hex, "UTC: " + utc(), "Command: " + command, note,
                 "Simulator: SpinDoctor Scripter Cartridge %s (%s). %s" % (CARTRIDGE_VERSION, backend.name(), GUARDRAIL), "",
                 "COMPLETE STRUCTURED RETURN (exact integer count strings retained)"]
        lines += reports.structured(resp)
        return "\n".join(lines) + "\n"

    def normalize(self, commands, params):
        names = set(n.lower() for n in self.circuit.names()); mapping = {}; out = []; added = 0
        schema = self.parameter_schema(commands)
        for k in params:
            if k not in schema: raise ValueError("Unknown/inapplicable preset parameter: " + k)
        for c in commands:
            command_text(c); w = words_of(c)
            if w[0].lower() not in LEGACY:
                out.append(c.strip()); continue
            if w[0].lower() == "q.circuit" and w[1].lower() == "preset":
                from .circuits import parse_preset_options
                o = parse_preset_options(w)
                base = o["name"] or ("bell" if o["preset"] == "bell" else o["preset"] + "-" + str(o["qubits"]))
                fresh = _fresh(base, names); mapping[base.lower()] = fresh
                w = ["q.circuit", "preset", o["preset"], str(o["qubits"])]
                w += (["shots", str(o["shots"]), "basis", o["basis"]] if o["run"] else ["run=false"])
                w += ["as", fresh]; added += 1
            if "shots" in params:
                for p in range(len(w) - 1):
                    if w[p].lower() == "shots": w[p + 1] = str(_int(params["shots"], 1, 100000))
            if "basis" in params:
                for p in range(len(w) - 1):
                    if w[p].lower() == "basis":
                        if params["basis"].lower() not in ("x", "y", "z"): raise ValueError("Basis must be x, y or z.")
                        w[p + 1] = params["basis"].lower()
            if w[0].lower() == "q.circuit" and w[1].lower() == "new":
                if "qubits" in params: w[3] = str(_int(params["qubits"], 1, 298))
                orig = check_name(w[2]); fresh = _fresh(orig, names); mapping[orig.lower()] = fresh; w[2] = fresh; added += 1
            if w[0].lower() == "q.circuit" and w[1].lower() == "select" and w[2].lower() in mapping:
                w[2] = mapping[w[2].lower()]
            if "input" in params and w[0].lower() == "q.circuit" and w[1].lower() == "input":
                w[2] = str(int(params["input"]))
            gs = (2 if len(w) > 1 and w[1].lower() in ("add", "gate") else -1) if w[0].lower() in ("q.circuit", "q.tranche") else (1 if w[0].lower() == "q.gate" else -1)
            if gs >= 0:
                from .register import GATE_SPECS
                from .calculators import real
                spec = GATE_SPECS.get(gate_alias(w[gs]))
                if spec is None: raise ValueError("Unsupported gate: " + gate_alias(w[gs]))
                for a in range(spec["angleCount"]):
                    expr = params.get("angle", w[gs + 1 + a])
                    v = real(expr)
                    if abs(v) > 1e12: raise ValueError("Angle/value must be finite within +/-1e12.")
                    w[gs + 1 + a] = fmt_r(v)
            out.append(" ".join(w))
        cap = self.circuit.capacity; existing = len(self.circuit.programs)
        if existing + added > cap:
            raise ValueError("Sequence needs %d new circuit program(s) but only %d of %d circuit slots are free (%d preset-owned). Free slots with q.circuit prune presets or q.circuit delete NAME, or raise the limit with q.circuit capacity N (maximum 1024)."
                             % (added, max(0, cap - existing), cap, len(self.circuit.owned_serial)))
        return out

    @staticmethod
    def parameter_schema(commands):
        r = {}; angles = 0
        from .register import GATE_SPECS
        for c in commands:
            w = words_of(c)
            for t in w:
                if t.lower() == "shots": r["shots"] = 1
                if t.lower() == "basis": r["basis"] = 1
            if len(w) > 2 and w[0].lower() == "q.circuit" and w[1].lower() == "preset":
                from .circuits import parse_preset_options
                if parse_preset_options(w)["run"]: r["shots"] = 1; r["basis"] = 1
            if len(w) > 1 and w[0].lower() == "q.circuit" and w[1].lower() == "new": r["qubits"] = 1
            if len(w) > 1 and w[0].lower() == "q.circuit" and w[1].lower() == "input": r["input"] = 1
            at = 2 if (w[0].lower() in ("q.circuit", "q.tranche") and len(w) > 2 and w[1].lower() in ("add", "gate")) else (1 if w[0].lower() == "q.gate" and len(w) > 1 else -1)
            if at >= 0:
                s = GATE_SPECS.get(gate_alias(w[at]))
                if s: angles += s["angleCount"]
        if angles == 1: r["angle"] = 1
        return r

    def auto_prune(self, commands, job):
        cap = self.circuit.capacity; existing = len(self.circuit.programs); owned = len(self.circuit.owned_serial)
        added = sum(1 for c in commands if len(words_of(c)) > 1 and words_of(c)[0].lower() == "q.circuit" and words_of(c)[1].lower() in ("new", "preset"))
        deficit = existing + added - cap
        if deficit <= 0 or owned < deficit: return
        resp = self.native("q.circuit prune presets " + str(owned - deficit))
        if not resp["ok"]: raise ValueError("Automatic preset-circuit pruning failed: " + resp["error"])
        job["pruned"] = list(resp["result"]["pruned"])

    def run_sequence(self, commands, preset_id, params, original_command=None, report_name=None, source=None):
        """q.preset run ID / explicit command list.  Synchronous; returns summary with per-step reports."""
        self.command_index += 1
        seq_id = uuid.uuid4().hex; t0 = time.perf_counter()
        job = {"id": seq_id, "active": True, "phase": "queued", "currentIndex": -1, "totalCommands": 0, "completedCommands": 0,
               "commands": [], "normalizedCommands": [], "presetId": preset_id or "", "parameters": dict(params or {}), "pruned": [],
               "records": [], "error": "", "receivedUtc": utc(), "completedUtc": ""}
        if source:
            job.update({"sourceSha256": source.get("sha256", ""), "sourceFilename": source.get("filename", ""), "sourceFormat": source.get("format", "")})
            if source.get("parentJobId"): job["parentJobId"] = source["parentJobId"]
        self.remember_job(job)
        label = original_command or ("q.preset run " + preset_id if preset_id else "q.sequence run")
        base_dir = self._report_dir() if self.write_reports else None
        stem = report_name or (preset_id if preset_id else "%05d-sequence" % self.command_index)
        paths = []
        try:
            if preset_id:
                card = self.preset_card(preset_id)
                if card["runtimeAvailability"] == "needs-backend":
                    raise ValueError("Preset is unavailable: " + card["runtimeReason"])
                if not commands: commands = list(card["commands"])
            if not commands or len(commands) > MAX_SEQUENCE:
                raise ValueError("Sequences contain 1..128 ordinary commands.")
            if not preset_id: commands = self.expand_presets(commands)
            if not commands or len(commands) > MAX_SEQUENCE:
                raise ValueError("Sequences contain 1..128 ordinary commands.")
            for c in commands:
                if words_of(c)[0].lower() in ("q.preset", "q.sequence", "q.folder", "q.input"):
                    raise ValueError("Recursive preset expansion is unsupported.")
            if preset_id: self.auto_prune(commands, job)
            norm = self.normalize(commands, params or {})
            for i, c in enumerate(norm):
                s = self.support(c)
                if not s["available"]:
                    job["currentIndex"] = i; raise ValueError("Command " + str(i) + ": " + s["reason"])
            job["commands"] = list(commands); job["normalizedCommands"] = norm; job["totalCommands"] = len(norm)
        except Exception as e:  # preflight failure: a report is still written
            job["phase"] = "failed"; job["active"] = False; job["error"] = "Preflight: " + str(e); job["completedUtc"] = utc()
            idx = job["currentIndex"] if job["currentIndex"] >= 0 else 0
            orig = commands[idx] if commands and len(commands) > idx else label
            failed = {"ok": False, "command": orig, "error": job["error"], "status": self.status()}
            rec = {"sequenceId": seq_id, "index": idx, "command": orig, "normalizedCommand": orig, "phase": "preflight-failed",
                   "receivedUtc": job["receivedUtc"], "completedUtc": "", "response": failed}
            job["records"].append(rec)
            accepted = {"ok": True, "command": label, "result": {"queued": False, "job": job, "error": job["error"]}, "status": self.status()}
            if base_dir:
                paths += reports.write_bundle(os.path.join(base_dir, stem), self.result_text(label, accepted, "Recorded classical calculation or command response. Represented procedural family operations are not executed gates. A status/help/error report does not imply a measurement."), accepted, stem)
                self.history.add(label, False, paths[-4:], accepted)
            self.sequence = job
            return {"ok": False, "command": label, "phase": "failed", "error": job["error"], "job": job, "reports": paths,
                    "steps": [], "elapsedMs": (time.perf_counter() - t0) * 1000.0}
        job["phase"] = "executing"; steps = []
        for i, c in enumerate(norm):
            job["currentIndex"] = i
            rec, final = self.execute_step(seq_id, i, commands[i], c)
            sp = []
            if base_dir:
                sp = self.write_step(os.path.join(base_dir, stem + "_steps", "%02d" % i), rec)
            steps.append({"index": i, "command": c, "ok": final["ok"], "reports": sp,
                          "error": final.get("error", ""), "result": final.get("result")})
            job["records"].append({"index": i, "command": commands[i], "normalizedCommand": c, "phase": "completed" if final["ok"] else "failed",
                                   "receivedUtc": rec["receivedUtc"], "completedUtc": rec.get("completedUtc", ""), "ok": final["ok"]})
            if not final["ok"]:
                job["phase"] = "failed"; job["error"] = final.get("error", ""); break
            # 3.0.3 ownership: circuits created by a preset run are preset-owned
            if preset_id:
                w = words_of(c); name = None
                if len(w) >= 4 and w[0].lower() == "q.circuit" and w[1].lower() == "new": name = w[2]
                elif len(w) >= 5 and w[0].lower() == "q.circuit" and w[1].lower() == "preset" and w[-2].lower() == "as": name = w[-1]
                if name: self.circuit.mark_preset_owned(name, preset_id)
            job["completedCommands"] += 1
        if job["phase"] != "failed": job["phase"] = "completed"
        job["active"] = False; job["completedUtc"] = utc()
        final_resp = {"ok": job["phase"] == "completed", "command": label, "error": job["error"], "result": job, "status": self.status()}
        if base_dir:
            paths += reports.write_bundle(os.path.join(base_dir, stem), self.result_text(label, final_resp, "Matched native asynchronous job completion. Partial, failed or cancelled work is reported at its actual completed count; exporting performs no additional calculation."), final_resp, stem)
            self.history.add(label, final_resp["ok"], paths[-4:], final_resp)
        self.sequence = job
        return {"ok": job["phase"] == "completed", "command": label, "phase": job["phase"], "error": job["error"], "job": job,
                "steps": steps, "reports": paths, "elapsedMs": (time.perf_counter() - t0) * 1000.0}


def _int(v, lo, hi):
    s = str(v)
    if not s.isdigit() or not (lo <= int(s) <= hi): raise ValueError("Integer outside allowed range.")
    return int(s)


def _fresh(original, names):
    check_name(original); fresh = original
    while fresh.lower() in names:
        fresh = (original[:23] if len(original) > 23 else original) + "-" + uuid.uuid4().hex[:8]
    names.add(fresh.lower())
    return fresh
