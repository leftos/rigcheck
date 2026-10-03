"""Rule for an instruction line that repeats one in a file Claude Code loads before it, every turn or in a shadowed AGENTS.md.

Lines are compared clause by clause, as lower-cased word tokens. The finding is about maintenance only: two copies of an
instruction drift apart when one is edited; it makes no claim about how well Claude follows either.

A compared file is *shared* when git lists it as the repo's own, and *local* otherwise. The user's ``~/.claude/CLAUDE.md``
and its imports, a ``CLAUDE.local.md`` and a CLAUDE.md in a folder above the repo are local: they exist on one machine
only, so a repo restating one of their rules is usually deliberate, and deleting the repo copy would drop the
instruction for a cloud session or a contributor. An AGENTS.md is the repo's shared Codex peer wherever it sits. A
shared file and a local one are never compared with each other. The MEMORY.md index is compared with both, and sorts
last so the memory copy is the one reported.
"""

import os
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from rigcheck.discover import AGENTS_MD, IGNORED_BY_CLAUDE, path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, LoadClass, Rig, Severity
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import prose_segments
from rigcheck.rules import emit, rule
from rigcheck.rules.references import inside

_EVERY_TURN_KINDS = frozenset({Kind.INSTRUCTIONS, Kind.RULE, Kind.MEMORY_INDEX})
"""The Markdown kinds discovery can mark every-turn; a shadowed AGENTS.md is an instructions file."""
_LAYER_RANK = {Layer.USER: 0, Layer.REPO: 1, Layer.MEMORY: 2}
"""Ordering only: a file's layer says which discovery pass found it, not whether it is shared."""
_SHARED = "shared"
_LOCAL = "local"
_MEMORY = "memory"
"""The three classes of compared file: the repo's own file, a machine-local one, and the MEMORY.md index."""
_LOCAL_INSTRUCTIONS = "CLAUDE.local.md"
_LINE_BREAK = re.compile(r"\r\n?|\n")
_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_IMPORT_LINE = re.compile(r"^@\S+$")
_SETEXT_UNDERLINE = re.compile(r"^\s*(=+|-+)\s*$")
_NOT_PROSE = re.compile(
    r"(?P<code>`+).*?(?P=code)"
    r"|(?P<link>\]\([^)]*\))"
    r"|<[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*>"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>"
)
"""Code spans, kept; link destinations, reduced to the ``]`` that closes the link text; autolinks and HTML tags, removed."""
_CLAUSE_BREAK = re.compile(r"[.;!?](?=\s|$)|:\s")
_TOKEN = re.compile(r"[a-z0-9._/-]+")
_MIN_TOKENS = 5

Clause = tuple[str, ...]


def _eligible(artifact: Artifact) -> bool:
    if artifact.kind not in _EVERY_TURN_KINDS or artifact.path.name in IGNORED_BY_CLAUDE:
        return False
    return artifact.load_class is LoadClass.EVERY_TURN or (artifact.path.name == AGENTS_MD and artifact.load_class is LoadClass.NOT_LOADED)


def _resolved_key(path: Path) -> str:
    try:
        return path_key(path.resolve())
    except (OSError, RuntimeError):
        return path_key(path)


def _project_name(rig: Rig, path: Path) -> str | None:
    """Return the file's repo-relative POSIX path, or None when it is not on the repo's drive."""
    try:
        return Path(os.path.relpath(path, rig.repo_root)).as_posix()
    except ValueError:
        return None


def _shares_project(rig: Rig, path: Path) -> bool:
    """True when git lists the file as the repo's own: tracked, or untracked and not ignored.

    Outside git the test falls back to location: a file inside the repo is the repo's own, unless it is a
    ``CLAUDE.local.md``. An ``AGENTS.md`` counts either way: it is the peer Codex reads, and it belongs to the project
    it sits above rather than to the machine.
    """
    files = rig.project_files
    if files is not None:
        name = _project_name(rig, path)
        if name is not None:
            return name in files
    return path.name == AGENTS_MD or (inside(path, rig.repo_root) and path.name != _LOCAL_INSTRUCTIONS)


def _classify(rig: Rig, artifact: Artifact) -> str:
    """Return the class of one compared file: ``shared``, ``local`` or ``memory``."""
    if artifact.kind is Kind.MEMORY_INDEX:
        return _MEMORY
    return _SHARED if _shares_project(rig, artifact.path) else _LOCAL


def _comparable(one: str, other: str) -> bool:
    """True unless one file is shared and the other local, which are never compared with each other."""
    return not (one == _SHARED and other == _LOCAL) and not (one == _LOCAL and other == _SHARED)


def _compared(rig: Rig) -> list[Artifact]:
    """The every-turn Markdown files, then the shadowed AGENTS.md peers, then the memory index, each real file once.

    Loaded files come first, user before repo, then discovery order; every memory file sorts after all of them, and a
    file that resolves to one already listed (a symlinked peer) is left out.
    """
    ranked = sorted(
        (
            artifact.kind is Kind.MEMORY_INDEX,
            artifact.load_class is LoadClass.NOT_LOADED,
            _LAYER_RANK.get(artifact.layer, len(_LAYER_RANK)),
            index,
            artifact,
        )
        for index, artifact in enumerate(rig.artifacts)
        if _eligible(artifact)
    )
    files: dict[str, Artifact] = {}
    for *_, artifact in ranked:
        files.setdefault(_resolved_key(artifact.path), artifact)
    return list(files.values())


def _considered(line: str, following: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "|")) or _IMPORT_LINE.match(stripped) is not None:
        return False
    return _SETEXT_UNDERLINE.match(following) is None


