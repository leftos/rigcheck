"""Rules for permission entries: allow, ask and deny, and the tool patterns they match."""

import itertools
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from wcmatch import glob

from rigcheck.discover import SKIP_DIRS, path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity, git_output
from rigcheck.parse import config
from rigcheck.parse.permissions import PermissionRule, bash_covers, parse_rule
from rigcheck.rules import emit, emit_setup, rule

_LISTS = ("allow", "ask", "deny")
"""The permission lists, in the order a settings file is read."""

_IGNORED_PATH_TOOLS = frozenset({"Write", "NotebookEdit", "Glob", "MultiEdit"})
"""Tools whose path rules Claude Code accepts but never consults."""

_PATH_TOOLS = frozenset({"Read", "Edit"})
"""Tools whose specifier is a path Claude Code checks."""

_SECRET_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
"""File names that hold secrets."""

_SECRET_SUFFIXES = (".pem", ".key")
"""File name endings that hold secrets."""

_ENV_TEMPLATES = (".example", ".sample", ".template")
"""Endings of ``.env.*`` files that hold placeholders rather than secrets."""

_SECRET_CAP = 10
"""How many uncovered secret files one run reports."""

_PEM_PROBE_BYTES = 64 * 1024
"""How much of a ``.pem`` file is searched for a private key."""

_WALK_DEPTH = 6
"""How many folder levels below an ignored folder the secret walk descends."""

_WALK_BUDGET = 20_000
"""How many entries the secret walk of ignored folders visits in one run."""

_WALK_SKIP = SKIP_DIRS | {"__pycache__"}
"""Folder names the secret walk of ignored folders does not enter."""

_GLOB_FLAGS = glob.GLOBSTAR | glob.DOTGLOB


@dataclass(frozen=True)
class _Entry:
    """One parsed rule of a settings file's permission list.

    Attributes:
        artifact: The settings file.
        list_name: ``allow``, ``ask`` or ``deny``.
        rule: The parsed rule.
        line: The 1-based line the rule is written on.
    """

    artifact: Artifact
    list_name: str
    rule: PermissionRule
    line: int


def _scope(artifact: Artifact) -> str:
    """Return the settings scope a file belongs to: ``user``, ``local`` or ``project``."""
    if artifact.layer is Layer.USER:
        return "user"
    return "local" if artifact.path.name == "settings.local.json" else "project"


def _display(rig: Rig, artifact: Artifact) -> str:
    """Show a settings file relative to the repo, or to home as ``~/``, or in full."""
    for base, prefix in ((rig.repo_root, ""), (rig.home, "~/")):
        if artifact.path.is_relative_to(base):
            return prefix + artifact.path.relative_to(base).as_posix()
    return artifact.path.as_posix()


def _settings_files(rig: Rig) -> Iterator[Artifact]:
    """Yield the settings files on the repo and user layers, in rig order."""
    for artifact in rig.artifacts:
        if artifact.kind is Kind.SETTINGS and artifact.layer in (Layer.REPO, Layer.USER):
            yield artifact


def _permissions(text: str) -> dict[object, object] | None:
    """Return the ``permissions`` object of a settings text, or None when it has none."""
    data = config.load(text).data
    permissions = data.get("permissions") if isinstance(data, dict) else None
    return permissions if isinstance(permissions, dict) else None


def _line_start(text: str, line: int) -> int:
    """Return the offset of the first character of 1-based ``line``."""
    offset = 0
    for _ in range(line - 1):
        offset = text.find("\n", offset) + 1
        if offset == 0:
            return len(text)
    return offset


def _find_raw(text: str, raw: str, start: int) -> int | None:
    """Return the offset of the first quoted ``raw`` at or after ``start``, as JSON writes it with or without escapes."""
    hits = [text.find(json.dumps(raw, ensure_ascii=escaped), start) for escaped in (True, False)]
    found = [hit for hit in hits if hit >= 0]
    return min(found) if found else None


