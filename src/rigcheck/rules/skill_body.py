"""Rules for the body of skill and command files: injected shell commands, ``$N`` in prose and unused arguments."""

import re
import shlex
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse.markdown import Injection, find_injections, prose_segments
from rigcheck.rules import emit, rule
from rigcheck.rules.components import components, load
from rigcheck.rules.references import exists, inside, resolved, segments
from rigcheck.rules.skills import LISTED_KINDS


def _injections(rig: Rig, artifact: Artifact) -> list[Injection]:
    """Return the shell commands the body of ``artifact`` injects, frontmatter excluded."""
    return find_injections(rig.text(artifact.path), load(rig, artifact).body_line)


@rule(
    "skill-injection-literal",
    "core",
    Severity.WARN,
    "Put a space before the !, or start the line with it, so Claude Code runs the command.",
    ("official:SK22",),
)
def skill_injection_literal(rig: Rig) -> Iterator[Finding]:
    """An injected command whose ``!`` follows another character, so Claude Code leaves it as text and never runs it."""
    for artifact in components(rig, LISTED_KINDS):
        for injection in _injections(rig, artifact):
            if injection.literal:
                command = injection.command
                message = f"`!` right after `{injection.after}` is not recognized, so `{command}` does not run; put a space or line start before `!`"
                yield emit("skill-injection-literal", artifact, message, injection.line)


_ANCHORED = ("$", "~", "/", "%", "\\\\")
"""Word prefixes that make a path resolve the same way from any working directory.

Any variable or command substitution (``$VAR``, ``${VAR}``, ``$(...)``), the home folder, the root, a
Windows ``%VAR%`` and a UNC path.
"""

_DRIVE = re.compile(r"^[A-Za-z]:")
_CWD_RELATIVE = ("./", "../", ".\\", "..\\")
_FILE_EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
"""An environment assignment before a command, such as ``FOO=1``."""


def _words(segment: str) -> list[str]:
    """Split one shell command into words, quotes removed and backslashes kept; on unbalanced quotes, split on whitespace."""
    lexer = shlex.shlex(segment, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        return [word.strip("\"'") for word in segment.split()]


def _anchored(word: str) -> bool:
    return word.startswith(_ANCHORED) or _DRIVE.match(word) is not None or "://" in word


def _in_skill(word: str, root: Path) -> bool:
    r"""True when ``word`` names an existing file or folder of the skill; words starting with ``/`` or ``\`` are never resolved."""
    if word.startswith(("/", "\\")) or ("/" not in word and _FILE_EXTENSION.search(word) is None):
        return False
    candidate = resolved(root, word)
    return inside(candidate, root) and exists(candidate)


def _cwd_relative(word: str, first: bool, root: Path | None) -> bool:
    """True when ``word`` is a path that resolves against the session's current directory."""
    if _anchored(word):
        return False
    if word.startswith(_CWD_RELATIVE) or (first and ("/" in word or "\\" in word)):
        return True
    return root is not None and _in_skill(word, root)


def _segment_word(segment: str, root: Path | None) -> str | None:
    """Return the first current-directory-relative path in one command; leading ``NAME=value`` words are assignments."""
    words = _words(segment)
    start = 0
    while start < len(words) and (assignment := _ASSIGNMENT.match(words[start])) is not None:
        value = words[start][assignment.end() :]
        if value.startswith(_CWD_RELATIVE):
            return value
        start += 1
    for index, word in enumerate(words[start:]):
        if _cwd_relative(word, index == 0, root):
            return word
    return None


def _uncommented(line: str) -> str:
    """Cut ``line`` at the first ``#`` outside quotes that starts a word, where a shell comment begins."""
    quote = ""
    for index, char in enumerate(line):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _relative_word(line: str, root: Path | None) -> str | None:
    """Return the first word of one command line that is a current-directory-relative path."""
    for segment in segments(_uncommented(line)):
        word = _segment_word(segment, root)
        if word is not None:
            return word
    return None


def _relative_path(injection: Injection, root: Path | None) -> tuple[int, str] | None:
    """Return the line and word of the first current-directory-relative path in an injected command."""
    for index, line in enumerate(injection.command.split("\n")):
        word = _relative_word(line, root)
        if word is not None:
            return injection.line + index, word
    return None


@rule(
    "skill-injection-relative-path",
    "core",
    Severity.WARN,
    "Start the path with ${CLAUDE_SKILL_DIR} or ${CLAUDE_PROJECT_DIR}, so it resolves the same way wherever the session has moved.",
    ("official:SK23",),
)
def skill_injection_relative_path(rig: Rig) -> Iterator[Finding]:
    """An injected command that names a path relative to the session's current directory."""
    for artifact in components(rig, LISTED_KINDS):
        root = artifact.path.parent if artifact.kind is Kind.SKILL else None
        for injection in _injections(rig, artifact):
            found = None if injection.literal else _relative_path(injection, root)
            if found is not None:
                line, word = found
                message = f"`{word}` in an injected command resolves against the session's current directory, which moves when Claude runs cd"
                yield emit("skill-injection-relative-path", artifact, message, line)


_DOLLAR_DIGIT = re.compile(r"(\\*)(\$\d+)")
"""A ``$`` followed by digits, with the backslashes before it."""


def _unescaped(backslashes: str) -> bool:
    """A single backslash escapes the ``$`` after it; none, or two or more, leave it to expand."""
    return len(backslashes) != 1


@rule(
    "skill-dollar-digit",
    "core",
    Severity.WARN,
    "Escape the dollar sign with a backslash, as \\$1.00, or put the text in a code span.",
    ("official:SK24",),
)
def skill_dollar_digit(rig: Rig) -> Iterator[Finding]:
    """A ``$`` before a digit in prose, which Claude Code replaces with an argument."""
    for artifact in components(rig, LISTED_KINDS):
        for line, text in prose_segments(rig.text(artifact.path), load(rig, artifact).body_line):
            for match in _DOLLAR_DIGIT.finditer(text):
                if _unescaped(match.group(1)):
                    token = match.group(2)
                    message = f"`{token}` in prose is replaced by an argument when the skill is invoked; write `\\{token}`"
                    yield emit("skill-dollar-digit", artifact, message, line)


def _declared(value: Any) -> list[str]:
    """Return the argument names ``arguments`` declares, from a space-separated string or a list of strings."""
    if isinstance(value, str):
        names = value.split()
    elif isinstance(value, list):
        names = [item.strip() for item in value if isinstance(item, str)]
    else:
        return []
    return list(dict.fromkeys(name for name in names if name))


def _used(name: str, body: str) -> bool:
    """True when ``$name`` appears in ``body`` as a whole name, not escaped by a single backslash."""
    pattern = re.compile(rf"(\\*)\${re.escape(name)}(?![\w-])")
    return any(_unescaped(match.group(1)) for match in pattern.finditer(body))


@rule(
    "skill-argument-unused",
    "core",
    Severity.WARN,
    "Use $name in the body where the value belongs, or remove the name from arguments.",
    ("official:SK24",),
)
def skill_argument_unused(rig: Rig) -> Iterator[Finding]:
    """An argument name declared in ``arguments`` that the body never uses as ``$name``."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        body = "\n".join(rig.text(artifact.path).split("\n")[parsed.body_line - 1 :])
        for name in _declared(parsed.data.get("arguments")):
            if not _used(name, body):
                message = f'arguments declares "{name}", but the body never uses ${name}'
                yield emit("skill-argument-unused", artifact, message, parsed.key_lines.get("arguments", 1))
