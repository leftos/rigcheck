# Component frontmatter and the rules directory

Skills, commands, agents, rules and output styles carry YAML frontmatter, and rigcheck reads it the way Claude Code does, so every rule sees the values Claude Code loads. The loader is `src/rigcheck/parse/frontmatter.py`; the shared helpers (artifact selection, the per-kind key tables, `misplaced_fence`, `case_match`, the unknown-key message) and the portability warn are in `src/rigcheck/rules/components.py`. The rules directory (`.claude/rules/*.md`) has its own rules in `src/rigcheck/rules/rules_dir.py`, with `paths` pattern handling in `src/rigcheck/parse/globs.py`. The terms frontmatter retry and load class are in the glossary in [`../README.md`](../README.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `frontmatter-yaml-nonstandard` | warn | `official:SK1`, `official:AG1`, `rigcheck:frontmatter-probe` |
| `rule-key-unknown` | warn | `official:RL1` |
| `rule-frontmatter-invalid` | error | `official:RL2` |
| `rule-glob-invalid` | error | `official:RL3` |
| `rule-glob-unmatched` | warn | `official:RL3` |
| `rule-external-scoped` | warn | `official:RL7` |

## Reading frontmatter

- Frontmatter is present only when the file's first line (after a byte-order mark) is exactly `---`, and it runs to the next `---` line. An unclosed block is rejected by both strict YAML and Claude Code.
- `parse` returns the data Claude Code loads, the strict YAML error, the Claude Code error, each top-level key's line and the body's first line. Claude Code's own accept/reject rule is reproduced: when strict YAML fails with a syntax error, the block is parsed again through the frontmatter retry, which re-quotes a `key: value` line whose unquoted value holds `: ` or a YAML indicator (`{ } [ ] * & # ! | > % @` or a backtick) and expands leading tabs. A line ending in CR never matches the retry, as in Claude Code. The rule was pinned by a probe of `claude plugin validate` ([`../research/frontmatter-probe.md`](../research/frontmatter-probe.md)); where the probe cannot settle what Claude Code loads, rigcheck leans to "loads".
- The outcome decides the finding: a block Claude Code rejects is the kind's invalid or skipped error (`skill-frontmatter-invalid`, `agent-skipped`, `rule-frontmatter-invalid`), and a block Claude Code loads but strict YAML rejects is `frontmatter-yaml-nonstandard`, one portability warn per file on every frontmatter kind and every layer. Every other rule runs on the data Claude Code loads.
- Booleans read `true`/`yes`/`on`/`1` and `false`/`no`/`off`/`0` (any case, and the YAML booleans and integers 1 and 0) through one function, `as_bool`.
- A wrong-case or kebab/snake variant of a known key (a key equal to a known one once case, `-` and `_` are folded away) is reported under the kind's `*-key-unknown` rule with a "did you mean".
- A `---` that is not on line 1 counts as misplaced frontmatter only when it is the first non-blank line and a closing `---` follows it, so a leading horizontal rule is not frontmatter. A skill or command reports it as `skill-frontmatter-misplaced`, an agent as `agent-skipped`.
- A flow list such as `allowed-tools: [Read, Grep]` in a block only the retry loads becomes a string, so every rule that reads `allowed-tools` or an agent's `tools` accepts a string there and splits it into entries.
- `read_lenient` reads chosen top-level keys (and one level of nesting, such as `metadata.type`) from a block strict YAML rejects; the memory rules use it.

## Key tables

The recognised keys per kind are in `KEYS` in `src/rigcheck/rules/components.py`, each taken from its entry in [`../research/official.md`](../research/official.md): skills, commands (the skill keys except `name` and `paths`), agents, rules (`paths` only) and output styles.

## Rules directory

- Rule files come from the `rules` folder of the repo and user `.claude` folders only; plugins ship no `rules/` folder. How links in `rules/` are walked is in [`discovery.md`](discovery.md).
- `rule-key-unknown` reports every key other than `paths`.
- `rule-frontmatter-invalid` reports frontmatter Claude Code rejects, because such a rule loads every turn as if it had no `paths`. A rule that does not load is skipped.
- `rule-external-scoped` reports a repo-layer rule reached through a link out of the project that has `paths`, because Claude Code never loads it; a rule linked to a network path is left to `unc-symlink`.

## `paths` patterns

- `paths` is a string or a list; non-string items and blank patterns are dropped.
- Matching uses the `wcmatch` dependency with picomatch-like flags: `**` crosses folders, braces expand, `*` and `**` match dotfiles, `/` is the only separator, a leading `./` is ignored, and case folds on Windows only.
- `rule-glob-invalid` and `rule-glob-unmatched` check repo-layer rules only.
- `rule-glob-invalid` reports each pattern with a `[` that starts no bracket expression (unescaped, and not closed by a `]` later in the same path segment with at least one member between), one finding per pattern. It also reports, once per rule, a `paths` list whose brace expansion passes 1,000 patterns or 4 MiB across the whole list, because Claude Code then matches none of its braces. Negated (`!`) patterns count for both checks.
- `rule-glob-unmatched` reports each non-negated pattern that matches no file, one finding per pattern. The file list is `git ls-files -co --exclude-standard`; a pattern the list misses is then globbed on disk under the repo root before it is reported, which covers git-ignored folders, submodule contents and nested repositories. Negated patterns, patterns with a bracket error, over-budget rules, rules that do not load, and every rule outside a git repository are skipped.
- The RL7 fixture needs a real symlink, which the catalog harness's `copytree` would dereference, so it is built by `RUNTIME_SETUP` in `tests/test_rule_catalog.py`.