def _without_markup(match: re.Match[str]) -> str:
    if match.group("code") is not None:
        return match.group(0)
    return "]" if match.group("link") is not None else " "


def clauses(line: str) -> list[Clause]:
    """Return the clauses of one prose line that are long enough to compare, as token tuples.

    A leading list marker, link destinations (the link text stays), autolinks and HTML tags are dropped, backticks and
    asterisks are deleted, and the line splits after ``.``, ``;``, ``!`` or ``?`` before whitespace or the end, and
    after ``:`` before whitespace. Code spans keep their content. Tokens are runs of lower-case letters, digits and
    ``._/-``, with dots stripped from both ends.

    Args:
        line: One source line of prose.

    Returns:
        The token tuples of clauses with at least five distinct tokens, in order.
    """
    text = _NOT_PROSE.sub(_without_markup, _LIST_MARKER.sub("", line, count=1)).replace("`", "").replace("*", "")
    found: list[Clause] = []
    for clause in _CLAUSE_BREAK.split(text):
        tokens = tuple(token for token in (raw.strip(".") for raw in _TOKEN.findall(clause.casefold())) if token)
        if len(set(tokens)) >= _MIN_TOKENS:
            found.append(tokens)
    return found


def _lines(rig: Rig, artifact: Artifact) -> Iterator[tuple[int, list[Clause]]]:
    """Yield each prose line of the file's body that has clauses to compare, with those clauses."""
    text = rig.text(artifact.path)
    source = _LINE_BREAK.split(text)
    numbers = dict.fromkeys(number for number, _ in prose_segments(text, frontmatter.parse(text).body_line))
    for number in numbers:
        line = source[number - 1] if number <= len(source) else ""
        following = source[number] if number < len(source) else ""
        found = clauses(line) if _considered(line, following) else []
        if found:
            yield number, found


def _near(small: int, large: int, overlap: int) -> bool:
    """True when the overlap is at least 0.8 of the smaller set and the larger set is at most twice the smaller."""
    return large <= 2 * small and 5 * overlap >= 4 * small


class _Seen:
    """The clauses of the files already read, indexed by exact tokens and by token, numbered in load order."""

    def __init__(self) -> None:
        self.places: list[tuple[int, int, str]] = []
        self.sizes: list[int] = []
        self.exact: dict[Clause, list[int]] = {}
        self.postings: dict[str, list[int]] = {}

    def add(self, place: tuple[int, int], cls: str, clause: Clause) -> None:
        """Record a clause found at ``(file index, line)`` in a file of class ``cls``."""
        number = len(self.places)
        tokens = set(clause)
        self.places.append((*place, cls))
        self.sizes.append(len(tokens))
        self.exact.setdefault(clause, []).append(number)
        for token in tokens:
            self.postings.setdefault(token, []).append(number)

    def exact_match(self, clause: Clause, cls: str) -> int | None:
        """Return the number of the earliest clause record holding ``clause`` that ``cls`` may be compared with, or None."""
        for number in self.exact.get(clause, ()):
            if _comparable(cls, self.places[number][2]):
                return number
        return None

    def near(self, clause: Clause, cls: str) -> int | None:
        """Return the earliest recorded clause that nearly matches ``clause`` in a file ``cls`` may be compared with, or None."""
        tokens = set(clause)
        size = len(tokens)
        overlaps: Counter[int] = Counter()
        for token in tokens:
            for number in self.postings.get(token, ()):
                if _comparable(cls, self.places[number][2]) and self.sizes[number] <= 2 * size and size <= 2 * self.sizes[number]:
                    overlaps[number] += 1
        matches = [number for number, overlap in overlaps.items() if _near(min(size, self.sizes[number]), max(size, self.sizes[number]), overlap)]
        return min(matches, default=None)


def _label(rig: Rig, path: Path) -> str:
    for root, prefix in ((rig.repo_root, ""), (rig.home, "~/")):
        if inside(path, root):
            return prefix + Path(os.path.relpath(path, root)).as_posix()
    return path.as_posix()


def _message(rig: Rig, files: list[Artifact], seen: _Seen, found: list[Clause], cls: str) -> str | None:
    """Return the message naming the earliest exact match of any clause, else the earliest near match, or None."""
    exact = [number for number in (seen.exact_match(clause, cls) for clause in found) if number is not None]
    if exact:
        verb, number = "repeats", min(exact)
    else:
        near = [match for match in (seen.near(clause, cls) for clause in found) if match is not None]
        if not near:
            return None
        verb, number = "nearly repeats", min(near)
    index, line, _cls = seen.places[number]
    return f"{verb} {_label(rig, files[index].path)}:{line}"


@rule(
    "duplicate-line",
    "core",
    Severity.INFO,
    "Keep the instruction in one file and import it (@path) where another file needs it; two copies drift apart when one is edited.",
    ("official:MM5", "rigcheck:duplication"),
)
def duplicate_line(rig: Rig) -> Iterator[Finding]:
    """A clause of an every-turn instruction file, or of an AGENTS.md peer, that repeats one in a file loaded before it."""
    files = _compared(rig)
    seen = _Seen()
    for index, artifact in enumerate(files):
        cls = _classify(rig, artifact)
        pending: list[tuple[int, list[Clause]]] = []
        for number, found in _lines(rig, artifact):
            message = _message(rig, files, seen, found, cls)
            if message is not None:
                yield emit("duplicate-line", artifact, message, number)
            pending.append((number, found))
        for number, found in pending:
            for clause in found:
                seen.add((index, number), cls, clause)
