from hypothesis import given, settings
from hypothesis import strategies as st

from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import find_imports, is_candidate, strip_html_comments

PATH_CHARS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=8)
CANDIDATES = st.builds(lambda stem, ext: f"{stem}.{ext}", PATH_CHARS, st.sampled_from(["md", "txt", "json"]))
PROSE = st.text(alphabet="abcdefghij @.`~/\n-*#", max_size=60)


@settings(deadline=None)
@given(st.text())
def test_frontmatter_parse_never_raises(text: str) -> None:
    result = frontmatter.parse(text)
    assert result.body_line >= 1
    assert result.present or (result.data is None and result.error is None)


@settings(deadline=None)
@given(st.text())
def test_frontmatter_after_fence_never_raises(body: str) -> None:
    frontmatter.parse("---\n" + body)


@settings(deadline=None)
@given(st.text())
def test_find_imports_never_raises(text: str) -> None:
    find_imports(text)
    strip_html_comments(text)


@settings(deadline=None)
@given(PROSE, CANDIDATES, PROSE)
def test_fenced_candidates_are_never_imports(before: str, candidate: str, after: str) -> None:
    text = f"{before}\n\n```\n@{candidate}\n```\n\n{after}\n"
    lines = text.split("\n")
    fence_lines = {index + 1 for index, line in enumerate(lines) if line == f"@{candidate}"}
    found = find_imports(text)
    assert not any(item.line in fence_lines and item.raw == candidate for item in found)


@settings(deadline=None)
@given(PROSE, CANDIDATES)
def test_code_span_candidates_are_never_imports(before: str, candidate: str) -> None:
    before = before.replace("`", "")
    found = find_imports(f"{before} `@{candidate}` tail\n")
    assert candidate not in [item.raw for item in found]


@settings(deadline=None)
@given(CANDIDATES)
def test_candidate_in_prose_is_found(candidate: str) -> None:
    text = "Intro line.\n\nSee @" + candidate + " for details.\n"
    assert [item.raw for item in find_imports(text)] == [candidate]


@settings(deadline=None)
@given(st.text())
def test_every_returned_raw_satisfies_the_candidate_rule(text: str) -> None:
    for item in find_imports(text):
        assert is_candidate(item.raw)
        assert item.raw[-1] not in ".,;:)!?\"'"
        assert item.line >= 1
