# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Port of SpinDoctor 3.1.2 TrancheRegister (SpinDoctorTranches.cs).

A coherent 1..298-logical-qubit register (each joint factor <=59 qubits) stored as a list of independent factor blocks.  Each factor
holds a sparse dictionary {index: complex} or, once it is dense enough (>=1024 basis states
and >=1/6 occupied), a dense vector (Python list, or numpy complex128 when available).
Entangling gates merge the factors they touch (exact tensor product); a collapsing
measurement contracts the measured qubit back out into its own factor.  Semantics, gate
matrices, operand order, memory-budget estimates and Born sampling follow the C# source.
"""
import math
from . import backend
from .qmath import matrix_for_gate, is_finite
from .netfmt import fmt_r

TILE_BITS = 20
TILE_COMPLEX = 1 << TILE_BITS
LOCAL0 = ("h", "x", "y", "z", "s", "sdg", "t", "tdg", "i", "sx", "sxdg")
LOCAL1 = ("rx", "ry", "rz", "p")
JOINT0 = ("cx", "cy", "cz", "ch", "swap")
JOINT1 = ("cp", "crx", "cry", "crz", "rxx", "ryy", "rzz", "rzx")


def supported_gates():
    out = []
    for n in LOCAL0: out.append({"name": n, "angleCount": 0, "targetCount": 1, "local": True})
    for n in LOCAL1: out.append({"name": n, "angleCount": 1, "targetCount": 1, "local": True})
    out.append({"name": "u", "angleCount": 3, "targetCount": 1, "local": True})
    for n in JOINT0: out.append({"name": n, "angleCount": 0, "targetCount": 2, "local": False})
    for n in JOINT1: out.append({"name": n, "angleCount": 1, "targetCount": 2, "local": False})
    out.append({"name": "cu", "angleCount": 4, "targetCount": 2, "local": False})
    for n in ("ccx", "cswap"): out.append({"name": n, "angleCount": 0, "targetCount": 3, "local": False})
    out.append({"name": "mcx7", "angleCount": 0, "targetCount": 8, "local": False})
    return out


MAX_LOGICAL_QUBITS = 298
MAX_FACTOR_QUBITS = 59


GATE_SPECS = {g["name"]: g for g in supported_gates()}

# Cartridge guard rails (not part of 3.0.3): a dense factor above this many qubits is refused
# before allocation with a clear message.  Configurable via q.cartridge limit dense-qubits N.
LIMITS = {"max_dense_qubits": 26 if backend.numpy_enabled() else 22}


class MemoryBudgetError(Exception):
    pass


def dense_cap_check(k):
    cap = LIMITS["max_dense_qubits"]
    if k > cap:
        need = (1 << k) * 16
        raise MemoryBudgetError(
            "Cartridge dense-factor cap: this operation needs a joint %d-qubit factor (dense statevector %s MiB "
            "of complex128 before working copies) but the cap is %d qubits (%s MiB). Classical simulation memory doubles "
            "with every qubit. Raise it explicitly with 'q.cartridge limit dense-qubits N' (or --max-dense-qubits N) only "
            "if this machine has the RAM." % (k, _mib(need), cap, _mib((1 << cap) * 16)))


def _mib(b):
    return ("%.1f" % (b / 1048576.0)) if b < 1 << 40 else ("%.3e" % (b / 1048576.0))


def _np():
    return backend.np if backend.numpy_enabled() else None


class Factor(object):
    __slots__ = ("bits", "sparse", "dense")

    def __init__(self, bits):
        self.bits = list(bits)
        self.sparse = {}
        self.dense = None

    @property
    def length(self):
        return 1 << len(self.bits)

    def dense_bytes(self):
        return 0 if self.dense is None else self.length * 16

    def est_bytes(self):
        if self.dense is None:
            return 4096 + len(self.sparse) * 96
        tiles = (self.length + TILE_COMPLEX - 1) // TILE_COMPLEX
        return 4096 + tiles * 8 + self.dense_bytes()

    def get(self, i):
        if self.dense is None:
            return self.sparse.get(i, 0j)
        return complex(self.dense[i])

    def set(self, i, v):
        if self.dense is None:
            if v == 0:
                self.sparse.pop(i, None)
            else:
                self.sparse[i] = v
        else:
            self.dense[i] = v

    def nonzero(self):
        if self.dense is None:
            return list(self.sparse.items())
        np = _np()
        if np is not None and not isinstance(self.dense, list):
            idx = np.flatnonzero(self.dense)
            vals = self.dense[idx]
            return [(int(i), complex(v)) for i, v in zip(idx.tolist(), vals.tolist())]
        return [(i, v) for i, v in enumerate(self.dense) if v != 0]

    def nonzero_count(self):
        if self.dense is None:
            return len(self.sparse)
        np = _np()
        if np is not None and not isinstance(self.dense, list):
            return int(np.count_nonzero(self.dense))
        return sum(1 for v in self.dense if v != 0)

    def clone(self):
        c = Factor(self.bits)
        if self.dense is None:
            c.sparse = dict(self.sparse)
        else:
            c.sparse = None
            c.dense = self.dense[:] if isinstance(self.dense, list) else self.dense.copy()
        return c

    def position(self, bit):
        try:
            return self.bits.index(bit)
        except ValueError:
            raise RuntimeError("Qubit is absent from a factor.")

    def make_dense(self):
        dense_cap_check(len(self.bits))
        np = _np()
        if np is not None:
            v = np.zeros(self.length, dtype=np.complex128)
            if self.sparse:
                keys = list(self.sparse.keys())
                v[np.array(keys, dtype=np.int64)] = np.array([self.sparse[k] for k in keys], dtype=np.complex128)
        else:
            v = [0j] * self.length
            for k, val in self.sparse.items():
                v[k] = val
        self.dense = v
        self.sparse = None

    def to_vector(self):
        """Full vector (numpy if enabled) in this factor's local index order."""
        np = _np()
        if self.dense is not None:
            return self.dense
        if np is not None:
            v = np.zeros(self.length, dtype=np.complex128)
            for k, val in self.sparse.items():
                v[k] = val
            return v
        v = [0j] * self.length
        for k, val in self.sparse.items():
            v[k] = val
        return v


