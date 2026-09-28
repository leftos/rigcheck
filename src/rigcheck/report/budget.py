"""Context budget: what the rig costs Claude Code's context, in estimated tokens.

A report, never a finding: it does not change the exit code.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rigcheck.discover import MEMORY_INDEX_BYTES, MEMORY_INDEX_LINES
from rigcheck.model import Artifact, Kind, Layer, LoadClass, Rig
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import strip_html_comments
from rigcheck.parse.tokens import DESCRIPTION_CHARS_PER_TOKEN, INSTRUCTION_CHARS_PER_TOKEN, estimate

LISTING_DETAIL_CHARS = 1_536
"""A skill listing entry's description and when_to_use together are cut to this many characters."""
AGENT_DESCRIPTIONS_BUDGET = 15_000
"""Claude Code warns at startup when subagents' combined names and descriptions exceed this many tokens."""

_STRIPPED_KINDS = (Kind.INSTRUCTIONS, Kind.NESTED_INSTRUCTIONS)
_LISTED_KINDS = (Kind.SKILL, Kind.COMMAND)


@dataclass(frozen=True)
class Source:
    """One every-turn file and its estimated cost."""

    path: Path
    layer: Layer
    kind: Kind
    tokens_est: int


@dataclass(frozen=True)
class EveryTurn:
    """The files loaded on every turn, largest first, and their total."""

    total_est: int
    sources: tuple[Source, ...]


@dataclass(frozen=True)
class Listing:
    """A listing Claude Code keeps in context (skills and commands, or agents) against its budget.

    Attributes:
        tokens_est: Estimated tokens of every entry together.
        budget: The budget Claude Code applies, in tokens.
        entries: How many entries the listing has.
        by_layer: Estimated tokens per layer value, in layer order, for layers with entries only.
    """

    tokens_est: int
    budget: int
    entries: int
    by_layer: dict[str, int]


@dataclass(frozen=True)
class Budget:
    """The context budget report for one rig and context window."""

    window: int
    every_turn: EveryTurn
    skill_listing: Listing
    agent_descriptions: Listing


@dataclass(frozen=True)
class _Entry:
    name: str
    description: str
    when_to_use: str
    disabled: bool


def window_label(window: int) -> str:
    """Show a context window as ``200k`` or ``1m`` when round, else with thousands separators."""
    if window % 1_000_000 == 0:
        return f"{window // 1_000_000}m"
    if window % 1_000 == 0:
        return f"{window // 1_000}k"
    return f"{window:,}"


def loaded_text(rig: Rig, artifact: Artifact) -> str:
    """Return the part of an artifact's text that enters the context when it loads.

    Instruction files lose their HTML comments, and MEMORY.md is cut to its loaded head
    (the first 200 lines, then the first 25,000 bytes); anything else loads as is.

    Args:
        rig: The rig holding the artifact's text.
        artifact: The artifact to read.

    Returns:
        The loaded text.
    """
    text = rig.text(artifact.path)
    if artifact.kind in _STRIPPED_KINDS:
        return strip_html_comments(text)
    if artifact.kind is Kind.MEMORY_INDEX:
        lines = text.split("\n")
        head = "\n".join(lines[:MEMORY_INDEX_LINES]) + ("\n" if len(lines) > MEMORY_INDEX_LINES else "")
        return head.encode("utf-8")[:MEMORY_INDEX_BYTES].decode("utf-8", errors="ignore")
    return text


def _text_field(data: Mapping[Any, Any], key: str) -> str:
    value = data.get(key)
    return "" if value is None else str(value)


def _entry(rig: Rig, artifact: Artifact) -> _Entry:
    default_name = artifact.path.parent.name if artifact.kind is Kind.SKILL else artifact.path.stem
    text = rig.text(artifact.path)
    parsed = frontmatter.parse(text)
    data: Mapping[Any, Any] = parsed.data if parsed.data is not None else {}
    disabled = frontmatter.as_bool(data.get("disable-model-invocation")) is True
    name = _text_field(data, "name") or default_name
    return _Entry(name, _text_field(data, "description"), _text_field(data, "when_to_use"), disabled=disabled)


def _entry_text(entry: _Entry, detail_chars: int | None) -> str:
    detail = " ".join(part for part in (entry.description, entry.when_to_use) if part)
    if detail_chars is not None:
        detail = detail[:detail_chars]
    return f"{entry.name}: {detail}" if detail else entry.name


def _listing(rig: Rig, artifacts: Iterable[Artifact], budget: int, detail_chars: int | None) -> Listing:
    by_layer: dict[str, int] = {}
    entries = 0
    for artifact in sorted(artifacts, key=lambda a: (a.layer.rank, a.path.as_posix())):
        entry = _entry(rig, artifact)
        if entry.disabled:
            continue
        entries += 1
        tokens = estimate(_entry_text(entry, detail_chars), DESCRIPTION_CHARS_PER_TOKEN)
        by_layer[artifact.layer.value] = by_layer.get(artifact.layer.value, 0) + tokens
    return Listing(tokens_est=sum(by_layer.values()), budget=budget, entries=entries, by_layer=by_layer)


def _every_turn(rig: Rig) -> EveryTurn:
    sources = [
        Source(artifact.path, artifact.layer, artifact.kind, estimate(loaded_text(rig, artifact), INSTRUCTION_CHARS_PER_TOKEN))
        for artifact in rig.artifacts
        if artifact.load_class is LoadClass.EVERY_TURN
    ]
    sources.sort(key=lambda source: (-source.tokens_est, source.path.as_posix()))
    return EveryTurn(total_est=sum(source.tokens_est for source in sources), sources=tuple(sources))


def compute(rig: Rig) -> Budget:
    """Estimate what the rig costs the context: every-turn files, the skill listing and agent descriptions.

    Args:
        rig: The discovered rig; the skill listing's budget is 1% of its context window.

    Returns:
        The budget report.
    """
    skills = [artifact for artifact in rig.artifacts if artifact.kind in _LISTED_KINDS]
    agents = [artifact for artifact in rig.artifacts if artifact.kind is Kind.AGENT]
    return Budget(
        window=rig.window,
        every_turn=_every_turn(rig),
        skill_listing=_listing(rig, skills, rig.window // 100, LISTING_DETAIL_CHARS),
        agent_descriptions=_listing(rig, agents, AGENT_DESCRIPTIONS_BUDGET, None),
    )
