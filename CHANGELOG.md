# Changelog

## 1.1.0 - 2026-10-11

- Engine 1.1.0 at parity with the updated SpinDoctor 3.1.2: 1-298 logical qubits (59 per entangled factor), the `mcx7` gate,
  wide-register Born-Z sampling, `q.folder` with 3.1.2 semantics, CSV report copies and measurement-CSV fitting equations. All 241
  presets replayed. Tools `spindoctor_functions` (function table) and `spindoctor_test_theory` (theory testing from a file, pasted
  text or the chat, with TXT+JSON+PDF theory reports). 1.0 described a 29-qubit cap.
- **A real Letta mod package.** The repo root is a package with `package.json#letta` (manifestVersion 1, entry
  `mods/spindoctor-qwerty.mjs`, capabilities `tools` and `commands`), so `letta install git:github.com/LKVexa/spindoctor-qwerty-letta-code`
  (or `letta install ./clone`) installs it, and `letta mods disable/enable/update/remove` manage it. 1.0 asked you to copy a .mjs
  file and an engine folder into `~/.letta/mods/` by hand.
- **Approval where Letta's mod guide asks for it.** 1.0 registered every tool with `requiresApproval: false`. The three tools that
  write reports and simulator state (`spindoctor_run_script`, `spindoctor_run_preset`, `spindoctor_test_theory`) now leave approval
  on; the three read-only ones (`spindoctor_functions`, `spindoctor_list_presets`, `spindoctor_report`) skip it and are marked
  parallel-safe. Letta's default "unrestricted" permission mode still runs them without asking; in "standard" mode Letta asks first.
- **Paths resolve where you are working.** Tools now run the engine in the session's working directory (`ctx.cwd`), so a relative
  theory-file path means what you expect. 1.0 used Letta's own process directory. Long runs stop when the turn is cancelled
  (`ctx.signal`).
- **Python on Windows.** 1.0 ran `python` on Windows and `python3` elsewhere. 1.1.0 uses `SPINDOCTOR_PYTHON` if set (arguments allowed,
  e.g. `py -3`), else the first of `py -3`, `python`, `python3` (Windows) or `python3`, `python` that is Python 3. A missing Python is
  reported to Letta's mod diagnostics file.
- **`/spindoctor` command.** Prints the function table locally without a model call; `/spindoctor gates`, `/spindoctor presets`, or
  `/spindoctor <filter>`.
- **A skill.** `skills/spindoctor-qwerty/` (SKILL.md plus the bundled engine) explains the tools and a Bash fallback through the CLI.
  `python3 tools/install_skill.py` copies it to `~/.letta/skills/` (or `--project DIR` -> `DIR/.agents/skills/`).
- Tool descriptions and schemas: every argument described, closed object schemas, 298-qubit limits instead of 29.
- Tests: `tests/letta_host_check.py` drives the **real Letta Code CLI** (local backend, a scripted local model, no account) through
  install, all 6 tools, approval in standard mode, `/spindoctor` in the TUI, the skill, disable/enable/remove; `tests/mod_smoke.mjs`
  checks the mod with a fake host.
- License changed from MIT to GPL-3.0-or-later. Author RUSSELL PHILIP SMITHSON. README, NOTICE, COPYRIGHT and SPDX headers added.

## 1.0.0

- First release: a single mod file `spindoctor-qwerty.mjs` plus `spindoctor-qwerty-engine/`, copied into `~/.letta/mods/` by hand.
