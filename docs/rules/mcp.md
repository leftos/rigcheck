# MCP servers

Rules on MCP server definitions, in `src/rigcheck/rules/mcp.py`. They read every server `mcp_servers` (`src/rigcheck/rules/config.py`) yields: a repo `.mcp.json`, a plugin `.mcp.json` (wrapped in `mcpServers` or flat) and a plugin manifest's inline `mcpServers`. How those files are found, and why the `~/.claude.json` servers carry no path or line, is in [`discovery.md`](discovery.md). A server whose value is not an object is skipped by every rule here. Each finding points at the line of the key it is about (`type`, `command`, `args`, `url` or `headers`), found through `McpServer.path`, or at the server's own line when the text does not show that key.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `mcp-type-invalid` | error | `official:MC5` |
| `mcp-project-dir-no-default` | warn | `official:MC4` |
| `mcp-credential-var-remote` | error | `official:MC3` |
| `mcp-secret-literal` | error | `official:MC1` |
| `mcp-server-conflict` | warn | `official:MC6` |

## Server type

- `mcp-type-invalid` accepts `stdio`, `http`, `streamable-http` (the MCP specification's name for `http`), `sse` and `ws`. `sdk` is reported in every file, because Claude Code skips an `sdk` server outside an Agent SDK host; any other string, and a `type` that is not a string, is reported as unknown. A server with no `type` is not reported.

## Variable references

- A reference is `${NAME}` or `${NAME:-default}`, the two forms Claude Code expands in an MCP config. A bare `$NAME` is not a reference and is never reported.
- `mcp-project-dir-no-default` reports `${CLAUDE_PROJECT_DIR}` with no `:-` default in `command` or in a string of `args`, in a repo `.mcp.json` only: the variable is set in the server's environment, not Claude Code's, and plugin configurations substitute it directly. One finding per server, for `command` before `args`. The docs say the same of local- and user-scoped servers in `~/.claude.json`; those are not checked, because their findings would have no file line and their config stays out of reports.
- `mcp-credential-var-remote` reports a variable Claude Code blanks, referenced in a remote server's `url` or in a string value of its `headers`, where Claude Code reads it as empty. Most are credentials; the list also holds proxies, package indexes, webhooks and telemetry endpoints. The probe confirmed the blanking for `http`, `sse` and `ws`. `streamable-http` is treated as remote too, since the MCP specification names `http` that way, but whether Claude Code applies the same list to it is unverified. A server is remote when its `type` is `http`, `streamable-http`, `sse` or `ws`, or when it has no `type` and has a `url`; a `type` that is not a string is not remote (`mcp-type-invalid` reports it).
- The credential names are the ones Claude Code itself blanks toward a remote server, read from its 2.1.288 binary and confirmed by a runtime probe ([`../research/mcp-credential-blanking.md`](../research/mcp-credential-blanking.md)), since the docs give only examples ("such as"). That is 130 fixed names in `src/rigcheck/rules/mcp_credentials.py`, each also with an `INPUT_` prefix and compared without regard to case. It also covers the name patterns Claude Code applies: `OTEL_*`, `GIT_CONFIG_*`, `CARGO_REGISTRIES_*_TOKEN`, Bundler per-host credentials, and package-manager prefixes such as `ORG_GRADLE_PROJECT_` with a credential word. `GITHUB_TOKEN`, `GH_TOKEN`, `HF_TOKEN` and `AWS_ACCESS_KEY_ID` expand normally, so they are not reported. Blanking that depends on a variable's value or on the run mode (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`) is out of reach of a static check. A reference with a default still counts. One finding per server, field and name; the message names the variable, never the url or header value.

## Credential literals

- `mcp-secret-literal` scans the string values of `env` and `headers`, `command`, each string item of `args`, and `url`, with the provider token formats of `src/rigcheck/parse/secrets.py` (the same detector as `secret-literal`, placeholders skipped). There is no key-name heuristic, so a value such as `"hunter2"` under `API_KEY` is not reported: the token formats keep false positives near zero.
- A `${VAR}` reference never matches. A token written as the default of `${VAR:-<token>}` is reported: the detector refuses a token that follows `-`, so each default is also scanned on its own.
- A repo `.mcp.json` is checked only when git tracks it, since an untracked, gitignored or non-git file is not shared yet; a new file is reported once it is added. A plugin's `.mcp.json` and a manifest's inline `mcpServers` are always checked, at the same severity, because a shipped plugin is as public as a committed file. `~/.claude.json` is never read by this rule.
- One finding per server and field key (`env.<KEY>`, `headers.<Header>`, `command`, `args`, `url`), at the key's line for `env` and `headers` and at the field's line otherwise; several literals in `args` make one finding, since they share its line. The message gives the credential kind and its length, never the value. The fix also tells a plugin's user to report the literal to its author, since a plugin cache is overwritten on update.

## Scope conflicts

- Claude Code loads a server name from the highest-precedence scope (local, then project, then user, then plugins, then claude.ai connectors) and warns when the same name is defined in more than one of the first three "with different endpoints". It matches plugins and connectors by endpoint rather than name, and plugin servers register as `plugin:<plugin>:<server>`, so they never conflict by name.
- `mcp-server-conflict` compares each project `.mcp.json` server with the user- and local-scope servers of the same name in `~/.claude.json`. The endpoint is compared as written, with `${VAR}` unexpanded, as Claude Code's own warning quotes it: `url` when the server has one, else `command` with `args`. `env`, `headers` and other keys are not compared, so two definitions that differ only in credentials do not conflict.
- The finding sits on the project server's line, naming the conflicting scopes and the scope Claude Code loads: `local` whenever a local-scope definition of that name exists, even one with the project's endpoint, else `project`. It never shows a value from `~/.claude.json`. A user-scope and a local-scope definition that conflict with no project file between them are not reported, because the finding would have no file line.
