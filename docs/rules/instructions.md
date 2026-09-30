# Instruction files, imports, references and memory

This area checks the always-on instruction files (`CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md` and the files they `@import`), the paths and commands those files and the repo's docs name, and the auto-memory folder. The instruction chain and its imports are built by `src/rigcheck/discover.py`; the rules are in `src/rigcheck/rules/instructions.py`, `src/rigcheck/rules/references.py` and `src/rigcheck/rules/memory.py`; Markdown reading (code spans, links, code block lines, `@` imports, HTML comments) is in `src/rigcheck/parse/markdown.py`. Terms such as layer, load class and finding are defined in the glossary in [`../README.md`](../README.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `instructions-too-large` | error | `official:CM1` |
| `import-unresolved` | error | `official:CM2` |
| `import-too-deep` | warn | `official:CM2` |
| `import-cycle` | warn | `official:CM2` |
| `import-external` | info | `official:CM3` |
| `claude-local-tracked` | warn | `official:CM13` |
| `claude-local-hides-agents-md` | warn | `official:CM14` |
| `agents-md-shadowed` | warn | `official:CM15` |
| `claude-never-reads` | info | `official:CM16` |
| `unc-symlink` | error | `official:CM19` |
| `reference-path-missing` | warn | `sota:#2 (A)`, `sota:#23 (B)` |
| `reference-script-missing` | warn | `sota:#2 (A)`, `sota:#23 (B)` |
| `memory-index-too-large` | error | `official:MM1` |
| `memory-link-broken` | warn | `official:MM3` |
| `memory-topic-orphan` | info | `official:MM3` |
| `memory-type-unknown` | info | `official:MM4` |

## Instruction files and imports

- The instruction chain is every `CLAUDE.md` (in a folder or in its `.claude` folder), `CLAUDE.local.md` and `AGENTS.md` from the filesystem root down to the target, stopping at the home folder when the target is inside it, plus `~/.claude/CLAUDE.md` on the user layer. When the chain holds any CLAUDE-family file, every `AGENTS.md` in it is recorded as not loaded, because Claude Code reads AGENTS.md only when no CLAUDE.md is present; an import of that AGENTS.md makes it loaded again.
- `@path` imports are followed breadth-first from every loaded root, so each file is recorded at its shortest import depth. A file reached past four hops is recorded as not loaded and reported by `import-too-deep` on the importing file, because Claude Code follows four hops and drops the rest.
- An import is `@` at a line start or after whitespace, followed by a token that starts `~/`, `./`, `../` or `/` or whose last segment has a file extension, so `@username` in prose is not an import. Code spans, code blocks and HTML blocks never yield imports, and block-level HTML comments are removed first, as Claude Code removes them before it injects the file.
- Imports resolve beside the importing file; `~/` resolves at the home folder.
- `import-external` fires only for repo-layer files importing a file outside the repository, because only those trigger the approval dialog teammates see.
- `instructions-too-large` measures instruction, nested instruction and rule files against 4 MiB, the size past which Claude Code skips a file.
- `unc-symlink` reports instruction and rule files that are symlinks to a network (UNC) path. rigcheck never follows such a link: it reads the file as empty and treats it as present, so no network lookup happens.
- `claude-never-reads` reports `AGENTS.local.md` and `AGENTS.override.md` on the chain; those files are kept as not-loaded artifacts only so this rule can see them.

## Path references

