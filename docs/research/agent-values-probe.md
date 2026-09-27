# Probe: model list and enum case in agent frontmatter

Measured 2026-09-27 with Claude Code 2.1.283 (`claude --version`), native build at `C:\Users\lefto\.local\bin\claude.exe` (a 244,960,928-byte Bun-compiled executable; no loose JS or JSON schema files ship beside it). Scratch files are in `D:\rigcheck\.tmp\probe-agents\` (`proj\.claude\agents\*.md` written by `make_agents.py`, one variant a file, LF, `name` + `description` + the one probed line).

## Question A: can a process be asked for the model list non-interactively?

Yes, through the SDK control protocol, not a CLI subcommand.

- `claude --help`, `claude agents --help`, `claude plugin --help` have no model-listing command or flag. `--model` help names aliases `fable`, `opus`, `sonnet` and full names such as `claude-fable-5`. `claude agents` manages background sessions, not subagents. `/list-agents` in `-p` lists other running sessions.
- Working route: pipe `{"type":"control_request","request_id":"req-1","request":{"subtype":"initialize"}}` into `claude -p --input-format stream-json --output-format stream-json --verbose` (file `init.jsonl`). The first stdout line is a `control_response` whose `response` holds `models`, `agents`, `commands`, `account`, `available_output_styles` and more. No inference call is made (cost 0). This is what the Agent SDK's `supportedModels()` / `supportedAgents()` read (both methods are in the binary's embedded SDK client code).
- `models` shape: array of `{value, resolvedModel, displayName, description, supportsEffort?, supportedEffortLevels?, supportsAdaptiveThinking?, supportsFastMode?, supportsAutoMode?}`. Here 11 rows: `default`, `opus`, `sonnet`, `haiku` (aliases with `resolvedModel`), then full ids `claude-fable-5-1`, `claude-opus-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-sonnet-4-6`.
- Not offline and not stable: the debug log (`--debug-file`) says `[servedCatalog] primary: using served rows (10 rows via cache over the org route, fetched 3717s ago); the served list replaces the compiled picker`. The list is the account's /model picker, served per organization and cached, with a compiled fallback. It is the picker, not the full set of ids the API accepts.
- Compiled-in lists (not a supported interface; minified names change per build): alias array `["sonnet","opus","haiku","fable","best","sonnet[1m]","opus[1m]","fable[1m]","opusplan"]`, and 35 distinct `claude-(opus|sonnet|haiku|fable)-*` strings found by `rg -a` over the executable. `availableModels` exists only as a settings allowlist ("Allowlist of models that users can select. Accepts family aliases ..."), not as a catalog.

## Question B: enum case in subagent frontmatter

Signals: (1) `initialize` response `agents` (name + raw `model` string: shows whether the agent loaded); (2) `--debug-file` log lines `Agent file <path> has invalid <field> '<value>'. Valid options: ...`; (3) one headless run (`--model haiku`, stream-json, `--forward-subagent-text`) spawning four agents and reading each subagent message's `message.model` or its error; (4) the agent-file parser read out of the executable with `rg -a -o`; (5) `claude plugin validate --json` on a plugin holding the same agents.

All 17 variant agents loaded (signal 1): no enum value, valid or not, skips an agent. `claude plugin validate` reported no errors or warnings for any of them (signal 5): it does not check these enums.

| Value | Result | Evidence |
|---|---|---|
| `model: sonnet` | accepted | listed as `sonnet` |
| `model: Sonnet`, `SONNET` | case folded: ran on `claude-sonnet-5` | spawn run, `message.model` |
| `model: Haiku` | folded (inferred, same alias path) | listed as `Haiku`; not spawned |
| `model: Inherit` | folded to `inherit` at parse | listed as `inherit`; parser lowercases only this word |
| `model: Claude-Haiku-4-5` | kept as-is, spawn fails: API 404 `model_not_found`, "model sent to the API: Claude-Haiku-4-5" | spawn run |
| `model: gpt-4` | agent loads; spawn fails with the same 404 | spawn run |
| `color: red`, `purple` | accepted | parser: `Th.includes(w)`, `Th` = red, blue, green, yellow, purple, orange, pink, cyan |
| `color: Red` | ignored silently (case-sensitive `includes`, no log) | parser code; no debug line |
| `color: magenta` | ignored silently (not in the list) | parser code; no debug line |
| `permissionMode: acceptEdits` | accepted | no debug line |
| `permissionMode: acceptedits` | ignored (field dropped), debug line: invalid permissionMode, valid options acceptEdits, auto, bypassPermissions, default, dontAsk, plan | debug log + parser (`...ze&&{permissionMode}`) |
| `permissionMode: yolo` | same as above | debug log |
| `effort: high` | accepted | no debug line |
| `effort: High` | case folded (`String(e).toLowerCase()`) | no debug line (bogus value does log) + parser |
| `effort: extreme` | ignored, debug line: invalid effort, valid options low, medium, high, xhigh, max or an integer | debug log |

Confidence: high for model, permissionMode and effort (runtime signals, backed by parser code). Medium-high for color: no non-interactive surface shows the color, so it rests on the parser code alone (`...w&&typeof w==="string"&&Th.includes(w)&&{color:w}`), which is the same function whose debug messages fired. Other parser notes: `manual` is mapped to `default` before the permissionMode check; `memory`, `isolation`, `background`, `maxTurns` invalid values also log and drop; for plugin agents `permissionMode`, `hooks` and `mcpServers` are ignored with a warning.
