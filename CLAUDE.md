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

After a discovery or rule change, run the real-repo smoke: `bash .claude/skills/rigcheck-nextup/smoke.sh` (counts only; fails on an `internal-error`).

## Structure

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first: its Task Index says which files to change for each kind of task, and its Integration Footguns list the cross-file changes. Terms (rig, layer, load class, pack, finding) are in the glossary in [docs/README.md](docs/README.md). The plan index is [docs/plans/MAIN.md](docs/plans/MAIN.md); the rule catalog is in [docs/plans/v1.md](docs/plans/v1.md).

## Rules a contributor would break

- A rule is a function of a `Rig` alone, registered with the `rule` decorator; a new rules module must be added to the import list at the bottom of `src/rigcheck/rules/__init__.py` or its rules never register, and no test fails.
- Every rule needs `tests/fixtures/<rule-id>/bad/` and `good/`, a non-empty `evidence` tuple (`official:<id>`, `sota:#<n> (<grade>)` or `rigcheck:<area>`), a docstring summary and a pack; `tests/test_rule_catalog.py` enforces this. Cite a rule's evidence from its entry in `docs/research/official.md` or `sota.md`, never from memory.
- A rule added, renamed or removed changes the catalog in `docs/plans/v1.md`; a CLI flag, exit code or JSON field changes the usage section of `README.md`. No test checks either.
- rigcheck never edits the files it checks, and makes no network or model calls outside `--deep`.
- Never read `~/.claude.json` whole, and never print file contents from the real home in a report, log or smoke output.
- No rule from `docs/research/sota.md` §6 "Folklore: do not encode"; there is no overall score.
- Fixtures and scripts that write files write LF; CRLF changes the byte counts the size rules measure.
- Imports are absolute (ruff bans relative imports); functions stay within complexity 8 and 5 arguments (ruff config in `pyproject.toml`).
