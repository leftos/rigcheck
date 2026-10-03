"""The MCP rules: server types, project-dir references without a default, and credential references."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, git_add, write


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
        "server `api` references `ANTHROPIC_AUTH_TOKEN` in its headers; Claude Code reads that variable as empty there, so the server gets none"
    ]
    assert _messages(workspace, "mcp-credential-var-remote", _remote("ANTHROPIC_AUTH_TOKEN")) == expected


def test_credential_reports_url(workspace: Workspace) -> None:
    servers = {"api": {"type": "sse", "url": "https://x.example/mcp?k=${ANTHROPIC_API_KEY}"}}
    expected = ["server `api` references `ANTHROPIC_API_KEY` in its url; Claude Code reads that variable as empty there, so the server gets none"]
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
        ("HTTPS_PROXY", True),
        ("NPM_TOKEN", True),
        ("CLAUDE_CODE_OAUTH_TOKEN", True),
        ("GOOGLE_APPLICATION_CREDENTIALS", True),
        ("MCP_CLIENT_SECRET", True),
        ("npm_token", True),
        ("INPUT_NPM_TOKEN", True),
        ("INPUT_CLAUDE_CODE_OAUTH_TOKEN", True),
        ("INPUT_MCP_CLIENT_SECRET", True),
        ("CLAUDE_CODE_SESSION_NAME", True),
        ("CLAUDE_BG_BACKEND", True),
        ("INPUT_CLAUDE_BG_RV_AUTH", False),
        ("CARGO_REGISTRIES_MY_TOKEN", True),
        ("OTEL_EXPORTER_OTLP_HEADERS", True),
        ("GIT_CONFIG_VALUE_0", True),
        ("ORG_GRADLE_PROJECT_PASSWORD", True),
        ("BUNDLE_GEMS__EXAMPLE__COM", True),
        ("AWS_ACCESS_KEY_ID", False),
        ("ANTHROPIC_FOO_KEY", False),
        ("ANTHROPIC_BASE_URL", False),
        ("GITHUB_TOKEN", False),
        ("GH_TOKEN", False),
        ("HF_TOKEN", False),
        ("AWS_REGION", False),
        ("ORG_GRADLE_PROJECT_VERSION", False),
        ("BUNDLE_PATH__VENDOR", False),
        ("GIT_CONFIG_COUNT", False),
    ],
)
def test_credential_names(workspace: Workspace, variable: str, *, fires: bool) -> None:
    assert bool(_repo_mcp(workspace, "mcp-credential-var-remote", _remote(variable))) is fires


def test_credential_message_omits_value(workspace: Workspace) -> None:
    messages = _messages(workspace, "mcp-credential-var-remote", _remote("ANTHROPIC_API_KEY"))
    assert messages
    assert all("Bearer" not in message for message in messages)


def test_credential_case_variants_one_finding(workspace: Workspace) -> None:
    servers = {"api": {"type": "http", "url": "https://x.test/mcp?a=${otel_x}&b=${OTEL_X}"}}
    findings = _repo_mcp(workspace, "mcp-credential-var-remote", servers)
    assert len(findings) == 1
    assert "`otel_x`" in findings[0][0]


def _stdio_args(variable: str) -> dict[str, object]:
    """Return a stdio server whose ``args`` reference ``variable``."""
    return {"api": {"command": "node", "args": ["--key", f"${{{variable}}}"]}}


def _stdio_message(variable: str, field: str) -> str:
    """Return the finding message for ``variable`` in ``field`` of server ``api``."""
    return (
        f"server `api` references `{variable}` in its {field}; "
        "Claude Code reads that variable as empty in a stdio server whenever it is set, so the server never gets its value"
    )


def test_stdio_credential_reports_env(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    body = (
        "{\n"
        '  "mcpServers": {\n'
        '    "api": {\n'
        '      "command": "node",\n'
        '      "env": {\n'
        '        "A": "x",\n'
        '        "KEY": "${MCP_CLIENT_SECRET}"\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    write(repo / ".mcp.json", body)
    assert _run(workspace, "mcp-credential-var-stdio") == [(_stdio_message("MCP_CLIENT_SECRET", "env"), 7)]


def test_stdio_credential_reports_args(workspace: Workspace) -> None:
    assert _messages(workspace, "mcp-credential-var-stdio", _stdio_args("MCP_CLIENT_SECRET")) == [_stdio_message("MCP_CLIENT_SECRET", "args")]


def test_stdio_credential_reports_command(workspace: Workspace) -> None:
    servers = {"api": {"command": "run-${CLAUDE_CODE_OAUTH_TOKEN}"}}
    assert _messages(workspace, "mcp-credential-var-stdio", servers) == [_stdio_message("CLAUDE_CODE_OAUTH_TOKEN", "command")]


def test_stdio_credential_default_form_counts(workspace: Workspace) -> None:
    servers = {"api": {"command": "node", "args": ["--key", "${OTEL_X:-D}"]}}
    assert _messages(workspace, "mcp-credential-var-stdio", servers) == [_stdio_message("OTEL_X", "args")]


def test_stdio_credential_lowercase_counts(workspace: Workspace) -> None:
    assert _messages(workspace, "mcp-credential-var-stdio", _stdio_args("otel_foo")) == [_stdio_message("otel_foo", "args")]


def test_stdio_credential_case_variants_one_finding(workspace: Workspace) -> None:
    servers = {"api": {"command": "node", "args": ["${otel_x}", "${OTEL_X}"]}}
    findings = _repo_mcp(workspace, "mcp-credential-var-stdio", servers)
    assert len(findings) == 1
    assert "`otel_x`" in findings[0][0]


def test_stdio_credential_remote_server_silent(workspace: Workspace) -> None:
    servers = {"api": {"type": "http", "url": "https://x.test/mcp?k=${OTEL_X}"}}
    assert _repo_mcp(workspace, "mcp-credential-var-stdio", servers) == []
    assert len(_repo_mcp(workspace, "mcp-credential-var-remote", servers)) == 1


def test_stdio_credential_untyped_server_is_stdio(workspace: Workspace) -> None:
    servers = {"api": {"command": "node", "args": ["--key", "${MCP_CLIENT_SECRET}"]}}
    assert len(_repo_mcp(workspace, "mcp-credential-var-stdio", servers)) == 1


def test_stdio_credential_skips_sdk_and_unknown_type(workspace: Workspace) -> None:
    for kind in ("sdk", "foo", 3):
        servers = {"api": {"type": kind, "command": "node", "args": ["${MCP_CLIENT_SECRET}"]}}
        assert _repo_mcp(workspace, "mcp-credential-var-stdio", servers) == []


@pytest.mark.parametrize(
    ("variable", "fires"),
    [
        ("CLAUDE_CODE_OAUTH_TOKEN", True),
        ("CLAUDE_CODE_SESSION_NAME", True),
        ("MCP_CLIENT_SECRET", True),
        ("INPUT_MCP_CLIENT_SECRET", True),
        ("CLAUDE_CODE_MEMORY_API_TOKEN", True),
        ("INPUT_OTEL_Y", True),
        ("CLAUDE_CODE_ARTIFACTS_FOO_BASE_URL", True),
        ("ANTHROPIC_API_KEY", False),
        ("ANTHROPIC_AUTH_TOKEN", False),
        ("ANTHROPIC_CUSTOM_HEADERS", False),
        ("NPM_TOKEN", False),
        ("INPUT_NPM_TOKEN", False),
        ("AWS_SECRET_ACCESS_KEY", False),
        ("INPUT_CLAUDE_CODE_OAUTH_TOKEN", False),
        ("INPUT_CLAUDE_CODE_SLACK_TAG_TOKEN", False),
        ("GITHUB_TOKEN", False),
    ],
)
def test_stdio_credential_names(workspace: Workspace, variable: str, *, fires: bool) -> None:
    assert bool(_repo_mcp(workspace, "mcp-credential-var-stdio", _stdio_args(variable))) is fires


def test_stdio_credential_message_omits_value(workspace: Workspace) -> None:
    servers = {"api": {"command": "node", "args": ["--key", "${MCP_CLIENT_SECRET:-hunter2}"]}}
    messages = _messages(workspace, "mcp-credential-var-stdio", servers)
    assert messages
    assert all("hunter2" not in message for message in messages)


def _token() -> str:
    """Return a pattern-valid Anthropic key built from pieces, so no committed file holds one."""
    return "sk-" + "ant-" + "api03-" + "a1B2c3D4" * 4


def _kind(token: str) -> str:
    return f"Anthropic API key literal ({len(token)} characters)"


def _write_mcp(workspace: Workspace, servers: Mapping[str, object], *, tracked: bool) -> None:
    """Write a project ``.mcp.json`` beside an instruction file, tracking it when ``tracked``."""
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".mcp.json", json.dumps({"mcpServers": servers}, indent=2))
    if tracked:
        git_add(repo, [".mcp.json"])


def _tracked_mcp(workspace: Workspace, rule_id: str, servers: Mapping[str, object]) -> list[tuple[str, int | None]]:
    """Write a git-tracked project ``.mcp.json`` and return one rule's findings."""
    _write_mcp(workspace, servers, tracked=True)
    return _run(workspace, rule_id)


