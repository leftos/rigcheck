"""Effective-setup discovery: builds the Rig from the repo, memory, user and plugin layers."""

import json
import os
import re
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from rigcheck.model import Artifact, Kind, Layer, LoadClass, McpScope, Rig, UserMcpServer, git_output, unc_link_target
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import Import, find_imports, strip_html_comments

MAX_BYTES = 4 * 1024 * 1024
"""Claude Code skips instruction files larger than this."""

MEMORY_INDEX_LINES = 200
"""Claude Code loads only the first 200 lines of MEMORY.md (official MM1)."""

MEMORY_INDEX_BYTES = 25_000
"""Claude Code loads only the first 25 KB of MEMORY.md's first 200 lines (official MM1)."""

MAX_IMPORT_DEPTH = 4
"""Claude Code follows ``@path`` imports at most this many hops."""

CLAUDE_FAMILY = ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")
AGENTS_MD = "AGENTS.md"
IGNORED_BY_CLAUDE = ("AGENTS.local.md", "AGENTS.override.md")
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "bin", "obj", "dist", "build", ".tmp"})
DOC_ROOTS = ("docs", "Docs")
"""Top-level repo folders whose Markdown files are discovered as docs."""

_CLAUDE_DIR_FILES = (
    ("skills/*/SKILL.md", Kind.SKILL, LoadClass.ON_INVOKE),
    ("commands/**/*.md", Kind.COMMAND, LoadClass.ON_INVOKE),
    ("agents/**/*.md", Kind.AGENT, LoadClass.ON_INVOKE),
    ("output-styles/*.md", Kind.OUTPUT_STYLE, LoadClass.ON_DEMAND),
    ("settings.json", Kind.SETTINGS, LoadClass.CONFIG),
    ("settings.local.json", Kind.SETTINGS, LoadClass.CONFIG),
)
_PLUGIN_FILES = (
    ("skills/*/SKILL.md", Kind.SKILL, LoadClass.ON_INVOKE),
    ("agents/*.md", Kind.AGENT, LoadClass.ON_INVOKE),
    ("commands/*.md", Kind.COMMAND, LoadClass.ON_INVOKE),
    ("output-styles/*.md", Kind.OUTPUT_STYLE, LoadClass.ON_DEMAND),
    ("hooks/hooks.json", Kind.HOOKS_CONFIG, LoadClass.CONFIG),
    (".mcp.json", Kind.MCP_CONFIG, LoadClass.CONFIG),
    (".claude-plugin/plugin.json", Kind.PLUGIN_MANIFEST, LoadClass.CONFIG),
)


def path_key(path: Path) -> str:
    """Return a comparison key for ``path``: normalized, and case-folded where the OS is case-insensitive."""
    return os.path.normcase(os.path.normpath(path))


def resolve_import(raw: str, importer: Path, home: Path) -> Path:
    """Resolve an ``@path`` import the way Claude Code does.

    Args:
        raw: The import as written, without the ``@``.
        importer: The file containing the import.
        home: The home directory ``~`` expands to.

    Returns:
        The normalized path; relative imports resolve against the importing file's directory.
    """
    if raw.startswith("~/"):
        resolved = home / raw[2:]
    elif Path(raw).is_absolute() or raw.startswith("/"):
        resolved = Path(raw)
    else:
        resolved = importer.parent / raw
    return Path(os.path.normpath(resolved))


def import_candidates(text: str) -> list[Import]:
    """Return the imports Claude Code would expand in ``text`` (block HTML comments removed first)."""
    return find_imports(strip_html_comments(text))


def resolved_imports(rig: Rig, artifact: Artifact) -> list[tuple[Import, Path]]:
    """Return each import in ``artifact`` with the path it resolves to."""
    return [(item, resolve_import(item.raw, artifact.path, rig.home)) for item in import_candidates(rig.text(artifact.path))]


def is_file_like(path: Path) -> bool:
    """Return True for a regular file, or for a network-path symlink (never followed, to avoid network access)."""
    return unc_link_target(path) is not None or path.is_file()


