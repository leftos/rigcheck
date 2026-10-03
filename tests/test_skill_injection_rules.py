"""The skill and command body rules: injected shell commands, ``$N`` in prose and unused arguments."""

from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW
from rigcheck.rules import REGISTRY
from support import Workspace, write

SKILL = Path(".claude") / "skills" / "demo" / "SKILL.md"
COMMAND = Path(".claude") / "commands" / "x.md"
HEAD = "---\nname: demo\ndescription: Demo skill.\n---\n\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home, DEFAULT_WINDOW), REGISTRY.values())
    return [(finding.message, finding.line) for finding in findings if finding.rule_id == rule_id]


def _findings(workspace: Workspace, rule_id: str, text: str, path: Path = SKILL) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    write(repo / "CLAUDE.md", "# Project\n")
    write(repo / path, text)
    return _run(workspace, rule_id)


def _literal(char: str, command: str) -> str:
    return f"`!` right after `{char}` is not recognized, so `{command}` does not run; put a space or line start before `!`"


@pytest.mark.parametrize(
    ("body", "char", "command"),
    [
        ("KEY=!`date`", "=", "date"),
        ("(!`git status`)", "(", "git status"),
        ("Output:!`ls`", ":", "ls"),
        ("**!`cmd`**", "*", "cmd"),
    ],
)
def test_injection_literal_fires(workspace: Workspace, body: str, char: str, command: str) -> None:
    assert _findings(workspace, "skill-injection-literal", HEAD + body + "\n") == [(_literal(char, command), 6)]


@pytest.mark.parametrize(
    "body",
    ["- PR: !`gh pr diff`", "!`ls`", "`error!`", "`!`", "![img](x)", "a != b", "```\nKEY=!`date`\n```"],
)
def test_injection_literal_passes(workspace: Workspace, body: str) -> None:
    assert _findings(workspace, "skill-injection-literal", HEAD + body + "\n") == []


def test_injection_literal_fires_in_a_command(workspace: Workspace) -> None:
    text = "---\ndescription: X.\n---\nKEY=!`date`\n"
    assert _findings(workspace, "skill-injection-literal", text, COMMAND) == [(_literal("=", "date"), 4)]


def test_injection_literal_scans_the_body_of_rejected_frontmatter(workspace: Workspace) -> None:
    text = "---\ndescription: [unclosed\n---\nKEY=!`date`\n"
    assert _findings(workspace, "skill-injection-literal", text) == [(_literal("=", "date"), 4)]


def test_injection_literal_ignores_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-injection-literal", "---\nname: demo\ndescription: KEY=!`date`\n---\nBody.\n") == []


def _relative(word: str) -> str:
    return f"`{word}` in an injected command resolves against the session's current directory, which moves when Claude runs cd"


def test_relative_path_fires_on_a_bundled_script(workspace: Workspace) -> None:
    write(workspace.rig() / SKILL.parent / "scripts" / "fill.py", "print()\n")
    body = "Run: !`python scripts/fill.py`\n"
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body) == [(_relative("scripts/fill.py"), 6)]


def test_relative_path_fires_on_a_bundled_tool(workspace: Workspace) -> None:
    write(workspace.rig() / SKILL.parent / "tools" / "x.js", "\n")
    body = "Run: !`node tools/x.js`\n"
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body) == [(_relative("tools/x.js"), 6)]


@pytest.mark.parametrize(
    ("body", "word"),
    [
        ("Run: !`./run.sh`", "./run.sh"),
        ("Run: !`cat ../shared/x.md`", "../shared/x.md"),
        ("Run: !`git status && .\\run.ps1`", ".\\run.ps1"),
        ("Run: !`bin/tool --flag`", "bin/tool"),
        ("Run: !`echo a | ./one.sh && ./two.sh`", "./one.sh"),
        ("Run: !`X=./out.txt make`", "./out.txt"),
        ("Run: !`FOO=1 scripts/run.sh`", "scripts/run.sh"),
        ("Run: !`echo a#b ./x.sh`", "./x.sh"),
        ("Run: !`echo '# not a comment' ./x.sh`", "./x.sh"),
    ],
)
def test_relative_path_fires(workspace: Workspace, body: str, word: str) -> None:
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body + "\n") == [(_relative(word), 6)]


