"""Advice-pack rules for instruction files: info-only style advice that cites the doc and the null result."""

import re
from collections.abc import Iterator
from pathlib import Path

from rigcheck.discover import AGENTS_MD, path_key
from rigcheck.model import Artifact, Finding, Kind, LoadClass, Rig, Severity
from rigcheck.parse.markdown import (
    code_blocks,
    strip_html_comments,
    structure_count,
    top_level_ordered_lists,
    top_level_paragraphs,
)
from rigcheck.rules import emit, rule
from rigcheck.rules.components import body_prose, load, maintained

_SIZED_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS, Kind.RULE)
_EVERY_TURN_KINDS = (Kind.INSTRUCTIONS, Kind.RULE)
_LINE_BREAK = re.compile(r"\r\n?|\n")
_MAX_LINES = 200
_EMPHASIS = re.compile(r"\b(?:IMPORTANT|CRITICAL|MUST|NEVER|ALWAYS|MANDATORY|REQUIRED|ABSOLUTELY|ESSENTIAL)\b")
_IF_IN_DOUBT = re.compile(r"\bif in doubt\b", re.IGNORECASE)
_MIN_EMPHASIZED = 5
_EMPHASIS_SHARE = 20
"""One emphasized line in this many prose lines (5%) is the least that counts as dense."""
_PARAGRAPH_WORDS = 150
_UNSTRUCTURED_LINES = 30
_PROCEDURE_STEPS = 8
_TABLE_DELIMITER = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_CLAUDE_NAMES = ("CLAUDE.md", "CLAUDE.local.md")
_AGENTS_POINTER = re.compile(r"\b(?:read|see|follow|refer to|consult|check|load|look at|defer to)\b", re.IGNORECASE)
_TREE_LINE = re.compile(r"^[\s│|]*(?:[├└]─+|\|--|\+--|`--)-*\s+[\w.@~-]")
_TREE_LINES = 8
_DEPENDENCY = re.compile(r"""^\s*(?:[-*]\s+)?["']?[@A-Za-z0-9_.\-/]+["']?\s*(?:==|>=|<=|~=|\^|@|:|=)\s*["']?[\^~>=<]*\d+\.\d+""")
_DEPENDENCY_RUN = 15
_HOOK_MOMENT = re.compile(r"\b(?:before|after)\s+(?:(?:every|each|any|you)\s+)?(?:commit|push|edit|file edit|write|save)s?\b", re.IGNORECASE)
_HOOK_DEMAND = re.compile(r"\b(?:always|must|make sure|ensure|run)\b", re.IGNORECASE)
_HOOK_BAN = re.compile(r"\b(?:never|do not|don't)\s+(?:edit|read|touch|modify|write to|commit|delete)\b", re.IGNORECASE)
_PROTECTED = re.compile(
    r"(?<![\w.])\.env\b|\bsecrets?\b|\bcredentials?\b|\blockfiles?\b"
    r"|(?<![\w.-])(?:package-lock\.json|pnpm-lock\.yaml|yarn\.lock|uv\.lock|cargo\.lock|poetry\.lock)\b",
    re.IGNORECASE,
)
"""Names a must-not-touch rule protects."""


def _every_turn(rig: Rig) -> list[Artifact]:
    """The maintained CLAUDE.md, AGENTS.md and rule files that load on every turn."""
    return [artifact for artifact in maintained(rig, _EVERY_TURN_KINDS) if artifact.load_class is LoadClass.EVERY_TURN]


def body_lines(text: str, body_line: int) -> list[tuple[str, str]]:
    """Return each line from ``body_line`` on as written and as Claude Code loads it, with block HTML comments removed.

    Args:
        text: The whole file content.
        body_line: The 1-based line to start from.

    Returns:
        ``(written, loaded)`` pairs, one per line; a line inside a block HTML comment loads as an empty string.
    """
    written = _LINE_BREAK.split(text)
    loaded = strip_html_comments(text).split("\n")
    if written[-1] == "":
        written, loaded = written[:-1], loaded[:-1]
    return list(zip(written[body_line - 1 :], loaded[body_line - 1 :], strict=True))


def loaded_line_count(lines: list[tuple[str, str]]) -> int:
    """Count the lines of :func:`body_lines` that Claude Code sees: blank lines count, block HTML comment lines do not."""
    return sum(1 for written, loaded in lines if loaded.strip() or not written.strip())


def body_line_count(rig: Rig, artifact: Artifact) -> int:
    """Count the lines of ``artifact``'s body that Claude Code loads.

    Args:
        rig: The discovered setup.
        artifact: The file to measure.

    Returns:
        The lines from the line the body starts on to the end of the file, without the lines that hold only a block
        HTML comment; blank lines count.
    """
    return loaded_line_count(body_lines(rig.text(artifact.path), load(rig, artifact).body_line))