def file_size(path: Path) -> int:
    """Return a file's size in bytes, or 0 for a network-path symlink (never followed) or a file that cannot be read.

    Args:
        path: The file to measure.

    Returns:
        The size on disk in bytes.
    """
    if unc_link_target(path) is not None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def encode_project(path: Path) -> str:
    r"""Encode a project path the way Claude Code names its ``~/.claude/projects`` folder (``D:\yaat`` → ``D--yaat``)."""
    return re.sub(r"[^A-Za-z0-9-]", "-", str(path))


def memory_dir(repo_root: Path, home: Path) -> Path:
    """Return the auto-memory folder Claude Code uses for ``repo_root``."""
    return home / ".claude" / "projects" / encode_project(repo_root) / "memory"


def _loads(path: Path) -> bool:
    if unc_link_target(path) is not None:
        return False
    try:
        return path.stat().st_size <= MAX_BYTES
    except OSError:
        return False


def _load_class(path: Path) -> LoadClass:
    return LoadClass.EVERY_TURN if _loads(path) else LoadClass.NOT_LOADED


def _is_below(path: Path, ancestor: Path) -> bool:
    child, parent = Path(path_key(path)), Path(path_key(ancestor))
    return child != parent and child.is_relative_to(parent)


@dataclass
class _Builder:
    target: Path
    repo_root: Path
    home: Path
    in_git: bool
    home_target: bool
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def add(self, artifact: Artifact) -> None:
        self.artifacts.setdefault(path_key(artifact.path), artifact)

    @cached_property
    def repo_files(self) -> list[str] | None:
        """The repo's tracked and untracked-but-not-ignored files as repo-relative POSIX paths, listed once; None when git fails."""
        output = git_output(self.repo_root, "ls-files", "-co", "--exclude-standard", "-z")
        if output is None:
            self.problems.append(f"git ls-files failed in {self.repo_root}")
            return None
        return [name for name in output.split("\0") if name]

    def read(self, path: Path) -> str | None:
        try:
            return path.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            self.problems.append(f"cannot read {path}: {exc.strerror or exc}")
            return None

    def read_json(self, path: Path) -> Any:
        if not path.is_file():
            return None
        text = self.read(path)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            self.problems.append(f"malformed JSON in {path}: {exc}")
            return None

    def add_glob(self, base: Path, patterns: tuple[tuple[str, Kind, LoadClass], ...], layer: Layer, plugin: str | None) -> None:
        for pattern, kind, load_class in patterns:
            for path in sorted(base.glob(pattern)):
                if is_file_like(path):
                    self.add(Artifact(path, kind, layer, load_class, plugin=plugin))


def _chain_dirs(target: Path, home: Path) -> list[Path]:
    """Directories from the filesystem root (or ``home``, when target is inside it) down to ``target``."""
    dirs = []
    home_key = path_key(home)
    for directory in (target, *target.parents):
        dirs.append(directory)
        if path_key(directory) == home_key:
            break
    return list(reversed(dirs))


def _chain_files(b: _Builder, names: tuple[str, ...]) -> list[Path]:
    user_file = path_key(b.home / ".claude" / "CLAUDE.md")
    found = []
    for directory in _chain_dirs(b.target, b.home):
        for name in names:
            path = directory / name
            if path.exists(follow_symlinks=False) and path_key(path) != user_file:
                found.append(path)
    return found


def _add_chain(b: _Builder) -> tuple[list[Artifact], set[str]]:
    """Add the always-on instruction files; return the loaded roots and the shadowed AGENTS.md keys."""
    chain = [] if b.home_target else _chain_files(b, (*CLAUDE_FAMILY, AGENTS_MD))
    has_claude = any(path.name != AGENTS_MD for path in chain)
    roots: list[Artifact] = []
    shadowed: set[str] = set()
    user_file = b.home / ".claude" / "CLAUDE.md"
    if user_file.exists(follow_symlinks=False):
        roots.append(Artifact(user_file, Kind.INSTRUCTIONS, Layer.USER, _load_class(user_file)))
    for path in chain:
        if has_claude and path.name == AGENTS_MD:
            shadowed.add(path_key(path))
            roots.append(Artifact(path, Kind.INSTRUCTIONS, Layer.REPO, LoadClass.NOT_LOADED))
        else:
            roots.append(Artifact(path, Kind.INSTRUCTIONS, Layer.REPO, _load_class(path)))
    for path in () if b.home_target else _chain_files(b, IGNORED_BY_CLAUDE):
        b.add(Artifact(path, Kind.INSTRUCTIONS, Layer.REPO, LoadClass.NOT_LOADED))
    for artifact in roots:
        b.add(artifact)
    return roots, shadowed


