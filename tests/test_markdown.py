import pytest
from markdown_it.token import Token

from rigcheck.parse import frontmatter, markdown
from rigcheck.parse.markdown import Injection, Reference, find_imports, find_injections, find_references, prose_segments, strip_html_comments
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
    assert frontmatter.parse("---\nname: x\n").strict_error == "unclosed frontmatter"
    assert frontmatter.parse("---\nname: x\n").load_error == "unclosed frontmatter"
    assert frontmatter.parse("---\n- a\n---\n").strict_error is not None
    assert frontmatter.parse("---\n- a\n---\n").load_error is not None
    assert frontmatter.parse("---\nkey: [unclosed\n---\n").strict_error is not None
    assert frontmatter.parse("---\n---\n").data == {}


def test_frontmatter_parsed_once_per_text(monkeypatch: pytest.MonkeyPatch) -> None:
    loads: list[str] = []
    safe_load = frontmatter.yaml.safe_load

    def counting(stream: str) -> object:
        loads.append(stream)
        return safe_load(stream)

    monkeypatch.setattr(frontmatter.yaml, "safe_load", counting)
    text = "---\nname: once\n---\nBody\n"
    assert frontmatter.parse(text) == frontmatter.parse(text)
    assert len(loads) == 1


def test_markdown_parsed_once_per_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    parse = markdown._PARSER.parse

    def counting(src: str) -> list[Token]:
        calls.append(src)
        return parse(src)

    monkeypatch.setattr(markdown._PARSER, "parse", counting)
    text = "# Title\n\nSee `a.md`, [b](b.md) and @c.md.\n\n!`date`\n"
    find_references(text)
    find_injections(text, 1)
    prose_segments(text, 1)
    find_imports(text)
    assert len(calls) == 1


def test_markdown_with_comments_parsed_at_most_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    parse = markdown._PARSER.parse

    def counting(src: str) -> list[Token]:
        calls.append(src)
        return parse(src)

    monkeypatch.setattr(markdown._PARSER, "parse", counting)
    text = "# Title\r\n\r\n<!-- note @hidden.md -->\r\n\r\nSee `a.md` and @c.md.\r\n\r\n!`date`\r\n"
    find_references(text)
    find_imports(text)
    find_injections(text, 1)
    prose_segments(text, 1)
    find_references(text)
    assert len(calls) <= 2


def _probe_text(lines: list[str], eol: str, bom: bool) -> str:
    return ("\ufeff" if bom else "") + eol.join(["---", "name: v", *lines, "---", "", "Body."]) + eol


LF, CRLF = "\n", "\r\n"
REJECTED = None

