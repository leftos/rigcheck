# Context budget

The context budget is the report section that estimates (≈) what the setup costs Claude Code's context: the files loaded every turn, the skill listing against 1% of the context window, and agent names and descriptions against 15,000 tokens. It is a report, not a rule, and never changes the exit status; two rules turn an over-budget listing into a warn finding. The estimate is `src/rigcheck/report/budget.py` (with the rates in `src/rigcheck/parse/tokens.py`), the findings are `src/rigcheck/rules/budget.py`, and the rendering is `src/rigcheck/report/terminal.py` and `src/rigcheck/report/json.py`.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `skill-listing-over-budget` | warn | `official:SK27` |
| `agent-descriptions-over-budget` | warn | `official:AG6` |

## Estimate

- The window is 200k tokens by default; `--window` takes another (a positive integer with an optional `k` or `m`, such as `1m`). `discover` takes the window as a required argument and carries it on the `Rig`, so the rules measure against the same window as the report.
- Tokens are `ceil(characters / rate)`: 2.5 characters per token for file bodies (instruction files, rules without `paths`, MEMORY.md) and 3.0 for listing text (names, descriptions, `when_to_use`). The rates were calibrated against Claude Code's `/context`; the measurement is under Verification in [`../plans/v1.md`](../plans/v1.md#verification).
- The every-turn part has one row per artifact whose load class is `every-turn`. Instruction files lose their block-level HTML comments first, and MEMORY.md is counted to its loaded head: the first 200 lines, then the first 25,000 bytes of those.
- The skill listing has one entry per skill and per command, from every layer, plugins included; a skill or command with `disable-model-invocation: true` is left out, because Claude Code does not list it. An entry is `name: description when_to_use`, with description and `when_to_use` together cut at 1,536 characters. Its budget is 1% of the window.
- The agent listing has one entry per agent file, plugins included, as `name: description`, against 15,000 tokens.
- Both listings carry per-layer subtotals.

## Findings

- `skill-listing-over-budget` and `agent-descriptions-over-budget` are warn only, and fire only when a listing is strictly past its budget. SK27's "info otherwise" is not a finding, because the budget table already shows the listing.
- Each is one finding about the whole setup, with no path or layer (built with `emit_setup`), and its message names the per-layer subtotals.

## Output

- The text report always shows the budget table at the top: the every-turn total, the largest 10 files and a "… N more" line, then the two listing rows with their percentage, per-layer split and an "over budget" marker.
- A finding with no layer that loads every turn is a setup finding. The text report prints setup findings first, under a `setup` heading, with the location `(setup)`, so they are not read as rigcheck faults; rigcheck's own findings (`discovery-error`, `internal-error`) print last under `rigcheck`.
- JSON carries a top-level `budget` object (the window, every every-turn row with its path, layer, kind and tokens, the total, and both listings with their budget, entry count and per-layer subtotals); the schema version stays 1. Each artifact in JSON also carries its own `tokens_est`.
