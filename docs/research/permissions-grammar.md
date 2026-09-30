# Claude Code permission-rule grammar

Researched 2026-09-30.

Primary sources only. Every claim is a verbatim quote with its page; lines marked **Inferred** are rigcheck's reading, not a source statement. The docs pages were fetched live as `.md` on 2026-09-30; the changelog's newest entry at fetch time was 2.1.285, so doc text may describe behaviour newer than CLI 2.1.283.

## Sources

- [P] https://code.claude.com/docs/en/permissions — "Configure permissions"
- [S] https://code.claude.com/docs/en/settings — "Settings files and precedence"
- [R] https://code.claude.com/docs/en/settings-reference — `permissions.allow` / `ask` / `deny`
- [E] https://code.claude.com/docs/en/errors — "Malformed Tool(content) rule", "Is not matched by file permission checks", "Has a wildcard before the rest of the command"
- [T] https://code.claude.com/docs/en/tools-reference — "Configure tools with permission rules and hooks"
- [K] https://code.claude.com/docs/en/skills — "Restrict Claude's skill access"
- [A] https://code.claude.com/docs/en/sub-agents — "Restrict which subagents can be spawned"
- [C] https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md — version cited per entry

## 1. Rule syntax

- [P] "Permission rules follow the format `Tool` or `Tool(specifier)`. Parentheses inside the specifier are literal, so a command or path that contains them needs no escaping."
- [T] "All of these accept the same rule format, `ToolName(specifier)`" — settings `allow`/`deny`, `/permissions`, `--allowedTools`/`--disallowedTools`, SDK options, a skill's `allowed-tools`, a hook's `if`.
- [T] specifier families: "`Bash(npm run *)` | Bash, Monitor"; "`PowerShell(Get-ChildItem *)` | PowerShell"; "`Read(~/secrets/**)` | Read, Grep, Glob, LSP"; "`Edit(/src/**)` | Edit, Write, NotebookEdit"; "`Skill(deploy *)` | Skill"; "`Agent(Explore)` | Agent"; "`WebFetch(domain:example.com)` | WebFetch"; "`WebSearch` | WebSearch | No specifier; allow or deny the tool as a whole".
- [T] "Tools not listed here, such as `ExitPlanMode` or `ShareOnboardingGuide`, accept only the bare tool name with no specifier."

**Bare tool / `*`.** [P] "`Bash(*)` is equivalent to `Bash` and matches all Bash commands. As a deny rule, both forms remove the tool from Claude's context." (Since [C] 2.1.20: "Changed permission rules like `Bash(*)` to be accepted and treated as equivalent to `Bash`".) Tool-name globs: [P] "Deny and ask rules also accept glob patterns in the tool-name position. The pattern must match the full tool name: `"*"` matches every tool, and `"mcp__*"` matches every MCP tool across all servers." [P] "An unanchored allow glob such as `"*"`, `"B*"`, or `"mcp__*"` is skipped with a warning and doesn't auto-approve anything."

**Unknown names.** [P] "A deny or ask rule whose tool name matches no known tool produces a startup warning to catch typos. Tool names containing `_` or `*` are exempt from the check". [P] "Permission rules and hook matchers don't match the label, so a rule written as `Stop Task` doesn't match."

**Parameter form (deny/ask only).** [P] "Deny and ask rules can match a top-level input parameter on any built-in tool with `Tool(param:value)`." Examples `Agent(model:opus)`, `Agent(isolation:worktree)`, `Bash(run_in_background:true)`. [P] "allow rules continue to use each tool's own specifier syntax." [P] "You can't match a tool's primary content field this way ... A rule like `Bash(command:rm *)` ... Claude Code ignores it and emits a startup warning."

**MCP.** [P] "`mcp__puppeteer` matches any tool provided by the `puppeteer` server"; "`mcp__puppeteer__*` uses wildcard syntax and also matches all tools from the `puppeteer` server"; "`mcp__puppeteer__puppeteer_navigate` matches the `puppeteer_navigate` tool". [P] "Allow rules accept tool-name globs only after a literal `mcp__<server>__` prefix. The server segment must be glob-free". [R] "In an MCP rule, `*` can appear only in the tool name after the `mcp__<server>__` prefix, such as `mcp__github__get_*`; it can't appear in the server name." [P] "When Claude Code loads a settings file, it skips any `mcp__` rule that has parentheses."

| Example | Status |
| :- | :- |
| `mcp__github`, `mcp__github__*`, `mcp__github__get_*` | valid in any list |
| `mcp__*`, `*` in `deny`/`ask` | valid |
| `mcp__*`, `*`, `B*` in `allow` | skipped with a warning |
| `mcp__gh*__x` in `allow` | invalid: server segment has a glob |
| `mcp__github__x(a:b)` in a settings file | skipped (parentheses on `mcp__`) |

