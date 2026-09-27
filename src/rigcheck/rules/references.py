"""Rules for paths and commands that instruction files name but the repository does not have."""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

from rigcheck.discover import AGENTS_MD, IGNORED_BY_CLAUDE, SKIP_DIRS, path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, LoadClass, Rig, Severity
from rigcheck.parse.markdown import Reference, find_references
from rigcheck.rules import emit, rule

_SCANNED_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS, Kind.RULE)
_SCANNED_LAYERS = (Layer.REPO, Layer.USER)
_EVIDENCE = ("sota:#2 (A)", "sota:#23 (B)")
_DRIVE = re.compile(r"^[A-Za-z]:")
_PLACEHOLDER_CHARS = frozenset("*?[]{}<>$%`")
_NOT_PATH_PREFIXES = ("#",)
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")
_KNOWN_SCHEMES = frozenset(
    {"tel", "sms", "mailto", "http", "https", "ftp", "file", "data", "javascript", "about", "urn", "ssh", "git"}
    | {"vscode", "vscode-insiders", "cursor", "zed", "obsidian", "slack"}
)
"""Schemes recognised before a ``:line`` suffix is dropped, so ``tel:5550100`` names no file but ``Makefile:12`` does."""
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(\S*)$")
_LOCATION = re.compile(r":\d+(?::\d+)?$")
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(com|org|net|io|dev|ai|app|co|gg|me|sh|xyz)$", re.IGNORECASE)


def _scanned(rig: Rig) -> list[Artifact]:
    """Instruction and rule files a user or project maintains, including an AGENTS.md only Codex reads."""
    return [
        a
        for a in rig.artifacts
        if a.kind in _SCANNED_KINDS
        and a.layer in _SCANNED_LAYERS
        and a.path.name not in IGNORED_BY_CLAUDE
        and (a.load_class is not LoadClass.NOT_LOADED or a.path.name == AGENTS_MD)
    ]


def _references(rig: Rig, artifact: Artifact) -> list[Reference]:
    return find_references(rig.text(artifact.path))


def _link_target(href: str) -> str | None:
    if "://" in href or href.startswith(_NOT_PATH_PREFIXES) or any(char.isspace() for char in href):
        return None
    return unquote(re.split(r"[#?]", href, maxsplit=1)[0])


def _span_target(content: str) -> str | None:
    assignment = _ASSIGNMENT.match(content)
    if assignment is not None:
        content = assignment.group(1)
    if "://" in content or content.startswith(_NOT_PATH_PREFIXES) or any(char.isspace() for char in content):
        return None
    return content.split("#", 1)[0]


def _first_segment(token: str) -> str:
    return token.removeprefix("./").split("/", 1)[0]


def _names_no_file(token: str) -> bool:
    if not token or _SCHEME.match(token):
        return True
    if "..." in token or "\N{HORIZONTAL ELLIPSIS}" in token or _PLACEHOLDER_CHARS.intersection(token):
        return True
    return "/" in token.removeprefix("./") and _HOST.match(_first_segment(token)) is not None


def reference_path(reference: Reference) -> str | None:
    """Return the file a code span or link may name, normalised to forward slashes, or None when it names none.

    The text must have no whitespace or leading ``#``; links lose their ``#fragment`` and ``?query``
    and are URL-decoded; code spans lose a ``#fragment``, and a span that is one ``NAME=value``
    assignment is judged by its value. A token that starts with a known scheme (``tel:``, ``mailto:``,
    ``vscode:`` and the like) names no file, and that is decided before the ``:line`` suffix is dropped,
    so ``tel:5550100`` is not read as the file ``tel`` while ``Makefile:12`` names ``Makefile``. What then remains has a trailing ``:line``
    or ``:line:column`` and a pytest ``::test`` suffix dropped, and names no file when it starts with a
    URL scheme such as ``https:`` (a single drive letter is not a scheme), holds a glob or placeholder
    character or ``...`` or ``…``, or a ``/`` follows a first segment that is a host name such as
    ``github.com``. A first segment with no ``/`` after it is a file, so ``deploy.sh`` and
    ``example.com`` name files.

    Args:
        reference: A reference from :func:`rigcheck.parse.markdown.find_references`.

    Returns:
        The normalised path, or None for fence lines and anything that names no file.
    """
    if reference.source == "link":
        token = _link_target(reference.raw)
    elif reference.source == "span":
        token = _span_target(reference.raw)
    else:
        return None
    if token is None:
        return None
    head = token.split("::", 1)[0]
    scheme = _SCHEME.match(head)
    if scheme is not None and scheme.group(0)[:-1].lower() in _KNOWN_SCHEMES:
        return None
    token = _LOCATION.sub("", head).replace("\\", "/")
    return None if _names_no_file(token) else token