def _write_home_json(workspace: Workspace, data: object) -> None:
    write(workspace.home / ".claude.json", json.dumps(data))


def test_secret_literal_reports_each_field(workspace: Workspace) -> None:
    token = _token()
    body = "\n".join(
        [
            "{",
            '  "mcpServers": {',
            '    "api": {',
            '      "type": "http",',
            '      "headers": {"Authorization": "Bearer ' + token + '"},',
            '      "url": "https://x.test/mcp?key=' + token + '",',
            '      "env": {"API_KEY": "' + token + '"},',
            '      "args": ["--key=' + token + '"]',
            "    }",
            "  }",
            "}",
            "",
        ]
    )
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".mcp.json", body)
    git_add(repo, [".mcp.json"])
    kind = _kind(token)
    assert _run(workspace, "mcp-secret-literal") == [
        (f"{kind} in `headers.Authorization` of server `api`; the value is not shown", 5),
        (f"{kind} in `url` of server `api`; the value is not shown", 6),
        (f"{kind} in `env.API_KEY` of server `api`; the value is not shown", 7),
        (f"{kind} in `args` of server `api`; the value is not shown", 8),
    ]


def test_secret_literal_message_hides_value(workspace: Workspace) -> None:
    token = _token()
    servers = {"api": {"type": "http", "url": "https://x.test/mcp", "env": {"API_KEY": token}}}
    messages = [message for message, _line in _tracked_mcp(workspace, "mcp-secret-literal", servers)]
    assert messages
    assert all(token not in message and token[7:] not in message for message in messages)


