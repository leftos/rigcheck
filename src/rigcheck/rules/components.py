"""Shared helpers for the component rules: artifact selection, recognized key tables and the frontmatter warn."""

import re
from collections.abc import Iterator

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import frontmatter
from rigcheck.rules import emit, rule

_LINE_REFERENCE = re.compile(r"line (\d+), column")
"""The line and column a PyYAML error's mark names."""

SKILL_KEYS = frozenset(
    {
        "name",
        "description",
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "allowed-tools",
        "disallowed-tools",
        "model",
        "effort",
        "context",
        "agent",
        "background",
        "hooks",
        "paths",
        "shell",
        "metadata",
        "license",
        "compatibility",
    }
)
"""The keys Claude Code recognizes in a skill's frontmatter (official.md:107)."""

COMMAND_KEYS = SKILL_KEYS - {"name", "paths"}
"""The keys a command file accepts: the skill keys "except ``name`` and ``paths``" (official.md:107)."""

AGENT_KEYS = frozenset(
    {
        "name",
        "description",
        "tools",
        "disallowedTools",
        "model",
        "permissionMode",
        "maxTurns",
        "skills",
        "mcpServers",
        "hooks",
        "memory",
        "background",
        "omitClaudeMd",
        "effort",
        "isolation",
        "color",
        "initialPrompt",
        "experimental",
    }
)
"""The keys Claude Code recognizes in a subagent definition (official.md:144)."""

RULE_KEYS = frozenset({"paths"})
"""The one key Claude Code reads from a rule file (official.md:84)."""

OUTPUT_STYLE_KEYS = frozenset({"name", "description", "keep-coding-instructions", "force-for-plugin"})
"""The keys Claude Code recognizes in an output style (official.md:218)."""

KEYS: dict[Kind, frozenset[str]] = {
    Kind.SKILL: SKILL_KEYS,
    Kind.COMMAND: COMMAND_KEYS,
    Kind.AGENT: AGENT_KEYS,
    Kind.RULE: RULE_KEYS,
    Kind.OUTPUT_STYLE: OUTPUT_STYLE_KEYS,
}
"""The recognized frontmatter keys of each component kind."""

FRONTMATTER_KINDS = (Kind.SKILL, Kind.COMMAND, Kind.AGENT, Kind.RULE, Kind.OUTPUT_STYLE)
"""The artifact kinds whose frontmatter Claude Code reads."""


def components(rig: Rig, kinds: tuple[Kind, ...]) -> list[Artifact]:
    """Return the rig's artifacts of the given kinds, in rig order, from every layer.

    Args:
        rig: The discovered setup.
        kinds: The artifact kinds to keep.

    Returns:
        The matching artifacts, in the order discovery recorded them.
    """
    return [artifact for artifact in rig.artifacts if artifact.kind in kinds]


def load(rig: Rig, artifact: Artifact) -> frontmatter.Frontmatter:
    """Parse ``artifact``'s frontmatter.

    Args:
        rig: The discovered setup.
        artifact: The file to parse.

    Returns:
        The parsed frontmatter, with no cache between calls.
    """
    return frontmatter.parse(rig.text(artifact.path))


def _yaml_reason(strict_error: str) -> str:
    """Return the line of ``strict_error`` that names the problem, skipping PyYAML's context lines.

    Args:
        strict_error: The error :func:`rigcheck.parse.frontmatter.parse` reported.

    Returns:
        The last line that starts at column 0 and is not an ``in "..."`` mark; the first line when there is none.
    """
    lines = strict_error.removeprefix("invalid YAML: ").splitlines()
    named = [line for line in lines if line[:1].strip() and not line.startswith('in "')]
    return named[-1] if named else lines[0]


def _yaml_line(strict_error: str) -> int:
    """Return the file line the error points at: the block's line ``N`` is the file's line ``N + 1``.

    Args:
        strict_error: The error :func:`rigcheck.parse.frontmatter.parse` reported.

    Returns:
        One more than the last ``line N`` the error names, or 1 when it names none.
    """
    marks = _LINE_REFERENCE.findall(strict_error)
    return int(marks[-1]) + 1 if marks else 1


@rule(
    "frontmatter-yaml-nonstandard",
    "core",
    Severity.WARN,
    'Quote the value that holds ": " or starts with a YAML indicator (description: "…"), '
    "or write it as a block scalar (description: >-), so the block is plain YAML that every loader reads.",
    ("official:SK1", "official:AG1", "rigcheck:frontmatter-probe"),
)
def frontmatter_yaml_nonstandard(rig: Rig) -> Iterator[Finding]:
    """Frontmatter that Claude Code loads but strict YAML rejects."""
    for artifact in components(rig, FRONTMATTER_KINDS):
        parsed = load(rig, artifact)
        if parsed.present and parsed.strict_error is not None and parsed.load_error is None:
            error = parsed.strict_error
            message = f"frontmatter is not strict YAML ({_yaml_reason(error)}); Claude Code loads it only through its retry"
            yield emit("frontmatter-yaml-nonstandard", artifact, message, _yaml_line(error))
