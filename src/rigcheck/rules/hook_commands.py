"""Rules for the commands hook handlers run: their form, their paths and how they fail."""

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from rigcheck.model import Finding, Layer, Rig, Severity, git_output
from rigcheck.parse import config, shell
from rigcheck.rules import emit, rule
from rigcheck.rules.config import HookHandler, HookMap, HookSource, handlers, hook_maps
from rigcheck.rules.references import exists, inside, resolved

_JSON_SOURCES = (HookSource.SETTINGS, HookSource.PLUGIN_HOOKS, HookSource.PLUGIN_MANIFEST)
_PLUGIN_SOURCES = (HookSource.PLUGIN_HOOKS, HookSource.PLUGIN_MANIFEST)
_PROJECT_DIR = ("${CLAUDE_PROJECT_DIR}", "$CLAUDE_PROJECT_DIR")
_PLUGIN_ROOT = ("${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT")
_UNRESOLVED_CHARS = frozenset("$`*?%")
"""Characters left in a path after its placeholder that make it unknowable without running a shell."""
_DIRECTORY_CHANGES = frozenset({"cd", "pushd", "set-location", "sl"})
_MAX_SCRIPT_BYTES = 1024 * 1024
_REGULAR = "100644"
"""The git mode of a regular file without the executable bit; a symlink (120000) or an executable (100755) is fine."""
_WINDOWS_SUFFIXES = frozenset({".cmd", ".bat", ".exe", ".com", ".ps1"})
"""Script types Windows runs by extension, which never need the executable bit."""


@dataclass(frozen=True)
class _Command:
    """One command handler with a non-empty command string.

    Attributes:
        hook: The handler as the hook map holds it.
        text: The ``command`` string.
        args: The ``args`` list in exec form, or None in shell form.
        line: The 1-based line findings on this handler point at.
    """

    hook: HookHandler
    text: str
    args: tuple[str, ...] | None
    line: int

    @property
    def inline(self) -> str:
        """The command as one line of text: in exec form, the command and its arguments joined by spaces."""
        return self.text if self.args is None else " ".join((self.text, *self.args))


@dataclass(frozen=True)
class _Script:
    """A script a command runs, resolved to a path.

    Attributes:
        word: The script word as written, quotes removed.
        path: Where it resolves.
        root: The folder it was resolved against: the repo root, the plugin root or the home folder.
        direct: Whether the command runs it directly rather than through an interpreter.
    """

    word: str
    path: Path
    root: Path
    direct: bool


def _line_start(text: str, line: int | None) -> int:
    """Return the offset where 1-based ``line`` starts in ``text``, or 0 when the line is unknown."""
    if line is None:
        return 0
    return sum(len(part) + 1 for part in text.split("\n")[: line - 1])


def _line(text: str, hook: HookHandler, command: str) -> int:
    """Return the line holding ``command`` as written, else the event's key, else the ``hooks`` key, else 1.

    In a JSON file the command is matched as a whole JSON string, from the event's key onwards, so the same command
    under two events points at each; in frontmatter its first line is matched from the ``hooks`` key onwards.
    """
    json_source = hook.map.source in _JSON_SOURCES
    event_line = config.key_line(text, ("hooks", hook.event)) if json_source else None
    start = _line_start(text, event_line if json_source else hook.map.line)
    needles = (json.dumps(command, ensure_ascii=False), json.dumps(command)) if json_source else (command.split("\n", 1)[0].strip(),)
    for needle in needles:
        offset = text.find(needle, start) if needle else -1
        if offset >= 0:
            return text.count("\n", 0, offset) + 1
    return event_line or hook.map.line or 1


def _command(text: str, hook: HookHandler) -> _Command | None:
    """Return the handler as a command, or None when it is not a command handler with a command string and a usable form."""
    command = hook.handler.get("command")
    args = hook.handler.get("args")
    if hook.handler.get("type") != "command" or not isinstance(command, str) or not command.strip():
        return None
    if "args" in hook.handler and not isinstance(args, list):
        return None
    exec_args = tuple(arg for arg in args if isinstance(arg, str)) if isinstance(args, list) else None
    return _Command(hook, command, exec_args, _line(text, hook, command))


def _commands(rig: Rig) -> Iterator[_Command]:
    """Yield every command handler in the rig's hook maps."""
    for hook_map in hook_maps(rig):
        text = rig.text(hook_map.artifact.path)
        for hook in handlers(hook_map):
            command = _command(text, hook)
            if command is not None:
                yield command


def _shell_scripts(text: str) -> list[tuple[str, bool]]:
    """Return the script words of shell text, segment by segment, stopping at the first change of directory."""
    found: list[tuple[str, bool]] = []
    for line in text.splitlines():
        for segment in shell.segments(shell.uncommented(line)):
            word = shell.command_word(segment)
            if word is not None and shell.program_name(word) in _DIRECTORY_CHANGES:
                return found
            script = shell.script_word(segment)
            if script is not None:
                found.append(script)
    return found


