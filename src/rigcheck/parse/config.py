"""JSON config files: loading them, and locating a key's line."""

import json
import re
from dataclasses import dataclass

BOM = chr(0xFEFF)
"""A UTF-8 byte-order mark, which a file may carry before its first character."""


@dataclass(frozen=True)
class JsonDoc:
    """One JSON document: the value it holds, or why it does not load.

    Attributes:
        data: The parsed value: an object, array, string, number, boolean or null; None when the text does not load.
        problem: Why the text is not JSON, or None when it loaded.
    """

    data: object | None
    problem: str | None


def load(text: str) -> JsonDoc:
    """Parse ``text`` as JSON.

    Args:
        text: The file's content, with or without a leading byte-order mark.

    Returns:
        The parsed document. A text that is empty or only whitespace does not load, and a syntax
        error's problem names the line and column the parser stopped at.
    """
    body = text.removeprefix(BOM)
    if not body.strip():
        return JsonDoc(data=None, problem="the file is empty")
    try:
        return JsonDoc(data=json.loads(body), problem=None)
    except json.JSONDecodeError as exc:
        return JsonDoc(data=None, problem=f"line {exc.lineno} column {exc.colno}: {exc.msg}")


def key_line(text: str, key: str) -> int | None:
    """Return the 1-based line where the JSON key ``key`` is written, or None when it is absent.

    The key counts only where it stands as a key: quoted, and followed by optional whitespace and
    ``:``. The same text written as a value, as in ``"a": "hooks"``, is not a match.

    Args:
        text: The file's content.
        key: The key's name, unquoted.

    Returns:
        The line of the first ``"<key>":``, or None when the text holds none.
    """
    match = re.search(re.escape(json.dumps(key)) + r"\s*:", text)
    if match is None:
        return None
    return text.count("\n", 0, match.start()) + 1
