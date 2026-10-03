# Skills and commands

Skills (`skills/<name>/SKILL.md` and the files bundled in its folder) and legacy commands (`commands/*.md`) share one frontmatter format, so most rules here read both. Frontmatter, name, option and bundled-file rules are in `src/rigcheck/rules/skills.py`; rules on the body (injected shell commands, `$N` in prose, unused arguments) are in `src/rigcheck/rules/skill_body.py`, using `find_injections` and `prose_segments` from `src/rigcheck/parse/markdown.py` and the shell helpers in `src/rigcheck/parse/shell.py`; the command-only rule is in `src/rigcheck/rules/commands.py`. A forked skill's `agent` and the agents a skill's prose dispatches are checked with the agent rules, in [`agents.md`](agents.md). How frontmatter is read is in [`frontmatter-and-rules-dir.md`](frontmatter-and-rules-dir.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `skill-frontmatter-misplaced` | error | `official:SK1` |
| `skill-frontmatter-invalid` | error | `official:SK1` |
| `skill-key-unknown` | warn | `official:SK2` |
| `skill-description-missing` | warn | `official:SK4` |
| `skill-description-truncated` | warn | `official:SK4` |
| `skill-name-mismatch` | warn | `official:SK8` |
| `skill-name-reserved` | warn | `official:SK8` |
| `skill-link-broken` | error | `official:SK11` |
| `skill-link-outside` | warn | `official:SK11` |
| `skill-link-too-deep` | warn | `official:SK11` |
| `skill-file-unreferenced` | info | `official:SK11` |
| `skill-unreachable` | warn | `official:SK19` |
| `skill-fork-option-ignored` | warn | `official:SK20` |
| `skill-allowed-tools-broad` | warn | `official:SK21` |
| `skill-injection-literal` | warn | `official:SK22` |
| `skill-injection-not-allowed` | warn | `official:SK22` |
| `skill-injection-relative-path` | warn | `official:SK23` |
| `skill-dollar-digit` | warn | `official:SK24` |
| `skill-argument-unused` | warn | `official:SK24` |
| `command-key-ignored` | warn | `official:SK30` |

## Layers

Every rule here runs on the repo, user and plugin layers, with two exceptions: `skill-name-reserved` skips the plugin layer (repo and user only), and `skill-allowed-tools-broad` runs on the repo layer only.

## Frontmatter and options

- `skill-frontmatter-misplaced`, `skill-frontmatter-invalid`, `skill-key-unknown`, `skill-description-missing`, `skill-description-truncated`, `skill-unreachable`, `skill-fork-option-ignored` and `skill-allowed-tools-broad` read skills and commands alike.
- `skill-key-unknown` leaves a command's `name` and `paths` to `command-key-ignored`, which reports them because Claude Code supports those keys only in skills.
- `skill-description-missing` fires for a file with no description, including one with no frontmatter at all; a file whose frontmatter Claude Code rejects is left to `skill-frontmatter-invalid`.
- `skill-description-truncated` fires when `description` and `when_to_use`, joined by a space, pass 1,536 characters, the length the skill listing keeps.
- `skill-unreachable` fires when `user-invocable` reads false and `disable-model-invocation` reads true.
- `skill-fork-option-ignored` reports `agent` (a non-empty value) and `background: true` on a skill whose `context` is not `fork`.
- `skill-allowed-tools-broad` counts as broad: `Bash`, `Write` or `Edit` bare, or with an everything-specifier (`(*)`, `(:*)`, `()`, or the whole-tree globs `(**)`, `(/**)`, `(./**)`), plus a lone `*`. It reports each broad entry, because workspace trust does not gate this field.

## Names

- `skill-name-mismatch` reports a skill whose `name` differs from its folder name, because Claude Code then answers to both. A plugin skill may also write `<plugin>:<folder>`.
- `skill-name-reserved` reports the folder name and the `name` when `claude` or `anthropic` is a whole hyphen-separated part of it, in any case (`my-claude-helper` is reported, `claudette` is not).

## Links and bundled files

These four rules read skills only, on every layer.

- Markdown links and images feed the link rules. A target resolves beside the linking file, then at the skill folder; `${CLAUDE_SKILL_DIR}/`, `$CLAUDE_SKILL_DIR/` and `{baseDir}/` (as written or URL-encoded) resolve at the skill folder, and `~/` at home. A token starting with `/` or `\` is never checked, so no UNC lookup reaches the network.
- Links are checked in SKILL.md and in the bundled `.md` files it links.
- A missing target is only `skill-link-broken`; `skill-link-outside` reports an existing target outside the skill folder, because a copied or installed skill carries only its own folder.
- `skill-link-too-deep` fires when a bundled `.md` file that SKILL.md links links another bundled `.md` file that SKILL.md does not.
- `skill-file-unreferenced` reports a bundled file that nothing names. A file counts as named when a link, image, code span, code block line, `@` import or a YAML file in the skill's top-level `agents/` folder names it or a folder above it, matched at a path boundary. In code text a `…skills/<name>/` prefix counts as the skill folder, and so do the skill-folder placeholders and an angle-bracket name that contains `skill` and ends in `dir`, `directory`, `path`, `folder` or `root`, in any case (`<skill-dir>/`, `<SKILL_ROOT>/`); `<root>/`, `<skill>/` and `<repo-root>/` do not count. The names come from SKILL.md, the bundled `.md` files it links, and the `.md` files it names in a code span, which count as one level deep for this.
- The walk of bundled files skips dotfiles and dot-folders, `SKIP_DIRS`, `__pycache__`, `*.pyc`, virtual environments (a folder holding `pyvenv.cfg`), links and junctions, nested skills (a folder holding its own SKILL.md), the top-level `agents/` folder, top-level files whose names start `LICENSE`, `NOTICE`, `README`, `UPSTREAM` or `CHANGELOG`, and, on the repo layer, files git ignores.

## Injected commands, `$N` and arguments

These rules read skills and commands on every layer, and only the file itself (not bundled files); frontmatter is excluded.

- An inline injection is `!` right before a code span, outside a link's text. It is recognised when the raw `!` is at a line start or after whitespace; after any other character `skill-injection-literal` reports it, because Claude Code leaves it as text. A backslash-escaped `!`, or an entity such as `&#33;`, is no injection. Only a backtick fence opened with ```` ```! ```` injects a block.
- `skill-injection-relative-path` checks non-literal injections line by line, after cutting a shell `#` comment. A relative path is a word starting `./` or `../`, a command word (after leading `NAME=` assignments) holding `/` or `\`, an assignment value starting `./` or `../`, or, in a skill, a word holding `/` or a file extension that names an existing file or folder in the skill folder. Words starting `$`, `~`, `/`, `%` or `\\`, a drive letter, or holding `://` are never flagged, because they resolve the same way from any working directory.
- `skill-dollar-digit` reports `$` followed by digits in prose only: code spans, code blocks, HTML, link destinations and titles are excluded. Exactly one backslash before the `$` escapes it; none, or two or more, leave it to expand.
- `skill-argument-unused` reports a name declared in `arguments` (a space-separated string or a list of strings) that the body never uses as `$name`; a use anywhere in the body counts, code included, unless one backslash escapes it.
- The docs do not say whether Claude Code substitutes inside code spans and fences; these rules assume it does not.
- `skill-injection-not-allowed` reports a non-literal injection with a subcommand that no `Bash` rule covers, because outside auto mode a permission check that is not "allow" aborts the invocation. It reads only a skill or command that has an `allowed-tools` key: without one, the command's permission comes from settings or auto mode, which the author chose not to pin. The covering rules are the `Bash` entries of `allowed-tools` (both the list and the comma-string form) plus the `Bash` allow rules of the repo and user settings files, which the same permission check reads. A bare `Bash` or `Bash(*)` covers every command, `Bash()` covers none, and other tools (`PowerShell(...)` included) cover none. A component whose `shell` is set to anything but `bash` is skipped; a blank `shell` counts as bash.
- Each subcommand must be covered on its own, as Claude Code matches them: lines are split on `&&`, `||`, `;`, `|`, `|&`, a background `&` and newlines, outside quotes, after cutting a `#` comment; the `&` of `>&`, `<&` and `&>` is a redirection, not a separator. Coverage is `bash_covers` against the whole subcommand.
- An injection this lexical pass cannot read is skipped whole rather than guessed at: one holding `$(`, a backtick, `<<`, `>|`, a backslash before `&`, `|`, `;` or a quote, a line ending in `\`, `&&` or `||`, or a subcommand opening with `(`, `{`, `!` or a compound-command keyword (`if`, `for`, `while`, `case`, `function` and their continuations).
- A subcommand is skipped unless covered as written when it starts with an assignment (`FOO=1 cmd`) or a wrapper Claude Code strips (`timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob`, `xargs`), or holds a `$` variable or placeholder (`$ARGUMENTS`, `$1`, `${CLAUDE_SKILL_DIR}`, `$HOME`): the docs say only deny and ask rules match past an assignment, wrapper arguments vary, and placeholders are substituted before the check sees the command.
- One finding per injection, at the first uncovered subcommand's line; the message names only that subcommand's program word, since the rest of a command may carry a credential.
- SK22's other clause, injected commands likely to exit non-zero, is not checked. SK24's deterministic parts ship as `skill-dollar-digit` and `skill-argument-unused`.
