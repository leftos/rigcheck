# Suppressions

A repo can silence a finding it has judged not to apply by adding an entry to `.rigcheck.toml` at the repo root. Discovery reads the file with `load_suppressions` in `src/rigcheck/config.py` and stores the entries in `Rig.suppressions`. After the rules have run, `apply_suppressions` in `src/rigcheck/engine.py` applies the entries. The two suppression rules are in `src/rigcheck/rules/suppressions.py`. Terms such as layer, load class and finding are in the glossary in [`../README.md`](../README.md).

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
| `suppression-unused` | info | `rigcheck:suppressions` |

`suppression-unused` is registered in `src/rigcheck/rules/suppressions.py` but never fires from its own check. `engine.apply_suppressions` emits it, because only the engine sees every rule's findings.

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
- **Applying the entries.** The CLI runs every rule, then `engine.apply_suppressions` removes each finding an entry matches, and only then applies `--only` and computes the exit status. So a suppressed finding never sets the exit status, whatever `--fail-on` says. An entry matches a finding when all of these hold:
  - its `rule` is the finding's rule id;
  - the rule is not `internal-error`, `discovery-error`, `suppression-no-reason` or `suppression-unused`, which are never suppressed;
  - for a finding with a file, the file is in the repo layer and inside the repo root, and the entry has no `path` or its glob matches the file's repo-relative path;
  - for a finding with no file (a setup finding), the entry has no `path`.
- **Never hidden.** A committed config never hides machine-local findings. Findings in the user, memory and plugin layers are never matched. Neither is a repo-layer file outside the repo root, such as a parent-folder `CLAUDE.md` or a file a repo `CLAUDE.md` imports from the home folder.
- **`path` is a file glob.** It uses the same picomatch-style matching as rule `paths`: `docs/**` matches the files under `docs/`, while `docs` matches only a file named `docs`.
- **First match takes the finding.** The first matching entry in file order takes it. An entry counts as used when it matches at least one finding, so two entries covering the same finding are both used.
- **`suppression-unused`** fires once for each unused entry, at the entry's line. When the `rule` is not a rigcheck rule id, the message says so, since a typo is the usual cause.
- **Reporting suppressed findings.**
  - The JSON report lists them under a top-level `suppressed` key, after `findings`: each one's finding fields plus its entry's `reason`, or null. It also counts them in `summary.suppressed`.
  - The text report adds ` · N suppressed` to its last line and does not list them.
  - `--only` filters the suppressed list the same way as the findings, so it also drops `suppression-unused` unless that id is named.
