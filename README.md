# rigcheck

A local validator for the instruction layer of coding agents: `CLAUDE.md`, `AGENTS.md`, `.claude/rules`, skills, subagent definitions, hooks, settings and memory files. It reports ranked findings and writes fix briefs an agent can carry out.

Status: early development. The instruction-file, `@import`, reference (stale paths and npm/just/make commands), auto-memory and component (skills, commands, agents, rules folder, output styles, listing budgets) rules work, and both reports open with a context budget; the rest of the catalog is being built per [docs/plans/MAIN.md](docs/plans/MAIN.md), the snapshot of the plan in Linear.

## Usage

```
uv run rigcheck check [PATH] [--format text|json] [--home DIR] [--window SIZE] [--packs PACK[,PACK...]] [--only ID[,ID...]] [--fail-on error|warn|info] [--sibling DIR]...
uv run rigcheck rules [--format text|json]
uv run rigcheck explain RULE_ID [--format text|json]
uv run rigcheck brief [PATH] [-o FILE] [--home DIR] [--window SIZE] [--packs PACK[,PACK...]] [--only ID[,ID...]] [--sibling DIR]...
```

Checks the setup Claude Code loads for `PATH` (default: the current directory): the repo's instruction files and `.claude/` folder, your `~/.claude`, enabled plugins, and that project's own memory folder. `rigcheck check ~` checks only `~/.claude`, its plugins and its memory. Both reports open with a context budget: ≈tokens for each file loaded every turn, and the skill listing and agent descriptions against Claude Code's limits (1% of the context window, set with `--window`, default `200k`; 15,000 tokens). The budget itself never changes the exit status; a listing past its limit also raises a warn finding (`skill-listing-over-budget`, `agent-descriptions-over-budget`), so `--window` moves that finding too. The text report groups findings by layer, with findings about the whole setup (the two over-budget warnings) under their own `setup` heading first; `--format json` gives a stable schema for agents.

Every rule belongs to a pack:
- `core`: defects backed by the docs or by graded evidence;
- `advice`: info-only style advice that never fails a default run;
- `house`: opinionated conventions.

`--packs PACK[,PACK...]` picks the packs whose rules run (default `core,advice`; `house` runs only when named). Rules outside the selection do not run, except a rule named in `--only`, and the engine and suppression rules, which always run.

`--only ID[,ID...]` reports only the findings of those rule ids (the other rules still run; an unknown id exits 2 and names the closest ids). `--fail-on error|warn|info` sets the lowest finding severity that makes the exit status 1 (default `error`). Exit status: 0 clean, 1 a finding at or above `--fail-on`, 2 a usage error. Repo docs (`docs/**/*.md` and `Docs/**/*.md`, without `plans/` or `archive/` folders) are discovered as kind `doc`. A line containing `<!-- rigcheck: allow reference-path-missing -->` silences that rule on the line and the next.

A `.rigcheck.toml` at the repo root silences findings the repo has judged not to apply. Each `[[suppress]]` entry names one `rule` id, an optional `path` glob relative to the repo root (for example `docs/**`), and a `reason`. A suppressed finding is left out of the findings and the exit status. The text report's last line adds `· N suppressed`, and `--format json` lists them under `suppressed` (each finding's fields plus `reason`) and counts them in `summary.suppressed`. `--only` filters them too.

Some findings are never suppressed:
- findings in `~/.claude`, plugins and memory, and in files outside the repo root;
- `internal-error` and `discovery-error`;
- the two suppression rules themselves. An entry with no reason is `suppression-no-reason` (warn), and one that matches nothing is `suppression-unused` (info).

`rigcheck rules` lists every rule, one line each: id, pack, severity and summary, ordered by pack (`core`, `advice`, `house`) and then id. `--format json` gives a list of objects with `id`, `pack`, `severity`, `summary`, `fix` and `evidence`.

`rigcheck explain RULE_ID` prints one rule's id, pack, severity, summary, fix and evidence, and the rule-area doc under `docs/rules/` that covers it when run from a checkout (an installed copy has no docs, so that line is left out). `--format json` gives the same fields as one object, with `docs` null when no doc is found. An unknown id exits 2 and names the closest ids. Evidence strings point into the research: `official:CM2` is entry CM2 of `docs/research/official.md`, `sota:#2 (A)` is row 2 of `docs/research/sota.md` with its evidence grade, and `rigcheck:<area>` is a probe or decision of rigcheck's own.

`rigcheck brief` writes the findings of the same run as a Markdown fix brief for an agent to work through: a `## Setup` section for findings about the whole setup, then one section per file in ranked order, each finding a checkbox line (`- [ ] <file>:<line> <rule-id> (<severity>): <message>`) with its `Fix:` and `Evidence:` lines underneath. It takes `check`'s target and run flags, leaves out suppressed findings, and writes to stdout or to `-o FILE` (relative to the current directory; the folder must exist, and an existing file is replaced). It writes nothing inside the checked repo unless `-o` names a path there, and exits 0 whenever the brief is written. A brief saved under `docs/` is discovered as a repo doc on the next run, so keep it elsewhere or in `.tmp/`.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13.

```
uv sync
uv run pytest
uv run ruff check . && uv run ty check
prek install   # git hooks: ruff, ty, actionlint, zizmor
```

Terms used in this repo are defined in [docs/README.md](docs/README.md).

## License

[MIT](LICENSE)
