"""Claude Code permission rules: parsing ``Tool`` and ``Tool(specifier)`` entries, and matching Bash patterns."""

import re
from dataclasses import dataclass

_TOOL_RENAMES = {"Task": "Agent"}
"""Old tool names Claude Code still accepts in rules, mapped to the tool they now name."""

_TRAILING_WILDCARDS = (" *", ":*")
"""The two spellings of a trailing wildcard that also match the bare command."""


@dataclass(frozen=True)
class PermissionRule:
    """One parsed permission rule.

    Attributes:
        tool: The tool name, with ``Task`` read as ``Agent``.
        specifier: The text between the parentheses, or None for a rule on the whole tool (``Tool`` or ``Tool(*)``).
        raw: The rule exactly as written.
    """

    tool: str
    specifier: str | None
    raw: str


def parse_rule(raw: str) -> PermissionRule | None:
    """Parse one permission rule written as ``Tool`` or ``Tool(specifier)``.

    The first ``(`` opens the specifier and the rule's final character must close it; parentheses
    inside the specifier are literal. ``Tool(*)`` is the whole tool, the same as ``Tool``, while an
    empty ``Tool()`` keeps its empty specifier.

    Args:
        raw: The rule as written in a settings list.

    Returns:
        The parsed rule, or None when Claude Code skips it as malformed: no tool name, text after
        the closing ``)``, a missing ``)``, or a ``)`` with no ``(``.
    """
    if "(" not in raw:
        if not raw or ")" in raw:
            return None
        return PermissionRule(_TOOL_RENAMES.get(raw, raw), None, raw)
    tool, _, rest = raw.partition("(")
    if not tool or not rest.endswith(")"):
        return None
    specifier: str | None = rest[:-1]
    if specifier == "*":
        specifier = None
    return PermissionRule(_TOOL_RENAMES.get(tool, tool), specifier, raw)


def _wildcard_regex(pattern: str) -> str:
    """Return a regex for ``pattern`` where each ``*`` matches any text and everything else is literal."""
    return ".*".join(re.escape(piece) for piece in pattern.split("*"))


def bash_covers(pattern: str, command: str) -> bool:
    """Return True when the Bash rule specifier ``pattern`` matches ``command``.

    A ``*`` matches any text, spaces included. A trailing `` *`` or ``:*`` also matches the bare
    command (``ls *`` matches ``ls``) when it is the pattern's only wildcard; a ``:*`` anywhere
    else is a literal colon followed by a wildcard. Anything else must match the whole command.

    Args:
        pattern: The specifier of a ``Bash(...)`` rule.
        command: The command text to test.

    Returns:
        True when the pattern matches the whole command.
    """
    expression = _wildcard_regex(pattern)
    if pattern.endswith(_TRAILING_WILDCARDS):
        base = pattern[:-2]
        tail = "(?: .*)?" if "*" not in base else " .*"
        expression = _wildcard_regex(base) + tail
    return re.fullmatch(expression, command, flags=re.DOTALL) is not None