def _add_import(b: _Builder, importer: Artifact, path: Path, shadowed: set[str]) -> Artifact | None:
    key = path_key(path)
    if (key in b.artifacts and key not in shadowed) or not is_file_like(path):
        return None
    depth = importer.import_depth + 1
    load_class = importer.load_class if depth <= MAX_IMPORT_DEPTH and _loads(path) else LoadClass.NOT_LOADED
    artifact = Artifact(path, Kind.INSTRUCTIONS, importer.layer, load_class, imported_from=importer.path, import_depth=depth)
    b.artifacts[key] = artifact
    shadowed.discard(key)
    return artifact


def _follow_imports(b: _Builder, roots: list[Artifact], shadowed: set[str]) -> None:
    """Breadth-first over imports, so each file is recorded at its shortest import depth."""
    queue = deque(root for root in roots if root.load_class is not LoadClass.NOT_LOADED)
    while queue:
        importer = queue.popleft()
        text = b.read(importer.path)
        if text is None:
            continue
        for item in import_candidates(text):
            added = _add_import(b, importer, resolve_import(item.raw, importer.path, b.home), shadowed)
            if added is not None and added.load_class is not LoadClass.NOT_LOADED:
                queue.append(added)


def _walk_claude_md(b: _Builder) -> Iterator[Path]:
    def on_error(error: OSError) -> None:
        b.problems.append(f"cannot list {error.filename}: {error.strerror or error}")

    for directory, subdirs, files in os.walk(b.target, onerror=on_error):
        # Junctions are links (Windows' legacy "My Documents"-style ones also deny listing), so the walk does not enter them.
        subdirs[:] = [name for name in subdirs if name not in SKIP_DIRS and not Path(directory, name).is_junction()]
        if "CLAUDE.md" in files:
            yield Path(directory) / "CLAUDE.md"


def _repo_claude_md(b: _Builder) -> Iterator[Path]:
    if not b.in_git:
        yield from _walk_claude_md(b)
        return
    for name in b.repo_files or ():
        if name == "CLAUDE.md" or name.endswith("/CLAUDE.md"):
            yield b.repo_root / name


def _add_nested(b: _Builder) -> None:
    if b.home_target:
        return
    for path in _repo_claude_md(b):
        if _is_below(path.parent, b.target):
            b.add(Artifact(path, Kind.NESTED_INSTRUCTIONS, Layer.REPO, LoadClass.ON_DEMAND))


def _is_doc(name: str) -> bool:
    """Return True for a repo-relative POSIX path to a doc: a ``.md`` file under ``docs/`` or ``Docs/``.

    Plans (``docs/plans/``) and anything in a folder named ``archive`` are left out: plans name files that do not exist yet.
    """
    parts = name.split("/")
    if len(parts) < 2 or parts[0] not in DOC_ROOTS or not parts[-1].endswith(".md"):
        return False
    return parts[1] != "plans" and "archive" not in parts[1:-1]


def _walk_docs(b: _Builder) -> Iterator[str]:
    """Yield the repo-relative POSIX path of every file under the doc folders, for a folder outside git."""

    def on_error(error: OSError) -> None:
        b.problems.append(f"cannot list {error.filename}: {error.strerror or error}")

    try:
        present = {path.name for path in b.repo_root.iterdir()}
    except OSError as exc:
        on_error(exc)
        return
    for root in (name for name in DOC_ROOTS if name in present):
        for directory, subdirs, files in os.walk(b.repo_root / root, onerror=on_error):
            subdirs[:] = [name for name in subdirs if name not in SKIP_DIRS and not Path(directory, name).is_junction()]
            yield from (Path(directory, name).relative_to(b.repo_root).as_posix() for name in files)


def _add_docs(b: _Builder) -> None:
    """Add the repo's docs, read on demand: git's file list inside a repository, a walk of the doc folders outside one."""
    if b.home_target:
        return
    names = b.repo_files if b.in_git else list(_walk_docs(b))
    for name in sorted(names or ()):
        path = b.repo_root / name
        if _is_doc(name) and is_file_like(path):
            b.add(Artifact(path, Kind.DOC, Layer.REPO, LoadClass.ON_DEMAND))


