"""Advice-pack rules for skills, commands and agents: info-only style advice on context cost, discovery and scanning."""

import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from rigcheck.discover import path_key
from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import find_references
from rigcheck.rules import emit, rule
from rigcheck.rules.advice_instructions import body_line_count, body_lines, loaded_line_count
from rigcheck.rules.agent_refs import agent_list_entries, tool_name
from rigcheck.rules.agents import loaded_agents
from rigcheck.rules.components import body_prose, load, maintained
from rigcheck.rules.skills import LISTED_KINDS, bundled_files

_QUOTES = "\"'"
_PERSONAL_START = re.compile(r"^(?:I'm|I'll|You'll|We'll|I|You|Your|We|My|Our)(?=\s|$)", re.IGNORECASE)
"""A description opening with a first- or second-person word followed by whitespace or the end: I, I'm, I'll, You, You'll,
Your, We, We'll, My or Our; ``I/O`` and ``I.e.`` are not."""

_MAX_SKILL_LINES = 500
_TOC_MIN_LINES = 101
_TOC_WINDOW = 20
"""How many non-blank lines at the top of a reference file may hold its table of contents."""

_TOC_RUN = 3
_TOC_HEADING = re.compile(r"^#{1,6}\s*(?:table of contents|contents|toc)\b", re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_ANCHOR_LINK = re.compile(r"\[[^\]]+\]\(#[^)]+\)")
_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*\.[A-Za-z0-9]+$")
_WINDOWS_ONLY_SUFFIXES = frozenset({".exe", ".dll", ".bat", ".cmd", ".sys", ".msi"})
"""Extensions of Windows binaries and scripts, whose native separator is the backslash; ``.ps1`` is not one, pwsh runs everywhere."""

_CHECKED_SOURCES = ("link", "image", "span")
_LINKED = ("link", "image")
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_YEAR = r"(?:19|20)\d\d\b"
_DATED = re.compile(
    rf"\b(?:before|after|until|since|as\s+of)\s+(?:(?:{_MONTHS})\s+{_YEAR}|q[1-4]\s+{_YEAR}|{_YEAR}(?!\s*[A-Za-z]))",
    re.IGNORECASE,
)
"""A dated condition: before, after, until, since or as of, then a month and year, a quarter and year, or a bare year
that no word follows (so ``after 2000 ms`` is a count, not a date)."""

_READ_ONLY = re.compile(r"\b(?:review\w*|audit\w*|research\w*|explor\w*|read-only|analy[sz]\w*|inspect\w*)\b", re.IGNORECASE)
_WRITE_INTENT = re.compile(
    r"\b(?:implement|fix|writ(?:e|es|ing)|edit|refactor|generat|creat|updat|appl(?:y|ies)|modif|chang|patch|add|remov|delet|renam|migrat|commit)\w*",
    re.IGNORECASE,
)
_WRITE_TOOLS = ("Write", "Edit", "NotebookEdit")
"""The tools that change files; MultiEdit is a legacy permission name with no tool (agents.PERMISSION_ONLY_TOOLS)."""


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@rule(
    "skill-description-not-third-person",
    "advice",
    Severity.INFO,
    'Write the description in the third person ("Reviews code ..."): it is injected into the system prompt, '
    "where a shifting point of view can hurt discovery.",
    ("official:SK6",),
)
def skill_description_not_third_person(rig: Rig) -> Iterator[Finding]:
    """A skill or command description written in the first or second person."""
    for artifact in maintained(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        description = _text((parsed.data or {}).get("description")).strip().strip(_QUOTES).strip()
        if _PERSONAL_START.match(description):
            message = "skill description starts in the first or second person"
            yield emit("skill-description-not-third-person", artifact, message, parsed.key_lines.get("description", 1))


@rule(
    "skill-body-long",
    "advice",
    Severity.INFO,
    "Move detailed reference material into files the skill links, and keep SKILL.md under 500 lines so the body stays cheap when the skill loads.",
    ("official:SK9", "sota:#17 (B)"),
)
def skill_body_long(rig: Rig) -> Iterator[Finding]:
    """A SKILL.md body runs past 500 lines."""
    for artifact in maintained(rig, (Kind.SKILL,)):
        count = body_line_count(rig, artifact)
        if count > _MAX_SKILL_LINES:
            yield emit("skill-body-long", artifact, f"SKILL.md body is {count} lines (over 500)", None)


def _bundled_markdown(rig: Rig, artifact: Artifact) -> list[Path]:
    """The ``.md`` files bundled in a skill's folder, SKILL.md left out."""
    return [path for path in bundled_files(rig, artifact) if path.suffix.lower() == ".md"]


def _anchor_list_starts_early(lines: list[str]) -> bool:
    """True when a run of three or more list items holding in-page anchor links starts within the first twenty lines."""
    run = 0
    for index, line in enumerate(lines):
        run = run + 1 if _LIST_ITEM.match(line) and _ANCHOR_LINK.search(line) else 0
        if run >= _TOC_RUN and index - run + 1 < _TOC_WINDOW:
            return True
    return False


def _has_toc(lines: list[str]) -> bool:
    """True when the first twenty non-blank lines hold a contents heading or a list of in-page anchor links."""
    nonblank = [line for line in lines if line.strip()]
    if any(_TOC_HEADING.match(line.strip()) for line in nonblank[:_TOC_WINDOW]):
        return True
    return _anchor_list_starts_early(nonblank)


@rule(
    "skill-reference-no-toc",
    "advice",
    Severity.INFO,
    "Add a contents list at the top of reference files over 100 lines, so a partial read still shows Claude what the file covers.",
    ("official:SK12",),
)
def skill_reference_no_toc(rig: Rig) -> Iterator[Finding]:
    """A reference file bundled in a skill runs past 100 lines with no table of contents at the top."""
    for artifact in maintained(rig, (Kind.SKILL,)):
        for path in _bundled_markdown(rig, artifact):
            lines = body_lines(rig.text(path), 1)
            count = loaded_line_count(lines)
            if count >= _TOC_MIN_LINES and not _has_toc([loaded for _, loaded in lines]):
                message = f"reference file is {count} lines with no table of contents at the top"
                yield replace(emit("skill-reference-no-toc", artifact, message, 1), path=path)


def backslash_path(text: str) -> bool:
    r"""Say whether a link target or code span is a relative path written with backslashes, such as ``docs\guide.md``.

    Args:
        text: The link target or code span content.

    Returns:
        True when ``text`` splits on ``\`` into two or more segments of letters, digits, ``_``, ``.`` and ``-``, no
        segment after the first starts with ``.``, and the last segment is a file name with an extension. Regex escapes
        such as ``settings\.json`` or ``\d+\.\d+``, registry keys and folders with no file name, Windows binaries and
        scripts (``.exe``, ``.dll``, ``.bat``, ``.cmd``, ``.sys``, ``.msi``), drive-letter and UNC paths, and text with
        spaces are not.
    """
    parts = text.split("\\")
    if len(parts) < 2 or not all(_PATH_SEGMENT.match(part) for part in parts):
        return False
    if any(part.startswith(".") for part in parts[1:]):
        return False
    return _FILE_NAME.match(parts[-1]) is not None and Path(parts[-1]).suffix.lower() not in _WINDOWS_ONLY_SUFFIXES


def _backslash_findings(rig: Rig, artifact: Artifact, path: Path, body_line: int) -> Iterator[Finding]:
    """The backslash paths in the links, images and code spans of ``path``'s body; frontmatter is not Markdown."""
    for reference in find_references(rig.text(path)):
        if reference.line < body_line or reference.source not in _CHECKED_SOURCES:
            continue
        written = unquote(reference.raw) if reference.source in _LINKED else reference.raw
        if backslash_path(written):
            finding = emit("skill-backslash-path", artifact, f"path uses backslashes: {written}", reference.line)
            yield replace(finding, path=path)


@rule(
    "skill-backslash-path",
    "advice",
    Severity.INFO,
    "Use forward slashes in file paths; they work on every platform, backslashes only on Windows.",
    ("official:SK13",),
)
def skill_backslash_path(rig: Rig) -> Iterator[Finding]:
    """A link or code span in a skill, command or bundled reference file writes a path with backslashes."""
    for artifact in maintained(rig, LISTED_KINDS):
        yield from _backslash_findings(rig, artifact, artifact.path, load(rig, artifact).body_line)
        if artifact.kind is Kind.SKILL:
            for path in _bundled_markdown(rig, artifact):
                yield from _backslash_findings(rig, artifact, path, frontmatter.parse(rig.text(path)).body_line)


@rule(
    "skill-time-sensitive-text",
    "advice",
    Severity.INFO,
    'Drop dated instructions or move them to a clearly marked "old patterns" section, so the skill does not go stale when the date passes.',
    ("official:SK14",),
)
def skill_time_sensitive_text(rig: Rig) -> Iterator[Finding]:
    """A SKILL.md line ties an instruction to a date, such as before August 2025."""
    for artifact in maintained(rig, (Kind.SKILL,)):
        for number, line in body_prose(rig, artifact):
            match = _DATED.search(line)
            if match is not None:
                yield emit("skill-time-sensitive-text", artifact, f'time-sensitive text: "{match.group(0)}"', number)


def _sounds_read_only(data: dict[Any, Any]) -> bool:
    name, description = _text(data.get("name")), _text(data.get("description"))
    said = f"{name}\n{description}"
    return _READ_ONLY.search(said) is not None and _WRITE_INTENT.search(said) is None


def _write_tools(data: dict[Any, Any]) -> tuple[bool, list[str]]:
    """Return whether the agent inherits every tool, and the write tools it can use after disallowedTools."""
    entries = agent_list_entries(data.get("tools"))
    inherits = data.get("tools") is None or "*" in entries
    named = {tool_name(entry) for entry in entries}
    candidates = _WRITE_TOOLS if inherits else tuple(tool for tool in _WRITE_TOOLS if tool in named)
    removed = {tool_name(entry) for entry in agent_list_entries(data.get("disallowedTools"))}
    tools = [tool for tool in candidates if tool not in removed]
    return inherits and len(tools) == len(candidates), tools


@rule(
    "agent-read-only-has-write-tools",
    "advice",
    Severity.INFO,
    "Give a read-only agent an explicit tools list without Write, Edit or NotebookEdit, so it cannot change files it is only meant to read.",
    ("official:AG10",),
)
def agent_read_only_has_write_tools(rig: Rig) -> Iterator[Finding]:
    """An agent that sounds read-only, such as a reviewer or auditor, can still write files."""
    kept = {path_key(artifact.path) for artifact in maintained(rig, (Kind.AGENT,))}
    for artifact, parsed, data in loaded_agents(rig):
        if path_key(artifact.path) not in kept or not _sounds_read_only(data):
            continue
        inherits_all, tools = _write_tools(data)
        if not tools:
            continue
        reach = "inherits every tool" if inherits_all else f"can use {', '.join(tools)}"
        line = parsed.key_lines.get("tools", parsed.key_lines.get("description", 1))
        yield emit("agent-read-only-has-write-tools", artifact, f"agent sounds read-only but {reach}", line)
