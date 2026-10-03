"""Reading ``.rigcheck.toml``: its suppression entries, their lines, and the problems a bad file reports."""

from pathlib import Path

from rigcheck.config import load_suppressions
from rigcheck.model import Suppression
from support import write


def _load(tmp_path: Path, text: str) -> tuple[tuple[Suppression, ...], list[str], Path]:
    path = write(tmp_path / ".rigcheck.toml", text)
    entries, problems = load_suppressions(path)
    return entries, problems, path


def test_absent_file_yields_nothing(tmp_path: Path) -> None:
    assert load_suppressions(tmp_path / ".rigcheck.toml") == ((), [])


def test_valid_file_yields_entries_with_header_lines(tmp_path: Path) -> None:
    text = (
        "# suppressions\n"
        "\n"
        "[[suppress]]\n"
        'rule = "skill-description-missing"\n'
        'path = "plugins/legacy/**"\n'
        'reason = "vendored; fixed upstream"\n'
        "\n"
        "# [[suppress]] a commented header is not an entry\n"
        "[[suppress]]\n"
        'rule = "import-unresolved"\n'
    )
    entries, problems, _ = _load(tmp_path, text)
    assert problems == []
    assert entries == (
        Suppression(rule="skill-description-missing", path="plugins/legacy/**", reason="vendored; fixed upstream", line=3),
        Suppression(rule="import-unresolved", path=None, reason=None, line=9),
    )


def test_invalid_toml_is_one_problem_and_no_entries(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, '[[suppress]]\nrule = "a\n')
    assert entries == ()
    assert len(problems) == 1
    assert problems[0].startswith(f"{path}: not valid TOML: ")
    assert "line 2" in problems[0]


def test_non_utf8_file_is_one_problem_and_no_entries(tmp_path: Path) -> None:
    path = tmp_path / ".rigcheck.toml"
    path.write_bytes(b'[[suppress]]\nrule = "\xff"\n')
    entries, problems = load_suppressions(path)
    assert entries == ()
    assert len(problems) == 1
    assert problems[0].startswith(f"{path}: not valid TOML: ")


def test_unknown_top_level_key_is_reported_and_the_rest_still_read(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, 'supress = 1\n\n[[suppress]]\nrule = "a"\nreason = "r"\n')
    assert problems == [f"{path}: unknown key `supress`"]
    assert entries == (Suppression(rule="a", path=None, reason="r", line=3),)


def test_suppress_not_an_array_of_tables_is_one_problem(tmp_path: Path) -> None:
    for text in ('suppress = "a"\n', "suppress = [1, 2]\n", '[suppress]\nrule = "a"\n'):
        entries, problems, path = _load(tmp_path, text)
        assert entries == ()
        assert problems == [f"{path}: `suppress` must be an array of tables"]


def test_missing_rule_skips_the_entry(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, '[[suppress]]\nreason = "r"\n\n[[suppress]]\nrule = "b"\nreason = "r"\n')
    assert problems == [f"{path}: [[suppress]] entry 1: rule is missing"]
    assert entries == (Suppression(rule="b", path=None, reason="r", line=4),)


def test_empty_string_rule_skips_the_entry(tmp_path: Path) -> None:
    for value in ('""', '"   "', "3"):
        entries, problems, path = _load(tmp_path, f"[[suppress]]\nrule = {value}\n")
        assert entries == ()
        assert problems == [f"{path}: [[suppress]] entry 1: rule must be a non-empty string"]


def test_non_string_path_skips_the_entry(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, '[[suppress]]\nrule = "a"\npath = ["x"]\n')
    assert entries == ()
    assert problems == [f"{path}: [[suppress]] entry 1: path must be a string"]


def test_non_string_reason_skips_the_entry(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, '[[suppress]]\nrule = "a"\nreason = true\n')
    assert entries == ()
    assert problems == [f"{path}: [[suppress]] entry 1: reason must be a string"]


def test_unknown_entry_key_skips_the_entry(tmp_path: Path) -> None:
    entries, problems, path = _load(tmp_path, '[[suppress]]\nrul = "a"\nrule = "a"\n')
    assert entries == ()
    assert problems == [f"{path}: [[suppress]] entry 1: unknown key `rul`"]


def test_problem_messages_never_quote_values(tmp_path: Path) -> None:
    _, problems, _ = _load(tmp_path, '[[suppress]]\nrule = 12345\npath = 67890\nreason = 13579\nextra = "secret-value"\n')
    assert len(problems) == 4
    for value in ("12345", "67890", "13579", "secret-value"):
        assert all(value not in problem for problem in problems)


def test_missing_reason_is_kept_as_none(tmp_path: Path) -> None:
    entries, problems, _ = _load(tmp_path, '[[suppress]]\nrule = "a"\n')
    assert problems == []
    assert entries == (Suppression(rule="a", path=None, reason=None, line=1),)


def test_whitespace_reason_is_kept_as_given(tmp_path: Path) -> None:
    entries, problems, _ = _load(tmp_path, '[[suppress]]\nrule = "a"\nreason = "  "\n\n[[suppress]]\nrule = "b"\nreason = ""\n')
    assert problems == []
    assert [entry.reason for entry in entries] == ["  ", ""]


def test_spaced_headers_get_their_own_lines(tmp_path: Path) -> None:
    entries, problems, _ = _load(tmp_path, '[[ suppress ]]\nrule = "a"\n\n[[ suppress ]]\nrule = "b"\n')
    assert problems == []
    assert [entry.line for entry in entries] == [1, 4]


def test_mixed_header_forms_get_each_header_line(tmp_path: Path) -> None:
    entries, problems, _ = _load(tmp_path, '[[suppress]]\nrule = "a"\n\n[[ suppress ]]  # spaced\nrule = "b"\n')
    assert problems == []
    assert [entry.line for entry in entries] == [1, 4]


def test_quoted_header_gets_its_line(tmp_path: Path) -> None:
    entries, problems, _ = _load(tmp_path, '# header\n\n[["suppress"]]\nrule = "a"\n')
    assert problems == []
    assert [entry.line for entry in entries] == [3]


def test_control_characters_in_key_names_are_escaped(tmp_path: Path) -> None:
    _, problems, _ = _load(tmp_path, '"a\\tb" = 1\n\n[[suppress]]\nrule = "a"\n"x\\ny" = 1\n')
    assert len(problems) == 2
    assert all("\n" not in problem and "\t" not in problem for problem in problems)
    assert "`a\\tb`" in problems[0]
    assert "x\\ny" in problems[1]


def test_inline_array_entries_use_the_suppress_key_line(tmp_path: Path) -> None:
    text = '# header\n\nsuppress = [\n  {rule = "a", reason = "r"},\n  {rule = "b"},\n]\n'
    entries, problems, _ = _load(tmp_path, text)
    assert problems == []
    assert [(entry.rule, entry.line) for entry in entries] == [("a", 3), ("b", 3)]
