"""The config helpers: hook maps, hook handlers and MCP servers read from a discovered rig."""

import json
from pathlib import Path

from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Rig
from rigcheck.rules.config import HookSource, McpSource, handlers, hook_maps, mcp_servers
from support import Workspace, write

PLUGIN = "tools@market"
HOOK = {"type": "command", "command": "echo hi"}


def _rig(repo: Path, workspace: Workspace) -> Rig:
    return discover(repo, workspace.home, DEFAULT_WINDOW)


def _enable(workspace: Workspace) -> None:
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))


def _install(workspace: Workspace) -> Path:
    install = workspace.home / "plugin-cache" / "tools"
    install.mkdir(parents=True, exist_ok=True)
    entry = {"scope": "user", "installPath": str(install)}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": {PLUGIN: [entry]}}))
    return install


def test_hook_maps_cover_every_source(workspace: Workspace) -> None:
    repo = workspace.rig()
    _enable(workspace)
    install = _install(workspace)
    write(repo / ".claude" / "settings.json", json.dumps({"hooks": {"Stop": [{"matcher": "*", "hooks": [HOOK]}]}}))
    write(install / "hooks" / "hooks.json", json.dumps({"description": "Hooks.", "hooks": {"PreToolUse": [{"hooks": [HOOK]}]}}))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools", "hooks": {"SessionStart": [{"hooks": [HOOK]}]}}))
    frontmatter = (
        "---\nname: lint\ndescription: Lint.\nhooks:\n  Stop:\n    - hooks:\n        - type: command\n          command: echo hi\n---\n\nBody.\n"
    )
    write(repo / ".claude" / "skills" / "lint" / "SKILL.md", frontmatter)
    write(repo / ".claude" / "agents" / "reviewer.md", frontmatter.replace("name: lint", "name: reviewer"))

    maps = list(hook_maps(_rig(repo, workspace)))
    by_source = {item.source: item for item in maps}
    assert len(maps) == 5
    assert set(by_source) == set(HookSource)
    assert by_source[HookSource.SETTINGS].artifact.path == repo / ".claude" / "settings.json"
    assert by_source[HookSource.PLUGIN_HOOKS].artifact.path == install / "hooks" / "hooks.json"
    assert by_source[HookSource.PLUGIN_MANIFEST].artifact.path == install / ".claude-plugin" / "plugin.json"
    assert by_source[HookSource.SKILL_FRONTMATTER].artifact.path == repo / ".claude" / "skills" / "lint" / "SKILL.md"
    assert by_source[HookSource.AGENT_FRONTMATTER].artifact.path == repo / ".claude" / "agents" / "reviewer.md"
    assert set(by_source[HookSource.SETTINGS].events) == {"Stop"}
    assert next(handlers(by_source[HookSource.SKILL_FRONTMATTER])).handler == HOOK


def test_hook_maps_skip_unloadable_and_non_object(workspace: Workspace) -> None:
    repo = workspace.rig()
    _enable(workspace)
    install = _install(workspace)
    write(repo / ".claude" / "settings.json", "{not json\n")
    write(repo / ".claude" / "settings.local.json", json.dumps({"hooks": [HOOK]}))
    write(install / "hooks" / "hooks.json", "[]\n")
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools", "hooks": "hooks.json"}))

    assert list(hook_maps(_rig(repo, workspace))) == []


def test_handlers_skip_malformed_shapes(workspace: Workspace) -> None:
    repo = workspace.rig()
    events = {
        "AsObject": {"hooks": [{"matcher": "x", "hooks": [HOOK]}]},
        "AsStrings": ["not a group", {"matcher": "x"}],
        "Stop": [{"matcher": "*", "hooks": ["not a handler", HOOK]}],
    }
    write(repo / ".claude" / "settings.json", json.dumps({"hooks": events}))

    found = list(handlers(next(hook_maps(_rig(repo, workspace)))))
    assert len(found) == 1
    assert found[0].event == "Stop"
    assert found[0].matcher == "*"
    assert found[0].group == {"matcher": "*", "hooks": ["not a handler", HOOK]}
    assert found[0].handler == HOOK
    assert found[0].map.events == events


def test_mcp_servers_cover_every_source(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    install = _install(workspace)
    write(repo / ".mcp.json", json.dumps({"mcpServers": {"repo-server": {"command": "npx"}}}))
    write(install / ".mcp.json", json.dumps({"mcpServers": {"plugin-server": {"command": "npx"}}}))
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools", "mcpServers": {"inline-server": {"command": "npx"}}}))

    servers = list(mcp_servers(_rig(repo, workspace)))
    assert {(server.source, server.name) for server in servers} == {
        (McpSource.REPO_FILE, "repo-server"),
        (McpSource.PLUGIN_FILE, "plugin-server"),
        (McpSource.PLUGIN_MANIFEST, "inline-server"),
    }
    assert next(server for server in servers if server.source is McpSource.REPO_FILE).config == {"command": "npx"}

    bare = workspace.rig("bare")
    write(bare / ".mcp.json", json.dumps({"other": {"command": "npx"}}))
    assert list(mcp_servers(_rig(bare, workspace))) == []


def test_flat_plugin_mcp_file_yields_its_servers(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    install = _install(workspace)
    write(install / ".mcp.json", json.dumps({"github": {"type": "http", "url": "https://x"}}))

    servers = list(mcp_servers(_rig(repo, workspace)))
    assert [(server.source, server.name, server.line) for server in servers] == [(McpSource.PLUGIN_FILE, "github", 1)]
    assert servers[0].config == {"type": "http", "url": "https://x"}

    write(install / ".mcp.json", json.dumps({"mcpServers": "not an object"}))
    assert list(mcp_servers(_rig(repo, workspace))) == []


def test_hook_map_line_points_at_the_hooks_key(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "settings.json", '{\n  "enabledPlugins": {},\n  "hooks": {"Stop": []}\n}\n')
    write(repo / ".claude" / "skills" / "lint" / "SKILL.md", "---\nname: lint\nhooks:\n  Stop: []\n---\n\nBody.\n")

    by_source = {item.source: item for item in hook_maps(_rig(repo, workspace))}
    assert by_source[HookSource.SETTINGS].line == 3
    assert by_source[HookSource.SKILL_FRONTMATTER].line == 3
