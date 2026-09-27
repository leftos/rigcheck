"""Offline token estimates."""

import math

INSTRUCTION_CHARS_PER_TOKEN = 2.5
"""Characters per token for file bodies loaded into context (instruction files, memory index).

Calibrated against Claude Code's ``/context``; the measurement is recorded in ``docs/plans/v1.md`` (Verification).
Counts built on it are approximate and are displayed with ``≈``.
"""

DESCRIPTION_CHARS_PER_TOKEN = 3.0
"""Characters per token for skill, command and agent listing text (name, description, when to use).

Calibrated against Claude Code's ``/context``; the measurement is recorded in ``docs/plans/v1.md`` (Verification).
Counts built on it are approximate and are displayed with ``≈``.
"""


def estimate(text: str, chars_per_token: float) -> int:
    """Estimate the token count of ``text``.

    Args:
        text: The content as it would enter the context.
        chars_per_token: The rate for this kind of text: ``INSTRUCTION_CHARS_PER_TOKEN`` or ``DESCRIPTION_CHARS_PER_TOKEN``.

    Returns:
        ``ceil(len(text) / chars_per_token)``.
    """
    return math.ceil(len(text) / chars_per_token)
