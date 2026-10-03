"""Shared helpers for the component rules: artifact selection, key tables, the frontmatter warn, misplaced_fence and case_match."""

import re
from collections.abc import Iterator

from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity
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


def plugin_name(artifact: Artifact) -> str | None:
    """Return the name of the plugin ``artifact`` comes from, without its ``@marketplace``.

    Args:
        artifact: A discovered file.

    Returns:
        The plugin name, or None when the file is not from the plugin layer.
    """
    if artifact.layer is not Layer.PLUGIN or artifact.plugin is None:
        return None
    return artifact.plugin.split("@")[0]


_QUOTES = ("'", '"')

_TOOL_ENTRY = re.compile(r"(?:[^,\s()]|\([^)]*\))+")
"""One entry of an allowed-tools string: commas and whitespace separate entries only outside parentheses."""


def _unquote(entry: str) -> str:
    """Strip one pair of matching quotes around ``entry``, as a flow list written inside a string leaves them."""
    if len(entry) >= 2 and entry[0] in _QUOTES and entry[-1] == entry[0]:
        return entry[1:-1]
    return entry


def tool_entries(value: object) -> list[str]:
    """Return the entries of a skill's allowed-tools value.

    Args:
        value: The frontmatter value.

    Returns:
        A list's string items, or a string split into entries (a ``[...]`` flow list loaded as a string is unwrapped
        and unquoted); empty for any other value.
    """
    if isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        items = [_unquote(item.strip()) for item in _TOOL_ENTRY.findall(text)]
    else:
        items = []
    return [item.strip() for item in items if item.strip()]


def load(rig: Rig, artifact: Artifact) -> frontmatter.Frontmatter:
    """Parse ``artifact``'s frontmatter.

    Args:
        rig: The discovered setup.
        artifact: The file to parse.

    Returns:
        The parsed frontmatter, cached by text and shared between callers, so read-only.
    """
    return frontmatter.parse(rig.text(artifact.path))


def normalise_key(key: str) -> str:
    """Return ``key`` with its case, ``-`` and ``_`` folded away, to compare key spellings that differ only in those."""
    return key.lower().replace("-", "").replace("_", "")


def unknown_key_message(key: str, known: frozenset[str]) -> str:
    """Return the unknown-key message, naming the one known key that differs from ``key`` only in case, ``-`` or ``_``.

    Args:
        key: The key the frontmatter sets.
        known: The keys the artifact kind recognizes.

    Returns:
        The message, with a ``did you mean`` hint when exactly one known key is a near match of ``key``.
    """
    matches = [candidate for candidate in known if normalise_key(candidate) == normalise_key(key)]
    if len(matches) == 1:
        return f'unknown key "{key}" (did you mean "{matches[0]}"?); Claude Code ignores it'
    return f'unknown key "{key}"; Claude Code ignores it'


def case_match(value: object, allowed: tuple[str, ...]) -> str | None:
    """Return the allowed value that ``value`` spells in another case.

    Args:
        value: A value from the frontmatter.
        allowed: The values the key accepts.

    Returns:
        The first allowed value equal to ``value`` ignoring case, or None when ``value`` is not a string or matches none.
    """
    if not isinstance(value, str):
        return None
    return next((candidate for candidate in allowed if candidate.casefold() == value.casefold()), None)


def misplaced_fence(text: str) -> tuple[int, str] | None:
    """Find an opening ``---`` that Claude Code does not read as frontmatter because it is not alone on line 1.

    Args:
        text: The whole file content.

    Returns:
        The fence's 1-based line and what is wrong with it; None when line 1 is exactly ``---``, the first
        non-blank line is not a fence, or no closing ``---`` line follows it (a horizontal rule, not frontmatter).
    """
    lines = text.removeprefix(frontmatter.BOM).split("\n")
    if lines[0].removesuffix("\r") == frontmatter.FENCE:
        return None
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None or lines[first].strip() != frontmatter.FENCE:
        return None
    if not any(line.strip() == frontmatter.FENCE for line in lines[first + 1 :]):
        return None
    if first == 0:
        return 1, f'the opening line is "{lines[0].removesuffix("\r")}", not exactly ---'
    return first + 1, f"the frontmatter starts on line {first + 1}"


def yaml_reason(strict_error: str) -> str:
    """Return the line of ``strict_error`` that names the problem, skipping PyYAML's context lines.

    Args:
        strict_error: The error :func:`rigcheck.parse.frontmatter.parse` reported.

    Returns:
        The last line that starts at column 0 and is not an ``in "..."`` mark; the first line when there is none.
    """
    lines = strict_error.removeprefix("invalid YAML: ").splitlines()
    named = [line for line in lines if line[:1].strip() and not line.startswith('in "')]
    return named[-1] if named else lines[0]


def yaml_line(strict_error: str) -> int:
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
            message = f"frontmatter is not strict YAML ({yaml_reason(error)}); Claude Code loads it only through its retry"
            yield emit("frontmatter-yaml-nonstandard", artifact, message, yaml_line(error))
