"""The skill and command body rules: injected shell commands, ``$N`` in prose and unused arguments."""

from pathlib import Path

import pytest

from rigcheck import engine
from rigcheck.discover import discover
from rigcheck.rules import REGISTRY
from support import Workspace, write

SKILL = Path(".claude") / "skills" / "demo" / "SKILL.md"
COMMAND = Path(".claude") / "commands" / "x.md"
HEAD = "---\nname: demo\ndescription: Demo skill.\n---\n\n"


def _run(workspace: Workspace, rule_id: str) -> list[tuple[str, int | None]]:
    repo = workspace.rig()
    findings = engine.run(discover(repo, workspace.home), REGISTRY.values())
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
