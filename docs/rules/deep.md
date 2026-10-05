# Deep checks

`--deep` asks Claude, through headless `claude -p`, to judge what code cannot. The runner, the cache and the consent flow live in `src/rigcheck/deep.py`. Each deep check family (one fixed prompt and JSON schema) adds its judgements to `Rig.verdicts` before the rules run, so a deep rule stays a function of the `Rig` alone. No family ships yet, so `--deep` lists the files it would send and makes no call.

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `deep-error` | warn | `rigcheck:deep` |

## What is sent

- Only instruction, nested instruction, rule, skill, command and agent files on the repo and user layers, and only files Claude Code loads (a shadowed AGENTS.md is not sent). Settings, hooks, MCP config, `~/.claude.json`, memory and plugin files are never sent: they hold credentials and machine-local state, and plugins are third-party code.
- A file where `secret-literal` fires is not sent, even when `.rigcheck.toml` suppresses that finding: a suppression silences a report, it does not make a credential safe to send.
- If the secret scan itself fails, no file is sent (each is listed as `secret scan failed`): the check fails closed.
- An empty file is not sent: a call on it costs money and judges nothing.
- A file over 100,000 bytes (UTF-8, as sent) is not sent, so a stray dump cannot run up the bill.
- A file held back for several reasons shows the first of: holds a secret, empty, over the cap.
- A path that several artifacts share is sent once.

## Consent

- `--deep` first prints the listing to stderr: each file with its byte count (repo files relative to the repo root, user files as `~/...`), a `Not sent:` block with each held-back file and its reason, then the model and the call count. File contents are never printed. Stderr keeps `--format json` and `brief` output on stdout clean.
- With calls to make, it asks `Send <n> file(s) to claude (model haiku, <c> call(s))? [y/N]` on stderr. Only `y` or `yes` goes ahead; anything else prints `--deep cancelled; nothing was sent` and exits 2. `claude` is looked up before the prompt, so nobody approves a run that cannot happen. `--yes` skips the prompt but not the listing. When stdin is not a terminal and `--yes` is absent, it exits 2: a script must say yes explicitly.
- `--dry-run` prints the listing and exits 0 without running any rule or call, and does not need `claude` installed.
- `--yes` or `--dry-run` without `--deep`, or no `claude` on PATH when a call is due, is a usage error (exit 2).
- A run without `--deep` never builds a runner: the offline guarantee holds by construction, and a test passes a runner that raises.

## The call

- Each call runs `claude -p --output-format json --json-schema <schema> --tools "" --no-session-persistence --safe-mode --model haiku --max-budget-usd 0.50 --system-prompt <fixed>` with the prompt on stdin, one call per family and file, in sequence, with a 120 s timeout. `--safe-mode` works with an OAuth login, so no API key is needed; `--tools ""` gives the model no tools and `--no-session-persistence` leaves no session behind. Defaults are model `haiku` and $0.50 per call (owner ruling).
- `claude` must be the native executable. A `.cmd` or `.bat` shim (an npm install on Windows) is refused: it runs through `cmd.exe`, which can split the JSON schema argument, and a timeout would kill only the shell, leaving the call running.
- The reply is one JSON object. rigcheck reads its `structured_output` and requires `is_error: false` and `subtype: "success"`.

## Cache

- Answers are cached under `$XDG_CACHE_HOME/rigcheck`, else `~/.cache/rigcheck`, on every platform, one `<sha256>.json` per answer, written atomically. The key hashes the family id, its prompt version, the model, the schema, the system prompt and the file text, so editing a prompt or a schema never serves a stale answer.
- Only an answer that parses is cached, so a failed call is retried on the next run. An unreadable cache entry counts as a miss. A cache write that fails prints one stderr line and the run goes on: the answer was paid for and is still used. Each write goes through a temp file named for its process, so two runs never collide.

## `deep-error`

- A call that raises, times out, or returns output that is not the expected envelope, or whose answer the family cannot parse, becomes one `deep-error` finding at that file, never a crash. Its message names the family and a fixed reason (`output is not JSON`, `subtype is not success`, ...), never model output or file text.
- `deep-error` is engine-emitted like `internal-error`: registered as a no-op in the `core` pack for its metadata, it cannot be suppressed and `--only` always keeps it. It is warn, so the default `--fail-on error` still exits 0 when a call fails.
- `--only` filters findings only; the listing covers every family.

## Deep rules and the `deep` pack

- A deep rule is a rule in the `deep` pack. Like every rule it is a function of the `Rig` alone: it turns one family's verdicts in `Rig.verdicts` into findings with `rules/deep_common.py` `findings_from(rig, family_id, rule_id)`. The artifact a finding is reported on comes from `deep_artifacts`, the same selection that decides which files are sent, so a finding carries the layer and load class of the file that was judged. A verdict whose path is not among those files is a bug, so `findings_from` raises and the engine reports `internal-error`.
- The `deep` pack is last in `PACKS` and not in the default packs. `--deep` always adds it, whatever `--packs` says: `--packs core --deep` runs core and deep, since the answers are paid for by then. Without `--deep` a deep rule could only run on no verdicts, so `--packs deep` or `--only <deep rule>` without `--deep` is a usage error rather than a silent clean run.
- A `.rigcheck.toml` suppression of a deep rule still hides its matching findings, but it is never reported as `suppression-unused`: a deep rule may judge nothing on a run (no call made, every file held back, every call failed), and a warning then would be false.
- Each deep rule's severity is set with the rule, not by the pack.
- A deep rule's fixtures carry canned verdicts: each of its variant folders holds `verdicts.json`, a list of `{"family", "path", "line", "message"}`. A path is relative to the variant root, or starts with `~/` for a file in the fixture's home. The catalog test loads the file straight into `Rig.verdicts` and runs with `--deep`, so no runner, cache or `claude` is involved and the rule is tested on its own. A verdict on a file `--deep` would not send fails the test, and the file is never copied into the checked rig. Each family's prompt and parsing are tested separately in `tests/test_deep.py`.
