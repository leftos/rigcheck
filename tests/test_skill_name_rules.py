"""The skill name, fork-option, allowed-tools and command-key rules."""

import json
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import Layer
from rigcheck.rules import REGISTRY
from support import Workspace, write

COMMAND = Path(".claude") / "commands" / "x.md"
PLUGIN = "tools@market"

Found = tuple[Layer | None, str, int | None]


def _file(frontmatter: str) -> str:
    return f"---\n{frontmatter}---\n\nBody.\n"


def _skill(folder: str) -> Path:
    return Path(".claude") / "skills" / folder / "SKILL.md"


def _run(workspace: Workspace, rule_id: str) -> list[Found]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
    return [(finding.layer, finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _repo(workspace: Workspace, rule_id: str, text: str, path: Path) -> list[Found]:
    write(workspace.rig() / path, text)
    return _run(workspace, rule_id)


def _plugin(workspace: Workspace, rule_id: str, folder: str, text: str) -> list[Found]:
    install = workspace.home / "plugin-cache" / "tools"
    write(install / "skills" / folder / "SKILL.md", text)
    write(install / ".claude-plugin" / "plugin.json", json.dumps({"name": "tools"}))
    installed = {"version": 2, "plugins": {PLUGIN: [{"scope": "user", "installPath": str(install)}]}}
    write(workspace.home / ".claude" / "plugins" / "installed_plugins.json", json.dumps(installed))
    write(workspace.home / ".claude" / "settings.json", json.dumps({"enabledPlugins": {PLUGIN: True}}))
    return _run(workspace, rule_id)


def _user(workspace: Workspace, rule_id: str, folder: str, text: str) -> list[Found]:
    write(workspace.home / ".claude" / "skills" / folder / "SKILL.md", text)
    return _run(workspace, rule_id)


def _mismatch(name: str, folder: str = "demo") -> str:
    return f'name "{name}" differs from the folder "{folder}", so the skill answers to two names'


def _mismatch_repo(workspace: Workspace, name: str) -> list[Found]:
    return _repo(workspace, "skill-name-mismatch", _file(f"name: {name}\ndescription: D.\n"), _skill("demo"))


def _mismatch_plugin(workspace: Workspace, name: str) -> list[Found]:
    return _plugin(workspace, "skill-name-mismatch", "demo", _file(f"name: {name}\ndescription: D.\n"))


def test_name_mismatch_matching_name_passes(workspace: Workspace) -> None:
    assert _mismatch_repo(workspace, "demo") == []


def test_name_mismatch_case_difference_fires(workspace: Workspace) -> None:
    assert _mismatch_repo(workspace, "Demo") == [(Layer.REPO, _mismatch("Demo"), 2)]


def test_name_mismatch_plugin_prefixed_name_passes(workspace: Workspace) -> None:
    assert _mismatch_plugin(workspace, "tools:demo") == []


def test_name_mismatch_other_plugin_prefix_fires(workspace: Workspace) -> None:
    assert _mismatch_plugin(workspace, "other:demo") == [(Layer.PLUGIN, _mismatch("other:demo"), 2)]


def test_name_mismatch_plugin_prefix_in_a_repo_skill_fires(workspace: Workspace) -> None:
    assert _mismatch_repo(workspace, "tools:demo") == [(Layer.REPO, _mismatch("tools:demo"), 2)]


def test_name_mismatch_non_string_name_is_skipped(workspace: Workspace) -> None:
    assert _mismatch_repo(workspace, "3") == []


def _reserved(name: str, word: str) -> str:
    return f'the name "{name}" uses the reserved word "{word}"'


@pytest.mark.parametrize(
    ("name", "word"),
    [
        pytest.param("claude-helper", "claude", id="name_reserved_leading_part"),
        pytest.param("my-claude", "claude", id="name_reserved_trailing_part"),
        pytest.param("Claude-x", "claude", id="name_reserved_capitalised"),
        pytest.param("x-anthropic-y", "anthropic", id="name_reserved_middle_part"),
    ],
)
def test_name_reserved_fires(workspace: Workspace, name: str, word: str) -> None:
    text = _file(f"name: {name}\ndescription: D.\n")
    assert _repo(workspace, "skill-name-reserved", text, _skill(name)) == [(Layer.REPO, _reserved(name, word), 2)]


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("claudette", id="name_reserved_word_prefix_passes"),
        pytest.param("anthropics", id="name_reserved_word_plural_passes"),
        pytest.param("claude_helper", id="name_reserved_underscore_is_not_a_separator"),
    ],
)
def test_name_reserved_passes(workspace: Workspace, name: str) -> None:
    text = _file(f"name: {name}\ndescription: D.\n")
    assert _repo(workspace, "skill-name-reserved", text, _skill(name)) == []


def test_name_reserved_folder_and_name_are_reported_apart(workspace: Workspace) -> None:
    text = _file("name: anthropic-b\ndescription: D.\n")
    found = _repo(workspace, "skill-name-reserved", text, _skill("claude-a"))
    assert sorted(found, key=lambda item: item[2] or 0) == [
        (Layer.REPO, _reserved("claude-a", "claude"), 1),
        (Layer.REPO, _reserved("anthropic-b", "anthropic"), 2),
    ]