def _resolved_key(path: Path) -> str:
    try:
        return path_key(path.resolve())
    except OSError:
        return path_key(path)


def is_outside(path: Path, root: Path) -> bool:
    """Return True when ``path`` resolves outside ``root``, which is how a linked rule leaves the project."""
    return not Path(_resolved_key(path)).is_relative_to(Path(_resolved_key(root)))


def _rule_files(b: _Builder, base: Path) -> list[Path]:
    """Return the paths under ``base/rules`` to report: its ``*.md`` files and its links to network paths.

    A rule reached through a linked folder loads where a rule reached through a link to a network path does
    not, so the walk follows folder links but reports a network link as itself and never enters it. A real
    folder under ``rules/`` always wins over a link resolving to it; between links to one folder outside
    ``rules/``, the first in walk order wins.
    """
    root = base / "rules"
    if unc_link_target(root) is not None:
        return [root]
    if not root.is_dir():
        return []

    def on_error(error: OSError) -> None:
        message = f"cannot list {error.filename}: {error.strerror or error}"
        if message not in b.problems:
            b.problems.append(message)

    real = _real_rule_dirs(root, on_error)
    found: list[Path] = []
    claimed: set[str] = set()
    pending = [(root, False)]
    while pending:
        current, linked = pending.pop()
        folders, paths = _list_rules_dir(current, on_error)
        found.extend(path for path in paths if path.name.endswith(".md") or unc_link_target(path) is not None)
        walked = _walkable_rule_folders(folders, real, claimed, linked=linked)
        pending.extend(reversed(walked))
    return sorted(found)


def _list_rules_dir(directory: Path, on_error: Callable[[OSError], None]) -> tuple[list[Path], list[Path]]:
    """Return ``(subfolders, paths)`` for ``directory``, classifying entries without following a network link.

    Args:
        directory: The folder to list.
        on_error: Called with the ``OSError`` when the folder cannot be listed.

    Returns:
        Every subfolder in name order, and every other entry: a link to a network path is reported here, so
        the walk neither resolves nor enters it.
    """
    try:
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError as exc:
        on_error(exc)
        return [], []
    folders: list[Path] = []
    paths: list[Path] = []
    for entry in entries:
        path = Path(entry.path)
        if unc_link_target(path) is not None:
            paths.append(path)
        elif entry.is_dir():
            folders.append(path)
        else:
            paths.append(path)
    return folders, paths


def _is_folder_link(path: Path) -> bool:
    """Return True when ``path`` is a link to another folder: a symlink, or a Windows directory junction."""
    return path.is_symlink() or path.is_junction()


def _real_rule_dirs(root: Path, on_error: Callable[[OSError], None]) -> set[str]:
    """Return the resolved keys of the real folders under ``root``: no link is entered to find them."""
    keys: set[str] = set()
    pending = [root]
    while pending:
        current = pending.pop()
        key = _resolved_key(current)
        if key in keys:
            continue
        keys.add(key)
        folders, _paths = _list_rules_dir(current, on_error)
        pending.extend(folder for folder in folders if not _is_folder_link(folder))
    return keys


def _claim_folder(folder: Path, real: set[str], claimed: set[str]) -> bool:
    """Claim ``folder``, reached through a link: True when it is walked, False when a real folder or an earlier claim owns it."""
    key = _resolved_key(folder)
    if key in real or key in claimed:
        return False
    claimed.add(key)
    return True


def _walkable_rule_folders(folders: list[Path], real: set[str], claimed: set[str], *, linked: bool) -> list[tuple[Path, bool]]:
    """Return the subfolders of one listed folder to walk, each paired with whether it is reached through a link.

    Args:
        folders: The subfolders, in name order.
        real: The resolved keys of the real folders under ``rules/``, which always win.
        claimed: The resolved keys of the folders already claimed through a link; updated in place.
        linked: True when the listed folder was itself reached through a link.

    Returns:
        Every real subfolder of a folder reached without a link, plus each folder reached through a link (the link
        itself, or any folder below it) that no real folder or earlier claim owns. Every subfolder is claimed when its
        parent is listed, so a link listed beside another wins over the same folder reached below that other link.
    """
    walked: list[tuple[Path, bool]] = []
    for folder in folders:
        through_link = linked or _is_folder_link(folder)
        if not through_link or _claim_folder(folder, real, claimed):
            walked.append((folder, through_link))
    return walked


