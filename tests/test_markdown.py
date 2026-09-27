import pytest

from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import Reference, find_imports, find_references, strip_html_comments
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


def test_find_references_spans_and_links_with_lines() -> None:
    text = "# Title\n\nSee `docs/a.md` and\nthen [guide](docs/b.md) and `c/d`\n\n- item `e/f`\n"
    assert find_references(text) == [
        Reference(line=3, raw="docs/a.md", source="span", lang=""),
        Reference(line=4, raw="docs/b.md", source="link", lang=""),
        Reference(line=4, raw="c/d", source="span", lang=""),
        Reference(line=6, raw="e/f", source="span", lang=""),
    ]


def test_find_references_counts_hard_breaks() -> None:
    text = "first  \nsecond\\\nthird `x/y`\n"
    assert find_references(text) == [Reference(line=3, raw="x/y", source="span", lang="")]


def test_find_references_fence_lines() -> None:
    text = "intro\n\n```bash\nnpm run a\n\nmake b\n```\n\n    indented/code\n"
    assert find_references(text) == [
        Reference(line=4, raw="npm run a", source="fence", lang="bash"),
        Reference(line=5, raw="", source="fence", lang="bash"),
        Reference(line=6, raw="make b", source="fence", lang="bash"),
        Reference(line=9, raw="indented/code", source="fence", lang=""),
    ]


def test_find_references_skips_autolinks_images_and_comments() -> None:
    text = "<https://example.com/a>\n\n![pic](img/p.png)\n\n<!-- `docs/c.md` [x](docs/d.md) -->\n\n[ok](docs/e.md)\n"
    assert find_references(text) == [Reference(line=7, raw="docs/e.md", source="link", lang="")]


def test_find_references_skips_code_spans_in_link_text() -> None:
    text = "[`ground/`](docs/ground/README.md) then `after/x`\n"
    assert find_references(text) == [
        Reference(line=1, raw="docs/ground/README.md", source="link", lang=""),
        Reference(line=1, raw="after/x", source="span", lang=""),
    ]


def test_find_references_counts_lines_inside_multiline_code_spans() -> None:
    text = "A `multi\nline` span then `src/x.py` here\n"
    assert find_references(text) == [
        Reference(line=1, raw="multi line", source="span", lang=""),
        Reference(line=2, raw="src/x.py", source="span", lang=""),
    ]


def test_find_references_records_fence_language() -> None:
    text = "```Bash extra\nmake x\n```\n\n```\nmake y\n```\n\n~~~text\nmake z\n~~~\n"
    assert [(item.raw, item.lang) for item in find_references(text)] == [("make x", "bash"), ("make y", ""), ("make z", "text")]


LENIENT_KEYS = ("name", "description")


def test_read_lenient_reads_top_level_keys_and_strips_quotes() -> None:
    text = "---\nname: 'quoted'\nmetadata:\n  description: nested\nother: 1\n---\n\ndescription: body\n"
    assert frontmatter.read_lenient(text, LENIENT_KEYS) == {"name": "quoted"}


def test_read_lenient_continues_a_plain_value_on_more_indented_lines() -> None:
    text = "---\ndescription: Use this agent when X.\n  Examples: user asks Y\nname: fixer\n---\n"
    assert frontmatter.read_lenient(text, LENIENT_KEYS) == {"description": "Use this agent when X. Examples: user asks Y", "name": "fixer"}


@pytest.mark.parametrize("marker", ["", "|", ">", "|+", ">-", "|2", ">2-", "|-2"])
def test_read_lenient_joins_block_scalars(marker: str) -> None:
    text = f"---\ndescription: {marker}\n  Use when: it breaks\n\n  and again\nname: n\n---\n"
    assert frontmatter.read_lenient(text, LENIENT_KEYS) == {"description": "Use when: it breaks and again", "name": "n"}


def test_read_lenient_continues_a_quoted_value_to_its_closing_quote() -> None:
    text = "---\ndescription: 'multi\n  line'\nname: \"two\nlines: here\"\n---\n"
    assert frontmatter.read_lenient(text, LENIENT_KEYS) == {"description": "multi line", "name": "two lines: here"}


def test_read_lenient_ignores_unclosed_frontmatter() -> None:
    assert frontmatter.read_lenient("---\nname: x\n\ndescription: x\n", LENIENT_KEYS) == {}
    assert frontmatter.read_lenient("description: x\n", LENIENT_KEYS) == {}


def test_token_estimate_rounds_up() -> None:
    assert estimate("", 2.5) == 0
    assert estimate("abcd", 2.5) == 2
    assert estimate("a" * 25, 2.5) == 10
    assert estimate("a" * 31, 3.0) == 11
