"""Rules for skill folders (SKILL.md) and their bundled files, and the frontmatter rules skills share with commands."""

import os
import re
import weakref
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from rigcheck.discover import SKIP_DIRS, import_candidates, path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity
from rigcheck.parse.frontmatter import as_bool
from rigcheck.parse.markdown import Reference, find_references
from rigcheck.report.budget import LISTING_DETAIL_CHARS
from rigcheck.rules import emit, rule
from rigcheck.rules.components import KEYS, components, load, misplaced_fence, plugin_name, unknown_key_message, yaml_line, yaml_reason
from rigcheck.rules.components import tool_entries as _tool_entries
from rigcheck.rules.references import exists, inside, reference_path, resolved

LISTED_KINDS = (Kind.SKILL, Kind.COMMAND)
"""The artifact kinds whose frontmatter follows the skill format."""

_COMMAND_UNSUPPORTED = frozenset({"name", "paths"})
"""Skill keys a command file does not support; another rule reports them."""


@rule(
    "skill-frontmatter-misplaced",
    "core",
    Severity.ERROR,
    "Put the opening --- alone on line 1: nothing before it and no spaces around it.",
    ("official:SK1",),
)
def skill_frontmatter_misplaced(rig: Rig) -> Iterator[Finding]:
    """Frontmatter whose opening --- is not the file's first line."""
    for artifact in components(rig, LISTED_KINDS):
        misplaced = misplaced_fence(rig.text(artifact.path))
        if misplaced is not None:
            line, problem = misplaced
            message = f"{problem}, so Claude Code reads the whole file as content and no field is set"
            yield emit("skill-frontmatter-misplaced", artifact, message, line)


@rule(
    "skill-frontmatter-invalid",
    "core",
    Severity.ERROR,
    'Fix the YAML: quote values that hold ": " or start with a YAML indicator, save the file with LF line endings, and close the block with ---.',
    ("official:SK1",),
)
def skill_frontmatter_invalid(rig: Rig) -> Iterator[Finding]:
    """Frontmatter that Claude Code cannot parse, so the skill loads with no fields set."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.present and parsed.load_error is not None:
            error = parsed.load_error
            message = f"Claude Code rejects the frontmatter ({yaml_reason(error)}), so the skill loads with no fields set"
            yield emit("skill-frontmatter-invalid", artifact, message, yaml_line(error))


@rule(
    "skill-key-unknown",
    "core",
    Severity.WARN,
    "Rename the key to one Claude Code recognizes (the names are case- and hyphen-exact), or remove it.",
    ("official:SK2",),
)
def skill_key_unknown(rig: Rig) -> Iterator[Finding]:
    """A frontmatter key Claude Code does not recognize, so it is ignored."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        known = KEYS[artifact.kind]
        skipped = _COMMAND_UNSUPPORTED if artifact.kind is Kind.COMMAND else frozenset()
        for key in map(str, parsed.data):
            if key not in known and key not in skipped:
                message = unknown_key_message(key, known)
                yield emit("skill-key-unknown", artifact, message, parsed.key_lines.get(key, 1))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


@rule(
    "skill-description-missing",
    "core",
    Severity.WARN,
    "Add a description that says what the skill does and when to use it, key use case first.",
    ("official:SK4",),
)
def skill_description_missing(rig: Rig) -> Iterator[Finding]:
    """A skill or command with no description, so Claude matches it on its first line of content."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.present and parsed.data is None:
            continue
        data = parsed.data or {}
        if not _text(data.get("description")).strip():
            message = "no description, so Claude Code lists the first line of content instead"
            yield emit("skill-description-missing", artifact, message, 1)


@rule(
    "skill-description-truncated",
    "core",
    Severity.WARN,
    "Shorten the description and when_to_use, putting the key use case first so the cut falls on detail.",
    ("official:SK4",),
)
def skill_description_truncated(rig: Rig) -> Iterator[Finding]:
    """A description and when_to_use longer than the skill listing keeps."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        parts = (_text(parsed.data.get("description")), _text(parsed.data.get("when_to_use")))
        length = len(" ".join(part for part in parts if part))
        if length > LISTING_DETAIL_CHARS:
            line = parsed.key_lines.get("description", parsed.key_lines.get("when_to_use", 1))
            message = f"description and when_to_use run to {length} characters; the skill listing cuts them at {LISTING_DETAIL_CHARS}"
            yield emit("skill-description-truncated", artifact, message, line)


