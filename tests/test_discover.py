import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover, encode_project, memory_dir
from rigcheck.model import Artifact, Kind, Layer, LoadClass, Rig
from rigcheck.rules import REGISTRY
from support import Workspace, symlink_or_skip, write

PLUGIN = "tools@market"
UNC_RULES = r"\\server\share\rules" if os.name == "nt" else "//server/share/rules"


def _by_name(rig: Rig) -> dict[str, Artifact]:
    return {artifact.path.name: artifact for artifact in rig.artifacts}


def _artifact(rig: Rig, path: Path) -> Artifact:
    return next(artifact for artifact in rig.artifacts if artifact.path == path)


def _install_plugin(workspace: Workspace, entry: dict[str, str]) -> Path:
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / "lint" / "SKILL.md", "---\nname: lint\ndescription: Lint.\n---\n")
    write(install / "agents" / "reviewer.md", "---\nname: reviewer\n---\n")
    write(install / "commands" / "go.md", "Go.\n")
    write(install / "output-styles" / "terse.md", "Terse.\n")
    write(install / "hooks" / "hooks.json", "{}\n")
    write(install / ".mcp.json", "{}\n")
    write(install / ".claude-plugin" / "plugin.json", '{"name": "tools"}\n')
    installed = {"version": 2, "plugins": {PLUGIN: [{**entry, "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    return install


def _enable(settings: Path, enabled: bool) -> None:
    write(settings, json.dumps({"enabledPlugins": {PLUGIN: enabled}}))


def _plugin_artifacts(rig: Rig) -> list[Artifact]:
    return [artifact for artifact in rig.artifacts if artifact.layer is Layer.PLUGIN]


def test_user_enabled_plugin_contributes_its_components(workspace: Workspace) -> None:
    repo = workspace.rig()
    _install_plugin(workspace, {"scope": "user"})
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    artifacts = _plugin_artifacts(discover(repo, workspace.home))
    kinds = sorted(artifact.kind.value for artifact in artifacts)
    assert kinds == ["agent", "command", "hooks-config", "mcp-config", "output-style", "plugin-manifest", "skill"]
    assert {artifact.plugin for artifact in artifacts} == {PLUGIN}


def test_plugin_output_styles_are_discovered_on_demand(workspace: Workspace) -> None:
    repo = workspace.rig()
    install = _install_plugin(workspace, {"scope": "user"})
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    artifact = _artifact(discover(repo, workspace.home), install / "output-styles" / "terse.md")
    assert (artifact.kind, artifact.layer, artifact.load_class) == (Kind.OUTPUT_STYLE, Layer.PLUGIN, LoadClass.ON_DEMAND)
    assert artifact.plugin == PLUGIN


def test_project_settings_disable_a_user_enabled_plugin(workspace: Workspace) -> None:
    repo = workspace.rig()
    _install_plugin(workspace, {"scope": "user"})
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    _enable(repo / ".claude" / "settings.json", enabled=False)
    assert _plugin_artifacts(discover(repo, workspace.home)) == []


def test_local_settings_override_project_settings(workspace: Workspace) -> None:
    repo = workspace.rig()
    _install_plugin(workspace, {"scope": "user"})
    _enable(repo / ".claude" / "settings.json", enabled=False)
    _enable(repo / ".claude" / "settings.local.json", enabled=True)
    assert _plugin_artifacts(discover(repo, workspace.home))


def test_plugin_not_enabled_anywhere_is_ignored(workspace: Workspace) -> None:
    repo = workspace.rig()
    _install_plugin(workspace, {"scope": "user"})
    assert _plugin_artifacts(discover(repo, workspace.home)) == []


def test_project_install_for_another_project_is_ignored(workspace: Workspace) -> None:
    repo = workspace.rig()
    other = workspace.rig("other")
    _install_plugin(workspace, {"scope": "project", "projectPath": str(other)})
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    assert _plugin_artifacts(discover(repo, workspace.home)) == []


def test_project_install_for_this_project_is_used(workspace: Workspace) -> None:
    repo = workspace.rig()
    _install_plugin(workspace, {"scope": "local", "projectPath": str(repo)})
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    assert _plugin_artifacts(discover(repo, workspace.home))


def test_missing_install_path_is_a_problem(workspace: Workspace) -> None:
    repo = workspace.rig()
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(workspace.home / "gone")}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    _enable(workspace.home / ".claude" / "settings.json", enabled=True)
    rig = discover(repo, workspace.home)
    assert any("does not exist" in problem for problem in rig.problems)


def test_malformed_installed_plugins_becomes_a_discovery_error_finding(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", "{not json")
    rig = discover(repo, workspace.home)
    findings = engine.run(rig, REGISTRY.values())
    errors = [finding for finding in findings if finding.rule_id == "discovery-error"]
    assert len(errors) == 1
    assert "malformed JSON" in errors[0].message
    assert errors[0].path is None


def test_encode_project_matches_claude_code_folder_names() -> None:
    assert encode_project(Path(r"D:\yaat")) == "D--yaat"
    assert encode_project(Path(r"C:\Users\me\.claude")) == "C--Users-me--claude"


def test_memory_folder_for_this_project_only(workspace: Workspace) -> None:
    repo = workspace.rig()
    memory = memory_dir(repo, workspace.home)
    write(memory / "MEMORY.md", "- [Topic](topic.md)\n")
    write(memory / "topic.md", "Details.\n")
    write(memory_dir(workspace.rig("other"), workspace.home) / "MEMORY.md", "Other project.\n")
    memory_artifacts = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.layer is Layer.MEMORY]
    by_name = {artifact.path.name: artifact for artifact in memory_artifacts}
    assert set(by_name) == {"MEMORY.md", "topic.md"}
    assert all(artifact.path.parent == memory for artifact in memory_artifacts)
    assert (by_name["MEMORY.md"].kind, by_name["MEMORY.md"].load_class) == (Kind.MEMORY_INDEX, LoadClass.EVERY_TURN)
    assert (by_name["topic.md"].kind, by_name["topic.md"].load_class) == (Kind.MEMORY_TOPIC, LoadClass.ON_DEMAND)


def test_rules_load_every_turn_unless_path_scoped(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "rules" / "always.md", "Always.\n")
    write(repo / ".claude" / "rules" / "api" / "scoped.md", "---\npaths:\n  - src/api/**\n---\nScoped.\n")
    write(repo / ".claude" / "rules" / "broken.md", "---\npaths:\n  - src/**\ndescription: 'a' b: 'c'\n---\nBroken.\n")
    write(repo / ".claude" / "rules" / "nonstandard.md", "---\npaths:\n  - src/**\ndescription: a: b\n---\nLoads anyway.\n")
    write(workspace.home / ".claude" / "rules" / "mine.md", "Mine.\n")
    artifacts = _by_name(discover(repo, workspace.home))
    assert artifacts["always.md"].load_class is LoadClass.EVERY_TURN
    assert artifacts["scoped.md"].load_class is LoadClass.ON_DEMAND
    assert artifacts["broken.md"].load_class is LoadClass.EVERY_TURN
    assert artifacts["nonstandard.md"].load_class is LoadClass.ON_DEMAND
    assert (artifacts["mine.md"].kind, artifacts["mine.md"].layer) == (Kind.RULE, Layer.USER)


def _rule_link(repo: Path, name: str, target: Path) -> Path:
    link = repo / ".claude" / "rules" / name
    link.parent.mkdir(parents=True, exist_ok=True)
    symlink_or_skip(link, os.fspath(target))
    return link


def test_rule_folder_link_outside_repo_scoped_by_paths_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    external = write(workspace.home / "elsewhere" / "rules" / "a.md", "---\npaths:\n  - src/**\n---\nScoped.\n")
    _rule_link(repo, "shared", external.parent)
    artifact = _artifact(discover(repo, workspace.home), repo / ".claude" / "rules" / "shared" / "a.md")
    assert (artifact.layer, artifact.load_class) == (Layer.REPO, LoadClass.NOT_LOADED)


def test_rule_folder_link_outside_repo_without_paths_loads_every_turn(workspace: Workspace) -> None:
    repo = workspace.rig()
    external = write(workspace.home / "elsewhere" / "rules" / "b.md", "No frontmatter.\n")
    _rule_link(repo, "shared", external.parent)
    artifact = _artifact(discover(repo, workspace.home), repo / ".claude" / "rules" / "shared" / "b.md")
    assert (artifact.layer, artifact.load_class) == (Layer.REPO, LoadClass.EVERY_TURN)


def test_rule_folder_link_inside_repo_keeps_paths_scoping(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "docs" / "rules" / "c.md", "---\npaths:\n  - src/**\n---\nScoped.\n")
    _rule_link(repo, "local", repo / "docs" / "rules")
    artifact = _artifact(discover(repo, workspace.home), repo / ".claude" / "rules" / "local" / "c.md")
    assert (artifact.layer, artifact.load_class) == (Layer.REPO, LoadClass.ON_DEMAND)


def test_rule_folder_link_cycle_terminates_and_lists_each_file_once(workspace: Workspace) -> None:
    repo = workspace.rig()
    real = write(repo / ".claude" / "rules" / "real.md", "Real.\n")
    _rule_link(repo, "loop", repo / ".claude" / "rules")
    rules = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.kind is Kind.RULE and artifact.layer is Layer.REPO]
    assert [artifact.path for artifact in rules] == [real]


def test_rule_folder_link_beside_its_target_lists_the_files_once(workspace: Workspace) -> None:
    repo = workspace.rig()
    real = write(repo / ".claude" / "rules" / "a" / "x.md", "Real.\n")
    _rule_link(repo, "b", real.parent)
    rules = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.kind is Kind.RULE and artifact.layer is Layer.REPO]
    assert [artifact.path for artifact in rules] == [real]


def test_rule_file_link_outside_repo_scoped_by_paths_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    external = write(workspace.home / "elsewhere" / "d.md", "---\npaths:\n  - src/**\n---\nScoped.\n")
    _rule_link(repo, "d.md", external)
    artifact = _artifact(discover(repo, workspace.home), repo / ".claude" / "rules" / "d.md")
    assert (artifact.layer, artifact.load_class) == (Layer.REPO, LoadClass.NOT_LOADED)


def _junction_or_skip(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False)  # noqa: S603, S607 - fixed test command
    if result.returncode != 0:
        pytest.skip("cannot create a junction here")


def _discover_within(target: Path, home: Path, timeout: float = 10.0) -> Rig:
    """Discover in a daemon thread, so a walk that loops fails the test instead of hanging it."""
    result: list[Rig] = []
    thread = threading.Thread(target=lambda: result.append(discover(target, home)), daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"discovery did not finish within {timeout}s"
    return result[0]


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_rule_folder_junction_cycle_terminates(workspace: Workspace) -> None:
    repo = workspace.rig()
    real = write(repo / ".claude" / "rules" / "x.md", "Real.\n")
    _junction_or_skip(repo / ".claude" / "rules" / "loop", repo / ".claude" / "rules")
    rig = _discover_within(repo, workspace.home)
    rules = [artifact for artifact in rig.artifacts if artifact.kind is Kind.RULE and artifact.layer is Layer.REPO]
    assert [artifact.path for artifact in rules] == [real]


@pytest.mark.skipif(os.name != "nt", reason="junctions exist only on Windows")
def test_rule_folder_junction_outside_repo_scoped_by_paths_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    external = write(workspace.home / "elsewhere" / "rules" / "a.md", "---\npaths:\n  - src/**\n---\nScoped.\n")
    _junction_or_skip(repo / ".claude" / "rules" / "shared", external.parent)
    artifact = _artifact(discover(repo, workspace.home), repo / ".claude" / "rules" / "shared" / "a.md")
    assert (artifact.layer, artifact.load_class) == (Layer.REPO, LoadClass.NOT_LOADED)


def test_rule_folder_link_to_a_real_folder_loses_to_it(workspace: Workspace) -> None:
    repo = workspace.rig()
    real = write(repo / ".claude" / "rules" / "z" / "x.md", "Real.\n")
    _rule_link(repo, "a", real.parent)
    rules = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.kind is Kind.RULE and artifact.layer is Layer.REPO]
    assert [artifact.path for artifact in rules] == [real]


def test_rule_folder_link_nested_below_a_real_folder_loses_to_it(workspace: Workspace) -> None:
    repo = workspace.rig()
    real = write(repo / ".claude" / "rules" / "b" / "c" / "y.md", "Real.\n")
    _rule_link(repo, "a/l", real.parent)
    rules = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.kind is Kind.RULE and artifact.layer is Layer.REPO]
    assert [artifact.path for artifact in rules] == [real]


def test_rule_folder_link_to_a_network_path_is_reported_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    link = _rule_link(repo, "shared", Path(UNC_RULES))
    rig = discover(repo, workspace.home)
    artifact = _artifact(rig, link)
    assert (artifact.kind, artifact.layer, artifact.load_class) == (Kind.RULE, Layer.REPO, LoadClass.NOT_LOADED)
    rules = [item for item in rig.artifacts if item.kind is Kind.RULE and item.layer is Layer.REPO]
    assert [item.path for item in rules] == [link]
    findings = engine.run(rig, REGISTRY.values())
    assert any(finding.rule_id == "unc-symlink" and finding.path == link for finding in findings)


def test_claude_rules_dir_link_to_a_network_path_is_reported_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    link = repo / ".claude" / "rules"
    symlink_or_skip(link, UNC_RULES)
    rig = discover(repo, workspace.home)
    artifact = _artifact(rig, link)
    assert (artifact.kind, artifact.layer, artifact.load_class) == (Kind.RULE, Layer.REPO, LoadClass.NOT_LOADED)
    assert rig.problems == ()


def test_claude_dir_components(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / ".claude" / "skills" / "ship" / "SKILL.md", "---\nname: ship\n---\n")
    write(repo / ".claude" / "commands" / "deep" / "cmd.md", "Command.\n")
    write(repo / ".claude" / "agents" / "helper.md", "---\nname: helper\n---\n")
    write(repo / ".claude" / "output-styles" / "terse.md", "Terse.\n")
    write(repo / ".claude" / "settings.json", "{}\n")
    write(repo / ".mcp.json", "{}\n")
    artifacts = _by_name(discover(repo, workspace.home))
    assert (artifacts["SKILL.md"].kind, artifacts["SKILL.md"].load_class) == (Kind.SKILL, LoadClass.ON_INVOKE)
    assert (artifacts["cmd.md"].kind, artifacts["cmd.md"].load_class) == (Kind.COMMAND, LoadClass.ON_INVOKE)
    assert (artifacts["helper.md"].kind, artifacts["helper.md"].load_class) == (Kind.AGENT, LoadClass.ON_INVOKE)
    assert (artifacts["terse.md"].kind, artifacts["terse.md"].load_class) == (Kind.OUTPUT_STYLE, LoadClass.ON_DEMAND)
    assert (artifacts["settings.json"].kind, artifacts["settings.json"].load_class) == (Kind.SETTINGS, LoadClass.CONFIG)
    assert (artifacts[".mcp.json"].kind, artifacts[".mcp.json"].layer) == (Kind.MCP_CONFIG, Layer.REPO)


def test_agents_md_alone_loads_every_turn(workspace: Workspace) -> None:
    repo = workspace.rig()
    agents = write(repo / "AGENTS.md", "# Agents\n")
    assert _artifact(discover(repo, workspace.home), agents).load_class is LoadClass.EVERY_TURN


def test_agents_md_beside_claude_md_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    agents = write(repo / "AGENTS.md", "# Agents\n")
    assert _artifact(discover(repo, workspace.home), agents).load_class is LoadClass.NOT_LOADED


def test_agents_md_below_a_parent_claude_md_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo.parent / "CLAUDE.md", "# Parent\n")
    agents = write(repo / "AGENTS.md", "# Agents\n")
    assert _artifact(discover(repo, workspace.home), agents).load_class is LoadClass.NOT_LOADED