# One row per variant of the `claude plugin validate` probe: (lines after `name: v`, line ending, BOM, extra keys Claude Code loads or
# REJECTED, strict YAML loads it).
PROBE_ROWS = {
    "plain": (["description: simple text"], LF, False, {"description": "simple text"}, True),
    "colon": (["description: use when: it breaks"], LF, False, {"description": "use when: it breaks"}, False),
    "colon-trailing": (["description: use when:"], LF, False, REJECTED, False),
    "colon-dq-inside": (['description: say "a b" then: c'], LF, False, {"description": 'say "a b" then: c'}, False),
    "colon-sq-inside": (["description: it's here: now"], LF, False, {"description": "it's here: now"}, False),
    "colon-dq-apostrophe": (
        ['description: phrases "don\'t do x", "y z": more'],
        LF,
        False,
        {"description": 'phrases "don\'t do x", "y z": more'},
        False,
    ),
    "dq-start-continues": (['description: "quoted" then more'], LF, False, REJECTED, False),
    "dq-start-continues-colon": (['description: "quoted" then: more'], LF, False, {"description": '"quoted" then: more'}, False),
    "sq-start-continues": (["description: 'quoted' then more"], LF, False, REJECTED, False),
    "dq-start-unclosed": (['description: "never closed'], LF, False, REJECTED, False),
    "hash": (["description: a # comment"], LF, False, {"description": "a"}, True),
    "hash-colon": (["description: a: b # c"], LF, False, {"description": "a: b # c"}, False),
    "hash-nospace": (["description: a#b: c"], LF, False, {"description": "a#b: c"}, False),
    "emdash": (["description: a \u2014 b"], LF, False, {"description": "a \u2014 b"}, True),
    "emdash-colon": (["description: a \u2014 b: c"], LF, False, {"description": "a \u2014 b: c"}, False),
    "multiline": (["description: first line", "  second line"], LF, False, {"description": "first line second line"}, True),
    "multiline-colon-first": (["description: first: line", "  second line"], LF, False, REJECTED, False),
    "multiline-colon-second": (["description: first line", "  second: line"], LF, False, REJECTED, False),
    "block-literal-colon": (["description: |", "  first: line", "  second"], LF, False, {"description": "first: line\nsecond"}, True),
    "list": (["description: d", "allowed-tools:", "  - Read", "  - Grep"], LF, False, {"description": "d", "allowed-tools": ["Read", "Grep"]}, True),
    "list-colon": (
        ["description: use when: x", "allowed-tools:", "  - Read", "  - Grep"],
        LF,
        False,
        {"description": "use when: x", "allowed-tools": ["Read", "Grep"]},
        False,
    ),
    "flow-list-colon": (
        ["description: use when: x", "allowed-tools: [Read, Grep]"],
        LF,
        False,
        {"description": "use when: x", "allowed-tools": "[Read, Grep]"},
        False,
    ),
    "bom": (["description: simple text"], LF, True, {"description": "simple text"}, True),
    "bom-colon": (["description: use when: x"], LF, True, {"description": "use when: x"}, False),
    "crlf": (["description: simple text"], CRLF, False, {"description": "simple text"}, True),
    "crlf-colon": (["description: use when: x"], CRLF, False, REJECTED, False),
    "crlf-colon-dq-apostrophe-emdash": (['description: phrases "don\'t do x", "y z": more \u2014 end'], CRLF, False, REJECTED, False),
    "crlf-list-colon": (["description: use when: x", "allowed-tools:", "  - Read"], CRLF, False, REJECTED, False),
    "tab-continuation": (["description: first", "\tsecond"], LF, False, {"description": "first second"}, False),
    "tab-list": (["description: d", "allowed-tools:", "\t- Read"], LF, False, {"description": "d", "allowed-tools": ["Read"]}, False),
    "flow-start-colon": (["description: [a: b"], LF, False, {"description": "[a: b"}, False),
    "brace-start-colon": (["description: {a: b"], LF, False, {"description": "{a: b"}, False),
    "at-start-colon": (["description: @a: b"], LF, False, {"description": "@a: b"}, False),
    "backtick-start-colon": (["description: `a`: b"], LF, False, {"description": "`a`: b"}, False),
    "star-start-colon": (["description: *a: b"], LF, False, {"description": "*a: b"}, False),
    "amp-start-colon": (["description: &a: b"], LF, False, {"description": "&a: b"}, False),
    "backslash-colon": (["description: a\\b: c"], LF, False, {"description": "a\\b: c"}, False),
    "colon-then-key": (["description: a: b", "model: sonnet"], LF, False, {"description": "a: b", "model": "sonnet"}, False),
    "dup-key": (["description: a", "description: b"], LF, False, {"description": "b"}, True),
    "key-colon-only-junk": (["description: a", "not a key line"], LF, False, REJECTED, False),
    "indented-key-colon": (["description: a", "  nested: b: c"], LF, False, REJECTED, False),
    "hyphen-key-colon": (["description: d", "argument-hint: a: b"], LF, False, {"description": "d", "argument-hint": "a: b"}, False),
    "underscore-key-colon": (["description: d", "my_key: a: b"], LF, False, {"description": "d", "my_key": "a: b"}, False),
    "digit-key-colon": (["description: d", "key2: a: b"], LF, False, REJECTED, False),
    "at-start": (["description: @a b"], LF, False, {"description": "@a b"}, False),
    "backtick-start": (["description: `a` b"], LF, False, {"description": "`a` b"}, False),
    "star-start": (["description: *a b"], LF, False, {"description": "*a b"}, False),
    "brace-start": (["description: {a b"], LF, False, {"description": "{a b"}, False),
    "bracket-start": (["description: [a b"], LF, False, {"description": "[a b"}, False),
    "bracket-inside": (["description: a [b"], LF, False, {"description": "a [b"}, True),
    "pipe-start": (["description: |a b"], LF, False, {"description": "|a b"}, False),
    "gt-start": (["description: >a b"], LF, False, {"description": ">a b"}, False),
    "percent-start": (["description: %a b"], LF, False, {"description": "%a b"}, False),
    "bang-start-junk": (["description: !a !b c"], LF, False, {"description": "!a !b c"}, False),
    "quoted-both-ends-colon": (['description: "a" b: "c"'], LF, False, REJECTED, False),
    "sq-both-ends-colon": (["description: 'a' b: 'c'"], LF, False, REJECTED, False),
    "backslash-bad-escape-colon": (["description: a\\q: c"], LF, False, {"description": "a\\q: c"}, False),
    "upper-key-colon": (["description: d", "Foo: a: b"], LF, False, {"description": "d", "Foo": "a: b"}, False),
    "two-space-colon": (["description:  a: b"], LF, False, {"description": "a: b"}, False),
    "tab-after-key-colon": (["description:\ta: b"], LF, False, {"description": "a: b"}, False),
    "trailing-space-colon": (["description: a: b   "], LF, False, {"description": "a: b   "}, False),
    "colon-in-list-item": (["description: d", "allowed-tools:", "  - a: b: c"], LF, False, REJECTED, False),
    "agent-colon": (
        ["description: use when: it breaks", "tools: Read, Grep"],
        LF,
        False,
        {"description": "use when: it breaks", "tools": "Read, Grep"},
        False,
    ),
    "agent-dq-inside-colon": (
        ['description: Use it. "a b, c d" then e: f', "tools: Read, mcp__s__t"],
        LF,
        False,
        {"description": 'Use it. "a b, c d" then e: f', "tools": "Read, mcp__s__t"},
        False,
    ),
    "agent-crlf-colon": (["description: use when: it breaks"], CRLF, False, REJECTED, False),
    "agent-crlf-plain": (["description: plain"], CRLF, False, {"description": "plain"}, True),
}