@rule(
    "skill-unreachable",
    "core",
    Severity.WARN,
    "Remove one of the two settings: keep disable-model-invocation for a skill only you run, or user-invocable: false for one only Claude runs.",
    ("official:SK19",),
)
def skill_unreachable(rig: Rig) -> Iterator[Finding]:
    """A skill hidden from both the user and Claude."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        data = parsed.data
        if data is None:
            continue
        if as_bool(data.get("user-invocable")) is False and as_bool(data.get("disable-model-invocation")) is True:
            message = "user-invocable is false and disable-model-invocation is true, so neither you nor Claude can invoke it"
            yield emit("skill-unreachable", artifact, message, parsed.key_lines.get("disable-model-invocation", 1))


def _accepted_names(artifact: Artifact, folder: str) -> set[str]:
    """Return the names that match the folder: the folder itself, and ``<plugin>:<folder>`` for a plugin skill."""
    names = {folder}
    plugin = plugin_name(artifact)
    if plugin is not None:
        names.add(f"{plugin}:{folder}")
    return names


@rule(
    "skill-name-mismatch",
    "core",
    Severity.WARN,
    "Make the name match the folder name: Claude Code invokes the skill by both, so a mismatch gives it two names.",
    ("official:SK8",),
)
def skill_name_mismatch(rig: Rig) -> Iterator[Finding]:
    """A skill whose name differs from its folder name."""
    for artifact in components(rig, (Kind.SKILL,)):
        parsed = load(rig, artifact)
        if parsed.data is None:
            continue
        name = _text(parsed.data.get("name"))
        folder = artifact.path.parent.name
        if name.strip() and name not in _accepted_names(artifact, folder):
            message = f'name "{name}" differs from the folder "{folder}", so the skill answers to two names'
            yield emit("skill-name-mismatch", artifact, message, parsed.key_lines.get("name", 1))


_RESERVED_WORDS = frozenset({"claude", "anthropic"})
"""Words the Agent Skills spec reserves in a skill name."""


def _reserved_word(name: str) -> str | None:
    """Return the first ``-``-separated part of ``name`` that, lowercased, is a reserved word."""
    return next((part for part in name.lower().split("-") if part in _RESERVED_WORDS), None)


@rule(
    "skill-name-reserved",
    "core",
    Severity.WARN,
    "Rename the skill without claude or anthropic, which the Agent Skills spec reserves.",
    ("official:SK8",),
)
def skill_name_reserved(rig: Rig) -> Iterator[Finding]:
    """A skill name that uses a reserved word."""
    for artifact in components(rig, (Kind.SKILL,)):
        parsed = load(rig, artifact)
        if parsed.data is None or artifact.layer is Layer.PLUGIN:
            continue
        lines = {artifact.path.parent.name: 1}
        name = _text(parsed.data.get("name"))
        if name.strip():
            lines[name] = parsed.key_lines.get("name", 1)
        for candidate, line in lines.items():
            word = _reserved_word(candidate)
            if word is not None:
                yield emit("skill-name-reserved", artifact, f'the name "{candidate}" uses the reserved word "{word}"', line)


@rule(
    "skill-fork-option-ignored",
    "core",
    Severity.WARN,
    "Add context: fork, or remove the key.",
    ("official:SK20",),
)
def skill_fork_option_ignored(rig: Rig) -> Iterator[Finding]:
    """A skill option that only works with context: fork, set without it."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        data = parsed.data
        if data is None or data.get("context") == "fork":
            continue
        agent = data.get("agent")
        ignored: list[str] = []
        if agent is not None and str(agent).strip():
            ignored.append("agent")
        if as_bool(data.get("background")) is True:
            ignored.append("background")
        for key in ignored:
            message = f'"{key}" is set but context is not fork, so Claude Code ignores it'
            yield emit("skill-fork-option-ignored", artifact, message, parsed.key_lines.get(key, 1))


_BROAD_TOOL = re.compile(r"^(Bash|Write|Edit)(\(\s*(\*|:\*|\*\*|/\*\*|\./\*\*)?\s*\))?$")
"""An allowed-tools entry naming Bash, Write or Edit with no specifier, or with an empty, wildcard or whole-tree one."""


