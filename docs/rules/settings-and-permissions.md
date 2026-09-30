# Settings and permissions

This area checks that JSON config files load, that settings files match Claude Code's settings schema, and that permission rules do what they appear to. JSON loading and key lines are `src/rigcheck/parse/config.py` (described in [`discovery.md`](discovery.md)); the load and schema rules are `src/rigcheck/rules/settings.py`, against the vendored schema in `src/rigcheck/data/`; permission-rule parsing and Bash pattern matching are `src/rigcheck/parse/permissions.py`, and the permission rules are `src/rigcheck/rules/permissions.py`. The grammar comes from [`../research/permissions-grammar.md`](../research/permissions-grammar.md). The terms vendored schema, permission rule, specifier, settings scope and shadowed are in the glossary in [`../README.md`](../README.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `config-json-invalid` | error | `official:ST1` |
| `settings-schema-invalid` | error | `official:ST1` |
| `permission-allow-shadowed` | warn | `official:ST2` |
| `permission-path-tool-ignored` | error | `official:ST3` |
| `secret-file-not-denied` | warn | `official:ST5` |
| `permission-bash-wildcard` | warn | `official:ST6` |
| `permission-bash-colon-star` | error | `official:ST6` |

## Config files that do not load

- `config-json-invalid` covers every JSON config kind (settings files, `.mcp.json`, plugin `hooks.json` and `plugin.json`) on every layer, because the hook and MCP readers skip a file that does not load and would otherwise say nothing about it.
- It fires on a parse error, on `NaN`, `Infinity` or `-Infinity` (which Python's parser accepts and JSON.parse rejects), and on a top level that is not an object. An empty or whitespace-only file is silent.
- A settings file with a trailing comma is dropped whole by Claude Code (a probe with `claude -p --settings`), so it is `config-json-invalid` and not a schema finding.

## Settings schema

- The schema is SchemaStore's Claude Code settings schema, vendored at commit `d2cbdcd` with attribution in `src/rigcheck/data/NOTICE` and refreshed by `scripts/update_schema.py`. It is draft-07 with local `$ref`s only, validated with no format checks, so the check runs offline.
- `settings-schema-invalid` runs on the repo and user `settings.json` and `settings.local.json` files that load to an object.
- Errors under `hooks` are dropped, because the hook rules own the hook map ([`hooks.md`](hooks.md)). Errors on a single `permissions.allow`, `ask` or `deny` string are dropped too, because the schema's rule pattern forbids `)` inside a specifier, which Claude Code accepts, and the permission rules own rule grammar; the lists themselves stay checked.
- One error is kept per rejected path, in path order with array indexes compared as numbers, capped at 8 per file; the last finding shown counts the rest.
- Each message is worded from the failing schema keyword and the schema's own values, never echoing a value from the file, because rigcheck never prints file contents from the real home in a report. Unknown keys and keys that break `propertyNames` are named, as key names, up to three per finding.
- A finding sits on the line of the first key the reason names, else the value's own key, else the nearest enclosing key.
- A settings file with no `$schema` gets no finding: that is an editor convenience, and nothing Claude Code loads changes.

## Permission rules

- Rules are read from the `permissions.allow`, `ask` and `deny` lists of the repo and user settings files. A rule is `Tool` or `Tool(specifier)`: the first `(` opens the specifier and the last character must close it, parentheses inside are literal, `Tool(*)` is the whole tool, and `Task` reads as `Agent`. A malformed rule is skipped, as Claude Code skips it. Each finding sits on the line the rule string is written on.
- The settings scope of a file is `user` (the user layer), `local` (`settings.local.json`) or `project`.
- `permission-allow-shadowed` compares every loaded scope, since Claude Code combines them: an allow rule is shadowed by the first deny rule, else the first ask rule, in any scope that covers it. The finding sits on the allow rule's file and names the covering rule's list, scope and file. A rule covers another when it is a whole-tool rule for the same tool, has an equal specifier, is a Bash pattern that matches the allow rule's literal command (one with no `*`), or is `mcp__<server>` or `mcp__<server>__*` and the allow rule names that server or one of its tools. Read and Edit specifiers are compared after resolving their anchors per scope: a path starting `//` is absolute, one starting `~/` is under home, and one starting with a single `/` is under the settings file's base (the home folder's `.claude` folder for user settings, the repo root otherwise). Glob containment between two path patterns is not compared.
- In a Bash pattern, `*` matches any text, spaces included; a trailing ` *` or `:*` also matches the bare command when it is the pattern's only wildcard, and a `:*` anywhere else is a literal colon followed by a wildcard.
- `permission-path-tool-ignored` reports a path rule (one with a specifier) on `Write`, `NotebookEdit`, `Glob` or `MultiEdit`, which Claude Code accepts but never consults; paths are checked only on Read and Edit. A bare tool name on those tools is silent.
- `permission-bash-wildcard` reports an allow rule `Bash(...)` whose specifier ends in `*` with no space or `:` before it (and is not `*` alone), because it also matches longer command names (`Bash(ls*)` matches `lsof`).
- `permission-bash-colon-star` reports a `Bash(...)` rule in any list with `:*` before its end. ST6 has an error half and a warn half, and one rule has one severity, so the error half is its own id.

## Secret files without a Read deny

- `secret-file-not-denied` runs on the repo layer only, and skips a target or repo root that is the home folder and a folder outside git.
- A secret is a file named `.env`, `id_rsa` or `id_ed25519`, a file ending `.pem` or `.key`, a `.env.*` file not ending `.example`, `.sample` or `.template`, or a `secrets/` folder (reported once, at its outermost `secrets/`). A `.pem` counts only when its first 64 KiB hold `PRIVATE KEY` (or it cannot be read), so a public certificate is not a secret.
- Candidates are git's file list (`ls-files -co --exclude-standard`) plus the git-ignored files and folders on disk. A git-ignored folder git lists whole is walked at most 6 levels deep and 20,000 entries per run in all, skipping `SKIP_DIRS`, `__pycache__`, virtual environments and links; when the budget runs out the walk stops quietly.
- A secret is covered when a `Read(...)` deny rule in any settings file matches it; a whole-tool `Read` deny covers everything. Deny paths resolve by anchor as above, and an unanchored path (no anchor, or a leading `./`) matches at the repo root or at any depth below it. A `!` pattern re-opens what an earlier pattern of the same file covered, as in gitignore; it never re-opens another file's deny.
- One finding per uncovered secret, sorted, capped at 10 with a count on the last. Findings sit on the `permissions` key of the repo's `.claude/settings.json`, else its `settings.local.json`; with neither, each is a setup finding.
- rigcheck's own `.claude/settings.json` denies `Read(./tests/fixtures/**/.env)`, so the `.env` files among its fixtures are covered when rigcheck checks itself.
