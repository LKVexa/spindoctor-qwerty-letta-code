# SpinDoctor Qwerty 1.1.0 - local scripted model stand-in for host tests
# Copyright (C) 2026 RUSSELL PHILIP SMITHSON <russellsmithson77@outlook.com>
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. It is distributed WITHOUT ANY WARRANTY; see the LICENSE file for details.
"""Local stand-in for an OpenAI-compatible chat endpoint (no model, no network, no key).
Scripted: each request gets the next scripted step; logs request tool names and tool results to LOG (jsonl).
Letta Code variant: string arguments may contain $SKILLDIR, the skill folder found in an earlier tool result of the same
conversation (Letta prints "Skill directory: ..." with the loaded skill); the request's spindoctor_*, Skill and Bash tool schemas are logged too."""
import json, re, sys, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
PORT = int(sys.argv[1]); LOG = sys.argv[2]; SCRIPT = json.load(open(sys.argv[3]))
state = {}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"object": "list", "data": [{"id": "stub", "object": "model", "owned_by": "local"}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        msgs = body.get("messages", [])
        rec = {"path": self.path, "tools": [t.get("function", {}).get("name") for t in body.get("tools", []) or []],
               "system": next((m.get("content") for m in msgs if m.get("role") == "system"), None),
               "tool_results": [m.get("content") for m in msgs if m.get("role") == "tool"],
               "user": [m.get("content") for m in msgs if m.get("role") == "user"], "stream": body.get("stream"),
               "schemas": {t["function"]["name"]: t["function"].get("parameters") for t in body.get("tools", []) or []
                           if str(t.get("function", {}).get("name", "")).startswith("spindoctor_") or t.get("function", {}).get("name") in ("Skill", "Bash")}}
        # SCRIPT is a list of steps, or {"main": [...], "child": [...]} to script a subagent separately: Grok Build subagent
        # requests are recognised by their system prompt, so a subagent running alongside its parent can't take the parent's steps.
        who = "child" if isinstance(SCRIPT, dict) and "Grok Build subagent" in json.dumps(rec["system"] or "") else "main"
        seq = SCRIPT if isinstance(SCRIPT, list) else SCRIPT[who]
        step = seq[min(state.get(who, 0), len(seq) - 1)]
        rec["who"] = who
        # only advance on requests that carry tools (agent turns), not title/summary side calls
        if rec["tools"] and rec["tools"] != ["session_title"]: state[who] = state.get(who, 0) + 1  # Grok Build asks for a session title on the side
        else: step = {"text": "SpinDoctor"}
        hist = "\n".join(str(x) for x in rec["tool_results"] + rec["user"])  # Letta injects the loaded skill as a user message
        def fill(v):
            if isinstance(v, str):
                d = re.search(r"Skill directory: ([^\s\\'\"]+)", hist)
                return v.replace("$SKILLDIR", d.group(1)) if d else v
            if isinstance(v, dict): return {k: fill(x) for k, x in v.items()}
            if isinstance(v, list): return [fill(x) for x in v]
            return v
        step = fill(step)
        rec["step"] = step
        rec["helper_agent_offered"] = "spindoctor-qwerty-helper" in json.dumps(body)
        with open(LOG, "a") as f: f.write(json.dumps(rec) + "\n")
        cid = "chatcmpl-" + uuid.uuid4().hex[:8]; now = int(time.time())
        if "tool" in step:
            delta = {"role": "assistant", "content": None, "tool_calls": [{"index": 0, "id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                     "function": {"name": step["tool"], "arguments": json.dumps(step.get("args", {}))}}]}; fin = "tool_calls"
        else:
            delta = {"role": "assistant", "content": step["text"]}; fin = "stop"
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for ch in ({"index": 0, "delta": delta, "finish_reason": None}, {"index": 0, "delta": {}, "finish_reason": fin}):
                self.wfile.write(("data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": now, "model": "stub", "choices": [ch]}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()
        else:
            m = dict(delta); b = json.dumps({"id": cid, "object": "chat.completion", "created": now, "model": "stub", "choices": [{"index": 0, "message": m, "finish_reason": fin}],
                                             "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
