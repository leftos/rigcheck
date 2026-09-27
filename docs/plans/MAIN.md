# rigcheck plan

## Current focus

- [ ] Research: official guidance (Anthropic docs, AGENTS.md spec) — background agent running; lands as `docs/research/official.md`
- [ ] Research: non-official state of the art, evidence-graded — background agent running; lands as `docs/research/sota.md`
- [ ] Rule catalog from both reports: `core` pack (official or grade A/B evidence only), `house` pack (opinionated, off by default), rejected list with reasons
- [ ] Architecture plan and approval (subplan to be written)

## Next up

- [ ] Scaffold: Python 3.13, uv, ruff, ty, pytest, prek hooks, CI
- [ ] Discovery of the effective setup (repo, user, plugin, memory layers)
- [ ] Deterministic checks for the `core` pack
- [ ] Reports: terminal, JSON, fix brief
- [ ] Suppression config with required reasons
- [ ] `--deep` checks via `claude -p`
- [ ] `house` pack

## Decisions (user, 2026-09-27)

- Targets: the Claude Code layer plus `AGENTS.md` as a peer file, including drift between the two.
- Scope of a run: the effective setup; findings tagged by layer. Only the checked project's own memory folder is read.
- Checks: deterministic and offline by default; semantic checks only behind `--deep`, sent through headless `claude -p`.
- Fixes: findings carry a fix and rigcheck can write a fix brief; it never edits the checked files.
- No overall score: findings ranked by severity × load cost.
- Rule packs: `core` (sourced) and `house` (the user's conventions, written generically, enabled per machine).
- Suppression: per-repo config, each entry with a mandatory reason; a reasonless suppression is itself a finding.
- Public repo `leftos/rigcheck`, MIT license.
