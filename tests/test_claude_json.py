"""Reading MCP servers from ``~/.claude.json`` without ever exposing the file's content."""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, McpScope, Rig
from support import Workspace, run_cli, symlink_or_skip, write

MARKER = "sk-ant-FAKE-SECRET"


def _write_claude_json(workspace: Workspace, data: Any) -> Path:
    return write(workspace.home / ".claude.json", json.dumps(data))


def _servers(rig: Rig) -> list[tuple[McpScope, str]]:
    return [(server.scope, server.name) for server in rig.user_mcp_servers]


def _outputs(capsys: pytest.CaptureFixture[str], target: Path, home: Path) -> list[str]:
    return [run_cli(capsys, target, home, output_format)[1] for output_format in ("json", "text")]


def test_user_scope_servers_are_read(workspace: Workspace) -> None:
    _write_claude_json(workspace, {"mcpServers": {"first": {"command": "a"}, "second": {"command": "b"}}})
    rig = discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)
    assert _servers(rig) == [(McpScope.USER, "first"), (McpScope.USER, "second")]
    assert rig.user_mcp_servers[0].config == {"command": "a"}
    assert rig.problems == ()


def _local_scope_check(workspace: Workspace, repo: Path, key: str) -> None:
    other = workspace.rig("other")
    projects = {
        other.as_posix(): {"mcpServers": {"elsewhere": {}}},
        key: {"mcpServers": {"alpha": {}, "beta": {}}},
    }
    _write_claude_json(workspace, {"mcpServers": {"global": {}}, "projects": projects})
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    assert _servers(rig) == [(McpScope.USER, "global"), (McpScope.LOCAL, "alpha"), (McpScope.LOCAL, "beta")]


def test_local_scope_matches_the_repo_key(workspace: Workspace) -> None:
    repo = workspace.rig()
    _local_scope_check(workspace, repo, repo.as_posix())


@pytest.mark.skipif(os.name != "nt", reason="drive letters and backslash separators are Windows paths")
def test_local_scope_matches_a_backslash_lower_case_drive_key(workspace: Workspace) -> None:
    repo = workspace.rig()
    raw = str(repo)
    _local_scope_check(workspace, repo, raw[0].lower() + raw[1:])


def test_home_target_reads_user_scope_only(workspace: Workspace) -> None:
    projects = {workspace.home.as_posix(): {"mcpServers": {"local": {}}}}
    _write_claude_json(workspace, {"mcpServers": {"global": {}}, "projects": projects})
    rig = discover(workspace.home, workspace.home, DEFAULT_WINDOW)
    assert _servers(rig) == [(McpScope.USER, "global")]


def test_missing_claude_json_is_silent(workspace: Workspace) -> None:
    rig = discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)
    assert rig.user_mcp_servers == ()
    assert rig.problems == ()


def test_invalid_claude_json_is_a_problem_without_content(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(workspace.home / ".claude.json", '{"oauthAccount": "' + MARKER + '",\n  broken')
    repo = workspace.rig()
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    assert rig.user_mcp_servers == ()
    assert len(rig.problems) == 1
    assert str(path) in rig.problems[0]
    assert MARKER not in "\n".join(rig.problems)
    for output in _outputs(capsys, repo, workspace.home):
        assert MARKER not in output


def test_unc_linked_claude_json_is_not_read(workspace: Workspace) -> None:
    target = r"\\server\share\.claude.json" if os.name == "nt" else "//server/share/.claude.json"
    link = workspace.home / ".claude.json"
    symlink_or_skip(link, target)
    rig = discover(workspace.rig(), workspace.home, DEFAULT_WINDOW)
    assert rig.user_mcp_servers == ()
    assert rig.problems == (f"{link}: links to a network path ({target}); not read",)


def test_claude_json_is_never_an_artifact(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    _write_claude_json(workspace, {"mcpServers": {"secret": {"env": {"API_KEY": MARKER}}}})
    repo = workspace.rig()
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    assert _servers(rig) == [(McpScope.USER, "secret")]
    assert all(artifact.path.name != ".claude.json" for artifact in rig.artifacts)
    for output in _outputs(capsys, repo, workspace.home):
        assert MARKER not in output


@pytest.mark.parametrize(
    "data",
    [
        {"mcpServers": ["not", "an", "object"], "projects": ["not", "an", "object"]},
        {"projects": {"{REPO}": "not an object"}},
    ],
    ids=["lists", "project-entry-string"],
)
def test_non_object_values_are_skipped(workspace: Workspace, data: dict[str, Any]) -> None:
    repo = workspace.rig()
    text = json.dumps(data).replace("{REPO}", repo.as_posix())
    write(workspace.home / ".claude.json", text)
    rig = discover(repo, workspace.home, DEFAULT_WINDOW)
    assert rig.user_mcp_servers == ()
    assert rig.problems == ()
