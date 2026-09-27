"""Rules for the always-on instruction files and their ``@path`` imports."""

from collections.abc import Iterator
from pathlib import Path

from rigcheck.discover import AGENTS_MD, IGNORED_BY_CLAUDE, MAX_BYTES, MAX_IMPORT_DEPTH, is_file_like, path_key, resolved_imports
from rigcheck.model import Artifact, Finding, Kind, Layer, LoadClass, Rig, Severity, unc_link_target
from rigcheck.rules import REGISTRY, emit, rule

_SIZED_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS, Kind.RULE)
_MIB = 1024 * 1024


def _chain(rig: Rig) -> list[Artifact]:
    """Instruction files found by walking up from the target, not through an import."""
    return [a for a in rig.artifacts if a.kind is Kind.INSTRUCTIONS and a.layer is Layer.REPO and a.imported_from is None]


def _importers(rig: Rig) -> list[Artifact]:
    """Instruction files whose imports Claude Code expands."""
    return [a for a in rig.artifacts if a.kind is Kind.INSTRUCTIONS and a.load_class is not LoadClass.NOT_LOADED]


def _size(artifact: Artifact) -> int:
    if unc_link_target(artifact.path) is not None:
        return 0
    try:
        return artifact.path.stat().st_size
    except OSError:
        return 0


@rule(
    "instructions-too-large",
    "core",
    Severity.ERROR,
    "Claude Code skips files over 4 MiB: split the file, or move the detail into skills or path-scoped rules.",
    ("official:CM1",),
)
def instructions_too_large(rig: Rig) -> Iterator[Finding]:
    """An instruction or rule file is over 4 MiB, so Claude Code skips it."""
    for artifact in rig.artifacts:
        size = _size(artifact) if artifact.kind in _SIZED_KINDS else 0
        if size > MAX_BYTES:
            yield emit("instructions-too-large", artifact, f"{artifact.path.name} is {size / _MIB:.1f} MiB; Claude Code does not load it", None)


@rule(
    "import-unresolved",
    "core",
    Severity.ERROR,
    "Fix the path: imports resolve relative to the file that contains them, and ~ is the home directory.",
    ("official:CM2",),
)
def import_unresolved(rig: Rig) -> Iterator[Finding]:
    """An ``@path`` import points at no file."""
    for importer in _importers(rig):
        for item, path in resolved_imports(rig, importer):
            if not is_file_like(path):
                yield emit("import-unresolved", importer, f"@{item.raw} resolves to {path.as_posix()}, which is not a file", item.line)


def _import_line(rig: Rig, importer: Artifact, target: Path) -> int | None:
    key = path_key(target)
    return next((item.line for item, path in resolved_imports(rig, importer) if path_key(path) == key), None)


@rule(
    "import-too-deep",
    "core",
    Severity.WARN,
    "Flatten the import chain: Claude Code follows four hops and silently drops files beyond them.",
    ("official:CM2",),
)
def import_too_deep(rig: Rig) -> Iterator[Finding]:
    """A file is reached only past Claude Code's four-hop import limit."""
    by_key = {path_key(a.path): a for a in rig.artifacts}
    for artifact in rig.artifacts:
        if artifact.import_depth <= MAX_IMPORT_DEPTH or artifact.imported_from is None:
            continue
        importer = by_key.get(path_key(artifact.imported_from), artifact)
        line = _import_line(rig, importer, artifact.path) if importer is not artifact else None
        message = f"{artifact.path.name} is import hop {artifact.import_depth}; Claude Code stops after {MAX_IMPORT_DEPTH}, so it does not load"
        yield emit("import-too-deep", importer, message, line)


def _ancestry(artifact: Artifact, by_key: dict[str, Artifact]) -> set[str]:
    keys: set[str] = set()
    current: Artifact | None = artifact
    while current is not None and path_key(current.path) not in keys:
        keys.add(path_key(current.path))
        current = by_key.get(path_key(current.imported_from)) if current.imported_from is not None else None
    return keys


@rule("import-cycle", "core", Severity.WARN, "Remove one side of the cycle.", ("official:CM2",))
def import_cycle(rig: Rig) -> Iterator[Finding]:
    """An import leads back to a file already on its own import chain."""
    by_key = {path_key(a.path): a for a in rig.artifacts}
    for importer in _importers(rig):
        chain = _ancestry(importer, by_key)
        for item, path in resolved_imports(rig, importer):
            if path_key(path) in chain:
                yield emit("import-cycle", importer, f"@{item.raw} imports {path.name}, which is already on this import chain", item.line)


