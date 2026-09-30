"""Reading shell command text: segments, words, comments, and the command and script one segment runs.

These helpers are lexical. They split and classify text the way a POSIX shell mostly would, without
running or expanding anything, and fall back to whitespace splitting where the quoting does not balance.
"""

import re
import shlex
from dataclasses import dataclass

_SHELL_PARTS = re.compile(r"""'[^']*'|"[^"]*"|&&|\|\||[;|]|[^'"&|;]+|.""")
_SEPARATORS = ("&&", "||", ";", "|")

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
"""An environment assignment before a command, such as ``FOO=1``."""

CWD_RELATIVE = ("./", "../", ".\\", "..\\")
"""Word prefixes that name a path from the current directory."""

_ANCHORED = ("$", "~", "/", "%", "\\\\")
"""Word prefixes that make a path resolve the same way from any working directory.

Any variable or command substitution (``$VAR``, ``${VAR}``, ``$(...)``), the home folder, the root, a
Windows ``%VAR%`` and a UNC path.
"""

_DRIVE = re.compile(r"^[A-Za-z]:")

_INTERPRETERS = frozenset({"bash", "sh", "zsh", "dash", "python", "python3", "py", "node", "deno", "bun", "ruby", "perl", "pwsh", "powershell"})
"""Programs that run the script named after them, so the script itself needs no executable bit."""

_SHELL_GROUP = re.compile(r"^-[A-Za-z]*c$")
"""A short-flag group ending in ``c``, such as ``-lc`` or ``-euc``: a POSIX shell's inline-command flag."""


@dataclass(frozen=True)
class _Flags:
    """How one interpreter's flags read.

    Attributes:
        inline: Flags after which no script file follows: inline code, or a module to run.
        valued: Flags that take the next word as their value; ``--flag=value`` is one word and needs no entry.
        grouped: Whether a short-flag group ending in ``c`` is the inline-command flag, as in POSIX shells.
    """

    inline: frozenset[str] = frozenset()
    valued: frozenset[str] = frozenset()
    grouped: bool = False

    def ends_search(self, word: str) -> bool:
        """True when ``word`` means the command runs no script file."""
        return word in self.inline or (self.grouped and _SHELL_GROUP.match(word) is not None)


_SHELL_FLAGS = _Flags(frozenset({"-c"}), grouped=True)
_PYTHON_FLAGS = _Flags(frozenset({"-c", "-m"}), frozenset({"-W", "-X"}))
_JS_FLAGS = _Flags(
    frozenset({"-e", "--eval", "-p", "--print"}),
    frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader", "--env-file", "-C", "--conditions"}),
)
_INTERPRETER_FLAGS: dict[str, _Flags] = {
    **dict.fromkeys(("bash", "sh", "zsh", "dash"), _SHELL_FLAGS),
    **dict.fromkeys(("python", "python3", "py"), _PYTHON_FLAGS),
    **dict.fromkeys(("node", "deno", "bun"), _JS_FLAGS),
    "ruby": _Flags(frozenset({"-e"}), frozenset({"-r", "-I"})),
    "perl": _Flags(frozenset({"-e", "-E"}), frozenset({"-M", "-I"})),
}
"""Per interpreter other than PowerShell, how its flags read."""

_POWERSHELL = frozenset({"pwsh", "powershell"})
_POWERSHELL_FILE = frozenset({"-file", "-f"})
_POWERSHELL_FLAGS = _Flags(frozenset({"-command", "-c", "-encodedcommand", "-ec", "-e"}))
"""PowerShell's flags, compared lower-cased."""
_NO_FLAGS = _Flags()

_SUBCOMMAND_RUNNERS = frozenset({"deno", "bun"})
"""Interpreters that take a ``run`` subcommand before the script."""

