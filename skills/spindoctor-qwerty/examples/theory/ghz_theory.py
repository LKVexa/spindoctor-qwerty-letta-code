# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Theory: a 3-qubit GHZ circuit gives only 000 and 111.
Prediction: P(000) = 0.5 +/- 0.05 and P(111) = 0.5 +/- 0.05 over 2000 shots."""
SCRIPT = [
    "q.circuit new ghzth 3",
    "q.circuit add h 0",
    "q.circuit add cx 0 1",
    "q.circuit add cx 1 2",
    "q.circuit run shots 2000 basis z",
]