def _list_entries(artifact: Artifact, text: str, list_name: str, values: list[object]) -> Iterator[_Entry]:
    """Yield the parsed string rules of one permission list, each on the line it is written on."""
    list_line = config.key_line(text, ("permissions", list_name))
    cursor = _line_start(text, list_line or 1)
    for raw in values:
        if not isinstance(raw, str):
            continue
        found = _find_raw(text, raw, cursor)
        line = list_line or 1
        if found is not None:
            cursor = found + 1
            line = text.count("\n", 0, found) + 1
        parsed = parse_rule(raw)
        if parsed is not None:
            yield _Entry(artifact, list_name, parsed, line)


def _entries(rig: Rig) -> list[_Entry]:
    """Return every parsed permission rule of the repo and user settings files, file by file, list by list."""
    entries: list[_Entry] = []
    for artifact in _settings_files(rig):
        text = rig.text(artifact.path)
        permissions = _permissions(text)
        if permissions is None:
            continue
        for list_name in _LISTS:
            values = permissions.get(list_name)
            if isinstance(values, list):
                entries.extend(_list_entries(artifact, text, list_name, values))
    return entries


def settings_allow_rules(rig: Rig) -> list[PermissionRule]:
    """Return the parsed ``allow`` rules of the repo and user settings files, in rig order."""
    return [entry.rule for entry in _entries(rig) if entry.list_name == "allow"]


def _mcp_covers(blocker: PermissionRule, allowed: PermissionRule) -> bool:
    """Return True when ``blocker`` names a whole MCP server (``mcp__s`` or ``mcp__s__*``) that ``allowed`` is a tool of."""
    if blocker.specifier is not None or not blocker.tool.startswith("mcp__"):
        return False
    server = blocker.tool.removeprefix("mcp__").removesuffix("__*")
    if not server or "__" in server or "*" in server:
        return False
    return allowed.tool == f"mcp__{server}" or allowed.tool.startswith(f"mcp__{server}__")


def _source_base(rig: Rig, artifact: Artifact) -> Path:
    """Return the folder a ``/path`` rule in ``artifact`` is relative to: ``~/.claude`` for user settings, else the repo root."""
    return rig.home / ".claude" if artifact.layer is Layer.USER else rig.repo_root


def _resolved_specifier(rig: Rig, entry: _Entry) -> str | None:
    """Return a rule's specifier, a Read or Edit path resolved by its anchor to an absolute POSIX path.

    ``//x`` is the absolute ``/x``, ``~/x`` is under home and ``/x`` is under the settings file's
    base; ``x`` and ``./x`` stay as written. Other tools' specifiers are returned unchanged.
    """
    specifier = entry.rule.specifier
    if entry.rule.tool not in _PATH_TOOLS or specifier is None:
        return specifier
    if specifier.startswith("//"):
        return specifier[1:]
    if specifier.startswith("~/"):
        return _posix(rig.home) + specifier[1:]
    if specifier.startswith("/"):
        return _posix(_source_base(rig, entry.artifact)) + specifier
    return specifier


def _covers(rig: Rig, blocker: _Entry, allowed: _Entry) -> bool:
    """Return True when the deny or ask rule ``blocker`` matches every call the allow rule ``allowed`` approves."""
    if _mcp_covers(blocker.rule, allowed.rule):
        return True
    if blocker.rule.tool != allowed.rule.tool:
        return False
    if blocker.rule.specifier is None or _resolved_specifier(rig, blocker) == _resolved_specifier(rig, allowed):
        return True
    specifier = allowed.rule.specifier
    if allowed.rule.tool != "Bash" or specifier is None or "*" in specifier or blocker.rule.specifier is None:
        return False
    return bash_covers(blocker.rule.specifier, specifier)


def _first_blocker(rig: Rig, allowed: _Entry, entries: list[_Entry]) -> _Entry | None:
    """Return the first deny rule, else the first ask rule, that covers ``allowed``."""
    for list_name in ("deny", "ask"):
        for entry in entries:
            if entry.list_name == list_name and _covers(rig, entry, allowed):
                return entry
    return None