def _rule_load_class(b: _Builder, path: Path, layer: Layer, repo_root: Path) -> LoadClass:
    if not _loads(path):
        return LoadClass.NOT_LOADED
    text = b.read(path)
    parsed = frontmatter.parse(text or "")
    if parsed.data is not None and "paths" in parsed.data:
        # RL7: a rule reached through a link out of the project loads only while it carries no `paths`.
        if layer is Layer.REPO and is_outside(path, repo_root):
            return LoadClass.NOT_LOADED
        return LoadClass.ON_DEMAND
    return LoadClass.EVERY_TURN


def _add_claude_dir(b: _Builder, base: Path, layer: Layer) -> None:
    for path in _rule_files(b, base):
        if is_file_like(path):
            b.add(Artifact(path, Kind.RULE, layer, _rule_load_class(b, path, layer, b.repo_root)))
    b.add_glob(base, _CLAUDE_DIR_FILES, layer, None)


def _add_claude_dirs(b: _Builder) -> None:
    user_dir = b.home / ".claude"
    repo_dir = b.repo_root / ".claude"
    if path_key(repo_dir) != path_key(user_dir):
        _add_claude_dir(b, repo_dir, Layer.REPO)
    _add_claude_dir(b, user_dir, Layer.USER)
    mcp = b.repo_root / ".mcp.json"
    if mcp.is_file() and not b.home_target:
        b.add(Artifact(mcp, Kind.MCP_CONFIG, Layer.REPO, LoadClass.CONFIG))


def _enabled_plugins(b: _Builder) -> dict[str, Any]:
    """Merge ``enabledPlugins`` from user, project and local settings; later files win."""
    merged: dict[str, Any] = {}
    sources = (b.home / ".claude" / "settings.json", b.repo_root / ".claude" / "settings.json", b.repo_root / ".claude" / "settings.local.json")
    for path in sources:
        data = b.read_json(path)
        enabled = data.get("enabledPlugins") if isinstance(data, dict) else None
        if isinstance(enabled, dict):
            merged.update(enabled)
    return merged