def local_matrix(name, a):
    """TrancheRegister.LocalMatrix: row-major [g00, g01, g10, g11] complex entries."""
    if name == "rx":
        c = math.cos(a[0] / 2); s = math.sin(a[0] / 2)
        return [complex(c, 0), complex(0, -s), complex(0, -s), complex(c, 0)]
    if name == "p":
        return [1 + 0j, 0j, 0j, complex(math.cos(a[0]), math.sin(a[0]))]
    if name == "sdg":
        return [1 + 0j, 0j, 0j, complex(0, -1)]
    if name == "tdg":
        return [1 + 0j, 0j, 0j, complex(math.cos(-math.pi / 4), math.sin(-math.pi / 4))]
    if name in ("sx", "sxdg"):
        sign = 1.0 if name == "sx" else -1.0
        return [complex(.5, .5 * sign), complex(.5, -.5 * sign), complex(.5, -.5 * sign), complex(.5, .5 * sign)]
    g = matrix_for_gate(name, a)
    return [complex(g[0], g[1]), complex(g[2], g[3]), complex(g[4], g[5]), complex(g[6], g[7])]


def process_private_bytes():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t)]
        pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.PrivateUsage)
    except Exception:
        pass
    try:
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        return 0


class Register(object):
    def __init__(self, qubits, spinors=None):
        if qubits < 1 or qubits > MAX_LOGICAL_QUBITS:
            raise ValueError("Selected registers support 1..298 logical qubits, with each coherent joint factor limited to 59 qubits.")
        if spinors is not None and len(spinors) != qubits:
            raise ValueError("Supply one four-component spinor per qubit.")
        self.qubits = qubits
        self.memory_limit = 512 * 1024 * 1024
        self.logical_gates = 0; self.amplitude_writes = 0; self.tensor_products = 0
        self.measurement_shots = 0; self.query_count = 0
        self.factors = []
        for q in range(qubits):
            s = [1.0, 0.0, 0.0, 0.0] if spinors is None else spinors[q]
            if s is None or len(s) != 4:
                raise ValueError("Each spinor has [alpha real,alpha imaginary,beta real,beta imaginary].")
            for v in s:
                if not is_finite(v):
                    raise ValueError("Spinor components must be finite.")
            norm = s[0] * s[0] + s[1] * s[1] + s[2] * s[2] + s[3] * s[3]
            if abs(norm - 1) > 2e-9:
                raise ValueError("Each initial spinor must be normalized.")
            f = Factor([q]); f.set(0, complex(s[0], s[1])); f.set(1, complex(s[2], s[3]))
            self.factors.append(f); self.amplitude_writes += 2

    # ------------------------------------------------------------------ memory
    def est_bytes(self):
        return sum(f.est_bytes() for f in self.factors)

    def dense_bytes(self):
        return sum(f.dense_bytes() for f in self.factors)

    def sparse_bytes(self):
        return sum(f.est_bytes() for f in self.factors if f.dense is None)

    def nonzero_estimate(self):
        return sum((len(f.sparse) if f.dense is None else f.dense_bytes() // 16) for f in self.factors)

    def set_memory_limit(self, b):
        if b < self.est_bytes() or b < 1024 * 1024:
            raise ValueError("Budget must hold current state and be at least 1 MiB.")
        self.memory_limit = b

    def budget(self, extra):
        live = self.est_bytes()
        if extra > self.memory_limit or live > self.memory_limit - extra:
            raise MemoryBudgetError("Tranche memory budget exceeded before commit. Raise q.tranche memory explicitly; dense 29-qubit state alone is 8 GiB, and transactional work needs additional memory.")

    def check_qubit(self, q):
        if q < 0 or q >= self.qubits:
            raise ValueError("Qubit is outside the selected register.")

    def find(self, lst, q):
        for f in lst:
            if q in f.bits:
                return f
        raise RuntimeError("Missing qubit factor.")

    def clone(self):
        r = Register.__new__(Register)
        r.qubits = self.qubits; r.memory_limit = self.memory_limit
        r.logical_gates = self.logical_gates; r.amplitude_writes = self.amplitude_writes
        r.tensor_products = self.tensor_products; r.measurement_shots = self.measurement_shots
        r.query_count = self.query_count
        r.factors = [f.clone() for f in self.factors]
        return r

    # ------------------------------------------------------------------ gates
    def gate(self, name, angles, qubits, all_=False, cancel=None):
        name = (name or "").lower()
        if name == "toffoli": name = "ccx"
        spec = GATE_SPECS.get(name)
        if spec is None:
            raise ValueError("Unknown tranche operator. Use q.tranche help.")
        angles = list(angles or [])
        if len(angles) != spec["angleCount"]:
            raise ValueError("Incorrect gate angle count.")
        for a in angles:
            if not is_finite(a) or abs(a) > 1e12:
                raise ValueError("Angles must be finite within +/-1e12 radians.")
        if all_:
            if not spec["local"]:
                raise ValueError("all is supported for local operators only. Controlled and joint operators require explicit distinct qubits.")
            qubits = list(range(self.qubits))
        elif qubits is None or len(qubits) != spec["targetCount"]:
            raise ValueError("Incorrect gate qubit count.")
        seen = set()
        for q in qubits:
            self.check_qubit(q)
            if q in seen:
                raise ValueError("Gate qubits must be distinct.")
            seen.add(q)
        selected = []
        for f in self.factors:
            for q in qubits:
                if q in f.bits:
                    if f not in selected: selected.append(f)
                    break
        work = []
        writes = [0]; products = [0]
        try:
            if spec["local"]:
                self.budget(sum(f.est_bytes() for f in selected))
                work = [f.clone() for f in selected]
                g = local_matrix(name, angles)
                for q in qubits:
                    f = self.find(work, q)
                    self._apply_single(f, q, [], g, writes)
                    self._maybe_dense(f, work)
            else:
                if sum(len(f.bits) for f in selected) > MAX_FACTOR_QUBITS:
                    raise RuntimeError("Gate would merge a coherent factor beyond the 59-qubit local addressing limit. The selected register is unchanged.")
                joint = self._merge(selected, products, writes)
                work.append(joint)
                if name in ("swap", "cswap"):
                    self._apply_swap(joint, qubits, name == "cswap", writes)
                elif name in ("rxx", "ryy", "rzz", "rzx"):
                    self._apply_pauli_rotation(joint, name, angles[0], qubits, writes)
                else:
                    target = qubits[-1]; controls = list(qubits[:-1])
                    local = "x" if name in ("ccx", "mcx7") else name[1:]
                    la = angles[:3] if name == "cu" else angles
                    g = local_matrix(local, la)
                    if name == "cu":
                        ph = complex(math.cos(angles[3]), math.sin(angles[3]))
                        g = [x * ph for x in g]
                    self._apply_single(joint, target, controls, g, writes)
                self._maybe_dense(joint, work)
            for f in selected:
                self.factors.remove(f)
            self.factors.extend(work)
            self.factors.sort(key=lambda f: f.bits[0])
            self.logical_gates += len(qubits) if all_ else 1
        finally:
            self.amplitude_writes += writes[0]; self.tensor_products += products[0]
        return {"gate": name, "qubits": list(qubits), "angles": angles,
                "logicalApplications": str(len(qubits) if all_ else 1),
                "actualAmplitudeWrites": str(writes[0]), "actualTensorProducts": str(products[0])}

    def _merge(self, selected, products, writes):
        bits = sorted(b for f in selected for b in f.bits)
        k = len(bits)
        np = _np()
        nnz = 1
        for f in selected:
            nnz *= f.nonzero_count()
        dense_target = (1 << k) >= 1024 and nnz * 96 >= (1 << k) * 16
        if np is not None and dense_target and (1 << k) > 4096:
            # Vectorised exact tensor product, then axis permutation to sorted bit order.
            dense_cap_check(k)
            self.budget((1 << k) * 16 * 2)
            tensor = np.ones((), dtype=np.complex128); axes_bits = []
            for f in selected:
                t = np.asarray(f.to_vector(), dtype=np.complex128).reshape((2,) * len(f.bits)) if f.bits else f.to_vector()
                tensor = np.multiply.outer(tensor, t)
                axes_bits.extend(reversed(f.bits))   # tensor axis j <-> bit
                products[0] += f.nonzero_count() * 1
            order = [axes_bits.index(b) for b in reversed(bits)]
            vec = np.ascontiguousarray(np.transpose(tensor, order)).reshape(-1)
            merged = Factor(bits); merged.sparse = None; merged.dense = vec
            nz = int(np.count_nonzero(vec)); writes[0] += nz; products[0] += nz
            if nz * 96 < merged.length * 16:
                merged.dense = None
                idx = np.flatnonzero(vec)
                merged.sparse = {int(i): complex(v) for i, v in zip(idx.tolist(), vec[idx].tolist())}
            return merged
        merged = Factor(bits); merged.set(0, 1 + 0j)
        extra = merged.est_bytes()
        for f in selected:
            nxt = Factor(merged.bits)
            pos = [merged.bits.index(b) for b in f.bits]
            fnz = f.nonzero()
            shifted_cache = []
            for key, val in fnz:
                sh = 0
                for j, p in enumerate(pos):
                    if key & (1 << j): sh |= 1 << p
                shifted_cache.append((sh, val))
            for okey, oval in merged.nonzero():
                for sh, val in shifted_cache:
                    nxt.set(okey | sh, oval * val); products[0] += 1; writes[0] += 1
            self.budget(extra + nxt.est_bytes())
            merged = nxt; extra = merged.est_bytes()
            self._maybe_dense(merged, [merged])
        return merged

    def _maybe_dense(self, f, working):
        if f.dense is not None or f.length < 1024 or len(f.sparse) * 96 < f.length * 16:
            return
        extra = f.length * 16 + sum(w.est_bytes() for w in working)
        self.budget(extra)
        f.make_dense()

    def _apply_single(self, f, qubit, controls, g, writes):
        bit = 1 << f.position(qubit); mask = 0
        for q in controls:
            mask |= 1 << f.position(q)
        g0, g1, g2, g3 = g
        if f.dense is not None:
            np = _np()
            if np is not None and not isinstance(f.dense, list):
                k = len(f.bits)
                t = f.dense.reshape((2,) * k)
                s0 = [slice(None)] * k; s1 = [slice(None)] * k
                for q in controls:
                    ax = k - 1 - f.position(q); s0[ax] = 1; s1[ax] = 1
                ax = k - 1 - f.position(qubit); s0[ax] = 0; s1[ax] = 1
                a = t[tuple(s0)].copy(); b = t[tuple(s1)].copy()
                t[tuple(s0)] = g0 * a + g1 * b
                t[tuple(s1)] = g2 * a + g3 * b
                writes[0] += 2 * a.size
                return
            v = f.dense
            for i in range(f.length):
                if not (i & bit) and (i & mask) == mask:
                    j = i | bit; a = v[i]; b = v[j]
                    v[i] = g0 * a + g1 * b; v[j] = g2 * a + g3 * b; writes[0] += 2
            return
        pairs = {}
        for i in f.sparse.keys():
            if (i & mask) == mask:
                pairs[i & ~bit] = None
        sp = f.sparse
        for i in pairs:
            j = i | bit
            a = sp.get(i, 0j); b = sp.get(j, 0j)
            na = g0 * a + g1 * b; nb = g2 * a + g3 * b
            if na == 0: sp.pop(i, None)
            else: sp[i] = na
            if nb == 0: sp.pop(j, None)
            else: sp[j] = nb
            writes[0] += 2
        self.budget(f.est_bytes() + len(pairs) * 32)

    def _apply_swap(self, f, qubits, controlled, writes):
        off = 1 if controlled else 0
        a = 1 << f.position(qubits[off]); b = 1 << f.position(qubits[off + 1])
        control = (1 << f.position(qubits[0])) if controlled else 0
        if f.dense is not None:
            np = _np()
            if np is not None and not isinstance(f.dense, list):
                k = len(f.bits)
                t = f.dense.reshape((2,) * k)
                sl = [slice(None)] * k
                if controlled:
                    sl[k - 1 - f.position(qubits[0])] = slice(1, 2)
                sub = t[tuple(sl)]
                ax_a = k - 1 - f.position(qubits[off]); ax_b = k - 1 - f.position(qubits[off + 1])
                sub[...] = np.swapaxes(sub, ax_a, ax_b).copy()
                writes[0] += sub.size // 2
                return
            v = f.dense
            for i in range(f.length):
                if (i & control) == control and not (i & a) and (i & b):
                    j = i ^ a ^ b; v[i], v[j] = v[j], v[i]; writes[0] += 2
            return
        sources = {}
        for key in list(f.sparse.keys()):
            if (key & control) == control and ((key & a) == 0) != ((key & b) == 0):
                sources[(key | b) & ~a] = None
        for i in sources:
            j = i ^ a ^ b
            vi = f.get(i); f.set(i, f.get(j)); f.set(j, vi); writes[0] += 2

    def _apply_pauli_rotation(self, f, name, angle, qubits, writes):
        a = 1 << f.position(qubits[0]); b = 1 << f.position(qubits[1])
        c = math.cos(angle / 2); s = math.sin(angle / 2)
        np = _np()
        if name == "rzz":
            ph_pos = complex(math.cos(-1 * angle / 2), math.sin(-1 * angle / 2))   # sign=+1 -> -angle/2
            ph_neg = complex(math.cos(1 * angle / 2), math.sin(1 * angle / 2))     # sign=-1 -> +angle/2
            if f.dense is not None and np is not None and not isinstance(f.dense, list):
                idx = np.arange(f.length, dtype=np.int64)
                par = ((idx & a) != 0) ^ ((idx & b) != 0)
                f.dense *= np.where(par, ph_neg, ph_pos)
                writes[0] += f.length
                return
            keys = range(f.length) if f.dense is not None else [k for k, _ in f.nonzero()]
            for i in keys:
                sign = (1 if not (i & a) else -1) * (1 if not (i & b) else -1)
                f.set(i, (ph_pos if sign == 1 else ph_neg) * f.get(i)); writes[0] += 1
            return
        flip = b if name == "rzx" else (a | b)

        def sign_of(i):
            if name == "ryy":
                return -((1 if not (i & a) else -1) * (1 if not (i & b) else -1))
            if name == "rzx":
                return 1 if not (i & a) else -1
            return 1
        if f.dense is not None and np is not None and not isinstance(f.dense, list):
            idx = np.arange(f.length, dtype=np.int64)
            low = idx[idx < (idx ^ flip)]
            hi = low ^ flip
            sa = np.where((low & a) == 0, 1.0, -1.0); sb = np.where((low & b) == 0, 1.0, -1.0)
            if name == "ryy": sg = -(sa * sb)
            elif name == "rzx": sg = sa
            else: sg = np.ones(low.size)
            coef = 1j * (-s * sg)
            ai = f.dense[low].copy(); aj = f.dense[hi].copy()
            f.dense[low] = c * ai + coef * aj
            f.dense[hi] = c * aj + coef * ai
            writes[0] += 2 * low.size
            return
        if f.dense is not None:
            pairs = [i for i in range(f.length) if i < (i ^ flip)]
        else:
            pd = {}
            for key, _ in f.nonzero():
                pd[min(key, key ^ flip)] = None
            pairs = list(pd)
        for i in pairs:
            j = i ^ flip; sg = sign_of(i)
            ai = f.get(i); aj = f.get(j); coef = complex(0, -s * sg)
            f.set(i, c * ai + coef * aj); f.set(j, c * aj + coef * ai); writes[0] += 2

    # ------------------------------------------------------------------ queries
    def amplitude(self, basis_index):
        if basis_index < 0 or basis_index >= (1 << self.qubits):
            raise ValueError("basisIndex")
        value = 1 + 0j
        for f in self.factors:
            idx = 0
            for j, b in enumerate(f.bits):
                if basis_index & (1 << b): idx |= 1 << j
            value *= f.get(idx)
        self.query_count += 1
        return [value.real, value.imag]

    def state(self, basis_index):
        a = self.amplitude(basis_index)
        return {"basisIndex": str(basis_index), "amplitude": a, "probability": a[0] * a[0] + a[1] * a[1],
                "bitOrder": "little-endian; qubit 0 is least significant"}

    def spin(self, qubit):
        self.check_qubit(qubit)
        f = self.find(self.factors, qubit)
        bit = 1 << f.position(qubit)
        np = _np()
        if f.dense is not None and np is not None and not isinstance(f.dense, list):
            k = len(f.bits); ax = k - 1 - f.position(qubit)
            t = f.dense.reshape((2,) * k)
            a0 = np.take(t, 0, axis=ax); a1 = np.take(t, 1, axis=ax)
            p0 = float(np.sum(a0.real ** 2 + a0.imag ** 2)); p1 = float(np.sum(a1.real ** 2 + a1.imag ** 2))
            cross = complex(np.sum(np.conj(a0) * a1))
            self.query_count += 1
            return [2 * cross.real, 2 * cross.imag, p0 - p1]
        x = y = z = 0.0
        for key, v in f.nonzero():
            p = v.real * v.real + v.imag * v.imag
            if not (key & bit):
                z += p
                cross = v.conjugate() * f.get(key | bit)
                x += 2 * cross.real; y += 2 * cross.imag
            else:
                z += -p
        self.query_count += 1
        return [x, y, z]

    def measure(self, qubit, basis, shots, uniform, collapse):
        self.check_qubit(qubit)
        basis = (basis or "").lower()
        if basis not in ("x", "y", "z"):
            raise ValueError("Basis must be x, y or z.")
        if shots < 1 or shots > 100000:
            raise ValueError("shots")
        if collapse and shots != 1:
            raise ValueError("A collapsing measurement takes exactly one shot. Repeated shots normally sample independent copies without collapse.")
        sp = self.spin(qubit)
        prob = max(0.0, min(1.0, (1 - sp[{"x": 0, "y": 1, "z": 2}[basis]]) / 2))
        one = 0
        for _ in range(shots):
            r = uniform()
            if not is_finite(r) or r < 0 or r >= 1:
                raise ValueError("Uniform draw must be in [0,1).")
            if r < prob: one += 1
            self.measurement_shots += 1
        if collapse:
            self._collapse(qubit, basis, one)
        return {"qubit": qubit, "basis": basis, "shots": str(shots), "zero": str(shots - one), "one": str(one),
                "probabilityOne": prob, "collapsed": collapse, "collapseOutcome": one if collapse else None,
                "scope": "Seeded classical Born sampling of the selected coherent register; no physical quantum measurement."}

    def _collapse(self, qubit, basis, outcome):
        old = self.find(self.factors, qubit)
        position = old.position(qubit); bit = 1 << position
        r2 = 1 / math.sqrt(2)
        if basis == "z":
            e0 = 1 + 0j if outcome == 0 else 0j; e1 = 1 + 0j if outcome == 1 else 0j
        elif basis == "x":
            e0 = complex(r2, 0); e1 = complex(r2 if outcome == 0 else -r2, 0)
        else:
            e0 = complex(r2, 0); e1 = complex(0, r2 if outcome == 0 else -r2)
        bra0 = e0.conjugate(); bra1 = e1.conjugate()
        measured = Factor([qubit]); remainder = None; writes = 0
        try:
            if len(old.bits) == 1:
                cval = bra0 * old.get(0) + bra1 * old.get(1)
                norm = cval.real * cval.real + cval.imag * cval.imag
                if not is_finite(norm) or norm <= 0:
                    raise RuntimeError("Sampled an impossible collapse outcome.")
                phase = cval / math.sqrt(norm)
                measured.set(0, e0 * phase); measured.set(1, e1 * phase); writes += 2
            else:
                rest = [q for q in old.bits if q != qubit]
                remainder = Factor(rest)
                np = _np()
                if old.dense is not None and np is not None and not isinstance(old.dense, list):
                    k = len(old.bits); ax = k - 1 - position
                    t = old.dense.reshape((2,) * k)
                    cvec = (bra0 * np.take(t, 0, axis=ax) + bra1 * np.take(t, 1, axis=ax)).reshape(-1)
                    norm = float(np.sum(cvec.real ** 2 + cvec.imag ** 2))
                    if not is_finite(norm) or norm <= 0:
                        raise RuntimeError("Sampled an impossible collapse outcome.")
                    cvec = cvec * (1 / math.sqrt(norm))
                    nz = int(np.count_nonzero(cvec))
                    if remainder.length >= 1024 and nz * 96 >= remainder.length * 16:
                        remainder.sparse = None; remainder.dense = np.ascontiguousarray(cvec)
                    else:
                        idx = np.flatnonzero(cvec)
                        remainder.sparse = {int(i): complex(v) for i, v in zip(idx.tolist(), cvec[idx].tolist())}
                    writes += nz
                else:
                    if old.dense is None:
                        pairs = {}
                        for idx in old.sparse.keys():
                            pairs[idx & ~bit] = None
                        zeros = list(pairs)
                    else:
                        zeros = [((i & (bit - 1)) | ((i & ~(bit - 1)) << 1)) for i in range(remainder.length)]
                    vals = []
                    norm = 0.0
                    for zero in zeros:
                        cval = bra0 * old.get(zero) + bra1 * old.get(zero | bit)
                        norm += cval.real * cval.real + cval.imag * cval.imag
                        vals.append(cval)
                    if not is_finite(norm) or norm <= 0:
                        raise RuntimeError("Sampled an impossible collapse outcome.")
                    scale = 1 / math.sqrt(norm)
                    nonzero = sum(1 for v in vals if v != 0)
                    if remainder.length >= 1024 and nonzero * 96 >= remainder.length * 16:
                        remainder.make_dense()
                    for zero, cval in zip(zeros, vals):
                        cs = cval * scale
                        if cs == 0: continue
                        index = (zero & (bit - 1)) | ((zero >> (position + 1)) << position)
                        remainder.set(index, cs); writes += 1
                measured.set(0, e0); measured.set(1, e1); writes += 2
            self.factors.remove(old)
            if remainder is not None:
                self.factors.append(remainder)
            self.factors.append(measured)
            self.factors.sort(key=lambda f: f.bits[0])
        finally:
            self.amplitude_writes += writes

    def reset(self):
        self.factors = []
        for q in range(self.qubits):
            f = Factor([q]); f.set(0, 1 + 0j); self.factors.append(f); self.amplitude_writes += 2

    def sample_z(self, uniform):
        """3.1.2-298 SampleZ: one independent Born-Z draw from the retained factor product.  Each factor is sampled
        jointly (sorted local keys, one uniform per factor, including fixed factors); the state is not changed."""
        basis = 0
        for f in self.factors:
            entries = sorted(f.nonzero(), key=lambda kv: kv[0])
            self.budget(4096 + len(entries) * 48)
            norm = 0.0
            for _, v in entries:
                p = v.real * v.real + v.imag * v.imag
                if not is_finite(p): raise RuntimeError("Nonfinite coherent-factor probability.")
                norm += p
            self.query_count += 1
            if not entries or not is_finite(norm) or norm <= 0 or abs(norm - 1) > 2e-7:
                raise RuntimeError("Born sampling requires a normalized nonempty coherent factor.")
            draw = uniform()
            if not is_finite(draw) or draw < 0 or draw >= 1: raise ValueError("Uniform draws must lie in [0,1).")
            threshold = draw * norm; cumulative = 0.0; selected = entries[-1][0]
            for k, v in entries:
                cumulative += v.real * v.real + v.imag * v.imag
                if threshold < cumulative: selected = k; break
            for j, b in enumerate(f.bits):
                if selected & (1 << j): basis |= 1 << b
        self.measurement_shots += self.qubits
        return basis

    # ------------------------------------------------------------------ status/export
    def status(self):
        fs = []
        for f in self.factors:
            fs.append({"qubits": list(f.bits), "basisStateCount": str(f.length),
                       "storage": "sparse-joint" if f.dense is None else "segmented-FP64-joint",
                       "nonzeroAmplitudes": str(len(f.sparse)) if f.dense is None else "not scanned",
                       "estimatedBytes": str(f.est_bytes())})
        return {"qubits": self.qubits, "maximumLogicalQubits": MAX_LOGICAL_QUBITS, "maximumJointFactorQubits": MAX_FACTOR_QUBITS,
                "basisStateCount": str(1 << self.qubits),
                "backend": "factorized-product" if len(self.factors) == self.qubits else "coherent-factor-blocks",
                "factors": fs, "allocatedDenseStateBytes": str(self.dense_bytes()),
                "estimatedSparseStateBytes": str(self.sparse_bytes()),
                "allocatedStateBytesEstimate": str(self.est_bytes()), "memoryLimitBytes": str(self.memory_limit),
                "worstDenseStateBytes": str((1 << self.qubits) * 16),
                "worstTransactionalDenseGateBytes": str((1 << self.qubits) * 32),
                "logicalGateApplications": str(self.logical_gates), "actualAmplitudeWrites": str(self.amplitude_writes),
                "actualTensorProducts": str(self.tensor_products), "measurementShots": str(self.measurement_shots),
                "queryCount": str(self.query_count), "restoredAmplitudeLoads": "0",
                "canCompactCheckpoint": self.dense_bytes() <= 64 * 1024 * 1024 and self.nonzero_estimate() <= (64 * 1024 * 1024) // 24,
                "processPrivateBytes": str(process_private_bytes()),
                "memoryAccountingScope": "Cartridge port: dense bytes are exact for numpy/list storage; sparse dictionary storage uses the SpinDoctor conservative estimate (96 B per amplitude). Process bytes are this Python process.",
                "bitOrder": "little-endian",
                "scope": "One selected coherent register; factor blocks preserve genuine entanglement. No whole-domain entangling throughput or physical quantum gates are claimed."}

    def export(self):
        result = {"schema": "SPINDOCTOR/COHERENT-TRANCHE/1", "status": self.status(), "stateIncluded": False}
        if self.dense_bytes() > 32768 * 16 or self.nonzero_estimate() > 32768:
            result["note"] = "Use a binary checkpoint for this state; a large amplitude array is not inserted into an HTTP response."
            return result
        fs = []
        for f in self.factors:
            fs.append({"qubits": list(f.bits), "amplitudes": [[str(k), fmt_r(v.real), fmt_r(v.imag)] for k, v in f.nonzero()]})
        result["factors"] = fs; result["stateIncluded"] = True
        return result

    def full_state(self):
        """Dense full statevector (list or numpy) - only for small registers / validation."""
        np = _np()
        dense_cap_check(self.qubits)
        n = self.qubits
        if np is not None:
            tensor = np.ones((), dtype=np.complex128); axes_bits = []
            for f in self.factors:
                tensor = np.multiply.outer(tensor, np.asarray(f.to_vector(), dtype=np.complex128).reshape((2,) * len(f.bits)))
                axes_bits.extend(reversed(f.bits))
            order = [axes_bits.index(b) for b in reversed(range(n))]
            return np.ascontiguousarray(np.transpose(tensor, order)).reshape(-1)
        return [complex(*self.amplitude(i)) for i in range(1 << n)]