@rule(
    "permission-allow-shadowed",
    "core",
    Severity.WARN,
    "Remove the dead allow rule, or narrow the deny or ask rule that covers it.",
    ("official:ST2",),
)
def permission_allow_shadowed(rig: Rig) -> Iterator[Finding]:
    """An allow rule that a deny or ask rule in any loaded settings file matches first, so it never applies."""
    entries = _entries(rig)
    for entry in entries:
        if entry.list_name != "allow":
            continue
        blocker = _first_blocker(rig, entry, entries)
        if blocker is None:
            continue
        where = f"{_scope(blocker.artifact)} settings ({_display(rig, blocker.artifact)})"
        message = f'allow "{entry.rule.raw}" never applies: {blocker.list_name} "{blocker.rule.raw}" in {where} matches first'
        yield emit("permission-allow-shadowed", entry.artifact, message, entry.line)


@rule(
    "permission-path-tool-ignored",
    "core",
    Severity.ERROR,
    "Write the rule as Edit(<path>) (Edit covers Write and NotebookEdit) or Read(<path>).",
    ("official:ST3",),
)
def permission_path_tool_ignored(rig: Rig) -> Iterator[Finding]:
    """A path rule on Write, NotebookEdit, Glob or MultiEdit, which Claude Code accepts but never consults."""
    for entry in _entries(rig):
        if entry.rule.tool in _IGNORED_PATH_TOOLS and entry.rule.specifier is not None:
            message = f'path rule "{entry.rule.raw}" is accepted but never consulted; Claude Code checks paths only on Read and Edit'
            yield emit("permission-path-tool-ignored", entry.artifact, message, entry.line)


def _bash_specifiers(rig: Rig) -> Iterator[tuple[_Entry, str]]:
    """Yield each ``Bash(...)`` rule with its specifier."""
    for entry in _entries(rig):
        if entry.rule.tool == "Bash" and entry.rule.specifier is not None:
            yield entry, entry.rule.specifier


@rule(
    "permission-bash-wildcard",
    "core",
    Severity.WARN,
    "Put a space before the trailing * (Bash(ls *)) unless the prefix match is intended.",
    ("official:ST6",),
)
def permission_bash_wildcard(rig: Rig) -> Iterator[Finding]:
    """A Bash allow rule whose trailing * has no space before it, so it also matches longer command names."""
    for entry, specifier in _bash_specifiers(rig):
        if entry.list_name != "allow" or not specifier.endswith("*") or specifier.endswith((" *", ":*")) or specifier == "*":
            continue
        message = f'allow "{entry.rule.raw}" has no space before *, so it also matches longer commands (Bash(ls*) matches lsof)'
        yield emit("permission-bash-wildcard", entry.artifact, message, entry.line)


@rule(
    "permission-bash-colon-star",
    "core",
    Severity.ERROR,
    "Use a space-separated wildcard (Bash(git * push)) or put :* only at the end.",
    ("official:ST6",),
)
def permission_bash_colon_star(rig: Rig) -> Iterator[Finding]:
    """A Bash rule with :* before its end, where the colon is a literal character rather than a wildcard marker."""
    for entry, specifier in _bash_specifiers(rig):
        if ":*" in specifier.removesuffix(":*"):
            message = f'"{entry.rule.raw}" has :* mid-pattern, where the colon is a literal character'
            yield emit("permission-bash-colon-star", entry.artifact, message, entry.line)


def _is_secret_name(name: str) -> bool:
    """Return True when a file name is one that holds secrets."""
    if name in _SECRET_NAMES or name.endswith(_SECRET_SUFFIXES):
        return True
    return name.startswith(".env.") and not name.endswith(_ENV_TEMPLATES)


def _holds_private_key(path: Path) -> bool:
    """Return True when a ``.pem`` file's first 64 KiB hold ``PRIVATE KEY``, or when the file cannot be read."""
    try:
        with path.open("rb") as handle:
            head = handle.read(_PEM_PROBE_BYTES)
    except OSError:
        return True
    return b"PRIVATE KEY" in head


