"""The JSON config parser: loading a document and locating a key's line."""

import pytest

from rigcheck.parse import config


def test_load_object() -> None:
    doc = config.load('{"hooks": {"Stop": []}}')
    assert doc.problem is None
    assert doc.data == {"hooks": {"Stop": []}}


def test_load_empty_object_is_not_a_problem() -> None:
    doc = config.load("{}")
    assert doc.problem is None
    assert doc.data == {}


def test_load_invalid_json_names_line_and_column() -> None:
    doc = config.load('{\n  "hooks": ,\n}')
    assert doc.data is None
    assert doc.problem == "line 2 column 12: Expecting value"


def test_load_empty_text_is_empty() -> None:
    doc = config.load("")
    assert doc.data is None
    assert doc.problem == "the file is empty"


def test_load_whitespace_only_is_empty() -> None:
    doc = config.load(" \n\t\n")
    assert doc.data is None
    assert doc.problem == "the file is empty"


def test_load_strips_a_leading_bom() -> None:
    doc = config.load(chr(0xFEFF) + '{"hooks": {}}')
    assert doc.problem is None
    assert doc.data == {"hooks": {}}


def test_load_huge_number_is_a_problem() -> None:
    doc = config.load("1" * 5000)
    assert doc.data is None
    assert doc.problem == "not loadable JSON: ValueError"


def test_load_deep_nesting_is_a_problem() -> None:
    doc = config.load("[" * 100000)
    assert doc.data is None
    assert doc.problem == "not loadable JSON: RecursionError"


def test_key_line_top_level() -> None:
    assert config.key_line('{\n"a": "hooks",\n"hooks": {}\n}', ("hooks",)) == 3


def test_key_line_nested_path() -> None:
    text = '{\n"mcpServers": {\n"a": {"env": {"b": 1}},\n"b": {}}}'
    assert config.key_line(text, ("mcpServers", "b")) == 4
    assert config.key_line(text, ("mcpServers", "a")) == 3


@pytest.mark.parametrize("written", ['"sérver"', '"s' + chr(92) + 'u00e9rver"'])
def test_key_line_non_ascii(written: str) -> None:
    assert config.key_line('{"mcpServers": {\n' + written + ": {}}}", ("mcpServers", "sérver")) == 2


def test_key_line_ignores_strings_and_arrays() -> None:
    text = '{\n"x": "\\"hooks\\": 1",\n"list": [{"hooks": 1}],\n"hooks": {}\n}'
    assert config.key_line(text, ("hooks",)) == 4


def test_key_line_absent_or_unscannable() -> None:
    assert config.key_line('{"a": 1}', ("hooks",)) is None
    assert config.key_line('{"a": [{"b": 1}]}', ("a", "b")) is None
    assert config.key_line('{"b": "unterminated', ("b", "c")) is None


def test_key_line_forgets_a_key_after_its_value() -> None:
    assert config.key_line('{"a": 1,\n"c": {\n"b": 2}}', ("a", "b")) is None
    assert config.key_line('{"a": {"x": 1},\n"c": {"b": 2},\n"a2": 0}', ("a", "b")) is None


def test_key_line_reports_the_last_duplicate() -> None:
    assert config.key_line('{"hooks": 1,\n"hooks": {}}', ("hooks",)) == 2
