# Discovery and layers

Discovery builds the `Rig`: every artifact of the effective setup, tagged with its kind, layer and load class, plus the problems met reading it. It lives in `src/rigcheck/discover.py`; the data types are in `src/rigcheck/model.py`, and the helpers that read hook maps and MCP server definitions out of the discovered config files are in `src/rigcheck/rules/config.py`. Discovery never raises for an unreadable or malformed input: each one becomes a problem string, which the `discovery-error` rule reports. Terms such as rig, effective setup, layer and load class are defined in the glossary in [`../README.md`](../README.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `discovery-error` | warn | `rigcheck:discovery` |
| `internal-error` | error | `rigcheck:engine` |

`discovery-error` and `internal-error` are registered in `src/rigcheck/rules/instructions.py`. `internal-error` never fires from its own check: the engine emits it in place of a rule that raised, and the other rules still run.

## Layers

- **Repo**: the instruction chain, nested `CLAUDE.md` files below the target, repo docs, the repo's `.claude/` folder (rules, skills, commands, agents, output styles, `settings.json`, `settings.local.json`) and the repo's `.mcp.json`. The repo root is `git rev-parse --show-toplevel`; outside git it is the target itself.
- **User**: `~/.claude/CLAUDE.md` and the same `.claude/` contents under the home folder. In both `.claude/` folders, commands and agents are found at any depth (`commands/**/*.md`, `agents/**/*.md`); skills are `skills/*/SKILL.md` and output styles `output-styles/*.md`.
- **Plugin**: every plugin in `~/.claude/plugins/installed_plugins.json` that `enabledPlugins` turns on (user, project and local settings merged, later files winning) and whose install entry applies (user scope, or project or local scope for this repo root). A plugin contributes `skills/*/SKILL.md`, flat `agents/*.md` and `commands/*.md`, `output-styles/*.md`, `hooks/hooks.json`, `.mcp.json` and `.claude-plugin/plugin.json`. Plugins ship no `rules/` folder, so no rule file comes from this layer.
- **Memory**: `MEMORY.md` and the topic files in this repo's own memory folder only.
- Nested `CLAUDE.md` files come from git's file list inside a repository; outside one, a walk of the target that skips `SKIP_DIRS` (`.git`, `node_modules`, `.venv`, `bin`, `obj`, `dist`, `build`, `.tmp`) and does not enter junctions.

## The home folder as target

When the target is the home folder itself, only `~/.claude` is checked: there is no repo-layer instruction chain, no nested `CLAUDE.md` walk, no `CLAUDE.md` directly in the home folder, no repo docs and no repo `.mcp.json`; plugins and memory are still discovered. A walk of the whole home folder visits every folder, and the nested `CLAUDE.md` files it finds there sit mostly in tool and test temp folders under AppData, not in instructions anyone loads; the home check must finish in a few seconds. A subfolder of home that is not a git repository keeps the usual walk and its exclusions.

## Rules folders

- The `rules/` walk follows links to folders, because a rule reached through a linked folder loads, but reports a link to a network path as itself and never enters it. A real folder under `rules/` always wins over a link resolving to it; between links to one folder outside `rules/`, the first in walk order wins.
- A rule with `paths` that is reached through a link out of the project is recorded as not loaded on the repo layer, because Claude Code does not load an external rule that carries `paths` ([`frontmatter-and-rules-dir.md`](frontmatter-and-rules-dir.md) has the rule that reports it).
- A rule without `paths` loads every turn; a rule with `paths` loads on demand; a file over 4 MiB or linked to a network path is not loaded.

## `~/.claude.json`

- The file holds credentials, so it is never an artifact and never cached: `Rig.text` and the reports never hold it. Discovery parses it once and extracts only `mcpServers` (user scope) and `projects[<repo root>].mcpServers` (local scope) into `Rig.user_mcp_servers`, user-scope servers first.
- The `projects` key naming the repo folder is found by comparing paths with `normcase` and `normpath`. The local scope is read for a non-git target too (its repo root is the target), and never for the home check.
- An unreadable file, one that is not UTF-8, invalid JSON, a top level that is not an object, and a file that links to a network path are each one discovery problem that names the file and the error kind, never its content. A missing file is no problem.
- A server's config value may hold secrets, so it never goes into a finding message or a report.

## MCP server definitions

- `mcp_servers` in `src/rigcheck/rules/config.py` reads the repo `.mcp.json`, each plugin's `.mcp.json` and each plugin manifest. Servers under a top-level `mcpServers` object are read from it.
- A plugin `.mcp.json` with no `mcpServers` key names its servers at the top level, because many published plugins write the file flat; a repo `.mcp.json` is never read flat. An `mcpServers` key that is present but not an object defines no servers, and a server whose name is not a string is skipped.

## JSON config text

`src/rigcheck/parse/config.py` loads every JSON config kind and locates keys for finding lines.

- `load` returns the parsed value or a problem. An empty or whitespace-only text does not load; a syntax error names its line and column; `NaN`, `Infinity` and `-Infinity`, which Python's parser accepts and JSON does not, are a problem naming the token; and a document the parser refuses without a syntax error (a number too long to convert, nesting too deep) is a problem naming the error type, never a crash. No problem message carries the file's content.
- `key_line` finds a key by its path from the root through objects only, so a quoted text inside a string value or an array never counts. A key written more than once resolves to its last occurrence, the one `json.loads` keeps, and keys are compared by decoded text, so an escaped non-ASCII key is found.