def path_candidate(reference: Reference) -> str | None:
    """Return the repository path a code span or link names, or None when it names none.

    A candidate is a :func:`reference_path` that also contains ``/`` (or starts with ``./`` or ``../``),
    is not a bare absolute path or drive-letter path, and whose first segment is not a build-output
    folder (``bin``, ``node_modules`` and the like). ``~/`` paths are candidates.

    Args:
        reference: A reference from :func:`rigcheck.parse.markdown.find_references`.

    Returns:
        The normalised path, or None for fence lines and anything that is not a checkable path.
    """
    token = reference_path(reference)
    if token is None or "/" not in token or token.startswith("/") or _DRIVE.match(token):
        return None
    return None if _first_segment(token) in SKIP_DIRS else token


def _inside(path: Path, root: Path) -> bool:
    return Path(path_key(path)).is_relative_to(Path(path_key(root)))


def _resolved(base: Path, token: str) -> Path:
    return Path(os.path.normpath(base / token))


def path_bases(token: str, directory: Path, root: Path) -> list[Path]:
    """Return where a relative path may point, beside its file and at the repo root, keeping only places inside the repo.

    Args:
        token: A relative path from :func:`path_candidate`.
        directory: The folder of the file that names the path.
        root: The repository root.

    Returns:
        The normalised candidates inside ``root``; empty when every reading leaves the repository.
    """
    return [path for path in (_resolved(directory, token), _resolved(root, token)) if _inside(path, root)]


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _stale(paths: list[Path]) -> bool:
    """True when no path exists but at least one path's parent folder does, so only the leaf is gone."""
    return not any(_exists(path) for path in paths) and any(_exists(path.parent) for path in paths)


def _missing_path_message(rig: Rig, artifact: Artifact, reference: Reference, token: str) -> str | None:
    """Return the message for a path that names no file, or None when it exists or is not checkable."""
    if token.startswith("~/"):
        return f"{reference.raw} does not exist in the home folder" if _stale([_resolved(rig.home, token[2:])]) else None
    if artifact.layer is not Layer.REPO:
        return None
    bases = path_bases(token, artifact.path.parent, rig.repo_root)
    if bases:
        return f"{reference.raw} does not exist (looked beside {artifact.path.name} and at the repo root)" if _stale(bases) else None
    if token.startswith("../") and _stale([_resolved(artifact.path.parent, token)]):
        return f"{reference.raw} does not exist (looked beside {artifact.path.name}, outside the repo)"
    return None


@rule(
    "reference-path-missing",
    "core",
    Severity.WARN,
    "Update or remove the path: agents follow the paths an instruction file names, so a stale one sends them looking for a file that is gone.",
    _EVIDENCE,
)
def reference_path_missing(rig: Rig) -> Iterator[Finding]:
    """A path in a code span or link names no file or folder."""
    for artifact in _scanned(rig):
        for reference in _references(rig, artifact):
            token = path_candidate(reference)
            message = _missing_path_message(rig, artifact, reference, token) if token is not None else None
            if message is not None:
                yield emit("reference-path-missing", artifact, message, reference.line)


