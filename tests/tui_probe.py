# SpinDoctor Qwerty 1.1.0 - drive the Letta Code TUI in a pseudo-terminal and type one slash command (test helper)
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Usage: tui_probe.py OUTFILE LINE -- letta-command... ; types LINE + Enter once the TUI is idle, records the screen bytes, exits."""
import os, pty, re, select, sys, time
out, line = sys.argv[1], sys.argv[2]; cmd = sys.argv[sys.argv.index("--") + 1:]
pid, fd = pty.fork()
if pid == 0:
    os.environ.update(TERM="xterm-256color", COLUMNS="200", LINES="60"); os.execvp(cmd[0], cmd)
import fcntl, struct, termios
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 60, 200, 0, 0))
buf = b""; t0 = time.time(); typed = None
def pump(sec):
    global buf
    end = time.time() + sec
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try: d = os.read(fd, 65536)
            except OSError: return
            if not d: return
            buf += d
pump(12)
for ch in line: os.write(fd, ch.encode()); time.sleep(0.03)
pump(1.5); os.write(fd, b"\r"); pump(15)
os.write(fd, b"\x03"); pump(1); os.write(fd, b"\x03"); pump(1)
try: os.kill(pid, 9)
except OSError: pass
plain = re.sub(rb"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-B]|\r", b"", buf)
open(out, "wb").write(plain)
