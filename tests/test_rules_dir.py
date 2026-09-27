"""The rules-directory rules: unknown keys, unparseable frontmatter and rules linked out of the project."""

import os
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import MAX_BYTES, discover
from rigcheck.rules import REGISTRY
from support import Workspace, symlink_or_skip, write

RULE = Path(".claude") / "rules" / "style.md"
UNC_RULES = r"\\server\share\rules" if os.name == "nt" else "//server/share/rules"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _findings(workspace: Workspace, rule_id: str, text: str, *, in_home: bool = False) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write((workspace.home if in_home else repo) / RULE, text)
    return _run(workspace, rule_id)


def _link(repo: Path, name: str, target: Path) -> None:
    link = repo / ".claude" / "rules" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, os.fspath(target))


def test_key_unknown_suggests_case_fix(workspace: Workspace) -> None:
    text = "---\nPaths:\n  - src/**\n---\n\nStyle rules.\n"
    expected = [('unknown key "Paths" (did you mean "paths"?); Claude Code ignores it', 2)]
    assert _findings(workspace, "rule-key-unknown", text) == expected


def test_key_unknown_silent_when_yaml_invalid(workspace: Workspace) -> None:
    assert _findings(workspace, "rule-key-unknown", '---\nglobs: "src/**"\n') == []


def test_frontmatter_invalid_ignores_strict_only_yaml(workspace: Workspace) -> None:
    text = "---\npaths:\n  - src/**\ndescription: a: b\n---\n\nLoads anyway.\n"
    assert _findings(workspace, "rule-frontmatter-invalid", text) == []


def test_external_scoped_silent_without_paths(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    external = write(workspace.home / "elsewhere-rules" / "plain.md", "External rule.\n")
    _link(repo, "shared", external.parent)
    assert _run(workspace, "rule-external-scoped") == []


def test_external_scoped_silent_on_user_layer(workspace: Workspace) -> None:
    text = "---\npaths:\n  - src/**\n---\n\nMine.\n"
    assert _findings(workspace, "rule-external-scoped", text, in_home=True) == []


def test_external_scoped_skips_network_links(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    link = repo / ".claude" / "rules" / "shared"
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, UNC_RULES)
    monkeypatch.setattr("rigcheck.rules.rules_dir.is_outside", _fail_outside)
    rules = _every_rule_id(workspace)
    assert "rule-external-scoped" not in rules
    assert "internal-error" not in rules


def _fail_outside(*args: object) -> bool:
    raise AssertionError(f"is_outside was called with {args!r}")


def _every_rule_id(workspace: Workspace) -> list[str]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [finding.rule_id for finding in findings]


def test_frontmatter_invalid_silent_when_not_loaded(workspace: Workspace) -> None:
    text = "---\n- src/**\n---\n\n" + "filler line\n" * (MAX_BYTES // 12 + 1)
    assert _findings(workspace, "rule-frontmatter-invalid", text) == []