def _scripts(command: _Command) -> list[tuple[str, bool]]:
    """Return the script words a command runs, with whether each runs directly."""
    if command.args is None:
        return _shell_scripts(command.text)
    script = shell.script_of([command.text, *command.args])
    return [script] if script is not None else []


def _placeholder_rest(word: str, names: tuple[str, ...]) -> str | None:
    """Return the path after one of the placeholder ``names`` and its ``/``, or None when ``word`` does not start that way."""
    for name in names:
        rest = word.removeprefix(name)
        if rest != word:
            return rest[1:] if rest.startswith("/") else None
    return None


def _anchor(rig: Rig, hook_map: HookMap, word: str) -> tuple[Path | None, str] | None:
    """Return the folder a placeholder word resolves against (None when this map cannot know it) and the rest of the word."""
    project = rig.repo_root if hook_map.artifact.layer is Layer.REPO else None
    plugin = hook_map.artifact.path.parent.parent if hook_map.source in _PLUGIN_SOURCES else None
    for names, base in ((_PROJECT_DIR, project), (_PLUGIN_ROOT, plugin)):
        rest = _placeholder_rest(word, names)
        if rest is not None:
            return base, rest
    return None


def _base(rig: Rig, hook_map: HookMap, word: str) -> tuple[Path, str] | None:
    """Return the folder a script word resolves against and the path under it, or None when it cannot be resolved."""
    anchor = _anchor(rig, hook_map, word)
    if anchor is not None:
        base, rest = anchor
        return (base, rest) if base is not None else None
    if word.startswith("~/"):
        return rig.home, word[2:]
    if hook_map.artifact.layer is Layer.REPO and not shell.anchored(word) and "/" in word:
        return rig.repo_root, word
    return None


def _resolve(rig: Rig, hook_map: HookMap, word: str, direct: bool) -> _Script | None:
    """Resolve one script word to a path, or return None when it names no knowable file."""
    found = _base(rig, hook_map, word.replace("\\", "/"))
    if found is None or not found[1] or _UNRESOLVED_CHARS.intersection(found[1]):
        return None
    base, rest = found
    return _Script(word, resolved(base, rest), base, direct)


def _resolved_scripts(rig: Rig, command: _Command) -> list[_Script]:
    """Return the scripts of a command that resolve to a path."""
    scripts = (_resolve(rig, command.hook.map, word, direct) for word, direct in _scripts(command))
    return [script for script in scripts if script is not None]


class _GitModes:
    """The file modes git records for the repository's tracked files, read with one ``git ls-files`` on first use."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._modes: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
        output = git_output(self._root, "ls-files", "-s", "-z") or ""
        modes: dict[str, str] = {}
        for entry in output.split("\0"):
            meta, tab, name = entry.partition("\t")
            if tab:
                modes[name] = meta.split(" ", 1)[0]
        return modes

    def mode(self, path: Path) -> str | None:
        """Return the mode git records for ``path``, or None when git does not track it."""
        if self._modes is None:
            self._modes = self._load()
        try:
            relative = path.relative_to(self._root)
        except ValueError:
            return None
        return self._modes.get(relative.as_posix())


def _missing_message(script: _Script, modes: _GitModes, repo: bool) -> str | None:
    """Return the message for a script that does not exist, or that git tracks without the executable bit it needs."""
    if not exists(script.path):
        return f'hook script "{script.word}" does not exist, so this hook is silently disabled'
    windows = script.path.suffix.lower() in _WINDOWS_SUFFIXES
    if script.direct and repo and not windows and modes.mode(script.path) == _REGULAR:
        return f'hook script "{script.word}" is committed without the executable bit, so a fresh clone cannot run it'
    return None


@rule(
    "hook-script-missing",
    "core",
    Severity.ERROR,
    "Fix the path, add the script, or commit it executable (git update-index --chmod=+x <path>).",
    ("official:HK8",),
)
def hook_script_missing(rig: Rig) -> Iterator[Finding]:
    """A hook's script does not exist, or runs directly but is committed without the executable bit."""
    modes = _GitModes(rig.repo_root)
    for command in _commands(rig):
        repo = command.hook.map.artifact.layer is Layer.REPO
        for script in _resolved_scripts(rig, command):
            message = _missing_message(script, modes, repo)
            if message is not None:
                yield emit("hook-script-missing", command.hook.map.artifact, message, command.line)


@rule(
    "hook-script-relative",
    "core",
    Severity.WARN,
    'Anchor the path at "${CLAUDE_PROJECT_DIR}" (or ${CLAUDE_PLUGIN_ROOT} in a plugin).',
    ("official:HK9",),
)
def hook_script_relative(rig: Rig) -> Iterator[Finding]:
    """A hook runs a script by a path relative to the current directory."""
    for command in _commands(rig):
        word = next((word for word, _direct in _scripts(command) if shell.cwd_relative(word, True)), None)
        if word is not None:
            message = f'hook script "{word}" is relative, so it breaks when Claude Code runs from another folder'
            yield emit("hook-script-relative", command.hook.map.artifact, message, command.line)


