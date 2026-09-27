"""Rules for skill folders (SKILL.md) and their bundled files, and the frontmatter rules skills share with commands."""

from collections.abc import Iterator
from typing import Any

from rigcheck.model import Finding, Kind, Rig, Severity
from rigcheck.parse.frontmatter import FENCE, as_bool
from rigcheck.report.budget import LISTING_DETAIL_CHARS
from rigcheck.rules import emit, rule
from rigcheck.rules.components import KEYS, components, load, unknown_key_message, yaml_line, yaml_reason

LISTED_KINDS = (Kind.SKILL, Kind.COMMAND)
"""The artifact kinds whose frontmatter follows the skill format."""

_COMMAND_UNSUPPORTED = frozenset({"name", "paths"})
"""Skill keys a command file does not support; another rule reports them."""

_BOM = "\ufeff"


@rule(
    "skill-frontmatter-misplaced",
    "core",
    Severity.ERROR,
    "Put the opening --- alone on line 1: nothing before it and no spaces around it.",
    ("official:SK1",),
)
def skill_frontmatter_misplaced(rig: Rig) -> Iterator[Finding]:
    """Frontmatter whose opening --- is not the file's first line."""
    for artifact in components(rig, LISTED_KINDS):
        lines = rig.text(artifact.path).removeprefix(_BOM).split("\n")
        if lines[0].removesuffix("\r") == FENCE:
            continue
        first = next((index for index, line in enumerate(lines) if line.strip()), None)
        if first is not None and lines[first].strip() == FENCE:
            yield emit("skill-frontmatter-misplaced", artifact, _misplaced_message(lines, first), first + 1)


def _misplaced_message(lines: list[str], first: int) -> str:
    """Name the problem: spaces around a fence on line 1, or the later line the fence sits on."""
    consequence = "so Claude Code reads the whole file as content and no field is set"
    if first == 0:
        return f'the opening line is "{lines[0].removesuffix("\r")}", not exactly ---, {consequence}'
    return f"the frontmatter starts on line {first + 1}, {consequence}"


@rule(
    "skill-frontmatter-invalid",
    "core",
    Severity.ERROR,
    'Fix the YAML: quote values that hold ": " or start with a YAML indicator, save the file with LF line endings, and close the block with ---.',
    ("official:SK1",),
)
def skill_frontmatter_invalid(rig: Rig) -> Iterator[Finding]:
    """Frontmatter that Claude Code cannot parse, so the skill loads with no fields set."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.present and parsed.load_error is not None:
            error = parsed.load_error
            message = f"Claude Code rejects the frontmatter ({yaml_reason(error)}), so the skill loads with no fields set"
            yield emit("skill-frontmatter-invalid", artifact, message, yaml_line(error))


@rule(
    "skill-key-unknown",
    "core",
    Severity.WARN,
    "Rename the key to one Claude Code recognizes (the names are case- and hyphen-exact), or remove it.",
    ("official:SK2",),
)
def skill_key_unknown(rig: Rig) -> Iterator[Finding]:
    """A frontmatter key Claude Code does not recognize, so it is ignored."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        known = KEYS[artifact.kind]
        skipped = _COMMAND_UNSUPPORTED if artifact.kind is Kind.COMMAND else frozenset()
        for key in map(str, parsed.data):
            if key not in known and key not in skipped:
                message = unknown_key_message(key, known)
                yield emit("skill-key-unknown", artifact, message, parsed.key_lines.get(key, 1))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@rule(
    "skill-description-missing",
    "core",
    Severity.WARN,
    "Add a description that says what the skill does and when to use it, key use case first.",
    ("official:SK4",),
)
def skill_description_missing(rig: Rig) -> Iterator[Finding]:
    """A skill or command with no description, so Claude matches it on its first line of content."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.present and parsed.data is None:
            continue
        data = parsed.data or {}
        if not _text(data.get("description")).strip():
            message = "no description, so Claude Code lists the first line of content instead"
            yield emit("skill-description-missing", artifact, message, 1)


@rule(
    "skill-description-truncated",
    "core",
    Severity.WARN,
    "Shorten the description and when_to_use, putting the key use case first so the cut falls on detail.",
    ("official:SK4",),
)
def skill_description_truncated(rig: Rig) -> Iterator[Finding]:
    """A description and when_to_use longer than the skill listing keeps."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        parts = (_text(parsed.data.get("description")), _text(parsed.data.get("when_to_use")))
        length = len(" ".join(part for part in parts if part))
        if length > LISTING_DETAIL_CHARS:
            line = parsed.key_lines.get("description", parsed.key_lines.get("when_to_use", 1))
            message = f"description and when_to_use run to {length} characters; the skill listing cuts them at {LISTING_DETAIL_CHARS}"
            yield emit("skill-description-truncated", artifact, message, line)


@rule(
    "skill-unreachable",
    "core",
    Severity.WARN,
    "Remove one of the two settings: keep disable-model-invocation for a skill only you run, or user-invocable: false for one only Claude runs.",
    ("official:SK19",),
)
def skill_unreachable(rig: Rig) -> Iterator[Finding]:
    """A skill hidden from both the user and Claude."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        data = parsed.data
        if data is None:
            continue
        if as_bool(data.get("user-invocable")) is False and as_bool(data.get("disable-model-invocation")) is True:
            message = "user-invocable is false and disable-model-invocation is true, so neither you nor Claude can invoke it"
            yield emit("skill-unreachable", artifact, message, parsed.key_lines.get("disable-model-invocation", 1))
