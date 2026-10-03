---
name: rigcheck-nextup
description: Profile for the user-level `nextup` skill in the rigcheck repo — loaded by `nextup` at its step 0 for this project's plan convention, agents, gates, docs map and landing path. Not a loop of its own; invoke `/nextup`.
---

# rigcheck profile for `nextup`

The generic loop is the user-level `nextup` skill; this file supplies only what is rigcheck-specific.

siblings: none
linear: rigcheck

## Plan and tracker

- The plan lives in Linear: every task is a Linear issue in team RIG, per `~/.claude/docs/plan-operations.md`; `docs/plans/MAIN.md` is its generated snapshot, never edited by hand. Project order, which is the order the queue is worked: `M4 config rules`, `M5 to M7 CLI surface and packs`, `Backlog`. Each milestone issue points into `docs/plans/v1.md`: its rule catalog names every rule by the research id it cites (`CM2`, `SK4`, `HK3`, `sota:#2`), and `docs/research/official.md` / `sota.md` hold each id's quote, check type and suggested severity. Read the id's entry there before writing a brief; never cite a rule from memory.
- A milestone issue that is too big for one brief (about 100 implementer calls: up to four steps or six files) is a *design* item: **split** it into lettered sub-issues (`M3a`, `M3b`), grouped by rule module, before dispatching.
- Pre-loop hooks: none.
- An item **land**s after its commit, once every ruling it settled is written into the owning rule-area doc under `docs/rules/` as current behaviour, undated (docs map below). When every milestone of `v1.md` has landed, `git mv` it to `docs/plans/archive/` in the landing commit.
- A steer or a finding the item does not fix gets an **add**, in the project whose files it shares, else in `Backlog`.
- Tracker: **triage** as plan-operations says (GitHub issues reach the team through Linear's sync; an untriaged one is top-level with no project), each placed in the project that shares its files, else in `Backlog`.
- Pull requests: `gh pr list --repo leftos/rigcheck --state open --json number,title,headRefName`. An open PR from an item's own `<slug>` branch is that item still landing: finish the landing (Landing, below). Any other PR is triaged as plan-operations says.
- Hotspots (two items touching one wait on each other): `src/rigcheck/model.py` (the `Kind`/`LoadClass` enums), `src/rigcheck/discover.py`, `src/rigcheck/rules/__init__.py` (the module import list), `tests/test_rule_catalog.py`.

## Rulings every brief carries

- **Defect and cost linter, not a scorer** (research, user-approved plan): no overall score; no rule from `sota.md` §6 "Folklore: do not encode". A doc-backed style rule goes to the `advice` pack at `info` and cites both the doc and the null result.
- **Every rule** has a slug id, a pack, a severity, evidence strings (`official:<id>` / `sota:#<n> (<grade>)` / `rigcheck:<area>`), and a fix text; it ships with `tests/fixtures/<rule-id>/bad/` and `good/` (the catalog meta-test enforces all of this). The proving command for a new rule is that meta-test filtered to the rule id, red first.
- **Offline by default:** no network and no model calls outside `--deep`; rigcheck never edits the files it checks.
- **Secrets:** never read `~/.claude.json` whole, and never print file contents from the real home in a report or log; smoke runs against `$HOME` report counts only.

- **Decision round**: the user wants this loop to run autonomously: rigcheck audits the agent's own harness, and the user trusts the orchestrator's educated design calls. Every open decision the docs, research and smoke corpus can inform (a matcher boundary, a fallback, a severity, what a rule covers inside its research entry, splitting a line into its own item, how to fix a false positive) is settled by the orchestrator, noted in a comment on the item's issue until it lands and then written into the owning `docs/rules/` doc (before the item **land**s), and never asked. The user is asked only when the input is truly theirs: a new dependency, a change to the decisions in `docs/README.md` "Decisions" or to an earlier user ruling, dropping or adding a milestone, or docs and a probe that disagree with no way to settle it. A feature-branch verdict (an explorer's `BRANCH: feat/<name>`, or a hygiene pass's branch proposal) is always the user's, however well the smoke validates it (user-level `nextup` §3).

## Agents and gates

- Explore: `Explore`. Second opinion on a rule's grammar or a discovery edge: `oracle`.
- Reviewer: `code-review` for every item.
- Gates, each run through the repo's gate (`tools/gate.ps1`, the user-level launcher: it lowers priority, takes a machine-wide slot, writes the whole output to the log and prints the tail, keeping the exit status) from the worktree root, as `pwsh tools/gate.ps1 -Log .tmp/<name>.log -TimeoutSeconds <n> -Slot light -- <command>`:
  - `uv run ruff format --check .`, `uv run ruff check .`, `uv run ty check` (`-TimeoutSeconds 300`)
  - `uv run pytest` (`-TimeoutSeconds 450`, the whole suite taking about 170 s; `180` when scoped with `-k <rule-id>` during a step, whole suite once at the end)
  - A `git commit` (its prek hooks run ruff, ty and the agent-mail lease guard) as `pwsh tools/gate.ps1 -Log .tmp/commit.log -TimeoutSeconds 120 -Slot heavy -- git commit -F .tmp/msg-<slug>.txt`, the message written with the Write tool to a file new to this commit (slug from the subject) and committed in a later turn than the Write, never in its parallel batch
  - Smoke after any discovery or rule change: `pwsh tools/gate.ps1 -Log .tmp/smoke.log -TimeoutSeconds 700 -Slot light -- bash .claude/skills/rigcheck-nextup/smoke.sh`, then read `.tmp/smoke.log` whole (it holds counts only). It checks every git repo under D:/ with a commit in the last 30 days (rigcheck excluded) plus `$HOME`, writes `.tmp/smoke/<name>.json`, prints counts only (user and plugin layers once, repo layer per repo), and fails on an `internal-error`. Compare against the same script's output on `main`; a new rule's hits on real repos are read before landing, and a jump in one rule is a false-positive suspect to bring to the user.
- Parent-side gate: `git -C <wt> status --short` in the worktree and in the main checkout.

## Traps

- **Windows line endings:** scripts and fixtures that write files write LF (`newline="\n"`); a CRLF fixture changes byte counts that size rules measure.
- **Memory dir encoding** is `str(repo_root)` with every character outside `[A-Za-z0-9-]` turned into `-` (`D:\yaat` → `D--yaat`); worktrees get their own `D--<repo>-wt-...` dirs, so a smoke run from a worktree sees that worktree's memory, not the main checkout's.
- **Plugins on this machine** are real third-party code under `~/.claude/plugins/cache/`: findings there belong to the plugin layer, and a rule that fires on most plugins is more likely wrong than they are.

## Concurrency

- Worktrees: `git worktree add ../rigcheck.wt/<slug> -b <slug> <base>` from the main checkout, then `branch.<slug>.base` and `branch.<slug>.landOn` recorded as the user-level `nextup` §3 **Base and target** says (`main` and `main` by default).
- Ceiling: **two** implementers. Rule modules are separate files, but every new rule family also touches the hotspots above; pair a component-rules item with a config-rules item, never two items that add `Kind` values.
- Context: read the status bar's figure at every landing (`jq .context_window.used_percentage <scratchpad>/statusline.json`); past 40% the loop stops refilling, per the user-level `nextup`.

## Docs map

| What changed | Owning docs |
|---|---|
| A rule added, renamed or removed | the rule catalog in `docs/plans/v1.md` |
| A CLI command, flag, exit code or JSON field | `README.md` usage section |
| A term used in a project-specific sense (a pack, a load class, a layer) | `docs/README.md` Glossary |
| A design ruling (a matcher boundary, a scope, a severity, a false-positive fix, a probe's result) | the rule-area doc in `docs/rules/` that owns the rule (a new area gets a new doc and a line in `docs/rules/README.md`), written as current behaviour with its reason, no dates |
| An item finished | its issue **land**ed after the commit, once its rulings are in `docs/rules/` |

The repo keeps no CHANGELOG yet.

## Landing

- Each item is multi-file work, so it lands by PR (the user's standing authorisation for this repo: commit, push and merge as you go). Commit in the worktree with a ≤4-char type tag, imperative ≤72-char subject and the session's attribution trailers; `git push -u origin <slug>`; `gh pr create --base <landOn>` with a body opening with the agent-authored marker line (a stacked item opens its PR once the item under it has merged, after `git rebase --onto origin/<landOn> <base sha> <slug>`, so the PR carries only its own commits); wait for `gh pr checks <n> --watch` to pass on ubuntu and windows; `gh pr merge <n> --rebase --delete-branch`.
- An item under a feature marker (user-level `nextup` §3, "Feature branches") opens its PR with `--base feat/<name>` (its `landOn`; CI runs on a PR into any base here) and merges it the same way; the feature PR into `main` merges only through `/ship` on the feature branch, and the item's plan tick is its own commit on `main`.
- Plan and docs-only commits (index edits, interview answers) go straight to `main` and are pushed. A session running from a worktree offers `/ship` for them instead of pushing (user-level `nextup`, "A worktree session offers a ship instead of a push").
- Then, from the main checkout: `git pull` (in the feature worktree for an item under a marker), and once `git cherry <landOn> <slug> <base sha>` prints no `+` line (a rebase merge keeps each commit's patch id), `git worktree remove ../rigcheck.wt/<slug>` and `git branch -D <slug>`.
