"""Advice-pack rules for rule files, the memory index and prompt prose: info-only style advice on cost, scanning and upkeep."""

import re
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import markup_lines, prose_segments, strip_html_comments
from rigcheck.rules import emit, rule
from rigcheck.rules.components import body_prose, maintained
from rigcheck.rules.memory import index_links, memory_artifacts
from rigcheck.rules.skills import bundled_files

_GENERIC_NAMES = frozenset({"rules", "rule", "misc", "miscellaneous", "notes", "general", "other", "stuff", "untitled", "new", "temp", "tmp"})
_COUNTER = re.compile(r"[-_ ]?\d+$")
"""A trailing counter on a file stem, as in ``rules2`` or ``general-1``."""

_SHOW = r"show|explain|reveal|expose|narrate|describe|share|print|output|display|walk through|lay out|spell out|write out"
_REASONING = re.compile(
    rf"\b(?:{_SHOW})\s+(?:me\s+)?(?:your|its|their)\s+(?:(?:internal|own|full|complete|detailed|step-by-step)\s+)*"
    r"(?:reasoning|thinking|thought process|chain[- ]of[- ]thought)\b",
    re.IGNORECASE,
)
_THOUGHTS = re.compile(r"\b(?:transcribe|echo|write out|spell out)\s+(?:your|its)\s+(?:internal\s+)?thoughts\b", re.IGNORECASE)
_ALOUD = re.compile(r"\bthink(?:ing)?\s+(?:out loud|aloud)\b", re.IGNORECASE)
_REQUESTS = (_REASONING, _THOUGHTS, _ALOUD)
_ALOUD_LEAD = re.compile(r"^\s*(?:(?:please|always|you should|you must)\s+)?$", re.IGNORECASE)
"""What may come before "think out loud" in its clause for it to be an instruction: nothing, or please, always, you should or you must."""

_CLAUSE_BREAK = re.compile(r"[.;:,!?\N{EM DASH}]")
_APOSTROPHES = "'\N{RIGHT SINGLE QUOTATION MARK}"
_NEGATION = re.compile(rf"\b(?:don[{_APOSTROPHES}]t|do not|never|not|without|avoid|no need to)\b", re.IGNORECASE)
"""A negation before the request in its clause, with a straight or typographic apostrophe in "don't"."""

_PROMPT_KINDS = (Kind.SKILL, Kind.COMMAND, Kind.AGENT, Kind.OUTPUT_STYLE, Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS, Kind.RULE)


@rule(
    "rule-filename-generic",
    "advice",
    Severity.INFO,
    "Name each rule file for the one topic it covers (testing.md, api-design.md), so its name says what it holds.",
    ("official:RL5",),
)
def rule_filename_generic(rig: Rig) -> Iterator[Finding]:
    """A rule file's name, such as misc.md or notes.md, says nothing about its topic."""
    for artifact in maintained(rig, (Kind.RULE,)):
        stem = _COUNTER.sub("", artifact.path.stem.lower())
        if stem in _GENERIC_NAMES:
            message = f'rule file name "{artifact.path.name}" says nothing about its topic'
            yield emit("rule-filename-generic", artifact, message, None)


def _offending_lines(rig: Rig, index: Artifact) -> tuple[list[int], int]:
    """Return the numbers of the index lines that link no local file, and how many lines were counted.

    Blank lines, headings, code blocks and block-level HTML comments are not counted; the structure comes from the
    same parse :func:`index_links` reads.
    """
    text = rig.text(index.path)
    linked = {reference.line for reference, _ in index_links(rig, index)}
    skipped = markup_lines(text)
    counted = [number for number, line in enumerate(strip_html_comments(text).split("\n"), start=1) if line.strip() and number not in skipped]
    return [number for number in counted if number not in linked], len(counted)


@rule(
    "memory-index-shape",
    "advice",
    Severity.INFO,
    "Keep MEMORY.md to one line per entry, each linking its topic file; move detail into the topic file, since the index loads every turn.",
    ("official:MM2",),
)
def memory_index_shape(rig: Rig) -> Iterator[Finding]:
    """A MEMORY.md line is not a one-line entry linking a topic file."""
    for index in memory_artifacts(rig, Kind.MEMORY_INDEX):
        offending, counted = _offending_lines(rig, index)
        if offending:
            message = f"{len(offending)} of {counted} index lines are not a one-line entry linking a topic file"
            yield emit("memory-index-shape", index, message, offending[0])


def _clause_lead(line: str, match: re.Match[str]) -> str:
    """Return the text of ``match``'s clause before it: from the last clause break before the match, or the line start."""
    breaks = [found.end() for found in _CLAUSE_BREAK.finditer(line, 0, match.start())]
    return line[breaks[-1] if breaks else 0 : match.start()]


def _is_request(line: str, match: re.Match[str]) -> bool:
    """True when no negation precedes ``match`` in its clause, and "think out loud" opens its clause as an instruction."""
    lead = _clause_lead(line, match)
    if _NEGATION.search(lead):
        return False
    return match.re is not _ALOUD or _ALOUD_LEAD.match(lead) is not None


def _reasoning_request(line: str) -> str | None:
    """Return the first phrase on ``line`` that asks for the model's reasoning and is not negated in its clause."""
    matches = sorted((match for pattern in _REQUESTS for match in pattern.finditer(line)), key=lambda match: match.start())
    return next((match.group(0) for match in matches if _is_request(line, match)), None)


def _reasoning_findings(artifact: Artifact, lines: list[tuple[int, str]], path: Path) -> Iterator[Finding]:
    """The reasoning requests among ``lines`` of ``path``, reported against ``artifact``."""
    for number, line in lines:
        phrase = _reasoning_request(line)
        if phrase is not None:
            finding = emit("prompt-reasoning-extraction", artifact, f'asks the model to show its reasoning: "{phrase}"', number)
            yield replace(finding, path=path)


def _prompt_files(rig: Rig) -> Iterator[tuple[Artifact, Path]]:
    """Yield each maintained prompt file, memory file and Markdown file bundled in a maintained skill, with its owner."""
    for artifact in maintained(rig, _PROMPT_KINDS):
        yield artifact, artifact.path
        if artifact.kind is Kind.SKILL:
            yield from ((artifact, path) for path in bundled_files(rig, artifact) if path.suffix.lower() == ".md")
    for kind in (Kind.MEMORY_INDEX, Kind.MEMORY_TOPIC):
        yield from ((artifact, artifact.path) for artifact in memory_artifacts(rig, kind))


@rule(
    "prompt-reasoning-extraction",
    "advice",
    Severity.INFO,
    "Ask for the conclusion and its justification instead of the model's reasoning as text; reflection instructions can trigger "
    "the reasoning_extraction refusal on Fable and Mythos 5 models and later.",
    ("official:PR10",),
)
def prompt_reasoning_extraction(rig: Rig) -> Iterator[Finding]:
    """A prompt line asks the model to show or narrate its reasoning."""
    for artifact, path in _prompt_files(rig):
        if path == artifact.path:
            lines = body_prose(rig, artifact)
        else:
            text = rig.text(path)
            lines = prose_segments(text, frontmatter.parse(text).body_line)
        yield from _reasoning_findings(artifact, lines, path)
