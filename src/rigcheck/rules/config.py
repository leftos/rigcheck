"""Reading the config artifacts: hook maps, hook handlers and MCP server definitions.

No rule registers itself here. These helpers are what the hook, settings, MCP and duplication
rules read the discovered config files through.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from rigcheck.model import Artifact, Kind, Layer, Rig
from rigcheck.parse import config
from rigcheck.rules import components


class HookSource(StrEnum):
    """Where a hook map is written."""

    SETTINGS = "settings"
    PLUGIN_HOOKS = "plugin-hooks"
    PLUGIN_MANIFEST = "plugin-manifest"
    SKILL_FRONTMATTER = "skill-frontmatter"
    AGENT_FRONTMATTER = "agent-frontmatter"


@dataclass(frozen=True)
class HookMap:
    """One artifact's hook event map.

    Attributes:
        artifact: The file the map is written in.
        source: The kind of file it is, which decides where the map sits in it.
        events: The raw event map, keyed as written: event name to its list of groups.
        line: The 1-based line of the ``hooks`` key, or None when the text does not show one.
    """

    artifact: Artifact
    source: HookSource
    events: Mapping[str, object]
    line: int | None


@dataclass(frozen=True)
class HookHandler:
    """One hook handler: an entry of a group's ``hooks`` list.

    Attributes:
        map: The hook map the handler was found in.
        event: The event name it is registered under.
        matcher: The group's ``matcher`` value, or None when the group sets none.
        group: The group object holding the handler.
        handler: The handler object itself.
    """

    map: HookMap
    event: str
    matcher: object
    group: Mapping[str, object]
    handler: Mapping[str, object]


class McpSource(StrEnum):
    """Where a server definition is written."""

    REPO_FILE = "repo-file"
    PLUGIN_FILE = "plugin-file"
    PLUGIN_MANIFEST = "plugin-manifest"


@dataclass(frozen=True)
class McpServer:
    """One MCP server definition.

    Attributes:
        artifact: The file the definition is written in.
        source: The kind of file it is.
        name: The server's name, the key it is written under.
        config: The server's value, as written.
        line: The 1-based line of the server's key, or None when the text does not show one.
    """

    artifact: Artifact
    source: McpSource
    name: str
    config: object
    line: int | None


_JSON_SOURCES: dict[Kind, HookSource] = {
    Kind.SETTINGS: HookSource.SETTINGS,
    Kind.HOOKS_CONFIG: HookSource.PLUGIN_HOOKS,
    Kind.PLUGIN_MANIFEST: HookSource.PLUGIN_MANIFEST,
}
"""The artifact kinds whose JSON holds the hook map under a top-level ``hooks`` key."""

_FRONTMATTER_SOURCES: dict[Kind, HookSource] = {
    Kind.SKILL: HookSource.SKILL_FRONTMATTER,
    Kind.COMMAND: HookSource.SKILL_FRONTMATTER,
    Kind.AGENT: HookSource.AGENT_FRONTMATTER,
}
"""The artifact kinds whose frontmatter holds the hook map under a ``hooks`` key."""


def _str_keys(value: Mapping[object, object]) -> dict[str, object]:
    """Return ``value`` with its non-string keys dropped."""
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _json_hooks(rig: Rig, artifact: Artifact, source: HookSource) -> HookMap | None:
    """Return the hook map a JSON artifact holds under ``hooks``, or None when it holds none."""
    text = rig.text(artifact.path)
    doc = config.load(text)
    if not isinstance(doc.data, dict):
        return None
    hooks = doc.data.get("hooks")
    if not isinstance(hooks, dict):
        return None
    return HookMap(artifact, source, _str_keys(hooks), config.key_line(text, "hooks"))


def _frontmatter_hooks(rig: Rig, artifact: Artifact, source: HookSource) -> HookMap | None:
    """Return the hook map a component artifact holds under frontmatter ``hooks``, or None when it holds none."""
    parsed = components.load(rig, artifact)
    hooks = parsed.data.get("hooks") if parsed.data is not None else None
    if not isinstance(hooks, dict):
        return None
    return HookMap(artifact, source, _str_keys(hooks), parsed.key_lines.get("hooks"))


def _hook_map(rig: Rig, artifact: Artifact) -> HookMap | None:
    """Return the hook map of one artifact, or None when its kind carries no hook map or its map is malformed."""
    source = _JSON_SOURCES.get(artifact.kind)
    if source is not None:
        return _json_hooks(rig, artifact, source)
    frontmatter_source = _FRONTMATTER_SOURCES.get(artifact.kind)
    if frontmatter_source is not None:
        return _frontmatter_hooks(rig, artifact, frontmatter_source)
    return None


def hook_maps(rig: Rig) -> Iterator[HookMap]:
    """Yield one hook map per artifact that carries one, in the order discovery recorded them.

    A settings file, a plugin ``hooks/hooks.json`` and a plugin manifest hold their map under a
    top-level ``hooks`` key; a skill, command or agent holds it in its frontmatter. An artifact
    whose text does not load, whose top level is not an object, or whose ``hooks`` is absent or
    not an object yields nothing: the rules that report those say why.

    Args:
        rig: The discovered setup.

    Yields:
        The hook maps, in rig order.
    """
    for artifact in rig.artifacts:
        found = _hook_map(rig, artifact)
        if found is not None:
            yield found


def _group_handlers(hook_map: HookMap, event: str, group: Mapping[str, object]) -> Iterator[HookHandler]:
    """Yield the handlers of one group's ``hooks`` list, skipping entries that are not objects."""
    entries = group.get("hooks")
    if not isinstance(entries, list):
        return
    for handler in entries:
        if isinstance(handler, dict):
            yield HookHandler(hook_map, event, group.get("matcher"), group, handler)


