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
    if "<!--" not in text:
        return text
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
        raw: The code span's content, the link's href or image's src, or one code block line without its newline.
        source: ``span`` for a code span, ``link`` for a link, ``image`` for an image, ``fence`` for a code block line.
        lang: A fenced block's language, the first word of its info string lower-cased; empty otherwise.
    """

    line: int
    raw: str
    source: str
    lang: str


def _span_match(source: str, cursor: int, span: Token) -> re.Match[str] | None:
    """Find ``span`` in the inline source from ``cursor``.

    markdown-it turns a line break inside a code span into a space, so the span's raw text is
    matched in the source, where the break survives.
    """
    body = r"[ \n]".join(re.escape(part) for part in span.content.split(" "))
    ticks = re.escape(span.markup)
    return re.compile(rf"(?<!`){ticks}[ \n]?{body}[ \n]?{ticks}(?!`)").search(source, cursor)


def _escaped(source: str, index: int) -> bool:
    """True when an odd number of backslashes stands right before ``source[index]``."""
    run = 0
    while index - run - 1 >= 0 and source[index - run - 1] == "\\":
        run += 1
    return run % 2 == 1


def _find_unescaped(source: str, needle: str, start: int) -> int:
    """Return the index of the first ``needle`` at or after ``start`` that no backslash escapes, or -1."""
    index = source.find(needle, start)
    while index >= 0 and _escaped(source, index):
        index = source.find(needle, index + 1)
    return index


def _past_ticks(source: str, index: int) -> int:
    """Return the index past the code span whose opening backticks start at ``index``, or past the backticks alone."""
    rest = source[index:]
    run = len(rest) - len(rest.lstrip("`"))
    closing = re.compile(rf"(?<!`)`{{{run}}}(?!`)").search(source, index + run)
    return closing.end() if closing is not None else index + run


def _bracket_end(source: str, start: int) -> int:
    """Return the index of the ``]`` that closes link text starting at ``start``, skipping code spans and escapes; -1 when none."""
    depth, index = 0, start
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            index = _past_ticks(source, index)
            continue
        if char == "]" and depth == 0:
            return index
        depth += {"[": 1, "]": -1}.get(char, 0)
        index += 1
    return -1


def _skip_space(source: str, index: int) -> int:
    while index < len(source) and source[index] in " \t\n":
        index += 1
    return index


def _skip_target(source: str, index: int) -> int:
    """Return the index past a link destination: ``<...>``, or a run without spaces whose parentheses balance."""
    if source.startswith("<", index):
        close = _find_unescaped(source, ">", index + 1)
        return close + 1 if close >= 0 else index
    depth = 0
    while index < len(source) and not source[index].isspace():
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == ")" and depth == 0:
            return index
        depth += {"(": 1, ")": -1}.get(char, 0)
        index += 1
    return min(index, len(source))


def _skip_title(source: str, index: int) -> int:
    """Return the index past a link title in ``"..."``, ``'...'`` or ``(...)``, or ``index`` when none starts there."""
    if index >= len(source) or source[index] not in "\"'(":
        return index
    close = _find_unescaped(source, ")" if source[index] == "(" else source[index], index + 1)
    return close + 1 if close >= 0 else index


def _destination_end(source: str, index: int) -> int:
    """Return the index past what follows a link's text at ``index``: ``(destination "title")``, ``[label]``, or nothing."""
    if source.startswith("[", index):
        close = _find_unescaped(source, "]", index + 1)
        return close + 1 if close >= 0 else index
    if not source.startswith("(", index):
        return index
    end = _skip_space(source, _skip_title(source, _skip_space(source, _skip_target(source, _skip_space(source, index + 1)))))
    return end + 1 if source.startswith(")", end) else end


Range = tuple[int, int]