_PLACEHOLDER_AT = re.compile(r"\$\{(?:CLAUDE_PROJECT_DIR|CLAUDE_PLUGIN_ROOT)\}|\$(?:CLAUDE_PROJECT_DIR|CLAUDE_PLUGIN_ROOT)(?![A-Za-z0-9_])")
_ASSIGNMENT_AT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
_WORD_BREAKS = frozenset(" \t\r\n;&|()")


def segments(raw: str) -> list[str]:
    """Split shell text on ``&&``, ``||``, ``;`` and ``|`` outside single and double quotes.

    Args:
        raw: One line of shell text.

    Returns:
        The text between separators, in order; empty strings where separators meet.
    """
    found = [""]
    for part in _SHELL_PARTS.findall(raw):
        if part in _SEPARATORS:
            found.append("")
        else:
            found[-1] += part
    return found


def pipeline(raw: str) -> list[tuple[str, str]]:
    """Split shell text like :func:`segments`, keeping the separator written before each segment.

    Args:
        raw: One line of shell text.

    Returns:
        ``(separator, segment)`` pairs in order: the separator is ``&&``, ``||``, ``;`` or ``|``, and empty for the first.
    """
    found = [("", "")]
    for part in _SHELL_PARTS.findall(raw):
        if part in _SEPARATORS:
            found.append((part, ""))
        else:
            separator, text = found[-1]
            found[-1] = (separator, text + part)
    return found


