"""The rules that turn the budget report's listings into findings."""

import json
import shutil
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.cli import main
from rigcheck.discover import discover
from rigcheck.model import Finding
from rigcheck.rules import REGISTRY
from support import FIXTURES, Workspace, run_cli, run_json, write

SKILL_RULE = "skill-listing-over-budget"
WINDOW = 30_000
"""A window whose 1% budget, 300 tokens, one skill can reach exactly: ``s1: `` plus 896 characters is 900 characters, 300 tokens."""


def _listing_findings(workspace: Workspace, description_chars: int) -> list[Finding]:
    repo = workspace.rig()
    write(repo / ".claude" / "skills" / "s1" / "SKILL.md", f"---\nname: s1\ndescription: {'d' * description_chars}\n---\n\nBody.\n")
    findings = engine.run(discover(repo, workspace.home, WINDOW), REGISTRY.values())
    return [finding for finding in findings if finding.rule_id == SKILL_RULE]


def _bad_skill_rig(workspace: Workspace) -> Path:
    rig = workspace.home / "work" / "bad"
    shutil.copytree(FIXTURES / SKILL_RULE / "bad", rig)
    return rig


def test_skill_listing_at_budget_is_silent(workspace: Workspace) -> None:
    assert _listing_findings(workspace, 896) == []


def test_skill_listing_over_budget_warns(workspace: Workspace) -> None:
    findings = _listing_findings(workspace, 897)
    assert len(findings) == 1
    assert findings[0].message == (
        "skill listing ≈301 tokens is over its ≈300-token budget (1% of a 30k window) across 1 skill or command; by layer: repo ≈301"
    )


def test_window_flag_lifts_skill_listing_budget(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _bad_skill_rig(workspace)
    main(["check", str(rig), "--home", str(workspace.home), "--window", "1m", "--format", "json"])
    lifted = json.loads(capsys.readouterr().out)
    assert SKILL_RULE not in [finding["rule"] for finding in lifted["findings"]]
    _, default = run_json(capsys, rig, workspace.home)
    assert [finding["rule"] for finding in default["findings"]].count(SKILL_RULE) == 1


def test_budget_finding_has_no_path(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _bad_skill_rig(workspace)
    _, report = run_json(capsys, rig, workspace.home)
    finding = next(finding for finding in report["findings"] if finding["rule"] == SKILL_RULE)
    assert finding["path"] is None
    assert finding["line"] is None
    assert finding["layer"] is None
    assert finding["load_class"] == "every-turn"
    _, text = run_cli(capsys, rig, workspace.home, "text")
    assert any(line.startswith("  (setup)  WARN  skill-listing-over-budget  skill listing ≈") for line in text.splitlines())
