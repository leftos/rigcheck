"""Rule ``paths`` patterns: reading them, spotting ones Claude Code cannot use, and matching them against files."""

import os
from pathlib import Path

import bracex
from wcmatch import glob

PATTERN_BUDGET = 1000
"""How many patterns brace expansion may produce across one rule's whole ``paths`` list."""

BYTE_BUDGET = 4 * 1024 * 1024
"""How many UTF-8 bytes brace expansion may produce across one rule's whole ``paths`` list."""

_MATCH_FLAGS = glob.GLOBSTAR | glob.BRACE | glob.DOTGLOB | glob.FORCEUNIX | (glob.IGNORECASE if os.name == "nt" else 0)


def rule_patterns(value: object) -> list[str]:
    """Return the patterns of a rule's ``paths`` value.

    Args:
        value: The parsed ``paths`` value: a string, a list, or anything else.

    Returns:
        The string patterns, stripped, with blank ones dropped; empty for any other type.
    """
    if isinstance(value, str):
        items: list[object] = [value]
    elif isinstance(value, list):
        items = list(value)
    else:
        return []
    stripped = (item.strip() for item in items if isinstance(item, str))
    return [pattern for pattern in stripped if pattern]


def _bracket_end(pattern: str, start: int) -> int | None:
    """Return the index of the ``]`` closing the bracket expression opened at ``start``, or None."""
    index = start + 1
    if pattern[index : index + 1] in ("!", "^"):
        index += 1
    if pattern[index : index + 1] == "]":
        index += 1
    while index < len(pattern) and pattern[index] != "/":
        if pattern[index] == "\\":
            index += 2
            continue
        if pattern[index] == "]":
            return index
        index += 1
    return None


def bracket_error(pattern: str) -> bool:
    """Return True when the pattern has a ``[`` that does not start a bracket expression.

    A ``[`` starts one when it is not backslash-escaped and a ``]`` closes it later in the
    same path segment with at least one member between them; as in POSIX, a ``]`` right
    after ``[``, ``[!`` or ``[^`` is a member rather than the close.

    Args:
        pattern: One ``paths`` pattern.

    Returns:
        True when some unescaped ``[`` is never closed within its segment.
    """
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            end = _bracket_end(pattern, index)
            if end is None:
                return True
            index = end
        index += 1
    return False


def over_budget(patterns: list[str]) -> bool:
    """Return True when brace-expanding all the patterns together passes the budget.

    The budget, shared across the list, is 1,000 expanded patterns or 4 MiB of UTF-8.

    Args:
        patterns: Every pattern of one rule's ``paths`` list.

    Returns:
        True when the expansion produces more than 1,000 patterns or more than 4 MiB.
    """
    count = 0
    size = 0
    for pattern in patterns:
        remaining = PATTERN_BUDGET - count
        if remaining < 1:
            return True
        # bracex.iexpand(string, keep_escapes, limit) raises bracex.ExpansionLimitException once an expansion
        # would pass `limit` results (bracex/__init__.py, ExpandBrace.account), so a huge pattern never materialises.
        try:
            for expanded in bracex.iexpand(pattern, keep_escapes=True, limit=remaining):
                count += 1
                size += len(expanded.encode("utf-8"))
                if count > PATTERN_BUDGET or size > BYTE_BUDGET:
                    return True
        except bracex.ExpansionLimitException:
            return True
    return False


def matches_on_disk(pattern: str, root: Path) -> bool:
    """Return True when the pattern matches at least one path on disk under ``root``.

    This catches what git's file listing cannot show: ignored folders, submodule contents
    and untracked nested repositories. It uses the same flags as ``matches_any`` and stops
    at the first hit.

    Args:
        pattern: One ``paths`` pattern; a leading ``./`` is ignored.
        root: The folder the pattern is relative to.

    Returns:
        True when some path under ``root`` matches.
    """
    relative = pattern.removeprefix("./")
    # wcmatch.glob.iglob(patterns, *, flags, root_dir, ...) globs relative to root_dir and yields lazily
    # (wcmatch/glob.py, iglob and Glob.__init__), so next() stops at the first match.
    return next(glob.iglob(relative, flags=_MATCH_FLAGS, root_dir=os.fspath(root)), None) is not None


def matches_any(pattern: str, files: frozenset[str]) -> bool:
    """Return True when the pattern matches at least one of the files.

    Matching follows Claude Code's picomatch semantics as closely as wcmatch allows: ``**``
    crosses folders, braces expand, ``*`` and ``**`` match dotfiles, ``/`` is the only
    separator, and case folds on Windows only.

    Args:
        pattern: One ``paths`` pattern; a leading ``./`` is ignored.
        files: Repository-relative POSIX paths.

    Returns:
        True when some file matches.
    """
    return any(matches_path(pattern, name) for name in files)


def matches_path(pattern: str, name: str) -> bool:
    """Return True when the pattern matches one file.

    Matching follows Claude Code's picomatch semantics as closely as wcmatch allows: ``**``
    crosses folders, braces expand, ``*`` and ``**`` match dotfiles, ``/`` is the only
    separator, and case folds on Windows only. The pattern is a file glob: ``docs/**``
    matches the files under ``docs/``, while ``docs`` matches only a file named ``docs``.

    Args:
        pattern: One glob; a leading ``./`` is ignored.
        name: A repository-relative POSIX path.

    Returns:
        True when the file matches.
    """
    return glob.globmatch(name, pattern.removeprefix("./"), flags=_MATCH_FLAGS)
