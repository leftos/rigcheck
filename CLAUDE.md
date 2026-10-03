# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

rigcheck is a local validator for the instruction layer of coding agents (`CLAUDE.md`, `AGENTS.md`, `.claude/rules`, skills, agents, hooks, settings, memory). It is one Python 3.13 package that builds a `Rig` from the effective setup, runs registered rules over it, and reports ranked findings as text or JSON.

## Commands

Run from the repo root; CI (`.github/workflows/ci.yml`) runs the same four checks on Ubuntu and Windows.

```
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pytest tests/test_rule_catalog.py -k <rule-id>   # one rule's catalog and fixture tests
uv run rigcheck check [PATH] [--format text|json] [--home DIR] [--window SIZE] [--only ID[,ID...]] [--fail-on error|warn|info] [--sibling DIR]...
prek install                                            # hooks: ruff, ty, actionlint, zizmor
```

Run test suites, the smoke and hook-running commits through the gate, `pwsh tools/gate.ps1 -Log .tmp/<name>.log -TimeoutSeconds <n> -Slot light|heavy -- <command…>` (`tools/gate.ps1` is the user-level gate's launcher; on a machine without the gate it runs the command at below-normal priority and still writes the log). The slots and timeouts per command are in the nextup profile's "Agents and gates".

After a discovery or rule change, run the real-repo smoke: `pwsh tools/gate.ps1 -Log .tmp/smoke.log -TimeoutSeconds 700 -Slot light -- bash .claude/skills/rigcheck-nextup/smoke.sh` (counts only; fails on an `internal-error`).

## Structure

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first: its Task Index says which files to change for each kind of task, and its Integration Footguns list the cross-file changes. Terms (rig, layer, load class, pack, finding) are in the glossary in [docs/README.md](docs/README.md). The plan lives in Linear: every task is a Linear issue in team RIG, grouped into projects worked in order (the `rigcheck-nextup` profile names the order). [docs/plans/MAIN.md](docs/plans/MAIN.md) is a generated snapshot of it, never edited by hand: change Linear, then regenerate it. A steer or finding mid-task gets an **add** first, before any reply in prose. The operations (**add**, **land**, **triage** and the rest) are in `~/.claude/docs/plan-operations.md`. The rule catalog is in [docs/plans/v1.md](docs/plans/v1.md).

## Rules a contributor would break

- A rule is a function of a `Rig` alone, registered with the `rule` decorator; a new rules module must be added to the import list at the bottom of `src/rigcheck/rules/__init__.py` or its rules never register, and no test fails.
- Every rule needs `tests/fixtures/<rule-id>/bad/` and `good/`, a non-empty `evidence` tuple (`official:<id>`, `sota:#<n> (<grade>)` or `rigcheck:<area>`), a docstring summary and a pack; `tests/test_rule_catalog.py` enforces this. Cite a rule's evidence from its entry in `docs/research/official.md` or `sota.md`, never from memory.
- A rule added, renamed or removed changes the catalog in `docs/plans/v1.md`; a CLI flag, exit code or JSON field changes the usage section of `README.md`. No test checks either.
- rigcheck never edits the files it checks, and makes no network or model calls outside `--deep`.
- Never read `~/.claude.json` whole, and never print file contents from the real home in a report, log or smoke output.
- No rule from `docs/research/sota.md` §6 "Folklore: do not encode"; there is no overall score.
- Fixtures and scripts that write files write LF; CRLF changes the byte counts the size rules measure.
- Imports are absolute (ruff bans relative imports); functions stay within complexity 8 and 5 arguments (ruff config in `pyproject.toml`).
