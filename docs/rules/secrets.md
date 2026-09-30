# Secrets and remote code

Two checks on what the rig's Markdown files hold rather than how they load: a credential written as a literal, and a skill or command that pipes a downloaded script into a shell. Both rules are in `src/rigcheck/rules/secrets.py`. Credential formats and the placeholder test are `find_secrets` and `classify` in `src/rigcheck/parse/secrets.py` (`classify` is the single-value form, for a JSON string); the pipeline reading uses `pipeline`, `runs_inline`, `segments`, `command_words` and `uncommented` from `src/rigcheck/parse/shell.py`, whose shell grammar is described in [`hooks.md`](hooks.md). A secret file with no Read deny is a settings rule, in [`settings-and-permissions.md`](settings-and-permissions.md).

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `secret-literal` | error | `sota:#19 (B)` |
| `skill-remote-exec` | warn | `official:SK28` |

Both rules run on every layer.

## `secret-literal`

- The rule reads instruction files (root and nested), rules, the memory index and topics, skills, commands and agents, on every layer and whatever their load class, because a committed secret is a leak whether or not Claude loads the file. The whole file is scanned, frontmatter and fenced blocks included. A skill's bundled files are not read.
- Only provider token formats count: Anthropic keys (`sk-ant-`), OpenAI keys (`sk-` or `sk-proj-`, not `sk-ant-`), GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`), Slack tokens (`xoxb-`, `xoxa-`, `xoxp-`, `xoxr-`, `xoxs-`), AWS access keys (`AKIA` and 16 upper-case characters), Google API keys (`AIza` and 35 characters), and JWTs (three `eyJ`-led dot-separated parts). Each format needs its minimum body length and no token character directly before or after it, so `task-sk-...` or a short `ghp_abc` does not match.
- A private key counts only when its `-----BEGIN ... PRIVATE KEY-----` header is followed, within the next two lines, by a line of 40 or more base64 characters: a header alone is documentation, not a key. A public key header never counts.
- Generic assignments such as `password=` or `token:` get no entropy check. The research reports that marketplace scanners flag up to 46.8% of skills, and only 0.52% stay suspicious once the repository context is read ([`../research/sota.md`](../research/sota.md) #19); a fixed provider format keeps the false-positive rate near zero.
- Placeholders are skipped: a literal ending `EXAMPLE` (AWS's documented `AKIAIOSFODNN7EXAMPLE`), a body starting with `...` or `…`, a body of one repeated character, a body holding a run of six or more `x` or `X`, and a body holding `your`, `example`, `changeme`, `placeholder`, `dummy`, `fake` or `redacted` in any case. Variable references such as `${ANTHROPIC_API_KEY}` never match a format.
- A finding sits on the line the literal starts on, and its message names only the token kind and its length in characters, never any character of the value, so the report itself cannot leak it. A hit keeps no part of the value either.

## `skill-remote-exec`

- The rule reads skills and commands on every layer. It scans their injected commands, fenced code lines and code spans, and their prose lines; frontmatter is not read, and neither are a skill's supporting files (`references/*.md` and other bundled files).
- A line is reported when it runs downloaded code in one of three shapes:
  - A fetch (`curl`, `wget`, `iwr`, `irm`, `Invoke-WebRequest`, `Invoke-RestMethod`) whose output reaches an interpreter (`sh`, `bash`, `zsh`, `dash`, `python`, `python3`, `node`, `pwsh`, `powershell`, `ruby`, `perl`, `iex`, `Invoke-Expression`) through `|` alone. A `&&`, `||` or `;` between them breaks the chain, so downloading to a file and then running it is silent.
  - `sh -c`, `bash -c` or `zsh -c` (or a short-flag group ending in `c`, such as `-lc`) whose command holds a `$(curl ...)`, `$(wget ...)` or backtick fetch.
  - `iex (irm ...)` or `Invoke-Expression (Invoke-WebRequest ...)`, with any of the four PowerShell fetch words.
- The interpreter must read its script from standard input. `iex` and `Invoke-Expression` always do. Any other interpreter does not when it has its own inline-code or module flag (`runs_inline`: `-c` or a `-lc`-style group for POSIX shells, `-c` and `-m` for Python, `-e`, `--eval`, `-p` and `--print` for Node, `-e` for Ruby, `-e` and `-E` for Perl, `-Command`, `-c`, `-EncodedCommand` and the like for PowerShell); otherwise a POSIX shell with `-s` does even when words follow, and any interpreter does when it names no script operand. Flags are read per interpreter, so `bash -e` still runs standard input while `bash -c`, `node -e` and `pwsh -Command` do not.
- A leading `sudo` is skipped with its flags and the values of its value-taking flags (`-u`, `-g`, `-C`, `-h`, `-p`, `-r`, `-t`, `-U`, `-D`), so `curl ... | sudo -u root bash` is read as `bash`.
- A Markdown table row (a prose line starting and ending with `|`) is not read as a pipeline, because its `|` separates cells; code spans inside the row are still read.
- `#` comments are cut from injected commands and fenced code lines before they are read, so a commented-out example is silent.
- Base64 blobs and instructions to send data to a URL, which SK28 also names, are not encoded: neither has a mechanical definition that separates it from ordinary content.
- A line is reported once. The message names the fetch word and the interpreter word, never the URL.
