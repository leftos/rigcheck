"""YAML frontmatter between ``---`` fences at the top of a Markdown file."""

import re
from dataclasses import dataclass
from typing import Any

import yaml

FENCE = "---"

_BLOCK_MARKER = re.compile(r"[|>](?:[+-]?[1-9]?|[1-9][+-])")
_QUOTES = ("'", '"')
_BOM = "\ufeff"

_RETRY_KEY_LINE = re.compile(r"([a-zA-Z_-]+):\s+([^\r\n\u2028\u2029]+)")
"""A line Claude Code's retry may re-quote: its value is JavaScript's ``.+``, so a line ending in CR never matches."""
_RETRY_SPECIAL = re.compile(r"[{}\[\]*&#!|>%@`]|: ")
_LEADING_SPACE = re.compile(r"[ \t]+")
_KEY_LINE = re.compile(r"([^\s:#-][^:]*?):(?:\s|$)")
_TRUE = frozenset({"true", "yes", "on", "1"})
_FALSE = frozenset({"false", "no", "off", "0"})
_SYNTAX_ERROR = object()
"""What ``_load`` returns in place of data when the text is not YAML at all."""


@dataclass(frozen=True)
class Frontmatter:
    """The result of parsing a file's frontmatter, as strict YAML and as Claude Code loads it.

    Attributes:
        present: True when the file's first line is exactly ``---``.
        data: The mapping Claude Code loads: strict YAML's when it parses, else the mapping of Claude Code's
            retry, which re-quotes unquoted values holding ``: `` or a YAML indicator; None when absent or rejected.
        strict_error: Why strict YAML cannot use the block, or None.
        load_error: Why Claude Code rejects the block, or None when it loads (or is absent).
        key_lines: The 1-based file line of each top-level key found at column 0; the last wins for a repeated key.
        body_line: 1-based line number where the body starts.
    """

    present: bool
    data: dict[Any, Any] | None
    strict_error: str | None
    load_error: str | None
    key_lines: dict[str, int]
    body_line: int


def parse(text: str) -> Frontmatter:
    """Parse the frontmatter block of ``text``; never raises.

    Args:
        text: The whole file content.

    Returns:
        The frontmatter. An unclosed block or a non-mapping sets both errors; YAML that only Claude Code's retry
        reads sets ``strict_error`` alone.
    """
    raw = text.removeprefix(_BOM).split("\n")
    lines = [line.removesuffix("\r") for line in raw]
    if lines[0] != FENCE:
        return Frontmatter(present=False, data=None, strict_error=None, load_error=None, key_lines={}, body_line=1)
    try:
        closing = lines.index(FENCE, 1)
    except ValueError:
        unclosed = "unclosed frontmatter"
        return Frontmatter(present=True, data=None, strict_error=unclosed, load_error=unclosed, key_lines={}, body_line=1)
    data, strict_error = _load("\n".join(lines[1:closing]))
    load_error = strict_error
    if strict_error is not None and data is _SYNTAX_ERROR:
        data, load_error = _load(_retry_block(raw[1:closing]))
    loaded = data if isinstance(data, dict) else None
    return Frontmatter(
        present=True,
        data=loaded,
        strict_error=strict_error,
        load_error=load_error,
        key_lines=_key_lines(lines[1:closing], loaded),
        body_line=closing + 2,
    )


def _load(block: str) -> tuple[Any, str | None]:
    """Parse ``block`` as YAML; return the mapping and None, or ``_SYNTAX_ERROR`` or the non-mapping value and why."""
    try:
        data = yaml.safe_load(block)
    except Exception as exc:  # noqa: BLE001 - any parser failure on arbitrary text becomes a reported error, never a crash
        return _SYNTAX_ERROR, f"invalid YAML: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return data, f"frontmatter is a {type(data).__name__}, not a mapping"
    return data, None


def _retry_line(line: str) -> str:
    """Re-quote ``line``'s value as Claude Code's retry does, and expand its leading tabs (which Claude Code accepts)."""
    match = _RETRY_KEY_LINE.fullmatch(line)
    if match:
        key, value = match.groups()
        wrapped = len(value) > 1 and value[0] in _QUOTES and value[-1] == value[0]
        if not wrapped and _RETRY_SPECIAL.search(value):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            line = f'{key}: "{escaped}"'
    indent = _LEADING_SPACE.match(line)
    if indent:
        line = indent.group().replace("\t", "  ") + line[indent.end() :]
    return line.removesuffix("\r")


