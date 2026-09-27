"""Every rule has evidence, a failing fixture and a passing fixture, and behaves on both."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from rigcheck.discover import MAX_BYTES, memory_dir
from rigcheck.rules import REGISTRY
from support import FIXTURES, Workspace, git_add, run_json, symlink_or_skip, write

ENGINE_RULES = {"internal-error", "discovery-error"}
FIXTURE_RULES = sorted(set(REGISTRY) - ENGINE_RULES)


def _pad_past_limit(rig: Path) -> None:
    write(rig / "CLAUDE.md", "# Project\n\n" + "filler line\n" * (MAX_BYTES // 12 + 1))


def _unc_link(rig: Path) -> None:
    target = r"\\server\share\CLAUDE.md" if os.name == "nt" else "//server/share/CLAUDE.md"
    symlink_or_skip(rig / "CLAUDE.md", target)


RUNTIME_SETUP: dict[tuple[str, str], Callable[[Path], None]] = {
    ("instructions-too-large", "bad"): _pad_past_limit,
    ("unc-symlink", "bad"): _unc_link,
}


def _prepare(rule_id: str, variant: str, workspace: Workspace) -> Path:
    fixture = FIXTURES / rule_id
    for home_source in (fixture / variant / "home", fixture / "home"):
        if home_source.is_dir():
            shutil.copytree(home_source, workspace.home, dirs_exist_ok=True)
            break
    rig = workspace.home / "work" / variant
    excluded = ["home", "memory"]
    shutil.copytree(fixture / variant, rig, ignore=lambda directory, _names: excluded if Path(directory) == fixture / variant else [])
    memory_source = fixture / variant / "memory"
    if memory_source.is_dir():
        shutil.copytree(memory_source, memory_dir(rig.resolve(), workspace.home.resolve()), dirs_exist_ok=True)
    gitfixture = rig / ".gitfixture"
    if gitfixture.is_file():
        git_add(rig, gitfixture.read_text(encoding="utf-8").split())
    setup = RUNTIME_SETUP.get((rule_id, variant))
    if setup is not None:
        setup(rig)
    return rig


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_has_evidence_and_summary(rule_id: str) -> None:
    rule = REGISTRY[rule_id]
    assert rule.evidence
    assert rule.summary
    assert rule.fix
    assert rule.pack == "core"


@pytest.mark.parametrize("rule_id", FIXTURE_RULES)
def test_rule_has_both_fixtures(rule_id: str) -> None:
    assert (FIXTURES / rule_id / "bad").is_dir()
    assert (FIXTURES / rule_id / "good").is_dir()


@pytest.mark.parametrize("rule_id", FIXTURE_RULES)
def test_bad_fixture_triggers_rule(rule_id: str, workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _prepare(rule_id, "bad", workspace)
    _, report = run_json(capsys, rig, workspace.home)
    rules = [finding["rule"] for finding in report["findings"]]
    assert rule_id in rules
    assert "internal-error" not in rules


@pytest.mark.parametrize("rule_id", FIXTURE_RULES)
def test_good_fixture_passes_rule(rule_id: str, workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _prepare(rule_id, "good", workspace)
    _, report = run_json(capsys, rig, workspace.home)
    rules = [finding["rule"] for finding in report["findings"]]
    assert rule_id not in rules
    assert "internal-error" not in rules
