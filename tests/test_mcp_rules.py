"""The MCP rules: server types, project-dir references without a default, and credential references."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, write


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _repo_mcp(workspace: Workspace, rule_id: str, servers: Mapping[str, object]) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".mcp.json", json.dumps({"mcpServers": servers}))
    return _run(workspace, rule_id)


def _messages(workspace: Workspace, rule_id: str, servers: Mapping[str, object]) -> list[str]:
    return [message for message, _line in _repo_mcp(workspace, rule_id, servers)]


def _plugin(workspace: Workspace) -> Path:
    """Install an enabled plugin ``demo@local`` in the fake home and return its install folder."""
    install = workspace.home / ".claude" / "plugins" / "cache" / "demo"
    write(workspace.home / ".claude" / "settings.json", '{"enabledPlugins": {"demo@local": true}}\n')
    installed = {"version": 2, "plugins": {"demo@local": [{"scope": "user", "installPath": install.as_posix()}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    return install


def test_type_invalid_reports_sdk(workspace: Workspace) -> None:
    expected = ["server `docs` has type `sdk`, which Claude Code skips outside an Agent SDK host"]
    assert _messages(workspace, "mcp-type-invalid", {"docs": {"type": "sdk", "command": "node"}}) == expected


def test_type_invalid_reports_unknown_value(workspace: Workspace) -> None:
    expected = ["server `docs` has unknown type `grpc`; Claude Code accepts stdio, http (streamable-http), sse and ws"]
    assert _messages(workspace, "mcp-type-invalid", {"docs": {"type": "grpc", "command": "node"}}) == expected


def test_type_invalid_reports_non_string(workspace: Workspace) -> None:
    expected = ["server `docs` has a type that is not a string"]
    assert _messages(workspace, "mcp-type-invalid", {"docs": {"type": 3, "command": "node"}}) == expected


@pytest.mark.parametrize("value", ["stdio", "http", "streamable-http", "sse", "ws"])
def test_type_valid_values_silent(workspace: Workspace, value: str) -> None:
    assert _repo_mcp(workspace, "mcp-type-invalid", {"docs": {"type": value, "command": "node"}}) == []


def test_type_absent_silent(workspace: Workspace) -> None:
    assert _repo_mcp(workspace, "mcp-type-invalid", {"docs": {"command": "node"}}) == []


def test_type_invalid_line_is_type_key(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".mcp.json", '{\n  "mcpServers": {\n    "docs": {\n      "command": "node",\n      "type": "sdk"\n    }\n  }\n}\n')
    assert [line for _message, line in _run(workspace, "mcp-type-invalid")] == [5]


def test_type_invalid_reads_plugin_manifest(workspace: Workspace) -> None:
    manifest = {"name": "demo", "mcpServers": {"docs": {"type": "sdk", "command": "node"}}}
    write(_plugin(workspace) / ".claude-plugin" / "plugin.json", json.dumps(manifest))
    messages = [message for message, _line in _run(workspace, "mcp-type-invalid")]
    assert messages == ["server `docs` has type `sdk`, which Claude Code skips outside an Agent SDK host"]


def test_project_dir_reports_args_without_default(workspace: Workspace) -> None:
    servers = {"tool": {"command": "node", "args": ["--flag", "${CLAUDE_PROJECT_DIR}/server.js"]}}
    expected = ["server `tool` references ${CLAUDE_PROJECT_DIR} in args with no default"]
    assert _messages(workspace, "mcp-project-dir-no-default", servers) == expected


def test_project_dir_reports_command_without_default(workspace: Workspace) -> None:
    servers = {"tool": {"command": "${CLAUDE_PROJECT_DIR}/bin/server", "args": ["${CLAUDE_PROJECT_DIR}/x"]}}
    expected = ["server `tool` references ${CLAUDE_PROJECT_DIR} in command with no default"]
    assert _messages(workspace, "mcp-project-dir-no-default", servers) == expected


def test_project_dir_default_silent(workspace: Workspace) -> None:
    servers = {"tool": {"command": "${CLAUDE_PROJECT_DIR:-.}/bin/server", "args": ["${CLAUDE_PROJECT_DIR:-.}/server.js"]}}
    assert _repo_mcp(workspace, "mcp-project-dir-no-default", servers) == []


def test_project_dir_plugin_file_silent(workspace: Workspace) -> None:
    servers = {"mcpServers": {"tool": {"command": "node", "args": ["${CLAUDE_PROJECT_DIR}/server.js"]}}}
    write(_plugin(workspace) / ".mcp.json", json.dumps(servers))
    assert _run(workspace, "mcp-project-dir-no-default") == []


def test_project_dir_bare_dollar_silent(workspace: Workspace) -> None:
    servers = {"tool": {"command": "node", "args": ["$CLAUDE_PROJECT_DIR/x"]}}
    assert _repo_mcp(workspace, "mcp-project-dir-no-default", servers) == []


def _remote(variable: str) -> dict[str, object]:
    return {"api": {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": f"Bearer ${{{variable}}}"}}}


def test_credential_reports_header(workspace: Workspace) -> None:
    expected = [
        "server `api` references `ANTHROPIC_AUTH_TOKEN` in its headers; Claude Code reads that credential as empty there, so the server gets none"
    ]
    assert _messages(workspace, "mcp-credential-var-remote", _remote("ANTHROPIC_AUTH_TOKEN")) == expected


def test_credential_reports_url(workspace: Workspace) -> None:
    servers = {"api": {"type": "sse", "url": "https://x.example/mcp?k=${ANTHROPIC_API_KEY}"}}
    expected = ["server `api` references `ANTHROPIC_API_KEY` in its url; Claude Code reads that credential as empty there, so the server gets none"]
    assert _messages(workspace, "mcp-credential-var-remote", servers) == expected


def test_credential_untyped_url_is_remote(workspace: Workspace) -> None:
    servers = {"api": {"url": "https://example.com/mcp", "headers": {"X-Key": "${ANTHROPIC_API_KEY:-none}"}}}
    assert len(_repo_mcp(workspace, "mcp-credential-var-remote", servers)) == 1


def test_credential_stdio_silent(workspace: Workspace) -> None:
    servers = {"api": {"type": "stdio", "command": "node", "args": ["--key", "${ANTHROPIC_API_KEY}"]}}
    assert _repo_mcp(workspace, "mcp-credential-var-remote", servers) == []


@pytest.mark.parametrize(
    ("variable", "fires"),
    [
        ("ANTHROPIC_API_KEY", True),
        ("ANTHROPIC_AUTH_TOKEN", True),
        ("AWS_BEARER_TOKEN_BEDROCK", True),
        ("AWS_SECRET_ACCESS_KEY", True),
        ("AWS_ACCESS_KEY_ID", True),
        ("HTTPS_PROXY", True),
        ("NPM_TOKEN", True),
        ("ANTHROPIC_BASE_URL", False),
        ("GITHUB_TOKEN", False),
        ("AWS_REGION", False),
    ],
)
def test_credential_names(workspace: Workspace, variable: str, *, fires: bool) -> None:
    assert bool(_repo_mcp(workspace, "mcp-credential-var-remote", _remote(variable))) is fires


def test_credential_message_omits_value(workspace: Workspace) -> None:
    messages = _messages(workspace, "mcp-credential-var-remote", _remote("ANTHROPIC_API_KEY"))
    assert messages
    assert all("Bearer" not in message for message in messages)
