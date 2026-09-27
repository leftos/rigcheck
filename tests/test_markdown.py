import pytest

from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import find_imports, strip_html_comments
from rigcheck.parse.tokens import estimate


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("See @README.md for details", ["README.md"]),
        ("@docs/git-instructions.md", ["docs/git-instructions.md"]),
        ("@~/.claude/my-rules.md", ["~/.claude/my-rules.md"]),
        ("Read @AGENTS.md.", ["AGENTS.md"]),
        ("(@AGENTS.md)", []),
        ("email a@b.com", []),
        ("`@foo.md`", []),
        ("```\n@foo.md\n```", []),
        ("    @indented.md", []),
        ("npm i @types/node", []),
        ("thanks @username", []),
        ("@./local", ["./local"]),
    ],
)
def test_find_imports_examples(text: str, expected: list[str]) -> None:
    assert [item.raw for item in find_imports(text)] == expected


def test_find_imports_reports_lines() -> None:
    text = "# Title\n\nfirst line\nsecond @a.md\n\n- item @b.md\n"
    assert [(item.line, item.raw) for item in find_imports(text)] == [(4, "a.md"), (6, "b.md")]


def test_strip_html_comments_keeps_code_and_line_count() -> None:
    text = "keep\n\n<!-- drop\n@x.md -->\n\n```\n<!-- kept -->\n```\n"
    stripped = strip_html_comments(text)
    assert "drop" not in stripped
    assert "<!-- kept -->" in stripped
    assert stripped.count("\n") == text.count("\n")


def test_frontmatter_cases() -> None:
    assert frontmatter.parse("# No frontmatter\n").present is False
    parsed = frontmatter.parse("﻿---\npaths:\n  - src/**\n---\nBody\n")
    assert parsed.data == {"paths": ["src/**"]}
    assert parsed.body_line == 5
    assert frontmatter.parse("---\nname: x\n").error == "unclosed frontmatter"
    assert frontmatter.parse("---\n- a\n---\n").error is not None
    assert frontmatter.parse("---\nkey: [unclosed\n---\n").error is not None
    assert frontmatter.parse("---\n---\n").data == {}


def test_token_estimate_rounds_up() -> None:
    assert estimate("") == 0
    assert estimate("abcd") == 2
    assert estimate("a" * 38) == 10
