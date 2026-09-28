"""The output-style frontmatter rules: unknown keys, the plugin-only key, and the dropped coding instructions."""

import json
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import Kind, Layer
from rigcheck.rules import REGISTRY
from support import Workspace, write

STYLE = Path(".claude") / "output-styles" / "terse.md"
PLUGIN = "tools@market"
KEY = "output-style-key-unknown"
DROP = "output-style-drops-coding"
STYLE_RULES = (KEY, DROP)
DROP_MESSAGE = (
    "no keep-coding-instructions, so this style drops Claude Code's built-in coding instructions; set it to true to keep them, or false to confirm"
)


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBe terse.\n"


def _write_style(workspace: Workspace, text: str) -> Path:
    """Write ``text`` as the repo rig's only output style and return the rig."""
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    write(rig / STYLE, text)
    return rig


def _findings(workspace: Workspace, rig: Path, rule_ids: tuple[str, ...]) -> list[tuple[str, str, int | None]]:
    findings = engine.run(discover(rig, workspace.home), REGISTRY.values())
    return [(finding.rule_id, finding.message, finding.line) for finding in findings if finding.rule_id in rule_ids]


def _style(workspace: Workspace, text: str) -> list[tuple[str, str, int | None]]:
    return _findings(workspace, _write_style(workspace, text), STYLE_RULES)


def _frontmatter(workspace: Workspace, frontmatter: str) -> list[tuple[str, str, int | None]]:
    return _style(workspace, _file(frontmatter))


def _styles(rig: Path, workspace: Workspace) -> list[tuple[Layer, str]]:
    """Return the layer and file name of every output style the rig discovers."""
    artifacts = discover(rig, workspace.home).artifacts
    return [(artifact.layer, artifact.path.name) for artifact in artifacts if artifact.kind is Kind.OUTPUT_STYLE]


def _install_plugin_style(workspace: Workspace, text: str) -> None:
    """Install a plugin holding one output style and enable it in the fake home."""
    install = workspace.home / "plugin-cache" / "styles"
    write(install / "output-styles" / "terse.md", text)
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "styles"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))


def test_unknown_key_suggests_the_documented_spelling(workspace: Workspace) -> None:
    expected = 'unknown key "keep_coding_instructions" (did you mean "keep-coding-instructions"?); Claude Code ignores it'
    assert _frontmatter(workspace, "name: Terse\nkeep_coding_instructions: true\n") == [(KEY, expected, 3)]


def test_camel_case_variant_gets_the_hint_and_silences_the_drop(workspace: Workspace) -> None:
    expected = 'unknown key "keepCodingInstructions" (did you mean "keep-coding-instructions"?); Claude Code ignores it'
    assert _frontmatter(workspace, "name: Terse\nkeepCodingInstructions: true\n") == [(KEY, expected, 3)]


def test_unknown_key_without_a_near_match(workspace: Workspace) -> None:
    assert _frontmatter(workspace, "name: Terse\nmode: terse\n") == [
        (DROP, DROP_MESSAGE, 1),
        (KEY, 'unknown key "mode"; Claude Code ignores it', 3),
    ]


def test_non_string_keys_are_ignored(workspace: Workspace) -> None:
    assert _frontmatter(workspace, "1: x\nname: Terse\n") == [(DROP, DROP_MESSAGE, 1)]


@pytest.mark.parametrize("value", ["true", "false", "no", "[1]"])
def test_keep_coding_instructions_silences_the_drop(workspace: Workspace, value: str) -> None:
    assert _frontmatter(workspace, f"name: Terse\nkeep-coding-instructions: {value}\n") == []


def test_style_without_frontmatter_drops_coding(workspace: Workspace) -> None:
    assert _style(workspace, "Be terse.\n") == [(DROP, DROP_MESSAGE, 1)]


def test_rejected_frontmatter_still_drops_coding(workspace: Workspace) -> None:
    assert _style(workspace, "---\nname: Terse\n\nBe terse.\n") == [(DROP, DROP_MESSAGE, 1)]


def test_force_for_plugin_is_reported_outside_a_plugin(workspace: Workspace) -> None:
    assert _frontmatter(workspace, "name: Terse\nforce-for-plugin: true\n") == [
        (DROP, DROP_MESSAGE, 1),
        (KEY, '"force-for-plugin" works only in a plugin\'s output style; Claude Code ignores it', 3),
    ]


def test_force_for_plugin_variant_gets_no_hint(workspace: Workspace) -> None:
    assert _frontmatter(workspace, "name: Terse\nkeep-coding-instructions: true\nforce_for_plugin: true\n") == [
        (KEY, 'unknown key "force_for_plugin"; Claude Code ignores it', 4),
    ]


def test_force_for_plugin_is_reported_in_the_user_layer(workspace: Workspace) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    text = _file("name: Terse\nkeep-coding-instructions: true\nforce-for-plugin: true\n")
    write(workspace.home / ".claude" / "output-styles" / "terse.md", text)
    assert _styles(rig, workspace) == [(Layer.USER, "terse.md")]
    assert _findings(workspace, rig, STYLE_RULES) == [
        (KEY, '"force-for-plugin" works only in a plugin\'s output style; Claude Code ignores it', 4),
    ]


def test_force_for_plugin_is_quiet_in_a_plugin_style(workspace: Workspace) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    _install_plugin_style(workspace, _file("name: Terse\nkeep-coding-instructions: true\nforce-for-plugin: true\n"))
    assert _styles(rig, workspace) == [(Layer.PLUGIN, "terse.md")]
    assert _findings(workspace, rig, STYLE_RULES) == []


def test_plugin_style_drops_coding(workspace: Workspace) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    _install_plugin_style(workspace, _file("name: Terse\n"))
    assert _styles(rig, workspace) == [(Layer.PLUGIN, "terse.md")]
    assert _findings(workspace, rig, STYLE_RULES) == [(DROP, DROP_MESSAGE, 1)]


def test_empty_frontmatter_drops_coding(workspace: Workspace) -> None:
    assert _style(workspace, "---\n---\n\nBe terse.\n") == [(DROP, DROP_MESSAGE, 1)]


def test_crlf_yaml_claude_code_rejects_still_drops_coding(workspace: Workspace) -> None:
    rig = workspace.rig()
    write(rig / "CLAUDE.md", "# Project\n")
    style = rig / STYLE
    style.parent.mkdir(parents=True, exist_ok=True)
    style.write_bytes(_file("name: Terse\ndescription: a: b\n").replace("\n", "\r\n").encode())
    assert _findings(workspace, rig, STYLE_RULES) == [(DROP, DROP_MESSAGE, 1)]


def test_style_yaml_nonstandard_is_reported(workspace: Workspace) -> None:
    rig = _write_style(workspace, _file("name: Terse\ndescription: Terse: short replies.\n"))
    findings = engine.run(discover(rig, workspace.home), REGISTRY.values())
    reported = {finding.rule_id for finding in findings if finding.path is not None and finding.path.name == STYLE.name}
    assert reported == {"frontmatter-yaml-nonstandard", DROP}