def _entry_applies(b: _Builder, entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    scope = entry.get("scope")
    if scope == "user":
        return True
    project = entry.get("projectPath")
    return scope in ("project", "local") and isinstance(project, str) and path_key(Path(project)) == path_key(b.repo_root)


def _install_path(b: _Builder, name: str, entries: Any) -> Path | None:
    if not isinstance(entries, list):
        b.problems.append(f"installed_plugins.json: entry for {name} is not a list")
        return None
    entry = next((entry for entry in entries if _entry_applies(b, entry)), None)
    if entry is None:
        return None
    install = entry.get("installPath")
    if not isinstance(install, str):
        b.problems.append(f"installed_plugins.json: plugin {name} has no installPath")
        return None
    return Path(install)


def _add_plugins(b: _Builder) -> None:
    source = b.home / ".claude" / "plugins" / "installed_plugins.json"
    data = b.read_json(source)
    if data is None:
        return
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        b.problems.append(f'{source}: expected an object with a "plugins" object')
        return
    enabled = _enabled_plugins(b)
    for name, entries in sorted(plugins.items()):
        if enabled.get(name) is not True:
            continue
        install = _install_path(b, name, entries)
        if install is None:
            continue
        if not install.is_dir():
            b.problems.append(f"plugin {name}: installPath {install} does not exist")
            continue
        b.add_glob(install, _PLUGIN_FILES, Layer.PLUGIN, name)


def _add_memory(b: _Builder) -> None:
    directory = memory_dir(b.repo_root, b.home)
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.md")):
        if path.name == "MEMORY.md":
            b.add(Artifact(path, Kind.MEMORY_INDEX, Layer.MEMORY, LoadClass.EVERY_TURN))
        else:
            b.add(Artifact(path, Kind.MEMORY_TOPIC, Layer.MEMORY, LoadClass.ON_DEMAND))


def _repo_root(target: Path) -> tuple[Path, bool]:
    output = git_output(target, "rev-parse", "--show-toplevel")
    if output is None or not output.strip():
        return target, False
    return Path(output.strip()), True


def _named_servers(value: object, scope: McpScope) -> list[UserMcpServer]:
    if not isinstance(value, dict):
        return []
    return [UserMcpServer(scope=scope, name=name, config=config) for name, config in value.items() if isinstance(name, str)]


def _read_claude_json(path: Path) -> tuple[str | None, str | None]:
    """Return ``path``'s text, or a problem that names the file and the error kind only; neither when it is missing."""
    link = unc_link_target(path)
    if link is not None:
        return None, f"{path}: links to a network path ({link}); not read"
    if not path.is_file():
        return None, None
    try:
        return path.read_bytes().decode("utf-8-sig"), None
    except OSError as exc:
        return None, f"{path}: cannot read ({exc.strerror or type(exc).__name__})"
    except UnicodeDecodeError:
        return None, f"{path}: not valid UTF-8"


def _load_claude_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse ``path`` into its top-level object, or return a problem that names the file and the error kind only."""
    text, problem = _read_claude_json(path)
    if text is None:
        return None, problem
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"{path}: not valid JSON (line {exc.lineno})"
    except (ValueError, RecursionError) as exc:
        return None, f"{path}: not loadable JSON ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, f"{path}: top level is not a JSON object"
    return data, None


def _local_servers(data: dict[str, Any], repo_root: Path) -> list[UserMcpServer]:
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return []
    wanted = path_key(repo_root)
    for key, entry in projects.items():
        if isinstance(key, str) and isinstance(entry, dict) and path_key(Path(key)) == wanted:
            return _named_servers(entry.get("mcpServers"), McpScope.LOCAL)
    return []


def _claude_json_servers(home: Path, repo_root: Path | None) -> tuple[tuple[UserMcpServer, ...], tuple[str, ...]]:
    """Return the MCP servers ``~/.claude.json`` declares, and the problems met reading it.

    The file holds credentials, so it is parsed here directly and never cached or made an artifact; problems name the
    file and the error kind, never its content.

    Args:
        home: The home directory holding ``.claude.json``.
        repo_root: The checked repository's root, whose ``projects`` entry supplies local-scope servers; None for the home check.

    Returns:
        The user-scope servers then the local-scope ones, each in file order, and the discovery problems.
    """
    data, problem = _load_claude_json(home / ".claude.json")
    if data is None:
        return (), (() if problem is None else (problem,))
    servers = _named_servers(data.get("mcpServers"), McpScope.USER)
    if repo_root is not None:
        servers.extend(_local_servers(data, repo_root))
    return tuple(servers), ()


def discover(target: Path, home: Path, window: int, *, siblings: tuple[Path, ...] = ()) -> Rig:
    """Discover the effective setup Claude Code loads for ``target``.

    Problems with unreadable or malformed inputs are collected in ``Rig.problems``; discovery never raises for them.
    Only this project's own memory folder is read, and ``~/.claude.json`` is read only for its MCP servers, never as an artifact.
    When ``target`` is the home directory itself, only ``~/.claude`` is discovered: no repo-layer chain at home and no nested ``CLAUDE.md`` walk.

    Args:
        target: The directory Claude Code would start in.
        home: The home directory holding ``.claude``.
        window: The model's context window, in tokens, carried on the rig for the rules that measure against it.
        siblings: Folders given with ``--sibling``, carried on the rig for reference-path-missing; never scanned.

    Returns:
        The rig: every artifact with its layer and load class.
    """
    repo_root, in_git = _repo_root(target)
    b = _Builder(target=target, repo_root=repo_root, home=home, in_git=in_git, home_target=path_key(target) == path_key(home))
    roots, shadowed = _add_chain(b)
    _follow_imports(b, roots, shadowed)
    _add_nested(b)
    _add_docs(b)
    _add_claude_dirs(b)
    _add_plugins(b)
    _add_memory(b)
    servers, problems = _claude_json_servers(home, None if b.home_target else repo_root)
    b.problems.extend(problems)
    return Rig(
        target=target,
        repo_root=repo_root,
        home=home,
        artifacts=tuple(b.artifacts.values()),
        problems=tuple(b.problems),
        user_mcp_servers=servers,
        window=window,
        siblings=siblings,
    )
