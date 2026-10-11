#!/usr/bin/env python3
# SpinDoctor Qwerty 1.1.0 - copy the bundled spindoctor-qwerty skill where Letta Code looks for skills
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Optional. The mod (tools + /spindoctor) works without the skill; the skill adds instructions and a Bash fallback.

  python3 tools/install_skill.py                  # global: ~/.letta/skills/spindoctor-qwerty (all sessions on this computer)
  python3 tools/install_skill.py --project DIR    # one project: DIR/.agents/skills/spindoctor-qwerty
  python3 tools/install_skill.py --uninstall [--project DIR]
Letta Code picks it up in new sessions. Stdlib only; copies files, nothing else."""
import argparse, os, shutil, sys
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "spindoctor-qwerty")
ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--project", help="install into DIR/.agents/skills instead of ~/.letta/skills")
ap.add_argument("--uninstall", action="store_true", help="remove the installed copy")
a = ap.parse_args()
base = os.path.join(os.path.abspath(a.project), ".agents", "skills") if a.project else os.path.join(os.path.expanduser("~"), ".letta", "skills")
dst = os.path.join(base, "spindoctor-qwerty")
if a.uninstall:
    if os.path.isdir(dst) and os.path.isfile(os.path.join(dst, "SKILL.md")):
        shutil.rmtree(dst); print("removed", dst)
    else: print("nothing to remove at", dst)
    sys.exit(0)
if not os.path.isfile(os.path.join(SRC, "SKILL.md")): sys.exit("skill folder not found next to this script: " + SRC)
if os.path.exists(dst):
    if not os.path.isfile(os.path.join(dst, "SKILL.md")): sys.exit(dst + " exists and is not a skill folder; not touching it")
    shutil.rmtree(dst)
shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
print("installed", dst)
