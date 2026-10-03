"""Rule for an instruction line that repeats one in a file Claude Code loads before it, every turn or in a shadowed AGENTS.md.

Lines are compared clause by clause, as lower-cased word tokens. The finding is about maintenance only: two copies of an
instruction drift apart when one is edited; it makes no claim about how well Claude follows either.
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


def _compared(rig: Rig) -> list[Artifact]:
    """The every-turn Markdown files, then the shadowed AGENTS.md peers, in load order, each real file once.

    Loaded files come first, user before repo before memory, then discovery order; a file that resolves to one
    already listed (a symlinked peer) is left out.
    """
    ranked = sorted(
        (artifact.load_class is LoadClass.NOT_LOADED, _LAYER_RANK.get(artifact.layer, len(_LAYER_RANK)), index, artifact)
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
        self.places: list[tuple[int, int]] = []
        self.sizes: list[int] = []
        self.exact: dict[Clause, int] = {}
        self.postings: dict[str, list[int]] = {}

    def add(self, place: tuple[int, int], clause: Clause) -> None:
        """Record a clause found at ``(file index, line)``."""
        number = len(self.places)
        tokens = set(clause)
        self.places.append(place)
        self.sizes.append(len(tokens))
        self.exact.setdefault(clause, number)
        for token in tokens:
            self.postings.setdefault(token, []).append(number)

    def near(self, clause: Clause) -> int | None:
        """Return the earliest recorded clause that nearly matches ``clause``, or None."""
        tokens = set(clause)
        size = len(tokens)
        overlaps: Counter[int] = Counter()
        for token in tokens:
            for number in self.postings.get(token, ()):
                if self.sizes[number] <= 2 * size and size <= 2 * self.sizes[number]:
                    overlaps[number] += 1
        matches = [number for number, overlap in overlaps.items() if _near(min(size, self.sizes[number]), max(size, self.sizes[number]), overlap)]
        return min(matches, default=None)


def _label(rig: Rig, path: Path) -> str:
    for root, prefix in ((rig.repo_root, ""), (rig.home, "~/")):
        if inside(path, root):
            return prefix + Path(os.path.relpath(path, root)).as_posix()
    return path.as_posix()


def _message(rig: Rig, files: list[Artifact], seen: _Seen, found: list[Clause]) -> str | None:
    """Return the message naming the earliest exact match of any clause, else the earliest near match, or None."""
    exact = [seen.exact[clause] for clause in found if clause in seen.exact]
    if exact:
        verb, number = "repeats", min(exact)
    else:
        near = [match for match in (seen.near(clause) for clause in found) if match is not None]
        if not near:
            return None
        verb, number = "nearly repeats", min(near)
    index, line = seen.places[number]
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
        pending: list[tuple[int, list[Clause]]] = []
        for number, found in _lines(rig, artifact):
            message = _message(rig, files, seen, found)
            if message is not None:
                yield emit("duplicate-line", artifact, message, number)
            pending.append((number, found))
        for number, found in pending:
            for clause in found:
                seen.add((index, number), clause)
