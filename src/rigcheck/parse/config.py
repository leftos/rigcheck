"""JSON config files: loading them, and locating a key's line."""

import json
import re
from dataclasses import dataclass

BOM = chr(0xFEFF)
"""A UTF-8 byte-order mark, which a file may carry before its first character."""

_SPACE = " \t\r\n"
"""The whitespace JSON allows between tokens."""

_OPEN = "{["
"""The characters that open a container."""

_CLOSE = "}]"
"""The characters that close a container."""

_BRACKETS = _OPEN + _CLOSE
"""Every character that opens or closes a container."""

_CONSTANT_OR_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|-Infinity|Infinity|NaN', re.DOTALL)
"""A JSON string, matched whole so a constant's name inside one is skipped, or a bare non-JSON constant."""


@dataclass(frozen=True)
class JsonDoc:
    """One JSON document: the value it holds, or why it does not load.

    Attributes:
        data: The parsed value: an object, array, string, number, boolean or null; None when the text does not load.
        problem: Why the text is not JSON, or None when it loaded.
        line: The 1-based line a syntax error stopped the parser at, or None when the text loaded or
            failed without naming a line.
    """

    data: object | None
    problem: str | None
    line: int | None


def load(text: str) -> JsonDoc:
    """Parse ``text`` as JSON.

    Args:
        text: The file's content, with or without a leading byte-order mark.

    Returns:
        The parsed document. A text that is empty or only whitespace does not load, a syntax error's
        problem names the line and column the parser stopped at, and a document the parser refuses
        rather than reports on (a number too long to convert, nesting too deep to walk) is named by
        the error it raised, which never carries any of the file's content. ``NaN``, ``Infinity``
        and ``-Infinity``, which Python's parser accepts and JSON does not, are a problem naming the
        token and where it stands.
    """
    body = text.removeprefix(BOM)
    if not body.strip():
        return JsonDoc(data=None, problem="the file is empty", line=None)
    try:
        return JsonDoc(data=json.loads(body, parse_constant=_reject_constant), problem=None, line=None)
    except _ConstantError as exc:
        return _constant_problem(body, exc.token)
    except json.JSONDecodeError as exc:
        return JsonDoc(data=None, problem=f"line {exc.lineno} column {exc.colno}: {exc.msg}", line=exc.lineno)
    except (ValueError, RecursionError) as exc:
        return JsonDoc(data=None, problem=f"not loadable JSON: {type(exc).__name__}", line=None)


class _ConstantError(ValueError):
    """Raised by the parser for a ``NaN``, ``Infinity`` or ``-Infinity`` token, which JSON does not allow."""

    def __init__(self, token: str) -> None:
        super().__init__(token)
        self.token = token


def _reject_constant(token: str) -> object:
    """Refuse the non-JSON constant ``token`` the parser met."""
    raise _ConstantError(token)


def _constant_problem(body: str, token: str) -> JsonDoc:
    """Return the problem for a non-JSON constant, placed at its first occurrence outside a string when one is found."""
    for match in _CONSTANT_OR_STRING.finditer(body):
        if match.group() == token:
            start = match.start()
            line = body.count("\n", 0, start) + 1
            column = start - body.rfind("\n", 0, start)
            return JsonDoc(data=None, problem=f"line {line} column {column}: {token} is not valid JSON", line=line)
    return JsonDoc(data=None, problem=f"{token} is not valid JSON", line=None)


def key_line(text: str, path: tuple[str, ...]) -> int | None:
    """Return the 1-based line of the last object key that completes ``path``.

    The path is read from the document's root object inwards through object keys only, so
    ``("hooks",)`` is a top-level key and ``("mcpServers", "b")`` is key ``b`` of the top-level
    ``mcpServers`` object. A key written more than once resolves to its last occurrence, which is
    the one a JSON loader keeps. Keys are compared by their decoded text, so a key holding
    non-ASCII characters is found whether it is written literally or through JSON unicode escapes.
    A quoted text that only looks like a key, standing inside a string value or inside an array,
    does not count.

    Args:
        text: The file's content.
        path: The key names to walk, outermost first.

    Returns:
        The line of the last key that completes the path, or None when no key does or the text does
        not scan as JSON.
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
        pending: The name of the key whose value this object is reading, held only while that key
            matches the path and only until its value begins or the object reads another key.
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
        found: The line of the last key that completed the path, or None while none has.
        broken: True once the walk meets text it cannot scan, which voids the whole result.
    """

    def __init__(self, text: str, path: tuple[str, ...]) -> None:
        self.text = text
        self.path = path
        self.stack: list[_Frame] = []
        self.line = 1
        self.found: int | None = None
        self.broken = False

    def run(self) -> int | None:
        """Return the line of the last key completing the path, or None when none does or the text does not scan."""
        index = 0
        while index < len(self.text) and not self.broken:
            char = self.text[index]
            if char == '"':
                index = self._string(index)
            elif char in _BRACKETS:
                self._bracket(char)
                index += 1
            else:
                if char == "\n":
                    self.line += 1
                index += 1
        return None if self.broken else self.found

    def _bracket(self, char: str) -> None:
        """Push the container ``char`` opens, or pop the one it closes; a close with nothing open breaks the walk."""
        if char in _OPEN:
            self._open(char)
        elif not self.stack:
            self.broken = True
        else:
            self.stack.pop()

    def _open(self, char: str) -> None:
        """Push the container ``char`` opens, an object taking a path depth from the key it follows."""
        parent = self.stack[-1] if self.stack else None
        chain = self._chain(parent) if char == "{" else None
        if parent is not None:
            parent.pending = None
        self.stack.append(_Frame(kind="o" if char == "{" else "a", chain=chain))

    def _chain(self, parent: _Frame | None) -> int | None:
        """Return the depth this object's keys are compared at: 0 at the root, one past a matched key, else None."""
        if parent is None:
            return 0
        if parent.kind != "o" or parent.chain is None or parent.pending != self.path[parent.chain]:
            return None
        return parent.chain + 1

    def _string(self, start: int) -> int:
        """Read the string whose opening quote is at ``start``; return the index just after it."""
        end = self._string_end(start)
        if end is None:
            self.broken = True
            return len(self.text)
        if self.stack and self.stack[-1].kind == "o":
            self._key(self.stack[-1], start, end)
        self.line += self.text.count("\n", start, end)
        return end + 1

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

    def _key(self, frame: _Frame, start: int, end: int) -> None:
        """Record a string ``frame`` reads: a value ends the key before it, a matching key passes the path on."""
        frame.pending = None
        chain = frame.chain
        if chain is None or not _is_key(self.text, end + 1):
            return
        name = _decoded(self.text[start : end + 1])
        if name is None or name != self.path[chain]:
            return
        if chain == len(self.path) - 1:
            self.found = self.line
        else:
            frame.pending = name


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
