"""Markdown helpers that follow Claude Code's handling of instruction files."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.token import Token

_PARSER = MarkdownIt("commonmark")
_NEWLINES = re.compile(r"\r\n?")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CANDIDATE = re.compile(r"(?<=\s)@(\S+)")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_TRAILING = ".,;:)!?\"'"
_PATH_PREFIXES = ("~/", "./", "../", "/")
_BREAKS = ("softbreak", "hardbreak")
_OPAQUE = "\x00"


@dataclass(frozen=True)
class Import:
    """An ``@path`` import found in an instruction file.

    Attributes:
        line: 1-based line of the import.
        raw: The path as written, without the ``@`` and trailing punctuation.
    """

    line: int
    raw: str


def _normalize(text: str) -> str:
    return _NEWLINES.sub("\n", text)


def strip_html_comments(text: str) -> str:
    r"""Remove block-level HTML comments, as Claude Code does before injecting CLAUDE.md.

    Comments inside code blocks and inline comments within a paragraph are kept.
    Line breaks inside a removed comment are kept, so line numbers still match the file.

    Args:
        text: The file content.

    Returns:
        The content with newlines normalized to ``\n`` and block-level comments removed.
    """
    text = _normalize(text)
    lines = text.split("\n")
    for token in _PARSER.parse(text):
        if token.type != "html_block" or token.map is None or not token.content.lstrip().startswith("<!--"):
            continue
        start, end = token.map
        chunk = "\n".join(lines[start:end])
        chunk = _COMMENT.sub(lambda match: "\n" * match.group().count("\n"), chunk)
        lines[start:end] = chunk.split("\n")
    return "\n".join(lines)


def is_candidate(raw: str) -> bool:
    """Return True when ``raw`` looks like a path rather than prose such as ``@username``.

    Args:
        raw: The text after ``@``, with trailing punctuation removed.

    Returns:
        True when it starts with ``~/``, ``./``, ``../`` or ``/``, or its last segment has a file extension.
    """
    if not raw or any(char.isspace() for char in raw):
        return False
    if raw.startswith(_PATH_PREFIXES):
        return True
    last_segment = re.split(r"[\\/]", raw)[-1]
    return _EXTENSION.search(last_segment) is not None


def _scan_text(content: str, previous: str, line: int) -> list[Import]:
    found = []
    combined = previous + content
    for match in _CANDIDATE.finditer(combined):
        raw = match.group(1).rstrip(_TRAILING)
        if is_candidate(raw):
            offset = combined.count("\n", 1, match.start())
            found.append(Import(line=line + offset, raw=raw))
    return found


def _inline_imports(children: Sequence[Token], first_line: int) -> list[Import]:
    found: list[Import] = []
    line = first_line
    previous = "\n"
    for child in children:
        if child.type in _BREAKS:
            line += 1
            previous = "\n"
        elif child.type == "text":
            found.extend(_scan_text(child.content, previous, line))
            line += child.content.count("\n")
            previous = child.content[-1:] or previous
        else:
            previous = _OPAQUE
    return found


def find_imports(text: str) -> list[Import]:
    """Find Claude Code ``@path`` imports outside code blocks and code spans.

    An import is ``@`` at the start of a line or after whitespace, followed by a path-like
    token (see :func:`is_candidate`). Fenced and indented code blocks, code spans and HTML
    blocks never yield imports.

    Args:
        text: The file content.

    Returns:
        The imports in document order.
    """
    found: list[Import] = []
    for token in _PARSER.parse(_normalize(text)):
        if token.type == "inline" and token.map is not None and token.children:
            found.extend(_inline_imports(token.children, token.map[0] + 1))
    return found
