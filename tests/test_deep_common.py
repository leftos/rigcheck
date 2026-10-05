"""The shared helper that turns a ``--deep`` family's verdicts into findings of a deep rule."""

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from rigcheck.cli import main
from rigcheck.model import DEFAULT_WINDOW, Artifact, Finding, Kind, Layer, LoadClass, Rig, Severity, Verdict
from rigcheck.rules import REGISTRY, rule
from rigcheck.rules.deep_common import deep_artifacts, findings_from
from support import Workspace, write

RULE_ID = "deep-common-throwaway"


@pytest.fixture
def deep_rule() -> Iterator[str]:
    def check(rig: Rig) -> Iterator[Finding]:
        """A throwaway deep check that turns the fake family's verdicts into findings."""
        return findings_from(rig, "fake", RULE_ID)

    rule(RULE_ID, "deep", Severity.WARN, "Fix it.", ("rigcheck:deep",))(check)
    try:
        yield RULE_ID
    finally:
        REGISTRY.pop(RULE_ID, None)


def _rig(tmp_path: Path, artifacts: tuple[Artifact, ...], verdicts: dict[str, tuple[Verdict, ...]]) -> Rig:
    repo = tmp_path / "repo"
    rig = Rig(repo, repo, tmp_path / "home", artifacts, (), (), DEFAULT_WINDOW)
    rig.verdicts.update(verdicts)
    return rig


def _claude_md(tmp_path: Path) -> Artifact:
    return Artifact(tmp_path / "repo" / "CLAUDE.md", Kind.INSTRUCTIONS, Layer.REPO, LoadClass.EVERY_TURN)


def test_no_findings_for_missing_family(tmp_path: Path, deep_rule: str) -> None:
    rig = _rig(tmp_path, (_claude_md(tmp_path),), {})
    assert list(findings_from(rig, "fake", deep_rule)) == []


def test_no_findings_for_empty_verdicts(tmp_path: Path, deep_rule: str) -> None:
    rig = _rig(tmp_path, (_claude_md(tmp_path),), {"fake": ()})
    assert list(findings_from(rig, "fake", deep_rule)) == []


def test_maps_path_line_layer_and_load_class(tmp_path: Path, deep_rule: str) -> None:
    repo_file = _claude_md(tmp_path)
    user_file = Artifact(tmp_path / "home" / ".claude" / "skills" / "x" / "SKILL.md", Kind.SKILL, Layer.USER, LoadClass.ON_INVOKE)
    later_duplicate = Artifact(repo_file.path, Kind.INSTRUCTIONS, Layer.USER, LoadClass.NOT_LOADED)
    verdicts = (Verdict("fake", repo_file.path, 3, "vague rule"), Verdict("fake", user_file.path, 7, "conflicting step"))
    rig = _rig(tmp_path, (repo_file, user_file, later_duplicate), {"fake": verdicts, "other": (Verdict("other", repo_file.path, 1, "x"),)})
    assert list(findings_from(rig, "fake", deep_rule)) == [
        Finding(deep_rule, Severity.WARN, repo_file.path, 3, "vague rule", "Fix it.", Layer.REPO, LoadClass.EVERY_TURN),
        Finding(deep_rule, Severity.WARN, user_file.path, 7, "conflicting step", "Fix it.", Layer.USER, LoadClass.ON_INVOKE),
    ]


def test_finding_uses_the_artifact_deep_would_send(tmp_path: Path, deep_rule: str) -> None:
    eligible = _claude_md(tmp_path)
    earlier_unloaded = Artifact(eligible.path, Kind.INSTRUCTIONS, Layer.REPO, LoadClass.NOT_LOADED)
    rig = _rig(tmp_path, (earlier_unloaded, eligible), {"fake": (Verdict("fake", eligible.path, 2, "vague"),)})
    [finding] = findings_from(rig, "fake", deep_rule)
    assert (finding.layer, finding.load_class) == (Layer.REPO, LoadClass.EVERY_TURN)
    assert list(deep_artifacts(rig).values()) == [eligible]


def test_line_none_means_whole_file(tmp_path: Path, deep_rule: str) -> None:
    artifact = _claude_md(tmp_path)
    rig = _rig(tmp_path, (artifact,), {"fake": (Verdict("fake", artifact.path, None, "too long overall"),)})
    [finding] = findings_from(rig, "fake", deep_rule)
    assert finding.path == artifact.path
    assert finding.line is None


def test_verdict_with_no_artifact_raises(tmp_path: Path, deep_rule: str) -> None:
    stale = tmp_path / "repo" / "gone.md"
    rig = _rig(tmp_path, (_claude_md(tmp_path),), {"fake": (Verdict("fake", stale, None, "vague"),)})
    with pytest.raises(ValueError, match="matches no artifact") as excinfo:
        list(findings_from(rig, "fake", deep_rule))
    assert str(excinfo.value) == f"verdict for {stale} matches no artifact"


def test_raising_deep_rule_becomes_internal_error(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], deep_rule: str
) -> None:
    target = workspace.rig()
    write(target / "docs" / "other.md", "x\n")
    write(target / "CLAUDE.md", "Read `docs/gone.md`.\n")

    def stale_verdicts(parser: argparse.ArgumentParser, args: argparse.Namespace, rig: Rig, home: Path) -> list[Finding]:
        rig.verdicts["fake"] = (Verdict("fake", rig.target / "stale.md", None, "vague"),)
        return []

    monkeypatch.setattr("rigcheck.cli._deep", stale_verdicts)
    main(["check", str(target), "--home", str(workspace.home), "--format", "json", "--deep"])
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert sorted(finding["rule"] for finding in findings) == ["internal-error", "reference-path-missing"]
    [error] = [finding for finding in findings if finding["rule"] == "internal-error"]
    assert error["message"].startswith(f"rule {deep_rule} raised ValueError: verdict for ")
    assert error["message"].endswith("stale.md matches no artifact")