@rule(
    "skill-allowed-tools-broad",
    "core",
    Severity.WARN,
    "Narrow the grant to what the skill needs, such as Bash(git status:*) or Edit(docs/**).",
    ("official:SK21",),
)
def skill_allowed_tools_broad(rig: Rig) -> Iterator[Finding]:
    """An allowed-tools entry that grants Bash, Write or Edit with no narrowing specifier."""
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        if parsed.data is None or artifact.layer is not Layer.REPO:
            continue
        for entry in _tool_entries(parsed.data.get("allowed-tools")):
            if entry == "*" or _BROAD_TOOL.match(entry):
                message = f'allowed-tools grants "{entry}" with no narrowing specifier, and workspace trust does not gate this field'
                yield emit("skill-allowed-tools-broad", artifact, message, parsed.key_lines.get("allowed-tools", 1))


_SK11 = ("official:SK11",)
_SKILL_FILE = "SKILL.md"
_VENV_MARKER = "pyvenv.cfg"
_TOP_LEVEL_EXTRAS = ("LICENSE", "NOTICE", "README", "UPSTREAM", "CHANGELOG")
"""Name prefixes of top-level files a skill folder carries for people, not for Claude."""

_AGENT_METADATA = "agents"
"""The top-level folder of other agents' skill metadata (Codex's ``openai.yaml``), which Claude Code does not read."""

_AGENT_METADATA_SUFFIXES = (".yaml", ".yml")
_LINKED = ("link", "image")
"""Reference sources that point at a file: Markdown links and images."""

_PLACEHOLDER = re.compile(r"(?:\$(?:\{|%7[Bb])CLAUDE_SKILL_DIR(?:\}|%7[Dd])|\$CLAUDE_SKILL_DIR|(?:\{|%7[Bb])baseDir(?:\}|%7[Dd]))(?:/|\\|%5[Cc])")
"""A skill-folder placeholder at the start of a path, as written or URL-encoded; the rest resolves against the skill folder."""

_CODE_PREFIX = re.compile(
    r"(?:\$\{CLAUDE_SKILL_DIR\}|\$CLAUDE_SKILL_DIR|\{baseDir\})/"
    r"|(?i:<[A-Za-z0-9_-]*skill[A-Za-z0-9_-]*(?:dir|directory|path|folder|root)>)/"
    r"|(?<![\w.\-/])\./"
)
"""Prefixes that may stand before a skill-relative path in code text; replaced by a space before matching.

That is a skill-folder placeholder (``${CLAUDE_SKILL_DIR}/``, ``$CLAUDE_SKILL_DIR/`` or ``{baseDir}/``), an
angle-bracket placeholder naming the skill folder such as ``<skill-dir>/`` or ``<SKILL_ROOT>/``, or a leading ``./``.
"""


def _written(reference: Reference) -> str:
    """The reference as the author wrote it: link and image targets URL-decoded."""
    return unquote(reference.raw) if reference.source in _LINKED else reference.raw


@dataclass(frozen=True)
class _Link:
    """A link, image or code span in a skill file that names a path, with the places it may point.

    ``target`` is the first candidate that exists, or the first candidate when none does.
    """

    source: Path
    reference: Reference
    candidates: tuple[Path, ...]
    target: Path
    exists: bool

    @property
    def named(self) -> tuple[Path, ...]:
        """The paths this reference names: the target it resolved to, or every candidate when none exists."""
        return (self.target,) if self.exists else self.candidates

    @property
    def shown(self) -> str:
        """The reference as written."""
        return _written(self.reference)


@dataclass(frozen=True)
class _Names:
    """What SKILL.md and the files it points at name: resolved paths, and code span, block and agent-metadata text."""

    paths: frozenset[str]
    code: str


@dataclass(frozen=True)
class _Bundle:
    """A skill's SKILL.md, the links of it and of the bundled Markdown files it links, and what they all name."""

    artifact: Artifact
    top: list[_Link]
    nested: list[_Link]
    files: list[Path]
    names: _Names

    @property
    def root(self) -> Path:
        """The skill folder."""
        return self.artifact.path.parent

    @property
    def links(self) -> list[_Link]:
        """The links of SKILL.md and of the bundled Markdown files it links."""
        return self.top + self.nested


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, ValueError):
        return False


