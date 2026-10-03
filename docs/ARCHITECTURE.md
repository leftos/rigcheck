# rigcheck — architecture

rigcheck is a local validator for the instruction layer of coding agents (`CLAUDE.md`, `AGENTS.md`, rules, skills, agents, hooks, settings, memory). It is one Python package: `discover` builds a `Rig` (every artifact of the effective setup), `rules` holds the checks, `engine` runs them and ranks the findings, `report` renders them. The rule that shapes it: a rule is a function of a `Rig` alone that registers itself in `REGISTRY`, and rigcheck never edits the files it checks. Terms used in a project sense (rig, layer, load class, finding, pack) are in the glossary in [`README.md`](README.md).

## Task Index

| Task | Files, in order | Deep doc |
|---|---|---|
| Add a rule to an existing area | `src/rigcheck/rules/<area>.py` → `tests/fixtures/<rule-id>/bad/` and `good/` → `tests/test_rule_catalog.py` (proves it) → the catalog in `docs/plans/v1.md` | [`plans/v1.md`](plans/v1.md) |
| Add a rules module | `src/rigcheck/rules/<area>.py` → the import list at the bottom of `src/rigcheck/rules/__init__.py` | [`plans/v1.md`](plans/v1.md) |
| Add a frontmatter key or value check for skills, commands, agents, rules or output styles | `src/rigcheck/rules/components.py` (key tables) → `src/rigcheck/rules/skills.py`, `agents.py`, `rules_dir.py`, `output_styles.py` or `commands.py` → `src/rigcheck/parse/frontmatter.py` | [`research/frontmatter-probe.md`](research/frontmatter-probe.md), [`research/agent-values-probe.md`](research/agent-values-probe.md) |
| Update the built-in tool or agent tables | `src/rigcheck/rules/agents.py` (`BUILTIN_TOOLS`, `TOOL_ALIASES`, `BUILTIN_AGENTS`) → `src/rigcheck/rules/agent_refs.py` | [`research/builtin-tables-probe.md`](research/builtin-tables-probe.md) |
| Discover a new kind of file | `src/rigcheck/model.py` (`Kind`) → `src/rigcheck/discover.py` (`_CLAUDE_DIR_FILES`, `_PLUGIN_FILES`) → `tests/test_discover.py` | [`plans/v1.md`](plans/v1.md) |
| Change how `@imports`, memory or the instruction chain are found | `src/rigcheck/discover.py` → `src/rigcheck/parse/markdown.py` → `src/rigcheck/rules/instructions.py`, `memory.py` | [`rules/instructions.md`](rules/instructions.md), [`rules/discovery.md`](rules/discovery.md) |
| Change stale-path or script-reference detection | `src/rigcheck/rules/references.py` → `src/rigcheck/parse/markdown.py` → `tests/test_references.py` | [`rules/instructions.md`](rules/instructions.md) |
| Add a cross-file text rule over the every-turn instruction files (duplicates) | `src/rigcheck/rules/duplication.py` → `src/rigcheck/rules/references.py` (`_scanned`, `inside`) → `src/rigcheck/report/budget.py` (`_every_turn`) → `src/rigcheck/parse/markdown.py` (`prose_segments`) → `src/rigcheck/parse/frontmatter.py` (`body_line`) → `tests/test_duplication_rules.py`, `tests/fixtures/duplicate-line/` | [`rules/duplication.md`](rules/duplication.md) |
| Discover repo docs | `src/rigcheck/discover.py` (`DOC_ROOTS`, `_is_doc`, `_add_docs`) → `tests/test_discover.py` | [`plans/v1.md`](plans/v1.md) |
| Change which agent names a skill's prose dispatches | `src/rigcheck/rules/agent_refs.py` (`dispatched_agents`) → `tests/test_agent_ref_rules.py` | [`research/builtin-tables-probe.md`](research/builtin-tables-probe.md) |
| Change rule `paths` glob handling | `src/rigcheck/parse/globs.py` → `src/rigcheck/rules/rules_dir.py` → `tests/test_globs.py` | [`rules/frontmatter-and-rules-dir.md`](rules/frontmatter-and-rules-dir.md) |
| Read hooks, settings or MCP config in a rule | `src/rigcheck/rules/config.py` (`hook_maps`, `handlers`, `mcp_servers`) → `src/rigcheck/parse/config.py` → the rule module | [`rules/discovery.md`](rules/discovery.md), [`rules/hooks.md`](rules/hooks.md) |
| Add or change a hook structure rule (event, handler shape, matcher, `if`, `once`, timeout) | `src/rigcheck/rules/hooks.py` (`HOOK_EVENTS`, `TOOL_EVENTS`, `HANDLER_TYPES`) → `src/rigcheck/rules/config.py` (`hook_maps`, `handlers`) → `tests/test_hook_rules.py`, `tests/fixtures/hook-*/` (repo hooks in `.claude/settings.json`, plugin hooks in `home/.claude/plugins/cache/<plugin>/hooks/hooks.json`) | [`rules/hooks.md`](rules/hooks.md) |
| Add or change a hook command rule (script path, exec bit, placeholder quoting, exit code, reprinted instructions) | `src/rigcheck/rules/hook_commands.py` → `src/rigcheck/parse/shell.py` (segments, words, `script_word`, `unquoted_placeholders`) → `src/rigcheck/rules/config.py` (`hook_maps`, `handlers`) → `tests/test_hook_command_rules.py`, `tests/test_shell.py`, `tests/fixtures/hook-*/` | [`rules/hooks.md`](rules/hooks.md) |
| Change the settings schema check, or report a config file that does not load | `src/rigcheck/rules/settings.py` (`settings_docs`, the error filter and wording) → `src/rigcheck/parse/config.py` (`load`, `JsonDoc.line`, `key_line`) → `tests/test_settings_rules.py`, `tests/test_parse_config.py` | [`rules/settings-and-permissions.md`](rules/settings-and-permissions.md) |
| Add or change an MCP server rule (type, variable references, secrets, scope conflicts) | `src/rigcheck/rules/mcp.py` → `src/rigcheck/rules/config.py` (`mcp_servers`, `McpServer.path`) → `src/rigcheck/parse/config.py` (`key_line`) → `src/rigcheck/model.py` (`Rig.user_mcp_servers`, `Rig.is_tracked`) → `src/rigcheck/parse/secrets.py` (`find_secrets`, for literals) → `tests/test_mcp_rules.py`, `tests/fixtures/mcp-*/`, `tests/test_rule_catalog.py` (`RUNTIME_SETUP` builds tokens from pieces; `.gitfixture` stages files; `home/.claude.json` takes `{HOME}` and `{REPO}`) | [`rules/mcp.md`](rules/mcp.md), [`rules/discovery.md`](rules/discovery.md) |
| Add or change a settings scope rule (managed-only keys, committed MCP approval, tracked local settings, `claudeMdExcludes`) | `src/rigcheck/rules/settings.py` (`KEY_SCOPES`, `settings_docs`) → `src/rigcheck/parse/config.py` (`key_line`) → `src/rigcheck/model.py` (`Rig.is_tracked`) → `tests/test_settings_rules.py`, `tests/fixtures/<rule-id>/` (a `.gitfixture` makes files tracked) | [`rules/settings-and-permissions.md`](rules/settings-and-permissions.md) |
| Refresh the vendored settings schema | `python scripts/update_schema.py <commit>` → `src/rigcheck/data/claude-code-settings.schema.json` and `.meta.json` (shipped as package data; `NOTICE` holds the attribution) → re-run `tests/test_settings_rules.py` and the smoke | [`rules/settings-and-permissions.md`](rules/settings-and-permissions.md) |
| Check a skill or command's injected commands (literal `!`, relative paths, coverage by `allowed-tools`) | `src/rigcheck/rules/skill_body.py` → `src/rigcheck/parse/markdown.py` (`find_injections`) → `src/rigcheck/rules/components.py` (`load`, `tool_entries`) → `src/rigcheck/parse/permissions.py` (`parse_rule`, `bash_covers`), `src/rigcheck/rules/permissions.py` (`settings_allow_rules`) → `src/rigcheck/parse/shell.py` (`segments`, `uncommented`, `words`) → `tests/test_skill_injection_rules.py`, `tests/fixtures/skill-injection-*/` | [`rules/skills-and-commands.md`](rules/skills-and-commands.md) |
| Change permission-rule parsing or a permission rule (shadowing, path tools, Bash wildcards, secret files without a Read deny) | `src/rigcheck/parse/permissions.py` (`parse_rule`, `bash_covers`) → `src/rigcheck/rules/permissions.py` → `tests/test_parse_permissions.py`, `tests/test_permission_rules.py`, `tests/fixtures/permission-*/`, `tests/fixtures/secret-file-not-denied/` | [`rules/settings-and-permissions.md`](rules/settings-and-permissions.md) |
| Add or change a secret or remote-exec check | `src/rigcheck/parse/secrets.py` (`find_secrets`, `classify`) → `src/rigcheck/rules/secrets.py` → `src/rigcheck/parse/shell.py` (`pipeline`, `runs_inline`) → `tests/test_parse_secrets.py`, `tests/test_secret_rules.py`, `tests/fixtures/secret-literal/` (its token is built at runtime in `RUNTIME_SETUP` in `tests/test_rule_catalog.py`, so no pattern-valid token is committed) | [`rules/secrets.md`](rules/secrets.md) |
| Change the context budget | `src/rigcheck/report/budget.py` → `src/rigcheck/rules/budget.py` → `tests/test_budget.py`, `tests/test_budget_rules.py` | [`rules/context-budget.md`](rules/context-budget.md) |
| Change a report or the JSON schema | `src/rigcheck/report/terminal.py` or `json.py` → `tests/test_engine_and_reports.py` → the usage section of `README.md` | [`README.md`](../README.md) |
| Add a CLI flag or command | `src/rigcheck/cli.py` → `tests/test_cli.py` → the usage section of `README.md` | [`README.md`](../README.md) |
| Change the ranking or how a failing rule is reported | `src/rigcheck/engine.py` → `tests/test_engine_and_reports.py` | [`plans/v1.md`](plans/v1.md) |