def words(segment: str) -> list[str]:
    """Split one shell command into words, quotes removed and backslashes kept; on unbalanced quotes, split on whitespace.

    Args:
        segment: One command, as :func:`segments` returns it.

    Returns:
        The words, in order.
    """
    lexer = shlex.shlex(segment, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:
        return [word.strip("\"'") for word in segment.split()]


def uncommented(line: str) -> str:
    """Cut ``line`` at the first ``#`` outside quotes that starts a word, where a shell comment begins.

    Args:
        line: One line of shell text.

    Returns:
        The line up to the comment, or the whole line when it holds none.
    """
    quote = ""
    for index, char in enumerate(line):
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def anchored(word: str) -> bool:
    r"""Return True when ``word`` resolves the same way from any working directory.

    Args:
        word: One shell word.

    Returns:
        True for a word starting with ``$``, ``~``, ``/``, ``%`` or ``\\``, a drive letter, or holding a URL scheme.
    """
    return word.startswith(_ANCHORED) or _DRIVE.match(word) is not None or "://" in word


def cwd_relative(word: str, first: bool) -> bool:
    r"""Return True when ``word`` is a path that resolves against the session's current directory.

    Args:
        word: One shell word.
        first: Whether the word is in command position, where a ``/`` or ``\`` makes it a path.

    Returns:
        True for an unanchored word starting ``./`` or ``../``, or a command-position word holding a separator.
    """
    if anchored(word):
        return False
    return word.startswith(CWD_RELATIVE) or (first and ("/" in word or "\\" in word))


def command_words(segment: str) -> list[str]:
    """Return the words of one command from its command word on, leading ``NAME=value`` assignments dropped.

    Args:
        segment: One command, as :func:`segments` returns it.

    Returns:
        The command word and its arguments; empty when the segment holds only assignments or nothing.
    """
    parts = words(segment)
    start = 0
    while start < len(parts) and ASSIGNMENT.match(parts[start]) is not None:
        start += 1
    return parts[start:]


def command_word(segment: str) -> str | None:
    """Return the first word of one command after its ``NAME=value`` assignments.

    Args:
        segment: One command, as :func:`segments` returns it.

    Returns:
        The command word, or None when the segment has none.
    """
    parts = command_words(segment)
    return parts[0] if parts else None


def program_name(word: str) -> str:
    r"""Return the program a command word runs: its last path segment, lower-cased, with ``.exe`` stripped.

    Args:
        word: A command word, such as ``/usr/bin/python3`` or ``C:\Tools\pwsh.exe``.

    Returns:
        The bare program name, such as ``python3`` or ``pwsh``.
    """
    return re.split(r"[\\/]", word)[-1].lower().removesuffix(".exe")


def _operand(parts: list[str], start: int, flags: _Flags) -> int | None:
    """Return the index of the first word from ``start`` that is neither a flag nor a flag's value.

    None when the words run out, or a flag that means no script file follows (inline code, a module) comes first.
    """
    index = start
    while index < len(parts):
        word = parts[index]
        if flags.ends_search(word):
            return None
        if not word.startswith("-"):
            return index
        index += 2 if word in flags.valued else 1
    return None


def _powershell_script(parts: list[str]) -> str | None:
    """Return the script a PowerShell command line runs: the word after ``-File``, else its first operand; flags ignore case."""
    lowered = [word.lower() for word in parts]
    for index, word in enumerate(lowered[1:-1], start=1):
        if word in _POWERSHELL_FILE:
            return parts[index + 1]
    index = _operand(lowered, 1, _POWERSHELL_FLAGS)
    return parts[index] if index is not None else None


def _interpreted(parts: list[str]) -> str | None:
    """Return the script an interpreter command line runs, or None when it names none."""
    program = program_name(parts[0])
    if program in _POWERSHELL:
        return _powershell_script(parts)
    flags = _INTERPRETER_FLAGS[program]
    index = _operand(parts, 1, flags)
    if index is not None and program in _SUBCOMMAND_RUNNERS and parts[index] == "run":
        index = _operand(parts, index + 1, flags)
    return parts[index] if index is not None else None


def runs_inline(parts: list[str]) -> bool:
    """Return True when an interpreter command line holds that interpreter's inline-code or module flag.

    The flags are the interpreter's own: ``-c`` or a short-flag group ending in ``c`` for POSIX shells, ``-c`` and
    ``-m`` for Python, ``-e``, ``--eval``, ``-p`` and ``--print`` for Node, ``-e`` for Ruby, ``-e`` and ``-E`` for Perl,
    and ``-Command``, ``-c``, ``-EncodedCommand`` and the like for PowerShell, whose flags ignore case. Other flags,
    such as ``bash -e`` or ``python -E``, are not inline code.

    Args:
        parts: The command's words from its command word on.

    Returns:
        True when any word is such a flag; False for a program with no known flags.
    """
    program = program_name(parts[0])
    if program in _POWERSHELL:
        return any(_POWERSHELL_FLAGS.ends_search(word.lower()) for word in parts[1:])
    flags = _INTERPRETER_FLAGS.get(program, _NO_FLAGS)
    return any(flags.ends_search(word) for word in parts[1:])


def _uv_rest(parts: list[str]) -> list[str] | None:
    """Return the command ``uv run`` or ``uvx`` runs, from its first non-flag word, or None when the line is neither."""
    program = program_name(parts[0])
    if program == "uvx":
        start = 1
    elif program == "uv" and len(parts) > 1 and parts[1] == "run":
        start = 2
    else:
        return None
    index = _operand(parts, start, _NO_FLAGS)
    return parts[index:] if index is not None else []


def script_of(parts: list[str]) -> tuple[str, bool] | None:
    """Return the script a command's words run, and whether it runs directly rather than through an interpreter.

    The command word comes after leading ``NAME=value`` assignments. When its program (see :func:`program_name`) is
    an interpreter such as ``bash``, ``python`` or ``node``, the script is the next word that is neither a flag nor
    the value of a flag that takes one (``node -r``, ``python -W``, ``ruby -I`` and the like); ``deno`` and ``bun``
    skip a ``run`` subcommand; ``pwsh`` and ``powershell`` take the word after ``-File`` or ``-f``. An inline-code
    flag (``-c``, a shell's ``-lc`` group, ``-e``, ``-Command`` and the like) or ``python -m`` before that word
    means there is no script.
    ``uv run`` and ``uvx`` skip to their first non-flag word, which is read again as a command. Any other command
    word is the script itself, run directly.

    Args:
        parts: The command's words, as :func:`words` returns them.

    Returns:
        ``(word, direct)``, or None when the words name no script.
    """
    start = 0
    while start < len(parts) and ASSIGNMENT.match(parts[start]) is not None:
        start += 1
    parts = parts[start:]
    if not parts:
        return None
    rest = _uv_rest(parts)
    if rest is not None:
        found = script_of(rest)
        return (found[0], False) if found is not None else None
    if program_name(parts[0]) in _INTERPRETERS:
        script = _interpreted(parts)
        return (script, False) if script is not None else None
    return parts[0], True


def script_word(segment: str) -> tuple[str, bool] | None:
    """Return the script one shell command runs, and whether it runs directly; see :func:`script_of`.

    Args:
        segment: One command, as :func:`segments` returns it.

    Returns:
        ``(word, direct)``, or None when the command names no script.
    """
    return script_of(words(segment))


class _PlaceholderScan:
    """One left-to-right pass over shell text that tracks quoting through ``$(...)`` and ``(...)`` nesting."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._quote = ""
        self._assignment = False
        self._stack: list[tuple[str, bool]] = []
        self.found: list[str] = []

    def run(self) -> list[str]:
        """Scan the whole text and return the unquoted placeholders outside assignment words."""
        index = 0
        while index < len(self._text):
            index = self._step(index)
        return self.found

    def _step(self, index: int) -> int:
        """Read the text at ``index`` and return where the next read starts."""
        char = self._text[index]
        if self._quote == "'":
            self._quote = "" if char == "'" else "'"
            return index + 1
        if char == "\\":
            return index + 2
        if self._text.startswith("$(", index):
            self._stack.append((self._quote, self._assignment))
            self._quote = ""
            return index + 2
        if self._quote == '"':
            self._quote = "" if char == '"' else '"'
            return index + 1
        return self._unquoted(index, char)

    def _unquoted(self, index: int, char: str) -> int:
        """Read one character outside quotes: a word start, a quote, a parenthesis or a placeholder."""
        if index == 0 or self._text[index - 1] in _WORD_BREAKS:
            self._assignment = _ASSIGNMENT_AT.match(self._text, index) is not None
        if char in "\"'":
            self._quote = char
        elif char == "(":
            self._stack.append(("", self._assignment))
        elif char == ")" and self._stack:
            self._quote, self._assignment = self._stack.pop()
        elif char == "$":
            return self._placeholder(index)
        return index + 1

    def _placeholder(self, index: int) -> int:
        """Record a placeholder at ``index`` unless it is part of an assignment word, and return where it ends."""
        match = _PLACEHOLDER_AT.match(self._text, index)
        if match is None:
            return index + 1
        if not self._assignment:
            self.found.append(match.group(0))
        return match.end()


def unquoted_placeholders(command: str) -> list[str]:
    """Return the Claude Code path placeholders written outside any quotes in shell text.

    The placeholders are ``$CLAUDE_PROJECT_DIR``, ``${CLAUDE_PROJECT_DIR}``, ``$CLAUDE_PLUGIN_ROOT`` and
    ``${CLAUDE_PLUGIN_ROOT}``; ``$CLAUDE_PROJECT_DIRX`` is another variable. Text inside double quotes is quoted,
    text inside single quotes is not expanded at all, and a backslash outside single quotes escapes the next
    character. Quoting restarts inside ``$(...)``, and its closing ``)`` returns to the quoting around it, so
    ``"$(dirname "$CLAUDE_PROJECT_DIR")"`` is quoted. A placeholder in an assignment word (``D=$CLAUDE_PROJECT_DIR``)
    is not reported, since the shell does not split an assignment. An unterminated quote runs to the end of the text.

    Args:
        command: The shell text, possibly several lines.

    Returns:
        The unquoted placeholders as written, in order.
    """
    return _PlaceholderScan(command).run()
