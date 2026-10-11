# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Ports of the 3.1.2 procedural product-state grid (QuantumTerminal legacy q.* commands) and the
selected tranche register terminal (SpinDoctorTrancheTerminal.cs).

The grid is a *descriptor* of independent one-qubit states (address -> angles rule); nothing is
enumerated and no entanglement exists between addresses.  q.verify samples compares the CPU rule
against an independent complex-arithmetic evaluation (the cartridge has no OpenCL GPU path)."""
import hashlib
import math
import time
import uuid

from . import qmath
from .netfmt import dumps, fmt_r
from .register import Register, GATE_SPECS, supported_gates


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read64(b):
    return int.from_bytes(b[:8], "big")


def uint(s):
    if not s.isdigit() or not s.isascii() or int(s) > 18446744073709551615:
        raise ValueError("Expected an unsigned decimal integer.")
    return int(s)


def number(s):
    try:
        v = float(s)
    except Exception:
        raise ValueError("Expected a finite decimal number.")
    if v != v or v in (math.inf, -math.inf):
        raise ValueError("Expected a finite decimal number.")
    return v


def exact(words, n):
    if len(words) != n:
        raise ValueError("Incorrect number of command arguments. Use q.help.")


def need(word, expected):
    if word.lower() != expected:
        raise ValueError("Expected '" + expected + "'.")


class Plan(object):
    def __init__(self, m, l, requested, seed, descriptor):
        self.M = m; self.L = l; self.domain = m * l; self.requested = requested; self.seed = seed; self.descriptor = descriptor
        self.exhaustive = requested >= self.domain
        self.clipped = self.domain if self.exhaustive else requested
        self.boundaries = []; self.bset = set(); self.blocked = set()
        if self.exhaustive:
            self.planned = self.domain; return
        D = self.domain; M = m; L = l
        cands = [0, M - 1, M, D - M, D - 1, D // 2, 0 if D // 2 == 0 else D // 2 - 1, M // 2, M + M // 2, (L - 1) * M + M // 2, (L // 2) * M + M - 1, (L // 2) * M + M // 2]
        for i in cands:
            if 0 <= i < D: self.bset.add(i)
        self.boundaries = sorted(self.bset)
        bc = {}
        for i in self.boundaries:
            st = ((i + 1) * self.clipped - 1) // D
            bc[st] = bc.get(st, 0) + 1
        for k, v in bc.items():
            b = D * k // self.clipped; e = D * (k + 1) // self.clipped
            if e - b == v: self.blocked.add(k)
        self.planned = self.clipped - len(self.blocked) + len(self.boundaries)

    def addresses(self):
        if self.exhaustive:
            for i in range(self.domain): yield i
            return
        D = self.domain; c = self.clipped
        for j in range(c):
            if j in self.blocked: continue
            b = D * j // c; e = D * (j + 1) // c; w = e - b; thr = ((1 << 64) - w) % w
            att = 0
            while True:
                v = read64(hashlib.sha256((self.seed + "|stratum|" + self.descriptor + "|" + str(j) + "|" + str(att)).encode("utf-8")).digest())
                att += 1
                if v < thr: continue
                i = b + v % w
                if i in self.bset: continue
                yield i; break
        for i in self.boundaries: yield i


class Grid(object):
    SCHEMA = "QUETTAFLOP/PROCEDURAL-PRODUCT-SESSION/1"

    def __init__(self, field_seed, measurement_seed, version):
        self.field_seed = field_seed; self.measurement_seed = measurement_seed; self.version = version
        self.m = 20000000; self.l = 25000000; self.t = 0.0; self.matrix = list(qmath.IDENTITY); self.prepared = False
        self.generation = 0; self.preparations = 0; self.gates = 0; self.life_prep = 0; self.life_gates = 0
        self.actual_cpu = 0; self.actual_ref = 0; self.verified = 0; self.shots = 0; self.rules = 0; self.errors = 0
        self.counter = 0; self.ledger = []; self.last_verification = None; self.last_rule = None

    def count(self):
        return self.m * self.l

    def model_descriptor(self):
        return {"productName": "SpinDoctor", "schema": "QUETTAFLOP/PROCEDURAL-PRODUCT-DESCRIPTOR/1", "gridM": str(self.m), "gridL": str(self.l),
                "stateCount": str(self.count()), "migrationT": float(self.t), "matrix": [float(x) for x in self.matrix],
                "matrixExact": [fmt_r(x) for x in self.matrix], "migrationTExact": fmt_r(self.t), "fieldSeed": self.field_seed,
                "measurementSeed": self.measurement_seed, "indexRule": "k=id%gridM; ell=floor(id/gridM); id=ell*gridM+k",
                "angleRule": "q=(k+0.5)/gridM; theta=2*asin(sqrt(q)); phi=2*pi*ell/gridL",
                "stateRule": "alpha=cos(migrationT*theta/2); beta=exp(i*migrationT*phi)*sin(migrationT*theta/2); output=matrix*[alpha,beta]",
                "equationSource": "https://chatgpt.com/s/cx_6ac93a09e8048191a1b90ffb448a453c",
                "independentProductStates": True, "entanglingGatesSupported": False,
                "complexEncoding": "Interleaved real/imaginary row-major 2x2 matrix; amplitudes retain absolute phase."}

    def descriptor_hash(self):
        return sha(dumps(self.model_descriptor()))

    def add_ledger(self, kind, details):
        import datetime
        details = dict(details); details["kind"] = kind
        details["utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0Z"
        details["modelGeneration"] = str(self.generation); details["descriptorHash"] = self.descriptor_hash()
        self.ledger.append(details)
        self.ledger = self.ledger[-64:]

    def new_generation(self, reason):
        self.generation += 1; self.preparations = 0; self.gates = 0
        self.add_ledger(reason, {"gridM": str(self.m), "gridL": str(self.l), "migrationT": float(self.t), "representedCredit": "0"})

    def address(self, s):
        i = uint(s)
        if i >= self.count(): raise ValueError("Address is outside the prepared grid.")
        return i

    def state_result(self, i, s):
        return {"address": str(i), "amplitudes": {"alpha": [s[0], s[1]], "beta": [s[2], s[3]]}, "spin": {"x": s[4], "y": s[5], "z": s[6]},
                "norm": s[7], "p1": s[8]}

    def execute(self, words):
        a = words[0].lower()
        if a == "q.prepare":
            exact(words, 4); need(words[1], "grid"); m = uint(words[2]); l = uint(words[3]); qmath.validate_grid(m, l)
            self.m = m; self.l = l; self.t = 0.0; self.matrix = list(qmath.IDENTITY); self.prepared = True; self.new_generation("prepare")
            return {"gridM": str(m), "gridL": str(l), "stateCount": str(self.count()), "migrationT": float(self.t), "modelGeneration": str(self.generation),
                    "representedCredit": "0", "note": "Grid descriptor defined. q.migrate commits modeled preparations; sampled calculations are counted separately."}
        if a == "q.migrate":
            exact(words, 3); need(words[1], "t"); t = number(words[2])
            if t < 0 or t > 1: raise ValueError("Migration t must be in [0,1].")
            self.t = t; self.matrix = list(qmath.IDENTITY); self.prepared = True
            c = self.count(); self.preparations += c; self.life_prep += c
            self.add_ledger("prepare-u-family", {"migrationT": float(t), "representedPreparations": str(c), "matrixReset": True})
            return {"migrationT": float(t), "representedPreparations": str(c), "representedRotationEquivalent": str(c * 2), "descriptorHash": self.descriptor_hash(),
                    "note": "Committed one procedural U(theta,phi,0) preparation per address. Earlier composed gates are reset; no domain enumeration occurred."}
        if a == "q.gate":
            if len(words) < 3: raise ValueError("Use q.gate NAME [angles] all.")
            need(words[-1], "all"); name = words[1].lower()
            na = 3 if name in ("u", "u3") else (1 if name in ("ry", "rz") else 0)
            if len(words) != na + 3: raise ValueError("Incorrect number of gate angles. U/U3 take theta phi lambda; ry/rz take one angle; h/x/y/z/s/t/i take none.")
            an = [number(words[i + 2]) for i in range(na)]
            nxt = qmath.multiply(qmath.matrix_for_gate(name, an), self.matrix); err = qmath.unitarity_error(nxt)
            if not qmath.is_finite(err) or err > 1e-9: raise RuntimeError("Composed matrix failed the numeric unitarity check; command was not committed.")
            self.matrix = nxt; self.prepared = True; c = self.count(); self.gates += c; self.life_gates += c
            self.add_ledger("shared-single-qubit-gate", {"gate": name, "angles": an, "representedGateApplications": str(c)})
            return {"gate": name, "angles": an, "matrix": list(self.matrix), "unitarityError": err, "representedGateApplications": str(c),
                    "descriptorHash": self.descriptor_hash(), "scope": "One shared single-qubit matrix composition represents independent gate application at every address."}
        if a == "q.state":
            exact(words, 2); i = self.address(words[1]); s = qmath.grid_state(i, self.m, self.l, self.t, self.matrix); self.actual_cpu += 1
            return self.state_result(i, s)
        if a == "q.verify":
            if len(words) == 2 and words[1].lower() == "rule": return self.verify_rule()
            if len(words) == 2 and words[1].lower() == "status": return self.last_verification
            if len(words) == 2 and words[1].lower() == "cancel": return {"cancelRequested": False, "job": self.last_verification}
            exact(words, 4); need(words[1], "samples"); need(words[3], "errors-only")
            if not words[2].isdigit() or int(words[2]) <= 0:
                raise ValueError("Sample count must be a positive decimal integer. Distinct coverage is naturally bounded by the grid.")
            return self.verify_samples(int(words[2]))
        if a == "q.measure":
            exact(words, 6); need(words[2], "basis"); need(words[4], "shots")
            i = self.address(words[1]); n = uint(words[5])
            if n < 1 or n > 100000: raise ValueError("Shots must be 1-100000.")
            basis = words[3].lower()
            if basis not in ("x", "y", "z"): raise ValueError("Measurement basis must be x, y or z.")
            s = qmath.grid_state(i, self.m, self.l, self.t, self.matrix); self.actual_cpu += 1
            sp = s[4] if basis == "x" else (s[5] if basis == "y" else s[6])
            p = max(0.0, min(1.0, (1 - sp) / 2)); start = self.counter; one = 0
            for _ in range(n):
                u = (read64(hashlib.sha256((self.measurement_seed + "|measurement|" + str(self.counter)).encode("utf-8")).digest()) >> 11) * (1.0 / 9007199254740992.0)
                self.counter += 1
                if u < p: one += 1
            self.shots += n
            return {"address": str(i), "basis": basis, "shots": str(n), "zero": str(n - one), "one": str(one), "probabilityOne": p, "meanSpin": 1 - 2.0 * one / n,
                    "seed": self.measurement_seed, "counterStart": str(start), "counterEnd": str(self.counter),
                    "scope": "Seeded classical samples of single-qubit Born probabilities; descriptor state is retained, no hardware measurement or joint entanglement.",
                    "descriptorHash": self.descriptor_hash()}
        if a == "q.reset":
            exact(words, 1); self.m = 20000000; self.l = 25000000; self.t = 0.0; self.matrix = list(qmath.IDENTITY); self.prepared = False
            self.new_generation("reset")
            return {"reset": True, "seedsPreserved": True, "measurementCounterPreserved": str(self.counter), "modelGeneration": str(self.generation),
                    "note": "Model and current-generation represented credits reset; lifetime actual counters and seeds retained."}
        if a == "q.export":
            exact(words, 2); need(words[1], "descriptor")
            v = self.model_descriptor(); v["descriptorHash"] = self.descriptor_hash(); v["measurementCounter"] = str(self.counter)
            v["representedPreparations"] = str(self.preparations); v["representedGateApplications"] = str(self.gates); v["modelGeneration"] = str(self.generation)
            v["ledger"] = list(self.ledger); v["completeLedgerRetained"] = len(self.ledger) < 64
            v["accounting"] = {"actualCpuStates": str(self.actual_cpu), "actualGpuStates": "0",
                               "verifiedSamples": str(self.verified), "measurementShots": str(self.shots), "ruleChecks": str(self.rules), "errors": str(self.errors)}
            v["verification"] = self.last_verification; v["ruleVerification"] = self.last_rule
            v["replay"] = "Recreate grid, migration and matrix; use recorded measurement seed and counter for subsequent deterministic Born sampling. Family and shared gate matrix describe a separable product state; no arbitrary entanglement is encoded."
            return v
        raise ValueError("Unknown command. Use q.help.")

    def verify_rule(self):
        t0 = time.perf_counter(); err = qmath.unitarity_error(self.matrix); ok = qmath.is_finite(err) and err <= 1e-9
        proof = {"schema": "QUETTAFLOP/PRODUCT-RULE-PROOF/1",
                 "normalizedSpinor": "cos(t*theta/2)^2 + sin(t*theta/2)^2 = 1; |exp(i*t*phi)| = 1 for real t, theta and phi.",
                 "indexing": "id = ell*gridM + k; k = id mod gridM; ell = floor(id/gridM); 0 <= id < gridM*gridL.",
                 "sharedGateComposition": "A product of unitary single-qubit matrices is unitary: (VU)^dagger(VU) = I.",
                 "spinIdentity": "X=2Re(conj(alpha)beta), Y=2Im(conj(alpha)beta), Z=|alpha|^2-|beta|^2; X^2+Y^2+Z^2=1 for a normalized pure spinor.",
                 "symbolicScope": "The indexed real-angle mathematical family and exact unitary compositions; no enumeration or proof of every floating-point implementation result.",
                 "numericMatrixTolerance": 1e-9, "numericMatrixUnitarityError": err, "passed": ok, "descriptorHash": self.descriptor_hash(),
                 "stateCount": str(self.count()), "individuallyVerifiedStateCount": "0"}
        self.rules += 1
        self.last_rule = {"passed": ok, "proof": proof, "proofHash": sha(dumps(proof)), "ruleCheckMs": (time.perf_counter() - t0) * 1000.0,
                          "scope": "Constant-size algebraic rule audit plus current floating-point 2x2 matrix check."}
        return self.last_rule

    def verify_samples(self, requested):
        if requested > 2000000:
            raise ValueError("The cartridge verifies at most 2,000,000 samples per request (pure-Python CPU path).")
        t0 = time.perf_counter(); plan = Plan(self.m, self.l, requested, self.field_seed, self.descriptor_hash())
        dig = hashlib.sha256(); done = 0; failed = 0; mx = mn = ms = 0.0; first = last = None; tol = 2e-9; cpu_ms = ref_ms = 0.0
        preview = []; pdig = hashlib.sha256()
        for i in plan.addresses():
            a0 = time.perf_counter(); c = qmath.grid_state(i, self.m, self.l, self.t, self.matrix); a1 = time.perf_counter()
            g = qmath.grid_state_reference(i, self.m, self.l, self.t, self.matrix); a2 = time.perf_counter()
            cpu_ms += (a1 - a0) * 1000; ref_ms += (a2 - a1) * 1000
            pe = max(abs(x - y) for x, y in zip(c, g)); ne = max(abs(c[7] - 1), abs(g[7] - 1))
            se = max(abs(c[4] ** 2 + c[5] ** 2 + c[6] ** 2 - 1), abs(g[4] ** 2 + g[5] ** 2 + g[6] ** 2 - 1))
            mx = max(mx, pe); mn = max(mn, ne); ms = max(ms, se)
            if pe > tol or ne > tol or se > tol: failed += 1
            dig.update(i.to_bytes(8, "big")); done += 1
            if len(preview) < 32:
                preview.append({"address": str(i), "cpu": list(c), "reference": list(g), "maxError": pe, "normError": ne, "spinError": se,
                                "tolerance": tol, "passed": not (pe > tol or ne > tol or se > tol)})
                pdig.update(i.to_bytes(8, "big"))
            if first is None: first = i
            last = i
        self.actual_cpu += done; self.actual_ref += done; self.verified += done; self.errors += failed
        el = (time.perf_counter() - t0) * 1000.0
        self.last_verification = {"id": uuid.uuid4().hex, "phase": "completed", "stage": "finished", "active": False, "requestedSamples": str(requested),
                                  "plannedSamples": str(plan.planned), "completedSamples": str(done), "sampleCount": str(done), "cpuStates": str(done),
                                  "gpuStates": "0", "verifiedCount": str(done), "errorCount": str(failed),
                                  "exhaustive": plan.exhaustive or plan.planned == plan.domain, "requestedClampedToDomain": requested > plan.domain,
                                  "boundarySamples": len(plan.boundaries), "batchLimit": 16384, "passed": failed == 0, "maxError": mx, "maxNormError": mn,
                                  "maxSpinError": ms, "tolerance": tol, "elapsedMs": el, "totalMs": el, "cpuMs": cpu_ms, "gpuMs": 0.0, "referenceMs": ref_ms,
                                  "gpuKernelMs": 0.0, "descriptorHash": plan.descriptor, "selectionSeed": plan.seed, "addressDigest": dig.hexdigest(),
                                  "addressDigestEncoding": "SHA-256 of completed compared addresses as big-endian unsigned 64-bit words in traversal order",
                                  "firstAddress": "" if first is None else str(first), "lastAddress": "" if last is None else str(last),
                                  "cancelRequested": False, "failure": "", "checkpointError": "",
                                  "selectionRule": "Every finite domain address once, in ascending order." if plan.exhaustive else "One unbiased SHA-256 offset per evenly partitioned stratum excluding boundary addresses, followed by unique deterministic boundaries; fully blocked strata are skipped.",
                                  "comparisonBackend": "cartridge: CPU rule vs independent complex-arithmetic reference (no OpenCL GPU in the cartridge)",
                                  "scope": "Completed CPU/reference amplitude, relative-phase, norm, Born P1 and spin comparisons for the captured procedural descriptor. Partial work is counted exactly; a bounded sample preview is retained, and no represented gate credit is issued. This is not verification of unrelated calculator results or a scan of arbitrary physical RAM."}
        order = ["alphaReal", "alphaImaginary", "betaReal", "betaImaginary", "spinX", "spinY", "spinZ", "normSquared", "probabilityOne"]
        ranges = []
        for k, name in enumerate(order):
            cv = [r["cpu"][k] for r in preview]; rv = [r["reference"][k] for r in preview]
            ranges.append({"component": name, "cpuMinimum": min(cv) if cv else None, "cpuMaximum": max(cv) if cv else None, "cpuFiniteRows": len(cv),
                           "referenceMinimum": min(rv) if rv else None, "referenceMaximum": max(rv) if rv else None, "referenceFiniteRows": len(rv)})
        dep = "address-dependent-migration-rule" if self.prepared and float(self.t) != 0 else "address-independent-model"
        self.last_verification.update({
            "gridM": str(self.m), "gridL": str(self.l), "stateCount": str(self.count()), "migrationT": float(self.t), "hasPrepared": self.prepared,
            "modelGeneration": str(self.generation), "sampleComponentOrder": order, "samplePreview": preview, "samplePreviewLimit": 32,
            "omittedSampleRows": str(max(0, done - len(preview))), "samplePreviewAddressDigest": pdig.hexdigest(),
            "samplePreviewAddressDigestEncoding": "SHA-256 of displayed compared addresses as big-endian unsigned64-bit words in display/traversal order",
            "samplePreviewScope": "First at most32 actually compared addresses, copied from completed CPU/reference comparisons. Omitted success rows remain counted and represented by the address digest; no sample rows are synthesized. This verifies the captured procedural descriptor, not unrelated q.math operands/results or arbitrary physical RAM contents.",
            "sampleAssessment": {"schema": "SPINDOCTOR/NATIVE-PREVIEW-ASSESSMENT/1", "capturedPreviewRows": len(preview), "finiteCpuPreviewRows": len(preview),
                                 "finiteReferencePreviewRows": len(preview), "distinctCpuPreviewVectors": len(set(tuple(r["cpu"]) for r in preview)),
                                 "distinctReferencePreviewVectors": len(set(tuple(r["reference"]) for r in preview)),
                                 "cpuPreviewConstant": len(set(tuple(r["cpu"]) for r in preview)) <= 1, "referencePreviewConstant": len(set(tuple(r["reference"]) for r in preview)) <= 1,
                                 "modelAddressDependence": dep, "modelPreparedAtCapture": self.prepared,
                                 "modelInterpretation": "The captured nonzero migration rule depends on address. Returned preview variation describes only these retained sample rows and does not establish whole-domain variation or experimental truth." if dep.startswith("address-dependent") else "The captured model does not vary with address; identical preview rows are expected.",
                                 "componentRanges": ranges,
                                 "scope": "Assessment of the captured preview, at most32 actual compared rows. These describe neither omitted rows nor the whole model domain.",
                                 "countMeaning": "completedSamples counts comparison operations in this job. Repeating the same descriptor, selection seed and sample request reuses the deterministic address plan; repeated job totals are not newly distinct union coverage."},
            "verificationMethod": "Actual RAM-resident FP64 CPU rule and an independent complex-arithmetic reference at distinct procedural model addresses (the cartridge has no OpenCL GPU path); nine returned components plus norm and pure-spin identity checks at the stated tolerance.",
            "verificationPurpose": "Materialize selected addresses of the captured virtual procedural model on CPU and an independent reference, show what that model predicts, and check agreement and mathematical state identities at the returned tolerance.",
            "predictionMeaning": "Displayed amplitudes, X/Y/Z spin expectations and probabilityOne are the captured model's numerical predictions. probabilityOne is a Born probability, not an observed shot frequency. CPU/reference agreement checks two implementations under the same model assumptions; it is not experimental or physical quantum-hardware validation, proof of unsampled addresses, or verification of unrelated calculator operands/results."})
        return self.last_verification

    def status(self):
        return {"productName": "SpinDoctor", "productVersion": self.version, "model": "procedural-product-state", "schema": self.SCHEMA, "phase": "ready",
                "hasPrepared": self.prepared, "gridM": str(self.m), "gridL": str(self.l), "stateCount": str(self.count()), "migrationT": float(self.t),
                "matrix": list(self.matrix), "modelGeneration": str(self.generation), "fieldSeed": self.field_seed, "measurementSeed": self.measurement_seed,
                "measurementCounter": str(self.counter), "representedPreparations": str(self.preparations), "representedGateApplications": str(self.gates),
                "representedPreparationRotations": str(self.preparations * 2), "lifetimeRepresentedPreparations": str(self.life_prep),
                "lifetimeRepresentedGateApplications": str(self.life_gates), "actualCpuStates": str(self.actual_cpu), "actualGpuStates": "0",
                "verifiedSamples": str(self.verified), "measurementShots": str(self.shots),
                "ruleChecks": str(self.rules), "errorCount": str(self.errors), "descriptorHash": self.descriptor_hash(), "gpuAvailable": False,
                "gpuDevice": "", "gpuError": "Cartridge build: no OpenCL/GPU path (pure Python).", "quantumHardwareGates": "0",
                "lastVerification": self.last_verification, "lastRuleVerification": self.last_rule}

    def to_state(self):
        return {k: getattr(self, k) for k in ("m", "l", "t", "matrix", "prepared", "generation", "preparations", "gates", "life_prep", "life_gates",
                                              "actual_cpu", "actual_ref", "verified", "shots", "rules", "errors", "counter", "ledger", "last_verification", "last_rule")}

    def load_state(self, st):
        for k, v in st.items(): setattr(self, k, v)


class TrancheTerminal(object):
    def __init__(self, measurement_seed):
        self.seed = sha(measurement_seed + "|SpinDoctor|selected-tranche-measurements")
        self.register = None; self.qubits = 0; self.memory_limit = 512 * 1024 * 1024; self.counter = 0
        self.life = {"actualAmplitudeWrites": 0, "actualTensorProducts": 0, "measurementShots": 0, "queryCount": 0, "actualCheckpointAmplitudeLoads": 0}
        self.binding = None; self.journal = []; self.prepared_points = 0; self.committed_gates = 0; self.job = None
        self.spinors = None

    def help(self):
        return {"commands": ["q.tranche prepare 29 zero", "q.tranche from 0", "q.tranche gate h all", "q.tranche gate cx 0 1", "q.tranche gate u 0.2 0.3 0.4 0",
                             "q.tranche gate cu 0.2 0.3 0.4 0.5 0 1", "q.tranche state 0", "q.tranche spin 0", "q.tranche measure 0 basis z shots 100",
                             "q.tranche measure 0 basis z shots 1 collapse", "q.tranche status", "q.tranche cancel", "q.tranche memory 8192", "q.tranche export",
                             "q.tranche save dense", "q.tranche resume", "q.tranche reset", "q.tranche release"],
                "gates": supported_gates(), "bitOrder": "little-endian: qubit 0 is the least-significant basis bit",
                "scope": "One selected register; multi-qubit operands entangle its coherent factors. Compact states checkpoint automatically; large dense states retain a replay journal or can be explicitly checkpointed with q.tranche save dense."}

    def job_status(self):
        return self.job

    def status(self):
        v = dict(self.register.status()) if self.register is not None else {}
        v["product"] = "SpinDoctor"; v["prepared"] = self.qubits > 0; v["suspended"] = False; v["qubits"] = self.qubits
        v["memoryLimitBytes"] = str(self.memory_limit); v["seed"] = self.seed; v["counter"] = str(self.counter)
        v["modelBinding"] = self.binding; v["replayJournalLength"] = len(self.journal); v["job"] = self.job
        v["actualPreparedSingleQubits"] = str(self.prepared_points); v["committedGateApplications"] = str(self.committed_gates)
        cur = self.register.status() if self.register is not None else {}
        life = getattr(self, "life", {})
        v["lifetimeActualWork"] = {k: str(int(life.get(k, 0)) + (int(cur.get(k, "0")) if k in cur else 0)) for k in
                                   ("actualAmplitudeWrites", "actualTensorProducts", "measurementShots", "queryCount", "actualCheckpointAmplitudeLoads")}
        v["supportedGates"] = supported_gates()
        v["checkpointAvailable"] = self.register is not None; v["checkpointStateRestored"] = bool(getattr(self, "restored", False))
        v["scope"] = "One selected coherent register of up to 298 logical qubits, with each coherent joint factor limited to 59 qubits. Tensor factors retain entanglement. Global dense-state bounds are not allocated arrays. Logical gate calls and actual amplitude work are separate from the procedural family and from physical quantum gates."
        v["accountingScope"] = "Lifetime actual work survives release, reset and restart, including replay calculations. Register counters describe its current backend history; replay does not add committed logical gate credit. Amplitude writes and tensor products are source-level work units, not FLOPS or physical quantum operations."
        return v

    def _retire(self):
        if self.register is None: return
        st = self.register.status()
        for k in ("actualAmplitudeWrites", "actualTensorProducts", "measurementShots", "queryCount"):
            try: self.life[k] = int(self.life.get(k, 0)) + int(st.get(k, "0"))
            except (TypeError, ValueError): pass

    def _replace(self, reg, n, spinors, binding):
        self._retire()
        reg.set_memory_limit(self.memory_limit)
        self.register = reg; self.qubits = n; self.spinors = spinors; self.binding = binding; self.journal = []

    def _qubit(self, s):
        if not s.isdigit() or int(s) >= self.qubits:
            raise ValueError("Qubit operand is outside the selected tranche.")
        return int(s)

    def execute(self, words, grid):
        if len(words) < 2: return self.help()
        a = words[1].lower()
        if a == "status": exact(words, 2); return self.status()
        if a == "help": exact(words, 2); return self.help()
        if a == "cancel": exact(words, 2); return {"cancelRequested": False, "job": self.job}
        if a == "prepare":
            exact(words, 4); need(words[3], "zero")
            if not words[2].isdigit() or not (1 <= int(words[2]) <= 298): raise ValueError("A selected register contains 1..298 logical qubits; each coherent joint factor is limited to 59 qubits.")
            n = int(words[2]); self._replace(Register(n), n, None, None)
            return {"prepared": True, "qubits": n, "initialState": "zero", "note": "Selected register prepared in |0...0>. No family-wide gate credit is issued."}
        if a == "from":
            exact(words, 3); i = uint(words[2]); total = grid.m * grid.l; cnt = (total + 28) // 29
            if i >= cnt: raise ValueError("Tranche index must be less than " + str(cnt) + ".")
            start = i * 29; ln = min(29, total - start)
            sp = [qmath.grid_state(start + k, grid.m, grid.l, grid.t, grid.matrix)[:4] for k in range(ln)]
            b = {"trancheIndex": str(i), "firstFamilyAddress": str(start), "lastFamilyAddress": str(start + ln - 1), "familyDescriptorHash": grid.descriptor_hash(),
                 "familyStateCount": str(total), "totalTranches": str(cnt), "partialFinalTranche": ln < 29}
            self._replace(Register(ln, sp), ln, sp, b); self.prepared_points += ln
            return {"prepared": True, "qubits": ln, "actualPreparedSingleQubits": str(ln), "modelBinding": self.binding,
                    "note": "Selected consecutive family states form an initial product register. Subsequent tranche gates operate on this snapshot independently of the family."}
        if a == "release":
            exact(words, 2); self._retire(); self.register = None; self.qubits = 0; self.binding = None; self.journal = []
            return {"released": True, "seedPreserved": True, "counter": str(self.counter)}
        if a == "memory":
            exact(words, 3); mib = uint(words[2])
            if mib == 0: raise ValueError("Memory budget must be a positive whole number of MiB.")
            b = mib * 1024 * 1024
            if self.register is not None: self.register.set_memory_limit(b)
            self.memory_limit = b
            return {"memoryLimitBytes": str(b), "note": "This is a storage budget, not a qubit-operation count or measured throughput. The backend refuses an allocation beyond the budget."}
        if a == "resume":
            exact(words, 2)
            if self.qubits == 0: raise RuntimeError("No saved tranche is selected.")
            return {"resumed": True, "alreadyLive": True, "status": self.status()}
        if self.register is None:
            raise RuntimeError("Prepare a tranche first with q.tranche prepare N zero or q.tranche from INDEX.")
        if a == "gate":
            if len(words) < 4: raise ValueError("Use q.tranche gate NAME [angles] TARGETS or all.")
            from .circuits import alias
            name = alias(words[2]); spec = GATE_SPECS.get(name)
            if spec is None: raise ValueError("Unsupported tranche gate. Use q.tranche help for available operators.")
            na = spec["angleCount"]; nt = spec["targetCount"]; all_ = words[-1].lower() == "all"
            if all_ and nt != 1: raise ValueError("Controlled and multi-qubit gates require explicit distinct qubit operands.")
            if len(words) != 3 + na + (1 if all_ else nt):
                raise ValueError("Incorrect operands. " + name.upper() + " takes " + str(na) + " angles and " + str(nt) + " qubit operands (angles first).")
            an = [number(words[3 + i]) for i in range(na)]; tg = []
            if not all_:
                for i in range(nt):
                    q = self._qubit(words[3 + na + i])
                    if q in tg: raise ValueError("Qubit operands must be distinct.")
                    tg.append(q)
            t0 = time.perf_counter(); res = self.register.gate(name, an, tg, all_)
            self.journal.append({"operation": "gate", "name": name, "anglesExact": [fmt_r(x) for x in an], "targets": tg, "all": all_})
            self.committed_gates += self.qubits if all_ else 1
            res["elapsedMs"] = (time.perf_counter() - t0) * 1000.0; res["status"] = self.register.status()
            self.job = {"id": uuid.uuid4().hex, "phase": "completed", "active": False, "operation": "gate " + name, "completed": "1", "total": "1",
                        "elapsedMs": res["elapsedMs"], "result": res, "error": "", "checkpointError": "", "cancelRequested": False}
            return {"queued": True, "job": self.job, "note": "Cartridge executes tranche gates synchronously; the job is already complete."}
        if a == "state":
            exact(words, 3)
            if not words[2].isdigit() or not words[2].isascii(): raise ValueError("Expected a nonnegative decimal basis index.")
            return self.register.state(int(words[2]))
        if a == "spin":
            exact(words, 3); q = self._qubit(words[2]); s = self.register.spin(q)
            return {"qubit": q, "spin": {"x": s[0], "y": s[1], "z": s[2]},
                    "scope": "Reduced single-qubit spin expectation in the selected coherent register; entangled qubits can have a mixed reduced state."}
        if a == "measure":
            if len(words) not in (7, 8): raise ValueError("Use q.tranche measure Q basis x|y|z shots N [collapse].")
            q = self._qubit(words[2]); need(words[3], "basis"); need(words[5], "shots"); basis = words[4].lower()
            if not words[6].isdigit(): raise ValueError("Use 1-100000 independent shots, or exactly one shot with collapse.")
            shots = int(words[6]); col = len(words) == 8
            if col: need(words[7], "collapse")
            if shots < 1 or shots > 100000 or (col and shots != 1): raise ValueError("Use 1-100000 independent shots, or exactly one shot with collapse.")
            start = self.counter; cur = [start]

            def uni():
                b = hashlib.sha256((self.seed + "|tranche-measurement|" + str(cur[0])).encode("utf-8")).digest(); cur[0] += 1
                return (read64(b) >> 11) * (1.0 / 9007199254740992.0)
            r = self.register.measure(q, basis, shots, uni, col)
            r["seed"] = self.seed; r["counterStart"] = str(start); r["counterEnd"] = str(cur[0]); self.counter += shots
            if col: self.journal.append({"operation": "collapse", "qubit": q, "basis": basis, "counter": str(start)})
            return r
        if a == "reset":
            exact(words, 2); self.register.reset(); self.binding = None; self.journal = []
            return {"reset": True, "qubits": self.qubits, "seedPreserved": True, "counter": str(self.counter)}
        if a == "export":
            exact(words, 2)
            return {"register": self.register.export(), "modelBinding": self.binding, "seed": self.seed, "counter": str(self.counter),
                    "status": self.status(), "replayJournal": list(self.journal)}
        if a == "save":
            if len(words) not in (2, 3): raise ValueError("Use q.tranche save [dense].")
            dense = len(words) == 3
            if dense: need(words[2], "dense")
            return {"saved": True, "stateFile": "spindoctor-tranche.json", "largeDenseCheckpointAllowed": dense}
        raise ValueError("Unknown tranche command. Use q.tranche help.")

    # persistence: compact registers are stored as factor amplitudes
    def to_state(self):
        st = {"counter": self.counter, "memory_limit": self.memory_limit, "qubits": self.qubits, "binding": self.binding,
              "journal": self.journal, "prepared_points": self.prepared_points, "committed_gates": self.committed_gates, "life": dict(self.life)}
        if self.register is not None:
            ex = self.register.export()
            st["register"] = ex.get("factors") if ex.get("stateIncluded") else None
        return st

    def load_state(self, st):
        from .register import Factor
        self.counter = st["counter"]; self.memory_limit = st["memory_limit"]; self.qubits = st["qubits"]; self.binding = st["binding"]
        self.journal = st["journal"]; self.prepared_points = st["prepared_points"]; self.committed_gates = st["committed_gates"]
        if "life" in st: self.life.update(st["life"])
        fs = st.get("register"); self.restored = bool(self.qubits and fs)
        if self.qubits and fs:
            r = Register(self.qubits); r.factors = []
            for fd in fs:
                f = Factor(fd["qubits"])
                for k, re_, im in fd["amplitudes"]: f.set(int(k), complex(float(re_), float(im)))
                r._maybe_dense(f, [f]) if False else None
                r.factors.append(f)
            r.factors.sort(key=lambda f: f.bits[0]); r.memory_limit = self.memory_limit
            self.register = r