## Layers

One package, `src/rigcheck/`, built with `uv_build` (`pyproject.toml`); lint bans relative imports, so every import is absolute.

- **`model`** (`model.py`): owns the data types: `Artifact`, `Finding`, `Rule`, `Rig`, and the `Layer`, `LoadClass`, `Kind` and `Severity` enums (declaration order is rank order). References nothing else in the package. `Rig` caches file text and the git file lists; the `~/.claude.json` file is never an artifact.
- **`parse`** (`src/rigcheck/parse/`): owns readers for the file formats: frontmatter, Markdown, JSON config, glob patterns and token estimates. Pure functions over text.
- **`discover`** (`discover.py`): owns building the `Rig` from the repo, memory, user and plugin layers, and the classification tables that give each file a `Kind` and `LoadClass`. References `model` and `parse`.
- **`rules`** (`src/rigcheck/rules/`): owns the checks, one module per area. `src/rigcheck/rules/__init__.py` holds `REGISTRY`, the `rule` decorator and the `emit` and `emit_setup` builders, and imports every area module so its rules register. `components.py` and `config.py` hold the helpers the area modules share. A rule takes a `Rig` and yields `Finding`s.
- **`engine`** (`engine.py`): owns running the registered rules and ranking findings by severity, load class, layer, path and line. A rule that raises becomes one `internal-error` finding; the other rules still run.
- **`report`** (`src/rigcheck/report/`): owns output: `terminal.py`, `json.py` (`SCHEMA_VERSION` 1) and `budget.py`, the context budget, which is a report and not a rule.
- **`cli`** (`cli.py`): owns the `rigcheck check` command; it wires `discover`, `engine` and `report` and sets the exit status (0, 1 with a finding at or above `--fail-on`, 2 on a usage error).

