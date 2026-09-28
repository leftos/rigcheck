"""JSON config files: loading them, and locating a key's line."""

import json
from dataclasses import dataclass

BOM = chr(0xFEFF)
"""A UTF-8 byte-order mark, which a file may carry before its first character."""

_SPACE = " \t\r\n"
"""The whitespace JSON allows between tokens."""

_OPEN = "{["
"""The characters that open a container."""

_CLOSE = "}]"
"""The characters that close a container."""


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
        The parsed document. A text that is empty or only whitespace does not load, a syntax error's
        problem names the line and column the parser stopped at, and a document the parser refuses
        rather than reports on (a number too long to convert, nesting too deep to walk) is named by
        the error it raised, which never carries any of the file's content.
    """
    body = text.removeprefix(BOM)
    if not body.strip():
        return JsonDoc(data=None, problem="the file is empty")
    try:
        return JsonDoc(data=json.loads(body), problem=None)
    except json.JSONDecodeError as exc:
        return JsonDoc(data=None, problem=f"line {exc.lineno} column {exc.colno}: {exc.msg}")
    except (ValueError, RecursionError) as exc:
        return JsonDoc(data=None, problem=f"not loadable JSON: {type(exc).__name__}")


def key_line(text: str, path: tuple[str, ...]) -> int | None:
    """Return the 1-based line where the last key of ``path`` is written as an object key.

    The path is read from the document's root object inwards through object keys only, so
    ``("hooks",)`` is a top-level key and ``("mcpServers", "b")`` is key ``b`` of the top-level
    ``mcpServers`` object. Keys are compared by their decoded text, so a key holding non-ASCII
    characters is found whether it is written literally or through JSON unicode escapes. A quoted
    text that only looks like a key, standing inside a string value or inside an array, does not
    count.

    Args:
        text: The file's content.
        path: The key names to walk, outermost first.

    Returns:
        The line of the first key that completes the path, or None when the path is absent or the
        text does not scan as JSON.
    """
    if not path:
        return None
    return _Scanner(text, path).run()


@dataclass
class _Frame:
    """One open container of a scan.

    Attributes:
        kind: ``"o"`` for an object, ``"a"`` for an array.
        chain: The index in the sought path that this object's keys are compared against, or None
            when the object is not on the path.
        pending: The name of the key whose value this object is reading, or None.
    """

    kind: str
    chain: int | None = None
    pending: str | None = None


class _Scanner:
    """A character walk over JSON text, looking for the line one key path is written at.

    The walk tracks whether it is inside a string (with backslash escapes), the containers it has
    entered, and, for each object on the path, the key it has just read.

    Attributes:
        text: The text being walked.
        path: The keys to reach, from the root object inwards.
        stack: The containers currently open, outermost first.
        line: The 1-based line the walk has reached.
    """

    def __init__(self, text: str, path: tuple[str, ...]) -> None:
        self.text = text
        self.path = path
        self.stack: list[_Frame] = []
        self.line = 1

    def run(self) -> int | None:
        """Return the line of the path's last key, or None when the path is absent or the text does not scan."""
        index = 0
        while index < len(self.text):
            char = self.text[index]
            if char == '"':
                found, index = self._string(index)
            elif char in _OPEN or char in _CLOSE:
                self._bracket(char)
                found, index = None, index + 1
            else:
                found, index = None, index + 1
                if char == "\n":
                    self.line += 1
            if found is not None:
                return found
        return None

    def _bracket(self, char: str) -> None:
        """Push the container ``char`` opens, or pop the one it closes."""
        if char in _OPEN:
            self._open(char)
        elif self.stack:
            self.stack.pop()

    def _open(self, char: str) -> None:
        """Push the container ``char`` opens, carrying the path depth its keys are compared at."""
        if char == "[":
            self.stack.append(_Frame(kind="a"))
            return
        parent = self.stack[-1] if self.stack else None
        self.stack.append(_Frame(kind="o", chain=self._chain(parent)))

    def _chain(self, parent: _Frame | None) -> int | None:
        """Return the depth this object's keys are compared at: 0 at the root, one past a matched key, else None."""
        if parent is None:
            return 0
        if parent.kind != "o" or parent.chain is None or parent.pending != self.path[parent.chain]:
            return None
        return parent.chain + 1

    def _string(self, start: int) -> tuple[int | None, int]:
        """Read the string whose opening quote is at ``start``; return the line found and the index after it."""
        end = self._string_end(start)
        if end is None:
            return None, len(self.text)
        found = self._key(self.stack[-1] if self.stack else None, start, end)
        self.line += self.text.count("\n", start, end)
        return found, end + 1

    def _string_end(self, start: int) -> int | None:
        """Return the index of the quote that closes the string opened at ``start``, or None when it never closes."""
        index = start + 1
        while index < len(self.text):
            char = self.text[index]
            if char == "\\":
                index += 2
                continue
            if char == '"':
                return index
            index += 1
        return None

    def _key(self, frame: _Frame | None, start: int, end: int) -> int | None:
        """Return the line when the string at ``start`` is the key the object ``frame`` is looking for."""
        if frame is None or frame.kind != "o" or not _is_key(self.text, end + 1):
            return None
        name = _decoded(self.text[start : end + 1])
        if name is None or frame.chain is None or name != self.path[frame.chain]:
            return None
        if frame.chain == len(self.path) - 1:
            return self.line
        frame.pending = name
        return None


def _is_key(text: str, index: int) -> bool:
    """Return True when the first character at or after ``index`` that is not whitespace is ``:``."""
    index = _skip_space(text, index)
    return text[index : index + 1] == ":"


def _skip_space(text: str, index: int) -> int:
    """Return the index of the first character at or after ``index`` that is not JSON whitespace."""
    while index < len(text) and text[index] in _SPACE:
        index += 1
    return index


def _decoded(source: str) -> str | None:
    """Return the text the JSON string token ``source`` holds, or None when it is not a decodable string."""
    try:
        value = json.loads(source)
    except ValueError:
        return None
    return value if isinstance(value, str) else None