@pytest.mark.parametrize(("lines", "eol", "bom", "loaded", "strict_loads"), list(PROBE_ROWS.values()), ids=list(PROBE_ROWS))
def test_frontmatter_loads_as_claude_code_does(lines: list[str], eol: str, bom: bool, loaded: dict[str, object] | None, strict_loads: bool) -> None:
    parsed = frontmatter.parse(_probe_text(lines, eol, bom))
    assert parsed.data == (None if loaded is None else {"name": "v", **loaded})
    assert (parsed.strict_error is None) is strict_loads
    assert (parsed.load_error is None) is (loaded is not None)
    assert parsed.body_line == len(lines) + 4


def test_frontmatter_key_lines_are_file_lines() -> None:
    parsed = frontmatter.parse("---\nname: x\ndescription: y\ntools:\n  - a\n---\nBody.\n")
    assert parsed.key_lines == {"name": 2, "description": 3, "tools": 4}


def test_frontmatter_key_lines_on_a_block_claude_code_rejects() -> None:
    parsed = frontmatter.parse("---\nname: x\n\ndescription: a: b\r\n---\n")
    assert parsed.data is None
    assert parsed.key_lines == {"name": 2, "description": 4}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('---\n"name": n\ndescription: d\n---\n', {"name": 2, "description": 3}),
        ("---\n'name': n\ndescription: d\n---\n", {"name": 2, "description": 3}),
        ("---\n1: x\ndescription: d\n---\n", {"1": 2, "description": 3}),
    ],
    ids=["double-quoted", "single-quoted", "integer"],
)
def test_key_lines_reads_a_quoted_key(text: str, expected: dict[str, int]) -> None:
    assert frontmatter.parse(text).key_lines == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (1, True),
        ("true", True),
        ("Yes", True),
        ("ON", True),
        ("1", True),
        (False, False),
        (0, False),
        ("false", False),
        ("No", False),
        ("off", False),
        ("0", False),
        (None, None),
        (2, None),
        ("maybe", None),
        ("", None),
        (1.0, None),
        (["true"], None),
    ],
)
def test_as_bool(value: object, expected: bool | None) -> None:
    assert frontmatter.as_bool(value) is expected


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


