# rigcheck plan

## Current focus

- [x] Research: official guidance (Anthropic docs, AGENTS.md spec) — [research/official.md](../research/official.md)
- [x] Research: non-official state of the art, evidence-graded — [research/sota.md](../research/sota.md)
- [x] Rule catalog and architecture, approved 2026-09-27 — [v1.md](v1.md)
- [x] M1 Scaffold: Python 3.13, uv, ruff, ty, pytest, prek hooks, CI
- [ ] M2 Core engine: model, discovery (repo, user, plugin, memory layers), parsers, engine, terminal and JSON reports, instruction/import/reference/memory rules, budget report — see [v1.md](v1.md#milestones-one-pr-each-merged-as-they-land)

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