def _token(reference: Reference) -> tuple[str, bool] | None:
    r"""Return the path a link, image or code span names, and whether a skill-folder placeholder anchors it.

    Paths starting with ``/`` or ``\\`` are not skill paths; rejecting them here keeps ``//host/share``
    from reaching the filesystem, where Windows would look the host up on the network.
    """
    placeholder = _PLACEHOLDER.match(reference.raw)
    source = "link" if reference.source in _LINKED else reference.source
    raw = reference.raw[placeholder.end() :] if placeholder is not None else reference.raw
    token = reference_path(replace(reference, raw=raw, source=source))
    if token is None or token.startswith("/"):
        return None
    return token, placeholder is not None


def _candidates(rig: Rig, source: Path, root: Path, named: tuple[str, bool]) -> tuple[Path, ...]:
    """Return where a named path may point: the skill folder for a placeholder, else beside the file, then the skill folder."""
    token, anchored = named
    if anchored:
        return (resolved(root, token),)
    if token.startswith("~/"):
        return (resolved(rig.home, token[2:]),)
    beside, at_root = resolved(source.parent, token), resolved(root, token)
    return (beside,) if path_key(beside) == path_key(at_root) else (beside, at_root)


def _link(rig: Rig, source: Path, root: Path, reference: Reference) -> _Link | None:
    """Resolve a reference in ``source``, a file of the skill at ``root``; None when it names no path."""
    named = _token(reference)
    if named is None:
        return None
    candidates = _candidates(rig, source, root, named)
    found = next((candidate for candidate in candidates if exists(candidate)), None)
    return _Link(source, reference, candidates, found or candidates[0], found is not None)


class _Parsed:
    """The references of each skill file, parsed once."""

    def __init__(self, rig: Rig, root: Path) -> None:
        self._rig = rig
        self._root = root
        self._references: dict[str, list[Reference]] = {}
        self._links: dict[tuple[str, Reference], _Link | None] = {}

    def references(self, path: Path) -> list[Reference]:
        """Return the code spans, links, images and code block lines of ``path``."""
        key = path_key(path)
        if key not in self._references:
            self._references[key] = find_references(self._rig.text(path))
        return self._references[key]

    def link(self, path: Path, reference: Reference) -> _Link | None:
        """Resolve ``reference``, found in ``path``, once."""
        key = (path_key(path), reference)
        if key not in self._links:
            self._links[key] = _link(self._rig, path, self._root, reference)
        return self._links[key]

    def links(self, path: Path, sources: tuple[str, ...]) -> list[_Link]:
        """Return the references of ``path`` from ``sources`` that name a path, resolved."""
        found = (self.link(path, reference) for reference in self.references(path) if reference.source in sources)
        return [link for link in found if link is not None]


def _is_bundled_markdown(link: _Link, root: Path) -> bool:
    """True when ``link`` names an existing ``.md`` file inside the skill folder that is not a SKILL.md."""
    target = link.target
    return target.suffix.lower() == ".md" and target.name != _SKILL_FILE and inside(target, root) and _is_file(target)


def _bundled_markdown(links: list[_Link], root: Path) -> list[Path]:
    """Return the distinct bundled ``.md`` files ``links`` name, in order."""
    found: dict[str, Path] = {}
    for link in links:
        if link.exists and _is_bundled_markdown(link, root):
            found.setdefault(path_key(link.target), link.target)
    return list(found.values())


def _imports(text: str) -> list[Reference]:
    """Return the file's ``@path`` imports as code-span references, so they resolve like one."""
    if "@" not in text:
        return []
    return [Reference(line=found.line, raw=found.raw, source="span", lang="") for found in import_candidates(text)]


def _agent_metadata(rig: Rig, root: Path) -> list[str]:
    """Return the text of the YAML files in the skill's top-level ``agents`` folder."""
    folder = root / _AGENT_METADATA
    try:
        files = sorted(path for path in folder.iterdir() if path.suffix.lower() in _AGENT_METADATA_SUFFIXES and path.is_file())
    except OSError:
        return []
    return [rig.text(path) for path in files]


def _code_text(texts: list[str], root: Path) -> str:
    """Join code text with forward slashes, turning into spaces what may stand before a skill-relative path.

    That is a skill-folder placeholder, a leading ``./``, or a path through the skill's own folder
    such as ``~/.claude/skills/<name>/``.
    """
    own_folder = re.compile(rf"[^\s`'\"()]*skills/{re.escape(root.name)}/")
    return "\n".join(own_folder.sub(" ", _CODE_PREFIX.sub(" ", text.replace("\\", "/"))) for text in texts)


