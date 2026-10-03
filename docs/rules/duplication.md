# Duplication

`duplicate-line` lives in `src/rigcheck/rules/duplication.py`. It reports an instruction that two always-loaded files both state. The basis is maintenance only. Claude Code's memory docs (MM5 in [`../research/official.md`](../research/official.md)) skip what CLAUDE.md already says. The research (sota §5 #9 in [`../research/sota.md`](../research/sota.md)) finds no adherence effect either way, so the finding is `info`. Its message makes no compliance claim, only that two copies drift apart when one is edited. Reworded duplicates need judgement and belong to `--deep`.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `duplicate-line` | info | `official:MM5`, `rigcheck:duplication` |

## Files compared

- The rule compares every every-turn artifact that is Markdown: the user and repo CLAUDE.md, their imports, rules with no `paths`, and the MEMORY.md index. It adds the repo's AGENTS.md even when it is shadowed (not loaded because a CLAUDE.md exists): that file is the peer Codex reads, and its copy drifts the same way.
- `AGENTS.local.md` and `AGENTS.override.md` are never compared, since Claude Code never reads them. Neither are files loaded on demand, on invoke, or as config.
- A file is never compared with itself, including through a symlink: an AGENTS.md that links to CLAUDE.md (a common way to share one file between Codex and Claude Code) is the same file, compared once. A sentence repeated inside one file is that file's business, not a cross-file drift.

## What is compared

- **The unit is the clause, not the whole line.** A real duplicate is usually one sentence inside a long bullet. In `D:/yaat`, `AGENTS.md` lines 24, 25 and 88 restate one sentence of `CLAUDE.md:242`. A whole-line comparison scores that pair at 0.29 to 0.67 and misses it.
- **Which lines are read:**
  - Only prose lines, from `prose_segments`, read from the first line after any frontmatter. Code blocks, fences and HTML blocks are skipped, since commands repeat across files legitimately.
  - Headings (`#` headings and underlined ones), table rows and lines that are only an `@path` import are skipped.
  - The raw line is used rather than the code-span-blanked one, so a command named in backticks still counts. Link destinations, autolinks and inline HTML tags are removed from it first, since a shared URL is not a shared instruction.
- **How a line becomes clauses:**
  - A leading list marker is removed, along with every `` ` `` and `*`.
  - The line is split after `.`, `;`, `!` or `?` when whitespace or the end of the line follows, and after `: `.
  - Tokens are `[a-z0-9._/-]+` after case-folding, with dots trimmed from both ends.
  - A clause of fewer than 5 distinct tokens is ignored, because short clauses such as "Run the tests" repeat by chance.
- **What counts as a match:**
  - Exact when two clauses have equal tokens.
  - Near when the shared tokens are at least 0.8 of the smaller token set and the larger set is at most twice the smaller. The second condition stops a short clause from matching inside a long one.
  - Example: "never pass -q, -v q, --nologo or extra quieting flags to dotnet format" against "do not pass -v q, --nologo, or extra flags to dotnet format" shares 10 of 12 tokens, so it is near.
- **Speed:** candidate pairs come from an inverted index of tokens, and a candidate whose token set is less than half or more than twice the size of the clause is skipped before counting. The rule runs in well under a second (0.07 s for `D:/yaat`'s 679 clauses).

## Where the finding sits

- Files are ordered as Claude Code loads them. User-level files come first (`~/.claude/CLAUDE.md`, its imports, user rules), then repo files, then memory. Within a layer the order is discovery's. A shadowed AGENTS.md comes after every loaded file, since Claude Code never reads it. A line is reported when one of its clauses matches a clause in an earlier file. The earlier copy is the one to keep, and the later copy is the one to delete or replace with an import.
- There is one finding per line, even when several of its clauses match. It names the earliest match, preferring an exact match to a near one: `repeats <file>:<line>` or `nearly repeats <file>:<line>`.
- `<file>` is relative to the repo root, starts `~/` for a file in the home folder, and is otherwise the full path. The message never quotes the text, so a report never prints a user's files.
