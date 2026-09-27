from hypothesis import given, settings
from hypothesis import strategies as st

from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import find_imports, find_references, is_candidate, strip_html_comments

PATH_CHARS = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=8)
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
@given(CANDIDATES)
def test_candidate_names_cannot_form_emphasis(candidate: str) -> None:
    assert "_" not in candidate
    assert "*" not in candidate


@settings(deadline=None)
@given(st.text())
def test_find_references_never_raises(text: str) -> None:
    for reference in find_references(text):
        assert reference.line >= 1
        assert reference.source in {"span", "link", "fence"}


@settings(deadline=None)
@given(PROSE, CANDIDATES, PROSE)
def test_fenced_text_yields_no_span_or_link(before: str, candidate: str, after: str) -> None:
    before, after = before.replace("`", ""), after.replace("`", "")
    text = f"{before}\n\n```\n`dir/{candidate}` [x](dir/{candidate})\n```\n\n{after}\n"
    fence_line = text.split("\n").index(f"`dir/{candidate}` [x](dir/{candidate})") + 1
    found = find_references(text)
    assert not any(item.line == fence_line and item.source != "fence" for item in found)
    assert f"dir/{candidate}" not in [item.raw for item in found if item.source != "fence"]


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
