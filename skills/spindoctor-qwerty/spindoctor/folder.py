# SpinDoctor Qwerty 1.1.0 - engine (SpinDoctor 3.1.2 parity)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""q.folder - batch-run a folder of structured inputs with SpinDoctor 3.1.2 semantics (cartridge port).

Nonrecursive: .json .qasm .qasm2 .txt .circuit .csv .pdf (case-insensitive), 1..128 supported files, 4 MiB each,
1..128 commands per file, 4096 characters per command, strict UTF-8, ordinal (code-unit) order, first failing file
stops the job.  Other files are skipped and listed in skippedFiles.  The cartridge runs the job synchronously, so
q.folder status reports the finished job and q.folder cancel has nothing left to cancel.
"""
import os
import uuid

from .inputs import compile_source, FOLDER_FILE_BYTES

SUPPORTED = (".json", ".qasm", ".qasm2", ".txt", ".circuit", ".csv", ".pdf")
MAX_FILES = 128
MAX_SAMPLES = 16384000000
FOLDER_HELP = {
    "commands": ['q.folder run path="/absolute/folder" downloads=true purge=true verify=true samples=10240',
                 'q.folder run path="/absolute/folder" verify=false', "q.folder status", "q.folder cancel"],
    "scope": "Nonrecursive inputs: .json .qasm .qasm2 .txt .circuit .csv .pdf (1..128 files, 4 MiB each, 1..128 commands per file); other files are skipped and listed in skippedFiles. The first failing file stops the job. By default every file is followed by procedural-model sample verification (q.verify samples N errors-only) before a successful receipt; this does not independently verify calculator/circuit answers. verify=false explicitly requests unverified receipts. Sample request is 1..16384000000, default 10240. The cartridge runs folder jobs synchronously (no background job to cancel).",
    "maximumVerificationSamples": MAX_SAMPLES, "defaultVerificationSamples": 10240}


def _ordinal_key(s):
    return s.encode("utf-16-be")


def _bool(v):
    if v.lower() not in ("true", "false"): raise ValueError("Folder options downloads/purge/verify must be true or false.")
    return v.lower() == "true"


def _check_dir(path):
    if not os.path.isdir(path): raise ValueError("Input folder does not exist.")
    cur = path
    while True:
        if os.path.islink(cur): raise ValueError("Reparse-point directories are not accepted.")
        parent = os.path.dirname(cur)
        if parent == cur: break
        cur = parent


def parse_fields(command):
    """Parse key=value fields of q.folder run, honouring double-quoted values with spaces."""
    rest = command.strip()[len("q.folder"):].strip()
    if not rest.lower().startswith("run"): raise ValueError("Use q.folder run path=...")
    rest = rest[3:]; fields = {}; i = 0; n = len(rest)
    while i < n:
        while i < n and rest[i].isspace(): i += 1
        if i >= n: break
        j = rest.find("=", i)
        if j < 0: raise ValueError("Folder options use key=value.")
        key = rest[i:j].strip().lower(); i = j + 1
        if i < n and rest[i] == '"':
            k = rest.find('"', i + 1)
            if k < 0: raise ValueError("Unterminated quoted folder path.")
            val = rest[i + 1:k]; i = k + 1
        else:
            k = i
            while k < n and not rest[k].isspace(): k += 1
            val = rest[i:k]; i = k
        if key not in ("path", "downloads", "purge", "verify", "samples"): raise ValueError("Unknown folder option: " + key + ".")
        if key in fields: raise ValueError("Duplicate folder option: " + key + ".")
        fields[key] = val
    return fields


def enumerate_folder(path):
    if not path or not os.path.isabs(path): raise ValueError("Folder path must be an absolute local directory.")
    resolved = os.path.abspath(path)
    _check_dir(resolved)
    files = []; skipped = []; skipped_count = 0
    with os.scandir(resolved) as it:
        for entry in it:
            if not entry.is_file(follow_symlinks=False) and not entry.is_symlink(): continue
            ext = os.path.splitext(entry.name)[1].lower()
            if ext not in SUPPORTED:
                skipped_count += 1
                if len(skipped) < 64: skipped.append(entry.name)
                continue
            if entry.is_symlink(): raise ValueError("Reparse-point input files are not accepted.")
            files.append(entry.path)
            if len(files) > MAX_FILES: raise ValueError("Folder mode supports at most 128 input files per job.")
    files.sort(key=_ordinal_key); skipped.sort(key=_ordinal_key)
    if not files:
        msg = "No supported JSON/QASM/QASM2/TXT/CIRCUIT/CSV/PDF input files were found"
        msg += (" (" + str(skipped_count) + " unsupported file(s) skipped, e.g. " + skipped[0] + "; .md and other extensions are not read).") if skipped_count else "."
        raise ValueError(msg)
    return resolved, files, skipped, skipped_count


def read_input(path):
    if os.path.islink(path): raise ValueError("Input is missing or a reparse point.")
    size = os.path.getsize(path)
    if size > FOLDER_FILE_BYTES: raise ValueError("Folder files are limited to 4 MiB each; use bounded batches for larger inputs.")
    with open(path, "rb") as f: data = f.read(FOLDER_FILE_BYTES + 1)
    if len(data) != size: raise IOError("Folder input size changed during compilation.")
    return data


def compact_job(job):
    """3.1.2 compact status: file rows without nested verification evidence."""
    j = dict(job); rows = []
    for f in job.get("files", []):
        r = dict(f); v = r.get("verification")
        if isinstance(v, dict) and v:
            r["verification"] = {k: v[k] for k in ("command", "requestedSamples", "passed", "error") if k in v}
        rows.append(r)
    j["files"] = rows
    return j


def run_folder(session, command, label_prefix=None):
    fields = parse_fields(command)
    if "path" not in fields: raise ValueError('Folder run requires path="/absolute/folder".')
    downloads = _bool(fields["downloads"]) if "downloads" in fields else True
    purge = _bool(fields["purge"]) if "purge" in fields else False
    verify = _bool(fields["verify"]) if "verify" in fields else True
    samples = 10240
    if "samples" in fields:
        if not fields["samples"].isdigit() or not (1 <= int(fields["samples"]) <= MAX_SAMPLES):
            raise ValueError("Folder verification samples must be 1..16384000000.")
        samples = int(fields["samples"])
    folder, paths, skipped, skipped_count = enumerate_folder(fields["path"])
    from .terminal import utc
    job = {"id": uuid.uuid4().hex, "folder": True, "active": True, "phase": "compiling", "folderPath": folder,
           "totalFiles": len(paths), "completedFiles": 0, "compiledFiles": 0, "currentFile": -1, "discoveredCommandTotal": 0,
           "completedCommands": 0, "files": [], "skippedFiles": skipped, "skippedFileCount": skipped_count,
           "downloads": downloads, "purge": purge, "verificationRequired": verify, "verificationSamples": samples,
           "verificationPhase": "pending" if verify else "skipped-explicit", "receiptReady": False, "error": "", "warnings": [],
           "receivedUtc": utc(), "completedUtc": "", "executionModel": "cartridge-synchronous"}
    try:
        for idx, path in enumerate(paths):
            name = os.path.basename(path)
            f = {"index": idx, "path": path, "filename": name, "phase": "compiling", "executionPhase": "compiling",
                 "verificationRequired": verify, "verificationSamples": samples, "verificationPhase": "pending" if verify else "skipped-explicit",
                 "verificationError": "", "receiptReady": False, "verification": {}, "sourceSha256": "", "sourceFormat": "",
                 "childJobId": "", "error": "", "completedCommands": 0, "totalCommands": 0, "totalCommandsKnown": False, "reports": []}
            job["currentFile"] = idx; job["files"].append(f)
            try:
                compiled = compile_source(name, read_input(path))
                f["sourceSha256"] = compiled["sourceSha256"]; f["sourceFormat"] = compiled["sourceFormat"]; f["inputName"] = name
                cmds = session.expand_presets(compiled["commands"])
                if len(cmds) < 1 or len(cmds) > 128: raise ValueError("A compiled file must produce 1..128 ordinary commands.")
                job["compiledFiles"] += 1; job["discoveredCommandTotal"] += len(cmds)
                f["totalCommands"] = len(cmds); f["totalCommandsKnown"] = True
                normalized = session.normalize(cmds, {})
                for c in normalized:
                    s = session.support(c)
                    if not s["available"]: raise ValueError(s["reason"])
                f["phase"] = f["executionPhase"] = "executing"; job["phase"] = "executing"
                stem = (label_prefix or "folder-" + job["id"][:8]) + "-%03d-%s" % (idx, "".join(ch if ch.isalnum() else "-" for ch in name)[:40])
                r = session.run_sequence(cmds, None, {}, "q.folder file " + name, stem, source={"sha256": compiled["sourceSha256"], "filename": name, "format": compiled["sourceFormat"], "parentJobId": job["id"]})
                f["childJobId"] = r["job"]["id"]; f["completedCommands"] = r["job"]["completedCommands"]; f["reports"] = r.get("reports", [])
                job["completedCommands"] += r["job"]["completedCommands"]
                f["phase"] = f["executionPhase"] = r["phase"]; f["error"] = r["error"]
                if r["phase"] != "completed": raise RuntimeError("File " + name + ": " + (r["error"] or "failed"))
                if verify:
                    f["verificationPhase"] = "verifying"
                    vc = "q.verify samples " + str(samples) + " errors-only"
                    vr = session.native(vc)
                    passed = vr["ok"] and bool((vr.get("result") or {}).get("passed", True))
                    f["verification"] = {"schema": "SPINDOCTOR/FOLDER-VERIFICATION/1", "command": vc, "requestedSamples": samples, "passed": passed,
                                         "error": vr.get("error", ""),
                                         "scope": "Samples the current procedural model's predicted amplitudes, spin and Born probability at actual domain addresses (CPU/reference comparison). Sampled descriptor verification, not certification of calculator, circuit or tranche answers."}
                    if not passed:
                        f["verificationPhase"] = "failed"; f["verificationError"] = vr.get("error", "") or "verification failed"
                        raise RuntimeError("File " + name + ": folder verification failed: " + f["verificationError"])
                    f["verificationPhase"] = "passed"
                f["receiptReady"] = True; f["reportPhase"] = "archived" if f["reports"] else "not-written"
                f["purgePhase"] = "completed" if purge else "not-requested"
                job["completedFiles"] += 1
            except Exception as e:  # noqa: BLE001 - first failure stops the job
                if f["executionPhase"] != "completed":
                    f["phase"] = f["executionPhase"] = "failed"; f["error"] = str(e)
                raise
        job["phase"] = "completed"; job["verificationPhase"] = "passed" if verify else "skipped-explicit"; job["receiptReady"] = True
    except Exception as e:  # noqa: BLE001
        job["phase"] = "failed"; job["error"] = str(e)
    finally:
        job["active"] = False; job["completedUtc"] = utc()
    return job
