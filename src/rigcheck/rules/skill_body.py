"""Rules for the body of skill and command files: injected shell commands, ``$N`` in prose and unused arguments."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import frontmatter, shell
from rigcheck.parse.markdown import Injection, find_injections, prose_segments
from rigcheck.parse.permissions import PermissionRule, bash_covers, parse_rule
from rigcheck.rules import emit, rule
from rigcheck.rules.components import components, load, tool_entries
from rigcheck.rules.permissions import settings_allow_rules
from rigcheck.rules.references import exists, inside, resolved
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


_FILE_EXTENSION = re.compile(r"\.[A-Za-z0-9]+$")


def _in_skill(word: str, root: Path) -> bool:
    r"""True when ``word`` names an existing file or folder of the skill; words starting with ``/`` or ``\`` are never resolved."""
    if word.startswith(("/", "\\")) or ("/" not in word and _FILE_EXTENSION.search(word) is None):
        return False
    candidate = resolved(root, word)
    return inside(candidate, root) and exists(candidate)


def _cwd_relative(word: str, first: bool, root: Path | None) -> bool:
    """True when ``word`` is a path that resolves against the session's current directory."""
    if shell.cwd_relative(word, first):
        return True
    return root is not None and not shell.anchored(word) and _in_skill(word, root)


def _segment_word(segment: str, root: Path | None) -> str | None:
    """Return the first current-directory-relative path in one command; leading ``NAME=value`` words are assignments."""
    words = shell.words(segment)
    start = 0
    while start < len(words) and (assignment := shell.ASSIGNMENT.match(words[start])) is not None:
        value = words[start][assignment.end() :]
        if value.startswith(shell.CWD_RELATIVE):
            return value
        start += 1
    for index, word in enumerate(words[start:]):
        if _cwd_relative(word, index == 0, root):
            return word
    return None


def _relative_word(line: str, root: Path | None) -> str | None:
    """Return the first word of one command line that is a current-directory-relative path."""
    for segment in shell.segments(shell.uncommented(line)):
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


_UNREADABLE = ("$(", "`", "<<", ">|")
"""Text in a line that this lexical pass cannot read past: a substitution, a here-document or a clobber redirection."""

_ESCAPE = re.compile(r"\\[&|;\"']")
"""A backslash escaping a separator or quote, which moves where one command ends."""