def test_secret_literal_skips_untracked_repo_file(workspace: Workspace) -> None:
    servers = {"api": {"type": "http", "url": "https://x.test/mcp", "env": {"API_KEY": _token()}}}
    assert _repo_mcp(workspace, "mcp-secret-literal", servers) == []


def test_secret_literal_skips_references_and_placeholders(workspace: Workspace) -> None:
    servers = {
        "api": {
            "type": "http",
            "url": "https://x.test/mcp",
            "headers": {"Authorization": "Bearer ${API_KEY}"},
            "env": {"A": "${API_KEY}", "B": "${API_KEY:-}"},
            "args": ["--key=" + "sk-ant-" + "x" * 30],
        }
    }
    assert _tracked_mcp(workspace, "mcp-secret-literal", servers) == []


def test_secret_literal_reports_default_literal(workspace: Workspace) -> None:
    token = _token()
    servers = {"api": {"type": "http", "url": "https://x.test/mcp", "env": {"API_KEY": "${API_KEY:-" + token + "}"}}}
    assert _tracked_mcp(workspace, "mcp-secret-literal", servers) == [(f"{_kind(token)} in `env.API_KEY` of server `api`; the value is not shown", 7)]


def test_secret_literal_reports_plugin_config(workspace: Workspace) -> None:
    token = _token()
    install = _plugin(workspace)
    file_servers = {"mcpServers": {"api": {"type": "http", "url": "https://x.test/mcp", "env": {"API_KEY": token}}}}
    write(install / ".mcp.json", json.dumps(file_servers))
    assert len(_run(workspace, "mcp-secret-literal")) == 1
    (install / ".mcp.json").unlink()
    manifest = {"name": "demo", "mcpServers": {"api": {"command": "node", "env": {"API_KEY": token}}}}
    write(install / ".claude-plugin" / "plugin.json", json.dumps(manifest))
    assert len(_run(workspace, "mcp-secret-literal")) == 1


def test_secret_literal_ignores_claude_json(workspace: Workspace) -> None:
    _write_home_json(workspace, {"mcpServers": {"api": {"command": "node", "env": {"API_KEY": _token()}}}})
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    assert _run(workspace, "mcp-secret-literal") == []


def test_server_conflict_user_scope(workspace: Workspace) -> None:
    _write_mcp(workspace, {"docs": {"command": "node", "args": ["docs-server.js"]}}, tracked=False)
    _write_home_json(workspace, {"mcpServers": {"docs": {"type": "http", "url": "https://docs.example.test/mcp"}}})
    assert _run(workspace, "mcp-server-conflict") == [
        (
            "server `docs` is also defined in user scope in ~/.claude.json with a different endpoint; Claude Code loads the project scope definition",
            3,
        )
    ]


