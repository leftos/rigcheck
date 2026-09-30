"""The hook structure rules: event names, handler shapes, matchers, if, once and timeouts."""

import json
from collections.abc import Mapping

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, write

COMMAND: Mapping[str, object] = {"type": "command", "command": "echo hi"}


def _frontmatter(name: str, *options: str) -> str:
    handler = "".join(f"          {option}\n" for option in ("type: command", "command: echo hi", *options))
    return f"---\nname: {name}\ndescription: Test.\nhooks:\n  Stop:\n    - hooks:\n        - {handler.lstrip()}---\n\nBody.\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _messages(workspace: Workspace, rule_id: str, events: Mapping[str, object]) -> list[str]:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.json", json.dumps({"hooks": events}, indent=2) + "\n")
    return sorted(message for message, _line in _run(workspace, rule_id))


def _group(matcher: str, *handlers: Mapping[str, object]) -> dict[str, object]:
    return {"matcher": matcher, "hooks": list(handlers or (COMMAND,))}


def test_event_case_variant_gets_did_you_mean(workspace: Workspace) -> None:
    events = {"pretooluse": [_group("Bash")], "Bogus": [_group("")], "Stop": [_group("")]}
    assert _messages(workspace, "hook-event-unknown", events) == [
        'event "Bogus" is not a Claude Code hook event, so its hooks never run',
        'event "pretooluse" is not a Claude Code hook event, so its hooks never run; did you mean "PreToolUse"?',
    ]


def test_event_line_points_at_event_key(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.json", '{\n  "hooks": {\n    "Stop": [],\n    "Bogus": []\n  }\n}\n')
    assert _run(workspace, "hook-event-unknown") == [('event "Bogus" is not a Claude Code hook event, so its hooks never run', 4)]


def test_handler_non_object_and_missing_hooks_list(workspace: Workspace) -> None:
    handlers = ["not a handler", {"command": "x"}, {"type": "command"}, {"type": "agent", "prompt": ""}, {"type": "webhook"}, {"type": "http"}]
    events = {"Stop": [{"matcher": "*"}, "not a group", {"hooks": handlers}], "PreToolUse": {"hooks": []}}
    assert _messages(workspace, "hook-handler-invalid", events) == [
        "PreToolUse hooks are not a list of matcher groups",
        "Stop hook has no type",
        'Stop hook has unknown type "webhook"',
        "Stop hook is not an object",
        'Stop hook of type "agent" has no prompt',
        'Stop hook of type "command" has no command',
        "Stop matcher group has no hooks list",
        "Stop matcher group is not an object",
    ]


def test_mcp_exact_ignores_full_tool_name(workspace: Workspace) -> None:
    groups = [_group("mcp__memory__create_entities"), _group("mcp__memory__.*"), _group("Bash|Edit"), _group("Read|mcp__brave-search")]
    events = {"PreToolUse": groups, "Stop": [_group("mcp__memory")]}
    assert _messages(workspace, "hook-matcher-mcp-exact", events) == [
        'matcher "mcp__brave-search" is compared as an exact string and matches no tool',
    ]


def test_unanchored_skips_invalid_regex_and_exact_lists(workspace: Workspace) -> None:
    groups = [_group("*"), _group("Edit|Write"), _group(".*"), _group("^Edit$"), _group("Edit.*")]
    events = {"PostToolUse": groups, "Stop": [_group("Edit.*")]}
    assert _messages(workspace, "hook-matcher-unanchored", events) == ['matcher "Edit.*" also matches NotebookEdit']


def test_if_list_and_and_operator(workspace: Workspace) -> None:
    events = {
        "PreToolUse": [_group("Bash", {**COMMAND, "if": ["Bash(git *)"]}, {**COMMAND, "if": "Bash(a) && Bash(b)"}, {**COMMAND, "if": "Bash(git *)"})],
        "Stop": [_group("", {**COMMAND, "if": "Bash(x) || Bash(y)"})],
    }
    one_rule = '"if" takes one permission rule; it has no &&, || or list form'
    assert _messages(workspace, "hook-if-ignored", events) == [
        '"if" on Stop is never evaluated, so this hook never runs',
        one_rule,
        one_rule,
        one_rule,
    ]


def test_once_in_command_frontmatter_is_silent(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "commands" / "deploy.md", _frontmatter("deploy", "once: true"))
    agent = write(repo / ".claude" / "agents" / "reviewer.md", _frontmatter("reviewer", "once: true"))
    found = [
        finding for finding in engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values()) if finding.rule_id == "hook-once-ignored"
    ]
    assert [(finding.path, finding.message) for finding in found] == [(agent, '"once" is honored only in skill frontmatter; here it is ignored')]


def test_timeout_bool_is_not_a_number(workspace: Workspace) -> None:
    groups = [_group("", {**COMMAND, "async": True, "timeout": True}), _group("", {**COMMAND, "async": True, "timeout": 5})]
    assert _messages(workspace, "hook-timeout-long", {"Stop": groups}) == ["timeout is not enforced on an async hook"]


def test_timeout_on_async(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "skills" / "g" / "SKILL.md", _frontmatter("g", "async: true", "timeout: 10"))
    events = {
        "PostToolUse": [_group("", {**COMMAND, "async": True, "timeout": 10}), _group("", {**COMMAND, "async": "true", "timeout": 10})],
        "SessionEnd": [_group("", {**COMMAND, "timeout": 5}), _group("", {**COMMAND, "timeout": 1.5})],
        "UserPromptSubmit": [_group("", {**COMMAND, "timeout": 60}), _group("", {**COMMAND, "timeout": 30})],
    }
    assert _messages(workspace, "hook-timeout-long", events) == [
        "SessionEnd hooks share a 1.5 s budget, so a 5 s timeout is never reached",
        "a stuck UserPromptSubmit hook stalls the session for up to 60 s; the default is 30 s",
        "timeout is not enforced on an async hook",
        "timeout is not enforced on an async hook",
    ]


def test_one_finding_per_group_for_matchers(workspace: Workspace) -> None:
    events = {"PreToolUse": [_group("mcp__memory", COMMAND, COMMAND, COMMAND)]}
    assert _messages(workspace, "hook-matcher-mcp-exact", events) == ['matcher "mcp__memory" is compared as an exact string and matches no tool']


def test_if_on_unknown_event_left_to_event_unknown(workspace: Workspace) -> None:
    events = {"pretooluse": [_group("Bash", {**COMMAND, "if": "Bash(a) && Bash(b)"})], "Setp": [_group("", {**COMMAND, "if": "Bash(a)"})]}
    assert _messages(workspace, "hook-if-ignored", events) == ['"if" takes one permission rule; it has no &&, || or list form']


def _timeout_rules(workspace: Workspace, timeout: str) -> list[str]:
    repo = workspace.rig()
    handler = f'{{"type": "command", "command": "echo hi", "timeout": {timeout}}}'
    write(repo / ".claude" / "settings.json", f'{{"hooks": {{"UserPromptSubmit": [{{"hooks": [{handler}]}}]}}}}\n')
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [finding.rule_id for finding in findings if finding.rule_id in {"hook-timeout-long", "internal-error"}]


def test_timeout_huge_int_is_skipped(workspace: Workspace) -> None:
    assert _timeout_rules(workspace, "1" + "0" * 400) == []


def test_timeout_infinity_is_skipped(workspace: Workspace) -> None:
    assert _timeout_rules(workspace, "Infinity") == []
