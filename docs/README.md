# rigcheck docs

Start here. The plan lives in Linear (team RIG); [plans/MAIN.md](plans/MAIN.md) is its generated snapshot.

- [`ARCHITECTURE.md`](ARCHITECTURE.md): the architecture entry point: Task Index, layers, integration footguns, test locations and the deep docs.

## Decisions

The user's product decisions; a change to one is the user's call.

- Targets: the Claude Code layer plus `AGENTS.md` as a peer file, including drift between the two.
- Scope of a run: the effective setup; findings tagged by layer. Only the checked project's own memory folder is read.
- Checks: deterministic and offline by default; semantic checks only behind `--deep`, sent through headless `claude -p`.
- Fixes: findings carry a fix and rigcheck can write a fix brief; it never edits the checked files.
- No overall score: findings ranked by severity × load cost.
- Rule packs: `core` (sourced), `advice` (info-only style advice, citing the doc and its null result) and `house` (the user's conventions, written generically, enabled per machine).
- Suppression: per-repo config, each entry with a mandatory reason; a reasonless suppression is itself a finding.
- Public repo `leftos/rigcheck`, MIT license.

## Glossary

- **Rig**: the whole instruction setup an agent runs on in one place: repo files, user-level files, plugins, hooks and memory.
- **Effective setup**: the part of the rig Claude Code actually loads for a given repo: the repo layer, the user layer (`~/.claude`) and that project's own memory folder.
- **Layer**: where a file comes from: `repo`, `user`, `plugin` or `memory`. Every finding is tagged with one.
- **Finding**: one rule violation at one location, with a severity, a load cost and a suggested fix.
- **Load class**: when an artifact enters the context: `every-turn`, `on-invoke` (a skill body, a subagent prompt), `on-demand` (nested CLAUDE.md, path-scoped rules, memory topics), `config` (settings, hooks, MCP, which cost nothing unless they inject text), or `not-loaded` (a file Claude Code never reads, such as a shadowed AGENTS.md or an import past four hops).
- **Load cost**: how often a file's content enters the context: every turn (CLAUDE.md, skill and agent descriptions, hook-injected text) or on demand (a skill body, a subagent prompt). Findings are ranked by severity × load cost.
- **Context budget**: the report section, not a rule, that estimates (≈) the tokens a setup costs: every-turn files, the skill listing against 1% of the context window, and agent descriptions against 15,000 tokens. A listing past its limit is also reported as a warn finding.
- **Pack**: a named set of rules, selected with `--packs`.
  - `core` holds rules backed by official documentation or graded evidence.
  - `advice` holds info-only style advice that cites a doc together with the null result against it.
  - `house` holds opinionated conventions and is off unless named.

  `core` and `advice` run by default.
- **Deep check**: an opt-in check (`--deep`) that asks Claude, through headless `claude -p`, to judge what code cannot: contradictions, reworded duplicates, vague instructions.
- **Fix brief**: a Markdown file rigcheck writes that an agent can execute to fix a set of findings. rigcheck never edits the checked files itself.
- **Covered**: a command is covered when a permission allow rule matches it, as Claude Code matches `Bash(...)` specifiers: each subcommand of a compound command on its own. `skill-injection-not-allowed` reports injected commands that nothing covers.
- **Frontmatter retry**: Claude Code's second parse of a frontmatter block that strict YAML rejects: it re-quotes unquoted values holding `: ` or a YAML indicator and parses again; rigcheck reproduces it, so `data` is what Claude Code loads ([research/frontmatter-probe.md](research/frontmatter-probe.md)).
- **Hook map**: one `hooks` object rigcheck reads, from settings, a plugin's `hooks/hooks.json` or `plugin.json`, or skill, command or agent frontmatter: hook event names, each with a list of matcher groups.
- **Matcher group**: one entry under a hook event: an optional `matcher` (a tool name, a `|` list of exact names, or a regex) and the `hooks` list of handlers it runs.
- **Handler**: one hook to run, with a `type` (`command`, `http`, `mcp_tool`, `prompt` or `agent`) and the fields that type needs.
- **Shell form / exec form**: the two ways a command hook names what to run: shell form is one `command` string a shell parses; exec form is a program in `command` plus an `args` list, spawned without a shell.
- **Vendored schema**: the SchemaStore Claude Code settings schema, copied into `src/rigcheck/data/` at a pinned commit so the settings check runs offline; `scripts/update_schema.py` refreshes it.
- **Permission rule**: one string in a settings file's `permissions.allow`, `ask` or `deny` list: a tool name, optionally with a specifier in parentheses (`Bash(git *)`, `Read(./.env)`).
- **Specifier**: the part of a permission rule inside the parentheses: a command pattern for Bash, a path pattern for Read and Edit.
- **MCP scope**: where an MCP server is defined: `local` (`~/.claude.json` under the repo's `projects` entry), `project` (the repo's `.mcp.json`) or `user` (`~/.claude.json` top level), in that order of precedence; plugin servers sit below them under the name `plugin:<plugin>:<server>`.
- **Settings scope**: which settings file a rule or key comes from: `user` (`~/.claude/settings.json`), `project` (the repo's `.claude/settings.json`) or `local` (`settings.local.json` in the repo's `.claude` folder); Claude Code combines the permission lists of every scope.
- **Managed settings**: the policy tier of settings Claude Code reads from the system managed-settings file or MDM; some keys are honored only there. rigcheck does not read it.
- **Shadowed**: an allow rule that a deny or ask rule in any scope already matches, so it never applies (deny, then ask, then allow; the first match wins).
- **Setup finding**: a finding about the whole setup rather than one file (no path or layer, loads every turn), printed first under a `setup` heading with the location `(setup)`.
- **Script word**: the word of a hook command that names the script it runs: the command word, or the first operand after an interpreter such as `bash` or `python`.
- **Winning copy**: of several skills or commands that answer to one name, the one Claude Code uses: a skill over a command, then user over repo over plugin.
- **Bundled file**: a file inside a skill's folder other than SKILL.md that Claude may be meant to read or run.
- **AGENTS.md peer**: the repo's AGENTS.md beside a CLAUDE.md. Codex reads it; Claude Code reads it only through an `@AGENTS.md` import, so without one it is shadowed. Rules that compare instruction files include it either way.
- **Near-duplicate**: two clauses in different files whose tokens overlap by at least 0.8 of the smaller clause, the larger at most twice the smaller; see [rules/duplication.md](rules/duplication.md).
- **Rule-area doc**: one file under `docs/rules/` per group of related rules, stating what each rule checks and the design it settles, with reasons; see [rules/README.md](rules/README.md).
- **Suppression**: a per-repo config entry that silences a rule, globally or for a path; every suppression must carry a reason.
- **Feature marker**: `branch: feat/<name>` in a Linear project's content; every item under it lands on the `feat/<name>` branch instead of `main` (user-level `nextup` §3, "Feature branches").
- **Feature PR**: the draft pull request from a marker's `feat/<name>` into `main`, opened with the marker and merged with `--rebase` by `/ship` once every issue in the marker's project has landed.
