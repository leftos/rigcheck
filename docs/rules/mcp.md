# MCP servers

Rules on MCP server definitions, in `src/rigcheck/rules/mcp.py`. They read every server `mcp_servers` (`src/rigcheck/rules/config.py`) yields: a repo `.mcp.json`, a plugin `.mcp.json` (wrapped in `mcpServers` or flat) and a plugin manifest's inline `mcpServers`. How those files are found, and why the `~/.claude.json` servers carry no path or line, is in [`discovery.md`](discovery.md). A server whose value is not an object is skipped by every rule here. Each finding points at the line of the key it is about (`type`, `command`, `args`, `url` or `headers`), found through `McpServer.path`, or at the server's own line when the text does not show that key.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `mcp-type-invalid` | error | `official:MC5` |
| `mcp-project-dir-no-default` | warn | `official:MC4` |
| `mcp-credential-var-remote` | error | `official:MC3` |

## Server type

- `mcp-type-invalid` accepts `stdio`, `http`, `streamable-http` (the MCP specification's name for `http`), `sse` and `ws`. `sdk` is reported in every file, because Claude Code skips an `sdk` server outside an Agent SDK host; any other string, and a `type` that is not a string, is reported as unknown. A server with no `type` is not reported.

## Variable references

- A reference is `${NAME}` or `${NAME:-default}`, the two forms Claude Code expands in an MCP config. A bare `$NAME` is not a reference and is never reported.
- `mcp-project-dir-no-default` reports `${CLAUDE_PROJECT_DIR}` with no `:-` default in `command` or in a string of `args`, in a repo `.mcp.json` only: the variable is set in the server's environment, not Claude Code's, and plugin configurations substitute it directly. One finding per server, for `command` before `args`. The docs say the same of local- and user-scoped servers in `~/.claude.json`; those are not checked, because their findings would have no file line and their config stays out of reports.
- `mcp-credential-var-remote` reports a credential variable referenced in a remote server's `url` or in a string value of its `headers`, where Claude Code reads it as empty. A server is remote when its `type` is `http`, `streamable-http`, `sse` or `ws`, or when it has no `type` and has a `url`; a `type` that is not a string is not remote (`mcp-type-invalid` reports it).
- The credential names are the ones the docs name (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK`, `HTTPS_PROXY`, `NPM_TOKEN`), plus any `ANTHROPIC_` name ending `_KEY` or `_TOKEN` and any `AWS_` name ending `_KEY`, `_KEY_ID` or `_TOKEN`. The docs give their list as examples ("such as"), so names outside these shapes, such as `GITHUB_TOKEN`, are not reported. A reference with a default still counts. One finding per server, field and name; the message names the variable, never the url or header value.
