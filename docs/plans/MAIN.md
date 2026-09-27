# rigcheck plan

## Current focus

- [x] Research: official guidance (Anthropic docs, AGENTS.md spec) — [research/official.md](../research/official.md)
- [x] Research: non-official state of the art, evidence-graded — [research/sota.md](../research/sota.md)
- [x] Rule catalog and architecture, approved 2026-09-27 — [v1.md](v1.md)
- [x] M1 Scaffold: Python 3.13, uv, ruff, ty, pytest, prek hooks, CI
- [x] M2a Core engine: model, discovery (repo, user, plugin, memory layers), parsers, engine, terminal and JSON reports, `check` command, instruction-file and `@import` rules (CM1–CM3, CM13–CM16, CM19)
- [ ] M2b Reference rules (backticked/linked paths and npm/just/make scripts that do not exist; sota #1–2), memory rules (MM1, MM3, MM4 accepting both top-level `type` and `metadata.type`), and the budget report (≈tokens per every-turn source, skill listing vs 1% of the window, agent descriptions vs 15k) — see [v1.md](v1.md#rule-catalog-v1-ids-from-docsresearch)
- [ ] M2b Home walk: `rigcheck check ~` takes 23 s because a non-git target walks every folder, and 204 of 219 nested CLAUDE.md hits sit under AppData, mostly pytest temp dirs. Decide what the walk skips (AppData and dot-folders, or no nested walk when the target is home) and make it finish in a few seconds. Redirecting pytest's `--basetemp` into the repo's `.tmp/` was tried and breaks the fixtures, because their copies then sit inside rigcheck's own git repo.

## Next up

- [ ] M3 Component rules: skills, agents, commands, output styles, rules directory
- [ ] M4 Config rules: hooks, settings (vendored schema), MCP, secrets, duplication
- [ ] M5 Suppressions, advice pack, `explain`, `brief`
- [ ] M6 `--deep` checks via `claude -p`
- [ ] M7 House pack, the `rigcheck` Claude Code skill, install docs

## Decisions (user, 2026-09-27)

- Targets: the Claude Code layer plus `AGENTS.md` as a peer file, including drift between the two.
- Scope of a run: the effective setup; findings tagged by layer. Only the checked project's own memory folder is read.
- Checks: deterministic and offline by default; semantic checks only behind `--deep`, sent through headless `claude -p`.
- Fixes: findings carry a fix and rigcheck can write a fix brief; it never edits the checked files.
- No overall score: findings ranked by severity × load cost.
- Rule packs: `core` (sourced) and `house` (the user's conventions, written generically, enabled per machine).
- Suppression: per-repo config, each entry with a mandatory reason; a reasonless suppression is itself a finding.
- Public repo `leftos/rigcheck`, MIT license.