@rule(
    "instructions-long",
    "advice",
    Severity.INFO,
    "Move material that only some tasks or paths need into a skill or a path-scoped rule. "
    "This saves context; no study has measured an adherence drop from length alone.",
    ("official:CM1", "sota:#4 (A)"),
)
def instructions_long(rig: Rig) -> Iterator[Finding]:
    """An instruction file runs past 200 lines."""
    for artifact in maintained(rig, _SIZED_KINDS):
        count = body_line_count(rig, artifact)
        if count > _MAX_LINES:
            yield emit("instructions-long", artifact, f"{count} lines; Anthropic's guidance is under 200 per instruction file", None)


def _emphasized(line: str) -> bool:
    return _EMPHASIS.search(line) is not None or _IF_IN_DOUBT.search(line) is not None


@rule(
    "emphasis-dense",
    "advice",
    Severity.INFO,
    "Keep all-caps emphasis such as IMPORTANT, MUST or NEVER for the one or two rules that need it and state the rest plainly; "
    "when many lines are emphasized, none stands out.",
    ("official:CM11", "official:PR4", "sota:#12 (C)"),
)
def emphasis_dense(rig: Rig) -> Iterator[Finding]:
    """Many lines of an every-turn file use all-caps emphasis."""
    for artifact in _every_turn(rig):
        prose = [(number, text) for number, text in body_prose(rig, artifact) if text.strip()]
        hits = [number for number, text in prose if _emphasized(text)]
        if len(hits) >= _MIN_EMPHASIZED and _EMPHASIS_SHARE * len(hits) >= len(prose):
            message = f"{len(hits)} of {len(prose)} prose lines use all-caps emphasis such as IMPORTANT, MUST or NEVER"
            yield emit("emphasis-dense", artifact, message, hits[0])


def _delimiter_row(line: str) -> bool:
    return "|" in line and _TABLE_DELIMITER.match(line) is not None


def _table_header(lines: list[str]) -> int | None:
    """The index of the header line of a GFM pipe table in a paragraph's lines, or None when it holds no table.

    The CommonMark parser reads a pipe table, and any text lines right before it, as one paragraph.
    """
    for index in range(1, len(lines)):
        if _delimiter_row(lines[index]) and "|" in lines[index - 1]:
            return index - 1
    return None


def _unstructured(rig: Rig, artifact: Artifact) -> Iterator[Finding]:
    """The long paragraphs of one file, then the whole-file finding when it has no heading, list or table."""
    text = rig.text(artifact.path)
    start = load(rig, artifact).body_line
    has_table = False
    for line, paragraph in top_level_paragraphs(text, start):
        lines = paragraph.split("\n")
        header = _table_header(lines)
        has_table = has_table or header is not None
        words = len(" ".join(lines if header is None else lines[:header]).split())
        if words >= _PARAGRAPH_WORDS:
            yield emit("instructions-unstructured", artifact, f"a paragraph of {words} words; split it into bullets under a heading", line)
    lines = sum(1 for _, prose in body_prose(rig, artifact) if prose.strip())
    if lines >= _UNSTRUCTURED_LINES and not has_table and structure_count(text, start) == 0:
        yield emit("instructions-unstructured", artifact, f"{lines} lines with no heading or list", None)


@rule(
    "instructions-unstructured",
    "advice",
    Severity.INFO,
    "Group related instructions under headings and bullets; Claude scans structure the way readers do.",
    ("official:CM12", "sota:#4 (A)"),
)
def instructions_unstructured(rig: Rig) -> Iterator[Finding]:
    """An every-turn file has a long unbroken paragraph or no headings and lists."""
    for artifact in _every_turn(rig):
        yield from _unstructured(rig, artifact)


@rule(
    "instructions-long-procedure",
    "advice",
    Severity.INFO,
    "Move a multi-step procedure into a skill, which loads only when invoked, and name the skill where the steps were.",
    ("official:CM9", "sota:#4 (A)"),
)
def instructions_long_procedure(rig: Rig) -> Iterator[Finding]:
    """An every-turn file holds a numbered procedure of eight or more steps."""
    for artifact in _every_turn(rig):
        for line, items in top_level_ordered_lists(rig.text(artifact.path), load(rig, artifact).body_line):
            if items >= _PROCEDURE_STEPS:
                yield emit("instructions-long-procedure", artifact, f"a numbered list of {items} steps loads on every turn", line)


