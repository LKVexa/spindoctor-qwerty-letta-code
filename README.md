# SpinDoctor Qwerty mod for Letta Code

A [Letta Code](https://docs.letta.com/letta-code) **mod package** that runs the **SpinDoctor 3.1.2 quantum-circuit simulator** on
your computer: `q.*` circuit scripts (1-298 logical qubits), the 241 built-in presets, folders of command files (`q.folder`), and
theory tests from a file, pasted text or the chat itself, each with TXT, PDF, JSON and CSV reports. It adds 6 agent tools, a
`/spindoctor` command and an optional skill.

> **Honest limits.** SpinDoctor is a classical FP64 simulator. It is not a quantum computer, does not connect to quantum hardware,
> and gives no quantum speed-up or advantage. One entangled group is limited to 59 qubits and dense groups are limited by memory
> (2^n x 16 bytes). Registers wider than 29 qubits sample in basis Z only. Histograms are seeded Born samples.

Version 1.1.0 - engine 1.1.0 (SpinDoctor 3.1.2 parity) - Python 3.8+, standard library only - no network, no account and no keys
for the mod itself. Tested with the real Letta Code CLI 0.34.10 on Linux; see [Testing](#testing).

## Install

```bash
letta install git:github.com/LKVexa/spindoctor-qwerty-letta-code
```

Or clone the repo and run `letta install ./spindoctor-qwerty-letta-code`. Then run `/reload` in open sessions (new sessions load it
on start). `letta mods list` shows it as `tools, commands`; `letta mods disable|enable|update|remove <spec>` manage it. Letta loads
mods on the computer running Letta Code, so this works with local and cloud-hosted agents alike.

Mods are trusted local code: this one runs the bundled Python engine and nothing else (no events, permission overlays, providers,
network or startup work). Read `mods/spindoctor-qwerty.mjs` before installing.

**Optional skill** (instructions plus a Bash fallback through the CLI):

```bash
python3 tools/install_skill.py                 # from a clone: copies skills/spindoctor-qwerty to ~/.letta/skills/
python3 tools/install_skill.py --project .     # or only for one project: ./.agents/skills/
```

**Python.** The mod uses `SPINDOCTOR_PYTHON` if set (a command, arguments allowed, e.g. `py -3`), otherwise the first of `py -3`,
`python`, `python3` (Windows) or `python3`, `python` (macOS/Linux) that is Python 3. If none works, the tool returns an error and the
problem is written to `~/.letta/mods/diagnostics/latest.json`.

## What's in the repo

| Path | What it is |
|---|---|
| `package.json` | Letta package manifest (`letta.manifestVersion` 1, entry `mods/spindoctor-qwerty.mjs`, capabilities `tools`, `commands`) |
| `mods/spindoctor-qwerty.mjs` | The mod: 6 tools (`letta.tools.register`) and `/spindoctor` (`letta.commands.register`), capability-guarded, with a disposer |
| `skills/spindoctor-qwerty/` | Skill (`SKILL.md`), the bundled engine (`spindoctor/`), CLI and MCP server (`scripts/`), examples, LICENSE |
| `tools/install_skill.py` | Copies the skill to `~/.letta/skills/` or a project's `.agents/skills/` (or removes it) |
| `FUNCTIONS.md` | The full function table with a runnable example for every command |
| `tests/` | Real-host check, mod smoke test, scripted local model, TUI driver, shared end-to-end suite, reference outputs |

## Using it

- Ask in plain language: "show the SpinDoctor functions", "run a 3-qubit GHZ circuit", "test the Bell state theory we discussed".
- Type `/spindoctor` for the function table (no model call); `/spindoctor gates`, `/spindoctor presets`, `/spindoctor ghz`.
- Tools: `spindoctor_functions`, `spindoctor_list_presets`, `spindoctor_report` (read-only: no approval, parallel-safe) and
  `spindoctor_run_script`, `spindoctor_run_preset`, `spindoctor_test_theory` (they write reports and state, so they keep Letta's
  approval: in the default "unrestricted" permission mode they run straight away, in "standard" mode Letta asks first).
- Tools run in the session's working directory, so relative file paths resolve there. Reports and state go to
  `~/spindoctor-workspace` unless a call passes `workspace`; nothing is written into the installed package.

## SpinDoctor Qwerty - plugin tools

| Function | What it does | Command to type |
|---|---|---|
| Function table (spindoctor_functions) | Show this table in chat | Ask: "show the SpinDoctor functions" |
| Run a script (spindoctor_run_script) | Run any q.* lines above; returns results + TXT/JSON/CSV/PDF report paths | Ask: "run q.circuit new bell 2 / q.circuit add h 0 / ..." |
| Run a preset (spindoctor_run_preset) | Run qc-001..qc-241 with overrides | Ask: "run preset qc-067 with shots=64" |
| List presets (spindoctor_list_presets) | Search the 241 presets | Ask: "list presets about Grover" |
| Read a report (spindoctor_report) | List/read TXT reports (PDF/JSON paths alongside) | Ask: "show the newest SpinDoctor report" |
| Test a theory from a file (spindoctor_test_theory source=file) | Read a .txt/.md/.pdf/.py/.json/.csv/.q attachment, then hypothesis -> prediction -> q.* script -> run -> verdict + TXT/PDF theory report | Ask: "test the theory in C:/notes/theory.md" (the host must pass the file path/content) |
| Test a theory from text (spindoctor_test_theory source=text) | Same pipeline for pasted text | Ask: "test this theory: a Hadamard on \|0> gives 50/50" |
| Test the theory we discussed (spindoctor_test_theory source=chat) | The AI summarises the theory from the conversation (claims, assumptions, variables, prediction), you confirm, then it is tested; quoted excerpts go in the report under 'Source: chat history'. An exported chat transcript (.txt/.md/.json/.html) also works | Ask: "test the theory we discussed" or "test the theory in my exported chat C:/chats/conversation.json" |

Every command family is listed with a runnable example in **[FUNCTIONS.md](FUNCTIONS.md)** (the exact table the tool shows):
circuits (`q.circuit`, including 298-qubit wide registers and the `mcx7` gate), queries (`q.query`), the tranche register
(`q.tranche`), the procedural grid, presets and sequences, resource planning, math calculators, physics models, lessons, noise, error
correction, compilation, algorithms, inputs/folders/history (`q.input`, `q.folder`, `q.history`) and the cartridge commands.

## Theory testing

`spindoctor_test_theory` turns a claim into a test: hypothesis -> measurable prediction -> `q.*` script -> run -> compare -> a TXT +
JSON + PDF **theory test report** with the hypothesis, script, raw results, verdict (*supported*, *not supported* or *inconclusive*)
and limits.

- **From a file:** .txt, .md, .pdf, .py, .json, .csv or .q. In Letta Code, give the file's path (absolute, or relative to the session's working directory), or paste the text.
- **From pasted text.**
- **From the chat history:** say *"test the theory we discussed"*. The model writes a short summary (claims, assumptions, variables,
  measurable prediction), shows it to you to confirm or correct, then passes it with optional quoted excerpts; the report records them
  under *Source: chat history*. Exported chat transcripts (.txt/.md/.json/.html from ChatGPT, Claude and others) also work.
- The plugin cannot read your conversation or attachments by itself: only the model sees them, and very long conversations may already
  be truncated by the context window.

Sample theory files and chat transcripts are in `skills/spindoctor-qwerty/examples/theory/`. The two sample
PDFs are stored as text; run `python3 skills/spindoctor-qwerty/examples/theory/make_sample_pdfs.py` to
recreate them.

## Folder ingestion (`q.folder`)

`q.folder run path="<folder>"` runs every supported file at the top level of a folder (.txt, .csv, .json, .qasm, .qasm2, .circuit,
.pdf) in ordinal name order: 1-128 supported files, at most 4 MiB per file, 1-128 commands per file and 4096 characters per command,
strict UTF-8. Other files (for example .md) are skipped and listed. The first failing file stops the job.


## Testing

| Test | Command |
|---|---|
| Real Letta Code host check (installs this folder) | `python3 tests/letta_host_check.py --letta $(which letta)` |
| Same, installing from GitHub | `python3 tests/letta_host_check.py --source git:github.com/LKVexa/spindoctor-qwerty-letta-code` |
| Mod smoke test (no Letta needed, Node 18+) | `node tests/mod_smoke.mjs` |
| End-to-end suite only | `python3 tests/e2e_mcp.py --server python3 skills/spindoctor-qwerty/scripts/spindoctor_mcp.py --examples skills/spindoctor-qwerty/examples/theory` |

**Real host, scripted model.** Letta Code (npm `@letta-ai/letta-code`, free) runs with no account in its local backend, with an
"openai-compatible" provider. `tests/letta_host_check.py` gives it a throwaway home and points that provider at `tests/stub_llm.py`, a
local scripted model (no network, no key) that calls the tools in a fixed order. With the real CLI it then: installs the package
with `letta install`, checks the 6 tools and their schemas reach the model, calls all of them (function table, GHZ presets, a Bell
circuit, qc-001, reports, a 298-qubit `mcx7` circuit, a 300-qubit rejection, a theory file by relative path, a theory from the chat:
verdict *supported*, PDF written), checks approval in `--permission-mode standard` (read-only tool runs, `spindoctor_run_preset` is
held for approval), types `/spindoctor gates` into the real TUI in a pseudo-terminal, installs the skill and has the model load it
and run the CLI through Bash, checks `--no-mods`, `letta mods disable/enable/remove`, that the installed package is unchanged, and
runs the shared end-to-end suite through the installed engine. Not tested: a real model choosing the tools, Letta Cloud agents,
Letta Code Desktop, Windows, macOS. Results: [E2E_RESULTS.md](E2E_RESULTS.md).

## Author and license

Author: **RUSSELL PHILIP SMITHSON** <russellsmithson77@outlook.com>

Copyright (C) 2026 RUSSELL PHILIP SMITHSON. Licensed under the GNU General Public License v3.0 or later (`GPL-3.0-or-later`): see
[LICENSE](LICENSE), [NOTICE](NOTICE) and [COPYRIGHT](COPYRIGHT). Letta Code is a Letta product; this mod is not affiliated with
Letta.
