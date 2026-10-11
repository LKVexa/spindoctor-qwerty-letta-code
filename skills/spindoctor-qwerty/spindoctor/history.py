# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""q.history - per-command TXT/JSON/CSV/PDF archive index (port of SpinDoctor 3.1.2 q.history list|show|export|help)."""
import datetime
import json
import os
import re
import uuid

MAX_ENTRIES = 4096
MAX_ARCHIVE_BYTES = 33554432
HELP = {"commands": ["q.history list", "q.history show ID", "q.history export ID", "q.history help"],
        "scope": "All terminal commands run through the cartridge receive a TXT/JSON/CSV/PDF archive, including failed and non-measurement commands. q.history show returns the archived JSON; q.history export returns the TXT printout plus JSON."}


class History(object):
    def __init__(self, report_dir):
        self.dir = report_dir; self.entries = []
        if self.dir and os.path.exists(self._index()):
            try:
                with open(self._index(), encoding="utf-8") as f: data = json.load(f)
                if isinstance(data, list): self.entries = [e for e in data if isinstance(e, dict) and re.match(r"^[0-9a-f]{32}$", str(e.get("id", "")))]
            except (ValueError, OSError):
                self.entries = []

    def _index(self):
        return os.path.join(self.dir, "history-index.json")

    def count(self):
        return len(self.entries)

    def add(self, command, ok, paths, payload=None):
        if not self.dir or not paths: return None
        files = {}
        for p in paths:
            ext = os.path.splitext(p)[1].lower().lstrip(".")
            if ext in ("txt", "json", "csv", "pdf"): files[ext] = os.path.relpath(p, self.dir)
        e = {"id": uuid.uuid4().hex, "utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f0Z"), "command": command[:4096],
             "ok": bool(ok), "files": files}
        self.entries.append(e)
        if len(self.entries) > MAX_ENTRIES: self.entries = self.entries[-MAX_ENTRIES:]
        tmp = self._index() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(self.entries, f)
        os.replace(tmp, self._index())
        return e["id"]

    def _find(self, i):
        if not re.match(r"^[0-9a-f]{32}$", i or ""): raise ValueError("Expected a 32-character report archive ID.")
        for e in self.entries:
            if e["id"] == i: return e
        raise ValueError("Unknown report archive ID.")

    def _read(self, e, kind):
        rel = e["files"].get(kind)
        if not rel: raise ValueError("Archive has no " + kind.upper() + " file.")
        path = os.path.normpath(os.path.join(self.dir, rel))
        if not path.startswith(os.path.normpath(self.dir) + os.sep): raise ValueError("Archive path escapes the report folder.")
        if os.path.getsize(path) > MAX_ARCHIVE_BYTES: raise ValueError("Report exceeds bounded archive read size.")
        with open(path, encoding="utf-8") as f: return f.read()

    def execute(self, w):
        if not self.dir and not (len(w) == 2 and w[1].lower() == "help"):
            raise ValueError("q.history needs a workspace with reports enabled.")
        if len(w) == 2 and w[1].lower() == "list":
            recent = self.entries[-64:]
            return {"entries": [{"id": e["id"], "utc": e["utc"], "command": e["command"][:256], "ok": e["ok"], "files": e["files"]} for e in reversed(recent)],
                    "count": len(self.entries), "listed": len(recent), "maximumEntries": MAX_ENTRIES, "scope": HELP["scope"]}
        if len(w) == 3 and w[1].lower() == "show":
            return json.loads(self._read(self._find(w[2]), "json"))
        if len(w) == 3 and w[1].lower() == "export":
            e = self._find(w[2])
            return {"id": e["id"], "printout": self._read(e, "txt"), "json": json.loads(self._read(e, "json")), "files": e["files"]}
        if len(w) == 2 and w[1].lower() == "help":
            return dict(HELP)
        raise ValueError("Use q.history list|show ID|export ID|help.")