- `reference-path-missing` scans, on the repo and user layers, the loaded instruction files, nested `CLAUDE.md` files, rules, the repo's docs, skills, agents and commands, and an `AGENTS.md` that only Codex reads. `AGENTS.local.md` and `AGENTS.override.md` are not scanned. Repo docs are the `.md` files under a top-level `docs/` or `Docs/` folder, leaving out `docs/plans/` and any folder named `archive`, because plans name files that do not exist yet.
- A path is a code span or link target with no whitespace and no leading `#`. A link loses its `#fragment` and `?query` and is URL-decoded; a span loses a `#fragment`, and a span that is one `NAME=value` assignment is judged by its value.
- A token that starts with a known scheme (`tel`, `sms`, `mailto`, `http`, `https`, `ftp`, `file`, `data`, `javascript`, `about`, `urn`, `ssh`, `git`, `vscode`, `vscode-insiders`, `cursor`, `zed`, `obsidian`, `slack`) names no file, and that is decided before a `:line` suffix is dropped. Only listed schemes count, because a dotless scheme test would read `Makefile:12` as the scheme `Makefile:` and never report a missing Makefile, while `tel:5550100` must not read as file `tel` at line 5550100.
- After that, a trailing `:line` or `:line:column` and a pytest `::test` suffix are dropped. A token then names no file when it starts with any other scheme, holds a glob or placeholder character (`* ? [ ] { } < > $ % backtick`), holds `...` or `…`, or has a host name (such as `github.com`) as a first segment followed by `/`. A first segment is a host only when a `/` follows it, so `deploy.sh` and `example.com` alone name files.
- A path token needs a `/` (or a `./` or `../` prefix). Absolute paths and drive-letter paths are skipped, and so is a token whose first segment is a build-output folder (`.git`, `node_modules`, `.venv`, `bin`, `obj`, `dist`, `build`, `.tmp`). `~/` paths are checked against the home folder on every scanned layer.
- Other relative paths are checked on the repo layer only. A relative path is reported only when it is missing both beside the mentioning file and at the repo root, and only when the parent folder of at least one reading exists, so the finding means only the leaf is gone.
- A `../` path that leaves the repository is resolved beside the mentioning file and reported under the same parent-folder rule, because a path into a sibling repository is a real reference that can go stale; a file that names a sibling repo's file without the `../` is reported, and the fix is to write the `../` path.
- Docs, skills, agents and commands are checked more leniently, because they name paths relative to their own context: a single-segment token (`guide.md`, `Training/`) and a token holding `(` (code) are not checked, a `:<symbol>` after a file extension (`File.cs:MethodName`) and a `:<n>-<m>` line range are dropped, a `../` path is looked up beside the file and at the repo root, and a path that exists in a folder given with `--sibling` is fine.
- A line holding `<!-- rigcheck: allow reference-path-missing -->` silences the rule on that line and the next.

## Script references

- `reference-script-missing` reads code spans and code block lines of repo-layer instruction files, nested `CLAUDE.md` files and rules; links, images and code blocks whose language is not a shell (or `just`/`make`) are skipped.
- A segment (split on `&&`, `||`, `;` and `|` outside quotes) is an invocation when it starts `npm run`, `npm run-script`, `pnpm run`, `just` or `make`; the name is the first following word that is not an assignment. An invocation with a flag before the name, or with a flag that points elsewhere (`-C`, `--directory`, `--workspace`, `--filter`, `--prefix`, `-f` and the like), and every invocation after a `cd`, is skipped.
- The name is checked against the nearest `package.json`, justfile or Makefile at or above the mentioning file, up to the repo root. A justfile or Makefile that includes or imports another file is not checked, because the included file may define the name.

## Memory

- The memory layer is the one auto-memory folder Claude Code uses for this repository (`~/.claude/projects/<encoded repo path>/memory/`); other projects' memory is never read.
- `memory-index-too-large` fires when MEMORY.md has more than 200 lines or more than 25,000 bytes. 25 KB is read as 25,000 bytes, and lines are counted by `\n` as Claude Code cuts the file. There is no near-limit warning, because the guidance's "for example 90%" has no source.
- `memory-link-broken` checks Markdown links in MEMORY.md, resolved against the memory folder (`~/` against home). Unlike `reference-path-missing`, a link needs no `/`, so `[build](Makefile:12)` reports a missing `Makefile`.
- `memory-topic-orphan` reports a topic file that MEMORY.md does not link. With no MEMORY.md, no orphans are reported, since there is no index to be missing from.
- `memory-type-unknown` reads both a top-level `type` and `metadata.type`, because both forms are in use. A missing type is not a finding. Each unknown value is reported with its key path; when both keys hold valid but different values, that is one finding. Frontmatter strict YAML rejects is read with the lenient reader (`read_lenient` in `src/rigcheck/parse/frontmatter.py`), which reads one level of nesting for `metadata.type`.