What is planned is in Linear (team RIG), snapshot in [`plans/MAIN.md`](plans/MAIN.md).

## Integration Footguns

- Pytest's `--basetemp` cannot point into the repo's `.tmp/`: the fixture copies would then sit inside rigcheck's own git repo, and the git-dependent rules would see it instead of the fixture's.

- **A new rules module** must be added to the import list at the bottom of `src/rigcheck/rules/__init__.py`; a module nothing imports never registers its rules, and no test fails for it.
- **A new rule** needs `bad/` and `good/` fixture folders named for the rule id under `tests/fixtures/`, a non-empty `evidence` tuple, a summary (the check's docstring first line) and pack `core`; `tests/test_rule_catalog.py` enforces all of it and runs every fixture through the CLI, failing on any `internal-error`. The engine-only ids `internal-error` and `discovery-error` are exempt from fixtures.
- **A rule id registered twice**, or a check with no docstring, raises when `rigcheck.rules` is imported.
- **A new `Kind`** in `model.py` needs an entry in `discover.py`'s tables (`_CLAUDE_DIR_FILES` for the user and repo `.claude/` folder, `_PLUGIN_FILES` for plugins) and, for a frontmatter kind, in `KEYS` and `FRONTMATTER_KINDS` in `src/rigcheck/rules/components.py`.
- **The built-in tool and agent tables** in `src/rigcheck/rules/agents.py` are a snapshot of one Claude Code version (recorded in `docs/research/builtin-tables-probe.md`); `src/rigcheck/rules/agent_refs.py` resolves against them, so a new Claude Code tool reads as `agent-tool-unknown` until they are updated.
- **Rule catalog**: `docs/plans/v1.md` lists every rule id; a rule added, renamed or removed changes it too (the project's docs map says so, but no test checks it).
- **Fixtures that need runtime setup** (UNC symlinks, a file past the size limit, external symlinked rule folders) are built by `RUNTIME_SETUP` in `tests/test_rule_catalog.py`, because the harness copies fixtures with `copytree`, which dereferences links.
- **The `secret-literal` bad fixture holds no token**: `RUNTIME_SETUP` in `tests/test_rule_catalog.py` appends one built from string pieces, and tests build theirs the same way, so no committed file holds a pattern-valid token. A test or fixture that writes a whole token as one literal breaks this.
- **Fixture files are written with LF**; a CRLF fixture changes the byte counts that size rules measure.

## Test locations

`tests/` mirrors the package; helpers are in `tests/support.py` (a fake home with rigs inside it, CLI runs) and `tests/conftest.py`.

- `tests/test_rule_catalog.py`: every registered rule has evidence, both fixtures, and fires on `bad` and stays silent on `good`. A new rule's fixtures go in `tests/fixtures/<rule-id>/bad/` and `good/`.
- `tests/test_discover.py`, `tests/test_claude_json.py`: discovery of each layer, and `~/.claude.json` server extraction.
- `tests/test_engine_and_reports.py`, `tests/test_budget.py`, `tests/test_cli.py`: engine ranking, the two report formats, the budget and the command line.
- `tests/test_parse_config.py`, `tests/test_parse_properties.py`, `tests/test_markdown.py`, `tests/test_globs.py`, `tests/test_references.py`: the parsers and shared reference logic (`test_parse_properties.py` holds property tests).
- `tests/test_agent_rules.py`, `tests/test_agent_ref_rules.py`, `tests/test_skill_rules.py`, `tests/test_skill_name_rules.py`, `tests/test_skill_injection_rules.py`, `tests/test_rules_dir.py`, `tests/test_output_style_rules.py`, `tests/test_memory_rules.py`, `tests/test_secret_rules.py`, `tests/test_parse_secrets.py`, `tests/test_budget_rules.py`, `tests/test_components.py`, `tests/test_config_helpers.py`, `tests/test_mcp_rules.py`: behavior beyond the fixtures for each rules module.
- The smoke script `.claude/skills/rigcheck-nextup/smoke.sh` runs rigcheck over real repos and `$HOME` after a discovery or rule change.

## Deep docs

- [`README.md`](README.md): docs start page and glossary.
- [`rules/README.md`](rules/README.md): one doc per rule area (what each rule checks, and the design it settles, with reasons).
- [`plans/MAIN.md`](plans/MAIN.md): the generated snapshot of the plan in Linear (team RIG).
- [`plans/v1.md`](plans/v1.md): the v1 architecture sketch, rule catalog and milestones.
- [`research/official.md`](research/official.md): official Claude Code guidance; every rule's `official:<id>` evidence points here.
- [`research/sota.md`](research/sota.md): evidence-graded non-official work; `sota:#<n>` evidence points here.
- [`research/frontmatter-probe.md`](research/frontmatter-probe.md), [`research/agent-values-probe.md`](research/agent-values-probe.md), [`research/builtin-tables-probe.md`](research/builtin-tables-probe.md): probes of Claude Code behind the frontmatter, agent-value and built-in-table rules.