def _secret_candidate(root: Path, path: str) -> str | None:
    """Return the secret a repo path stands for: its outermost ``secrets/`` folder, the file itself, or None.

    A ``.pem`` file counts only when it holds a private key, so a public certificate is not a secret.
    """
    is_folder = path.endswith("/")
    parts = path.rstrip("/").split("/")
    folders = parts if is_folder else parts[:-1]
    if "secrets" in folders:
        return "/".join(parts[: folders.index("secrets") + 1]) + "/"
    if is_folder or not _is_secret_name(parts[-1]):
        return None
    if parts[-1].endswith(".pem") and not _holds_private_key(root / path):
        return None
    return path


def _walk_skipped(path: Path) -> bool:
    """Return True for a folder the ignored-folder walk does not enter: a skip-set name, a link, a junction or a virtualenv."""
    return path.name in _WALK_SKIP or path.is_symlink() or path.is_junction() or (path / "pyvenv.cfg").is_file()


class _IgnoredWalk:
    """A bounded walk of the folders git reports as ignored, whose files git does not list one by one.

    One walk serves a whole run. It goes at most 6 folder levels below each ignored folder and
    visits at most 20,000 entries in all; once that budget is spent it stops without a finding or
    a problem, so a huge ignored tree (a cache, a dependency folder outside the skip set) cannot
    stall the run. A folder that cannot be listed is passed over the same way.

    Attributes:
        root: The repo root the reported paths are relative to.
        left: How many more entries the walk may visit.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.left = _WALK_BUDGET

    def files(self, folder: str) -> Iterator[str]:
        """Yield the repo-relative POSIX paths of the files under the ignored ``folder``."""
        start = self.root / folder
        if _walk_skipped(start):
            return
        pending = [(start, 0)]
        while pending and self.left > 0:
            directory, depth = pending.pop()
            for entry in self._scan(directory):
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if depth < _WALK_DEPTH and not _walk_skipped(path):
                        pending.append((path, depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    yield path.relative_to(self.root).as_posix()

    def _scan(self, directory: Path) -> list[os.DirEntry[str]]:
        """Return the entries of ``directory`` the budget still allows, and charge them to it."""
        try:
            with os.scandir(directory) as entries:
                listed = list(itertools.islice(entries, self.left))
        except OSError:
            return []
        self.left -= len(listed)
        return listed


def _repo_paths(rig: Rig, project_files: frozenset[str]) -> set[str]:
    """Return git's files plus the git-ignored files and folders on disk, and the files inside those folders, repo-relative."""
    ignored = git_output(rig.repo_root, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "--no-empty-directory", "-z")
    paths = set(project_files)
    walk = _IgnoredWalk(rig.repo_root)
    for name in (ignored or "").split("\0"):
        if not name:
            continue
        paths.add(name)
        if name.endswith("/"):
            paths.update(walk.files(name))
    return paths


def _posix(path: Path) -> str:
    """Return an absolute path in Claude Code's POSIX form, a Windows drive ``C:`` becoming ``/c``."""
    text = path.as_posix()
    if len(text) > 1 and text[1] == ":":
        return "/" + text[0].lower() + text[2:]
    return text


@dataclass(frozen=True)
class _ReadDeny:
    """A ``Read(...)`` deny pattern resolved against a folder.

    Attributes:
        base: The POSIX folder the patterns are relative to; the empty string for the filesystem root.
        patterns: The glob patterns to try on a path relative to ``base``.
        negated: True for a ``!`` pattern, which re-opens what an earlier pattern of the same file covered.
    """

    base: str
    patterns: tuple[str, ...]
    negated: bool


def _deny_patterns(rig: Rig, artifact: Artifact, body: str) -> tuple[str, tuple[str, ...]]:
    """Resolve a Read deny path by its anchor: ``//`` absolute, ``~/`` home, ``/`` the settings source, else the repo at any depth."""
    if body.startswith("//"):
        return "", (body[2:],)
    if body.startswith("~/"):
        return _posix(rig.home), (body[2:],)
    if body.startswith("/"):
        return _posix(_source_base(rig, artifact)), (body[1:],)
    relative = body.removeprefix("./")
    return _posix(rig.repo_root), (relative, "**/" + relative)


