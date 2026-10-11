# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""SpinDoctor Scripter Cartridge 1.1.0 - a pure-Python port of the SpinDoctor 3.1.2 quantum-circuit
simulator.  Classical FP64 simulation only: no quantum hardware, no quantum advantage.

    from spindoctor import Session
    s = Session("workspace")            # persistent workspace (seeds, circuits, reports)
    s.run_command("q.circuit new bell 2")
"""
from .terminal import Session, ENGINE_VERSION, CARTRIDGE_VERSION, GUARDRAIL  # noqa: F401
from . import backend  # noqa: F401

__version__ = CARTRIDGE_VERSION
