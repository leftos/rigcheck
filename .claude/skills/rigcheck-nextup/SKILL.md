---
name: rigcheck-nextup
description: Profile for the user-level `nextup` skill in the rigcheck repo — loaded by `nextup` at its step 0 for this project's plan convention, agents, gates, docs map and landing path. Not a loop of its own; invoke `/nextup`.
---

# rigcheck profile for `nextup`

The generic loop is the user-level `nextup` skill; this file supplies only what is rigcheck-specific.

## Plan and tracker

- Index: `docs/plans/MAIN.md`, section `## Current focus`, then `## Next up`, then `## Backlog`. Each milestone line points into `docs/plans/v1.md`: its rule catalog names every rule by the research id it cites (`CM2`, `SK4`, `HK3`, `sota:#2`), and `docs/research/official.md` / `sota.md` hold each id's quote, check type and suggested severity. Read the id's entry there before writing a brief; never cite a rule from memory.
- A milestone line that is too big for one brief (about 100 implementer calls: up to four steps or six files) is a *design* item: split it into lettered sub-items (`M3a`, `M3b`) in MAIN.md, grouped by rule module, and land the split before dispatching.
- Siblings: none.
- Pre-loop hooks: none.
- Finished-item convention: **tick the line** (`- [x]`), never delete it. When every milestone of `v1.md` is ticked, `git mv` it to `docs/plans/archive/` in the landing commit.
- Tracker: `gh issue list --repo leftos/rigcheck --state open --json number,title`. No triage skill; place issues by the step-0 rule.
- Hotspots (two items touching one wait on each other): `src/rigcheck/model.py` (the `Kind`/`LoadClass` enums), `src/rigcheck/discover.py`, `src/rigcheck/rules/__init__.py` (the module import list), `tests/test_rule_catalog.py`.

## Rulings every brief carries

- **Defect and cost linter, not a scorer** (research, user-approved plan): no overall score; no rule from `sota.md` §6 "Folklore: do not encode". A doc-backed style rule goes to the `advice` pack at `info` and cites both the doc and the null result.
- **Every rule** has a slug id, a pack, a severity, evidence strings (`official:<id>` / `sota:#<n> (<grade>)` / `rigcheck:<area>`), and a fix text; it ships with `tests/fixtures/<rule-id>/bad/` and `good/` (the catalog meta-test enforces all of this). The proving command for a new rule is that meta-test filtered to the rule id, red first.
- **Offline by default:** no network and no model calls outside `--deep`; rigcheck never edits the files it checks.
- **Secrets:** never read `~/.claude.json` whole, and never print file contents from the real home in a report or log; smoke runs against `$HOME` report counts only.

- **Decision round**: the user trusts technical decisions that are grounded in validation against their repos, so a technical open decision (a matcher boundary, a fallback, a severity inside a documented range, how to fix a false positive) is settled by the orchestrator when the smoke script confirms the approach on the real repos, and recorded in MAIN.md as "orchestrator, validated by smoke". The user is asked only when the smoke corpus cannot exercise the case, for a scope or product call (what a rule covers, a new dependency, moving work between milestones), or when the docs and a probe disagree.

## Agents and gates

- Explore: `Explore`. Second opinion on a rule's grammar or a discovery edge: `oracle`.
- Reviewer: `code-review` for every item.
- Gates, each wrapped as `cmd > .tmp/<name>.log 2>&1; rc=$?; tail -n 20 .tmp/<name>.log; (exit $rc)` from the worktree root:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check`
  - `nice -n 10 uv run pytest` (scoped with `-k <rule-id>` during a step, whole suite once at the end)
  - Smoke after any discovery or rule change: `bash .claude/skills/rigcheck-nextup/smoke.sh > .tmp/smoke.log 2>&1; rc=$?; cat .tmp/smoke.log; (exit $rc)` from the worktree root. It checks every git repo under D:/ with a commit in the last 30 days (rigcheck excluded) plus `$HOME`, writes `.tmp/smoke/<name>.json`, prints counts only (user and plugin layers once, repo layer per repo), and fails on an `internal-error`. Compare against the same script's output on `main`; a new rule's hits on real repos are read before landing, and a jump in one rule is a false-positive suspect to bring to the user.
- Parent-side gate: `git -C <wt> status --short` in the worktree and in the main checkout.

## Traps

- **Windows line endings:** scripts and fixtures that write files write LF (`newline="\n"`); a CRLF fixture changes byte counts that size rules measure.
- **Memory dir encoding** is `str(repo_root)` with every character outside `[A-Za-z0-9-]` turned into `-` (`D:\yaat` → `D--yaat`); worktrees get their own `D--<repo>-wt-...` dirs, so a smoke run from a worktree sees that worktree's memory, not the main checkout's.
- **Plugins on this machine** are real third-party code under `~/.claude/plugins/cache/`: findings there belong to the plugin layer, and a rule that fires on most plugins is more likely wrong than they are.

## Concurrency

- Worktrees: `git worktree add ../rigcheck.wt/<slug> -b <slug> main` from the main checkout.
- Ceiling: **two** implementers. Rule modules are separate files, but every new rule family also touches the hotspots above; pair a component-rules item with a config-rules item, never two items that add `Kind` values.
- Context: read the status bar's figure at every landing (`jq .context_window.used_percentage <scratchpad>/statusline.json`); past 40% the loop stops refilling, per the user-level `nextup`.

## Docs map

| What changed | Owning docs |
|---|---|
| A rule added, renamed or removed | the rule catalog in `docs/plans/v1.md` |
| A CLI command, flag, exit code or JSON field | `README.md` usage section |
| A term used in a project-specific sense (a pack, a load class, a layer) | `docs/README.md` Glossary |
| A milestone finished | tick it in `docs/plans/MAIN.md` |

The repo keeps no CHANGELOG yet.

## Landing

- Each item is multi-file work, so it lands by PR (the user's standing authorisation for this repo: commit, push and merge as you go). Commit in the worktree with a ≤4-char type tag, imperative ≤72-char subject and the session's attribution trailers; `git push -u origin <slug>`; `gh pr create` with a body opening with the agent-authored marker line; wait for `gh pr checks <n> --watch` to pass on ubuntu and windows; `gh pr merge <n> --squash --delete-branch`.
- Plan and docs-only commits (index edits, interview answers) go straight to `main` and are pushed.
- Then, from the main checkout: `git pull`, `git worktree remove ../rigcheck.wt/<slug>`, `git branch -D <slug>` (a squash merge leaves the branch unmerged by ancestry; confirm the PR shows `MERGED` with `gh pr view <n> --json state` first).
