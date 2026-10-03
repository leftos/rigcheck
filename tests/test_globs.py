"""Rule paths patterns: reading them, spotting unusable ones and matching them against repository files."""

from pathlib import Path

import pytest

from rigcheck.parse.globs import bracket_error, matches_any, matches_on_disk, matches_path, over_budget, rule_patterns
from support import write

FILES = frozenset({"src/app.ts", ".github/workflows/ci.yml", "docs/a.md"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("src/**", ["src/**"], id="string"),
        pytest.param(["src/**", 3, "docs/*.md"], ["src/**", "docs/*.md"], id="list-keeps-strings"),
        pytest.param({"src": "**"}, [], id="other-type"),
        pytest.param(None, [], id="none"),
        pytest.param(["  src/**  ", "", "   "], ["src/**"], id="strips-and-drops-blanks"),
        pytest.param("   ", [], id="blank-string"),
    ],
)
def test_rule_patterns(value: object, expected: list[str]) -> None:
    assert rule_patterns(value) == expected


@pytest.mark.parametrize(
    ("pattern", "invalid"),
    [
        pytest.param("photos [2024/**", True, id="unclosed-before-slash"),
        pytest.param("[", True, id="lone-bracket"),
        pytest.param("src/[a/b.py", True, id="close-past-slash"),
        pytest.param("docs/[draft.md", True, id="unclosed-at-end"),
        pytest.param("src/[abc].py", False, id="class"),
        pytest.param("src/[!a]*.py", False, id="negated-bang"),
        pytest.param("src/[^a]*.py", False, id="negated-caret"),
        pytest.param("docs/\\[draft\\]/*.md", False, id="escaped"),
        pytest.param("a]b", False, id="stray-close"),
        pytest.param("src/**/*.{ts,tsx}", False, id="braces"),
        pytest.param("[]a]", False, id="close-as-first-member"),
    ],
)
def test_bracket_error(pattern: str, invalid: bool) -> None:
    assert bracket_error(pattern) is invalid


@pytest.mark.parametrize(
    ("patterns", "over"),
    [
        pytest.param(["src/{a,b}/*.ts"], False, id="two-patterns"),
        pytest.param(["{1..1001}"], True, id="one-pattern-past-limit"),
        pytest.param(["{a,b}{1..500}"], False, id="exactly-at-limit"),
        pytest.param(["{a,b}{1..500}", "x"], True, id="shared-across-list"),
    ],
)
def test_over_budget(patterns: list[str], over: bool) -> None:
    assert over_budget(patterns) is over


@pytest.mark.parametrize(
    ("pattern", "matched"),
    [
        pytest.param("src/**/*.ts", True, id="globstar"),
        pytest.param("**/*.yml", True, id="dotfiles"),
        pytest.param("./docs/*.md", True, id="leading-dot-slash"),
        pytest.param("src/*.{ts,tsx}", True, id="braces"),
        pytest.param("lib/**", False, id="no-such-folder"),
        pytest.param("*.ts", False, id="star-anchored-at-root"),
    ],
)
def test_matches_any(pattern: str, matched: bool) -> None:
    assert matches_any(pattern, FILES) is matched


@pytest.mark.parametrize(
    ("pattern", "name", "matched"),
    [
        pytest.param("docs/**", "docs/deep/guide.md", True, id="globstar"),
        pytest.param("docs/**", "src/guide.md", False, id="other-folder"),
        pytest.param("./docs/*.md", "docs/guide.md", True, id="leading-dot-slash"),
        pytest.param("docs", "docs/guide.md", False, id="bare-folder-name-is-a-file"),
        pytest.param("docs", "docs", True, id="bare-name-matches-that-file"),
    ],
)
def test_matches_path(pattern: str, name: str, matched: bool) -> None:
    assert matches_path(pattern, name) is matched


@pytest.mark.parametrize(
    ("pattern", "matched"),
    [
        pytest.param("./src/**/*.c", True, id="hit"),
        pytest.param("lib/**/*.c", False, id="miss"),
        pytest.param("**/*.yml", True, id="dotfile-hit"),
    ],
)
def test_matches_on_disk(pattern: str, matched: bool, tmp_path: Path) -> None:
    write(tmp_path / "src" / "deep" / "a.c", "int a;\n")
    write(tmp_path / ".github" / "workflows" / "ci.yml", "on: push\n")
    assert matches_on_disk(pattern, tmp_path) is matched