@pytest.mark.parametrize(
    "body",
    [
        'Run: !`python "${CLAUDE_SKILL_DIR}/scripts/fill.py"`',
        "Run: !`python $CLAUDE_SKILL_DIR/scripts/fill.py`",
        "Run: !`bash ${CLAUDE_PROJECT_DIR}/tools/x.sh`",
        "Run: !`git diff origin/main`",
        "Run: !`gh pr diff`",
        'Run: !`f="$(git rev-parse --show-toplevel)/docs/plans/x.md"; cat "$f"`',
        'Run: !`bash "$(git rev-parse --show-toplevel)/x.sh"`',
        'Run: !`"$(git rev-parse --show-toplevel)/x.sh"`',
        "Run: !`bash $CLAUDE_PLUGIN_ROOT/x.sh`",
        "Run: !`bash ${CLAUDE_PLUGIN_DATA}/x.sh`",
        "Run: !`bash ${HOME}/x.sh`",
        "Run: !`$HOMEBREW_PREFIX/bin/tool`",
        "Run: !`\\\\server\\share\\x.ps1`",
        "Run: !`git status # see ./x.sh`",
        "Run: !`git status; # ./x.sh`",
        "Run: !`cat ~/.gitconfig`",
        "Run: !`gh api repos/o/r`",
        "Run: !`curl https://example.com/a/b`",
        "Run: !`/usr/bin/env python`",
        "Run: !`C:\\tools\\x.exe`",
        "KEY=!`./run.sh`",
        "Run: `./run.sh`",
        "```bash\n./run.sh\n```",
    ],
)
def test_relative_path_passes(workspace: Workspace, body: str) -> None:
    write(workspace.rig() / SKILL.parent / "scripts" / "fill.py", "print()\n")
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body + "\n") == []


def test_relative_path_reports_the_fence_line(workspace: Workspace) -> None:
    body = "```!\ngit status\n# ./comment.sh\npython ./a.py && ./b.sh\n```\n"
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body) == [(_relative("./a.py"), 9)]


def test_relative_path_in_a_command_checks_prefixes_only(workspace: Workspace) -> None:
    write(workspace.rig() / "scripts" / "fill.py", "print()\n")
    text = "---\ndescription: X.\n---\n!`python scripts/fill.py`\n!`./run.sh`\n"
    assert _findings(workspace, "skill-injection-relative-path", text, COMMAND) == [(_relative("./run.sh"), 5)]


def test_relative_path_falls_back_on_an_unclosed_quote(workspace: Workspace) -> None:
    body = 'Run: !`cat "./a b`\n'
    assert _findings(workspace, "skill-injection-relative-path", HEAD + body) == [(_relative("./a"), 6)]


def _dollar(token: str) -> str:
    return f"`{token}` in prose is replaced by an argument when the skill is invoked; write `\\{token}`"


@pytest.mark.parametrize(
    ("body", "token"),
    [("It costs $1.00 a run.", "$1"), ("pay $5", "$5"), ("keep \\\\$1 here", "$1"), ("US$5", "$5")],
)
def test_dollar_digit_fires(workspace: Workspace, body: str, token: str) -> None:
    assert _findings(workspace, "skill-dollar-digit", HEAD + body + "\n") == [(_dollar(token), 6)]


@pytest.mark.parametrize(
    "body",
    [
        "It costs \\$1.00 a run.",
        "Use `$1` here",
        "```\necho $1\n```",
        "Use $ARGUMENTS",
        "Use $name",
        "    echo $1",
        '<b title="`$1`">x</b> `$1`',
        "[a](<`$1`>) `$1`",
        "[a](u '`$1`') `$1`",
        "<http://x/`$1`> `$1`",
        "![`$1`](u)",
    ],
)
def test_dollar_digit_passes(workspace: Workspace, body: str) -> None:
    assert _findings(workspace, "skill-dollar-digit", HEAD + body + "\n") == []


def test_dollar_digit_reports_each_occurrence(workspace: Workspace) -> None:
    body = "from $1 to $2\n\nthen $3\n"
    expected = [(_dollar("$1"), 6), (_dollar("$2"), 6), (_dollar("$3"), 8)]
    assert _findings(workspace, "skill-dollar-digit", HEAD + body) == expected


