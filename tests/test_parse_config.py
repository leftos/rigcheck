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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"hooks": {"Stop": []}}', 1),
        ('{"hooks" : {}}', 1),
        ('{\n  "enabledPlugins": {},\n  "hooks": {"Stop": []}\n}', 3),
        ('{"a": "hooks"}', None),
        ('{\n  "note": "hooks: x"\n}', None),
        ('{"a": "hooks", "hooks": 1}', 1),
        ('[\n  {"hooks": []}\n]', 2),
    ],
)
def test_key_line(text: str, expected: int | None) -> None:
    assert config.key_line(text, "hooks") == expected


def test_key_line_absent_for_a_text_without_the_key() -> None:
    assert config.key_line('{"mcpServers": {}}', "hooks") is None
