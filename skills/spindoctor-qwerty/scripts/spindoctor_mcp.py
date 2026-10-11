#!/usr/bin/env python3
# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Launch the SpinDoctor stdio MCP server (stdlib only)."""
import os, sys
_here = os.path.dirname(os.path.abspath(__file__))
for _p in (_here, os.path.dirname(_here)):  # engine package lives next to scripts/ (or beside this file)
    if os.path.isdir(os.path.join(_p, "spindoctor")) and _p not in sys.path: sys.path.insert(0, _p)
from spindoctor.mcp_server import main  # noqa: E402
main()