def test_agents_md_beside_claude_local_md_is_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.local.md", "Mine.\n")
    agents = write(repo / "AGENTS.md", "# Agents\n")
    assert _artifact(discover(repo, workspace.home), agents).load_class is LoadClass.NOT_LOADED


def test_agents_md_imported_by_claude_md_loads(workspace: Workspace) -> None:
    repo = workspace.rig()
    claude = write(repo / "CLAUDE.md", "@AGENTS.md\n")
    agents = write(repo / "AGENTS.md", "# Agents\n")
    artifact = _artifact(discover(repo, workspace.home), agents)
    assert artifact.load_class is LoadClass.EVERY_TURN
    assert artifact.imported_from == claude
    assert artifact.import_depth == 1


def test_import_depth_five_is_recorded_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "@hop1.md\n")
    for hop in range(1, 6):
        write(repo / f"hop{hop}.md", f"@hop{hop + 1}.md\n")
    write(repo / "hop6.md", "Never reached.\n")
    artifacts = _by_name(discover(repo, workspace.home))
    assert (artifacts["hop4.md"].import_depth, artifacts["hop4.md"].load_class) == (4, LoadClass.EVERY_TURN)
    assert (artifacts["hop5.md"].import_depth, artifacts["hop5.md"].load_class) == (5, LoadClass.NOT_LOADED)
    assert "hop6.md" not in artifacts


