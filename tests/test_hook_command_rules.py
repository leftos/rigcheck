"""The hook command rules: missing and relative scripts, unquoted placeholders, exec form, exit 1 and reprinted instructions."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.parse.shell import script_word
from rigcheck.rules import REGISTRY
from support import Workspace, git_add, write

SETTINGS = Path(".claude") / "settings.json"
GATE = Path(".claude") / "hooks" / "gate.sh"


def _handler(command: str, **extra: object) -> dict[str, object]:
    return {"type": "command", "command": command, **extra}


def _settings(event: str, *handlers: dict[str, object]) -> str:
    return json.dumps({"hooks": {event: [{"matcher": "Bash", "hooks": list(handlers)}]}}, indent=2) + "\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _messages(workspace: Workspace, rule_id: str, settings: str, files: dict[Path, str] | None = None) -> list[str]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SETTINGS, settings)
    for path, text in (files or {}).items():
        write(repo / path, text)
    return [message for message, _line in _run(workspace, rule_id)]


def _missing(word: str) -> str:
    return f'hook script "{word}" does not exist, so this hook is silently disabled'


def _not_executable(word: str) -> str:
    return f'hook script "{word}" is committed without the executable bit, so a fresh clone cannot run it'


def test_script_missing_resolves_project_dir(workspace: Workspace) -> None:
    settings = _settings(
        "PreToolUse",
        _handler('bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/gone.sh'),
        _handler('"${CLAUDE_PROJECT_DIR}/.claude/hooks/gate.sh"'),
        _handler("python3 tools/absent.py"),
    )
    found = _messages(workspace, "hook-script-missing", settings, {GATE: "#!/bin/sh\nexit 0\n"})
    assert found == [_missing("$CLAUDE_PROJECT_DIR/.claude/hooks/gone.sh"), _missing("tools/absent.py")]


def test_script_missing_skips_user_layer_project_dir(workspace: Workspace) -> None:
    user = _settings("PreToolUse", _handler('"$CLAUDE_PROJECT_DIR/.claude/hooks/gone.sh"'), _handler("~/.claude/hooks/gone.sh"))
    write(workspace.home / ".claude" / "settings.json", user)
    write(workspace.rig() / "CLAUDE.md", "# Project\n")
    assert [message for message, _line in _run(workspace, "hook-script-missing")] == [_missing("~/.claude/hooks/gone.sh")]


def _tracked_gate(workspace: Workspace, command: str, *, executable: bool) -> list[str]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SETTINGS, _settings("PreToolUse", _handler(command)))
    write(repo / GATE, "#!/bin/sh\nexit 0\n")
    git_add(repo, [GATE.as_posix()])
    if executable:
        git = shutil.which("git")
        assert git is not None
        # Test-owned arguments: a tmp repo path and a fixed file name.
        subprocess.run([git, "-C", str(repo), "update-index", "--chmod=+x", GATE.as_posix()], check=True)  # noqa: S603
    return [message for message, _line in _run(workspace, "hook-script-missing")]


def test_script_missing_reports_non_executable_tracked_script(workspace: Workspace) -> None:
    word = "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"
    assert _tracked_gate(workspace, f'"{word}"', executable=False) == [_not_executable(word)]


def test_script_missing_passes_executable_tracked_script(workspace: Workspace) -> None:
    assert _tracked_gate(workspace, '"$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"', executable=True) == []


def test_script_run_by_interpreter_needs_no_exec_bit(workspace: Workspace) -> None:
    assert _tracked_gate(workspace, 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"', executable=False) == []


def test_combined_inline_flag_has_no_script(workspace: Workspace) -> None:
    command = 'bash -lc "$CLAUDE_PROJECT_DIR/x.sh --fast"'
    assert script_word(command) is None
    assert _messages(workspace, "hook-script-missing", _settings("PreToolUse", _handler(command))) == []


def _git(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    # Test-owned arguments: a tmp repo path and fixed git subcommands.
    return subprocess.run([git, "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()  # noqa: S603


def test_exec_bit_skips_symlink_and_windows_scripts(workspace: Workspace) -> None:
    repo = workspace.rig()
    hooks = Path(".claude") / "hooks"
    names = ["gate.PS1", "gate.cmd", "link.sh"]
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SETTINGS, _settings("PreToolUse", *(_handler(f'"$CLAUDE_PROJECT_DIR/.claude/hooks/{name}"') for name in names)))
    for name in names:
        write(repo / hooks / name, "exit 0\n")
    git_add(repo, [(hooks / name).as_posix() for name in names])
    link = (hooks / "link.sh").as_posix()
    _git(repo, "update-index", "--cacheinfo", f"120000,{_git(repo, 'hash-object', link)},{link}")
    assert [message for message, _line in _run(workspace, "hook-script-missing")] == []


def _relative(word: str) -> str:
    return f'hook script "{word}" is relative, so it breaks when Claude Code runs from another folder'


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("python3 scripts/check.py", [_relative("scripts/check.py")]),
        ("bash ./gate.sh", [_relative("./gate.sh")]),
        (".claude/hooks/gate.sh --strict", [_relative(".claude/hooks/gate.sh")]),
        ("FOO=1 uv run tools\\check.py", [_relative("tools\\check.py")]),
        ('bash "$CLAUDE_PROJECT_DIR/gate.sh"', []),
        ('cd "$CLAUDE_PROJECT_DIR" && ./gate.sh', []),
        ("jq -r .tool_input.command", []),
    ],
)
def test_relative_script_after_interpreter(workspace: Workspace, command: str, expected: list[str]) -> None:
    assert _messages(workspace, "hook-script-relative", _settings("PreToolUse", _handler(command))) == expected


def _unquoted(placeholder: str) -> str:
    return f"{placeholder} is not in double quotes, so a path with spaces splits"


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (_handler("bash $CLAUDE_PROJECT_DIR/a.sh ${CLAUDE_PLUGIN_ROOT}"), [_unquoted("$CLAUDE_PROJECT_DIR")]),
        (_handler('"$CLAUDE_PROJECT_DIR"/.claude/hooks/gate.sh'), []),
        (_handler('bash "${CLAUDE_PROJECT_DIR}/.claude/hooks/gate.sh"'), []),
        (_handler("echo '$CLAUDE_PROJECT_DIR'"), []),
        (_handler("${CLAUDE_PROJECT_DIR}/.claude/hooks/gate.sh", args=["--strict"]), []),
    ],
)
def test_placeholder_quoted_forms_are_silent(workspace: Workspace, handler: dict[str, object], expected: list[str]) -> None:
    found = _messages(workspace, "hook-placeholder-unquoted", _settings("PreToolUse", handler), {GATE: "#!/bin/sh\n"})
    assert found == expected


@pytest.mark.parametrize(
    ("handler", "expected"),
    [
        (_handler("node server.js", args=["--check"]), ['command "node server.js" holds whitespace alongside args, so the spawn fails']),
        (_handler("node server.js"), []),
        (_handler("node", args=["server.js"]), []),
        (_handler("/opt/my tools/run", args=[]), []),
        (_handler("node server.js", args="--check"), []),
    ],
)
def test_exec_form_spawn_needs_args_list(workspace: Workspace, handler: dict[str, object], expected: list[str]) -> None:
    assert _messages(workspace, "hook-exec-form-spawn", _settings("PreToolUse", handler)) == expected


def _exit_1(event: str) -> str:
    return f"exit 1 does not block {event}; Claude Code treats it as a non-blocking error"


@pytest.mark.parametrize(
    ("command", "script", "expected"),
    [
        ("test -f ok || exit 1", None, [_exit_1("PreToolUse")]),
        ('bash "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"', "#!/bin/sh\nexit 1\n", [_exit_1("PreToolUse")]),
        ("test -f ok || exit 1; exit 2", None, []),
        ('bash "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"', "#!/bin/sh\n[ -f ok ] || exit 2\nexit 1\n", []),
        ('bash "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"', '#!/bin/sh\necho \'{"decision": "block"}\'\nexit 1\n', []),
        ("echo permissionDecision; exit 1", None, []),
        ("exit 10", None, []),
    ],
)
def test_exit_1_skipped_with_exit_2_or_json(workspace: Workspace, command: str, script: str | None, expected: list[str]) -> None:
    files = {GATE: script} if script is not None else {}
    assert _messages(workspace, "hook-exit-1-blocking", _settings("PreToolUse", _handler(command)), files) == expected


@pytest.mark.parametrize(("event", "fires"), [("PermissionRequest", False), ("PostToolUse", False), ("Stop", True)])
def test_exit_1_ignored_on_permission_request(workspace: Workspace, event: str, fires: bool) -> None:
    expected = [_exit_1(event)] if fires else []
    assert _messages(workspace, "hook-exit-1-blocking", _settings(event, _handler("exit 1"))) == expected


def _reprints(name: str) -> str:
    return f"SessionStart hook prints {name}, which Claude Code already loads, so it is in context twice"


RUN_GATE = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/gate.sh"'


@pytest.mark.parametrize(
    ("event", "command", "script", "expected"),
    [
        ("SessionStart", RUN_GATE, 'set -e\ncat "$CLAUDE_PROJECT_DIR/AGENTS.md"\n', [_reprints("AGENTS.md")]),
        ("SessionStart", RUN_GATE, "# cat AGENTS.md\necho ready\n", []),
        ("SessionStart", "Get-Content -Raw CLAUDE.md", None, [_reprints("CLAUDE.md")]),
        ("SessionStart", "cat docs/STATUS.md", None, []),
        ("PreToolUse", "cat CLAUDE.md", None, []),
    ],
)
def test_reprints_instructions_in_script(workspace: Workspace, event: str, command: str, script: str | None, expected: list[str]) -> None:
    files = {GATE: script} if script is not None else {}
    assert _messages(workspace, "hook-reprints-instructions", _settings(event, _handler(command)), files) == expected


def test_line_points_at_command(workspace: Workspace) -> None:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SETTINGS, _settings("PreToolUse", _handler("echo first"), _handler("bash ./gate.sh")))
    skill = (
        "---\nname: demo\ndescription: Demo skill.\nhooks:\n  PreToolUse:\n    - matcher: Bash\n"
        "      hooks:\n        - type: command\n          command: ./check.sh\n---\n\nBody.\n"
    )
    write(repo / ".claude" / "skills" / "demo" / "SKILL.md", skill)
    found = _run(workspace, "hook-script-relative")
    assert len(found) == 2
    assert {line for _message, line in found} == {9, 13}


def test_line_for_shared_command_under_two_events(workspace: Workspace) -> None:
    groups = {
        "PreToolUse": [{"matcher": "Bash", "hooks": [_handler("bash ./gate.sh")]}],
        "PostToolUse": [{"matcher": "Bash", "hooks": [_handler("./gate.sh"), _handler("bash ./gate.sh")]}],
    }
    found = _messages_and_lines(workspace, json.dumps({"hooks": groups}, indent=2) + "\n")
    assert len(found) == 3
    assert {line for _message, line in found} == {9, 20, 24}


def _messages_and_lines(workspace: Workspace, settings: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / SETTINGS, settings)
    return _run(workspace, "hook-script-relative")
