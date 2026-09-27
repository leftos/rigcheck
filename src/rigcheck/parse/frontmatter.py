"""YAML frontmatter between ``---`` fences at the top of a Markdown file."""

import re
from dataclasses import dataclass
from typing import Any

import yaml

FENCE = "---"

_BLOCK_MARKER = re.compile(r"[|>](?:[+-]?[1-9]?|[1-9][+-])")
_QUOTES = ("'", '"')


@dataclass(frozen=True)
class Frontmatter:
    """The result of parsing a file's frontmatter.

    Attributes:
        present: True when the file's first line is exactly ``---``.
        data: The parsed mapping, or None when absent or invalid.
        error: Why the block could not be used, or None.
        body_line: 1-based line number where the body starts.
    """

    present: bool
    data: dict[Any, Any] | None
    error: str | None
    body_line: int


def parse(text: str) -> Frontmatter:
    """Parse the frontmatter block of ``text``; never raises.

    Args:
        text: The whole file content.

    Returns:
        The frontmatter, with ``error`` set when the block is unclosed, not YAML, or not a mapping.
    """
    lines = _lines(text)
    if lines[0] != FENCE:
        return Frontmatter(present=False, data=None, error=None, body_line=1)
    try:
        closing = lines.index(FENCE, 1)
    except ValueError:
        return Frontmatter(present=True, data=None, error="unclosed frontmatter", body_line=1)
    body_line = closing + 2
    block = "\n".join(lines[1:closing])
    try:
        data = yaml.safe_load(block)
    except Exception as exc:  # noqa: BLE001 - any parser failure on arbitrary text becomes a reported error, never a crash
        return Frontmatter(present=True, data=None, error=f"invalid YAML: {exc}", body_line=body_line)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return Frontmatter(present=True, data=None, error=f"frontmatter is a {type(data).__name__}, not a mapping", body_line=body_line)
    return Frontmatter(present=True, data=data, error=None, body_line=body_line)


def _lines(text: str) -> list[str]:
    return [line.removesuffix("\r") for line in text.removeprefix("﻿").split("\n")]


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


def read_lenient(text: str, keys: tuple[str, ...]) -> dict[str, str]:
    """Read top-level keys from a frontmatter block the way Claude Code still loads it when strict YAML rejects it.

    A key is a line starting at column 0 as ``key:``. Its value is the rest of the line with
    surrounding quotes stripped, continued by the following lines indented more than the key and
    joined with single spaces. A block marker (``|`` or ``>`` with an optional chomping sign and
    indent digit) or an empty value takes the indented lines alone; a quoted value that does not
    close on its line continues to the line ending in its closing quote.

    Args:
        text: The whole file content.
        keys: The keys to read; others are skipped.

    Returns:
        The values read, by key; empty when the file has no closed frontmatter block.
    """
    lines = _lines(text)
    if lines[0] != FENCE or FENCE not in lines[1:]:
        return {}
    block = lines[1 : lines.index(FENCE, 1)]
    fields: dict[str, str] = {}
    index = 0
    while index < len(block):
        key, colon, rest = block[index].partition(":")
        index += 1
        if colon and key in keys:
            fields[key], index = _value(rest.strip(), block, index)
    return fields