def test_find_references_skips_autolinks_and_comments_and_reports_images() -> None:
    text = "<https://example.com/a>\n\n![pic](img/p.png)\n\n<!-- `docs/c.md` [x](docs/d.md) -->\n\n[ok](docs/e.md)\n"
    assert find_references(text) == [
        Reference(line=3, raw="img/p.png", source="image", lang=""),
        Reference(line=7, raw="docs/e.md", source="link", lang=""),
    ]


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


def test_read_lenient_reads_a_dotted_key_under_its_parent() -> None:
    text = "---\ndescription: Use when: x breaks\nmetadata:\n  name: m\n  type: 'user'\n    continued\nother:\n  type: no\ntype: top\n---\n"
    keys = ("type", "metadata.type", "other.name")
    assert frontmatter.read_lenient(text, keys) == {"metadata.type": "user continued", "type": "top"}


def test_read_lenient_nests_one_level_only() -> None:
    text = "---\nmetadata:\n  inner:\n    type: deep\n  type: user\n---\n"
    assert frontmatter.read_lenient(text, ("metadata.type", "metadata.inner.type", "type")) == {"metadata.type": "user"}


def test_read_lenient_ignores_a_top_level_dotted_key() -> None:
    text = "---\ndescription: Use when: x breaks\nmetadata.type: bogus\n---\n"
    assert frontmatter.parse(text).strict_error is not None
    assert frontmatter.read_lenient(text, ("metadata.type",)) == {}


def test_read_lenient_skips_a_parent_with_an_inline_value() -> None:
    assert frontmatter.read_lenient("---\nmetadata: {type: user}\n---\n", ("metadata.type",)) == {}


def test_read_lenient_ignores_unclosed_frontmatter() -> None:
    assert frontmatter.read_lenient("---\nname: x\n\ndescription: x\n", LENIENT_KEYS) == {}
    assert frontmatter.read_lenient("description: x\n", LENIENT_KEYS) == {}


def test_token_estimate_rounds_up() -> None:
    assert estimate("", 2.5) == 0
    assert estimate("abcd", 2.5) == 2
    assert estimate("a" * 25, 2.5) == 10
    assert estimate("a" * 31, 3.0) == 11


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("- PR: !`gh pr diff`", [("gh pr diff", False)]),
        ("!`ls`", [("ls", False)]),
        ("first\n!`ls`", [("ls", False)]),
        ("first  \n!`ls`", [("ls", False)]),
        ("a\t!`ls`", [("ls", False)]),
        ("KEY=!`date`", [("date", True)]),
        ("(!`git status`)", [("git status", True)]),
        ("Output:!`ls`", [("ls", True)]),
        ("**!`cmd`**", [("cmd", True)]),
        ("`error!`", []),
        ("`!`", []),
        ("![img](x)", []),
        ("a != b", []),
        ("`a`!`b`", [("b", True)]),
        ("`a` !`b`", [("b", False)]),
        ("<b>!`b`", [("b", True)]),
        ("[run !`ls`](x)", []),
        ("```\n!`ls`\n```", []),
        ("    !`ls`", []),
        ("```bash\necho hi\n```", []),
        ("\\!`ls`", []),
        ("x \\!`ls`", []),
        ("&#33;`ls`", []),
        ("a \\\\!`ls`", [("ls", True)]),
        ("[a][r]!`ls`\n\n[r]: http://x", [("ls", True)]),
        ("~~~!\n./x\n~~~", []),
        ("[`x`](u) !`ls`", [("ls", False)]),
    ],
)
def test_find_injections_inline_examples(text: str, expected: list[tuple[str, bool]]) -> None:
    assert [(item.command, item.literal) for item in find_injections(text, 1)] == expected


