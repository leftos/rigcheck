"""The skill and command frontmatter rules: placement, parse, keys, description and reachability."""

import json
from pathlib import Path

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import Layer
from rigcheck.report.budget import LISTING_DETAIL_CHARS
from rigcheck.rules import REGISTRY
from support import Workspace, write

SKILL = Path(".claude") / "skills" / "demo" / "SKILL.md"
COMMAND = Path(".claude") / "commands" / "x.md"
PLUGIN = "tools@market"


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _findings(workspace: Workspace, rule_id: str, text: str, path: Path = SKILL) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / path, text)
    return _run(workspace, rule_id)


def _misplaced(line: int) -> str:
    return f"the frontmatter starts on line {line}, so Claude Code reads the whole file as content and no field is set"


def test_misplaced_after_a_blank_line_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "\n---\nname: a\n---\n") == [(_misplaced(2), 2)]


def test_misplaced_indented_fence_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", " ---\nname: a\n---\n") == [(_misplaced(1), 1)]


def test_misplaced_after_a_heading_is_not_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "# Title\n\n---\n") == []


def test_misplaced_on_line_one_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-misplaced", "---\nname: a\n---\n") == []


def _rejected(reason: str) -> str:
    return f"Claude Code rejects the frontmatter ({reason}), so the skill loads with no fields set"


def test_invalid_crlf_colon_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    skill = repo / SKILL
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_bytes(b"---\r\nname: demo\r\ndescription: use when: x\r\n---\r\n\r\nBody.\r\n")
    assert _run(workspace, "skill-frontmatter-invalid") == [(_rejected("mapping values are not allowed here"), 3)]


def test_invalid_lf_colon_loads_through_the_retry(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-invalid", _file("name: demo\ndescription: use when: x\n")) == []


def test_invalid_unclosed_fires_on_line_one(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-frontmatter-invalid", "---\nname: a\n") == [(_rejected("unclosed frontmatter"), 1)]


def _unknown(key: str, known: str | None, line: int) -> tuple[str, int]:
    hint = f' (did you mean "{known}"?)' if known else ""
    return f'unknown key "{key}"{hint}; Claude Code ignores it', line


def _unknown_findings(workspace: Workspace, frontmatter: str, path: Path = SKILL) -> list[tuple[str, int | None]]:
    return _findings(workspace, "skill-key-unknown", _file(frontmatter), path)


def test_unknown_snake_case_suggests_the_hyphenated_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "name: a\nallowed_tools: Read\n") == [_unknown("allowed_tools", "allowed-tools", 3)]


def test_unknown_camel_case_suggests_the_hyphenated_key(workspace: Workspace) -> None:
    expected = [_unknown("disableModelInvocation", "disable-model-invocation", 2)]
    assert _unknown_findings(workspace, "disableModelInvocation: true\n") == expected


def test_unknown_hyphenated_when_to_use_suggests_the_underscore_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "when-to-use: x\n") == [_unknown("when-to-use", "when_to_use", 2)]


def test_unknown_key_without_a_near_match_has_no_suggestion(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "tags: x\n") == [_unknown("tags", None, 2)]


def test_unknown_capitalised_key_suggests_the_lower_case_key(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "Description: x\n") == [_unknown("Description", "description", 2)]


def test_unknown_non_string_key_is_reported_as_text(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "1: x\n") == [_unknown("1", None, 2)]


def test_unknown_skips_name_and_paths_in_a_command(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "name: x\npaths: src/**\n", COMMAND) == []


def test_unknown_key_in_a_command_fires(workspace: Workspace) -> None:
    assert _unknown_findings(workspace, "allowed_tools: Read\n", COMMAND) == [_unknown("allowed_tools", "allowed-tools", 2)]


def test_unknown_key_in_a_plugin_skill_fires(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", _file("name: lint\ndescription: Lint.\ntags: x\n"))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id == "skill-key-unknown"]
    assert [(finding.layer, finding.message, finding.line) for finding in fired] == [(Layer.PLUGIN, _unknown("tags", None, 4)[0], 4)]


MISSING = [("no description, so Claude Code lists the first line of content instead", 1)]


def test_description_missing_without_frontmatter_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "# Demo\n\nBody.\n") == MISSING


def test_description_missing_key_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("name: demo\n")) == MISSING


def test_description_not_a_string_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("description: 5\n")) == MISSING


def test_description_blank_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file('description: "  "\n')) == MISSING


def test_description_missing_skips_rejected_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "---\nname: a\n") == []


def test_description_present_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", _file("description: Demo.\n")) == []


def test_description_missing_in_a_command_fires(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-description-missing", "Run the thing.\n", COMMAND) == MISSING


def _truncated(total: int) -> list[tuple[str, int | None]]:
    message = f"description and when_to_use run to {total} characters; the skill listing cuts them at {LISTING_DETAIL_CHARS}"
    return [(message, 2)]


def test_description_at_the_limit_passes(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1536}\n")
    assert _findings(workspace, "skill-description-truncated", text) == []


def test_description_past_the_limit_fires(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1537}\n")
    assert _findings(workspace, "skill-description-truncated", text) == _truncated(1537)


def test_description_and_when_to_use_count_the_joining_space(workspace: Workspace) -> None:
    text = _file(f"description: {'a' * 1000}\nwhen_to_use: {'b' * 536}\n")
    assert _findings(workspace, "skill-description-truncated", text) == _truncated(1537)


UNREACHABLE = "user-invocable is false and disable-model-invocation is true, so neither you nor Claude can invoke it"


def test_unreachable_booleans_fire(workspace: Workspace) -> None:
    text = _file("user-invocable: false\ndisable-model-invocation: true\n")
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 3)]


def test_unreachable_yes_no_fire(workspace: Workspace) -> None:
    text = _file("disable-model-invocation: yes\nuser-invocable: no\n")
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 2)]


def test_unreachable_string_and_number_fire(workspace: Workspace) -> None:
    text = _file('user-invocable: "false"\ndisable-model-invocation: 1\n')
    assert _findings(workspace, "skill-unreachable", text) == [(UNREACHABLE, 3)]


def test_unreachable_needs_both_settings(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-unreachable", _file("user-invocable: false\n")) == []


def test_unreachable_disable_alone_passes(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-unreachable", _file("disable-model-invocation: true\n")) == []


def test_unreachable_command_fires(workspace: Workspace) -> None:
    text = _file("user-invocable: false\ndisable-model-invocation: true\n")
    assert _findings(workspace, "skill-unreachable", text, COMMAND) == [(UNREACHABLE, 3)]