def _basenames(files: list[Path], root: Path) -> frozenset[str]:
    """Return the lower-cased names of ``files`` and of the folders between them and ``root``."""
    names: set[str] = set()
    for path in files:
        relative = path.relative_to(root)
        names.update(part.lower() for part in relative.parts)
    return frozenset(names)


def _may_name(reference: Reference, basenames: frozenset[str]) -> bool:
    """False for a code span whose last path segment is no bundled file or folder name, so resolving it is wasted work."""
    if reference.source != "span":
        return reference.source != "fence"
    named = _token(reference)
    return named is not None and named[0].rstrip("/").rsplit("/", 1)[-1].lower() in basenames


def _names(rig: Rig, parsed: _Parsed, root: Path, sources: list[Path], files: list[Path]) -> _Names:
    paths: set[str] = set()
    code = _agent_metadata(rig, root)
    basenames = _basenames(files, root)
    for source in sources:
        references = parsed.references(source)
        code.extend(reference.raw for reference in references if reference.source in ("span", "fence"))
        for reference in (*references, *_imports(rig.text(source))):
            link = parsed.link(source, reference) if _may_name(reference, basenames) else None
            if link is not None:
                paths.update(path_key(path) for path in link.named)
    return _Names(frozenset(paths), _code_text(code, root))


def _bundle(rig: Rig, artifact: Artifact) -> _Bundle:
    root, skill = artifact.path.parent, artifact.path
    parsed = _Parsed(rig, root)
    top = parsed.links(skill, _LINKED)
    depth_one = _bundled_markdown(top, root)
    nested = [link for path in depth_one for link in parsed.links(path, _LINKED)]
    spanned = _bundled_markdown(parsed.links(skill, ("span",)), root)
    sources = list({path_key(path): path for path in (skill, *depth_one, *spanned)}.values())
    files = list(_bundled_files(rig, artifact))
    names = _names(rig, parsed, root, sources, files) if files else _Names(frozenset(), "")
    return _Bundle(artifact, top, nested, files, names)


_BUNDLES: dict[int, tuple["weakref.ref[Rig]", list[_Bundle]]] = {}
"""Each live rig's skill bundles, built once and shared by the four rules below."""


def _bundles(rig: Rig) -> list[_Bundle]:
    entry = _BUNDLES.get(id(rig))
    if entry is not None and entry[0]() is rig:
        return entry[1]
    bundles = [_bundle(rig, artifact) for artifact in components(rig, (Kind.SKILL,))]
    _BUNDLES[id(rig)] = (weakref.ref(rig), bundles)
    weakref.finalize(rig, _BUNDLES.pop, id(rig), None)
    return bundles


def _at(finding: Finding, path: Path) -> Finding:
    """Move ``finding`` to ``path``, a file of the skill that may not be its SKILL.md."""
    return replace(finding, path=path)


def _unique(findings: Iterable[Finding]) -> Iterator[Finding]:
    """Yield each distinct finding once."""
    seen: set[Finding] = set()
    for finding in findings:
        if finding not in seen:
            seen.add(finding)
            yield finding


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def _broken(bundle: _Bundle) -> Iterator[Finding]:
    for link in bundle.links:
        if not link.exists:
            finding = emit("skill-link-broken", bundle.artifact, f"the link {link.shown} points at no file", link.reference.line)
            yield _at(finding, link.source)


@rule(
    "skill-link-broken",
    "core",
    Severity.ERROR,
    "Fix the link to point at a file in the skill folder, or remove it.",
    _SK11,
)
def skill_link_broken(rig: Rig) -> Iterator[Finding]:
    """A link or image in SKILL.md, or in a file it links, points at no file."""
    for bundle in _bundles(rig):
        yield from _unique(_broken(bundle))


def _outside(bundle: _Bundle) -> Iterator[Finding]:
    for link in bundle.links:
        if link.exists and not inside(link.target, bundle.root):
            message = f"the link {link.shown} points outside the skill folder"
            yield _at(emit("skill-link-outside", bundle.artifact, message, link.reference.line), link.source)


@rule(
    "skill-link-outside",
    "core",
    Severity.WARN,
    "Move the file into the skill folder and link it there: a skill that is copied or installed carries only its own folder.",
    _SK11,
)
def skill_link_outside(rig: Rig) -> Iterator[Finding]:
    """A link or image in SKILL.md, or in a file it links, points outside the skill folder."""
    for bundle in _bundles(rig):
        yield from _unique(_outside(bundle))