def test_find_injections_reports_lines_and_form() -> None:
    text = "# T\n\nintro\nnext !`a`\n\n```!\ngit status\ngit diff\n```\n"
    assert find_injections(text, 1) == [
        Injection(line=4, command="a", form="inline", literal=False, after=" "),
        Injection(line=7, command="git status\ngit diff\n", form="fence", literal=False, after=""),
    ]


def test_find_injections_skips_tokens_before_the_start_line() -> None:
    text = "---\nname: !`x`\n---\n\n!`ls`\n"
    assert [(item.line, item.command) for item in find_injections(text, 4)] == [(5, "ls")]
    assert [item.command for item in find_injections(text, 1)] == ["x", "ls"]


def test_find_injections_counts_lines_across_a_multiline_span() -> None:
    text = "a `b\nc` d\n!`ls`\n"
    assert [(item.line, item.command) for item in find_injections(text, 1)] == [(3, "ls")]


def test_find_injections_places_spans_after_inline_html() -> None:
    text = '<b title="`a b`">x</b> `a\nb`\nKEY=!`z`\n'
    assert [(item.line, item.command, item.after) for item in find_injections(text, 1)] == [(3, "z", "=")]


def test_find_injections_counts_lines_in_a_link_title() -> None:
    text = '[a](u "t\nu") x\nKEY=!`z`\n'
    assert [(item.line, item.command) for item in find_injections(text, 1)] == [(3, "z")]


def test_find_references_places_spans_after_inline_html() -> None:
    text = '<b title="`a b`">x</b> `a\nb`\n`c`\n'
    assert [(item.line, item.raw) for item in find_references(text) if item.source == "span"] == [(1, "a b"), (3, "c")]


@pytest.mark.parametrize(
    "text",
    ['<b title="`$1`">x</b> `$1`', "[a](<`$1`>) `$1`", "[a](u '`$1`') `$1`", "<http://x/`$1`> `$1`", "![`$1`](u)"],
)
def test_prose_segments_blank_what_holds_no_prose(text: str) -> None:
    assert "$1" not in "".join(segment for _line, segment in prose_segments(text, 1))


def test_prose_segments_keep_image_alt_prose() -> None:
    assert prose_segments("![costs $1 `x`](u)", 1) == [(1, "![costs $1    " + " " * 4)]


def test_prose_segments_blank_code_spans_and_skip_blocks() -> None:
    text = "costs $1 and `$2` here\nnext \\$3\n\n```\n$4\n```\n\n    $5\n\n<div>\n$6\n</div>\n"
    assert prose_segments(text, 1) == [(1, "costs $1 and      here"), (2, "next \\$3")]


def test_prose_segments_keep_offsets_across_a_multiline_span() -> None:
    assert prose_segments("a `b\nc` $1\n", 1) == [(1, "a   "), (2, "   $1")]


def test_prose_segments_skip_tokens_before_the_start_line() -> None:
    assert prose_segments("---\nprice: $1\n---\nBody $2\n", 4) == [(4, "Body $2")]
