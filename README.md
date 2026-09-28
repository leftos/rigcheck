# rigcheck

A local validator for the instruction layer of coding agents: `CLAUDE.md`, `AGENTS.md`, `.claude/rules`, skills, subagent definitions, hooks, settings and memory files. It reports ranked findings and writes fix briefs an agent can carry out.

Status: early development. The instruction-file, `@import`, reference (stale paths and npm/just/make commands), auto-memory and component (skills, commands, agents, rules folder, output styles, listing budgets) rules work, and both reports open with a context budget; the rest of the catalog is being built per [docs/plans/MAIN.md](docs/plans/MAIN.md).

## Usage

```
uv run rigcheck check [PATH] [--format text|json] [--home DIR] [--window SIZE]
```

Checks the setup Claude Code loads for `PATH` (default: the current directory): the repo's instruction files and `.claude/` folder, your `~/.claude`, enabled plugins, and that project's own memory folder. `rigcheck check ~` checks only `~/.claude`, its plugins and its memory. Both reports open with a context budget: ≈tokens for each file loaded every turn, and the skill listing and agent descriptions against Claude Code's limits (1% of the context window, set with `--window`, default `200k`; 15,000 tokens). The budget itself never changes the exit status; a listing past its limit also raises a warn finding (`skill-listing-over-budget`, `agent-descriptions-over-budget`), so `--window` moves that finding too. The text report groups findings by layer; `--format json` gives a stable schema for agents. Exit status: 0 with no error findings, 1 with at least one, 2 on a usage error.

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
