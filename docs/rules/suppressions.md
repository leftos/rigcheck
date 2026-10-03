# Suppressions

A repo can silence a finding it has judged not to apply by adding an entry to `.rigcheck.toml` at the repo root. Discovery reads the file with `load_suppressions` in `src/rigcheck/config.py` and stores the entries in `Rig.suppressions`. The rule that checks the entries is in `src/rigcheck/rules/suppressions.py`. Terms such as layer, load class and finding are in the glossary in [`../README.md`](../README.md).

```toml
[[suppress]]
rule = "skill-description-missing"
path = "plugins/legacy/**"
reason = "vendored; fixed upstream"
```

## Rules

| Rule id | Severity | Evidence |
|---|---|---|
| `suppression-no-reason` | warn | `rigcheck:suppressions` |

## Design

- **Where the file is read.** rigcheck reads `.rigcheck.toml` only from the repo root: `git rev-parse --show-toplevel`, or the target outside git. There is no user-level config, so checking the home folder reads no `.rigcheck.toml`.
- **Not an artifact.** `.rigcheck.toml` is rigcheck's own config, not part of the rig. So it has no `Kind`, it is not in the JSON `artifacts` list, and it does not count toward the budget. A finding about it carries the repo layer and the `not-loaded` load class.
- **Entry keys.**
  - `rule` is one exact rule id.
  - `path` is optional: a glob relative to the repo root. An entry with no `path` covers the whole repo.
  - `reason` says why the finding does not apply.
- **Bad content never stops a run.** Each of these becomes a `discovery-error` problem, and the bad entry is skipped:
  - a file that cannot be read, is not UTF-8, or is not valid TOML (a leading BOM is accepted);
  - a top-level key other than `suppress`;
  - a `suppress` value that is not an array of tables;
  - an entry whose `rule` is missing or blank;
  - an entry with a `path` or `reason` that is not a string;
  - an unknown key in an entry.

  An entry with several faults gets one problem per fault. Problem messages name keys, with control characters escaped, but never values from the file.
- **`suppression-no-reason`.** It fires on an entry whose `reason` is missing, empty or whitespace, and the entry is kept. The reason is required so that a later reader can tell when the suppression stops being true.
- **Line numbers.** TOML gives no line numbers, so an entry's line is the line of its `[[suppress]]` header, counted in order. Spaces inside the brackets and a quoted key are accepted.
  - With an inline array (`suppress = [{…}]`), every entry gets the `suppress` key's line.
  - A `[[suppress]]` line inside a multi-line string is counted as a header too, which shifts the lines of the entries after it.
- **The engine does not apply the entries.** A finding an entry matches is still reported.