def test_dollar_digit_fires_in_a_command(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-dollar-digit", "Pay $5 now.\n", COMMAND) == [(_dollar("$5"), 1)]


def test_dollar_digit_ignores_frontmatter(workspace: Workspace) -> None:
    assert _findings(workspace, "skill-dollar-digit", "---\nname: demo\ndescription: costs $1\n---\nBody.\n") == []


def _unused(name: str) -> str:
    return f'arguments declares "{name}", but the body never uses ${name}'


def test_argument_unused_fires_for_a_string(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: D.\narguments: issue branch\n---\nFix $issue.\n"
    assert _findings(workspace, "skill-argument-unused", text) == [(_unused("branch"), 4)]


def test_argument_unused_fires_for_a_list(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: D.\narguments:\n  - issue\n  - branch\n---\nFix $branch.\n"
    assert _findings(workspace, "skill-argument-unused", text) == [(_unused("issue"), 4)]


def test_argument_unused_list_skips_duplicates_empties_and_non_strings(workspace: Workspace) -> None:
    items = "\n".join(f"  - {item}" for item in ("issue", "issue", '""', "3", "[x]", "branch"))
    text = f"---\nname: demo\ndescription: D.\narguments:\n{items}\n---\nFix $branch.\n"
    assert _findings(workspace, "skill-argument-unused", text) == [(_unused("issue"), 4)]


def test_argument_unused_fires_in_a_command(workspace: Workspace) -> None:
    text = "---\ndescription: D.\narguments: issue\n---\nUse $ARGUMENTS and $0.\n"
    assert _findings(workspace, "skill-argument-unused", text, COMMAND) == [(_unused("issue"), 3)]


@pytest.mark.parametrize(
    ("body", "unused"),
    [
        ("Fix $issue.", []),
        ("Run `gh issue view $issue`.", []),
        ("```\ngh issue view $issue\n```", []),
        ("Fix \\$issue.", ["issue"]),
        ("Fix \\\\$issue.", []),
        ("Fix $issues.", ["issue"]),
        ("Fix $issue-id.", ["issue"]),
        ("Fix $issue_x.", ["issue"]),
        ("Fix $ARGUMENTS.", ["issue"]),
    ],
)
def test_argument_unused_matches_whole_names(workspace: Workspace, body: str, unused: list[str]) -> None:
    text = f"---\nname: demo\ndescription: D.\narguments: issue\n---\n{body}\n"
    assert _findings(workspace, "skill-argument-unused", text) == [(_unused(name), 4) for name in unused]


@pytest.mark.parametrize("value", ["", "3", "{a: b}", "true"])
def test_argument_unused_skips_other_types(workspace: Workspace, value: str) -> None:
    text = f"---\nname: demo\ndescription: D.\narguments: {value}\n---\nBody.\n"
    assert _findings(workspace, "skill-argument-unused", text) == []


def test_argument_unused_ignores_the_frontmatter_itself(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: Uses $issue.\narguments: issue\n---\nBody.\n"
    assert _findings(workspace, "skill-argument-unused", text) == [(_unused("issue"), 4)]


RULE = "skill-injection-not-allowed"


def _not_allowed(program: str) -> str:
    return (
        f"injected command `{program}` is not covered by allowed-tools or a settings allow rule, "
        "so Claude Code aborts the invocation outside auto mode"
    )


def _allowed(tools: str, body: str) -> str:
    """A skill whose frontmatter allows ``tools`` and whose body is ``body``; the body starts on line 7."""
    return f"---\nname: demo\ndescription: Demo skill. Use when testing rigcheck fixtures.\nallowed-tools: {tools}\n---\n\n{body}"


def test_not_allowed_reports_uncovered_injection(workspace: Workspace) -> None:
    findings = _findings(workspace, RULE, _allowed("Bash(ls:*)", "Status: !`git status`\n"))
    assert len(findings) == 1
    message, line = findings[0]
    assert line == 7
    assert "`git`" in message
    assert "status" not in message


@pytest.mark.parametrize("tools", ["Bash(git status:*)", "Bash(git status *)"])
def test_not_allowed_silent_when_covered(workspace: Workspace, tools: str) -> None:
    assert _findings(workspace, RULE, _allowed(tools, "!`git status`\n")) == []


def test_not_allowed_silent_without_allowed_tools(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: Demo skill.\n---\n\n!`git status`\n"
    assert _findings(workspace, RULE, text) == []


@pytest.mark.parametrize("tools", ["Bash", "Bash(*)"])
def test_not_allowed_bare_bash_covers_all(workspace: Workspace, tools: str) -> None:
    assert _findings(workspace, RULE, _allowed(tools, "!`git status`\n")) == []


def test_not_allowed_empty_specifier_covers_nothing(workspace: Workspace) -> None:
    assert _findings(workspace, RULE, _allowed("Bash()", "!`git status`\n")) == [(_not_allowed("git"), 7)]


def test_not_allowed_non_bash_entries_cover_nothing(workspace: Workspace) -> None:
    assert _findings(workspace, RULE, _allowed("Read", "!`git status`\n")) == [(_not_allowed("git"), 7)]


@pytest.mark.parametrize(
    "text",
    [
        _allowed("Bash(git status:*), Read", "!`git status`\n"),
        "---\nname: demo\ndescription: D.\nallowed-tools:\n  - Bash(git status:*)\n  - Read\n---\n\n!`git status`\n",
    ],
)
def test_not_allowed_list_and_string_forms(workspace: Workspace, text: str) -> None:
    assert _findings(workspace, RULE, text) == []


def test_not_allowed_each_subcommand_must_be_covered(workspace: Workspace) -> None:
    text = _allowed("Bash(git status:*)", "!`git status && rm -rf build`\n")
    assert _findings(workspace, RULE, text) == [(_not_allowed("rm"), 7)]


@pytest.mark.parametrize(
    ("tools", "body", "program"),
    [
        ("Bash(git log:*)", "!`git log |& head`\n", "head"),
        ("Bash(git status:*)", "!`sleep 1 & git status`\n", "sleep"),
    ],
)
def test_not_allowed_splits_operators(workspace: Workspace, tools: str, body: str, program: str) -> None:
    assert _findings(workspace, RULE, _allowed(tools, body)) == [(_not_allowed(program), 7)]


@pytest.mark.parametrize("body", ["!`git status 2>&1`\n", "!`git status &>out.log`\n"])
def test_not_allowed_redirection_ampersand_is_not_a_separator(workspace: Workspace, body: str) -> None:
    assert _findings(workspace, RULE, _allowed("Bash(git status:*)", body)) == []


@pytest.mark.parametrize(
    ("tools", "body"),
    [
        ("Bash(ls:*)", "!`echo $(date)`\n"),
        ("Bash(ls:*)", "```!\nif true; then date; fi\n```\n"),
        ("Bash(ls:*)", "!`(cd x; date)`\n"),
        ("Bash(ls:*)", "!`date &&`\n"),
        ("Bash(ls:*)", "```!\ndate \\\n--utc\n```\n"),
        ("Bash(ls:*)", "```!\ncat <<EOF\n```\n"),
        ("Bash(ls:*)", "!`! git diff --quiet`\n"),
        ("Bash(date:*)", "!`date >| out.txt`\n"),
        ("Bash(echo:*)", "!`echo a\\&b`\n"),
        ("Bash(echo:*)", '```!\necho "a\\"&b"\n```\n'),
    ],
)
def test_not_allowed_skips_unanalysable(workspace: Workspace, tools: str, body: str) -> None:
    assert _findings(workspace, RULE, _allowed(tools, body)) == []


@pytest.mark.parametrize(
    ("tools", "body"),
    [
        ("Bash(ls:*)", "!`timeout 5 date`\n"),
        ("Bash(ls:*)", "!`FOO=1 date`\n"),
        ("Bash(timeout 5 date)", "!`timeout 5 date`\n"),
    ],
)
def test_not_allowed_skips_wrappers_and_assignments(workspace: Workspace, tools: str, body: str) -> None:
    assert _findings(workspace, RULE, _allowed(tools, body)) == []


@pytest.mark.parametrize("body", ["!`python ${CLAUDE_SKILL_DIR}/x.py`\n", "!`cat $1`\n", "!`echo $ARGUMENTS`\n"])
def test_not_allowed_skips_placeholders(workspace: Workspace, body: str) -> None:
    assert _findings(workspace, RULE, _allowed("Bash(ls:*)", body)) == []


def test_not_allowed_fence_reports_the_segment_line(workspace: Workspace) -> None:
    text = _allowed("Bash(ls:*)", "```!\nls\ndate\n```\n")
    assert _findings(workspace, RULE, text) == [(_not_allowed("date"), 9)]


def test_not_allowed_skips_literal_injection(workspace: Workspace) -> None:
    assert _findings(workspace, RULE, _allowed("Bash(ls:*)", "KEY=!`date`\n")) == []


def test_not_allowed_skips_non_bash_shell(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: D.\nallowed-tools: Bash(ls:*)\nshell: powershell\n---\n\n!`Get-Date`\n"
    assert _findings(workspace, RULE, text) == []


def test_not_allowed_blank_shell_is_bash(workspace: Workspace) -> None:
    text = "---\nname: demo\ndescription: D.\nallowed-tools: Bash(ls:*)\nshell:\n---\n\n!`date`\n"
    assert _findings(workspace, RULE, text) == [(_not_allowed("date"), 8)]


def test_not_allowed_settings_allow_covers(workspace: Workspace) -> None:
    text = _allowed("Read", "!`git status`\n")
    assert _findings(workspace, RULE, text) == [(_not_allowed("git"), 7)]
    write(workspace.rig() / ".claude" / "settings.json", '{"permissions": {"allow": ["Bash(git status:*)"]}}\n')
    assert _findings(workspace, RULE, text) == []


def test_not_allowed_checks_commands(workspace: Workspace) -> None:
    text = "---\ndescription: x\nallowed-tools: Bash(ls:*)\n---\n\n!`git status`\n"
    assert _findings(workspace, RULE, text, COMMAND) == [(_not_allowed("git"), 6)]
