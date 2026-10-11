# E2E results - spindoctor-qwerty-letta-code 1.1.0

Host: **the real Letta Code CLI 0.34.10** (npm `@letta-ai/letta-code`), run by `tests/letta_host_check.py` in a throwaway home with
the local backend (no account) and an "openai-compatible" provider pointing at `tests/stub_llm.py`, a scripted local model (no
network, no key) that calls the tools in a fixed order. The package is installed with `letta install`; `/spindoctor` is typed into
the real TUI through a pseudo-terminal. Python 3.13.5.

Not tested: a real model choosing the tools, Letta Cloud agents, Letta Code Desktop, Windows, macOS.

## Host check: 32/32

| Result | Check |
|---|---|
| PASS | package.json#letta: manifestVersion 1, mod entries exist, known capabilities, GPL-3.0-or-later, version 1.1.0 |
| PASS | every .py/.mjs file has a GPL-3.0-or-later SPDX header (30 files) |
| PASS | SKILL.md: frontmatter name/description, guardrail, mod tools + /spindoctor, no other host's variables |
| PASS | Bash fallback: every CLI command in SKILL.md runs as written from the skill folder (6 commands, bundled files only) |
| PASS | tests/mod_smoke.mjs (fake host: capability guards, approval flags, all tools, /spindoctor, disposer): 14 checks |
| PASS | tools/install_skill.py: global (~/.letta/skills) and --project (.agents/skills) installs, --uninstall removes |
| PASS | Letta Code CLI runs without an account: 0.34.10 (Letta Code) |
| PASS | local backend + openai-compatible provider -> local stub (no login, no key) |
| PASS | letta install <local folder> -> package enabled with tools, commands |
| PASS | installed package carries the engine + skill (self-contained) |
| PASS | the model is offered the 6 mod tools alongside Letta's own |
| PASS | tool schemas reach the model as registered (closed objects; preset_id/script required) |
| PASS | 9 tool calls returned (headless, default permission mode) |
| PASS | spindoctor_functions: the Markdown function table, verbatim |
| PASS | spindoctor_list_presets ghz |
| PASS | spindoctor_run_script: Bell ok, reports under ~/spindoctor-workspace |
| PASS | spindoctor_run_preset qc-001 |
| PASS | spindoctor_report lists the newest reports |
| PASS | 298-qubit wide register with mcx7 runs (3.1.2 parity) |
| PASS | 300 qubits -> error status, 'outside the supported range' |
| PASS | theory extract: relative path resolves against the session's working directory (ctx.cwd) |
| PASS | spindoctor_test_theory from the chat: supported, 2 excerpts, valid PDF |
| PASS | turn finishes with the model's final answer |
| PASS | --permission-mode standard: read-only tool runs, report-writing tool needs approval (denied headless) |
| PASS | /spindoctor gates typed into the real TUI prints the gate table (no model call) |
| PASS | skill installed with the package's tools/install_skill.py is listed in available_skills |
| PASS | Skill loads SKILL.md, then the Bash fallback runs the CLI from the skill folder |
| PASS | installed package folder unchanged by tool use (no __pycache__, reports outside; Letta's own .letta-mod-* loader copy ignored) |
| PASS | --no-mods: no SpinDoctor tools offered |
| PASS | letta mods disable hides the tools, enable brings them back |
| PASS | shared end-to-end suite through the installed package's engine: SUMMARY 12/12 passed in 12.7s |
| PASS | letta mods remove uninstalls the package |

## Shared end-to-end suite through the installed package's engine: 12/12

Started from the installed package: `python3 ~/.letta/mods/packages/<...>/skills/spindoctor-qwerty/scripts/spindoctor_mcp.py`.

| Result | Check |
|---|---|
| PASS | initialize (server spindoctor-qwerty 1.1.0) |
| PASS | tools/list exposes the 6 tools |
| PASS | function table (Markdown, 19 sections, 298-qubit limits listed) |
| PASS | 241 presets listed |
| PASS | one script per command family (16 families, every table example) |
| PASS | 298-qubit circuit with mcx7 (prepared-factor-Born-Z) |
| PASS | q.folder on mixed .txt/.csv/.json/.qasm folder (+ .md skipped) |
| PASS | theory from a file -> supported, TXT+PDF report |
| PASS | theory from a chat summary + quoted excerpts -> supported |
| PASS | theory from an exported chat transcript -> supported |
| PASS | presets qc-001..qc-025 match the updated 3.1.2 reference (20 identical, 5 documented differences) |
| PASS | TXT+PDF reports valid (255 PDFs, 255 TXT twins) |

## Runs

- Pre-push: real Letta Code 0.34.10 host check 32/32 (local folder install), shared suite 12/12.
