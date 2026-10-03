# Advice pack

The `advice` pack holds info-only style advice from Anthropic's docs. It runs by default with `core`; `--packs core` turns it off. Each rule cites the doc entry it encodes and, where `docs/research/sota.md` has one, the study row that bears on it, often a null result: a study that found no effect of the thing the advice is about. A finding here is a cost or maintenance note, never a claim that following the advice raises adherence. The rules are in `src/rigcheck/rules/advice_instructions.py`.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `instructions-long` | info | `official:CM1`, `sota:#4 (A)` |
| `emphasis-dense` | info | `official:CM11`, `official:PR4`, `sota:#12 (C)` |
| `instructions-unstructured` | info | `official:CM12`, `sota:#4 (A)` |
| `instructions-long-procedure` | info | `official:CM9`, `sota:#4 (A)` |
| `agents-md-prose-pointer` | info | `official:CM4`, `sota:#2 (A)` |
| `instructions-derivable-dump` | info | `official:CM8`, `sota:#3 (A)` |
| `instruction-better-as-hook` | info | `official:CM10`, `sota:#5 (A)` |

## The whole pack

- Every advice rule is info, whatever severity `docs/research/official.md` suggests (it suggests warn for CM1, CM11 and PR4): `sota.md` §6 rules out line caps and emphasis as errors, and the catalog test enforces info for the pack.
- Only the repo and user layers are checked (`components.maintained`). Plugin files are third-party, so style advice on them is noise.
- Messages and fixes speak of context cost and of what readers can scan, never of adherence: `sota:#4 (A)` found no adherence change from file size (25 to 500 lines), position or splitting, and `sota:#12 (C)` found the effect of all-caps emphasis small or absent on current models.
- A rule that scans prose reads it as `prose_segments` gives it: code blocks, HTML blocks and frontmatter are left out, and code spans are blanked.

## Instruction files

- `instructions-long` counts the body lines of instruction, nested instruction and rule files, a shadowed `AGENTS.md` included, and fires over 200, the target the memory docs give. A line that holds only a block HTML comment is not counted, because Claude Code strips those before loading the file. Rule frontmatter is not counted. The 4 MiB skip stays the core error `instructions-too-large`.
- The other rules check every-turn files only (instruction files and unscoped rules), because their advice is about what loads on every turn.
- `emphasis-dense` counts prose lines that hold a case-sensitive all-caps word from IMPORTANT, CRITICAL, MUST, NEVER, ALWAYS, MANDATORY, REQUIRED, ABSOLUTELY or ESSENTIAL, or the phrase "if in doubt" (the PR4 trigger). It fires when 5 or more lines, and at least 5% of the non-blank prose lines, are emphasized; the doc names no number, so this is rigcheck's own threshold. Sentence-case "Never" is not emphasis, and bold is not counted, because bold labels such as `**Rule:**` are structure.
- `instructions-unstructured` fires on a top-level paragraph of 150 words or more, counted in words so hard-wrapped Markdown is measured the same as soft-wrapped, and on a body of 30 or more non-blank prose lines with no heading, list or table. Paragraphs inside list items and blockquotes are not top level. rigcheck parses Markdown as plain CommonMark, which has no tables, so a GFM table inside a paragraph is found by its delimiter row (`|---|---|`, one dash or more per cell) under a line holding a `|`: the table counts as structure, and only the lines above it count as paragraph words.
- `instructions-long-procedure` fires on a top-level numbered list of 8 or more direct items: a procedure that long belongs in a skill, which loads only when invoked. Items of a nested list are not counted. The doc's other signal, a heading that names one subdirectory, is not encoded, since a rule cannot tell a project's layout from a heading.
- `agents-md-prose-pointer` fires on a prose line of `CLAUDE.md` or `CLAUDE.local.md` that names `AGENTS.md` with a verb such as read, see, follow or consult, when an `AGENTS.md` sits beside it (or beside its `.claude` folder) and that AGENTS.md is shadowed: Claude Code sees AGENTS.md only through an import, and once any file in the chain imports it, directly or through another import, the pointer is harmless. A pointer to any other file is not flagged, because naming a doc for Claude to open when needed is progressive disclosure, which an import would undo by loading it every turn. No study tests prose pointers; `sota:#2 (A)` is cited because agents act on what context files name. It can fire beside the core `agents-md-shadowed`, which reports the missing import once per file.
- `instructions-derivable-dump` fires on a code block that is a directory tree (8 or more non-blank lines, at least 60% of them a branch: indentation and `│` or `|`, then `├──`, `└──`, `|--`, `+--` or `` `-- ``, then a space and a name; a box-drawn diagram has no such lines and is not a tree) or a dependency list (a run of 15 or more lines shaped `name==1.2`, `"name": "^1.2.3"` and the like, a dotted version required so plain numeric settings do not count). Claude can list the tree or read the manifest itself, and the copy goes stale (`sota:#3 (A)`: generated overviews were mostly redundant with the repo). The doc's other examples (file-by-file descriptions, tutorials, API docs) need judgement and are not encoded.
- `instruction-better-as-hook` fires on a line that ties an action to a moment ("always run X before every commit", "after each edit") or forbids touching a protected file (`.env`, secrets, credentials, lockfiles), each matched as a whole name, so `process.env` or "secretary" does not count. Such rules must hold every time, and an instruction is a request; `sota:#5 (A)` measured adherence decaying within a session. It does not check whether a hook already enforces the rule, since matching hooks to prose needs judgement. This rule and `agents-md-prose-pointer` match the line as written, so a code span such as `` `.env` `` counts; fenced lines never do.
