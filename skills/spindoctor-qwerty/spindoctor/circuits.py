# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Port of SpinDoctor 3.1.2 CircuitTerminal (SpinDoctorCircuits.cs).

Named 1..298-qubit circuit programs (prepared-factor Born-Z sampling above 29), 3.1.2 capacity/prune/preset-ownership rules, seeded
SHA-256 Born sampling (same seed derivation, counter and draw order as 3.1.2, so a given
seed+counter reproduces 3.1.2's histogram), retained premeasurement output for state/spin/
q.query.  Runs execute synchronously inside the cartridge (no background thread).
"""
import re
import datetime
import hashlib
import math
import time
import uuid

from . import backend
from .register import Register, GATE_SPECS, supported_gates, MemoryBudgetError
from .netfmt import fmt_r, dumps

DEFAULT_CAPACITY = 64
MAX_CAPACITY = 1024
HISTOGRAM_PREVIEW = 4000
COUNT_KEYS = ["executedCircuitInstructions", "backendGateApplications", "actualAmplitudeWrites",
              "actualTensorProducts", "actualPreparedQubits", "completedShots", "measuredQubits",
              "uniformDraws", "exactCPReductions", "queryCount", "coherentOutputExecutions"]
TREE_SAMPLER_MIN = 4096


def sha_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_counts():
    return {k: 0 for k in COUNT_KEYS}


def counts_obj(c):
    return {k: str(c[k]) for k in COUNT_KEYS}


def eq(a, b):
    return a.lower() == b.lower()


def check_name(name):
    if not name or len(name) > 32 or not (name[0].isascii() and name[0].isalpha()):
        raise ValueError("Circuit names begin with an ASCII letter, use letters/digits/-/_, and have at most 32 characters.")
    for ch in name:
        if not (ch.isascii() and (ch.isalnum() or ch in "-_")):
            raise ValueError("Invalid circuit name.")
    return name


def integer(value, lo, hi):
    if not value.isdigit() or not value.isascii() or len(value) > 10:
        raise ValueError("Integer is outside the supported range.")
    n = int(value)
    if n < lo or n > hi or n > 2147483647:
        raise ValueError("Integer is outside the supported range.")
    return n


MAX_LOGICAL_QUBITS = 298
MAX_FACTOR_QUBITS = 59
WIDE_SAMPLING = "prepared-factor-Born-Z"
REPLAY_SAMPLING = "independent-shot-replay"


def basis_index(value):
    """3.1.2-298 BasisIndex: nonnegative decimal of any width (BigInteger)."""
    if not value or not re.match(r"^[0-9]+\Z", value):
        raise ValueError("Expected a nonnegative decimal basis index.")
    return int(value)


def unsigned(value):
    if not value.isdigit() or not value.isascii() or int(value) > 18446744073709551615:
        raise ValueError("Expected an unsigned decimal integer.")
    return int(value)


def angle(value):
    try:
        v = float(value.strip())
    except Exception:
        raise ValueError("Angles must be finite within +/-1e12 radians.")
    if value.strip().lower() in ("nan", "inf", "-inf", "+inf", "infinity", "-infinity") or v != v or abs(v) > 1e12:
        raise ValueError("Angles must be finite within +/-1e12 radians.")
    return v


def basis_of(value):
    value = value.lower()
    if value not in ("x", "y", "z"):
        raise ValueError("Basis must be x, y or z.")
    return value


def exact(words, n):
    if len(words) != n:
        raise ValueError("Incorrect command argument count. Use q.circuit help.")


def bits_str(value, width):
    return "".join("1" if value & (1 << q) else "0" for q in range(width - 1, -1, -1))


def alias(name):
    name = name.lower()
    return {"cnot": "cx", "toffoli": "ccx", "fredkin": "cswap", "id": "i", "identity": "i", "u3": "u"}.get(name, name)


class Instruction(object):
    __slots__ = ("name", "angles", "qubits", "all")

    def __init__(self, name, angles, qubits, all_=False):
        self.name = name; self.angles = list(angles); self.qubits = list(qubits); self.all = all_

    def clone(self):
        return Instruction(self.name, self.angles, self.qubits, self.all)


class Program(object):
    def __init__(self, name, qubits, initial=0):
        self.name = name; self.qubits = qubits; self.initial = initial; self.gates = []; self.input_import = None

    def clone(self):
        p = Program(self.name, self.qubits, self.initial)
        p.gates = [g.clone() for g in self.gates]; p.input_import = self.input_import
        return p


def gate_spec(name):
    s = GATE_SPECS.get(name)
    if s is None:
        raise ValueError("Unknown circuit gate. Use q.circuit help.")
    return s


def parse_instruction(words, start, n, program_name=None):
    if len(words) <= start:
        raise ValueError("Supply a gate name, its angles and its qubits.")
    name = alias(words[start]); spec = gate_spec(name)
    ac = spec["angleCount"]; qc = spec["targetCount"]
    all_ = len(words) == start + ac + 2 and eq(words[-1], "all")
    if all_ and not spec["local"]:
        raise ValueError("all supports local gates only.")
    if len(words) != start + 1 + ac + (1 if all_ else qc):
        raise ValueError("Incorrect angle/qubit count for " + name + ". Angles precede qubits.")
    angles = [angle(words[start + 1 + j]) for j in range(ac)]
    qubits = []
    if not all_:
        if program_name is None:
            for j in range(qc):
                q = integer(words[start + 1 + ac + j], 0, n - 1)
                if q in qubits:
                    raise ValueError("Gate qubits must be distinct.")
                qubits.append(q)
            return Instruction(name, angles, qubits, all_)
        # 3.1.2-298 operand diagnostics: name the circuit, the valid range, every offending operand and the remedy.
        context = "Circuit '" + program_name + "' has " + str(n) + " qubits (valid indices 0.." + str(n - 1) + "). Gate " + name.upper()
        outside = []; required = 0; negative = False
        for j in range(qc):
            text = words[start + 1 + ac + j]
            if not text or not re.match(r"^-?[0-9]+\Z", text):
                raise ValueError(context + " requires integer qubit operands in that range; received '" + text + "'.")
            op = int(text)
            if op < 0 or op >= n: outside.append(text); negative = negative or op < 0
            if op >= 0 and op + 1 > required: required = op + 1
            qubits.append(op)
        if outside:
            remedy = (" Use nonnegative qubit indices within the selected circuit's range." if negative else
                      " Create or select a circuit with at least " + str(required) + " qubits before adding this gate." if required <= MAX_LOGICAL_QUBITS else
                      " This runtime supports at most " + str(MAX_LOGICAL_QUBITS) + " logical qubits.")
            raise ValueError(context + " uses out-of-range qubit operands [" + ", ".join(outside) + "]." + remedy)
        if len(set(qubits)) != len(qubits):
            raise ValueError(context + " requires distinct qubit operands.")
    return Instruction(name, angles, qubits, all_)


def instruction_obj(g):
    return {"name": g.name, "angles": [float(a) for a in g.angles], "anglesExact": [fmt_r(a) for a in g.angles],
            "qubits": list(g.qubits), "all": g.all}


def program_hash(p):
    parts = ["SPINDOCTOR/CIRCUIT/1|", p.name, "|", str(p.qubits), "|", str(p.initial)]
    for g in p.gates:
        parts += ["|", g.name, "|", "all" if g.all else "selected"]
        for a in g.angles: parts += ["|", fmt_r(a)]
        for q in g.qubits: parts += ["|", str(q)]
    return sha_hex("".join(parts))


def program_obj(p, include_gates):
    r = {"name": p.name, "qubits": p.qubits, "initialBasis": str(p.initial), "gateCount": len(p.gates),
         "descriptorHash": program_hash(p)}
    if p.input_import is not None:
        r["inputImport"] = p.input_import
        r["inputImportMatchesProgram"] = p.input_import.get("appliedProgramHash") == program_hash(p)
    if include_gates:
        r["gates"] = [instruction_obj(g) for g in p.gates]
    return r


class Work(object):
    def __init__(self, program, shots, basis, counter, memory):
        self.id = uuid.uuid4().hex; self.phase = "queued"; self.basis = basis; self.error = ""; self.checkpoint_error = ""
        self.active = True; self.requested = shots; self.completed = 0; self.measured = 0
        self.counter_start = counter; self.counter_end = counter; self.memory = memory
        self.elapsed_ms = 0.0; self.program = program; self.hash = program_hash(program)
        self.histogram = {}; self.counts = new_counts(); self.snapshot = None; self.spin_preview = None
        if program.qubits > 29 and basis != "z":
            raise ValueError("Wide registers currently use prepared-factor Born sampling in basis z. Select basis z for a register wider than 29 qubits.")
        self.sampling_mode = WIDE_SAMPLING if program.qubits > 29 else REPLAY_SAMPLING; self.sampling_factors = 0


DEFAULT_PRESET_SHOTS = 1024
SPIN_PREVIEW_SCHEMA = "SPINDOCTOR/PREMEASUREMENT-SPIN-PREVIEW/1"
SPIN_PREVIEW_QUBIT_LIMIT = 4
SPIN_PREVIEW_FACTOR_LIMIT = 65536
SPIN_PREVIEW_SCOPE = "Actual reduced Pauli expectations for the first at most four qubits of the retained coherent circuit output before independent measurement shots. Each queried coherent factor has at most 65536 stored entries. Omitted qubits were not evaluated and are not assigned zero vectors. This capture is separate from the saved procedural model and from postmeasurement shot states."
SPIN_PREVIEW_VERIFICATION_SCOPE = "These are actual circuit-state calculations. The procedural-model q.verify CPU/GPU sampling gate does not independently verify these circuit snapshots."
SPIN_PREVIEW_OMISSION = "Existing coherent factor exceeds the bounded spin-preview traversal; no zero vector is inferred."
PRESET_USAGE = "Use q.circuit preset bell|ghz|qft [QUBITS] [shots N] [basis x|y|z] [run=false] [as FRESH_NAME]."


def parse_preset_options(words):
    """Port of 3.1.0+ SpinDoctorCircuits.ParsePresetOptions (shared by direct dispatch and sequence preflight)."""
    if words is None or len(words) < 3 or not eq(words[0], "q.circuit") or not eq(words[1], "preset"):
        raise ValueError(PRESET_USAGE)
    preset = words[2].lower()
    if preset not in ("bell", "ghz", "qft"): raise ValueError("Presets are bell, ghz and qft.")
    at = 3; n = 2 if preset == "bell" else 29; shots = DEFAULT_PRESET_SHOTS
    if at < len(words) and re.match(r"^-?[0-9]+$", words[at]):
        n = integer(words[at], 1, MAX_LOGICAL_QUBITS); at += 1
    if preset == "bell" and n != 2: raise ValueError("The Bell preset has exactly two qubits.")
    name = None; basis = "z"; run = True; seen = set()
    while at < len(words):
        token = words[at]; at += 1
        if "=" in token:
            key, value = token.split("=", 1)
        else:
            key = token
            if at == len(words): raise ValueError("Missing circuit preset option value.")
            value = words[at]; at += 1
        if key.lower() in seen: raise ValueError("Duplicate circuit preset option: " + key + ".")
        seen.add(key.lower())
        if eq(key, "shots"): shots = integer(value, 1, 100000)
        elif eq(key, "basis"): basis = basis_of(value)
        elif eq(key, "as"): name = check_name(value)
        elif eq(key, "run"):
            if not eq(value, "true") and not eq(value, "false"): raise ValueError("Preset run must be true or false.")
            run = eq(value, "true")
        else: raise ValueError("Unknown circuit preset option: " + key + ".")
    return {"preset": preset, "qubits": n, "name": name, "shots": shots, "basis": basis, "run": run}


def capture_spin_preview(reg, w):
    """Port of 3.1.2 CaptureSpinPreview: bounded reduced Pauli expectations of the retained coherent output."""
    from .calculators import bloch_state_metadata
    rows = []; omissions = []
    n = w.program.qubits; considered = min(SPIN_PREVIEW_QUBIT_LIMIT, n)
    for q in range(considered):
        f = reg.find(reg.factors, q)
        entries = len(f.sparse) if f.dense is None else f.length
        if entries > SPIN_PREVIEW_FACTOR_LIMIT:
            omissions.append({"qubit": q, "reason": SPIN_PREVIEW_OMISSION, "factorEntryCount": str(entries)})
        else:
            row = bloch_state_metadata(reg.spin(q), q); row["factorEntryCount"] = str(entries); rows.append(row)
    return {"schema": SPIN_PREVIEW_SCHEMA, "programHash": w.hash,
            "capturedUtc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f0Z"),
            "premeasurement": True, "qubitLimit": SPIN_PREVIEW_QUBIT_LIMIT, "maximumFactorEntries": SPIN_PREVIEW_FACTOR_LIMIT,
            "selectedQubits": n, "returnedQubits": len(rows), "omittedQubits": n - len(rows), "unrequestedQubits": n - considered,
            "rows": rows, "omissions": omissions, "scope": SPIN_PREVIEW_SCOPE, "independentVerification": False,
            "verificationScope": SPIN_PREVIEW_VERIFICATION_SCOPE}


class NetDict(object):
    """Case-insensitive mapping whose iteration order emulates .NET Dictionary<K,V>: removed slots go on a
    LIFO free list and are reused by the next Add, so 'q.circuit list' order matches SpinDoctor 3.1.2."""

    def __init__(self):
        self.slots = []; self.free = []; self.index = {}

    def __len__(self): return len(self.index)
    def __contains__(self, k): return k in self.index
    def get(self, k, d=None):
        i = self.index.get(k); return d if i is None else self.slots[i][1]
    def __getitem__(self, k): return self.slots[self.index[k]][1]
    def __setitem__(self, k, v):
        i = self.index.get(k)
        if i is not None: self.slots[i] = (k, v); return
        if self.free: i = self.free.pop()
        else: self.slots.append(None); i = len(self.slots) - 1
        self.slots[i] = (k, v); self.index[k] = i
    def __delitem__(self, k):
        i = self.index.pop(k); self.slots[i] = None; self.free.append(i)
    def pop(self, k, d=None):
        if k not in self.index: return d
        v = self[k]; del self[k]; return v
    def keys(self): return [e[0] for e in self.slots if e is not None]
    def values(self): return [e[1] for e in self.slots if e is not None]
    def items(self): return [e for e in self.slots if e is not None]
    def __iter__(self): return iter(self.keys())
    def compact_copy(self, fn=lambda v: v):
        n = NetDict()
        for k, v in self.items(): n[k] = fn(v)
        return n


class CircuitTerminal(object):
    def __init__(self, measurement_seed):
        self.seed = sha_hex(measurement_seed + "|SpinDoctor|coherent-circuit-measurements")
        self.programs = NetDict()   # key: lower-case name -> Program (case-insensitive like C#)
        self.selected = ""
        self.capacity = DEFAULT_CAPACITY
        self.owned_serial = {}      # lower name -> serial
        self.owned_by = {}
        self.ownership_serial = 0
        self.counter = 0
        self.memory_limit = 512 * 1024 * 1024
        self.lifetime = new_counts()
        self.job = None
        self.coherent = None; self.coherent_hash = ""; self.coherent_snapshot = None
        self.last_memory_estimate = None

    # ------------------------------------------------------------ helpers
    def _get(self, name):
        return self.programs.get(name.lower())

    def current(self):
        p = self._get(self.selected) if self.selected else None
        if p is None:
            raise RuntimeError("Create or select a circuit first.")
        return p

    def names(self):
        return sorted((p.name for p in self.programs.values()), key=lambda s: s.lower())

    def instruction_count(self):
        return sum(len(p.gates) for p in self.programs.values())

    def owned_oldest_first(self):
        return [self.programs[k].name for k, _ in sorted(self.owned_serial.items(), key=lambda kv: kv[1]) if k in self.programs]

    def release_coherent(self):
        self.coherent = None; self.coherent_hash = ""; self.coherent_snapshot = None

    def commit(self, change):
        prev = (self.programs.compact_copy(lambda p: p.clone()), self.selected, self.capacity, dict(self.owned_serial), dict(self.owned_by))
        prev_job = self.job; prev_preview = None if self.job is None else self.job.spin_preview
        try:
            change()
            for k in list(self.owned_serial):
                if k not in self.programs:
                    self.owned_serial.pop(k, None); self.owned_by.pop(k, None)
            if self.job is not None: self.job.spin_preview = None   # 3.1.2: a program mutation retires the spin preview
        except Exception:
            self.programs, self.selected, self.capacity, self.owned_serial, self.owned_by = prev
            self.job = prev_job
            if prev_job is not None: prev_job.spin_preview = prev_preview
            raise
        self.release_coherent()

    def capacity_message(self):
        return ("Circuit storage is full (%d/%d saved programs, %d preset-owned). Free a slot with q.circuit delete NAME or "
                "q.circuit prune presets, or raise the limit with q.circuit capacity N (maximum %d)."
                % (len(self.programs), self.capacity, len(self.owned_serial), MAX_CAPACITY))

    def capacity_obj(self):
        return {"programCapacity": self.capacity, "programCount": len(self.programs),
                "freeSlots": max(0, self.capacity - len(self.programs)), "presetOwnedCount": len(self.owned_serial),
                "userOwnedCount": len(self.programs) - len(self.owned_serial), "maximumCapacity": MAX_CAPACITY,
                "defaultCapacity": DEFAULT_CAPACITY, "presetOwned": self.owned_oldest_first(),
                "scope": "Saved circuit program slots. Preset-owned circuits were created by q.preset runs and may be pruned automatically (oldest first) when a later preset needs a slot; user circuits are never pruned automatically."}

    def mark_preset_owned(self, name, preset_id):
        p = self._get(name) if name else None
        if p is None:
            return
        self.ownership_serial += 1
        self.owned_serial[p.name.lower()] = self.ownership_serial; self.owned_by[p.name.lower()] = preset_id or ""

    def import_circuit(self, spec):
        """Port of 3.1.2 ImportCircuit: validated q.input spec -> selected program (never runs it)."""
        import json as _json
        if self.job is not None and self.job.active:
            raise RuntimeError("A circuit run is active. Finish or cancel it before importing another program.")
        p = Program(check_name(str(spec["name"])), integer(str(spec["qubits"]), 1, MAX_LOGICAL_QUBITS), basis_index(str(spec["initialBasis"])))
        if p.initial >= (1 << p.qubits): raise ValueError("Initial basis must be below 2^qubits.")
        for g in spec["gates"]:
            if len(p.gates) >= 8192: raise ValueError("Imported circuit exceeds 8192 instructions.")
            words = [str(g["name"])] + [fmt_r(float(a)) for a in g["angles"]]
            words += ["all"] if g["all"] else [str(q) for q in g["qubits"]]
            p.gates.append(parse_instruction(words, 0, p.qubits, p.name))
        old_p = self._get(p.name); replaced = old_p is not None
        if not replaced and len(self.programs) >= self.capacity: raise RuntimeError(self.capacity_message())
        if self.instruction_count() - (len(old_p.gates) if replaced else 0) + len(p.gates) > 65536:
            raise RuntimeError("Total circuit instruction storage limit reached.")
        meta = {k: spec[k] for k in ("source", "parameters", "hints", "equations") if k in spec}
        meta["appliedProgramHash"] = program_hash(p)
        p.input_import = _json.loads(_json.dumps(meta))

        def ch():
            self.programs[p.name.lower()] = p; self.selected = p.name
            self.owned_serial.pop(p.name.lower(), None); self.owned_by.pop(p.name.lower(), None)
            self.owned_serial.pop(p.name, None); self.owned_by.pop(p.name, None)
        self.commit(ch)
        return {"imported": True, "replaced": replaced, "executed": False, "seedPreserved": True, "program": program_obj(p, False),
                "note": "Input is validated and selected. Run it explicitly with q.circuit run."}

    # ------------------------------------------------------------ status
    def job_obj(self, w):
        return {"id": w.id, "active": w.active, "phase": w.phase, "requestedShots": str(w.requested),
                "completedShots": str(w.completed), "measuredQubits": str(w.measured), "basis": w.basis,
                "programName": w.program.name, "qubits": w.program.qubits, "initialBasis": str(w.program.initial),
                "programHash": w.hash, "elapsedMs": w.elapsed_ms, "programSnapshot": program_obj(w.program, True),
                "counterStart": str(w.counter_start), "counterEnd": str(w.counter_end), "error": w.error,
                "checkpointError": w.checkpoint_error, "counts": counts_obj(w.counts), "coherentSpinPreview": w.spin_preview,
                "samplingMode": w.sampling_mode, "samplingFactorCount": w.sampling_factors,
                "samplingScope": "One actual coherent preparation and gate replay; each independent shot samples every coherent factor jointly without collapsing the retained state. One seeded uniform draw per factor; correlations within a factor are preserved. Counters record only performed preparations, gates, factor traversals and sampled readout outcomes." if w.sampling_mode == WIDE_SAMPLING else "Each independent shot prepares, replays and measures a fresh coherent register in qubit order. One additional coherent execution is retained before measurement. Counters record actual replay and collapsing-measurement work."}

    def result_obj(self, w, full=False):
        r = self.job_obj(w)
        keys = sorted(w.histogram)
        preview = []; omitted = 0
        for j, k in enumerate(keys):
            if full or j < HISTOGRAM_PREVIEW:
                preview.append({"bitstring": k, "count": str(w.histogram[k])})
            else:
                omitted += w.histogram[k]
        r["histogram"] = preview
        r["histogramComplete"] = True if full else len(keys) <= HISTOGRAM_PREVIEW
        r["distinctOutcomes"] = len(keys)
        r["omittedOutcomes"] = 0 if full else max(0, len(keys) - HISTOGRAM_PREVIEW)
        r["omittedShots"] = "0" if full else str(omitted)
        r["fullPrintoutAvailable"] = True
        r["coherentOutputAvailable"] = self.coherent is not None and self.coherent_hash == w.hash
        r["coherentOutputStatus"] = w.snapshot
        r["bitOrder"] = "Most significant displayed bit at left; qubit 0 at right."
        r["seed"] = self.seed
        r["scope"] = ("Full joint bitstrings from independent Born-Z samples of the prepared coherent factors. Each factor is sampled jointly; its internal correlations are preserved. Histograms contain completed shots only; consumed draws and factor traversals from partial shots are counted separately."
                      if w.sampling_mode == WIDE_SAMPLING else "Full joint bitstrings from independently replayed coherent registers and sequential collapsing Born measurements. Histograms contain completed shots only; partial shot work and consumed random draws are counted separately.")
        if full:
            r["reportSnapshot"] = True
        return r

    def status(self):
        return {"product": "SpinDoctor", "available": True, "selected": self.selected,
                "programCount": len(self.programs), "programCapacity": self.capacity, "presetOwnedCount": len(self.owned_serial),
                "programNames": self.names(),
                "programSummaries": [{"name": n, "qubits": self._get(n).qubits, "descriptorHash": program_hash(self._get(n))} for n in self.names()],
                "program": None if not self.selected else program_obj(self.current(), False),
                "measurementSeed": self.seed, "counter": str(self.counter), "memoryLimitBytes": str(self.memory_limit),
                "memoryAccountingScope": "Combined estimated retained coherent output and working shot state, including backend transactional work. Managed GC retention and other host memory are reported separately by the backend.",
                "lifetime": counts_obj(self.lifetime), "job": None if self.job is None else self.job_obj(self.job),
                "result": None if self.job is None else self.result_obj(self.job),
                "coherentOutputAvailable": self.coherent is not None, "coherentOutputProgramHash": self.coherent_hash,
                "coherentOutputStatus": self.coherent_snapshot,
                "scope": "Selected 1..298-qubit coherent circuits, simulated with classical FP64 arithmetic and seeded Born sampling. Registers of at most 29 qubits independently replay every shot. Wider registers prepare once and draw independent joint Z-basis samples from coherent factors. No physical quantum hardware or whole-family gate execution is claimed."}

    @staticmethod
    def help():
        return {"commands": ["q.circuit new NAME QUBITS", "q.circuit select NAME", "q.circuit list", "q.circuit show",
                             "q.circuit add GATE [angles...] [qubits...|all]", "q.circuit input BASIS_INDEX", "q.circuit clear", "q.circuit delete [NAME]",
                             "q.circuit preset bell|ghz|qft [QUBITS] [shots N] [basis x|y|z] [run=false] [as FRESH_NAME]", "q.circuit run shots N basis x|y|z", "q.circuit status", "q.circuit result",
                             "q.circuit state INDEX", "q.circuit spin Q", "q.circuit cancel", "q.circuit export", "q.circuit memory MiB", "q.circuit capacity [N]", "q.circuit prune presets [KEEP]", "q.circuit help"],
                "storage": "Default capacity 64 saved circuits (configurable 1..1024 with q.circuit capacity N; 65536 instructions total). Circuits created by q.preset runs are tracked as preset-owned; when a preset needs space, its sequence automatically prunes the oldest preset-owned circuits (never user circuits) and records them. q.circuit prune presets [KEEP] does the same explicitly.",
                "gates": supported_gates(),
                "aliases": {"cnot": "cx", "toffoli": "ccx", "fredkin": "cswap", "id": "i", "identity": "i", "u3": "u"},
                "limits": {"maximumLogicalQubits": MAX_LOGICAL_QUBITS, "maximumJointFactorQubits": MAX_FACTOR_QUBITS,
                           "scope": "Native circuits support 1..298 logical qubits with at most 59 qubits in one coherent factor, subject to memory limits. Full joint query analysis is bounded to 16 qubits. Auxiliary q.compile, q.qec and q.noise analyses retain the limits described by their own capabilities."},
                "operandOrder": "Angles first, then qubit indices. Controlled gates: control(s), target. RZX: Z operand, X operand. Local all applies to the selected circuit's qubits only.",
                "qftConvention": "|j> maps to sum_k exp(2*pi*i*j*k/2^n)|k>/sqrt(2^n), with final bit-reversal swaps.",
                "presets": "bell uses 2 qubits; ghz/qft default to 29. Presets replace/select bell, ghz-N or qft-N, reset input to 0, and automatically queue 1024 independent shots in basis z. Override shots (1..100000) or basis (x/y/z); run=false defines/selects only, for scripts that set input before running. Options accept key value or key=value. Existing coherent memory limits and cancellation apply.",
                "run": "1..100000 independent shots. Registers of at most 29 qubits replay each shot and retain one separately counted premeasurement execution. Wider registers prepare once and sample every coherent factor jointly in Z, with actual work declared by samplingMode and samplingFactorCount. Full histograms survive restart; coherent output is recalculated by the next run."}

    # ------------------------------------------------------------ execute
    def execute(self, words):
        if len(words) < 2 or not eq(words[0], "q.circuit"):
            raise ValueError("Use q.circuit help.")
        c = words[1].lower()
        if c == "help": exact(words, 2); return self.help()
        if c == "status": exact(words, 2); return self.status()
        if c == "capacity" and len(words) == 2: return self.capacity_obj()
        if c == "result":
            exact(words, 2); return {"available": False} if self.job is None else self.result_obj(self.job)
        if c == "cancel":
            exact(words, 2)
            return {"cancelRequested": False, "job": None if self.job is None else self.job_obj(self.job)}
        if c == "new":
            exact(words, 4); name = check_name(words[2]); n = integer(words[3], 1, MAX_LOGICAL_QUBITS)
            if self._get(name) is not None:
                raise ValueError("Circuit name already exists. Select it or delete it first.")
            if len(self.programs) >= self.capacity:
                raise RuntimeError(self.capacity_message())

            def ch():
                self.programs[name.lower()] = Program(name, n); self.selected = name
            self.commit(ch); return program_obj(self.current(), True)
        if c == "select":
            exact(words, 3); p = self._get(words[2])
            if p is None: raise ValueError("Unknown circuit name.")

            def ch():
                self.selected = p.name
            self.commit(ch); return program_obj(p, True)
        if c == "list":
            exact(words, 2)
            return {"selected": self.selected, "circuits": [program_obj(p, False) for p in self.programs.values()]}
        if c == "show": exact(words, 2); return program_obj(self.current(), True)
        if c == "input":
            exact(words, 3); p = self.current(); v = basis_index(words[2])
            if v >= (1 << p.qubits):
                raise ValueError("Input basis index must be below 2^qubits.")

            def ch():
                p.initial = v
            self.commit(ch); return program_obj(p, False)
        if c == "add":
            p = self.current()
            if len(p.gates) >= 8192 or self.instruction_count() >= 65536:
                raise RuntimeError("Circuit program storage limit reached (8192 instructions per program, 65536 total).")
            ins = parse_instruction(words, 2, p.qubits, p.name)

            def ch():
                p.gates.append(ins)
            self.commit(ch); return {"program": program_obj(p, False), "instruction": instruction_obj(ins)}
        if c == "clear":
            exact(words, 2); p = self.current()

            def ch():
                p.gates = []
            self.commit(ch); return program_obj(self.current(), True)
        if c == "delete":
            if len(words) not in (2, 3):
                raise ValueError("Use q.circuit delete [NAME].")
            name = words[2] if len(words) == 3 else self.current().name
            if self._get(name) is None:
                raise ValueError("Unknown circuit name.")
            real = self._get(name).name

            def ch():
                del self.programs[name.lower()]
                if eq(self.selected, name): self.selected = ""
            self.commit(ch); return {"deleted": name, "selected": self.selected}
        if c == "capacity":
            exact(words, 3); req = integer(words[2], 1, MAX_CAPACITY)
            if req < len(self.programs):
                raise ValueError("Capacity cannot be set below the %d circuits already saved. Use q.circuit delete NAME or q.circuit prune presets first." % len(self.programs))

            def ch():
                self.capacity = req
            self.commit(ch); return self.capacity_obj()
        if c == "prune":
            if len(words) not in (3, 4) or not eq(words[2], "presets"):
                raise ValueError("Use q.circuit prune presets [KEEP]. Only circuits created by q.preset runs are removed, oldest first; user-created circuits are never pruned.")
            keep = integer(words[3], 0, MAX_CAPACITY) if len(words) == 4 else 0
            order = self.owned_oldest_first()
            removed = order[:max(0, len(order) - keep)]
            if removed:
                def ch():
                    for nme in removed:
                        self.programs.pop(nme.lower(), None)
                        if eq(self.selected, nme): self.selected = ""
                self.commit(ch)
            return {"pruned": removed, "prunedCount": len(removed), "keptPresetCircuits": len(self.owned_serial),
                    "selected": self.selected, "capacity": self.capacity_obj(),
                    "scope": "Removes only circuit programs that a q.preset run created (oldest first). User circuits, seeds, counters and the last histogram are preserved."}
        if c == "preset":
            o = parse_preset_options(words)
            iso = o["name"]; preset = o["preset"]; n = o["qubits"]
            name = iso if iso is not None else ("bell" if preset == "bell" else preset + "-" + str(n))
            if iso is not None and self._get(name) is not None:
                raise ValueError("Isolated preset name already exists; supply a fresh name.")
            if self._get(name) is None and len(self.programs) >= self.capacity:
                raise RuntimeError(self.capacity_message())
            p = Program(name, n)
            if preset in ("bell", "ghz"):
                p.gates.append(Instruction("h", [], [0]))
                for q in range(1, n): p.gates.append(Instruction("cx", [], [0, q]))
            else:
                for q in range(n - 1, -1, -1):
                    p.gates.append(Instruction("h", [], [q]))
                    for lower in range(q - 1, -1, -1):
                        p.gates.append(Instruction("cp", [math.pi / math.pow(2, q - lower)], [q, lower]))
                for q in range(n // 2): p.gates.append(Instruction("swap", [], [q, n - 1 - q]))

            if not o["run"]:
                def ch():
                    self.programs[name.lower()] = p; self.selected = name
                self.commit(ch)
                d = program_obj(p, True); d["executionRequested"] = False
                d["note"] = "Preset defined and selected only (run=false). No circuit execution or measurement shots were requested."
                return d
            w = Work(p.clone(), o["shots"], o["basis"], self.counter, self.memory_limit)

            def ch():
                self.programs[name.lower()] = p; self.selected = name; self.job = w
            self.commit(ch)
            queued = {"queued": True, "job": self.job_obj(w)}
            queued["preset"] = preset; queued["automaticPresetRun"] = True; queued["program"] = program_obj(p, True)
            queued["defaultShots"] = DEFAULT_PRESET_SHOTS
            self.last_memory_estimate = memory_estimate(p)
            self._run(w)
            return queued
        if c == "memory":
            exact(words, 3); mib = unsigned(words[2])
            if mib < 2:
                raise ValueError("Combined circuit budget must be at least 2 MiB.")
            b = mib * 1024 * 1024
            if self.coherent_snapshot is not None and int(self.coherent_snapshot["allocatedStateBytesEstimate"]) > b - 1024 * 1024:
                raise RuntimeError("Budget must hold the retained coherent output plus at least 1 MiB for a shot. Start a new smaller run before reducing it.")
            self.memory_limit = b
            return {"memoryLimitBytes": str(b), "scope": "Combined retained output and working shot transactional state estimate."}
        if c == "run":
            if len(words) != 6 or not eq(words[2], "shots") or not eq(words[4], "basis"):
                raise ValueError("Use q.circuit run shots N basis x|y|z.")
            shots = integer(words[3], 1, 100000); basis = basis_of(words[5]); p = self.current().clone()
            w = Work(p, shots, basis, self.counter, self.memory_limit)
            self.job = w; self.release_coherent()
            accepted = {"queued": True, "job": self.job_obj(w)}
            self.last_memory_estimate = memory_estimate(p)
            self._run(w)
            return accepted
        if c in ("state", "spin"):
            exact(words, 3)
            if self.coherent is None or self.coherent_hash != program_hash(self.current()):
                raise RuntimeError("No retained coherent output for the selected program is available. Run the circuit first; persisted histograms survive restart, while coherent output is recalculated by the next run.")
            if c == "state":
                res = self.coherent.state(basis_index(words[2]))
            else:
                q = integer(words[2], 0, self.coherent.qubits - 1)
                res = {"qubit": q, "spin": self.coherent.spin(q)}
            self.coherent_snapshot = self.coherent.status()
            return {"programHash": self.coherent_hash, "premeasurement": True, "result": res}
        if c == "export":
            exact(words, 2)
            return {"schema": "SPINDOCTOR/CIRCUIT/1", "program": program_obj(self.current(), True), "measurementSeed": self.seed,
                    "counter": str(self.counter), "status": self.status()}
        raise ValueError("Unknown circuit command. Use q.circuit help.")

    # ------------------------------------------------------------ run
    def uniform(self, w):
        index = self.counter; self.counter += 1; w.counter_end = self.counter
        w.counts["uniformDraws"] += 1; self.lifetime["uniformDraws"] += 1
        b = hashlib.sha256((self.seed + "|circuit-born|" + str(index)).encode("utf-8")).digest()
        word = int.from_bytes(b[:8], "big")
        return (word >> 11) * (1.0 / 9007199254740992.0)

    def _add(self, w, key, d):
        w.counts[key] += d; self.lifetime[key] += d

    def _prepare(self, p, budget):
        spinors = [[1.0, 0.0, 0.0, 0.0] if not (p.initial & (1 << q)) else [0.0, 0.0, 1.0, 0.0] for q in range(p.qubits)]
        r = Register(p.qubits, spinors)
        r.set_memory_limit(budget)
        return r

    def _replay(self, reg, p, w):
        known = [1 if p.initial & (1 << q) else 0 for q in range(p.qubits)]
        for g in p.gates:
            name, angles, qubits, all_, reduced = g.name, g.angles, g.qubits, g.all, False
            if name == "cp" and (known[qubits[0]] >= 0 or known[qubits[1]] >= 0):
                kp = 0 if known[qubits[0]] >= 0 else 1
                bit = known[qubits[kp]]; qubits = [qubits[1 - kp]]
                name = "i" if bit == 0 else "p"; angles = [] if bit == 0 else angles; all_ = False; reduced = True
            reg.gate(name, angles, qubits, all_)
            self._add(w, "executedCircuitInstructions", 1)
            self._add(w, "backendGateApplications", p.qubits if all_ else 1)
            if reduced: self._add(w, "exactCPReductions", 1)
            update_known(known, g)

    def _run(self, w):
        t0 = time.perf_counter()
        try:
            w.phase = "preparing coherent output"
            reg = self._prepare(w.program, w.memory - 1024 * 1024)
            self._add(w, "actualPreparedQubits", w.program.qubits)
            self._replay(reg, w.program, w)
            q0 = reg.query_count
            preview = capture_spin_preview(reg, w)
            self._add(w, "queryCount", reg.query_count - q0)
            snap = reg.status()
            self.coherent = reg; self.coherent_snapshot = snap; self.coherent_hash = w.hash; w.snapshot = snap; w.spin_preview = preview
            self._add(w, "coherentOutputExecutions", 1)
            cache = int(snap["allocatedStateBytesEstimate"])
            if cache > w.memory - 1024 * 1024:
                raise MemoryBudgetError("Retained output leaves insufficient memory for an independent shot.")
            n = w.program.qubits
            if w.sampling_mode == WIDE_SAMPLING:
                w.sampling_factors = len(reg.factors); q1 = reg.query_count
                for shot in range(w.requested):
                    w.phase = "sampling prepared joint Z shot " + str(shot + 1)
                    sampled = reg.sample_z(lambda: self.uniform(w))
                    key = bits_str(sampled, n); w.histogram[key] = w.histogram.get(key, 0) + 1
                    w.measured += n; self._add(w, "measuredQubits", n)
                    w.completed += 1; self._add(w, "completedShots", 1); w.counter_end = self.counter
                self._add(w, "queryCount", reg.query_count - q1)
                self._add(w, "actualAmplitudeWrites", reg.amplitude_writes)
                self._add(w, "actualTensorProducts", reg.tensor_products)
                self.coherent_snapshot = reg.status(); w.snapshot = self.coherent_snapshot
                w.phase = "completed"
                return
            # Factors too large to clone per shot are sampled from exact conditional
            # marginals in the measured basis (mathematically identical to sequential
            # collapsing measurement); small factors are collapsed exactly as in 3.0.3.
            big = {}
            for f in reg.factors:
                if f.dense is not None and f.length >= TREE_SAMPLER_MIN:
                    big[id(f)] = Marginals(f, w.basis)
            for shot in range(w.requested):
                w.phase = "executing shot " + str(shot + 1)
                shell = Register.__new__(Register)
                shell.__dict__.update({k: v for k, v in reg.__dict__.items() if k != "factors"})
                shell.factors = [f if id(f) in big else f.clone() for f in reg.factors]
                prefix = {}
                result = 0
                for q in range(n):
                    f = shell.find(shell.factors, q)
                    m = big.get(id(f))
                    if m is not None:
                        pos = f.position(q); pre = prefix.get(id(f), 0)
                        p1 = m.p_one(pos, pre)
                        r = self.uniform(w)
                        out = 1 if r < p1 else 0
                        prefix[id(f)] = pre | (out << pos)
                    else:
                        res = shell.measure(q, w.basis, 1, lambda: self.uniform(w), True)
                        out = res["collapseOutcome"]
                    if out == 1: result |= 1 << q
                    w.measured += 1; self._add(w, "measuredQubits", 1)
                key = bits_str(result, n)
                w.histogram[key] = w.histogram.get(key, 0) + 1
                w.completed += 1; self._add(w, "completedShots", 1); w.counter_end = self.counter
            self._add(w, "actualAmplitudeWrites", reg.amplitude_writes)
            self._add(w, "actualTensorProducts", reg.tensor_products)
            w.phase = "completed"
        except Exception as e:  # noqa: BLE001 - reported like the C# job
            w.error = str(e); w.phase = "failed"
        finally:
            w.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            w.counter_end = self.counter; w.active = False

    def capture_job_report(self, job_id):
        if self.job is None or self.job.id != job_id:
            raise RuntimeError("The requested circuit report job no longer matches the current run.")
        return self.result_obj(self.job, full=True)

    def printout(self):
        lines = ["SPINDOCTOR \u2014 COHERENT CIRCUIT MEASUREMENT PRINTOUT",
                 "Classical FP64 quantum-circuit simulation; independently replayed shots; no physical quantum hardware credit.",
                 "Measurement seed: " + self.seed, "Current measurement counter: " + str(self.counter)]
        if self.job is None:
            lines.append("No circuit run has been requested."); return "\n".join(lines) + "\n"
        w = self.job
        for k, v in self.job_obj(w).items():
            if k != "counts":
                lines.append(k + ": " + (dumps(v) if isinstance(v, (dict, list)) else (("True" if v else "False") if isinstance(v, bool) else (fmt_r(v) if isinstance(v, float) else str(v)))))
        lines.append("Exact program descriptor:"); lines.append(dumps(program_obj(w.program, True)))
        lines.append("ACTUALLY PERFORMED WORK (cartridge: one coherent replay plus per-shot sequential Born sampling):")
        for k in COUNT_KEYS: lines.append(k + ": " + str(w.counts[k]))
        lines.append("Coherent output retained: " + str(self.coherent is not None and self.coherent_hash == w.hash))
        lines.append("FULL HISTOGRAM \u2014 bitstring (qubit 0 at right)\tcompleted shots")
        total = 0
        for k in sorted(w.histogram):
            lines.append(k + "\t" + str(w.histogram[k])); total += w.histogram[k]
        lines.append("Distinct outcomes: " + str(len(w.histogram))); lines.append("Histogram total: " + str(total))
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------ persistence
    def to_state(self):
        st = {"seed": self.seed, "counter": str(self.counter), "memoryLimitBytes": str(self.memory_limit),
              "selected": self.selected, "programs": [program_obj(p, True) for p in self.programs.values()],
              "lifetime": counts_obj(self.lifetime), "programCapacity": self.capacity,
              "ownershipSerial": str(self.ownership_serial),
              "presetOwnedPrograms": [{"name": self.programs[k].name, "presetId": self.owned_by.get(k, ""), "serial": str(s)}
                                      for k, s in self.owned_serial.items() if k in self.programs]}
        if self.job is not None:
            j = self.job_obj(self.job); j["program"] = program_obj(self.job.program, True)
            j["histogramFull"] = dict(self.job.histogram); j["coherentOutputStatus"] = self.job.snapshot
            st["job"] = j
        return st

    def load_state(self, st):
        if st.get("seed") != self.seed:
            raise ValueError("Circuit checkpoint seed mismatch.")
        self.counter = int(st["counter"]); self.memory_limit = int(st["memoryLimitBytes"]); self.selected = st["selected"]
        self.capacity = int(st.get("programCapacity", DEFAULT_CAPACITY))
        for d in st["programs"]:
            p = read_program(d); self.programs[p.name.lower()] = p
        self.ownership_serial = int(st.get("ownershipSerial", "0"))
        for o in st.get("presetOwnedPrograms", []):
            k = o["name"].lower()
            if k in self.programs:
                self.owned_serial[k] = int(o["serial"]); self.owned_by[k] = o.get("presetId", "")
        for k in COUNT_KEYS:
            self.lifetime[k] = int(st["lifetime"][k])
        j = st.get("job")
        if j:
            p = read_program(j["program"])
            w = Work(p, int(j["requestedShots"]), j["basis"], int(j["counterStart"]), self.memory_limit)
            w.id = j["id"]; w.active = False; w.phase = "interrupted" if j["active"] else j["phase"]
            w.completed = int(j["completedShots"]); w.measured = int(j["measuredQubits"]); w.counter_end = int(j["counterEnd"])
            w.elapsed_ms = float(j["elapsedMs"]); w.error = j["error"]; w.checkpoint_error = j["checkpointError"]
            w.histogram = {k: int(v) for k, v in j["histogramFull"].items()}
            for k in COUNT_KEYS: w.counts[k] = int(j["counts"][k])
            w.snapshot = j.get("coherentOutputStatus")
            self.job = w


def read_program(d):
    p = Program(check_name(d["name"]), integer(str(d["qubits"]), 1, MAX_LOGICAL_QUBITS), basis_index(str(d["initialBasis"])))
    for g in d["gates"]:
        words = [g["name"]] + list(g["anglesExact"]) + (["all"] if g["all"] else [str(q) for q in g["qubits"]])
        p.gates.append(parse_instruction(words, 0, p.qubits, p.name))
    if d.get("descriptorHash") and d["descriptorHash"] != program_hash(p):
        raise ValueError("Circuit program descriptor hash mismatch.")
    p.input_import = d.get("inputImport")
    return p


def update_known(known, g):
    n = g.name
    if n in ("cp", "cz", "crz", "rzz"):
        return
    if n == "swap":
        a, b = g.qubits; known[a], known[b] = known[b], known[a]; return
    if GATE_SPECS[n]["local"]:
        targets = range(len(known)) if g.all else g.qubits
        for q in targets:
            if n in ("x", "y"):
                if known[q] >= 0: known[q] = 1 - known[q]
            elif n not in ("i", "z", "s", "sdg", "t", "tdg", "rz", "p"):
                known[q] = -1
    else:
        for q in g.qubits: known[q] = -1


def memory_estimate(p):
    """Worst-case dense estimate shown before a run (cartridge guard rail)."""
    n = p.qubits
    dense = (1 << n) * 16
    return {"qubits": n, "worstCaseDenseStatevectorBytes": dense, "worstCaseDenseMiB": round(dense / 1048576.0, 3),
            "note": "Worst case if every qubit becomes entangled; factorised/sparse states use far less. "
                    "Statevector memory doubles per qubit (2^n x 16 bytes complex128)."}


class Marginals(object):
    """Exact conditional Born probabilities for sequential measurement of a dense factor."""

    def __init__(self, f, basis):
        np = backend.np if backend.numpy_enabled() else None
        k = len(f.bits)
        v = f.dense
        if np is not None and not isinstance(v, list):
            t = np.array(v, dtype=np.complex128).reshape((2,) * k)
            if basis != "z":
                r2 = 1 / math.sqrt(2)
                for ax in range(k):
                    a0 = np.take(t, 0, axis=ax); a1 = np.take(t, 1, axis=ax)
                    if basis == "y":
                        a1 = a1 * (-1j)
                    t = np.stack([(a0 + a1) * r2, (a0 - a1) * r2], axis=ax)
            p = (t.real ** 2 + t.imag ** 2).reshape(-1)
            levels = [p]
            for j in range(k - 1, 0, -1):
                cur = levels[0].reshape(2, -1)
                levels.insert(0, cur[0] + cur[1])
            self.levels = [lv.tolist() if lv.size <= 64 else lv for lv in levels]
            self.total = float(np.sum(levels[0]))
        else:
            vec = list(v)
            if basis != "z":
                r2 = 1 / math.sqrt(2)
                for j in range(k):
                    bit = 1 << j
                    for i in range(len(vec)):
                        if not i & bit:
                            a0 = vec[i]; a1 = vec[i | bit]
                            if basis == "y": a1 = a1 * (-1j)
                            vec[i] = (a0 + a1) * r2; vec[i | bit] = (a0 - a1) * r2
            p = [z.real * z.real + z.imag * z.imag for z in vec]
            levels = [p]
            for j in range(k - 1, 0, -1):
                cur = levels[0]; half = len(cur) // 2
                levels.insert(0, [cur[i] + cur[i + half] for i in range(half)])
            self.levels = levels
            self.total = sum(levels[0])

    def p_one(self, pos, prefix):
        lv = self.levels[pos]
        denom = self.total if pos == 0 else float(self.levels[pos - 1][prefix])
        num = float(lv[prefix | (1 << pos)])
        if denom <= 0:
            return 0.0
        return max(0.0, min(1.0, num / denom))