def test_name_reserved_plugin_skill_passes(workspace: Workspace) -> None:
    assert _plugin(workspace, "skill-name-reserved", "claude-x", _file("name: claude-x\ndescription: D.\n")) == []


def _fork(key: str) -> str:
    return f'"{key}" is set but context is not fork, so Claude Code ignores it'


def _fork_findings(workspace: Workspace, frontmatter: str) -> list[Found]:
    return _repo(workspace, "skill-fork-option-ignored", _file(f"description: D.\n{frontmatter}"), _skill("demo"))


def test_fork_agent_without_context_fires(workspace: Workspace) -> None:
    assert _fork_findings(workspace, "agent: Explore\n") == [(Layer.REPO, _fork("agent"), 3)]


def test_fork_background_with_inline_context_fires(workspace: Workspace) -> None:
    assert _fork_findings(workspace, "context: inline\nbackground: yes\n") == [(Layer.REPO, _fork("background"), 4)]


def test_fork_agent_with_fork_context_passes(workspace: Workspace) -> None:
    assert _fork_findings(workspace, "context: fork\nagent: Explore\n") == []


def test_fork_background_false_passes(workspace: Workspace) -> None:
    assert _fork_findings(workspace, "background: false\n") == []


def _broad(entry: str) -> str:
    return f'allowed-tools grants "{entry}" with no narrowing specifier, and workspace trust does not gate this field'


def _broad_findings(workspace: Workspace, value: str) -> list[Found]:
    text = _file(f"description: D.\nallowed-tools: {value}\n")
    return _repo(workspace, "skill-allowed-tools-broad", text, _skill("demo"))


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("Bash", id="broad_bare_bash"),
        pytest.param("Bash(*)", id="broad_bash_star"),
        pytest.param("Bash(:*)", id="broad_bash_colon_star"),
        pytest.param("Bash()", id="broad_bash_empty"),
        pytest.param("Bash( * )", id="broad_bash_spaced_star"),
        pytest.param("Write(*)", id="broad_write_star"),
        pytest.param("Edit", id="broad_bare_edit"),
        pytest.param("*", id="broad_wildcard"),
        pytest.param("Edit(**)", id="broad_edit_tree_glob"),
        pytest.param("Write(/**)", id="broad_write_root_tree_glob"),
        pytest.param("Edit(./**)", id="broad_edit_relative_tree_glob"),
        pytest.param("Bash(**)", id="broad_bash_tree_glob"),
    ],
)
def test_broad_entry_fires(workspace: Workspace, entry: str) -> None:
    assert _broad_findings(workspace, f'["{entry}"]') == [(Layer.REPO, _broad(entry), 3)]


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param("Bash(git status:*)", id="broad_bash_command_prefix_passes"),
        pytest.param("Bash(git:*)", id="broad_bash_short_prefix_passes"),
        pytest.param("Read", id="broad_read_passes"),
        pytest.param("bash", id="broad_lower_case_bash_passes"),
        pytest.param("MultiEdit", id="broad_multiedit_passes"),
        pytest.param("Write(docs/**)", id="broad_write_path_passes"),
        pytest.param("Edit(src/*.py)", id="broad_edit_file_glob_passes"),
        pytest.param("Edit(/docs/**)", id="broad_edit_rooted_folder_passes"),
    ],
)
def test_broad_entry_passes(workspace: Workspace, entry: str) -> None:
    assert _broad_findings(workspace, f'["{entry}"]') == []


@pytest.mark.parametrize(
    ("value", "entry"),
    [
        pytest.param("Read, Bash", "Bash", id="broad_comma_string"),
        pytest.param("Bash(git status) Edit", "Edit", id="broad_space_string_keeps_parentheses"),
        pytest.param('"[Read, Bash]"', "Bash", id="broad_flow_list_string"),
        pytest.param("\"['Bash', 'Read']\"", "Bash", id="broad_flow_list_string_with_quoted_items"),
    ],
)
def test_broad_string_value_fires_once(workspace: Workspace, value: str, entry: str) -> None:
    assert _broad_findings(workspace, value) == [(Layer.REPO, _broad(entry), 3)]


def test_broad_user_skill_passes(workspace: Workspace) -> None:
    assert _user(workspace, "skill-allowed-tools-broad", "demo", _file("description: D.\nallowed-tools: Bash\n")) == []


def _command_key(key: str) -> str:
    return f'"{key}" is not supported in a command file, so Claude Code ignores it'


def test_command_key_name_and_paths_fire(workspace: Workspace) -> None:
    text = _file("name: x\npaths: src/**\ndescription: D.\n")
    expected = [(Layer.REPO, _command_key("name"), 2), (Layer.REPO, _command_key("paths"), 3)]
    assert _repo(workspace, "command-key-ignored", text, COMMAND) == expected


def test_command_key_supported_keys_pass(workspace: Workspace) -> None:
    assert _repo(workspace, "command-key-ignored", _file("description: D.\nallowed-tools: Read\n"), COMMAND) == []