class _SourceWalk:
    """Follows an inline token's children through its raw source, which keeps escapes and line breaks the tokens fold away."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.cursor = 0
        self.opened: list[int] = []

    def advance(self, child: Token) -> tuple[int, list[Range]]:
        """Move past ``child``; return where it starts and the ranges it covers that hold no prose.

        Those are code spans, inline HTML, autolinks, a link's destination and an image's
        destination and alt-text code spans. A child the walk cannot place starts at the cursor.
        """
        handler = {
            "code_inline": self._code,
            "html_inline": self._html,
            "link_open": self._link_open,
            "link_close": self._link_close,
            "image": self._image,
        }.get(child.type)
        return handler(child) if handler is not None else (self.cursor, [])

    def _code(self, child: Token) -> tuple[int, list[Range]]:
        match = _span_match(self.source, self.cursor, child)
        if match is None:
            return self.cursor, []
        self.cursor = match.end()
        return match.start(), [match.span()]

    def _html(self, child: Token) -> tuple[int, list[Range]]:
        start = self.source.find(child.content, self.cursor)
        if start < 0 or not child.content:
            return self.cursor, []
        self.cursor = start + len(child.content)
        return start, [(start, self.cursor)]

    def _link_open(self, child: Token) -> tuple[int, list[Range]]:
        if child.markup == "autolink":
            start = self.source.find("<", self.cursor)
            end = self.source.find(">", start + 1) if start >= 0 else -1
            if end < 0:
                return self.cursor, []
            self.cursor = end + 1
            return start, [(start, self.cursor)]
        start = _find_unescaped(self.source, "[", self.cursor)
        if start < 0:
            self.opened.append(self.cursor)
            return self.cursor, []
        self.cursor = start + 1
        self.opened.append(self.cursor)
        return start, []

    def _link_close(self, child: Token) -> tuple[int, list[Range]]:
        if child.markup == "autolink":
            return self.cursor, []
        end = _bracket_end(self.source, self.opened.pop() if self.opened else self.cursor)
        if end < 0:
            return self.cursor, []
        after = _destination_end(self.source, end + 1)
        self.cursor = max(self.cursor, after)
        return end, [(end, after)]

    def _image(self, child: Token) -> tuple[int, list[Range]]:
        start = _find_unescaped(self.source, "![", self.cursor)
        end = _bracket_end(self.source, start + 2) if start >= 0 else -1
        if end < 0:
            return self.cursor, []
        ranges: list[Range] = []
        inner = start + 2
        for span in child.children or ():
            match = _span_match(self.source, inner, span) if span.type == "code_inline" else None
            if match is not None and match.end() <= end:
                ranges.append(match.span())
                inner = match.end()
        after = _destination_end(self.source, end + 1)
        self.cursor = after
        return start, [*ranges, (end, after)]


class _InlineScan:
    """Walks one inline token's children, placing each in the source to know its line."""

    def __init__(self, token: Token) -> None:
        self.source = token.content
        self.first = (token.map[0] if token.map is not None else 0) + 1
        self.walk = _SourceWalk(self.source)
        self.line = self.first
        self.mark = 0
        self.in_link = False
        self.found: list[Reference] = []

    def place(self, child: Token) -> tuple[int, list[Range]]:
        """Advance the walk past ``child`` and set the line it starts on."""
        start, ranges = self.walk.advance(child)
        if start < self.mark:
            self.mark, self.line = 0, self.first
        self.line += self.source.count("\n", self.mark, start)
        self.mark = start
        return start, ranges

    def visit(self, child: Token) -> None:
        self.place(child)
        if child.type == "code_inline" and not self.in_link:
            self.found.append(Reference(line=self.line, raw=child.content, source="span", lang=""))
        elif child.type == "link_open":
            self.in_link = True
            if child.markup != "autolink":
                self.found.append(Reference(line=self.line, raw=str(child.attrs.get("href", "")), source="link", lang=""))
        elif child.type == "link_close":
            self.in_link = False
        elif child.type == "image":
            self.found.append(Reference(line=self.line, raw=str(child.attrs.get("src", "")), source="image", lang=""))


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

    Block-level HTML comments are removed first (see :func:`strip_html_comments`); autolinks
    and code spans inside a link's text are not reported.

    Args:
        text: The file content.

    Returns:
        The references in document order, one per code span, link, image, or code block line.
    """
    found: list[Reference] = []
    for token in _PARSER.parse(strip_html_comments(text)):
        if token.type == "inline" and token.map is not None and token.children:
            found.extend(_inline_references(token))
        elif token.type in ("fence", "code_block"):
            found.extend(_block_references(token))
    return found


@dataclass(frozen=True)
class Injection:
    """A shell command a skill or command file injects with ``!`` before its content reaches Claude.

    Attributes:
        line: 1-based line of the inline form, or of a fenced block's first content line.
        command: The command text; a fenced block's whole content.
        form: ``inline`` for ``!`` before a code span, ``fence`` for a code block opened with ```` ```! ````.
        literal: True when the ``!`` follows a character other than whitespace, so Claude Code leaves it as text.
        after: The character right before the ``!``; empty at the start of a line and for a fenced block.
    """

    line: int
    command: str
    form: str
    literal: bool
    after: str


class _InjectionScan(_InlineScan):
    """Walks one inline token's children, collecting ``!`` written right before a code span."""

    def __init__(self, token: Token) -> None:
        super().__init__(token)
        self.injections: list[Injection] = []

    def check(self, span: Token, start: int) -> None:
        """Record ``span`` when an unescaped ``!`` stands right before it in the source, at ``start - 1``."""
        bang = start - 1
        if bang < 0 or self.source[bang] != "!" or _escaped(self.source, bang):
            return
        char = self.source[bang - 1] if bang > 0 else ""
        after = "" if char == "\n" else char
        literal = bool(after) and not after.isspace()
        self.injections.append(Injection(line=self.line, command=span.content, form="inline", literal=literal, after=after))

    def visit(self, child: Token) -> None:
        if child.type != "code_inline":
            super().visit(child)
            return
        start, ranges = self.place(child)
        if ranges and not self.in_link:
            self.check(child, start)


def _from(token: Token, start_line: int) -> bool:
    """True when ``token`` has a source position at or after ``start_line``."""
    return token.map is not None and token.map[0] + 1 >= start_line


def _inline_injections(token: Token) -> list[Injection]:
    scan = _InjectionScan(token)
    for child in token.children or ():
        scan.visit(child)
    return scan.injections


def find_injections(text: str, start_line: int) -> list[Injection]:
    """Find the shell commands a skill or command injects: ``!`` before a code span, and code blocks opened with ```` ```! ````.

    The inline form counts only outside a link's text. It is recognized when the ``!`` starts a
    line or follows whitespace; after any other character it is reported with ``literal`` set,
    because Claude Code leaves it as text.

    Args:
        text: The file content.
        start_line: The 1-based line the body starts on; blocks that start before it, such as frontmatter
            that Markdown reads as a rule and a heading, are skipped.

    Returns:
        The injections in document order.
    """
    found: list[Injection] = []
    for token in _PARSER.parse(_normalize(text)):
        if not _from(token, start_line):
            continue
        if token.type == "inline" and token.children:
            found.extend(_inline_injections(token))
        elif token.type == "fence" and token.markup.startswith("`") and token.info.strip() == "!" and token.map is not None:
            found.append(Injection(line=token.map[0] + 2, command=token.content, form="fence", literal=False, after=""))
    return found


def _blank_spans(token: Token) -> str:
    """Return the inline token's source with what holds no prose replaced by spaces, keeping line breaks.

    That is code spans, inline HTML, autolinks, and link and image destinations (see :class:`_SourceWalk`).
    """
    source = token.content
    walk = _SourceWalk(source)
    chars = list(source)
    for child in token.children or ():
        for start, end in walk.advance(child)[1]:
            chars[start:end] = [char if char == "\n" else " " for char in source[start:end]]
    return "".join(chars)


def prose_segments(text: str, start_line: int) -> list[tuple[int, str]]:
    """Return the prose of a Markdown file line by line, as written, with code spans blanked.

    Each paragraph, heading and list item's source keeps its backslash escapes; code spans become
    spaces of the same length so offsets hold. Code blocks and HTML blocks are left out.

    Args:
        text: The file content.
        start_line: The 1-based line the body starts on; blocks that start before it are skipped.

    Returns:
        ``(line, text)`` pairs in document order, one per source line of prose.
    """
    found: list[tuple[int, str]] = []
    for token in _PARSER.parse(_normalize(text)):
        if token.type == "inline" and token.map is not None and _from(token, start_line):
            first = token.map[0] + 1
            found.extend((first + index, line) for index, line in enumerate(_blank_spans(token).split("\n")))
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