def test_import_cycle_terminates(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "@a.md\n")
    write(repo / "a.md", "@b.md\n")
    write(repo / "b.md", "@a.md @CLAUDE.md\n")
    names = sorted(artifact.path.name for artifact in discover(repo, workspace.home).artifacts)
    assert names == ["CLAUDE.md", "a.md", "b.md"]


def test_imports_in_code_and_comments_are_not_followed(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "`@a.md`\n\n```\n@b.md\n```\n\n<!-- @c.md -->\n")
    for name in ("a.md", "b.md", "c.md"):
        write(repo / name, "Not imported.\n")
    names = [artifact.path.name for artifact in discover(repo, workspace.home).artifacts]
    assert names == ["CLAUDE.md"]


def test_user_claude_md_and_tilde_imports(workspace: Workspace) -> None:
    repo = workspace.rig()
    user = write(workspace.home / ".claude" / "CLAUDE.md", "@~/.claude/extra.md\n")
    extra = workspace.home / ".claude" / "extra.md"
    write(extra, "Extra.\n")
    rig = discover(repo, workspace.home)
    assert (_artifact(rig, user).layer, _artifact(rig, user).load_class) == (Layer.USER, LoadClass.EVERY_TURN)
    assert (_artifact(rig, extra).layer, _artifact(rig, extra).imported_from) == (Layer.USER, user)


