"""The component rules' shared module: artifact selection, key tables and the frontmatter warn."""

import json

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import Kind, Layer
from rigcheck.rules import REGISTRY
from rigcheck.rules.components import COMMAND_KEYS, FRONTMATTER_KINDS, SKILL_KEYS, components
from support import Workspace, write

PLUGIN = "tools@market"


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def test_components_selects_kinds_in_rig_order(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".claude" / "skills" / "one" / "SKILL.md", _file("name: one\ndescription: One.\n"))
    write(repo / ".claude" / "agents" / "two.md", _file("name: two\ndescription: Two.\n"))
    write(repo / ".claude" / "rules" / "three.md", _file("paths: src/**\n"))
    rig = discover(repo, workspace.home)
    expected = [artifact for artifact in rig.artifacts if artifact.kind in FRONTMATTER_KINDS]
    assert len(expected) == 3
    assert components(rig, FRONTMATTER_KINDS) == expected
    assert [artifact.kind for artifact in components(rig, (Kind.AGENT,))] == [Kind.AGENT]
    assert components(rig, (Kind.MEMORY_INDEX, Kind.SETTINGS)) == []


def test_command_keys_are_the_skill_keys_without_name_and_paths() -> None:
    assert SKILL_KEYS - {"name", "paths"} == COMMAND_KEYS


def test_plugin_layer_skill_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", _file("name: lint\ndescription: Use when: it breaks\n"))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id == "frontmatter-yaml-nonstandard"]
    assert [(finding.layer, finding.line) for finding in fired] == [(Layer.PLUGIN, 1)]
