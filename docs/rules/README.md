# Rule areas

One doc per rule area: what the area checks, its rule ids with severity and evidence, and the design decisions behind each rule, stated as current behaviour. The rule catalog is in [`../plans/v1.md`](../plans/v1.md); terms are in the glossary in [`../README.md`](../README.md).

- [`discovery.md`](discovery.md): building the rig: layers, the home-folder check, rules-folder links, the `~/.claude.json` read, MCP server definitions, JSON config loading, and `discovery-error`.
- [`instructions.md`](instructions.md): instruction files and `@imports`, stale path and script references, and the auto-memory folder.
- [`context-budget.md`](context-budget.md): the token estimate of every-turn files and the skill and agent listings, and the two over-budget findings.
- [`frontmatter-and-rules-dir.md`](frontmatter-and-rules-dir.md): reading component frontmatter as Claude Code does, the portability warn, and the rules-directory rules and `paths` globs.
- [`skills-and-commands.md`](skills-and-commands.md): skill and command frontmatter, names and options, bundled-file links, and injected commands, `$N` and arguments in the body.
- [`agents.md`](agents.md): skipped agents, agent keys and values, tools, preloaded skills, name collisions, and the agents skills fork to or dispatch.
- [`output-styles.md`](output-styles.md): output-style keys and `keep-coding-instructions`.
- [`hooks.md`](hooks.md): hook maps, hook structure, and the commands hooks run.
- [`settings-and-permissions.md`](settings-and-permissions.md): config files that do not load, the settings schema, permission rules, and secret files without a Read deny.
- [`mcp.md`](mcp.md): MCP server types, the variable references Claude Code does not expand in a server definition, credential literals in a shared config, and server names defined in more than one scope.
- [`secrets.md`](secrets.md): credential literals in instruction, memory, skill, command and agent files, and skills and commands that pipe a downloaded script into a shell.

`internal-error` belongs to the engine: a rule that raises becomes one `internal-error` finding and the other rules still run.
