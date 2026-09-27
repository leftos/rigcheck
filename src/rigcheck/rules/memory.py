"""Rules for the auto-memory folder: MEMORY.md's size and links, and its topic files."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rigcheck.discover import MEMORY_INDEX_BYTES, MEMORY_INDEX_LINES, file_size, path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity
from rigcheck.parse import frontmatter
from rigcheck.parse.markdown import Reference, find_references
from rigcheck.rules import emit, rule
from rigcheck.rules.references import reference_path

_TYPES = frozenset({"user", "feedback", "project", "reference"})
_TYPE_KEYS = ("type", "metadata.type")


def _memory(rig: Rig, kind: Kind) -> list[Artifact]:
    return [a for a in rig.artifacts if a.layer is Layer.MEMORY and a.kind is kind]


def _line_count(text: str) -> int:
    r"""Count lines the way Claude Code cuts MEMORY.md: by ``\n`` only, with an unterminated last line counting as one."""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _resolve(rig: Rig, directory: Path, token: str) -> Path:
    if token.startswith("~/"):
        return Path(os.path.normpath(rig.home / token[2:]))
    return Path(os.path.normpath(directory / token))


def _links(rig: Rig, index: Artifact) -> Iterator[tuple[Reference, Path]]:
    """Yield each Markdown link in MEMORY.md that names a path, with the path it resolves to."""
    for reference in find_references(rig.text(index.path)):
        token = reference_path(reference) if reference.source == "link" else None
        if token is not None:
            yield reference, _resolve(rig, index.path.parent, token)


@rule(
    "memory-index-too-large",
    "core",
    Severity.ERROR,
    "Move detail into topic files and keep MEMORY.md to one line per entry, under 200 lines and 25 KB.",
    ("official:MM1",),
)
def memory_index_too_large(rig: Rig) -> Iterator[Finding]:
    """MEMORY.md is past the 200 lines or 25 KB Claude Code loads, so the entries past it are invisible."""
    for index in _memory(rig, Kind.MEMORY_INDEX):
        lines = _line_count(rig.text(index.path))
        size = file_size(index.path)
        if lines > MEMORY_INDEX_LINES or size > MEMORY_INDEX_BYTES:
            message = f"MEMORY.md has {lines} lines and {size:,} bytes; Claude Code loads the first 200 lines or 25,000 bytes"
            yield emit("memory-index-too-large", index, message, None)


@rule(
    "memory-link-broken",
    "core",
    Severity.WARN,
    "Fix or remove the link: memory links resolve relative to the memory folder.",
    ("official:MM3",),
)
def memory_link_broken(rig: Rig) -> Iterator[Finding]:
    """A link in MEMORY.md points at no file."""
    for index in _memory(rig, Kind.MEMORY_INDEX):
        for reference, target in _links(rig, index):
            if not _exists(target):
                yield emit("memory-link-broken", index, f"{reference.raw} does not exist", reference.line)


@rule(
    "memory-topic-orphan",
    "core",
    Severity.INFO,
    "Add a one-line entry linking the file from MEMORY.md, or delete the file if it is stale.",
    ("official:MM3",),
)
def memory_topic_orphan(rig: Rig) -> Iterator[Finding]:
    """A memory topic file is not linked from MEMORY.md, so Claude has no index entry to find it by."""
    linked: dict[str, set[str]] = {}
    for index in _memory(rig, Kind.MEMORY_INDEX):
        linked[path_key(index.path.parent)] = {path_key(target) for _, target in _links(rig, index)}
    for topic in _memory(rig, Kind.MEMORY_TOPIC):
        targets = linked.get(path_key(topic.path.parent))
        if targets is not None and path_key(topic.path) not in targets:
            yield emit("memory-topic-orphan", topic, f"{topic.path.name} is not linked from MEMORY.md", None)


def _type_value(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _types(text: str) -> dict[str, str]:
    """Return the file's ``type`` and ``metadata.type`` values that are present and not empty, by key path."""
    parsed = frontmatter.parse(text)
    if not parsed.present:
        return {}
    if parsed.data is None:
        raw: dict[str, Any] = frontmatter.read_lenient(text, _TYPE_KEYS)
    else:
        metadata = parsed.data.get("metadata")
        raw = {"type": parsed.data.get("type"), "metadata.type": metadata.get("type") if isinstance(metadata, dict) else None}
    values = {key: _type_value(value) for key, value in raw.items()}
    return {key: value for key, value in values.items() if value is not None}


def _type_messages(types: dict[str, str]) -> list[str]:
    unknown = [f"{key}: {value} is not a documented memory type" for key, value in types.items() if value not in _TYPES]
    if unknown or len(set(types.values())) < 2:
        return unknown
    return [f"type: {types['type']} and metadata.type: {types['metadata.type']} disagree"]


@rule(
    "memory-type-unknown",
    "core",
    Severity.INFO,
    "Use one of user, feedback, project or reference.",
    ("official:MM4",),
)
def memory_type_unknown(rig: Rig) -> Iterator[Finding]:
    """A memory file's ``type`` is not one of the documented kinds."""
    for topic in _memory(rig, Kind.MEMORY_TOPIC):
        for message in _type_messages(_types(rig.text(topic.path))):
            yield emit("memory-type-unknown", topic, message, None)