@rule(
    "import-external",
    "core",
    Severity.INFO,
    "Teammates get an approval dialog for imports outside the repo, and declining disables them silently; "
    "move the file into the repo if everyone needs it.",
    ("official:CM3",),
)
def import_external(rig: Rig) -> Iterator[Finding]:
    """A repo file imports a file outside the repository."""
    root = Path(path_key(rig.repo_root))
    for importer in _importers(rig):
        if importer.layer is not Layer.REPO:
            continue
        for item, path in resolved_imports(rig, importer):
            if is_file_like(path) and not Path(path_key(path)).is_relative_to(root):
                yield emit("import-external", importer, f"@{item.raw} imports {path.as_posix()}, outside the repository", item.line)


def _chain_names(rig: Rig) -> set[str]:
    return {a.path.name for a in _chain(rig)}


def _unread_agents_md(rig: Rig) -> list[Artifact]:
    return [a for a in _chain(rig) if a.path.name == AGENTS_MD and a.load_class is LoadClass.NOT_LOADED]


@rule(
    "agents-md-shadowed",
    "core",
    Severity.WARN,
    "Add `@AGENTS.md` to CLAUDE.md, or merge the two files.",
    ("official:CM15",),
)
def agents_md_shadowed(rig: Rig) -> Iterator[Finding]:
    """AGENTS.md is not read because a CLAUDE.md exists and nothing imports AGENTS.md."""
    if "CLAUDE.md" not in _chain_names(rig):
        return
    for artifact in _unread_agents_md(rig):
        yield emit("agents-md-shadowed", artifact, "Claude Code reads only the CLAUDE.md files here, and none of them imports this AGENTS.md", None)


@rule(
    "claude-local-hides-agents-md",
    "core",
    Severity.WARN,
    "Add a CLAUDE.md that imports AGENTS.md (`@AGENTS.md`).",
    ("official:CM14",),
)
def claude_local_hides_agents_md(rig: Rig) -> Iterator[Finding]:
    """A CLAUDE.local.md without a CLAUDE.md stops Claude Code from reading AGENTS.md."""
    names = _chain_names(rig)
    if "CLAUDE.md" in names or "CLAUDE.local.md" not in names:
        return
    for artifact in _unread_agents_md(rig):
        yield emit(
            "claude-local-hides-agents-md", artifact, "CLAUDE.local.md counts as a CLAUDE.md, so Claude Code does not read this AGENTS.md", None
        )


@rule(
    "claude-local-tracked",
    "core",
    Severity.WARN,
    "Untrack it (`git rm --cached CLAUDE.local.md`) and add it to .gitignore.",
    ("official:CM13",),
)
def claude_local_tracked(rig: Rig) -> Iterator[Finding]:
    """CLAUDE.local.md, meant for personal instructions, is tracked by git."""
    for artifact in _chain(rig):
        if artifact.path.name == "CLAUDE.local.md" and rig.is_tracked(artifact.path):
            yield emit("claude-local-tracked", artifact, "CLAUDE.local.md is committed, so every clone gets these personal instructions", None)


@rule(
    "unc-symlink",
    "core",
    Severity.ERROR,
    "Copy the file into the repo or home folder: Claude Code does not load instructions linked to a network path.",
    ("official:CM19",),
)
def unc_symlink(rig: Rig) -> Iterator[Finding]:
    """An instruction or rule file is a symlink to a network (UNC) path, which Claude Code does not load."""
    for artifact in rig.artifacts:
        target = unc_link_target(artifact.path) if artifact.kind in (Kind.INSTRUCTIONS, Kind.RULE) else None
        if target is not None:
            yield emit("unc-symlink", artifact, f"{artifact.path.name} links to the network path {target}", None)


@rule(
    "claude-never-reads",
    "core",
    Severity.INFO,
    "Claude Code ignores AGENTS.local.md and AGENTS.override.md (Codex reads AGENTS.override.md); "
    "move instructions Claude needs into CLAUDE.md or AGENTS.md.",
    ("official:CM16",),
)
def claude_never_reads(rig: Rig) -> Iterator[Finding]:
    """AGENTS.local.md or AGENTS.override.md exists; Claude Code never reads them."""
    for artifact in _chain(rig):
        if artifact.path.name in IGNORED_BY_CLAUDE:
            yield emit("claude-never-reads", artifact, f"Claude Code does not read {artifact.path.name}", None)


@rule("discovery-error", "core", Severity.WARN, "Fix or remove the file named in the message.", ("rigcheck:discovery",))
def discovery_error(rig: Rig) -> Iterator[Finding]:
    """Part of the setup could not be read or parsed."""
    meta = REGISTRY["discovery-error"]
    for problem in rig.problems:
        yield Finding("discovery-error", meta.severity, None, None, problem, meta.fix, None, None)


@rule("internal-error", "core", Severity.ERROR, "Report a bug to rigcheck with the message and the command you ran.", ("rigcheck:engine",))
def internal_error(rig: Rig) -> Iterator[Finding]:
    """A rule raised an exception; the engine emits this finding in its place."""
    del rig
    yield from ()