def test_nested_claude_md_is_on_demand_and_skips_vendor_dirs(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Root\n")
    nested = write(repo / "src" / "api" / "CLAUDE.md", "# API\n")
    write(repo / "node_modules" / "pkg" / "CLAUDE.md", "# Vendor\n")
    rig = discover(repo, workspace.home)
    nested_artifacts = [artifact for artifact in rig.artifacts if artifact.kind is Kind.NESTED_INSTRUCTIONS]
    assert [artifact.path for artifact in nested_artifacts] == [nested]
    assert nested_artifacts[0].load_class is LoadClass.ON_DEMAND


def test_home_target_reads_only_the_claude_folder(workspace: Workspace) -> None:
    write(workspace.home / "CLAUDE.md", "# Home\n")
    write(workspace.home / "AGENTS.md", "# Agents\n")
    write(workspace.home / ".mcp.json", "{}\n")
    write(workspace.home / "proj" / "CLAUDE.md", "# Proj\n")
    write(workspace.home / "AppData" / "x" / "CLAUDE.md", "# AppData\n")
    user_root = write(workspace.home / ".claude" / "CLAUDE.md", "# User\n")
    rule = write(workspace.home / ".claude" / "rules" / "r.md", "Rule.\n")
    rig = discover(workspace.home, workspace.home)
    assert [artifact for artifact in rig.artifacts if artifact.layer is Layer.REPO] == []
    assert _artifact(rig, user_root).kind is Kind.INSTRUCTIONS
    assert _artifact(rig, user_root).layer is Layer.USER
    assert _artifact(rig, rule).layer is Layer.USER
    assert [artifact for artifact in rig.artifacts if artifact.kind is Kind.NESTED_INSTRUCTIONS] == []


def test_home_subfolder_still_walks_nested(workspace: Workspace) -> None:
    notes = workspace.home / "notes"
    write(notes / "CLAUDE.md", "# Notes\n")
    nested = write(notes / "sub" / "CLAUDE.md", "# Sub\n")
    rig = discover(notes, workspace.home)
    nested_artifacts = [artifact for artifact in rig.artifacts if artifact.kind is Kind.NESTED_INSTRUCTIONS]
    assert [artifact.path for artifact in nested_artifacts] == [nested]
    assert nested_artifacts[0].layer is Layer.REPO


def test_walk_does_not_enter_junctions(workspace: Workspace) -> None:
    if os.name != "nt":
        pytest.skip("junctions exist only on Windows")
    repo = workspace.rig()
    write(workspace.home / "elsewhere" / "CLAUDE.md", "# Elsewhere\n")
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(repo / "link"), str(workspace.home / "elsewhere")], capture_output=True, check=False)  # noqa: S603, S607 - fixed test command
    if result.returncode != 0:
        pytest.skip("cannot create a junction here")
    nested = [artifact for artifact in discover(repo, workspace.home).artifacts if artifact.kind is Kind.NESTED_INSTRUCTIONS]
    assert nested == []


def test_agents_local_and_override_are_recorded_not_loaded(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "AGENTS.local.md", "Local.\n")
    write(repo / "AGENTS.override.md", "Override.\n")
    artifacts = _by_name(discover(repo, workspace.home))
    assert artifacts["AGENTS.local.md"].load_class is LoadClass.NOT_LOADED
    assert artifacts["AGENTS.override.md"].load_class is LoadClass.NOT_LOADED
