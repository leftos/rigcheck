"""Core data model: artifacts, findings, rules and the rig they describe."""

import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from pathlib import Path


class _Ranked(Enum):
    """An enum whose declaration order is its rank order."""

    @property
    def rank(self) -> int:
        """Position of this member in declaration order (0 ranks first)."""
        return list(type(self)).index(self)


class Layer(_Ranked):
    """Where a file comes from."""

    REPO = "repo"
    MEMORY = "memory"
    USER = "user"
    PLUGIN = "plugin"


class LoadClass(_Ranked):
    """How often a file's content enters Claude Code's context."""

    EVERY_TURN = "every-turn"
    ON_INVOKE = "on-invoke"
    CONFIG = "config"
    ON_DEMAND = "on-demand"
    NOT_LOADED = "not-loaded"


class Kind(Enum):
    """What an artifact is."""

    INSTRUCTIONS = "instructions"
    NESTED_INSTRUCTIONS = "nested-instructions"
    RULE = "rule"
    SKILL = "skill"
    COMMAND = "command"
    AGENT = "agent"
    OUTPUT_STYLE = "output-style"
    SETTINGS = "settings"
    HOOKS_CONFIG = "hooks-config"
    MCP_CONFIG = "mcp-config"
    MEMORY_INDEX = "memory-index"
    MEMORY_TOPIC = "memory-topic"
    PLUGIN_MANIFEST = "plugin-manifest"


class Severity(_Ranked):
    """How serious a finding is."""

    ERROR = "error"
    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True)
class Artifact:
    """One file of the rig, with where it comes from and how often it loads."""

    path: Path
    kind: Kind
    layer: Layer
    load_class: LoadClass
    plugin: str | None = None
    imported_from: Path | None = None
    import_depth: int = 0


@dataclass(frozen=True)
class Finding:
    """One rule violation at one location."""

    rule_id: str
    severity: Severity
    path: Path | None
    line: int | None
    message: str
    fix: str
    layer: Layer | None
    load_class: LoadClass | None


@dataclass(frozen=True)
class Rule:
    """A check with the metadata that explains and ranks its findings."""

    id: str
    pack: str
    severity: Severity
    summary: str
    fix: str
    evidence: tuple[str, ...]
    check: Callable[["Rig"], Iterable[Finding]]


def git_output(cwd: Path, *args: str) -> str | None:
    """Run git in ``cwd`` and return its stdout, or None when git is missing or fails.

    Args:
        cwd: Directory passed to ``git -C``.
        *args: The git subcommand and its arguments.

    Returns:
        The command's stdout, or None when git is not on PATH or exits non-zero.
    """
    git = shutil.which("git")
    if git is None:
        return None
    # Arguments are fixed by callers; nothing here comes from untrusted input.
    result = subprocess.run([git, "-C", str(cwd), *args], capture_output=True, check=False, timeout=60)  # noqa: S603
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def unc_link_target(path: Path) -> str | None:
    r"""Return the target of a symlink pointing at a network (UNC) path, else None.

    Args:
        path: The path to inspect; it need not exist.

    Returns:
        The link target when ``path`` is a symlink whose target starts with ``\\`` or ``//``.
    """
    try:
        if not path.is_symlink():
            return None
        target = str(path.readlink())
    except OSError:
        return None
    if target.startswith("\\\\?\\UNC\\"):
        return "\\\\" + target[len("\\\\?\\UNC\\") :]
    if target.startswith(("\\\\", "//")) and not target.startswith("\\\\?\\"):
        return target
    return None


@dataclass(frozen=True)
class Rig:
    """The discovered setup: every artifact plus the problems met while finding them."""

    target: Path
    repo_root: Path
    home: Path
    artifacts: tuple[Artifact, ...]
    problems: tuple[str, ...]
    _texts: dict[Path, str] = field(default_factory=dict, init=False, repr=False, compare=False)

    def text(self, path: Path) -> str:
        """Return a file's text, decoded as UTF-8 with replacement, cached per path.

        Unreadable files and symlinks to network paths read as the empty string;
        discovery reports read failures for the instruction files it parses.
        """
        cached = self._texts.get(path)
        if cached is not None:
            return cached
        text = ""
        if unc_link_target(path) is None:
            try:
                text = path.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                text = ""
        self._texts[path] = text
        return text

    @cached_property
    def _tracked(self) -> frozenset[str]:
        output = git_output(self.repo_root, "ls-files", "-z")
        if output is None:
            return frozenset()
        return frozenset(name for name in output.split("\0") if name)

    @cached_property
    def project_files(self) -> frozenset[str] | None:
        """The repository's tracked and untracked-but-not-ignored files, as repo-relative POSIX paths.

        None when the repo root is not a git repository or git is unavailable.
        """
        output = git_output(self.repo_root, "ls-files", "-co", "--exclude-standard", "-z")
        if output is None:
            return None
        return frozenset(name for name in output.split("\0") if name)

    def is_tracked(self, path: Path) -> bool:
        """Return True when git tracks ``path`` in this rig's repository."""
        try:
            relative = path.relative_to(self.repo_root)
        except ValueError:
            return False
        return relative.as_posix() in self._tracked
