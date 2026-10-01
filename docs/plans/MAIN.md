# rigcheck plan
<!-- plan-doc-hygiene: 2026-09-27 bce4e43 -->

Open work only. A finished item leaves this index in its landing commit; the design it settled lives in the rule-area docs under [../rules/](../rules/README.md), and git history keeps the item itself.

## Current focus

### Wave 2 — M4 config rules (new `rules/` modules for hooks, settings, MCP, secrets, duplication; gate: `code-review` plus smoke)

M4 Config rules: hooks, settings (vendored schema), MCP, secrets, duplication, split by module (all read [v1.md](v1.md#rule-catalog-v1-ids-from-docsresearch) and the ids' entries in [official.md](../research/official.md)). Discovery already finds settings, repo and plugin `.mcp.json`, plugin `hooks/hooks.json` and `plugin.json` (`Kind.SETTINGS`/`HOOKS_CONFIG`/`MCP_CONFIG`/`PLUGIN_MANIFEST`), and `rules/config.py` reads them. M4k waits on nothing now that the permission grammar is in; M4i goes last (it reuses `parse/secrets.py` from M4h).

Rulings (user): MC7 (server instructions over 2,048 characters) needs the server's own output, so it leaves v1 for the backlog; `duplicate-line` compares the every-turn files plus any AGENTS.md peer, loaded or shadowed; hook and MCP rules also read `hooks` and `mcpServers` inline in a plugin's `plugin.json`, and managed/policy settings are out of scope; `mcp-secret-literal` fires on git-tracked repo `.mcp.json` and plugin `.mcp.json` only, never on `~/.claude.json`. Technical choices in each sub-item (schema pin, grammar boundaries, duplicate measure, line lookup, split severities) are settled by the orchestrator against the smoke corpus when the sub-item is briefed.

- [ ] M4k Skill injections not covered by `allowed-tools` (SK22, SK24) in `rules/skill_body.py`, on M4f's permission grammar (after M4f; user ruling: its own line, not part of M4f)
- [ ] M4i MCP in `rules/mcp.py` (after M4b and M4h): `mcp-secret-literal`, `mcp-credential-var-remote`, `mcp-project-dir-no-default`, `mcp-type-invalid`, `mcp-server-conflict` (MC1, MC3–6)
- [ ] M4j Duplication in `rules/duplication.py`: `duplicate-line` (info) across every-turn files

## Next up

### Wave 3 — M5 to M7 (CLI surface and packs, in order)

- [ ] M5 Suppressions, advice pack, `explain`, `brief`
- [ ] M6 `--deep` checks via `claude -p`
- [ ] M7 House pack, the `rigcheck` Claude Code skill, install docs

## Backlog

- [ ] `rigcheck check .` on rigcheck reports 12 `reference-path-missing` findings in `docs/research/` (`official.md` 7, `permissions-grammar.md` 4, `sota.md` 1): the notes quote Claude Code paths such as `.claude/rules/` that are examples, not this repo's files; mark those lines with the allow comment or reword them, so rigcheck checks itself clean
- [ ] Probe whether Claude Code keys `~/.claude.json` `projects` by the main checkout or by the worktree folder for a session opened in a git worktree (M4b matches the worktree's own root, so a worktree run may miss the main repo's local-scope servers); open a session in a worktree, add a local-scope server, and read which key appears (from the M4b review)
- [ ] `parse/shell.py` `_operand` still reads the value of `bash -o <option>` and `uv run --with <pkg>` as the script word, so a value holding `/` is resolved as a hook script path (from the M4d implementer); add both to the value-taking flag tables
- [ ] `secret-literal` misses an encrypted PEM private key: its body starts 3 or more lines after the header (`Proc-Type` and `DEK-Info` lines come first), past the 2-line window in `parse/secrets.py` (from the M4h implementer)
- [ ] `skill-remote-exec` does not scan a skill's supporting files (`references/*.md`, `resources/**`); 26 such files on this machine hold `curl … | sh`; decide whether bundled Markdown files count (from the M4h implementer)
- [ ] MC7: MCP server instructions over 2,048 characters. Needs the server's own output (starting or contacting it), which offline-by-default forbids; left out of v1 (user, 2026-09-27)
- [ ] Section citations that name a missing heading: a skill or instruction file cites `<file or skill> § "<Heading>"` (or "`<skill>` <Heading>") and the target has no such heading. `skill-link-broken`, `skill-file-unreferenced` and `reference-path-missing` resolve files only; nothing under `src/` resolves headings. Prior art: muthur `scripts/check-skill-catalog.sh` check 6 (github.com/vzakharov/muthur) (user, 2026-10-01)
- [ ] Warn when the every-turn instruction files (CLAUDE.md plus its `@`-imports) pass a size threshold; muthur's `scripts/check-claude-md-size.sh` uses 30,000 characters. `instructions-too-large` (`src/rigcheck/rules/instructions.py:25`) fires only at Claude Code's 4 MiB skip, and the context budget never moves the exit status. Muthur's ratchet (a branch over the cap must come back to 29,000) needs a baseline that one offline run does not have (user, 2026-10-01)

## Decisions (user)

- Targets: the Claude Code layer plus `AGENTS.md` as a peer file, including drift between the two.
- Scope of a run: the effective setup; findings tagged by layer. Only the checked project's own memory folder is read.
- Checks: deterministic and offline by default; semantic checks only behind `--deep`, sent through headless `claude -p`.
- Fixes: findings carry a fix and rigcheck can write a fix brief; it never edits the checked files.
- No overall score: findings ranked by severity × load cost.
- Rule packs: `core` (sourced) and `house` (the user's conventions, written generically, enabled per machine).
- Suppression: per-repo config, each entry with a mandatory reason; a reasonless suppression is itself a finding.
- Public repo `leftos/rigcheck`, MIT license.