def test_server_conflict_local_scope_wins(workspace: Workspace) -> None:
    _write_mcp(workspace, {"docs": {"command": "node", "args": ["docs-server.js"]}}, tracked=False)
    repo = workspace.rig()
    projects = {repo.as_posix(): {"mcpServers": {"docs": {"command": "node", "args": ["local.js"]}}}}
    _write_home_json(workspace, {"projects": projects})
    assert [message for message, _line in _run(workspace, "mcp-server-conflict")] == [
        "server `docs` is also defined in local scope in ~/.claude.json with a different endpoint; Claude Code loads the local scope definition"
    ]
    home = {"mcpServers": {"docs": {"type": "http", "url": "https://docs.example.test/mcp"}}, "projects": projects}
    _write_home_json(workspace, home)
    assert [message for message, _line in _run(workspace, "mcp-server-conflict")] == [
        "server `docs` is also defined in local and user scope in ~/.claude.json with a different endpoint; "
        "Claude Code loads the local scope definition"
    ]


def test_server_conflict_same_endpoint(workspace: Workspace) -> None:
    servers = {
        "docs": {"command": "node", "args": ["docs-server.js"], "env": {"LEVEL": "debug"}},
        "api": {"url": "https://x.test/mcp", "headers": {"X-A": "1"}},
    }
    _write_mcp(workspace, servers, tracked=False)
    home = {
        "mcpServers": {
            "docs": {"command": "node", "args": ["docs-server.js"]},
            "api": {"url": "https://x.test/mcp", "headers": {"X-B": "2"}},
        }
    }
    _write_home_json(workspace, home)
    assert _run(workspace, "mcp-server-conflict") == []


def test_server_conflict_unexpanded_reference(workspace: Workspace) -> None:
    _write_mcp(workspace, {"tool": {"command": "${HOME}/bin/x"}}, tracked=False)
    _write_home_json(workspace, {"mcpServers": {"tool": {"command": workspace.home.as_posix() + "/bin/x"}}})
    assert len(_run(workspace, "mcp-server-conflict")) == 1


def test_server_conflict_ignores_plugins(workspace: Workspace) -> None:
    _write_mcp(workspace, {"docs": {"command": "node", "args": ["docs-server.js"]}}, tracked=False)
    plugin = {"mcpServers": {"docs": {"type": "http", "url": "https://docs.example.test/mcp"}}}
    write(_plugin(workspace) / ".mcp.json", json.dumps(plugin))
    assert _run(workspace, "mcp-server-conflict") == []
    _write_home_json(workspace, {"mcpServers": {"docs": {"command": "node", "args": ["docs-server.js"]}}})
    assert _run(workspace, "mcp-server-conflict") == []


def test_server_conflict_message_hides_home_config(workspace: Workspace) -> None:
    _write_mcp(workspace, {"docs": {"command": "node", "args": ["docs-server.js"]}}, tracked=False)
    url = "https://docs.example.test/mcp"
    _write_home_json(workspace, {"mcpServers": {"docs": {"type": "http", "url": url}}})
    findings = _run(workspace, "mcp-server-conflict")
    assert findings
    assert all(url not in message for message, _line in findings)


def test_secret_literal_one_finding_per_args(workspace: Workspace) -> None:
    token = _token()
    servers = {"api": {"command": "node", "args": ["--a=" + token, "--b=" + token]}}
    findings = _tracked_mcp(workspace, "mcp-secret-literal", servers)
    assert len(findings) == 1
    assert "`args`" in findings[0][0]


def test_secret_literal_reports_command(workspace: Workspace) -> None:
    token = _token()
    servers = {"api": {"command": "npx -y srv --token " + token, "args": ["srv.js"]}}
    assert _tracked_mcp(workspace, "mcp-secret-literal", servers) == [(f"{_kind(token)} in `command` of server `api`; the value is not shown", 4)]


def test_secret_literal_skips_untracked_file_in_git_repo(workspace: Workspace) -> None:
    servers = {"api": {"type": "http", "url": "https://x.test/mcp", "env": {"API_KEY": _token()}}}
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / ".mcp.json", json.dumps({"mcpServers": servers}, indent=2))
    git_add(repo, ["CLAUDE.md"])
    assert _run(workspace, "mcp-secret-literal") == []


def test_server_conflict_winner_local_same_endpoint(workspace: Workspace) -> None:
    _write_mcp(workspace, {"docs": {"command": "node", "args": ["docs-server.js"]}}, tracked=False)
    repo = workspace.rig()
    local = {"command": "node", "args": ["docs-server.js"], "env": {"LEVEL": "debug"}}
    user = {"type": "http", "url": "https://docs.example.test/mcp"}
    home = {"mcpServers": {"docs": user}, "projects": {repo.as_posix(): {"mcpServers": {"docs": local}}}}
    _write_home_json(workspace, home)
    assert [message for message, _line in _run(workspace, "mcp-server-conflict")] == [
        "server `docs` is also defined in user scope in ~/.claude.json with a different endpoint; Claude Code loads the local scope definition"
    ]
