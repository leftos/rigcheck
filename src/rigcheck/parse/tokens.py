"""Offline token estimates."""

import math

CHARS_PER_TOKEN = 3.8
"""Characters per token: an offline estimate, to be calibrated against Claude Code's ``/context``.

Counts built on it are approximate and are displayed with ``≈``.
"""


def estimate(text: str) -> int:
    """Estimate the token count of ``text``.

    Args:
        text: The content as it would enter the context.

    Returns:
        ``ceil(len(text) / CHARS_PER_TOKEN)``.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)
