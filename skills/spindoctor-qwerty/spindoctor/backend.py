# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Optional numpy acceleration. Pure stdlib is the baseline; numpy is used automatically
when importable unless SPINDOCTOR_NO_NUMPY=1 is set (or set_numpy(False) is called)."""
import os

np = None
if os.environ.get("SPINDOCTOR_NO_NUMPY", "").strip() not in ("1", "true", "yes"):
    try:
        import numpy as np  # noqa: F401
    except Exception:  # pragma: no cover - numpy absent is the normal baseline
        np = None

_enabled = np is not None


def numpy_enabled():
    return _enabled and np is not None


def set_numpy(flag):
    global _enabled
    _enabled = bool(flag) and np is not None
    return _enabled


def name():
    return ("numpy " + np.__version__) if numpy_enabled() else "python-stdlib"