def _prose_source(rig: Rig, artifact: Artifact) -> list[tuple[int, str]]:
    """Each prose line of the body as written, code spans kept; code blocks, HTML blocks and frontmatter left out."""
    written = _LINE_BREAK.split(rig.text(artifact.path))
    return [(number, written[number - 1]) for number, _ in body_prose(rig, artifact)]


def _has_agents_peer(path: Path, agents_folders: set[str]) -> bool:
    """True when an AGENTS.md sits beside ``path``, or above it when ``path`` is in a ``.claude`` folder."""
    folders = [path.parent, path.parent.parent] if path.parent.name == ".claude" else [path.parent]
    return any(path_key(folder) in agents_folders for folder in folders)


def _pointer_files(rig: Rig) -> list[Artifact]:
    """The every-turn CLAUDE.md and CLAUDE.local.md files beside an AGENTS.md that Claude Code does not load."""
    shadowed = {
        path_key(artifact.path.parent)
        for artifact in rig.artifacts
        if artifact.path.name == AGENTS_MD and artifact.load_class is LoadClass.NOT_LOADED
    }
    return [
        artifact
        for artifact in maintained(rig, (Kind.INSTRUCTIONS,))
        if artifact.path.name in _CLAUDE_NAMES and artifact.load_class is LoadClass.EVERY_TURN and _has_agents_peer(artifact.path, shadowed)
    ]


@rule(
    "agents-md-prose-pointer",
    "advice",
    Severity.INFO,
    "Replace the sentence with an @AGENTS.md import line so Claude Code loads the file, or drop it if AGENTS.md is meant only for other agents.",
    ("official:CM4", "sota:#2 (A)"),
)
def agents_md_prose_pointer(rig: Rig) -> Iterator[Finding]:
    """An instruction file tells Claude in prose to read AGENTS.md instead of importing it."""
    for artifact in _pointer_files(rig):
        for number, line in _prose_source(rig, artifact):
            if AGENTS_MD in line and _AGENTS_POINTER.search(line):
                yield emit(
                    "agents-md-prose-pointer",
                    artifact,
                    "points to AGENTS.md in prose; Claude Code reads it only through an @AGENTS.md import",
                    number,
                )


def _longest_dependency_run(lines: list[str]) -> int:
    longest = current = 0
    for line in lines:
        current = current + 1 if _DEPENDENCY.match(line) else 0
        longest = max(longest, current)
    return longest


def _dump_message(lines: list[str]) -> str | None:
    """The finding message for a code block that is a directory tree or a dependency list, or None."""
    nonblank = [line for line in lines if line.strip()]
    tree = sum(1 for line in nonblank if _TREE_LINE.match(line))
    if len(nonblank) >= _TREE_LINES and 5 * tree >= 3 * len(nonblank):
        return f"a directory tree of {len(nonblank)} lines Claude can list itself"
    run = _longest_dependency_run(lines)
    if run >= _DEPENDENCY_RUN:
        return f"a dependency list of {run} lines Claude can read from the manifest"
    return None


@rule(
    "instructions-derivable-dump",
    "advice",
    Severity.INFO,
    "Drop the listing and name where it lives (the manifest, or a command such as tree); "
    "Claude can read the current version itself, and a copy here goes stale.",
    ("official:CM8", "sota:#3 (A)"),
)
def instructions_derivable_dump(rig: Rig) -> Iterator[Finding]:
    """An every-turn file holds a directory tree or dependency list Claude can derive from the repo."""
    for artifact in _every_turn(rig):
        for line, lines in code_blocks(rig.text(artifact.path), load(rig, artifact).body_line):
            message = _dump_message(lines)
            if message is not None:
                yield emit("instructions-derivable-dump", artifact, message, line)


def _hookable(line: str) -> bool:
    """True when the line asks for something at a commit, push or edit, or bans touching secrets or lockfiles."""
    if _HOOK_MOMENT.search(line) and _HOOK_DEMAND.search(line):
        return True
    return _HOOK_BAN.search(line) is not None and _PROTECTED.search(line) is not None


@rule(
    "instruction-better-as-hook",
    "advice",
    Severity.INFO,
    "If this must happen every time, enforce it with a hook (a Claude Code PreToolUse or PostToolUse hook, or a git hook) "
    "and keep at most a one-line note here; an instruction is a request, not a guarantee.",
    ("official:CM10", "sota:#5 (A)"),
)
def instruction_better_as_hook(rig: Rig) -> Iterator[Finding]:
    """An every-turn file states a must-happen rule that a hook could enforce."""
    for artifact in _every_turn(rig):
        for number, line in _prose_source(rig, artifact):
            if _hookable(line):
                yield emit("instruction-better-as-hook", artifact, "a must-happen rule in prose; a hook would enforce it", number)