def handlers(hook_map: HookMap) -> Iterator[HookHandler]:
    """Yield every well-formed hook handler of ``hook_map``.

    The walk is event → list of groups → the group's ``hooks`` list → handler. An event whose
    value is not a list, a group that is not an object, a group without a ``hooks`` list and a
    handler that is not an object are all skipped silently.

    Args:
        hook_map: The map to walk.

    Yields:
        Each handler, with the event and the group it was written under.
    """
    for event, groups in hook_map.events.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if isinstance(group, dict):
                yield from _group_handlers(hook_map, event, group)


def _mcp_servers(rig: Rig, artifact: Artifact, source: McpSource) -> Iterator[McpServer]:
    """Yield the servers a JSON artifact holds under a top-level ``mcpServers`` object."""
    text = rig.text(artifact.path)
    doc = config.load(text)
    if not isinstance(doc.data, dict):
        return
    servers = doc.data.get("mcpServers")
    if not isinstance(servers, dict):
        return
    for name, server in servers.items():
        if isinstance(name, str):
            yield McpServer(artifact, source, name, server, config.key_line(text, name))


def mcp_servers(rig: Rig) -> Iterator[McpServer]:
    """Yield every MCP server the rig defines, in the order discovery recorded their artifacts.

    A repo or plugin ``.mcp.json`` and a plugin manifest hold their servers under a top-level
    ``mcpServers`` object. A file without that object, with one that is not an object, or with a
    server whose name is not a string defines none.

    Args:
        rig: The discovered setup.

    Yields:
        The server definitions, in rig order.
    """
    for artifact in rig.artifacts:
        if artifact.kind is Kind.MCP_CONFIG:
            source = McpSource.REPO_FILE if artifact.layer is Layer.REPO else McpSource.PLUGIN_FILE
        elif artifact.kind is Kind.PLUGIN_MANIFEST:
            source = McpSource.PLUGIN_MANIFEST
        else:
            continue
        yield from _mcp_servers(rig, artifact, source)
