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


@dataclass(frozen=True)
class Reference:
    """Text in an instruction file that may name a path or a command.

    Attributes:
        line: 1-based line the reference starts on.
        raw: The code span's content, the link's href, or one code block line without its newline.
        source: ``span`` for a code span, ``link`` for a link, ``fence`` for a code block line.
        lang: A fenced block's language, the first word of its info string lower-cased; empty otherwise.
    """

    line: int
    raw: str
    source: str
    lang: str


def _span_newlines(source: str, cursor: int, span: Token) -> tuple[int, int]:
    """Find ``span`` in the inline source from ``cursor``; return the line breaks inside it and the cursor past it.

    markdown-it turns a line break inside a code span into a space, so the span's raw text is
    matched in the source, where the break survives.
    """
    body = r"[ \n]".join(re.escape(part) for part in span.content.split(" "))
    ticks = re.escape(span.markup)
    match = re.compile(rf"{ticks}[ \n]?{body}[ \n]?{ticks}").search(source, cursor)
    if match is None:
        return 0, cursor
    return match.group().count("\n"), match.end()


class _InlineScan:
    """Walks one inline token's children, tracking the current line."""

    def __init__(self, token: Token) -> None:
        self.source = token.content
        self.line = (token.map[0] if token.map is not None else 0) + 1
        self.cursor = 0
        self.in_link = False
        self.found: list[Reference] = []

    def span(self, child: Token) -> None:
        if not self.in_link:
            self.found.append(Reference(line=self.line, raw=child.content, source="span", lang=""))
        newlines, self.cursor = _span_newlines(self.source, self.cursor, child)
        self.line += newlines

    def link(self, child: Token) -> None:
        self.in_link = True
        if child.markup != "autolink":
            self.found.append(Reference(line=self.line, raw=str(child.attrs.get("href", "")), source="link", lang=""))

    def visit(self, child: Token) -> None:
        if child.type in _BREAKS:
            self.line += 1
        elif child.type in ("text", "html_inline"):
            self.line += child.content.count("\n")
        elif child.type == "code_inline":
            self.span(child)
        elif child.type == "link_open":
            self.link(child)
        elif child.type == "link_close":
            self.in_link = False


def _inline_references(token: Token) -> list[Reference]:
    scan = _InlineScan(token)
    for child in token.children or ():
        scan.visit(child)
    return scan.found


def _block_references(token: Token) -> list[Reference]:
    if token.map is None:
        return []
    first = token.map[0] + (2 if token.type == "fence" else 1)
    words = token.info.split() if token.type == "fence" else []
    lang = words[0].lower() if words else ""
    lines = token.content.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return [Reference(line=first + index, raw=raw, source="fence", lang=lang) for index, raw in enumerate(lines)]


def find_references(text: str) -> list[Reference]:
    """Find the code spans, links and code block lines of a Markdown file.

    Block-level HTML comments are removed first (see :func:`strip_html_comments`); autolinks,
    images, and code spans inside a link's text are not reported.

    Args:
        text: The file content.

    Returns:
        The references in document order, one per code span, link, or code block line.
    """
    found: list[Reference] = []
    for token in _PARSER.parse(strip_html_comments(text)):
        if token.type == "inline" and token.map is not None and token.children:
            found.extend(_inline_references(token))
        elif token.type in ("fence", "code_block"):
            found.extend(_block_references(token))
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
