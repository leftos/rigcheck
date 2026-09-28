"""The component rules' shared module: artifact selection, key tables and the frontmatter warn."""

import json
from pathlib import Path

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Finding, Kind, Layer
from rigcheck.rules import REGISTRY
from rigcheck.rules.components import COMMAND_KEYS, FRONTMATTER_KINDS, SKILL_KEYS, components, yaml_line
from support import Workspace, write

PLUGIN = "tools@market"
AGENT = Path(".claude") / "agents" / "helper.md"


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _agent_findings(workspace: Workspace, frontmatter: str) -> list[Finding]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / AGENT, _file(frontmatter))
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [finding for finding in findings if finding.rule_id == "frontmatter-yaml-nonstandard"]


def test_components_selects_kinds_in_rig_order(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "skills" / "one" / "SKILL.md", _file("name: one\ndescription: One.\n"))
    write(repo / ".claude" / "agents" / "two.md", _file("name: two\ndescription: Two.\n"))
    write(repo / ".claude" / "rules" / "three.md", _file("paths: src/**\n"))
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    expected = [artifact for artifact in rig.artifacts if artifact.kind in FRONTMATTER_KINDS]
    assert len(expected) == 3
    assert components(rig, FRONTMATTER_KINDS) == expected
    assert [artifact.kind for artifact in components(rig, (Kind.AGENT,))] == [Kind.AGENT]
    assert components(rig, (Kind.MEMORY_INDEX, Kind.SETTINGS)) == []


def test_command_keys_are_the_skill_keys_without_name_and_paths() -> None:
    assert SKILL_KEYS - {"name", "paths"} == COMMAND_KEYS


def test_reason_is_the_problem_line_not_the_context(workspace: Workspace) -> None:
    findings = _agent_findings(workspace, "name: helper\ndescription: @foo bar\n")
    expected = "frontmatter is not strict YAML (found character '@' that cannot start any token); Claude Code loads it only through its retry"
    assert [(finding.message, finding.line) for finding in findings] == [(expected, 3)]


def test_line_is_the_block_line_plus_one(workspace: Workspace) -> None:
    findings = _agent_findings(workspace, "name: helper\ndescription: use when: x\n")
    expected = "frontmatter is not strict YAML (mapping values are not allowed here); Claude Code loads it only through its retry"
    assert [(finding.message, finding.line) for finding in findings] == [(expected, 3)]


def test_line_falls_back_to_one_without_a_line_reference() -> None:
    assert yaml_line("invalid YAML: unexpected end of stream") == 1
    assert yaml_line("unclosed frontmatter") == 1


def test_plugin_layer_skill_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", _file("name: lint\ndescription: Use when: it breaks\n"))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id == "frontmatter-yaml-nonstandard"]
    assert [(finding.layer, finding.line) for finding in fired] == [(Layer.PLUGIN, 3)]