def _retry_block(raw: list[str]) -> str:
    return "\n".join(_retry_line(line) for line in raw)


def _key_lines(block: list[str], data: dict[Any, Any] | None) -> dict[str, int]:
    """Map each column-0 key in ``block`` (file line 2 onwards) to its file line; only keys in ``data`` when it loaded."""
    found: dict[str, int] = {}
    for index, line in enumerate(block):
        match = _KEY_LINE.match(line)
        if match:
            found[match.group(1).rstrip()] = index + 2
    if data is None:
        return found
    return {key: line for key, line in found.items() if key in data}


def as_bool(value: object) -> bool | None:
    """Read a frontmatter flag the way Claude Code reads booleans.

    Args:
        value: A value from ``Frontmatter.data``.

    Returns:
        True for ``True``, ``1`` and the strings true/yes/on/1 in any case; False for ``False``, ``0`` and
        false/no/off/0; None for anything else.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return {1: True, 0: False}.get(value)
    if isinstance(value, str):
        word = value.strip().lower()
        return True if word in _TRUE else False if word in _FALSE else None
    return None


def _lines(text: str) -> list[str]:
    return [line.removesuffix("\r") for line in text.removeprefix(_BOM).split("\n")]


def _join(parts: list[str]) -> str:
    return " ".join(part.strip() for part in parts if part.strip())


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] in _QUOTES and value[-1] == value[0]:
        return value[1:-1]
    return value


def _is_indented(line: str) -> bool:
    return line[:1] in (" ", "\t") or not line.strip()


def _indented_end(lines: list[str], start: int) -> int:
    end = start
    while end < len(lines) and _is_indented(lines[end]):
        end += 1
    return end


def _quoted_end(lines: list[str], start: int, quote: str) -> int:
    end = start
    while end < len(lines):
        end += 1
        if lines[end - 1].rstrip().endswith(quote):
            break
    return end


def _value(first: str, lines: list[str], start: int) -> tuple[str, int]:
    """Read a value whose first line holds ``first``; return it and the index of the line after it."""
    if first[:1] in _QUOTES and _unquote(first) == first:
        end = _quoted_end(lines, start, first[0])
        return _unquote(_join([first, *lines[start:end]])), end
    end = _indented_end(lines, start)
    if not first or _BLOCK_MARKER.fullmatch(first):
        return _join(lines[start:end]), end
    return _join([_unquote(first), *lines[start:end]]), end


def _dedent(lines: list[str]) -> list[str]:
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return [line[indent:] for line in lines]


def _scan(block: list[str], keys: tuple[str, ...], prefix: str) -> dict[str, str]:
    """Read ``keys`` from ``block``, whose keys sit at column 0 and are named ``prefix`` + key; nest once when prefix is empty."""
    parents = {key.split(".", 1)[0] for key in keys if "." in key} if not prefix else set()
    fields: dict[str, str] = {}
    index = 0
    while index < len(block):
        key, colon, rest = block[index].partition(":")
        index += 1
        if colon and "." not in key and prefix + key in keys:
            fields[prefix + key], index = _value(rest.strip(), block, index)
        elif colon and key in parents and not rest.strip():
            end = _indented_end(block, index)
            fields.update(_scan(_dedent(block[index:end]), keys, f"{key}."))
            index = end
    return fields


def read_lenient(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Read top-level keys from a frontmatter block the way Claude Code still loads it when strict YAML rejects it.

    A key is a line starting at column 0 as ``key:``. Its value is the rest of the line with
    surrounding quotes stripped, continued by the following lines indented more than the key and
    joined with single spaces. A block marker (``|`` or ``>`` with an optional chomping sign and
    indent digit) or an empty value takes the indented lines alone; a quoted value that does not
    close on its line continues to the line ending in its closing quote.

    A key may also be ``parent.child``, one level deep: it is read the same way from the
    ``child:`` lines at the first indentation under a ``parent:`` line that has no value of its own.

    Args:
        text: The whole file content.
        keys: The keys to read; others are skipped.

    Returns:
        The values read, by key; empty when the file has no closed frontmatter block.
    """
    lines = _lines(text)
    if lines[0] != FENCE or FENCE not in lines[1:]:
        return {}
    return _scan(lines[1 : lines.index(FENCE, 1)], keys, "")
