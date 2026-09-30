"""Rules for credentials written into the rig's files, and for skills that pipe downloaded code into a shell."""

import re
from collections.abc import Iterator

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import shell
from rigcheck.parse.markdown import find_injections, find_references, prose_segments
from rigcheck.parse.secrets import find_secrets
from rigcheck.rules import emit, rule
from rigcheck.rules.components import components, load
from rigcheck.rules.skills import LISTED_KINDS

SECRET_KINDS = (
    Kind.INSTRUCTIONS,
    Kind.NESTED_INSTRUCTIONS,
    Kind.RULE,
    Kind.MEMORY_INDEX,
    Kind.MEMORY_TOPIC,
    Kind.SKILL,
    Kind.COMMAND,
    Kind.AGENT,
)
"""The Markdown kinds searched for credential literals, whether they load or not."""


@rule(
    "secret-literal",
    "core",
    Severity.ERROR,
    "Remove the literal, reference an environment variable instead, and rotate the exposed credential.",
    ("sota:#19 (B)",),
)
def secret_literal(rig: Rig) -> Iterator[Finding]:
    """A provider credential (API key, access token, private key or JWT) written as a literal in an instruction, memory, skill or agent file."""
    for artifact in components(rig, SECRET_KINDS):
        for hit in find_secrets(rig.text(artifact.path)):
            message = f"{hit.kind} literal ({hit.length} characters) on this line; the value is not shown"
            yield emit("secret-literal", artifact, message, hit.line)


_FETCHERS = frozenset({"curl", "wget", "iwr", "irm", "invoke-webrequest", "invoke-restmethod"})
_RUNNERS = frozenset({"sh", "bash", "zsh", "dash", "iex", "invoke-expression", "python", "python3", "node", "pwsh", "powershell", "ruby", "perl"})
_POSIX_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
_SUBSTITUTING_SHELLS = frozenset({"sh", "bash", "zsh"})
_EVALUATORS = frozenset({"iex", "invoke-expression"})
_SUDO_VALUED = frozenset({"-u", "-g", "-C", "-h", "-p", "-r", "-t", "-U", "-D"})
"""The ``sudo`` flags that take the next word as their value."""
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
"""A Markdown table row, whose ``|`` separates cells rather than commands."""
_SHELL_INLINE = re.compile(r"^-[A-Za-z]*c$")
"""A POSIX shell's inline-command flag, alone or ending a short-flag group such as ``-lc``."""
_FETCH_SUBSTITUTION = re.compile(r"(?:\$\(|`)\s*(curl|wget)(?![\w-])", re.IGNORECASE)
_EVALUATED_FETCH = re.compile(r"(?<![\w-])(iex|invoke-expression)\s*\(\s*(irm|iwr|invoke-webrequest|invoke-restmethod)(?![\w-])", re.IGNORECASE)


def _command(segment: str) -> list[str]:
    """Return one command's words from its command word on, skipping a leading ``sudo``, its flags and their values."""
    parts = shell.command_words(segment)
    if not parts or shell.program_name(parts[0]) != "sudo":
        return parts
    index = 1
    while index < len(parts) and parts[index].startswith("-"):
        index += 2 if parts[index] in _SUDO_VALUED else 1
    return parts[index:]


def _runs_stdin(parts: list[str]) -> bool:
    """True when an interpreter command runs the script it reads from standard input.

    ``iex`` always does. Any other interpreter does unless it has its own inline-code or module flag (see
    :func:`shell.runs_inline`); then a POSIX shell with ``-s`` does even when words follow, and otherwise an
    interpreter does when it names no script operand.
    """
    if shell.program_name(parts[0]) in _EVALUATORS:
        return True
    if shell.runs_inline(parts):
        return False
    return (shell.program_name(parts[0]) in _POSIX_SHELLS and "-s" in parts[1:]) or shell.script_of(parts) is None


def _piped(line: str) -> tuple[str, str] | None:
    """Return the fetch and interpreter words when a fetch's output reaches an interpreter through ``|`` alone."""
    fetch = None
    for separator, segment in shell.pipeline(line):
        if separator != "|":
            fetch = None
        parts = _command(segment)
        if not parts:
            continue
        program = shell.program_name(parts[0])
        if fetch is not None and program in _RUNNERS and _runs_stdin(parts):
            return fetch, parts[0]
        if program in _FETCHERS:
            fetch = parts[0]
    return None


def _substituted(segment: str) -> tuple[str, str] | None:
    """Return the fetch and shell words when ``sh -c``, ``bash -c`` or ``zsh -c`` runs a ``$(curl ...)`` or backtick fetch."""
    parts = _command(segment)
    if not parts or shell.program_name(parts[0]) not in _SUBSTITUTING_SHELLS:
        return None
    for index, word in enumerate(parts[1:], start=1):
        if _SHELL_INLINE.match(word):
            match = _FETCH_SUBSTITUTION.search(" ".join(parts[index + 1 :]))
            return (match.group(1), parts[0]) if match is not None else None
    return None


def _remote_exec(line: str) -> tuple[str, str] | None:
    """Return the fetch and interpreter words when one line runs downloaded code, or None."""
    found = _piped(line)
    if found is None:
        found = next((hit for segment in shell.segments(line) if (hit := _substituted(segment)) is not None), None)
    if found is None and (evaluated := _EVALUATED_FETCH.search(line)) is not None:
        found = evaluated.group(2), evaluated.group(1)
    return found


def _code_lines(text: str, body_line: int) -> Iterator[tuple[int, str]]:
    """Yield the body's injected command lines, code block lines and code spans, comments cut from the command lines."""
    for injection in find_injections(text, body_line):
        for index, line in enumerate(injection.command.split("\n")):
            yield injection.line + index, shell.uncommented(line)
    for reference in find_references(text):
        if reference.line >= body_line and reference.source == "fence":
            yield reference.line, shell.uncommented(reference.raw)
        elif reference.line >= body_line and reference.source == "span":
            yield reference.line, reference.raw


def _candidate_lines(rig: Rig, artifact: Artifact) -> Iterator[tuple[int, str]]:
    """Yield each body line that may hold a command: code (see :func:`_code_lines`), then prose lines other than table rows."""
    text = rig.text(artifact.path)
    body_line = load(rig, artifact).body_line
    yield from _code_lines(text, body_line)
    for line, prose in prose_segments(text, body_line):
        if _TABLE_ROW.match(prose) is None:
            yield line, prose


@rule(
    "skill-remote-exec",
    "core",
    Severity.WARN,
    "Pin and vendor the script, or download it, verify a checksum, then run it.",
    ("official:SK28",),
)
def skill_remote_exec(rig: Rig) -> Iterator[Finding]:
    """A skill or command that pipes a downloaded script into a shell or interpreter, running remote code unchecked."""
    for artifact in components(rig, LISTED_KINDS):
        reported: set[int] = set()
        for line, text in _candidate_lines(rig, artifact):
            found = None if line in reported else _remote_exec(text)
            if found is not None:
                reported.add(line)
                message = f"{found[0]} output is piped into {found[1]}, running remote code unchecked"
                yield emit("skill-remote-exec", artifact, message, line)
