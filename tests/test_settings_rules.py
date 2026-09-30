"""The settings rules: config files that do not load, and settings values the schema rejects."""

import json
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, write

BOOLEAN_KEYS = (
    "allowManagedHooksOnly",
    "allowManagedPermissionRulesOnly",
    "autoMemoryEnabled",
    "disableAllHooks",
    "enableAllProjectMcpServers",
    "fastMode",
    "includeCoAuthoredBy",
    "includeGitInstructions",
    "respectGitignore",
    "spinnerTipsEnabled",
)


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _settings(workspace: Workspace, rule_id: str, text: str, *, in_home: bool = False) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write((workspace.home if in_home else repo) / ".claude" / "settings.json", text)
    return _run(workspace, rule_id)


def _plugin(workspace: Workspace) -> Path:
    """Install an enabled plugin ``demo@local`` in the fake home and return its install folder."""
    install = workspace.home / ".claude" / "plugins" / "cache" / "demo"
    write(workspace.home / ".claude" / "settings.json", '{"enabledPlugins": {"demo@local": true}}\n')
    installed = {"version": 2, "plugins": {"demo@local": [{"scope": "user", "installPath": install.as_posix()}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    return install


def test_config_json_invalid_names_problem_and_line(workspace: Workspace) -> None:
    expected = [("settings.json does not load as JSON: line 2 column 18: Illegal trailing comma before end of object", 2)]
    assert _settings(workspace, "config-json-invalid", '{\n  "verbose": true,\n}\n') == expected


def test_config_json_invalid_plugin_hooks(workspace: Workspace) -> None:
    write(_plugin(workspace) / "hooks" / "hooks.json", '{"hooks": \n')
    assert _run(workspace, "config-json-invalid") == [("hooks.json does not load as JSON: line 2 column 1: Expecting value", 2)]


def test_config_json_invalid_plugin_manifest(workspace: Workspace) -> None:
    write(_plugin(workspace) / ".claude-plugin" / "plugin.json", '{"name": "demo"\n"version": "1"}\n')
    assert _run(workspace, "config-json-invalid") == [("plugin.json does not load as JSON: line 2 column 1: Expecting ',' delimiter", 2)]


def test_config_json_invalid_repo_mcp(workspace: Workspace) -> None:
    write(workspace.rig() / ".mcp.json", "{'mcpServers': {}}\n")
    expected = [(".mcp.json does not load as JSON: line 1 column 2: Expecting property name enclosed in double quotes", 1)]
    assert _run(workspace, "config-json-invalid") == expected


@pytest.mark.parametrize("text", ["", "  \n\t\n", "﻿\n"])
def test_config_json_invalid_silent_on_empty_file(workspace: Workspace, text: str) -> None:
    assert _settings(workspace, "config-json-invalid", text) == []


@pytest.mark.parametrize(
    ("text", "held"),
    [("[]\n", "an array"), ("null\n", "null"), ('"x"\n', "a string"), ("1.5\n", "a number"), ("true\n", "a boolean")],
)
def test_config_json_invalid_non_object(workspace: Workspace, text: str, held: str) -> None:
    expected = [(f"settings.json holds {held} where Claude Code expects an object", None)]
    assert _settings(workspace, "config-json-invalid", text) == expected


def test_config_json_invalid_on_nan(workspace: Workspace) -> None:
    expected = [("settings.json does not load as JSON: line 2 column 24: NaN is not valid JSON", 2)]
    assert _settings(workspace, "config-json-invalid", '{\n  "cleanupPeriodDays": NaN\n}\n') == expected


def test_config_json_invalid_never_echoes_content(workspace: Workspace) -> None:
    findings = _settings(workspace, "config-json-invalid", '{"env": {"TOKEN": "sk-secret-123"}, oops}\n')
    assert len(findings) == 1
    assert "sk-secret-123" not in findings[0][0]


def test_schema_error_never_echoes_value(workspace: Workspace) -> None:
    findings = _settings(workspace, "settings-schema-invalid", '{\n  "env": {\n    "TOKEN": ["sk-secret-123"]\n  }\n}\n')
    assert findings == [("env.TOKEN: must be string", 3)]


def test_schema_enum_lists_allowed_values_from_schema(workspace: Workspace) -> None:
    text = '{\n  "permissions": {\n    "defaultMode": "sometimes"\n  }\n}\n'
    [(message, line)] = _settings(workspace, "settings-schema-invalid", text)
    assert message.startswith('permissions.defaultMode: must be one of "acceptEdits", "bypassPermissions"')
    assert "sometimes" not in message
    assert line == 3


def test_schema_errors_capped_at_eight(workspace: Workspace) -> None:
    text = "{\n" + ",\n".join(f'  "{key}": "yes"' for key in BOOLEAN_KEYS) + "\n}\n"
    findings = _settings(workspace, "settings-schema-invalid", text)
    expected = [(f"{key}: must be boolean", number) for number, key in enumerate(BOOLEAN_KEYS[:8], start=2)]
    expected[-1] = ("includeGitInstructions: must be boolean (and 2 more)", 9)
    assert findings == expected


def test_schema_errors_sorted_by_numeric_index(workspace: Workspace) -> None:
    text = '{\n  "permissions": {\n    "additionalDirectories": [' + ", ".join(str(number) for number in range(12)) + "]\n  }\n}\n"
    expected = [(f"permissions.additionalDirectories[{index}]: must be string", 3) for index in range(8)]
    expected[-1] = ("permissions.additionalDirectories[7]: must be string (and 4 more)", 3)
    assert _settings(workspace, "settings-schema-invalid", text) == expected


@pytest.mark.parametrize(
    ("env", "message", "line"),
    [
        ('{\n    "GOOD": "1",\n    "lower_x": "2"\n  }', 'env: key "lower_x" does not match the expected form', 4),
        ('{\n    "lower_x": "1",\n    "GOOD": "2",\n    "bad-y": "3"\n  }', 'env: keys "lower_x", "bad-y" do not match the expected form', 3),
    ],
)
def test_property_names_error_names_the_key(workspace: Workspace, env: str, message: str, line: int) -> None:
    assert _settings(workspace, "settings-schema-invalid", '{\n  "env": ' + env + "\n}\n") == [(message, line)]


def test_schema_hooks_errors_left_to_hook_rules(workspace: Workspace) -> None:
    text = '{\n  "hooks": {"Stop": "not a list", "Nope": 1},\n  "respectGitignore": "yes"\n}\n'
    assert _settings(workspace, "settings-schema-invalid", text) == [("respectGitignore: must be boolean", 3)]


def test_schema_unknown_top_level_key_is_allowed(workspace: Workspace) -> None:
    text = '{\n  "myOwnKey": 1,\n  "respectGitignore": "yes"\n}\n'
    assert _settings(workspace, "settings-schema-invalid", text) == [("respectGitignore: must be boolean", 3)]


def test_schema_line_points_at_key(workspace: Workspace) -> None:
    text = '{\n  "permissions": {\n    "allow": [],\n    "bogus": 1,\n    "other": 2\n  }\n}\n'
    assert _settings(workspace, "settings-schema-invalid", text) == [('permissions: unknown keys "bogus", "other"', 4)]


def test_schema_line_of_array_item_falls_back_to_its_key(workspace: Workspace) -> None:
    text = '{\n  "permissions": {\n    "additionalDirectories": [\n      "../shared",\n      7\n    ]\n  }\n}\n'
    assert _settings(workspace, "settings-schema-invalid", text) == [("permissions.additionalDirectories[1]: must be string", 3)]


@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        ('{\n    "allow": ["Bash(echo (a))", "NewTool(x)"],\n    "deny": [7],\n    "ask": [""]\n  }', []),
        ('{\n    "allow": "Bash"\n  }', [("permissions.allow: must be array", 3)]),
    ],
)
def test_permission_rule_strings_left_to_permission_rules(workspace: Workspace, permissions: str, expected: list[tuple[str, int]]) -> None:
    assert _settings(workspace, "settings-schema-invalid", '{\n  "permissions": ' + permissions + "\n}\n") == expected


def test_user_layer_settings_checked(workspace: Workspace) -> None:
    findings = _settings(workspace, "settings-schema-invalid", '{"respectGitignore": "yes"}\n', in_home=True)
    assert findings == [("respectGitignore: must be boolean", 1)]


def test_settings_local_checked(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.local.json", '{"respectGitignore": 0}\n')
    assert _run(workspace, "settings-schema-invalid") == [("respectGitignore: must be boolean", 1)]


def test_non_object_left_to_config_json_invalid(workspace: Workspace) -> None:
    assert _settings(workspace, "settings-schema-invalid", "[]\n") == []
    assert _run(workspace, "config-json-invalid") == [("settings.json holds an array where Claude Code expects an object", None)]