_COMPOUND = frozenset({"!", "if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "select"})
"""Words that open or continue a compound command or negate a pipeline, whose subcommands this pass cannot read."""

_WRAPPERS = frozenset({"timeout", "time", "nice", "nohup", "stdbuf", "command", "builtin", "noglob", "xargs"})
"""Commands that run the command named after them, so the wrapper's own text is not the command that runs."""

_VARIABLE = re.compile(r"\$[A-Za-z0-9_{]")
"""A shell variable or Claude Code placeholder, whose value the text does not resolve."""


def _redirection(piece: str, index: int) -> bool:
    """True when the ``&`` at ``index`` belongs to a ``>&``, ``<&`` or ``&>`` redirection rather than backgrounding the command."""
    if index and piece[index - 1] in "<>":
        return True
    return index + 1 < len(piece) and piece[index + 1] == ">"


def _background(piece: str) -> list[str]:
    """Split one shell piece on a background ``&`` outside quotes; a redirection's ``&`` is part of the piece."""
    parts: list[str] = []
    current = ""
    quote = ""
    for index, char in enumerate(piece):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "&" and not _redirection(piece, index):
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return parts


def _subcommands(line: str) -> list[str]:
    """Split one command line into the subcommands a shell would run, each stripped, empty pieces dropped."""
    found: list[str] = []
    for piece in shell.segments(shell.uncommented(line)):
        for part in _background(piece):
            command = part.strip()
            if command:
                found.append(command)
    return found


def _group(command: str) -> bool:
    """True when a subcommand is a shell group or a compound-command keyword, which this pass cannot read."""
    if command.startswith(("(", "{")):
        return True
    words = shell.words(command)
    return bool(words) and words[0] in _COMPOUND


def _line_unreadable(line: str) -> bool:
    """True when one line holds syntax whose subcommands this lexical pass cannot read."""
    if any(marker in line for marker in _UNREADABLE) or _ESCAPE.search(line) is not None:
        return True
    if line.rstrip().endswith(("\\", "&&", "||")):
        return True
    return any(_group(command) for command in _subcommands(line))


def _readable(lines: list[str]) -> bool:
    """True when every line of an injected command can be split into subcommands."""
    return not any(_line_unreadable(line) for line in lines)


def _skipped(command: str) -> bool:
    """True when a subcommand is not checked as written: an assignment word, a wrapper, or a variable the text leaves unexpanded."""
    if _VARIABLE.search(command) is not None:
        return True
    words = shell.words(command)
    return bool(words) and (shell.ASSIGNMENT.match(words[0]) is not None or words[0] in _WRAPPERS)


def _covered(entries: list[PermissionRule], command: str) -> bool:
    """True when one of the component's ``Bash`` rules covers ``command``."""
    return any(found.specifier is None or bash_covers(found.specifier, command) for found in entries)


def _uncovered_line(line: str, entries: list[PermissionRule]) -> str | None:
    """Return the program of the first subcommand of one line that no ``Bash`` rule covers."""
    for command in _subcommands(line):
        if _skipped(command) or _covered(entries, command):
            continue
        words = shell.words(command)
        return words[0] if words else command
    return None


def _uncovered(injection: Injection, entries: list[PermissionRule]) -> tuple[int, str] | None:
    """Return the line and program of the first subcommand of an injection that no ``Bash`` rule covers."""
    lines = injection.command.split("\n")
    if not _readable(lines):
        return None
    for index, line in enumerate(lines):
        program = _uncovered_line(line, entries)
        if program is not None:
            return injection.line + index, program
    return None


def _bash_rules(rules: list[PermissionRule]) -> list[PermissionRule]:
    """Return the ``Bash`` rules of a parsed rule list."""
    return [found for found in rules if found.tool == "Bash"]


def _bash_entries(parsed: frontmatter.Frontmatter, settings: list[PermissionRule]) -> list[PermissionRule] | None:
    """Return the ``Bash`` allow rules covering a skill or command, or None when this rule does not apply to it.

    None when the frontmatter has no data, sets no ``allowed-tools``, or names a ``shell`` other than ``bash``
    (a blank ``shell`` counts as bash); otherwise the component's own ``Bash`` rules plus ``settings``, the
    repo and user settings allow rules, empty when neither names a ``Bash`` tool at all.
    """
    data = parsed.data
    if data is None or "allowed-tools" not in data:
        return None
    if "shell" in data and data["shell"] not in (None, "", "bash"):
        return None
    own = (parse_rule(entry) for entry in tool_entries(data["allowed-tools"]))
    return settings + _bash_rules([found for found in own if found is not None])


@rule(
    "skill-injection-not-allowed",
    "core",
    Severity.WARN,
    "Add a Bash(<command> *) entry to allowed-tools for each injected command, or Claude Code aborts the invocation outside auto mode.",
    ("official:SK22",),
)
def skill_injection_not_allowed(rig: Rig) -> Iterator[Finding]:
    """An injected command that no Bash entry of the component's ``allowed-tools`` or of a settings allow rule covers.

    Claude Code aborts the invocation outside auto mode, so add the entry that covers the command.
    """
    settings = _bash_rules(settings_allow_rules(rig))
    for artifact in components(rig, LISTED_KINDS):
        entries = _bash_entries(load(rig, artifact), settings)
        if entries is None:
            continue
        for injection in _injections(rig, artifact):
            found = None if injection.literal else _uncovered(injection, entries)
            if found is not None:
                line, program = found
                message = (
                    f"injected command `{program}` is not covered by allowed-tools or a settings allow rule, "
                    "so Claude Code aborts the invocation outside auto mode"
                )
                yield emit("skill-injection-not-allowed", artifact, message, line)
