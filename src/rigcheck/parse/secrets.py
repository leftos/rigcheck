"""Finding provider credentials written as literals in text, without keeping any part of the value.

A hit records the line, the kind of credential and its length only, so a finding built from it can
never echo the secret. Documented placeholders (``AKIAIOSFODNN7EXAMPLE``, ``sk-ant-xxxxxxxx...``,
``ghp_your_token_here``) are not hits, and variable references such as ``${ANTHROPIC_API_KEY}`` never
match a token format.
"""

import re
from dataclasses import dataclass

_BEFORE = r"(?<![A-Za-z0-9_-])"
_AFTER = r"(?![A-Za-z0-9_-])"
_KEY_BODY = r"(?=[^\n]*\n(?:[^\n]*\n)?[ \t]*[A-Za-z0-9+/=]{40,}[ \t]*\r?(?:\n|$))"
"""A key body after a private key header: a line of 40 or more base64 characters within the next two lines."""


def _token(prefix: str, body: str) -> re.Pattern[str]:
    """Compile a token format: ``prefix`` then ``body``, with no token character on either side."""
    return re.compile(rf"{_BEFORE}(?P<prefix>{prefix})(?P<body>{body}){_AFTER}")


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic API key", _token("sk-ant-", r"[A-Za-z0-9_-]{20,}")),
    ("OpenAI API key", _token(r"sk-(?!ant-)(?:proj-)?", r"[A-Za-z0-9_-]{32,}")),
    ("GitHub token", _token("gh[pousr]_", r"[A-Za-z0-9]{36,}")),
    ("GitHub token", _token("github_pat_", r"[A-Za-z0-9_]{50,}")),
    ("Slack token", _token("xox[baprs]-", r"[A-Za-z0-9-]{10,}")),
    ("AWS access key", _token("AKIA", r"[0-9A-Z]{16}")),
    ("Google API key", _token("AIza", r"[0-9A-Za-z_-]{35}")),
    ("private key", re.compile(rf"(?P<prefix>-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----)(?P<body>){_KEY_BODY}")),
    ("JWT", _token("eyJ", r"[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)
"""Each credential kind and its format; the ``body`` group is the part after the fixed prefix."""

_FILLER = re.compile(r"x{6,}|X{6,}")
_PLACEHOLDER_WORDS = re.compile(r"your|example|changeme|placeholder|dummy|fake|redacted", re.IGNORECASE)
_ELLIPSES = ("...", "…")


@dataclass(frozen=True)
class SecretHit:
    """A credential literal found in text; it holds no part of the value.

    Attributes:
        line: 1-based line the literal starts on.
        kind: The credential kind, such as ``GitHub token``.
        length: The literal's length in characters.
    """

    line: int
    kind: str
    length: int


def _placeholder(match: re.Match[str]) -> bool:
    """True when the matched literal is a documented example or filler rather than a real credential."""
    body = match.group("body")
    if match.group(0).endswith("EXAMPLE") or body.startswith(_ELLIPSES):
        return True
    if len(set(body)) == 1:
        return True
    return _FILLER.search(body) is not None or _PLACEHOLDER_WORDS.search(body) is not None


def find_secrets(text: str) -> list[SecretHit]:
    """Find the provider credential literals in ``text``, placeholders skipped.

    Args:
        text: The text to scan, possibly several lines.

    Returns:
        One hit per literal, in the order they appear.
    """
    found: list[tuple[int, SecretHit]] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if not _placeholder(match):
                line = text.count("\n", 0, match.start()) + 1
                found.append((match.start(), SecretHit(line=line, kind=kind, length=len(match.group(0)))))
    return [hit for _, hit in sorted(found, key=lambda pair: pair[0])]


def classify(value: str) -> str | None:
    """Return the kind of the first credential literal in a single string value, such as one JSON string.

    Args:
        value: The string to check.

    Returns:
        The credential kind, or None when the value holds no credential literal other than a placeholder.
    """
    hits = find_secrets(value)
    return hits[0].kind if hits else None
