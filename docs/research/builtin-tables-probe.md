# Probe: built-in tool names and built-in subagent names

Measured 2026-09-27 with Claude Code 2.1.283 (`claude --version`), native build at `C:\Users\lefto\.local\bin\claude.exe` (244,960,928 bytes, Bun-compiled). Scratch files are in `D:\rigcheck\.tmp\` (`init*.json`, `tools-ref.md`, `doc-*.md`, `tool_scan.py`, `defer_scan.py`, `tools-scan.txt`).

## Method

Three sources, each named in the evidence column below:

- **docs**: `https://code.claude.com/docs/en/tools-reference.md` (the tools table, 46 rows), `sub-agents.md` ("Built-in subagents", "Available tools", the `Task` rename note), `permissions.md` (the "legacy `MultiEdit` tool" sentence), fetched as raw Markdown with `curl`.
- **init**: the SDK `initialize` control request (cost 0, no inference; recipe from [agent-values-probe.md](agent-values-probe.md)), run from the empty folder `.tmp\probe-empty\` twice: once with `--safe-mode`, once with `--setting-sources ""`. The response's `agents` array carries only `name`, `description` and sometimes `model`, no source field; no user or plugin agent appeared in either run, so every row is built-in. The response has no tool list field (keys: `account`, `agents`, `commands`, `models`, output-style and remote-control fields).
- **bin**: `rg -a -o` and two small Python scans over the executable: the built-in agent list function, the tool objects built by the bundle's tool factory with their `shouldDefer` flag and `aliases`, and the legacy-name map. Minified names change per build; this is evidence, not an interface.
- **live**: the deferred-tool list this probe's own subagent session was handed (ArtifactComments, ArtifactData, EnterWorktree, ExitWorktree, LSP, Monitor, NotebookEdit, SendMessage, TaskStop, WebFetch, WebSearch).

"Deferred" means the tool's schema is loaded on demand through `ToolSearch`; its name is still valid in a `tools:` list, a permission rule and a hook matcher. The docs do not list which built-in tools are deferred (tools-reference and mcp pages mention deferral only for `ToolSearch` and MCP tools), so that column rests on bin and live.

## Table A: built-in tool names

| Name | Kind | Evidence |
|---|---|---|
| Agent | core | docs; bin (alias `Task`) |
| Artifact | core | docs; bin `shouldDefer:!1` |
| ArtifactCheck | deferred | bin (artifact addon factory, `shouldDefer:!0`); not in docs |
| ArtifactComments | deferred | bin; live; not in docs |
| ArtifactData | deferred | bin; live; not in docs |
| AskUserQuestion | core | docs; bin |
| Bash | core | docs; bin |
| CronCreate | deferred | docs; bin |
| CronDelete | deferred | docs; bin |
| CronList | deferred | docs; bin |
| Edit | core | docs; bin |
| EndConversation | deferred | docs; bin |
| EnterPlanMode | deferred | docs; bin |
| EnterWorktree | deferred | docs; bin; live |
| ExitPlanMode | deferred | docs; bin |
| ExitWorktree | deferred | docs; bin; live |
| Glob | core | docs; bin |
| Grep | core | docs; bin |
| ListAgents | core | docs; bin (alias `ListPeers`) |
| ListMcpResourcesTool | deferred | docs; bin (alias `ListMcpResources`) |
| LSP | deferred | docs; bin; live |
| Monitor | deferred | docs; bin; live |
| NotebookEdit | deferred | docs; bin; live |
| PowerShell | core | docs; bin |
| PushNotification | deferred | docs; bin |
| Read | core | docs; bin |
| ReadMcpResourceDirTool | deferred | bin (alias `ReadMcpResourceDir`); not in docs |
| ReadMcpResourceTool | deferred | docs; bin (alias `ReadMcpResource`) |
| RemoteTrigger | deferred | docs; bin |
| REPL | core | bin; `claude --help` (`--restricted` names it); not in docs table |
| ReportFindings | core | docs; bin |
| ScheduleWakeup | deferred | docs; bin |
| SendFeedback | core | docs; bin |
| SendMessage | deferred | docs; bin; live |
| SendUserFile | core | docs; bin |
| SendUserMessage | core | bin (alias `Brief`); `claude --help` (`--brief` enables it); not in docs table |
| ShareOnboardingGuide | core | docs; bin |
| Skill | core | docs; bin |
| SubagentHandback | core | docs; bin |
| TaskCreate | deferred | docs; bin |
| TaskGet | deferred | docs; bin |
| TaskList | deferred | docs; bin |
| TaskOutput | core | docs (deprecated in favour of `Read`); bin (no factory object found) |
| TaskStop | deferred | docs; bin; live (aliases `KillShell`, `KillBash`) |
| TaskUpdate | deferred | docs; bin |
| TodoWrite | deferred | docs (off by default); bin |
| ToolSearch | core | docs; bin |
| WaitForMcpServers | core | docs; bin |
| WebFetch | deferred | docs; bin; live |
| WebSearch | deferred | docs; bin; live |
| Workflow | core | docs; bin (alias `RunWorkflow`) |
| Write | core | docs; bin |
| MultiEdit | legacy | docs (permissions: "the legacy `MultiEdit` tool", rule accepted but never consulted); bin (legacy permission lists) |
| Task | legacy | docs (sub-agents: renamed to Agent in v2.1.63, still an alias); bin alias map |
| KillShell, KillBash | legacy | bin alias map to `TaskStop` |
| ListPeers | legacy | bin alias map to `ListAgents` |
| Brief | legacy | bin alias map to `SendUserMessage` |
| ListMcpResources, ReadMcpResource, ReadMcpResourceDir | legacy | bin alias map to the `...Tool` names |
| RunWorkflow | legacy | bin (`aliases:["RunWorkflow"]` on Workflow) |
| LS, NotebookRead | legacy | bin only (legacy permission-rule lists; no tool object) |

Not every name reaches a subagent. sub-agents.md "Available tools" removes `Agent` (at the depth limit), `AskUserQuestion`, `EndConversation`, `EnterPlanMode`, `ExitPlanMode` (unless `permissionMode: plan`), `ScheduleWakeup`, `WaitForMcpServers` and `Workflow` from every subagent "even when listed in the `tools` field", and a background subagent keeps only `Read`, `Grep`, `Glob`, `LSP`, `Bash`, `PowerShell`, `Edit`, `Write`, `NotebookEdit`, `WebFetch`, `WebSearch`, `TodoWrite`, `Skill`, `ToolSearch`, `EnterWorktree`, `ExitWorktree`, `Monitor`, `TaskStop`, `SendMessage`, `Artifact` (plus `SubagentHandback`). Those names are still known names, so a linter should not call them unknown.

## Table B: built-in subagent names

| Name | Kind | Evidence |
|---|---|---|
| general-purpose | default | docs; init (both runs); bin (always in the list) |
| Explore | default | docs; init (both runs); bin (gated on a host feature check; docs: `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` removes it) |
| Plan | default | docs; init (both runs); bin (same gate as Explore) |
| claude | default | docs ("Other" tab); init (both runs); bin (gated) |
| statusline-setup | default | docs; init (`--setting-sources ""` run only); bin (pushed only when not in safe mode) |
| claude-code-guide | conditional | docs; bin (pushed only when `CLAUDE_CODE_ENTRYPOINT` is not `sdk-ts`, `sdk-py` or `sdk-cli`, hence absent from both init runs); present in interactive sessions |
| fork | conditional | docs (sub-agents: "requesting the `fork` subagent type"); bin (`Lz="fork"`); not in init |
| web-fetch | conditional | bin only (gated; "Use this to fetch and read web pages / URLs when you do not have a direct WebFetch tool"); not in docs or init |

Internal agent types in bin, not spawnable by name and not for the table: `comment-thread-analyst` ("Dispatched programmatically by the artifact comment pipeline"), `workflow-subagent` ("Internal subagent for workflow script orchestration"), `main-session`.

## Open edges

- `ArtifactCheck`, `ArtifactComments`, `ArtifactData`, `ReadMcpResourceDirTool`, `REPL`, `SendUserMessage`: real tool names in bin (and live or `--help` for some) but absent from the docs tools table.
- `web-fetch` agent: bin only.
- `LS`, `NotebookRead`: bin only, in legacy permission-rule lists; no tool object registers them.
- `TaskOutput`: docs list it (deprecated); bin shows the name only in a set of retired names (`Tfe`: `TaskOutput`, `AgentOutputTool`, `BashOutputTool`, `AgentOutput`, `BashOutput`, `Frame`, `TeamCreate`, ...), no factory object found. It may no longer register.
- Deferral is per build and per session: the bin flag is the default, and `ENABLE_TOOL_SEARCH` or the model can change it. Treat the kind column as informational, not as a validity rule.
- Other factory-built names seen only in bin and likely gated or internal (not tabled): `DesignSync`, `FetchInboxMessage`, `ListConnectors`, `SuggestConnectors`, `SearchMcpRegistry`, `SendFile`, `ProposeGoal`, `ReadNotifications`, `ShowOnboardingRolePicker`, `GetTask`, `Poll`, `RefreshMcpTools`, `SuggestPluginInstall`, `SuggestSkills`, `ClaudeDesign`, `AppifactRepl`, `ObserverReport`, `memory_*`, `self_hosted_runner_*`.

## Commands

```bash
claude --version
printf '%s\n' '{"type":"control_request","request_id":"1","request":{"subtype":"initialize"}}' > D:/rigcheck/.tmp/init-req.jsonl
cd D:/rigcheck/.tmp/probe-empty
claude -p --safe-mode --input-format stream-json --output-format stream-json --verbose < ../init-req.jsonl > ../init-all.jsonl
claude -p --setting-sources "" --input-format stream-json --output-format stream-json --verbose < ../init-req.jsonl > ../init-all2.jsonl
head -n1 ../init-all2.jsonl > ../init2.json
jq -c '.response.response | keys' ../init2.json
jq -r '.response.response.agents[] | [.name, (.source // "")] | @tsv' ../init2.json
curl -sSL -o tools-ref.md https://code.claude.com/docs/en/tools-reference.md   # also sub-agents, permissions, hooks, mcp
B=/c/Users/lefto/.local/bin/claude.exe
rg -a -o 'agentType:[A-Za-z_$"-]+,whenToUse' $B | sort -u
rg -a -o '.{300}[^A-Za-z_$]Wnt[^A-Za-z_$=].{300}' $B        # the built-in agent list function and its gates
rg -a -o 'var i=\{Task:"Agent".{0,400}' $B                   # legacy tool-name alias map
rg -a -o 'name:[A-Za-z_$]{1,5},aliases:\[[^\]]*\]' $B | sort -u
uv run --no-project python tool_scan.py > tools-scan.txt       # name + shouldDefer + aliases per tool-factory object
```
