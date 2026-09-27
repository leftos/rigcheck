"""YAML frontmatter between ``---`` fences at the top of a Markdown file."""

from dataclasses import dataclass
from typing import Any

import yaml

FENCE = "---"


@dataclass(frozen=True)
class Frontmatter:
    """The result of parsing a file's frontmatter.

    Attributes:
        present: True when the file's first line is exactly ``---``.
        data: The parsed mapping, or None when absent or invalid.
        error: Why the block could not be used, or None.
        body_line: 1-based line number where the body starts.
    """

    present: bool
    data: dict[Any, Any] | None
    error: str | None
    body_line: int


def parse(text: str) -> Frontmatter:
    """Parse the frontmatter block of ``text``; never raises.

    Args:
        text: The whole file content.

    Returns:
        The frontmatter, with ``error`` set when the block is unclosed, not YAML, or not a mapping.
    """
    lines = text.removeprefix("﻿").split("\n")
    lines = [line.removesuffix("\r") for line in lines]
    if lines[0] != FENCE:
        return Frontmatter(present=False, data=None, error=None, body_line=1)
    try:
        closing = lines.index(FENCE, 1)
    except ValueError:
        return Frontmatter(present=True, data=None, error="unclosed frontmatter", body_line=1)
    body_line = closing + 2
    block = "\n".join(lines[1:closing])
    try:
        data = yaml.safe_load(block)
    except Exception as exc:  # noqa: BLE001 - any parser failure on arbitrary text becomes a reported error, never a crash
        return Frontmatter(present=True, data=None, error=f"invalid YAML: {exc}", body_line=body_line)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return Frontmatter(present=True, data=None, error=f"frontmatter is a {type(data).__name__}, not a mapping", body_line=body_line)
    return Frontmatter(present=True, data=data, error=None, body_line=body_line)
