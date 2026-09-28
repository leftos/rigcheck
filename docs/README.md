# rigcheck docs

Start here. The plan index is [plans/MAIN.md](plans/MAIN.md).

## Glossary

- **Rig**: the whole instruction setup an agent runs on in one place: repo files, user-level files, plugins, hooks and memory.
- **Effective setup**: the part of the rig Claude Code actually loads for a given repo: the repo layer, the user layer (`~/.claude`) and that project's own memory folder.
- **Layer**: where a file comes from: `repo`, `user`, `plugin` or `memory`. Every finding is tagged with one.
- **Finding**: one rule violation at one location, with a severity, a load cost and a suggested fix.
- **Load class**: when an artifact enters the context: `every-turn`, `on-invoke` (a skill body, a subagent prompt), `on-demand` (nested CLAUDE.md, path-scoped rules, memory topics), `config` (settings, hooks, MCP, which cost nothing unless they inject text), or `not-loaded` (a file Claude Code never reads, such as a shadowed AGENTS.md or an import past four hops).
- **Load cost**: how often a file's content enters the context: every turn (CLAUDE.md, skill and agent descriptions, hook-injected text) or on demand (a skill body, a subagent prompt). Findings are ranked by severity × load cost.
- **Context budget**: the report section, not a rule, that estimates (≈) the tokens a setup costs: every-turn files, the skill listing against 1% of the context window, and agent descriptions against 15,000 tokens. A listing past its limit is also reported as a warn finding.
- **Pack**: a named set of rules. `core` holds rules backed by official documentation or graded evidence; `house` holds opinionated conventions and is off unless enabled.
- **Deep check**: an opt-in check (`--deep`) that asks Claude, through headless `claude -p`, to judge what code cannot: contradictions, reworded duplicates, vague instructions.
- **Fix brief**: a Markdown file rigcheck writes that an agent can execute to fix a set of findings. rigcheck never edits the checked files itself.
- **Frontmatter retry**: Claude Code's second parse of a frontmatter block that strict YAML rejects: it re-quotes unquoted values holding `: ` or a YAML indicator and parses again; rigcheck reproduces it, so `data` is what Claude Code loads ([research/frontmatter-probe.md](research/frontmatter-probe.md)).
- **Suppression**: a per-repo config entry that silences a rule, globally or for a path; every suppression must carry a reason.
