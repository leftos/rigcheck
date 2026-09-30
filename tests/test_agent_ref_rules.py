"""The subagent reference rules: tools and skills that resolve, name collisions, and a forked skill's agent."""

import json
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Layer
from rigcheck.rules import REGISTRY
from support import Workspace, write

AGENTS = Path(".claude") / "agents"
SKILLS = Path(".claude") / "skills"
PLUGIN = "tools@market"
REF_RULES = (
    "agent-tools-unresolved",
    "agent-tool-unknown",
    "agent-disallowed-specifier",
    "agent-skill-missing",
    "agent-skill-not-preloadable",
    "agent-name-collision",
    "skill-agent-missing",
)
VALID = "name: helper\ndescription: Helps.\n"
FULL_WIDTH_COLON = chr(0xFF1A)

Found = list[tuple[str, str, int | None]]


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _run(workspace: Workspace) -> Found:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.rule_id, finding.message, finding.line) for finding in findings if finding.rule_id in REF_RULES]


def _repo(workspace: Workspace) -> Path:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    return repo


def _agent(workspace: Workspace, frontmatter: str) -> Found:
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID + frontmatter))
    return _run(workspace)


def _skill(workspace: Workspace, folder: str, frontmatter: str) -> None:
    write(_repo(workspace) / SKILLS / folder / "SKILL.md", _file(f"description: Does {folder}.\n" + frontmatter))


def _unknown(key: str, entry: str, hint: str | None = None) -> str:
    suggestion = f' (did you mean "{hint}"?)' if hint else ""
    return f'{key} entry "{entry}"{suggestion} names no built-in tool or mcp__ tool; Claude Code ignores it'


def _unknowns(key: str, named: str) -> str:
    return f"{key} entries {named} name no built-in tool or mcp__ tool; Claude Code ignores them"


UNRESOLVED = "no entry in tools resolves to a tool, so the agent usually fails to launch"