@rule(
    "hook-placeholder-unquoted",
    "core",
    Severity.WARN,
    "Wrap the placeholder in double quotes, or use exec form (command plus args).",
    ("official:HK9",),
)
def hook_placeholder_unquoted(rig: Rig) -> Iterator[Finding]:
    """A shell-form hook command uses a path placeholder outside double quotes."""
    for command in _commands(rig):
        found = shell.unquoted_placeholders(command.text) if command.args is None else []
        if found:
            message = f"{found[0]} is not in double quotes, so a path with spaces splits"
            yield emit("hook-placeholder-unquoted", command.hook.map.artifact, message, command.line)


def _spawn_fails(command: _Command) -> bool:
    """True when an exec-form command is a bare name holding whitespace, which Claude Code cannot spawn."""
    text = command.text
    return command.args is not None and "/" not in text and "\\" not in text and any(char.isspace() for char in text)


@rule(
    "hook-exec-form-spawn",
    "core",
    Severity.ERROR,
    "Put the program alone in command and every argument in args.",
    ("official:HK10",),
)
def hook_exec_form_spawn(rig: Rig) -> Iterator[Finding]:
    """An exec-form hook puts a bare program name and its arguments together in ``command``."""
    for command in _commands(rig):
        if _spawn_fails(command):
            message = f'command "{command.text}" holds whitespace alongside args, so the spawn fails'
            yield emit("hook-exec-form-spawn", command.hook.map.artifact, message, command.line)


def _readable(script: _Script) -> bool:
    """True when a resolved script is a file inside its root and small enough to read."""
    if not inside(script.path, script.root):
        return False
    try:
        return script.path.is_file() and script.path.stat().st_size <= _MAX_SCRIPT_BYTES
    except OSError:
        return False


def _texts(rig: Rig, command: _Command) -> list[str]:
    """Return the command's inline text followed by the text of each script it runs that can be read."""
    return [command.inline, *(rig.text(script.path) for script in _resolved_scripts(rig, command) if _readable(script))]


_BLOCKING_EVENTS = frozenset({"PreToolUse", "UserPromptSubmit", "Stop", "SubagentStop"})
_EXIT_1 = re.compile(r"\bexit\s+1\b")
_EXIT_2 = re.compile(r"\bexit\s+2\b")
_JSON_OUTPUT = re.compile(r'permissionDecision|"decision"')


def _blocks_with_exit_1(text: str) -> bool:
    """True when ``text`` exits 1 and has neither an ``exit 2`` nor JSON decision output to block with."""
    return _EXIT_1.search(text) is not None and _EXIT_2.search(text) is None and _JSON_OUTPUT.search(text) is None


@rule(
    "hook-exit-1-blocking",
    "core",
    Severity.WARN,
    "Use exit 2 (or JSON output) to block the action.",
    ("official:HK7",),
)
def hook_exit_1_blocking(rig: Rig) -> Iterator[Finding]:
    """A hook on a blocking event exits 1, which Claude Code treats as a non-blocking error."""
    for command in _commands(rig):
        if command.hook.event in _BLOCKING_EVENTS and _blocks_with_exit_1("\n".join(_texts(rig, command))):
            event = command.hook.event
            message = f"exit 1 does not block {event}; Claude Code treats it as a non-blocking error"
            yield emit("hook-exit-1-blocking", command.hook.map.artifact, message, command.line)


_PRINTERS = frozenset({"cat", "type", "get-content", "gc", "head", "tail", "bat", "more", "less"})
_INSTRUCTION_NAMES = frozenset({"CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"})


def _printed_name(segment: str) -> str | None:
    """Return the instruction file one command prints, or None when it prints none."""
    parts = shell.command_words(segment)
    if not parts or shell.program_name(parts[0]) not in _PRINTERS:
        return None
    names = (re.split(r"[\\/]", word)[-1] for word in parts[1:])
    return next((name for name in names if name in _INSTRUCTION_NAMES), None)


def _printed(texts: Sequence[str]) -> str | None:
    """Return the first instruction file any line of ``texts`` prints."""
    for text in texts:
        for line in text.splitlines():
            for segment in shell.segments(shell.uncommented(line)):
                name = _printed_name(segment)
                if name is not None:
                    return name
    return None


@rule(
    "hook-reprints-instructions",
    "core",
    Severity.WARN,
    "Remove the hook; Claude Code already loads the file it prints.",
    ("official:CM17",),
)
def hook_reprints_instructions(rig: Rig) -> Iterator[Finding]:
    """A SessionStart hook prints an instruction file Claude Code already loads."""
    for command in _commands(rig):
        name = _printed(_texts(rig, command)) if command.hook.event == "SessionStart" else None
        if name is not None:
            message = f"SessionStart hook prints {name}, which Claude Code already loads, so it is in context twice"
            yield emit("hook-reprints-instructions", command.hook.map.artifact, message, command.line)
