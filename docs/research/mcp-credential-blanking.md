# Probe: which variables Claude Code blanks in MCP server config

Claude Code 2.1.288 (`claude --version`), Windows, probed from its bundled JavaScript and at runtime. It backs `mcp-credential-var-remote` ([rules/mcp.md](../rules/mcp.md)).

## Question

The MCP docs (MC3 in [official.md](official.md)) name some credential variables "such as" `ANTHROPIC_API_KEY` and `NPM_TOKEN` that Claude Code reads as empty in a remote server's `url` and `headers`, "and other credentials your environment carries". Which names exactly?

## Method

1. **Bundle.** Strings were extracted from `~/.local/bin/claude.exe` around the MCP config expansion. Function `QLn` expands a server's config. A stdio server's `command`, `args` and `env` go through `V2(..., {remoteSink: false})`. An `sse`, `http` or `ws` server's `url` and `headers` go through `V2(..., {remoteSink: true})`, and the headers are expanded again at connect time (`Xrn`). Inside `V2` a reference expands to the empty string when:

   ```
   he.has(NAME) || (K && Bbe(name, value)) || (remoteSink && (Nbe(NAME) || Fbe(NAME, value)))
   ```

   The terms:
   - `he` is the set applied toward a remote server (`remoteSink` is the bundle's own flag name): the always-on `plain` set (`Wrr() ∪ _tt`) together with `Oxn`.
   - `Oxn` is the upper-cased union of two lists: the credential list `Co` minus a few GitHub and Hugging Face names (`xxn`), and the package-registry and proxy list `Rxn`. Every name also counts with an `INPUT_` prefix.
   - Names are compared upper-cased, so `npm_token` counts as `NPM_TOKEN`.
2. **Runtime.** A local HTTP server logged the request URL and headers it received. It was given an `--mcp-config` holding an `http`, an `sse` and a stdio server whose fields referenced marker variables, and was run with `claude -p ... --strict-mcp-config` from a scratch folder. The variables were set only in the child process.

## Result

**Blanked in a remote `url` or `headers`:**
- 130 fixed names, each also with an `INPUT_` prefix, compared without regard to case. The list is the `_REMOTE_BLANKED` set in `src/rigcheck/rules/mcp_credentials.py`. It spans Anthropic and Claude Code credentials, cloud credentials (`AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `GOOGLE_APPLICATION_CREDENTIALS`, `AZURE_CLIENT_SECRET`), CI and vault tokens, package-registry credentials and index URLs (`NPM_TOKEN`, `PIP_INDEX_URL`, `UV_PUBLISH_TOKEN`), webhook URLs, and the proxy variables in both cases.
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

**stdio:** a stdio server's fields test only the always-on `plain` set: Claude Code's own tokens, `MCP_CLIENT_SECRET` and the `OTEL_*` pattern. The probe saw `${CLAUDE_CODE_ARTIFACTS_API_TOKEN}`, `${MCP_CLIENT_SECRET}` and `${OTEL_FOO_BAR}` arrive empty in a stdio server's `env`, while `NPM_TOKEN` and the AWS names arrived intact.

**Unverified:** `QLn` names `sse`, `http` and `ws` as remote types. It was not checked whether `streamable-http` is normalised to `http` before that point.

The names come from the bundle of one version, so a later release can change them. Re-run the probe when MC3 findings look wrong against a newer Claude Code.