def test_builtin_and_mcp_tools_resolve(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: Read, Grep, mcp__godot__run_project\n") == []


def test_mcp_server_ids_and_wildcards_resolve(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: mcp__godot, mcp__godot__*\n") == []
    assert _agent(workspace, 'tools: "*"\n') == []


def test_one_unknown_entry_in_a_list(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: [Read, Grpe]\n") == [("agent-tool-unknown", _unknown("tools", "Grpe"), 4)]


def test_miscased_tool_suggests_the_spelling(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: read\n") == [
        ("agent-tools-unresolved", UNRESOLVED, 4),
        ("agent-tool-unknown", _unknown("tools", "read", "Read"), 4),
    ]


def test_no_entry_resolving_is_an_error_too(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: Foo, Bar\n") == [
        ("agent-tools-unresolved", UNRESOLVED, 4),
        ("agent-tool-unknown", _unknowns("tools", '"Foo", "Bar"'), 4),
    ]


def test_unknown_entries_are_one_finding_per_key_with_inline_hints(workspace: Workspace) -> None:
    found = _agent(workspace, "tools: Read, read_file, grep, run_shell_command\ndisallowedTools: Wrte, Bash\n")
    assert found == [
        ("agent-tool-unknown", _unknowns("tools", '"read_file", "grep" (did you mean "Grep"?), "run_shell_command"'), 4),
        ("agent-tool-unknown", _unknown("disallowedTools", "Wrte"), 5),
    ]


def test_unknown_entries_past_eight_are_counted(workspace: Workspace) -> None:
    names = [f"t{index}" for index in range(10)]
    found = _agent(workspace, f"tools: Read, {', '.join(names)}\n")
    named = ", ".join(f'"{name}"' for name in names[:8])
    assert found == [("agent-tool-unknown", _unknowns("tools", f"{named} and 2 more"), 4)]


def test_case_variant_of_a_listed_tool_is_skipped(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: read, Read, skill, Skill\n") == []
    found = _agent(workspace, "tools: read, Read, edit, execute\n")
    assert found == [("agent-tool-unknown", _unknowns("tools", '"edit" (did you mean "Edit"?), "execute"'), 4)]


def test_specifiers_and_aliases_resolve(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: Bash(git:*), Agent(Explore), Task, KillShell, RunWorkflow\n") == []


def test_permission_only_legacy_names_do_not_resolve(workspace: Workspace) -> None:
    message = 'tools entry "MultiEdit" (a legacy permission name with no tool) names no built-in tool or mcp__ tool; Claude Code ignores it'
    assert _agent(workspace, "tools: MultiEdit\n") == [("agent-tools-unresolved", UNRESOLVED, 4), ("agent-tool-unknown", message, 4)]
    legacy = '"LS" (a legacy permission name with no tool), "NotebookRead" (a legacy permission name with no tool)'
    assert _agent(workspace, "tools: Read, LS, NotebookRead\n") == [("agent-tool-unknown", _unknowns("tools", legacy), 4)]


def test_agent_lists_split_every_string_on_commas_and_spaces(workspace: Workspace) -> None:
    assert _agent(workspace, 'tools: ["Read, Grep"]\n') == []
    assert _agent(workspace, "tools:\n  - Read Grep\n  - Bash(git push *)\n") == []


def test_flow_list_inside_a_string_is_not_unwrapped(workspace: Workspace) -> None:
    found = _agent(workspace, 'tools: "[Read, Grep]"\n')
    assert found == [("agent-tools-unresolved", UNRESOLVED, 4), ("agent-tool-unknown", _unknowns("tools", '"[Read", "Grep]"'), 4)]


def test_repeated_unknown_entries_are_named_once(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: Read, Foo, Foo, Bar\n") == [("agent-tool-unknown", _unknowns("tools", '"Foo", "Bar"'), 4)]


def test_case_variant_of_a_tool_reached_through_an_alias_is_skipped(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: agent, Task\n") == []


def test_mcp_ids_need_a_server_and_a_non_empty_tool(workspace: Workspace) -> None:
    found = _agent(workspace, "tools: Read, mcp__, mcp____x, mcp__s__, mcp__*, mcp__-, mcp__s, mcp__s__*, mcp__s__t\n")
    bad = '"mcp__", "mcp____x", "mcp__s__", "mcp__*", "mcp__-"'
    assert found == [("agent-tool-unknown", _unknowns("tools", bad), 4)]


def test_unknown_entries_at_the_cap_are_all_named(workspace: Workspace) -> None:
    names = [f"t{index}" for index in range(9)]
    eight = ", ".join(f'"{name}"' for name in names[:8])
    assert _agent(workspace, f"tools: Read, {', '.join(names[:8])}\n") == [("agent-tool-unknown", _unknowns("tools", eight), 4)]
    nine = _agent(workspace, f"tools: Read, {', '.join(names)}\n")
    assert nine == [("agent-tool-unknown", _unknowns("tools", f"{eight} and 1 more"), 4)]


def test_full_width_colon_in_a_name_skips_the_agent(workspace: Workspace) -> None:
    name = f"a{FULL_WIDTH_COLON}b"
    write(_repo(workspace) / AGENTS / "helper.md", _file(f"name: {name}\ndescription: Helps.\n"))
    findings = engine.run(discover(workspace.rig(), workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [(finding.rule_id, finding.message) for finding in findings if finding.rule_id == "agent-skipped"]
    assert fired == [("agent-skipped", f'name "{name}" holds ":", so Claude Code skips the agent')]


def test_empty_tools_is_silent(workspace: Workspace) -> None:
    assert _agent(workspace, 'tools: ""\n') == []


def test_non_string_tool_items_are_dropped(workspace: Workspace) -> None:
    assert _agent(workspace, "tools: [Foo, 5]\n") == [("agent-tools-unresolved", UNRESOLVED, 4), ("agent-tool-unknown", _unknown("tools", "Foo"), 4)]


def test_unknown_disallowed_tool(workspace: Workspace) -> None:
    assert _agent(workspace, "disallowedTools: Wrte\n") == [("agent-tool-unknown", _unknown("disallowedTools", "Wrte"), 4)]


def test_disallowed_specifier_removes_the_whole_tool(workspace: Workspace) -> None:
    message = 'disallowedTools entry "Bash(git push *)" has a specifier, but it still removes the whole Bash tool'
    assert _agent(workspace, "disallowedTools: Bash(git push *)\n") == [("agent-disallowed-specifier", message, 4)]


def test_whole_disallowed_tool_is_silent(workspace: Workspace) -> None:
    assert _agent(workspace, "disallowedTools: WebFetch\n") == []


def test_disallowed_subagent_specifiers_remove_the_whole_tool(workspace: Workspace) -> None:
    assert _agent(workspace, "disallowedTools: Agent(Explore), Task(Plan)\n") == [
        ("agent-disallowed-specifier", 'disallowedTools entry "Agent(Explore)" has a specifier, but it still removes the whole Agent tool', 4),
        ("agent-disallowed-specifier", 'disallowedTools entry "Task(Plan)" has a specifier, but it still removes the whole Task tool', 4),
    ]


def test_skipped_agent_is_not_checked(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file("name: helper\ntools: Foo\nskills: nope\n"))
    assert _run(workspace) == []


def _missing_skill(entry: str, hint: str | None = None) -> str:
    suggestion = f' (did you mean "{hint}"?)' if hint else ""
    return f'skills entry "{entry}" names no skill or command{suggestion}, so nothing is preloaded for it'


def test_existing_skill_resolves(workspace: Workspace) -> None:
    _skill(workspace, "demo", "")
    assert _agent(workspace, "skills: [demo]\n") == []


def test_skill_by_its_frontmatter_name_resolves(workspace: Workspace) -> None:
    _skill(workspace, "demo", "name: showcase\n")
    assert _agent(workspace, "skills: showcase\n") == []


def test_command_resolves_as_a_skill(workspace: Workspace) -> None:
    write(_repo(workspace) / ".claude" / "commands" / "deploy.md", _file("description: Deploys.\n"))
    assert _agent(workspace, "skills: deploy\n") == []


def test_missing_skill_is_an_error(workspace: Workspace) -> None:
    _skill(workspace, "demo", "")
    assert _agent(workspace, "skills: demoo\n") == [("agent-skill-missing", _missing_skill("demoo"), 4)]


def test_miscased_skill_suggests_the_name(workspace: Workspace) -> None:
    _skill(workspace, "demo", "")
    assert _agent(workspace, "skills:\n  - Demo\n") == [("agent-skill-missing", _missing_skill("Demo", "demo"), 4)]


def _blocked(entry: str) -> str:
    return f'skills entry "{entry}" names a skill with disable-model-invocation: true, which also stops preloading into subagents'


BLOCKS = "disable-model-invocation: true\n"


def _command(workspace: Workspace, relative: str, frontmatter: str) -> None:
    write(_repo(workspace) / ".claude" / "commands" / relative, _file("description: Runs.\n" + frontmatter))


def test_skill_that_blocks_model_invocation_cannot_preload(workspace: Workspace) -> None:
    _skill(workspace, "demo", BLOCKS)
    assert _agent(workspace, "skills: demo\n") == [("agent-skill-not-preloadable", _blocked("demo"), 4)]


def test_command_that_blocks_model_invocation_cannot_preload(workspace: Workspace) -> None:
    _command(workspace, "deploy.md", BLOCKS)
    assert _agent(workspace, "skills: deploy\n") == [("agent-skill-not-preloadable", _blocked("deploy"), 4)]


def test_nested_command_is_named_by_its_folders(workspace: Workspace) -> None:
    _command(workspace, "grp/leaf.md", "")
    assert _agent(workspace, "skills: grp:leaf\n") == []
    assert _agent(workspace, "skills: leaf\n") == [("agent-skill-missing", _missing_skill("leaf"), 4)]


def test_skill_wins_over_a_command_of_the_same_name(workspace: Workspace) -> None:
    _skill(workspace, "deploy", "")
    _command(workspace, "deploy.md", BLOCKS)
    assert _agent(workspace, "skills: deploy\n") == []
    _skill(workspace, "deploy", BLOCKS)
    _command(workspace, "deploy.md", "")
    assert _agent(workspace, "skills: deploy\n") == [("agent-skill-not-preloadable", _blocked("deploy"), 4)]


def test_user_skill_wins_over_the_project_skill(workspace: Workspace) -> None:
    user = workspace.home / SKILLS / "demo" / "SKILL.md"
    _skill(workspace, "demo", "")
    write(user, _file("description: Demo.\n" + BLOCKS))
    assert _agent(workspace, "skills: demo\n") == [("agent-skill-not-preloadable", _blocked("demo"), 4)]
    _skill(workspace, "demo", BLOCKS)
    write(user, _file("description: Demo.\n"))
    assert _agent(workspace, "skills: demo\n") == []


def _collision(name: str, winner: str) -> str:
    return f'agent name "{name}" is also defined in {winner}, which takes precedence, so this agent is never used'


def test_user_agent_loses_to_the_project_agent(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID))
    write(workspace.home / AGENTS / "helper.md", _file(VALID))
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [(finding.layer, finding.path, finding.message, finding.line) for finding in findings if finding.rule_id in REF_RULES]
    assert fired == [(Layer.USER, workspace.home / AGENTS / "helper.md", _collision("helper", ".claude/agents/helper.md"), 2)]


def test_later_path_loses_within_one_layer(workspace: Workspace) -> None:
    repo = _repo(workspace)
    write(repo / AGENTS / "a.md", _file(VALID))
    write(repo / AGENTS / "sub" / "b.md", _file(VALID))
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [(finding.path, finding.message) for finding in findings if finding.rule_id in REF_RULES]
    assert fired == [(repo / AGENTS / "sub" / "b.md", _collision("helper", ".claude/agents/a.md"))]


def test_custom_agent_with_a_builtin_name_is_silent(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "explore.md", _file("name: Explore\ndescription: Explores.\n"))
    assert _run(workspace) == []


def _missing_agent(name: str, hint: str | None = None) -> str:
    suggestion = f' (did you mean "{hint}"?)' if hint else ""
    return f'agent "{name}" names no built-in or custom subagent{suggestion}'


def test_fork_to_a_builtin_agent_resolves(workspace: Workspace) -> None:
    _skill(workspace, "demo", "context: fork\nagent: Explore\n")
    assert _run(workspace) == []


def test_fork_to_a_missing_agent_is_an_error(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID))
    _skill(workspace, "demo", "context: fork\nagent: helperr\n")
    assert _run(workspace) == [("skill-agent-missing", _missing_agent("helperr"), 4)]


def test_fork_to_a_miscased_agent_suggests_the_name(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID))
    _skill(workspace, "demo", "context: fork\nagent: Helper\n")
    assert _run(workspace) == [("skill-agent-missing", _missing_agent("Helper", "helper"), 4)]


def test_fork_to_a_custom_agent_resolves(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID))
    _skill(workspace, "demo", "context: fork\nagent: helper\n")
    assert _run(workspace) == []


def test_agent_without_fork_is_left_to_the_fork_option_rule(workspace: Workspace) -> None:
    _skill(workspace, "demo", "agent: helperr\n")
    assert _run(workspace) == []


def test_forked_command_to_a_missing_agent_is_an_error(workspace: Workspace) -> None:
    _command(workspace, "run.md", "context: fork\nagent: nobody\n")
    assert _run(workspace) == [("skill-agent-missing", _missing_agent("nobody"), 4)]


def test_fork_to_a_skipped_agent_is_an_error(workspace: Workspace) -> None:
    write(_repo(workspace) / AGENTS / "helper.md", _file("name: helper\n"))
    _skill(workspace, "demo", "context: fork\nagent: helper\n")
    assert _run(workspace) == [("skill-agent-missing", _missing_agent("helper"), 4)]


def _plugin(workspace: Workspace, files: dict[str, str], ids: tuple[str, ...] = (PLUGIN,)) -> None:
    installed: dict[str, list[dict[str, str]]] = {}
    for plugin_id in ids:
        install = workspace.home / "plugin-cache" / plugin_id.replace("@", "-")
        for relative, text in files.items():
            write(install / relative, text)
        write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": plugin_id.split("@")[0]}))
        installed[plugin_id] = [{"scope": "user", "installPath": str(install)}]
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps({"version": 2, "plugins": installed}))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": dict.fromkeys(ids, True)}))


def _plugin_found(workspace: Workspace) -> list[tuple[Layer | None, str, str]]:
    repo = _repo(workspace)
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.layer, finding.rule_id, finding.message) for finding in findings if finding.rule_id in REF_RULES]


def test_plugin_agent_resolves_its_own_skills_by_bare_name(workspace: Workspace) -> None:
    lint = _file("name: lint\ndescription: Lint.\nskills:\n  - style\n  - tools:style\n  - gone\n")
    _plugin(workspace, {"agents/lint.md": lint, "skills/style/SKILL.md": _file("description: Style.\n")})
    assert _plugin_found(workspace) == [(Layer.PLUGIN, "agent-skill-missing", _missing_skill("gone"))]


def test_other_agents_name_a_plugin_skill_with_its_prefix(workspace: Workspace) -> None:
    _plugin(workspace, {"skills/style/SKILL.md": _file("description: Style.\n"), "skills/strict/SKILL.md": _file("description: S.\n" + BLOCKS)})
    write(_repo(workspace) / AGENTS / "helper.md", _file(VALID + "skills:\n  - tools:style\n  - style\n  - tools:strict\n"))
    assert _plugin_found(workspace) == [
        (Layer.REPO, "agent-skill-missing", _missing_skill("style")),
        (Layer.REPO, "agent-skill-not-preloadable", _blocked("tools:strict")),
    ]


def test_two_installs_of_one_plugin_collide(workspace: Workspace) -> None:
    _plugin(workspace, {"agents/lint.md": _file("name: lint\ndescription: Lint.\n")}, ("tools@a", "tools@b"))
    repo = _repo(workspace)
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    fired = [(finding.path, finding.message) for finding in findings if finding.rule_id in REF_RULES]
    loser = workspace.home / "plugin-cache" / "tools-b" / "agents" / "lint.md"
    assert fired == [(loser, _collision("tools:lint", "~/plugin-cache/tools-a/agents/lint.md"))]


def test_plugin_skill_forks_to_its_own_agent_by_bare_name(workspace: Workspace) -> None:
    lint = _file("name: lint\ndescription: Lint.\n")
    fork = _file("description: Fork.\ncontext: fork\nagent: lint\n")
    other = _file("description: Other.\ncontext: fork\nagent: lnt\n")
    _plugin(workspace, {"agents/lint.md": lint, "skills/fork/SKILL.md": fork, "skills/other/SKILL.md": other})
    assert _plugin_found(workspace) == [(Layer.PLUGIN, "skill-agent-missing", _missing_agent("lnt"))]


def test_repo_skill_forks_to_a_plugin_agent_by_its_prefixed_name(workspace: Workspace) -> None:
    _plugin(workspace, {"agents/lint.md": _file("name: lint\ndescription: Lint.\n")})
    _skill(workspace, "demo", "context: fork\nagent: tools:lint\n")
    _skill(workspace, "bare", "context: fork\nagent: lint\n")
    assert _plugin_found(workspace) == [(Layer.REPO, "skill-agent-missing", _missing_agent("lint"))]


DISPATCH = "skill-dispatch-agent-missing"
DISPATCH_HEAD = "---\nname: demo\ndescription: Demo.\n---\n\n"
GHOST = 'dispatches agent "ghost", which names no built-in or custom subagent'


def _dispatch_found(workspace: Workspace, skill: str) -> list[tuple[str, int | None]]:
    repo = _repo(workspace)
    write(repo / AGENTS / "helper.md", _file(VALID))
    write(repo / SKILLS / "demo" / "SKILL.md", skill)
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == DISPATCH]


@pytest.mark.parametrize(
    "body",
    [
        "Dispatch the `ghost` agent with the brief.",
        "It dispatches `ghost`.",
        "Then it dispatched a `ghost`, and waits.",
        "Hand the diff to the `ghost` agent.",
        "The `ghost` subagent reviews it.",
        'Pass subagent_type: "ghost" to the tool.',
        'Call it with `subagent_type: "ghost"`.',
        'Call `Agent(subagent_type="ghost", prompt=brief)`.',
        "Pass `subagent_type`: `ghost` to the tool.",
    ],
)
def test_skill_dispatching_a_missing_agent_is_flagged(workspace: Workspace, body: str) -> None:
    assert _dispatch_found(workspace, f"{DISPATCH_HEAD}{body}\n") == [(GHOST, 6)]


@pytest.mark.parametrize(
    "body",
    [
        "Run the `dispatch` skill.",
        "Load the `plan-execution` skill.",
        "`nextup` loads the profile.",
        "Hand it to the profile's explore agent.",
        "Dispatch the `claude-security:explore` agent.",
        "Dispatch `general-purpose`.",
        "Dispatch the `helper` agent.",
        "Dispatch `ghost` with the brief.",
        "The `ghost` agent-native design.",
        "Pass `subagent_type=tools:worker`, `model=x` and no `ghost` id.",
        "Each seat's subagent_type must declare `ghost` in its tools.",
        "```text\nDispatch the `ghost` agent.\n```",
    ],
)
def test_skill_prose_that_dispatches_no_missing_agent_is_quiet(workspace: Workspace, body: str) -> None:
    assert _dispatch_found(workspace, f"{DISPATCH_HEAD}{body}\n") == []


def test_skill_dispatch_in_frontmatter_is_not_read(workspace: Workspace) -> None:
    assert _dispatch_found(workspace, "---\nname: demo\ndescription: Dispatch the `ghost` agent.\n---\n\nBody.\n") == []


def test_skill_dispatching_a_miscased_agent_suggests_the_name(workspace: Workspace) -> None:
    message = 'dispatches agent "Helper", which names no built-in or custom subagent (did you mean "helper"?)'
    assert _dispatch_found(workspace, f"{DISPATCH_HEAD}Dispatch the `Helper` agent.\n") == [(message, 6)]


def test_skill_dispatching_one_agent_twice_is_one_finding(workspace: Workspace) -> None:
    assert _dispatch_found(workspace, f"{DISPATCH_HEAD}Use the `ghost` agent.\n\nAgain, the `ghost` agent.\n") == [(GHOST, 6)]


def test_skill_dispatching_a_plugin_agent_by_bare_name_resolves(workspace: Workspace) -> None:
    _plugin(workspace, {"agents/lint.md": _file("name: lint\ndescription: Lint.\n")})
    assert _dispatch_found(workspace, f"{DISPATCH_HEAD}Dispatch the `lint` agent, then the `tools:lint` agent.\n") == []
