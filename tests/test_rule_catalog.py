"""Every rule has evidence, a failing fixture and a passing fixture, and behaves on both."""

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from rigcheck.discover import MAX_BYTES, discover, memory_dir
from rigcheck.model import Kind, Layer
from rigcheck.rules import REGISTRY
from support import FIXTURES, Workspace, git_add, run_json, symlink_or_skip, write

ENGINE_RULES = {"internal-error", "discovery-error"}
FIXTURE_RULES = sorted(set(REGISTRY) - ENGINE_RULES)


def _pad_past_limit(rig: Path) -> None:
    write(rig / "CLAUDE.md", "# Project\n\n" + "filler line\n" * (MAX_BYTES // 12 + 1))


def _unc_link(rig: Path) -> None:
    target = r"\\server\share\CLAUDE.md" if os.name == "nt" else "//server/share/CLAUDE.md"
    symlink_or_skip(rig / "CLAUDE.md", target)


def _external_rule_link(rig: Path, *, scoped: bool) -> None:
    """Point ``rig``'s ``rules/shared`` at a folder outside the rig holding one rule, scoped by ``paths`` or not."""
    body = "---\npaths:\n  - src/**\n---\n\nScoped.\n" if scoped else "External rule.\n"
    target = write(rig.parent.parent / "elsewhere-rules" / "scoped.md", body).parent
    link = rig / ".claude" / "rules" / "shared"
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, os.fspath(target))


RUNTIME_SETUP: dict[tuple[str, str], Callable[[Path], None]] = {
    ("instructions-too-large", "bad"): _pad_past_limit,
    ("unc-symlink", "bad"): _unc_link,
    ("rule-external-scoped", "bad"): lambda rig: _external_rule_link(rig, scoped=True),
    ("rule-external-scoped", "good"): lambda rig: _external_rule_link(rig, scoped=False),
}


def _resolve_home_placeholders(workspace: Workspace) -> None:
    installed = workspace.home / ".claude" / "plugins" / "installed_plugins.json"
    if not installed.is_file():
        return
    write(installed, installed.read_text(encoding="utf-8").replace("{HOME}", workspace.home.as_posix()))


def _prepare(rule_id: str, variant: str, workspace: Workspace) -> Path:
    fixture = FIXTURES / rule_id
    for home_source in (fixture / variant / "home", fixture / "home"):
        if home_source.is_dir():
            shutil.copytree(home_source, workspace.home, dirs_exist_ok=True)
            break
    _resolve_home_placeholders(workspace)
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


def test_prepare_resolves_plugin_install_paths(workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixtures = tmp_path / "catalog-fixtures"
    home = fixtures / "demo-rule" / "bad" / "home"
    write(home / ".claude" / "settings.json", '{"enabledPlugins": {"demo@local": true}}\n')
    installed = {"version": 2, "plugins": {"demo@local": [{"scope": "user", "installPath": "{HOME}/.claude/plugins/cache/demo"}]}}
    write(home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(home / ".claude" / "plugins" / "cache" / "demo" / "skills" / "x" / "SKILL.md", "---\nname: x\n---\n")
    monkeypatch.setattr("test_rule_catalog.FIXTURES", fixtures)
    rig = _prepare("demo-rule", "bad", workspace)
    artifacts = [artifact for artifact in discover(rig, workspace.home).artifacts if artifact.layer is Layer.PLUGIN]
    expected = workspace.home / ".claude" / "plugins" / "cache" / "demo" / "skills" / "x" / "SKILL.md"
    assert [artifact.path for artifact in artifacts] == [expected]
    assert artifacts[0].kind is Kind.SKILL


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