**Agent / Task.** [P] "`Agent(Explore)` matches the Explore subagent ... `Agent(my-custom-agent)` matches a custom subagent named `my-custom-agent`". [A] "In version 2.1.63, the Task tool was renamed to Agent. Existing `Task(...)` references in settings and agent definitions still work as aliases."

**WebFetch.** [P] "WebFetch rules use a `domain:` prefix and match against the hostname ... Matching is case-insensitive, supports `*` wildcards". "`WebFetch(domain:*.example.com)` matches any subdomain at any depth ... but not `example.com` itself". "`WebFetch(domain:example.*)` matches `example.org` ... but not `example.evil.com`". "`WebFetch(domain:*)` matches every domain. It isn't the same as a bare `WebFetch` rule" (bare deny removes the tool; `domain:*` deny keeps it, refuses each fetch, and also feeds the sandbox list).

**Skill.** [K] "Permission syntax: `Skill(name)` for exact match, `Skill(name *)` for prefix match with any arguments." Bare `Skill` in deny disables all skills. [K] "`Skill(anthropic *)` doesn't cover `anthropic-skills:pdf`" in allow; "`Skill(anthropic-skills:pdf)` approves the synced `pdf` skill".

**Cd.** [P] "`Cd` is not a model-invocable tool"; `Cd(~/code/*)`, `Cd(~/code/**)` use the `//`, `~/`, `/` anchors but "matching is anchored to the whole directory path rather than gitignore-style".

**Empty `()`.** No source addresses `Tool()`. **Inferred:** it has the `Tool(content)` shape with empty content, so it is not reported as malformed; what it matches is undocumented. Treat as a finding-worthy oddity, not as equal to bare `Tool`.

**Malformed rules.** [E] "A permission rule ... doesn't have the shape `Tool` or `Tool(content)`, for example because text follows the closing parenthesis or one of the parentheses is missing. Claude Code skips the rule and lists it in the invalid-settings dialog". Message: "Invalid permission rule "Bash(ls) x" was skipped: Malformed Tool(content) rule. Rules take the form Tool or Tool(content) and must end at the closing ")"; parentheses inside the content are literal". [E] "Before v2.1.260, Claude Code reported a rule with unmatched parentheses as `Mismatched parentheses`." [S] "**Settings Warning**: only individual entries fail, such as a malformed permission rule ... Claude Code skips those values and keeps the rest of the file in effect." [C] 2.1.260: "Changed permission rules with text after the closing parenthesis (e.g. `Bash(ls) x`), which never matched anything, to be reported as invalid settings instead of being silently ignored".

| Rule | Status |
| :- | :- |
| `Edit(./Finance (2024)/**)` | valid; inner parens literal |
| `Bash(ls) x` | skipped: text after `)` |
| `Bash(ls` | skipped: missing `)` (**Inferred** from "one of the parentheses is missing") |
| `Bash ls)` | **Inferred** skipped: no `(` yet ends in `)`; not quoted |

## 2. Bash specifiers

- Exact: [P] "A rule with no `*` matches one exact command." `Bash(npm run build)` matches `npm run build`, not `npm run build --watch`.
- Trailing ` *`: [P] "A `*` at the end, with a space before it, also matches the bare command. `Bash(ls *)` matches `ls` ... That holds only when the trailing `*` is the rule's only wildcard: `Bash(* --help *)` matches `npm --help x` but not `npm --help`."
- `*` with no space: [P] "`Bash(ls *)` requires a space after `ls`, so `lsof` doesn't match. `Bash(ls*)` has no space, so it matches `lsof` too."
- Legacy `:*` at end: [P] "The `:*` suffix is an equivalent way to write a trailing wildcard, so `Bash(ls:*)` matches the same commands as `Bash(ls *)`."
- `:*` mid-pattern: [P] "The `:*` form is only recognized at the end of a pattern. In a pattern like `Bash(git:* push)`, the colon is treated as a literal character and won't match git commands." See Conflicts.
- `*` in the middle: [P] "A `*` in a Bash rule matches any text, including spaces". "`Bash(git log * main)` | `git log --oneline main` ... | `git log main`, `git push origin main`"; "`Bash(* --version)` | `node --version`". [E] allow rules with a `*` before the subcommand (`Bash(git * main)`) get a startup warning; "Claude Code keeps the rule and changes nothing about how it matches"; no warning for deny/ask, for `Bash(git *)`, or for `:*` prefix rules.
- Compound commands: [P] "a rule like `Bash(safe-cmd *)` won't give it permission to run the command `safe-cmd && other-cmd`. The recognized command separators are `&&`, `||`, `;`, `|`, `|&`, `&`, and newlines. A rule must match each subcommand independently." [P] "Deny and ask rules apply when any subcommand matches them, including a command nested inside a subshell, a command substitution, or a control-flow body". [P] "When `&&` or `||` has nothing after it, such as in `npm test &&`, Claude Code treats the command as unparseable".
- Wrappers: [P] "Claude Code strips ... `timeout`, `time`, `nice`, `nohup`, and `stdbuf`, plus the shell builtins `command` and `builtin`, and zsh's `noglob`"; bare `xargs` too. [P] "A deny or ask rule matches past any leading assignment". Not a boundary: [P] "`Bash(rm *)` | `rm -rf build/` | `/bin/rm -rf build/`, `bash -c 'rm -rf build/'`".
- `Bash(*)` vs `Bash`: equal (section 1). [P] also: the sandbox auto-allow substitutes for "a bare `Bash` ask rule, or the equivalent `Bash(*)` form".
- PowerShell: [P] "PowerShell permission rules use the same shape as Bash rules ... the `:*` suffix is equivalent to a trailing ` *`, and a bare `PowerShell` or `PowerShell(*)` matches every command." "Matching is case-insensitive."

