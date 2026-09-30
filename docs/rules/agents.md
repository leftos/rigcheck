# Agents

Subagent definitions (`agents/*.md` in the repo, user and plugin layers) are checked for files Claude Code skips, unknown keys and invalid values in `src/rigcheck/rules/agents.py`, and for what they refer to (tools, skills, other agents' names) in `src/rigcheck/rules/agent_refs.py`. The same module checks the agents skills refer to: a forked skill's `agent`, and the agents a skill's prose dispatches. The built-in tool, alias and agent tables in `src/rigcheck/rules/agents.py` are a snapshot of one Claude Code version, recorded in [`../research/builtin-tables-probe.md`](../research/builtin-tables-probe.md); the value tables rest on [`../research/agent-values-probe.md`](../research/agent-values-probe.md). How frontmatter is read is in [`frontmatter-and-rules-dir.md`](frontmatter-and-rules-dir.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `agent-skipped` | error | `official:AG1`, `rigcheck:frontmatter-probe` |
| `agent-key-unknown` | warn | `official:AG2` |
| `agent-value-invalid` | error | `official:AG3`, `rigcheck:agent-values-probe` |
| `agent-value-case` | warn | `official:AG3`, `rigcheck:agent-values-probe` |
| `agent-tools-unresolved` | error | `official:AG4`, `rigcheck:builtin-tables-probe` |
| `agent-tool-unknown` | warn | `official:AG4`, `rigcheck:builtin-tables-probe` |
| `agent-disallowed-specifier` | warn | `official:AG4` |
| `agent-key-ignored-in-plugin` | warn | `official:AG5`, `official:PL3`, `rigcheck:agent-values-probe` |
| `agent-skill-missing` | error | `official:AG8` |
| `agent-skill-not-preloadable` | warn | `official:AG8` |
| `agent-name-collision` | info | `official:AG11` |
| `skill-agent-missing` | error | `official:SK20`, `rigcheck:builtin-tables-probe` |
| `skill-dispatch-agent-missing` | warn | `rigcheck:agent-refs`, `rigcheck:builtin-tables-probe` |

Every rule here runs on every layer; `agent-key-ignored-in-plugin` runs on the plugin layer only.

## Skipped agents

- A file in an agents folder with no `---` at all is documentation and silent.
- `agent-skipped` is one finding per file, for the first reason that applies, in this order: a misplaced opening fence (a `---` first non-blank line after line 1, or a first line that is not exactly `---`, with a closing `---` after it), frontmatter Claude Code rejects, a bad `name`, a bad `description`.
- Frontmatter Claude Code rejects is reported with a message saying the agent loads under its filename with no settings.
- A missing, non-string or empty `name`, a name starting with `-`, and a name holding `:` after NFKC normalisation (so a full-width colon counts) are skips. A missing, non-string or empty `description` is a skip.
- A YAML 1.1 boolean or date given as `name` or `description` counts as a string, because Claude Code parses YAML 1.2 and keeps the text.
- A skipped file gets no key, value or reference findings; every other rule here reads only the agents Claude Code loads with their settings. A non-string key is skipped.

## Keys and values

- `agent-key-unknown` reports every key outside the agent key table, with "did you mean" for a case or `-`/`_` variant. A top-level `cacheTtl` gets "write it inside experimental", and every `experimental` sub-key other than `cacheTtl` is unknown.
- `agent-value-invalid` checks enums and types at error, and `agent-value-case` reports a value Claude Code reads only because it folds case, at warn. One key gives at most one finding.
- `model`: an alias (`sonnet`, `opus`, `haiku`, `fable`, `inherit`, `opusplan`, `best`, `default`, `sonnet[1m]`, `opus[1m]`, `fable[1m]`, the probe's compiled list) or a full id. The model list is served only online, so a full id is any string starting with lower-case `claude-`. An invalid value makes the agent fail when it starts, so `Claude-Haiku-4-5` (with a "did you mean" in lower case) and `gpt-4` are errors. A case variant of an alias is `agent-value-case`.
- `effort`: `low`, `medium`, `high`, `xhigh` or `max`, or an integer (unbounded), and a digit string counts as one. A case variant of a level is `agent-value-case`.
- `color` and `permissionMode` match exactly, because Claude Code compares them exactly; a case variant is `agent-value-invalid` with "did you mean". `permissionMode: manual` is valid. `memory`, `isolation` and `experimental.cacheTtl` also match exactly with "did you mean".
- `maxTurns` must be an integer of at least 1; a digit string is invalid. `background` and `omitClaudeMd` must be a boolean `as_bool` can read. `tools`, `disallowedTools` and `skills` must be a string or a list of strings. `initialPrompt` must be a string, and `experimental` a mapping.
- `hooks` and `mcpServers` get no value check on any layer; the hook rules read agent `hooks` ([`hooks.md`](hooks.md)). On the plugin layer, `permissionMode`, `hooks`, `mcpServers` and `initialPrompt` get no value check, because `agent-key-ignored-in-plugin` reports them.
- `agent-key-ignored-in-plugin` reports each of those four keys in a loaded plugin agent, worded "when it runs as a subagent", because the source says "Ignored for plugin subagents" and a plugin agent can also run as the main session.

## Tools

- `tools` and `disallowedTools` are split as Claude Code splits them: non-string list items are dropped, and every string is split on `,` and whitespace outside parentheses.
- An entry resolves by its name before `(`, against the built-in tools and their aliases (`Task`, `KillShell` and the rest of `TOOL_ALIASES`), a lone `*`, or a well-formed `mcp__server`, `mcp__server__*` or `mcp__server__tool` (any server). `MultiEdit`, `LS` and `NotebookRead` are permission names with no tool and do not resolve; the message says so.
- `agent-tools-unresolved` fires when `tools` has entries and none resolves, because such an agent usually fails to launch.
- `agent-tool-unknown` is one finding per key naming its unknown entries, up to 8 and then a count. A case variant of a tool that the same list already reaches is left out.
- `agent-disallowed-specifier` reports any `disallowedTools` entry with a specifier, `Agent(...)` included, because a specifier there still removes the whole tool.

## Skills an agent preloads

- A skills entry names a skill (by folder or `name`) or a command. A nested command is named `grp:leaf` by its path under the repo or user `commands` folder; a plugin's flat command by its stem.
- A plugin skill or command answers to `<plugin>:<name>` everywhere; its bare name resolves only for that plugin's own agents.
- `agent-skill-missing` reports an entry that names nothing, with a "did you mean" for a case variant.
- `agent-skill-not-preloadable` reads the winning copy of the name (a skill over a command, then user over repo over plugin) and fires when it sets `disable-model-invocation: true`, which also keeps it out of subagents.

## Name collisions

- Agents are grouped by the name Claude Code lists them under (`<plugin>:<name>` for a plugin agent). In each group the winner is the repo copy, then user, then plugin, and within one layer the first path in case-folded path order; `agent-name-collision` reports every other file, naming the winner.

## Agents that skills refer to

- `skill-agent-missing` reports a skill or command with `context: fork` whose `agent` names no built-in agent (`Explore`, `Plan`, `claude`, `claude-code-guide`, `fork`, `general-purpose`, `statusline-setup`, `web-fetch`) and no loaded custom agent. A plugin skill may also name its own plugin's agents by bare name.
- `skill-dispatch-agent-missing` reads the prose lines of loaded skills (code blocks and frontmatter excluded) for dispatched agent names: a code span of letters, digits and hyphens followed by `agent` or `subagent`, or following `dispatch` (any tense, with an optional `the`, `a` or `an`) at the end of a clause, or a quoted or backticked name assigned to `subagent_type` with `:` or `=`. It reports each name, at its first line, that no built-in or custom agent (plugin agents by bare name included) has.