_SHELL_PARTS = re.compile(r"""'[^']*'|"[^"]*"|&&|\|\||[;|]|[^'"&|;]+|.""")
_SEPARATORS = ("&&", "||", ";", "|")
_RUNNERS = {("npm", "run"), ("npm", "run-script"), ("pnpm", "run")}
_REDIRECTING_FLAGS = (
    "-C",
    "--directory",
    "--working-directory",
    "-f",
    "--file",
    "--justfile",
    "--makefile",
    "-w",
    "--workspace",
    "--filter",
    "--prefix",
)
_SHELL_LANGS = frozenset({"", "sh", "bash", "zsh", "shell", "console", "terminal", "pwsh", "powershell", "ps1", "cmd", "bat", "just", "make"})
_JUST_INCLUDE = re.compile(r"^(?:import|mod)\??\s")
_MAKE_INCLUDE = re.compile(r"^(?:include|-include|sinclude)\s")
_JUST_PARAMETER = r"""[+*$]?[A-Za-z_][A-Za-z0-9_-]*(?:=(?:'[^']*'|"[^"]*"|`[^`]*`|[^\s:'"`]+))?"""
_JUST_RECIPE = re.compile(rf"^@?([A-Za-z_][A-Za-z0-9_-]*)(?:\s+{_JUST_PARAMETER})*\s*:(?!=)")
_JUST_ALIAS = re.compile(r"^alias\s+([A-Za-z_][A-Za-z0-9_-]*)\s*:=")
_MAKE_TARGETS = re.compile(r"^([A-Za-z0-9_./-]+(?:\s+[A-Za-z0-9_./-]+)*)\s*::?(?![:=])")
_MAKE_ASSIGNMENT = re.compile(r"^[^:#=]*?(?:::=|:::=|:=|\?=|\+=|!=|=)")
_MANIFESTS = {
    "npm": ("package.json",),
    "just": ("justfile", "Justfile", ".justfile"),
    "make": ("Makefile", "makefile", "GNUmakefile"),
}
_KINDS = {"npm": "script", "just": "recipe", "make": "target"}


def _segments(raw: str) -> list[str]:
    """Split shell text on ``&&``, ``||``, ``;`` and ``|`` outside single and double quotes."""
    segments = [""]
    for part in _SHELL_PARTS.findall(raw):
        if part in _SEPARATORS:
            segments.append("")
        else:
            segments[-1] += part
    return segments


def _redirected(tool: str, words: list[str]) -> bool:
    if tool == "just" and "-d" in words:
        return True
    return any(word.startswith(_REDIRECTING_FLAGS) for word in words)


def _command(words: list[str]) -> tuple[str, list[str]] | None:
    if len(words) >= 2 and (words[0], words[1]) in _RUNNERS:
        return f"{words[0]} {words[1]}", words[2:]
    if words and words[0] in ("just", "make"):
        return words[0], words[1:]
    return None


def _first_name(arguments: list[str]) -> str | None:
    """Return the first word that is not an assignment, or None when a flag comes before it."""
    for word in arguments:
        if word.startswith("-"):
            return None
        if "=" not in word:
            return word
    return None


def _invocation(segment: str) -> tuple[str, str] | None:
    words = segment.split()
    command = _command(words)
    if command is None or _redirected(command[0], words):
        return None
    name = _first_name(command[1])
    return (command[0], name) if name is not None else None


def invocations(raw: str) -> list[tuple[str, str]]:
    """Return the package-script, just-recipe and make-target invocations in a line of shell.

    The text splits into segments on ``&&``, ``||``, ``;`` and ``|`` outside quotes. A segment is an
    invocation when its first words are ``npm run``, ``npm run-script``, ``pnpm run``, ``just`` or
    ``make``; the name is the first following word that is not an assignment. Invocations with a flag
    before the name, or with a flag that points elsewhere (``-C``, ``--directory``, ``--workspace``
    and the like), and every invocation after a ``cd``, are skipped.

    Args:
        raw: A code span's content or one code block line.

    Returns:
        ``(tool, name)`` pairs in order, with tool such as ``npm run``, ``just`` or ``make``.
    """
    found: list[tuple[str, str]] = []
    for segment in _segments(raw):
        if segment.split()[:1] == ["cd"]:
            break
        invocation = _invocation(segment)
        if invocation is not None:
            found.append(invocation)
    return found