## 3. Path specifiers (Read / Edit)

File-rule tools: [P] "Claude Code checks file permissions against `Edit(path)` and `Read(path)` rules only." [P] "`Edit` rules apply to all built-in tools that edit files. Claude makes a best-effort attempt to apply `Read` rules to all built-in tools that read files like Grep and Glob". [T] "An `Edit(...)` allow rule also grants read access to the same path".

Anchors, [P] table: "`//path` | Absolute path from filesystem root"; "`~/path` | Path from home directory"; "`/path` | Path relative to the settings source"; "`path` or `./path` | Path relative to current directory".

[P] `/path` resolves by source: "Project settings at `.claude/settings.json` | `<primary working directory>/path`"; "Local settings at `.claude/settings.local.json` | `<primary working directory>/path`"; "User settings at `~/.claude/settings.json` | `~/.claude/path`"; "A file passed with `--settings <file>` | `<directory of file>/path`"; "CLI flags or session rules | `<primary working directory>/path`". [P] "A pattern like `/Users/alice/file` isn't an absolute path." [P] "A deny rule such as `Read(/secrets/**)` in user settings blocks `~/.claude/secrets/**`, not a `secrets` directory in your project."

| Rule | Meaning |
| :- | :- |
| `Edit(/docs/**)` in project settings | `<pwd>/docs/**`, "not `/docs/` or `<primary working directory>/.claude/docs/`" [P] |
| `Read(~/.zshrc)` | home `.zshrc` [P] |
| `Edit(//tmp/scratch.txt)` | absolute `/tmp/scratch.txt` [P] |
| `Read(//c/**/.env)` on Windows | `.env` anywhere on C: [P] |
| `Read(/Users/alice/x)` in user settings | `~/.claude/Users/alice/x` (non-example of absolute) |

Globs: [P] "Read and Edit rules both use gitignore pattern syntax"; "`*` matches within a single path segment ... while `**` matches across directories." [P] "Bare filenames follow gitignore semantics and match at any depth, so `Read(.env)` and `Read(**/.env)` are equivalent". Single-segment depth differs by list: [P] "**Allow rules**: `Edit(src/**)` matches only `<cwd>/src` and the files under it." "**Deny and ask rules**: `Read(secrets/**)` matches a directory named `secrets` at any depth under the current directory". [P] "`Edit(/src/**)` and `Edit(src/components/**)` match only at their anchored location". Negation: [P] "A deny or ask pattern that starts with `!` is a gitignore negation ... A `!` rule listed first carves nothing out." and "The carve-out reaches only rules from the same source." Unusable patterns: [P] "A deny or ask rule whose path isn't usable as a gitignore pattern still guards that exact path. An allow rule with an unusable pattern doesn't approve anything."

Trailing `/`: no source addresses a trailing `/` in a rule. **Inferred:** gitignore semantics make `Read(build/)` match only a directory named `build`; unverified for Claude Code.

Case sensitivity: the permissions page says nothing for Read/Edit paths (it says "case-insensitive" only for PowerShell and WebFetch). [P] "On Windows, paths are normalized to POSIX form before matching. `C:\Users\alice` becomes `/c/Users/alice`". [C] 2.1.162: "Fixed Windows permission rules never matching when spelled with backslashes (`~\`, `\\server\share`) or case-variant paths". [C] 2.1.111: "paths differing only by drive-letter case are recognized as the same path". **Inferred:** Windows path matching is case-insensitive; macOS is undocumented.

