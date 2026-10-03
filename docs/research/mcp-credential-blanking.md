# Probe: which variables Claude Code blanks in MCP server config

Claude Code 2.1.288 (`claude --version`), Windows, probed from its bundled JavaScript and at runtime, in two passes: one for remote servers, and a second that read the stdio set out of the bundle and ran it. It backs `mcp-credential-var-remote` and `mcp-credential-var-stdio` ([rules/mcp.md](../rules/mcp.md)).

## Question

The MCP docs (MC3 in [official.md](official.md)) name some credential variables "such as" `ANTHROPIC_API_KEY` and `NPM_TOKEN` that Claude Code reads as empty in a remote server's `url` and `headers`, "and other credentials your environment carries". Which names exactly?

## Method

1. **Bundle.** Strings were extracted from `~/.local/bin/claude.exe` around the MCP config expansion. Function `QLn` expands a server's config. A stdio server's `command`, `args` and `env` go through `V2(..., {remoteSink: false})`. An `sse`, `http` or `ws` server's `url` and `headers` go through `V2(..., {remoteSink: true})`, and the headers are expanded again at connect time (`Xrn`). Inside `V2` a reference expands to the empty string when:

   ```
   he = remoteSink ? sets.remoteSink : sets.plain
   (he.has(NAME) || (K && Bbe(name, value)) || (remoteSink && (Nbe(NAME) || Fbe(NAME, value)))) && (value !== undefined || remoteSink)
   ```

   The terms:
   - `sets` comes from `_K()`, computed once per server: `plain` is `Wrr()` upper-cased together with `Ixn`, and `remoteSink` is `plain` together with `Oxn` (`remoteSink` is the bundle's own flag name). So a stdio field tests `plain` only, and a remote field tests both.
   - The last term means a stdio field blanks a reference only when the variable is set. A remote field blanks it whether or not it is set.
   - `Oxn` is the upper-cased union of two lists: the credential list `Co` minus a few GitHub and Hugging Face names (`xxn`), and the package-registry and proxy list `Rxn`. Every name also counts with an `INPUT_` prefix.
   - Names are compared upper-cased, so `npm_token` counts as `NPM_TOKEN`.
2. **Runtime.** A local HTTP server logged the request URL and headers it received. It was given an `--mcp-config` holding an `http`, an `sse` and a stdio server whose fields referenced marker variables, and was run with `claude -p ... --strict-mcp-config` from a scratch folder. The variables were set only in the child process. In the second pass, a Python stdio server wrote the argv and environment it received to a file, and the references sat in its `command`, `args` and `env`.

## Result

**Blanked in a remote `url` or `headers`:**
- 158 fixed names, compared without regard to case: the 54 stdio names below, plus 104 names blanked toward a remote server only. In `src/rigcheck/rules/mcp_credentials.py` they are `_PLAIN_BARE`, `_PLAIN_INPUT` and `_REMOTE_INPUT`.
  - The `INPUT_` form of a name counts for the `_PLAIN_INPUT` and `_REMOTE_INPUT` names, which come from the bundle's `Exn`, `Co` and `Rxn` lists. It does not count for the other `_PLAIN_BARE` names.
  - Three `_PLAIN_BARE` names are also in `Co`: `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_ARTIFACTS_API_TOKEN` and `CLAUDE_CODE_SLACK_TAG_TOKEN`. Their `INPUT_` form is blanked toward a remote server only.
  - The names span Anthropic and Claude Code credentials, cloud credentials (`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `GOOGLE_APPLICATION_CREDENTIALS`, `AZURE_CLIENT_SECRET`), CI and vault tokens, package-registry credentials and index URLs (`NPM_TOKEN`, `PIP_INDEX_URL`, `UV_PUBLISH_TOKEN`), webhook URLs, and the proxy variables in both cases.
- Names matching these patterns (`Nbe`):
  - `OTEL_*`, `CLAUDE_CODE_ARTIFACT*_BASE_URL` and `CLAUDE_CODE_MEMORY_API_{BASE_URL,TOKEN}`.
  - `GIT_CONFIG_PARAMETERS`, `GIT_CONFIG_KEY_<n>` and `GIT_CONFIG_VALUE_<n>`.
  - `CARGO_REGISTRIES_<name>_TOKEN`.
  - `BUNDLE_<host>__...`, except `BUNDLE_{BUILD,LOCAL,MIRROR,PATH,WITH,WITHOUT,CACHE,DISABLE,IGNORE,ONLY}__`.
  - Names starting `ORG_GRADLE_PROJECT_`, `POETRY_PYPI_TOKEN_`, `POETRY_HTTP_BASIC_`, `CARGO_REGISTRIES_`, `CONAN_LOGIN_USERNAME_` or `CONAN_PASSWORD_`. Such a name is blanked when it ends in `USER` or `USERNAME`, or when a credential word (`TOKEN`, `SECRET`, `PASSWORD`, `KEY`, `AUTH`, ...) appears anywhere after a `_` or a digit, followed by `_`, a digit or the end of the name. So `ORG_GRADLE_PROJECT_SIGNING_KEY_ID` and `CARGO_REGISTRIES_FOO_PASSWORD` are blanked too.
  - `POETRY_HTTP_BASIC_*` and `CONAN_LOGIN_USERNAME_*` are blanked whatever follows the prefix.
- A reference with a default is blanked too: `${ANTHROPIC_API_KEY:-DEF}` arrived as `''`, not `DEF`.

**Expanded normally:**
- `GITHUB_TOKEN`, `GH_TOKEN`, `GH_ENTERPRISE_TOKEN`, `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`.
- `AWS_ACCESS_KEY_ID`, `AWS_REGION`.
- `ANTHROPIC_FOO_KEY`, and arbitrary names such as `MY_API_TOKEN`, `MY_SECRET` and `DATABASE_URL`.

**Not decidable from the config alone:**
- `Fbe` blanks an `ANTHROPIC_*_BASE_URL`-type variable when its value holds `user:pass@`.
- `Bbe` blanks any credential-shaped name (`*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_KEY`, ...) except the GitHub tokens and the proxies. It does so only when `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` is set, or when the entrypoint is `local-agent`.
- rigcheck checks neither, since both depend on a value or on the run mode.

**User-visible effect:** the empty string is substituted silently, and the server connects or fails on its own merits. The only trace is a `--debug` log line, written once per field and naming only the variables that are set: `MCP server config references credential variable(s) that are never expanded toward a remote server: NPM_TOKEN (read as empty)`.

**stdio:** a stdio server's `command`, `args` and `env` test only the `plain` set, and only when the variable is set. The bundle lists 54 fixed names in it:
- 17 of Claude Code's own credentials (`gKt`): `AGENT_PROXY_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_ARTIFACTS_API_TOKEN`, the `CLAUDE_BG_*` auth names, the `*_FILE_DESCRIPTOR` names and others.
- 10 session settings written as literals in `Wrr()`: `CLAUDE_CODE_BRIDGE_CHILD_*`, `CLAUDE_CODE_SUBSCRIPTION_TYPE`, `CLAUDE_CODE_RATE_LIMIT_TIER` and others.
- 18 background-session and resume names: `CLAUDE_BG_BACKEND`, `CLAUDE_CODE_RESUME_*`, `CLAUDE_CODE_SESSION_NAME` and others.
- The 9 names of `Exn`, each also with an `INPUT_` prefix: `MCP_CLIENT_SECRET`, `MCP_XAA_IDP_CLIENT_SECRET`, `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`, `ENVIRONMENT_SERVICE_KEY` and others.

Together with these, `Wrr()` blanks any name that, after an optional `INPUT_`, is `OTEL_*`, `CLAUDE_CODE_OTEL_DIAG_STDERR`, `CLAUDE_CODE_ARTIFACT*_BASE_URL` or `CLAUDE_CODE_MEMORY_API_{BASE_URL,TOKEN}`. The full lists are the `_PLAIN_*` sets in `mcp_credentials.py`.

The runtime pass confirmed the following:
- **Blanked:** `CLAUDE_CODE_SLACK_TAG_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_SESSION_NAME`, `MCP_CLIENT_SECRET` (also in `args`), `INPUT_MCP_CLIENT_SECRET`, `CLAUDE_CODE_MEMORY_API_TOKEN`, `OTEL_X` and a lower-case `${otel_foo}`. They arrived empty when set.
- **`command`:** an `OTEL_` prefix in `command` was blanked.
- **Intact:** `INPUT_CLAUDE_CODE_SLACK_TAG_TOKEN`, `INPUT_CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_CUSTOM_HEADERS`, `NPM_TOKEN` and `AWS_SECRET_ACCESS_KEY`.
- **Defaults:** a set variable with a default was blanked (`${OTEL_FOO_BAR:-DEF}` gave `''`). An unset one took its default (`${OTEL_UNSET:-DEF}` gave `DEF`). An unset one with no default stayed literal (`${OTEL_UNSET}`).

Blanking that depends on the run mode adds names, read from the bundle and not run:
- a HIPAA-tainted session adds the `ANTHROPIC_*` credentials;
- `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` adds the provider auth names;
- a bridge session adds its session token;
- `Bbe` applies under `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`.

Earlier remote-only probing missed two things the stdio pass found:
- **28 more names toward a remote server:** the session names among the 54, because the remote set contains the `plain` set. They are read from the bundle only, since the remote side was not run again.
- **14 `INPUT_` forms not blanked:** for the other `gKt` names, which are not in `Co`, the `INPUT_` form is not blanked toward a remote server either.

**Unverified:** `QLn` names `sse`, `http` and `ws` as remote types. It was not checked whether `streamable-http` is normalised to `http` before that point.

The names come from the bundle of one version, so a later release can change them. Re-run the probe when MC3 findings look wrong against a newer Claude Code.