def justfile_names(text: str) -> set[str]:
    """Return the recipe and alias names a justfile defines.

    Args:
        text: The justfile's content.

    Returns:
        Names of recipes (lines at column 0 ending their header with ``:``, not ``:=``) and aliases.
    """
    names: set[str] = set()
    for line in text.splitlines():
        match = _JUST_ALIAS.match(line) or _JUST_RECIPE.match(line)
        if match is not None:
            names.add(match.group(1))
    return names


def makefile_names(text: str) -> set[str]:
    """Return the explicit target names a Makefile defines.

    Args:
        text: The Makefile's content.

    Returns:
        Names from rule lines at column 0, leaving out special targets (leading ``.``), pattern rules and variable targets.
    """
    names: set[str] = set()
    for line in text.splitlines():
        skipped = "%" in line or "$(" in line or _MAKE_ASSIGNMENT.match(line) is not None
        match = None if skipped else _MAKE_TARGETS.match(line)
        if match is not None:
            names.update(name for name in match.group(1).split() if not name.startswith("."))
    return names


def _package_scripts(text: str) -> set[str] | None:
    try:
        data = json.loads(text.removeprefix("\N{ZERO WIDTH NO-BREAK SPACE}"))
    except ValueError:
        return None
    scripts = data.get("scripts", {}) if isinstance(data, dict) else None
    return set(scripts) if isinstance(scripts, dict) else None


def _names(rig: Rig, family: str, manifest: Path) -> set[str] | None:
    text = rig.text(manifest)
    if family == "npm":
        return _package_scripts(text)
    include, parse = (_JUST_INCLUDE, justfile_names) if family == "just" else (_MAKE_INCLUDE, makefile_names)
    if any(include.match(line) for line in text.splitlines()):
        return None
    return parse(text)


def _nearest(directory: Path, root: Path, names: tuple[str, ...]) -> Path | None:
    if not _inside(directory, root):
        return None
    root_key = path_key(root)
    for folder in (directory, *directory.parents):
        found = next((folder / name for name in names if (folder / name).is_file()), None)
        if found is not None or path_key(folder) == root_key:
            return found
    return None


class _Manifests:
    """The nearest manifest for each tool family, looked up and parsed once per folder."""

    def __init__(self, rig: Rig) -> None:
        self._rig = rig
        self._cache: dict[tuple[str, str], tuple[Path, set[str]] | None] = {}

    @property
    def root(self) -> Path:
        """The repository root manifests are searched up to."""
        return self._rig.repo_root

    def lookup(self, family: str, directory: Path) -> tuple[Path, set[str]] | None:
        """Return the nearest usable manifest of ``family`` at or above ``directory`` with the names it defines, or None."""
        key = (family, path_key(directory))
        if key not in self._cache:
            manifest = _nearest(directory, self._rig.repo_root, _MANIFESTS[family])
            names = _names(self._rig, family, manifest) if manifest is not None else None
            self._cache[key] = (manifest, names) if manifest is not None and names is not None else None
        return self._cache[key]


def _missing_scripts(manifests: _Manifests, artifact: Artifact, reference: Reference) -> Iterator[str]:
    for tool, name in invocations(reference.raw):
        family = tool if tool in ("just", "make") else "npm"
        found = manifests.lookup(family, artifact.path.parent)
        if found is not None and name not in found[1]:
            where = Path(os.path.relpath(found[0], manifests.root)).as_posix()
            yield f"{tool} {name}: no such {_KINDS[family]} in {where}"


@rule(
    "reference-script-missing",
    "core",
    Severity.WARN,
    "Update or remove the command: the script, recipe or target it names is not defined in the nearest package.json, justfile or Makefile.",
    _EVIDENCE,
)
def reference_script_missing(rig: Rig) -> Iterator[Finding]:
    """A ``npm run``, ``just`` or ``make`` command names a script, recipe or target that is not defined."""
    manifests = _Manifests(rig)
    for artifact in _scanned(rig):
        if artifact.layer is not Layer.REPO:
            continue
        for reference in _references(rig, artifact):
            if reference.source == "link" or (reference.source == "fence" and reference.lang not in _SHELL_LANGS):
                continue
            for message in _missing_scripts(manifests, artifact, reference):
                yield emit("reference-script-missing", artifact, message, reference.line)
