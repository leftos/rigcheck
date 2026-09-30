"""The permission rules: shadowed allows, ignored path rules, Bash wildcards and secret files without a Read deny."""

import json
from collections.abc import Sequence
from pathlib import Path

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, git_add, write


def _permissions(**lists: Sequence[object]) -> str:
    return json.dumps({"permissions": lists}, indent=2) + "\n"


def _findings(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _messages(workspace: Workspace, rule_id: str) -> list[str]:
    return sorted(message for message, _line in _findings(workspace, rule_id))


def _repo_settings(workspace: Workspace, **lists: Sequence[object]) -> None:
    write(workspace.rig() / ".claude" / "settings.json", _permissions(**lists))


def _secret_repo(workspace: Workspace, files: list[str], **lists: Sequence[object]) -> Path:
    repo = workspace.rig()
    for name in files:
        write(repo / name, "EXAMPLE=1\n")
    _repo_settings(workspace, **lists)
    git_add(repo, [".claude/settings.json"])
    return repo


def _secret_message(path: str) -> str:
    return f"{path} is not covered by a Read deny rule, so Claude can read it"


def test_user_deny_shadows_repo_allow(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "settings.json", _permissions(deny=["Bash(rm *)"]))
    _repo_settings(workspace, allow=["Bash(rm -rf build)", "Bash(rm *)", "Bash(ls)"])
    write(workspace.rig() / ".claude" / "settings.local.json", _permissions(ask=["Bash(ls)"]))
    assert _messages(workspace, "permission-allow-shadowed") == [
        'allow "Bash(ls)" never applies: ask "Bash(ls)" in local settings (.claude/settings.local.json) matches first',
        'allow "Bash(rm *)" never applies: deny "Bash(rm *)" in user settings (~/.claude/settings.json) matches first',
        'allow "Bash(rm -rf build)" never applies: deny "Bash(rm *)" in user settings (~/.claude/settings.json) matches first',
    ]


def test_mcp_server_deny_shadows_tool_allow(workspace: Workspace) -> None:
    allow = ["mcp__github__get_issue", "mcp__srv__x", "mcp__srv", "mcp__other__y", "mcp__githubx__z"]
    _repo_settings(workspace, allow=allow, deny=["mcp__github"], ask=["mcp__srv__*"])
    assert _messages(workspace, "permission-allow-shadowed") == [
        'allow "mcp__github__get_issue" never applies: deny "mcp__github" in project settings (.claude/settings.json) matches first',
        'allow "mcp__srv" never applies: ask "mcp__srv__*" in project settings (.claude/settings.json) matches first',
        'allow "mcp__srv__x" never applies: ask "mcp__srv__*" in project settings (.claude/settings.json) matches first',
    ]


def test_path_rules_compare_by_equality_only(workspace: Workspace) -> None:
    allow = ["Read(./secrets/a.txt)", "Read(./secrets/**)", "Edit(src/**)", "Read"]
    _repo_settings(workspace, allow=allow, deny=["Read(./secrets/**)", "Edit"])
    assert _messages(workspace, "permission-allow-shadowed") == [
        'allow "Edit(src/**)" never applies: deny "Edit" in project settings (.claude/settings.json) matches first',
        'allow "Read(./secrets/**)" never applies: deny "Read(./secrets/**)" in project settings (.claude/settings.json) matches first',
    ]


def test_bare_write_is_silent(workspace: Workspace) -> None:
    _repo_settings(workspace, deny=["Write", "Glob", "Write(*)", "Edit(docs/**)", "Write(docs/**)"], allow=["MultiEdit(src/**)"])
    assert _messages(workspace, "permission-path-tool-ignored") == [
        'path rule "MultiEdit(src/**)" is accepted but never consulted; Claude Code checks paths only on Read and Edit',
        'path rule "Write(docs/**)" is accepted but never consulted; Claude Code checks paths only on Read and Edit',
    ]


def test_bash_wildcard_skips_colon_star_and_spaced(workspace: Workspace) -> None:
    _repo_settings(workspace, allow=["Bash(ls*)", "Bash(ls *)", "Bash(git:*)", "Bash(*)", "Bash", "Read(src*)"], deny=["Bash(rm*)"])
    assert _messages(workspace, "permission-bash-wildcard") == [
        'allow "Bash(ls*)" has no space before *, so it also matches longer commands (Bash(ls*) matches lsof)',
    ]


def test_colon_star_at_end_is_silent(workspace: Workspace) -> None:
    _repo_settings(workspace, allow=["Bash(git:*)", "Bash(npm run test:*)"], deny=["Bash(git:* push)"], ask=["Bash(a:*b:*)"])
    assert _messages(workspace, "permission-bash-colon-star") == [
        '"Bash(a:*b:*)" has :* mid-pattern, where the colon is a literal character',
        '"Bash(git:* push)" has :* mid-pattern, where the colon is a literal character',
    ]


def test_secret_ignored_env_found(workspace: Workspace) -> None:
    repo = _secret_repo(workspace, [".env"])
    write(repo / ".gitignore", ".env\n")
    assert _messages(workspace, "secret-file-not-denied") == [_secret_message(".env")]


def test_secret_example_env_skipped(workspace: Workspace) -> None:
    files = [".env.example", ".env.sample", ".env.template", ".env.local", ".envrc", "deploy/server.key", "id_ed25519", "notes.txt"]
    _secret_repo(workspace, files)
    assert _messages(workspace, "secret-file-not-denied") == [
        _secret_message(".env.local"),
        _secret_message("deploy/server.key"),
        _secret_message("id_ed25519"),
    ]


def test_secret_folder_reported_once(workspace: Workspace) -> None:
    _secret_repo(workspace, ["secrets/a.txt", "secrets/b/c.key", "config/secrets/d.txt"])
    assert _messages(workspace, "secret-file-not-denied") == [_secret_message("config/secrets/"), _secret_message("secrets/")]


def test_secret_deny_unanchored_matches_any_depth(workspace: Workspace) -> None:
    files = [".env", "app/.env", "app/secrets/x.txt", "keys/a.key"]
    _secret_repo(workspace, files, deny=["Read(secrets/**)", "Read(/.env)", "Read(./keys/*.key)"])
    assert _messages(workspace, "secret-file-not-denied") == [_secret_message("app/.env")]


def test_secret_findings_capped(workspace: Workspace) -> None:
    _secret_repo(workspace, [f"k{index:02}.key" for index in range(12)], allow=["Bash(ls)"])
    found = _findings(workspace, "secret-file-not-denied")
    assert len(found) == 10
    assert [message for message, _line in found if "more)" in message] == [_secret_message("k09.key") + " (and 2 more)"]
    assert _secret_message("k10.key") not in {message for message, _line in found}
    assert {line for _message, line in found} == {2}


def test_malformed_rule_skipped(workspace: Workspace) -> None:
    _repo_settings(workspace, allow=["Bash(ls) x", "Bash(ls", 42, "Bash(pwd)", "Write(x) y"], deny=["Bash", "Bash(rm"])
    assert _messages(workspace, "permission-allow-shadowed") == [
        'allow "Bash(pwd)" never applies: deny "Bash" in project settings (.claude/settings.json) matches first',
    ]
    assert _messages(workspace, "permission-path-tool-ignored") == []


def test_line_points_at_rule(workspace: Workspace) -> None:
    allow = '    "allow": [\n      "Bash(ls*)",\n      "Bash(x)",\n      "Bash(ls*)"\n    ]\n'
    text = '{\n  "permissions": {\n    "deny": ["Bash(x)", "Bash(ls*)"],\n' + allow + "  }\n}\n"
    write(workspace.rig() / ".claude" / "settings.json", text)
    assert sorted(_findings(workspace, "permission-bash-wildcard"), key=lambda found: found[1] or 0) == [
        ('allow "Bash(ls*)" has no space before *, so it also matches longer commands (Bash(ls*) matches lsof)', 5),
        ('allow "Bash(ls*)" has no space before *, so it also matches longer commands (Bash(ls*) matches lsof)', 7),
    ]
    assert sorted(line or 0 for _message, line in _findings(workspace, "permission-allow-shadowed")) == [5, 6, 7]


def test_secret_inside_ignored_folder_found(workspace: Workspace) -> None:
    files = [
        "deploy/.env",
        "deploy/sub/secrets/a.txt",
        "deploy/sub/secrets/b.txt",
        "deploy/node_modules/pkg/.env",
        "deploy/1/2/3/4/5/6/.env",
        "deploy/1/2/3/4/5/6/7/.env",
        "deploy/notes.txt",
    ]
    repo = _secret_repo(workspace, files)
    write(repo / ".gitignore", "deploy/\n")
    assert _messages(workspace, "secret-file-not-denied") == [
        _secret_message("deploy/.env"),
        _secret_message("deploy/1/2/3/4/5/6/.env"),
        _secret_message("deploy/sub/secrets/"),
    ]


def test_slash_path_rules_differ_across_user_and_project(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "settings.json", _permissions(deny=["Read(/secrets/**)"]))
    _repo_settings(workspace, allow=["Read(/secrets/**)"])
    assert _messages(workspace, "permission-allow-shadowed") == []
    _repo_settings(workspace, allow=["Read(/secrets/**)"], deny=["Read(/secrets/**)"])
    assert _messages(workspace, "permission-allow-shadowed") == [
        'allow "Read(/secrets/**)" never applies: deny "Read(/secrets/**)" in project settings (.claude/settings.json) matches first',
    ]


def test_negated_deny_reopens_secret(workspace: Workspace) -> None:
    repo = _secret_repo(workspace, [".env", "app/.env", "x.key"], deny=["Read(!x.key)", "Read(x.key)", "Read(.env)", "Read(!app/.env)"])
    write(repo / ".claude" / "settings.local.json", _permissions(deny=["Read(!.env)"]))
    assert _messages(workspace, "secret-file-not-denied") == [_secret_message("app/.env")]


def test_secret_rule_skips_home_target(workspace: Workspace) -> None:
    write(workspace.home / ".env", "EXAMPLE=1\n")
    write(workspace.home / ".claude" / "settings.json", _permissions(allow=["Bash(ls)"]))
    git_add(workspace.home, [".claude/settings.json"])
    findings = engine.run(discover(workspace.home, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    assert [finding.message for finding in findings if finding.rule_id == "secret-file-not-denied"] == []


def test_public_certificate_pem_skipped(workspace: Workspace) -> None:
    repo = _secret_repo(workspace, ["plain.key"])
    write(repo / "ca.pem", "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    write(repo / "server.pem", "marker: RSA PRIVATE KEY\n")
    write(repo / "certs" / "chain.pem", "CERTIFICATE\n" * 10 + "PRIVATE KEY\n")
    assert _messages(workspace, "secret-file-not-denied") == [
        _secret_message("certs/chain.pem"),
        _secret_message("plain.key"),
        _secret_message("server.pem"),
    ]