def _too_deep(bundle: _Bundle) -> Iterator[Finding]:
    linked = {path_key(link.target) for link in bundle.top}
    for link in bundle.nested:
        if not link.exists or path_key(link.target) in linked or not _is_bundled_markdown(link, bundle.root):
            continue
        source, target = _relative(link.source, bundle.root), _relative(link.target, bundle.root)
        message = f"{source} links {link.shown}, which SKILL.md does not link, so {target} sits two levels deep"
        yield _at(emit("skill-link-too-deep", bundle.artifact, message, link.reference.line), link.source)


@rule(
    "skill-link-too-deep",
    "core",
    Severity.WARN,
    "Link the file from SKILL.md as well, or fold it into the file that links it: keep bundled files one level deep.",
    _SK11,
)
def skill_link_too_deep(rig: Rig) -> Iterator[Finding]:
    """A bundled Markdown file reachable only through another bundled file, two levels down from SKILL.md."""
    for bundle in _bundles(rig):
        yield from _unique(_too_deep(bundle))


@lru_cache(maxsize=4096)
def _mention(needle: str) -> re.Pattern[str]:
    """Match ``needle`` in code text where no path character precedes it and, for a file, none follows it."""
    tail = "" if needle.endswith("/") else r"(?![\w\-])"
    return re.compile(rf"(?<![\w.\-/]){re.escape(needle)}{tail}")


def _named(path: Path, root: Path, names: _Names) -> bool:
    """True when ``path``, or a folder above it inside the skill, is a named path or appears in code text."""
    relative = path.relative_to(root)
    folders = [parent for parent in relative.parents if parent != Path()]
    if any(path_key(root / candidate) in names.paths for candidate in (relative, *folders)):
        return True
    needles = [relative.as_posix(), *(f"{folder.as_posix()}/" for folder in folders)]
    return bool(names.code) and any(_mention(needle).search(names.code) for needle in needles)


def _kept_folder(directory: Path, name: str, top: bool) -> bool:
    """False for folders the walk skips: hidden, build output, bytecode, agent metadata, links, venvs and nested skills."""
    if name.startswith(".") or name in SKIP_DIRS or name == "__pycache__" or (top and name == _AGENT_METADATA):
        return False
    folder = directory / name
    if folder.is_junction() or folder.is_symlink():
        return False
    return not _is_file(folder / _SKILL_FILE) and not _is_file(folder / _VENV_MARKER)


def _kept_file(name: str, top: bool) -> bool:
    if name.startswith(".") or name.endswith(".pyc"):
        return False
    return not top or (name != _SKILL_FILE and not name.upper().startswith(_TOP_LEVEL_EXTRAS))


def _ignored(rig: Rig, artifact: Artifact, path: Path) -> bool:
    """True when ``path`` is a repository file git ignores."""
    files = rig.project_files if artifact.layer is Layer.REPO else None
    if files is None:
        return False
    try:
        relative = path.relative_to(rig.repo_root)
    except ValueError:
        return False
    return relative.as_posix() not in files


def _bundled_files(rig: Rig, artifact: Artifact) -> Iterator[Path]:
    """Yield the skill folder's regular files that Claude may be meant to read or run."""
    root = artifact.path.parent
    for directory, folders, files in os.walk(root):
        here = Path(directory)
        top = here == root
        folders[:] = [name for name in folders if _kept_folder(here, name, top)]
        for name in files:
            path = here / name
            if _kept_file(name, top) and _is_file(path) and not _ignored(rig, artifact, path):
                yield path


def _unreferenced(bundle: _Bundle) -> Iterator[Finding]:
    for path in bundle.files:
        if not _named(path, bundle.root, bundle.names):
            message = f"{_relative(path, bundle.root)} is not named by SKILL.md or a file it links, so Claude has no pointer to it"
            yield _at(emit("skill-file-unreferenced", bundle.artifact, message, None), path)


@rule(
    "skill-file-unreferenced",
    "core",
    Severity.INFO,
    "Name the file from SKILL.md with when to read or run it, or delete it if nothing uses it.",
    _SK11,
)
def skill_file_unreferenced(rig: Rig) -> Iterator[Finding]:
    """A file bundled in a skill folder that neither SKILL.md nor a file it links names."""
    for bundle in _bundles(rig):
        yield from _unique(_unreferenced(bundle))
