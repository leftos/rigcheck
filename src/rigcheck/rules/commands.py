"""Rules for legacy command files (.claude/commands/*.md)."""

from collections.abc import Iterator

from rigcheck.model import Finding, Kind, Rig, Severity
from rigcheck.rules import emit, rule
from rigcheck.rules.components import components, load

_SKILL_ONLY_KEYS = ("name", "paths")
"""Skill keys a command file does not support, so Claude Code ignores them there."""


@rule(
    "command-key-ignored",
    "core",
    Severity.WARN,
    "Remove the key, or move the command into a skill folder (.claude/skills/<name>/SKILL.md), which supports it.",
    ("official:SK30",),
)
def command_key_ignored(rig: Rig) -> Iterator[Finding]:
    """A command file key Claude Code supports only in skills, so it is ignored."""
    for artifact in components(rig, (Kind.COMMAND,)):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        for key in _SKILL_ONLY_KEYS:
            if key in parsed.data:
                message = f'"{key}" is not supported in a command file, so Claude Code ignores it'
                yield emit("command-key-ignored", artifact, message, parsed.key_lines.get(key, 1))