def _read_deny(rig: Rig, entry: _Entry, specifier: str) -> _ReadDeny:
    """Resolve one Read deny specifier, a leading ``!`` marking a gitignore negation."""
    base, patterns = _deny_patterns(rig, entry.artifact, specifier.removeprefix("!"))
    return _ReadDeny(base, patterns, specifier.startswith("!"))


def _read_denies(rig: Rig) -> list[list[_ReadDeny]] | None:
    """Return the Read deny patterns of each settings file in list order, or None when a whole-tool Read deny covers everything."""
    groups: dict[Path, list[_ReadDeny]] = {}
    for entry in _entries(rig):
        if entry.list_name != "deny" or entry.rule.tool != "Read":
            continue
        specifier = entry.rule.specifier
        if specifier is None:
            return None
        if specifier.removeprefix("!"):
            groups.setdefault(entry.artifact.path, []).append(_read_deny(rig, entry, specifier))
    return list(groups.values())


def _deny_matches(absolute: str, deny: _ReadDeny) -> bool:
    """Return True when one Read deny pattern matches the absolute POSIX path."""
    prefix = deny.base.rstrip("/") + "/"
    if not absolute.startswith(prefix):
        return False
    relative = absolute[len(prefix) :]
    return any(glob.globmatch(relative, pattern, flags=_GLOB_FLAGS) for pattern in deny.patterns)


def _file_covers(absolute: str, denies: list[_ReadDeny]) -> bool:
    """Return True when one file's Read denies, read in order with gitignore negation, leave the path covered."""
    covered = False
    for deny in denies:
        if _deny_matches(absolute, deny):
            covered = not deny.negated
    return covered


def _covered(candidate: str, root: str, groups: list[list[_ReadDeny]]) -> bool:
    """Return True when any settings file's Read denies cover the repo-relative candidate, whose repo sits at POSIX ``root``."""
    absolute = f"{root}/{candidate}"
    return any(_file_covers(absolute, denies) for denies in groups)


def _anchor(rig: Rig) -> Artifact | None:
    """Return the repo's ``.claude/settings.json``, else its ``settings.local.json``, else None."""
    for name in ("settings.json", "settings.local.json"):
        for artifact in _settings_files(rig):
            if artifact.layer is Layer.REPO and artifact.path.name == name:
                return artifact
    return None


def _uncovered_secrets(rig: Rig, project_files: frozenset[str]) -> list[str]:
    """Return the repo's secret files and folders that no Read deny rule covers, sorted."""
    denies = _read_denies(rig)
    if denies is None:
        return []
    candidates = {_secret_candidate(rig.repo_root, path) for path in _repo_paths(rig, project_files)}
    root = _posix(rig.repo_root)
    return sorted(found for found in candidates if found is not None and not _covered(found, root, denies))


@rule(
    "secret-file-not-denied",
    "core",
    Severity.WARN,
    'Add a Read deny for it, such as "Read(./.env)" or "Read(./secrets/**)", to permissions.deny.',
    ("official:ST5",),
)
def secret_file_not_denied(rig: Rig) -> Iterator[Finding]:
    """A secret file in the repo (.env, a key, a secrets folder) that no Read deny rule covers, so Claude can read it."""
    home = path_key(rig.home)
    if rig.project_files is None or home in (path_key(rig.target), path_key(rig.repo_root)):
        return
    uncovered = _uncovered_secrets(rig, rig.project_files)
    anchor = _anchor(rig)
    line = (config.key_line(rig.text(anchor.path), ("permissions",)) or 1) if anchor is not None else None
    for index, path in enumerate(uncovered[:_SECRET_CAP]):
        message = f"{path} is not covered by a Read deny rule, so Claude can read it"
        if index == _SECRET_CAP - 1 and len(uncovered) > _SECRET_CAP:
            message += f" (and {len(uncovered) - _SECRET_CAP} more)"
        yield emit_setup("secret-file-not-denied", message) if anchor is None else emit("secret-file-not-denied", anchor, message, line)
