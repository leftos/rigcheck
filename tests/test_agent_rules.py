"""The subagent frontmatter rules: skipped files, unknown keys, and invalid or miscased values."""

import json
from pathlib import Path

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Layer
from rigcheck.rules import REGISTRY
from support import Workspace, write

AGENT = Path(".claude") / "agents" / "helper.md"
PLUGIN = "tools@market"
AGENT_RULES = ("agent-skipped", "agent-key-unknown", "agent-value-invalid", "agent-value-case")
PLUGIN_AGENT_RULES = (*AGENT_RULES, "agent-key-ignored-in-plugin")
VALID = "name: helper\ndescription: Helps.\n"

DEBUGGER = (
    "name: debugger\n"
    "description: Root-cause diagnostician for bugs, used when reading alone has not settled it: a drawn thing that looks wrong\n"
    "tools: Read, Glob, Grep, PowerShell, mcp__godot__run_project\n"
    "model: opus\n"
    "effort: high\n"
)


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _run(workspace: Workspace, rule_ids: tuple[str, ...]) -> list[tuple[str, str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.rule_id, finding.message, finding.line) for finding in findings if finding.rule_id in rule_ids]


def _all(workspace: Workspace, text: str) -> list[tuple[str, str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / AGENT, text)
    return _run(workspace, AGENT_RULES)


def _findings(workspace: Workspace, rule_id: str, text: str) -> list[tuple[str, int | None]]:
    return [(message, line) for found_id, message, line in _all(workspace, text) if found_id == rule_id]


def _values(workspace: Workspace, frontmatter: str) -> list[tuple[str, str, int | None]]:
    return _all(workspace, _file(VALID + frontmatter))


def test_debugger_shape_loads_through_the_retry_and_passes(workspace: Workspace) -> None:
    assert _all(workspace, _file(DEBUGGER)) == []


def test_debugger_shape_with_crlf_is_skipped(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    agent = repo / AGENT
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_bytes(_file(DEBUGGER).replace("\n", "\r\n").encode())
    message = 'Claude Code rejects the frontmatter (mapping values are not allowed here), so the agent loads as "helper" with no settings'
    assert _run(workspace, AGENT_RULES) == [("agent-skipped", message, 3)]


def test_unclosed_frontmatter_is_skipped(workspace: Workspace) -> None:
    message = 'Claude Code rejects the frontmatter (unclosed frontmatter), so the agent loads as "helper" with no settings'
    assert _findings(workspace, "agent-skipped", "---\nname: helper\n") == [(message, 1)]


def test_fence_after_a_blank_line_is_skipped(workspace: Workspace) -> None:
    expected = [("the frontmatter starts on line 2, so Claude Code skips the agent", 2)]
    assert _findings(workspace, "agent-skipped", "\n" + _file(VALID)) == expected


def test_indented_fence_is_skipped(workspace: Workspace) -> None:
    expected = [('the opening line is " ---", not exactly ---, so Claude Code skips the agent', 1)]
    assert _findings(workspace, "agent-skipped", " ---\n" + VALID + "---\n") == expected


def test_horizontal_rule_after_a_blank_line_is_silent(workspace: Workspace) -> None:
    assert _all(workspace, "\n---\n\n# Notes\n") == []


def test_bom_before_the_fence_loads(workspace: Workspace) -> None:
    assert _all(workspace, "﻿" + _file(VALID + "model: sonnet\n")) == []


def _rejected(reason: str) -> list[tuple[str, int | None]]:
    return [(f'Claude Code rejects the frontmatter ({reason}), so the agent loads as "helper" with no settings', 1)]


def test_list_frontmatter_is_skipped(workspace: Workspace) -> None:
    assert _findings(workspace, "agent-skipped", _file("- a\n- b\n")) == _rejected("frontmatter is a list, not a mapping")


def test_string_frontmatter_is_skipped(workspace: Workspace) -> None:
    assert _findings(workspace, "agent-skipped", _file("just text\n")) == _rejected("frontmatter is a str, not a mapping")


def test_yaml_the_retry_also_rejects_is_skipped(workspace: Workspace) -> None:
    found = _all(workspace, _file(VALID + '"unclosed\n'))
    assert [rule_id for rule_id, _, _ in found] == ["agent-skipped"]
    assert found[0][1].startswith("Claude Code rejects the frontmatter (")


def test_yaml_one_one_booleans_are_names_and_descriptions(workspace: Workspace) -> None:
    assert _all(workspace, _file("name: yes\ndescription: No\n")) == []


def test_date_name_is_a_string(workspace: Workspace) -> None:
    assert _all(workspace, _file("name: 2024-01-01\ndescription: Helps.\n")) == []


def test_description_mapping_or_number_is_skipped(workspace: Workspace) -> None:
    expected = [("description is not a string, so Claude Code skips the agent", 3)]
    assert _findings(workspace, "agent-skipped", _file("name: helper\ndescription:\n  a: b\n")) == expected
    assert _findings(workspace, "agent-skipped", _file("name: helper\ndescription: 5\n")) == expected


def test_body_only_file_is_silent(workspace: Workspace) -> None:
    assert _all(workspace, "# Notes\n\nAbout the agents.\n") == []


def test_missing_name_is_skipped(workspace: Workspace) -> None:
    expected = [("no name, so Claude Code treats the file as documentation and skips it", 1)]
    assert _findings(workspace, "agent-skipped", _file("description: Helps.\n")) == expected


def test_name_starting_with_a_dash_is_skipped(workspace: Workspace) -> None:
    text = _file("name: -helper\ndescription: Helps.\n")
    assert _findings(workspace, "agent-skipped", text) == [('name "-helper" starts with "-", so Claude Code skips the agent', 2)]


def test_name_holding_a_colon_is_skipped(workspace: Workspace) -> None:
    text = _file("name: a:b\ndescription: Helps.\n")
    assert _findings(workspace, "agent-skipped", text) == [('name "a:b" holds ":", so Claude Code skips the agent', 2)]


def test_empty_name_is_skipped(workspace: Workspace) -> None:
    text = _file('name: "  "\ndescription: Helps.\n')
    assert _findings(workspace, "agent-skipped", text) == [("name is empty, so Claude Code skips the agent", 2)]


def test_name_not_a_string_is_skipped(workspace: Workspace) -> None:
    text = _file("name: 5\ndescription: Helps.\n")
    assert _findings(workspace, "agent-skipped", text) == [("name is not a string, so Claude Code skips the agent", 2)]


def test_missing_description_is_skipped(workspace: Workspace) -> None:
    assert _findings(workspace, "agent-skipped", _file("name: helper\n")) == [("no description, so Claude Code skips the agent", 1)]


def test_empty_description_is_skipped(workspace: Workspace) -> None:
    text = _file('name: helper\ndescription: ""\n')
    assert _findings(workspace, "agent-skipped", text) == [("description is empty, so Claude Code skips the agent", 3)]


def test_skipped_file_has_no_key_or_value_findings(workspace: Workspace) -> None:
    found = _all(workspace, _file("name: helper\nmax_turns: 5\nmodel: gpt-4\n"))
    assert [rule_id for rule_id, _, _ in found] == ["agent-skipped"]


def _unknown(key: str, known: str | None) -> str:
    hint = f' (did you mean "{known}"?)' if known else ""
    return f'unknown key "{key}"{hint}; Claude Code ignores it'


def test_snake_case_max_turns_suggests_max_turns(workspace: Workspace) -> None:
    assert _values(workspace, "max_turns: 5\n") == [("agent-key-unknown", _unknown("max_turns", "maxTurns"), 4)]


def test_kebab_case_keys_suggest_camel_case(workspace: Workspace) -> None:
    found = _values(workspace, "disallowed-tools: Bash\npermission-mode: plan\n")
    expected = [
        ("agent-key-unknown", _unknown("disallowed-tools", "disallowedTools"), 4),
        ("agent-key-unknown", _unknown("permission-mode", "permissionMode"), 5),
    ]
    assert found == expected


def test_top_level_cache_ttl_points_inside_experimental(workspace: Workspace) -> None:
    message = 'unknown key "cacheTtl" (write it inside experimental); Claude Code ignores it'
    assert _values(workspace, "cacheTtl: 5m\n") == [("agent-key-unknown", message, 4)]


def test_unknown_experimental_sub_key_fires_at_experimental(workspace: Workspace) -> None:
    found = _values(workspace, "experimental:\n  cacheTtl: 1h\n  warm: true\n")
    assert found == [("agent-key-unknown", _unknown("experimental.warm", None), 4)]


def test_non_string_keys_are_not_reported(workspace: Workspace) -> None:
    assert _values(workspace, "null: 1\nyes: 1\non: 2\nexperimental:\n  1: x\n") == []


def test_long_alias_case_variants_are_case_warnings(workspace: Workspace) -> None:
    assert _values(workspace, "model: OPUSPLAN\n") == [("agent-value-case", 'model "OPUSPLAN": use the documented spelling "opusplan"', 4)]
    assert _values(workspace, "model: Sonnet[1M]\n") == [("agent-value-case", 'model "Sonnet[1M]": use the documented spelling "sonnet[1m]"', 4)]


def test_wrong_types_are_invalid(workspace: Workspace) -> None:
    cases = {
        "model: 5\n": "model 5 is not a model alias or a claude- model id, so the agent fails when it starts",
        "model:\n  a: b\n": 'model {"a": "b"} is not a model alias or a claude- model id, so the agent fails when it starts',
        "effort: 1.5\n": "effort 1.5 is not one of low, medium, high, xhigh, max or an integer; Claude Code ignores it",
        "maxTurns: true\n": "maxTurns true is not a positive integer; Claude Code ignores it",
        "tools:\n  Read: true\n": 'tools {"Read": true} is not a string or a list of strings',
        "color: [red]\n": 'color ["red"] is not one of red, blue, green, yellow, purple, orange, pink, cyan; Claude Code ignores it',
        "experimental:\n  cacheTtl: [5m]\n": 'experimental.cacheTtl ["5m"] is not one of 5m, 1h; Claude Code ignores it',
    }
    for frontmatter, message in cases.items():
        assert _values(workspace, frontmatter) == [("agent-value-invalid", message, 4)], frontmatter


def test_user_layer_agent_is_checked(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(workspace.home / ".claude" / "agents" / "helper.md", _file(VALID + "model: Opus\n"))
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [(finding.layer, finding.rule_id, finding.line) for finding in findings if finding.rule_id in AGENT_RULES]
    assert fired == [(Layer.USER, "agent-value-case", 4)]


def test_miscased_alias_is_a_case_warning(workspace: Workspace) -> None:
    assert _values(workspace, "model: Sonnet\n") == [("agent-value-case", 'model "Sonnet": use the documented spelling "sonnet"', 4)]


def test_valid_models_pass(workspace: Workspace) -> None:
    assert _values(workspace, "model: claude-haiku-4-5\n") == []


def test_long_context_alias_passes(workspace: Workspace) -> None:
    assert _values(workspace, "model: opus[1m]\n") == []


def test_capitalised_model_id_is_invalid(workspace: Workspace) -> None:
    message = 'model "Claude-Haiku-4-5" is not a model id (did you mean "claude-haiku-4-5"?), so the agent fails when it starts'
    assert _values(workspace, "model: Claude-Haiku-4-5\n") == [("agent-value-invalid", message, 4)]


def test_foreign_model_is_invalid(workspace: Workspace) -> None:
    message = 'model "gpt-4" is not a model alias or a claude- model id, so the agent fails when it starts'
    assert _values(workspace, "model: gpt-4\n") == [("agent-value-invalid", message, 4)]


def test_miscased_color_is_invalid_with_a_suggestion(workspace: Workspace) -> None:
    message = 'color "Red" is not valid (did you mean "red"?); Claude Code ignores it'
    assert _values(workspace, "color: Red\n") == [("agent-value-invalid", message, 4)]


def test_unknown_color_lists_the_allowed_values(workspace: Workspace) -> None:
    message = 'color "magenta" is not one of red, blue, green, yellow, purple, orange, pink, cyan; Claude Code ignores it'
    assert _values(workspace, "color: magenta\n") == [("agent-value-invalid", message, 4)]


def test_permission_mode_manual_passes(workspace: Workspace) -> None:
    assert _values(workspace, "permissionMode: manual\n") == []


def test_miscased_permission_mode_is_invalid(workspace: Workspace) -> None:
    message = 'permissionMode "acceptedits" is not valid (did you mean "acceptEdits"?); Claude Code ignores it'
    assert _values(workspace, "permissionMode: acceptedits\n") == [("agent-value-invalid", message, 4)]


def test_miscased_memory_isolation_and_cache_ttl_are_invalid(workspace: Workspace) -> None:
    found = _values(workspace, "memory: team\nisolation: Worktree\nexperimental:\n  cacheTtl: 5M\n")
    expected = [
        ("agent-value-invalid", 'memory "team" is not one of user, project, local; Claude Code ignores it', 4),
        ("agent-value-invalid", 'isolation "Worktree" is not valid (did you mean "worktree"?); Claude Code ignores it', 5),
        ("agent-value-invalid", 'experimental.cacheTtl "5M" is not valid (did you mean "5m"?); Claude Code ignores it', 6),
    ]
    assert found == expected


def test_miscased_effort_is_a_case_warning(workspace: Workspace) -> None:
    assert _values(workspace, "effort: HIGH\n") == [("agent-value-case", 'effort "HIGH": use the documented spelling "high"', 4)]


def test_integer_efforts_pass(workspace: Workspace) -> None:
    assert _values(workspace, "effort: 3\n") == []
    assert _values(workspace, 'effort: "3"\n') == []


def test_boolean_effort_is_invalid(workspace: Workspace) -> None:
    message = "effort true is not one of low, medium, high, xhigh, max or an integer; Claude Code ignores it"
    assert _values(workspace, "effort: true\n") == [("agent-value-invalid", message, 4)]


def test_max_turns_must_be_a_positive_integer(workspace: Workspace) -> None:
    assert _values(workspace, "maxTurns: 5\n") == []
    assert _values(workspace, "maxTurns: 0\n") == [("agent-value-invalid", "maxTurns 0 is not a positive integer; Claude Code ignores it", 4)]
    quoted = [("agent-value-invalid", 'maxTurns "5" is not a positive integer; Claude Code ignores it', 4)]
    assert _values(workspace, 'maxTurns: "5"\n') == quoted


def test_booleans_accept_what_claude_code_reads(workspace: Workspace) -> None:
    assert _values(workspace, "background: yes\nomitClaudeMd: false\n") == []
    expected = [("agent-value-invalid", 'background "maybe" is not true or false; Claude Code ignores it', 4)]
    assert _values(workspace, "background: maybe\n") == expected


def test_tool_lists_must_hold_strings(workspace: Workspace) -> None:
    assert _values(workspace, "tools: Read, Grep\nskills:\n  - demo\n") == []
    found = _values(workspace, "disallowedTools:\n  - Bash\n  - 5\n  - 6\nskills: 7\n")
    expected = [
        ("agent-value-invalid", "disallowedTools holds 5, which is not a string", 4),
        ("agent-value-invalid", "skills 7 is not a string or a list of strings", 8),
    ]
    assert found == expected


def test_initial_prompt_and_experimental_types(workspace: Workspace) -> None:
    found = _values(workspace, "initialPrompt: 5\nexperimental: 5m\n")
    expected = [
        ("agent-value-invalid", "initialPrompt 5 is not a string", 4),
        ("agent-value-invalid", 'experimental "5m" is not a mapping', 5),
    ]
    assert found == expected


def test_plugin_agent_skips_the_keys_claude_code_ignores_there(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "agents" / "lint.md", _file("name: lint\ndescription: Lint.\npermissionMode: bogus\ninitialPrompt: 5\ncolor: Red\n"))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [finding for finding in findings if finding.rule_id in AGENT_RULES]
    message = 'color "Red" is not valid (did you mean "red"?); Claude Code ignores it'
    assert [(finding.layer, finding.rule_id, finding.message, finding.line) for finding in fired] == [
        (Layer.PLUGIN, "agent-value-invalid", message, 6)
    ]


def _install_plugin_agent(workspace: Workspace, text: str) -> None:
    """Install a plugin whose one agent holds ``text`` and enable it in the fake home."""
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "agents" / "lint.md", text)
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))


