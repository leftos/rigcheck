# Hooks

Hooks are checked in two parts: their structure (event names, handler shape, matchers, `if`, `once`, timeouts) in `src/rigcheck/rules/hooks.py`, and the commands command handlers run (script paths, the executable bit, placeholder quoting, exec form, exit codes, reprinted instructions) in `src/rigcheck/rules/hook_commands.py`, which reads shell text through `src/rigcheck/parse/shell.py`. Both read every hook map through `hook_maps` and `handlers` in `src/rigcheck/rules/config.py`. The terms hook map, matcher group, handler, shell form and exec form are in the glossary in [`../README.md`](../README.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `hook-event-unknown` | error | `official:HK1` |
| `hook-handler-invalid` | error | `official:HK2` |
| `hook-matcher-mcp-exact` | error | `official:HK3` |
| `hook-matcher-unanchored` | warn | `official:HK4` |
| `hook-if-ignored` | error | `official:HK5` |
| `hook-once-ignored` | warn | `official:HK6` |
| `hook-timeout-long` | info | `official:HK13` |
| `hook-exit-1-blocking` | warn | `official:HK7` |
| `hook-script-missing` | error | `official:HK8` |
| `hook-placeholder-unquoted` | warn | `official:HK9` |
| `hook-script-relative` | warn | `official:HK9` |
| `hook-exec-form-spawn` | error | `official:HK10` |
| `hook-reprints-instructions` | warn | `official:CM17` |

## Hook maps

- A hook map is read from each settings file, each plugin's `hooks/hooks.json` and `.claude-plugin/plugin.json` (under a top-level `hooks` key), and from the frontmatter `hooks` key of skills, commands and agents; each map is tagged with its source. A file that does not load, whose top level is not an object, or whose `hooks` is absent or not an object yields no map; `config-json-invalid` ([`settings-and-permissions.md`](settings-and-permissions.md)) reports a JSON file that does not load. Non-string event keys are dropped.
- `handlers` walks event → list of groups → the group's `hooks` list → handler, skipping silently anything that is not the right shape; `hook-handler-invalid` is the rule that reports those shapes.

## Structure

- `hook-event-unknown` matches event names against the list in [`../research/official.md`](../research/official.md) case-sensitively, on every source, with a "did you mean" for a case variant.
- `hook-handler-invalid` checks the raw shape: an event's value is a list, each group is an object with a `hooks` list, each handler is an object with a known `type` (`command`, `http`, `mcp_tool`, `prompt`, `agent`), a command hook has a non-empty `command` string, and a prompt or agent hook a non-empty `prompt`. `http` and `mcp_tool` handlers get the type check only.
- The matcher rules run on tool events only (`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `PermissionDenied`), once per group with a string matcher.
- `hook-matcher-mcp-exact`: a matcher made only of `[A-Za-z0-9_|-]` is compared as an exact string or `|` list, so an alternative of the form `mcp__<server>` with no tool part matches no tool.
- `hook-matcher-unanchored`: a regex matcher (any other character present) that `re.search` matches inside a longer built-in tool name that `re.fullmatch` does not match. A pattern Python's `re` rejects is skipped.
- `hook-if-ignored`: `if` on a known event that is not a tool event, where it is never evaluated, or an `if` holding `&&` or `||` or given as a list, since `if` takes one permission rule.
- `hook-once-ignored`: `once` anywhere but skill or command frontmatter, where Claude Code ignores it.
- `hook-timeout-long` reads only finite numbers that are not booleans. It fires past 30 s on `UserPromptSubmit`, past 1.5 s on `SessionEnd` (those hooks share a 1.5 s budget), and on any timeout of a handler with `async` true (JSON `true`, or a frontmatter value `as_bool` reads as true), where the timeout is not enforced.
- Structure findings sit on the event key's line in JSON files, and on the `hooks` key's line in frontmatter.

## Commands

- The command rules read command handlers with a non-empty `command` string. A handler with an `args` list is exec form; with `args` present but not a list it is skipped.
- Findings sit on the handler's own command line: the command is found as a whole JSON string after its event's key (so the same command under two events points at each), or by its first line after the frontmatter `hooks` key; failing that, the event key's line.
- Shell text is read lexically with POSIX grammar: split into segments on `&&`, `||`, `;` and `|` outside quotes, cut at a `#` that starts a word, and split into words. The shell helpers are shared with the reference and skill-body rules.
- The script word of a segment is the command word (after leading `NAME=` assignments), or, when the program is an interpreter (`bash`, `sh`, `zsh`, `dash`, `python`, `python3`, `py`, `node`, `deno`, `bun`, `ruby`, `perl`, `pwsh`, `powershell`), its first operand, skipping flags and the values of value-taking flags (`node -r`, `python -W`, `ruby -I` and the like). `deno` and `bun` skip a `run` subcommand; PowerShell takes the word after `-File` or `-f`. An inline-code flag (`-c`, a shell's `-lc`-style group, `-e`, `-Command` and the like) or `python -m` means there is no script. `uv run` and `uvx` skip to their first non-flag word and read it again as a command. Reading stops at the first `cd`, `pushd`, `Set-Location` or `sl`, because later paths are relative to a folder rigcheck cannot follow.
- In exec form, the command and its `args` are read as one command's words.

## Script paths

- A script word resolves as follows: `${CLAUDE_PROJECT_DIR}` (or `$CLAUDE_PROJECT_DIR`) at the repo root, on the repo layer only; `${CLAUDE_PLUGIN_ROOT}` at the plugin's root, for plugin `hooks.json` and `plugin.json` only; `~/` at home; and, on the repo layer, an unanchored relative word holding `/` at the repo root. A word whose remaining path holds `$`, a backtick, `*`, `?` or `%` cannot be known without running a shell and is skipped, and so is every other word.
- `hook-script-missing` reports a resolved script that does not exist. When the command runs the script directly (no interpreter word) on the repo layer and git tracks it with mode 100644, it also reports the missing executable bit (from `git ls-files -s`), because a fresh clone cannot run it. A symlink (mode 120000) and a `.cmd`, `.bat`, `.exe`, `.com` or `.ps1` script are never reported for the bit.
- `hook-script-relative` reports a script word that is relative to the current directory, using the skill-body rules' test: a word starting `./` or `../`, or a word holding `/` or `\`, unless it starts `$`, `~`, `/`, `%` or `\\`, a drive letter, or holds `://`.

## Quoting and form

- `hook-placeholder-unquoted` reads shell-form commands only and reports `$CLAUDE_PROJECT_DIR`, `${CLAUDE_PROJECT_DIR}`, `$CLAUDE_PLUGIN_ROOT` or `${CLAUDE_PLUGIN_ROOT}` written outside double quotes, because a path with spaces then splits. Text in single quotes is not expanded, so a placeholder there is not reported. A backslash escapes the next character; quoting restarts inside `$(...)` and the closing `)` returns to the quoting around it; a placeholder in a `NAME=` assignment word is silent, since the shell does not split an assignment.
- `hook-exec-form-spawn` reports an exec-form command whose `command` is a bare name (no `/` or `\`) holding whitespace, which Claude Code cannot spawn.

## What the command does

- `hook-exit-1-blocking` covers `PreToolUse`, `UserPromptSubmit`, `Stop` and `SubagentStop`. It reads the inline command and each resolved script that is inside its root and at most 1 MiB, and fires on `exit 1` unless an `exit 2` or JSON decision output (`permissionDecision` or `"decision"`) is present, because exit 1 is a non-blocking error there.
- `hook-reprints-instructions` covers `SessionStart` hooks whose inline command or resolved script runs a printer (`cat`, `type`, `Get-Content`, `gc`, `head`, `tail`, `bat`, `more`, `less`) on `CLAUDE.md`, `AGENTS.md` or `CLAUDE.local.md`, because Claude Code already loads that file.