Edit vs Write/MultiEdit/NotebookEdit: [T] "`Edit(/src/**)` | Edit, Write, NotebookEdit". [E] "Replace `Write(path)`, `NotebookEdit(path)`, and legacy `MultiEdit(path)` rules with `Edit(path)`. `Edit` rules cover all file-editing tools." Read deny spills onto edits: [P] "A `Read` deny rule also blocks the Edit and Write tools on the same path ... NotebookEdit isn't covered, so add an `Edit` deny rule". Requires v2.1.208 (edits) / v2.1.228 (writes).

Read deny vs Bash `cat`: [P] "Read and Edit deny rules apply to Claude's built-in file tools, to file commands Claude Code recognizes in Bash, such as `cat`, `head`, `tail`, `sed`, and `tee`, and to the targets of Bash redirections ... They don't apply to a command that reads files without naming them, such as `grep -r pattern .` ... or to arbitrary subprocesses". [C] 2.1.257: "Fixed Bash `Read()`/`Edit()` deny rules not applying to `< file` redirects and reader commands like `tac` and `egrep`". [C] 2.1.259 widened this to option values and `cd DIR && cat FILE` compounds; [C] 2.1.260: "Reverted the 2.1.259 change applying `Read()` deny rules to Bash arguments". **Inferred:** reader-command coverage (`cat FILE`) predates and survives the revert, matching the live page; it is not a security boundary.

## 4. Evaluation and merging

- Order: [P] "Rules are evaluated in order: deny, then ask, then allow. The first match in that order determines the outcome, and rule specificity doesn't change the order." [P] "An allow rule can't carve an exception out of a deny rule. The same precedence applies between ask and allow".
- Bare-name deny removes the tool; a scoped deny blocks matching calls [P].
- Levels: [S] "1. **Managed settings** ... 2. **Command line arguments** ... 3. **Project local settings** ... 4. **Shared project settings** ... 5. **User settings**".
- Lists concatenate: [S] "When you set the same list key, such as `permissions.allow`, in more than one file, Claude Code combines the lists instead of picking one, so each file can add entries without removing another file's."
- Cross-scope: [P] "If a tool is denied at any level, no other level can allow it. For example, a managed settings deny can't be overridden by `--allowedTools`". [P] "if user settings allow a permission and project settings deny it, the deny rule blocks it. The reverse is also true: a user-level deny blocks a project-level allow, because deny rules from any scope are evaluated before allow rules." [S] "an `allow` rule there [local] doesn't outrank an `ask` rule from a project or managed file".
- Managed lock: [P] "`allowManagedPermissionRulesOnly` makes managed settings the only settings source of permission rules."
- Trust gate: [P] "`permissions.allow` rules and `permissions.additionalDirectories` entries in a project's `.claude/settings.json` ... apply ... only after you accept the workspace trust dialog ... `deny` and `ask` rules aren't affected". Local file is exempt unless tracked in git or `.claude` is a symlink [P].
- Hooks: [P] "Claude Code evaluates deny and ask rules regardless of what a PreToolUse hook returns".

## 5. Tools whose path rules are ignored

- [P] "If you write a path rule for `Write`, `NotebookEdit`, `Glob`, or the legacy `MultiEdit` tool instead, Claude Code accepts the rule but never consults it, and warns at startup, except for a `Glob` rule passed in `--allowedTools`. Use `Edit(docs/**)` in place of `Write(docs/**)` ... and `Read(docs/**)` in place of `Glob(docs/**)`. Claude Code doesn't warn about a tool-name rule with no path, such as a deny rule for `Write`; it matches that rule at the tool level everywhere. Requires Claude Code v2.1.210 or later."
- [E] warning text: "Permission deny rule (.claude/settings.json): Write(docs/**) is not matched by file permission checks — only Edit(path) rules are."
- Non-examples (valid, consulted): bare `Write`, bare `Glob`, `Edit(docs/**)`, `Read(docs/**)`. Grep is not in the ignored list; **Inferred:** a `Grep(path)` rule is also unconsulted, since only `Edit`/`Read` path rules are checked, but no source says it warns.

## Conflicts and gaps

1. Mid-pattern `:*`: [P] says the colon is literal and `Bash(git:* push)` "won't match git commands"; [C] 2.1.282 says "Fixed Bash permission rules with a mid-pattern `:*` being skipped in settings files while `--allowedTools` honored them; they now work from every source, with a startup warning on how they match". The changelog implies they were skipped (not literal) before 2.1.282 and now load; the matching semantics after the fix are not stated. For 2.1.283, **Inferred:** the rule loads, warns, and matches with `:` literal.
2. Read deny vs Bash arguments: the 2.1.260 revert [C] reads as removing Bash-argument coverage, while the live page [P] still lists `cat`/`head`; the revert targets the 2.1.259 widening, not the 2.1.257 reader-command check (section 3).
3. Undocumented: `Tool()` with empty content, trailing `/` in path rules, macOS path case sensitivity, `Grep(path)` rules.
