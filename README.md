# rigcheck

A local validator for the instruction layer of coding agents: `CLAUDE.md`, `AGENTS.md`, `.claude/rules`, skills, subagent definitions, hooks, settings and memory files. It reports ranked findings and writes fix briefs an agent can carry out.

Status: early development. The instruction-file, `@import`, reference (stale paths and npm/just/make commands), auto-memory and component (skills, commands, agents, rules folder, output styles, listing budgets) rules work, and both reports open with a context budget; the rest of the catalog is being built per [docs/plans/MAIN.md](docs/plans/MAIN.md), the snapshot of the plan in Linear.

## Usage

```
uv run rigcheck check [PATH] [--format text|json] [--home DIR] [--window SIZE] [--only ID[,ID...]] [--fail-on error|warn|info] [--sibling DIR]...
```

Checks the setup Claude Code loads for `PATH` (default: the current directory): the repo's instruction files and `.claude/` folder, your `~/.claude`, enabled plugins, and that project's own memory folder. `rigcheck check ~` checks only `~/.claude`, its plugins and its memory. Both reports open with a context budget: ≈tokens for each file loaded every turn, and the skill listing and agent descriptions against Claude Code's limits (1% of the context window, set with `--window`, default `200k`; 15,000 tokens). The budget itself never changes the exit status; a listing past its limit also raises a warn finding (`skill-listing-over-budget`, `agent-descriptions-over-budget`), so `--window` moves that finding too. The text report groups findings by layer, with findings about the whole setup (the two over-budget warnings) under their own `setup` heading first; `--format json` gives a stable schema for agents.

`--only ID[,ID...]` reports only the findings of those rule ids (the other rules still run; an unknown id exits 2 and names the closest ids). `--fail-on error|warn|info` sets the lowest finding severity that makes the exit status 1 (default `error`). Exit status: 0 clean, 1 a finding at or above `--fail-on`, 2 a usage error. Repo docs (`docs/**/*.md` and `Docs/**/*.md`, without `plans/` or `archive/` folders) are discovered as kind `doc`. A line containing `<!-- rigcheck: allow reference-path-missing -->` silences that rule on the line and the next.

A `.rigcheck.toml` at the repo root silences findings the repo has judged not to apply. Each `[[suppress]]` entry names one `rule` id, an optional `path` glob relative to the repo root (for example `docs/**`), and a `reason`. A suppressed finding is left out of the findings and the exit status. The text report's last line adds `· N suppressed`, and `--format json` lists them under `suppressed` (each finding's fields plus `reason`) and counts them in `summary.suppressed`. `--only` filters them too.

Some findings are never suppressed:
- findings in `~/.claude`, plugins and memory, and in files outside the repo root;
- `internal-error` and `discovery-error`;
- the two suppression rules themselves. An entry with no reason is `suppression-no-reason` (warn), and one that matches nothing is `suppression-unused` (info).

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