def _plugin_agent_findings(workspace: Workspace, text: str) -> list[tuple[str, str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    _install_plugin_agent(workspace, text)
    return _run(workspace, PLUGIN_AGENT_RULES)


def test_ignored_in_plugin_keys_are_reported(workspace: Workspace) -> None:
    text = _file("name: lint\ndescription: Lints.\npermissionMode: plan\nhooks: {}\n")
    expected = "is ignored when a plugin's agent runs as a subagent"
    assert _plugin_agent_findings(workspace, text) == [
        ("agent-key-ignored-in-plugin", f"permissionMode {expected}", 4),
        ("agent-key-ignored-in-plugin", f"hooks {expected}", 5),
    ]


def test_ignored_in_plugin_keys_are_quiet_in_a_repo_agent(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / AGENT, _file(VALID + "permissionMode: plan\nhooks: {}\n"))
    assert _run(workspace, PLUGIN_AGENT_RULES) == []


def test_ignored_in_plugin_fires_on_empty_and_null_values(workspace: Workspace) -> None:
    text = _file("name: lint\ndescription: Lints.\nmcpServers:\ninitialPrompt: ''\n")
    expected = "is ignored when a plugin's agent runs as a subagent"
    assert _plugin_agent_findings(workspace, text) == [
        ("agent-key-ignored-in-plugin", f"mcpServers {expected}", 4),
        ("agent-key-ignored-in-plugin", f"initialPrompt {expected}", 5),
    ]


def test_skipped_plugin_agent_has_no_ignored_in_plugin_findings(workspace: Workspace) -> None:
    text = _file("name: lint\npermissionMode: plan\n")
    assert _plugin_agent_findings(workspace, text) == [("agent-skipped", "no description, so Claude Code skips the agent", 1)]


def test_ignored_in_plugin_needs_the_exact_key(workspace: Workspace) -> None:
    text = _file("name: lint\ndescription: Lints.\npermission-mode: plan\nHooks: {}\n")
    assert _plugin_agent_findings(workspace, text) == [
        ("agent-key-unknown", 'unknown key "permission-mode" (did you mean "permissionMode"?); Claude Code ignores it', 4),
        ("agent-key-unknown", 'unknown key "Hooks" (did you mean "hooks"?); Claude Code ignores it', 5),
    ]
