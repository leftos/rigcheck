"""Parsing permission rules and matching Bash rule patterns."""

import pytest

from rigcheck.parse.permissions import PermissionRule, bash_covers, parse_rule


@pytest.mark.parametrize(
    ("raw", "tool", "specifier"),
    [
        ("Bash", "Bash", None),
        ("Bash(*)", "Bash", None),
        ("Bash()", "Bash", ""),
        ("Bash(npm run test:*)", "Bash", "npm run test:*"),
        ("Read(./secrets/**)", "Read", "./secrets/**"),
        ("mcp__srv__tool", "mcp__srv__tool", None),
        ("Bash(echo (a))", "Bash", "echo (a)"),
        ("Task(Explore)", "Agent", "Explore"),
    ],
)
def test_parse_rule_examples(raw: str, tool: str, specifier: str | None) -> None:
    assert parse_rule(raw) == PermissionRule(tool, specifier, raw)


@pytest.mark.parametrize("raw", ["Bash(ls", "Bash(ls) x", "Bash ls)", "", "(ls)"])
def test_parse_rule_malformed(raw: str) -> None:
    assert parse_rule(raw) is None


@pytest.mark.parametrize(
    ("pattern", "command", "expected"),
    [
        ("ls *", "ls", True),
        ("ls *", "ls -la", True),
        ("ls *", "lsof", False),
        ("ls*", "lsof", True),
        ("git:*", "git push", True),
        ("git:*", "git", True),
        ("git:*", "gitk", False),
        ("git push", "git push", True),
        ("git push", "git push --force", False),
        ("git * main", "git log --oneline main", True),
        ("git * main", "git log main x", False),
        ("* --help *", "npm --help x", True),
        ("* --help *", "npm --help", False),
        ("git:* push", "git push", False),
        ("git:* push", "git:x push", True),
    ],
)
def test_bash_covers(pattern: str, command: str, expected: bool) -> None:
    assert bash_covers(pattern, command) is expected
