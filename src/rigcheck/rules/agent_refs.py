"""Rules for what a subagent refers to: its tools and skills, its name against other agents, and a forked skill's agent."""

import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from rigcheck.discover import path_key
from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity
from rigcheck.parse.frontmatter import Frontmatter, as_bool
from rigcheck.rules import emit, rule
from rigcheck.rules.agents import BUILTIN_AGENTS, BUILTIN_TOOLS, PERMISSION_ONLY_TOOLS, TOOL_ALIASES, as_text, loaded_agents, show
from rigcheck.rules.components import case_match, components, load, plugin_name
from rigcheck.rules.skills import LISTED_KINDS

KNOWN_TOOLS = BUILTIN_TOOLS + tuple(TOOL_ALIASES)
"""Every tool name a ``tools`` or ``disallowedTools`` entry can resolve to."""

_MCP_TOOL = re.compile(r"mcp__[^\s_*\-](?:(?!__)\S)*(?:__(?:\*|[^\s_]\S*))?")
"""An MCP tool id: ``mcp__server``, ``mcp__server__*`` or ``mcp__server__tool``; the server is not checked."""

_SPECIFIER = re.compile(r"\s*\w+\s*\(.*\)\s*")
"""A tool entry with a parenthesized specifier, such as ``Bash(git push *)``."""

_TOOL_KEYS = ("tools", "disallowedTools")

_NAMED_LIMIT = 8
"""How many unknown entries one agent-tool-unknown message names before it counts the rest."""

_PERMISSION_ONLY = " (a legacy permission name with no tool)"

SkillCopy = tuple[tuple[int, int], bool]
"""One skill or command answering to a name: its precedence rank (lower wins) and whether it blocks preloading."""


def _split(text: str) -> list[str]:
    """Split a names string on commas and whitespace outside parentheses, as Claude Code splits an agent's list."""
    entries: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if depth == 0 and (char == "," or char.isspace()):
            entries.append("".join(current))
            current = []
            continue
        depth = max(0, depth + {"(": 1, ")": -1}.get(char, 0))
        current.append(char)
    entries.append("".join(current))
    return [entry for entry in entries if entry]


def _entries(value: Any) -> list[str]:
    """Return the entries of an agent's names value: each string, or each string item of a list, split into names."""
    if isinstance(value, str):
        texts = [value]
    elif isinstance(value, list):
        texts = [item for item in value if isinstance(item, str)]
    else:
        texts = []
    return [entry for text in texts for entry in _split(text)]


def _hint(value: str, candidates: tuple[str, ...]) -> str:
    match = case_match(value, candidates)
    return f' (did you mean "{match}"?)' if match is not None else ""


def _tool_name(entry: str) -> str:
    return entry.split("(", 1)[0].strip()


def _resolves(entry: str) -> bool:
    """Say whether a tools entry names a tool: a built-in name or alias, an MCP id, or a lone ``*``."""
    name = _tool_name(entry)
    return entry == "*" or name in KNOWN_TOOLS or _MCP_TOOL.fullmatch(name) is not None


def _canonical(name: str) -> str:
    return TOOL_ALIASES.get(name, name)


@rule(
    "agent-tools-unresolved",
    "core",
    Severity.ERROR,
    "List at least one tool by its exact name, such as Read or Bash, or an mcp__server__tool id.",
    ("official:AG4", "rigcheck:builtin-tables-probe"),
)
def agent_tools_unresolved(rig: Rig) -> Iterator[Finding]:
    """A subagent whose tools list names no tool at all, so it usually fails to launch."""
    for artifact, parsed, data in loaded_agents(rig):
        entries = _entries(data.get("tools"))
        if entries and not any(_resolves(entry) for entry in entries):
            message = "no entry in tools resolves to a tool, so the agent usually fails to launch"
            yield emit("agent-tools-unresolved", artifact, message, parsed.key_lines.get("tools", 1))


def _unknown_tools(entries: list[str]) -> list[str]:
    """Return each distinct entry that names no tool, with its hint; a case variant of a tool the list reaches is left out."""
    reachable = {_canonical(_tool_name(entry)) for entry in entries if _resolves(entry)}
    unknown: list[str] = []
    for entry in dict.fromkeys(entries):
        if _resolves(entry):
            continue
        name = _tool_name(entry)
        match = case_match(name, KNOWN_TOOLS)
        if match is not None and _canonical(match) in reachable:
            continue
        if name in PERMISSION_ONLY_TOOLS:
            unknown.append(show(entry) + _PERMISSION_ONLY)
        else:
            unknown.append(show(entry) + (f' (did you mean "{match}"?)' if match is not None else ""))
    return unknown


def _unknown_message(key: str, unknown: list[str]) -> str:
    if len(unknown) == 1:
        return f"{key} entry {unknown[0]} names no built-in tool or mcp__ tool; Claude Code ignores it"
    named = ", ".join(unknown[:_NAMED_LIMIT])
    extra = len(unknown) - _NAMED_LIMIT
    more = f" and {extra} more" if extra > 0 else ""
    return f"{key} entries {named}{more} name no built-in tool or mcp__ tool; Claude Code ignores them"


@rule(
    "agent-tool-unknown",
    "core",
    Severity.WARN,
    "Spell the tool exactly as Claude Code names it (case matters), use an mcp__server__tool id, or remove the entry.",
    ("official:AG4", "rigcheck:builtin-tables-probe"),
)
def agent_tool_unknown(rig: Rig) -> Iterator[Finding]:
    """Tools or disallowedTools entries that name no tool, so Claude Code ignores them."""
    for artifact, parsed, data in loaded_agents(rig):
        for key in _TOOL_KEYS:
            unknown = _unknown_tools(_entries(data.get(key)))
            if unknown:
                yield emit("agent-tool-unknown", artifact, _unknown_message(key, unknown), parsed.key_lines.get(key, 1))


@rule(
    "agent-disallowed-specifier",
    "core",
    Severity.WARN,
    "Name the whole tool in disallowedTools, or keep the tool and narrow it with a permission deny rule instead.",
    ("official:AG4",),
)
def agent_disallowed_specifier(rig: Rig) -> Iterator[Finding]:
    """A disallowedTools entry with a specifier, which still removes the whole tool."""
    for artifact, parsed, data in loaded_agents(rig):
        for entry in _entries(data.get("disallowedTools")):
            if _SPECIFIER.fullmatch(entry):
                message = f"disallowedTools entry {show(entry)} has a specifier, but it still removes the whole {_tool_name(entry)} tool"
                yield emit("agent-disallowed-specifier", artifact, message, parsed.key_lines.get("disallowedTools", 1))


def _command_name(path: Path) -> str:
    """Return a command's name: its path below ``.claude/commands`` joined with ``:``, or its stem in a plugin's flat folder."""
    for parent in path.parents:
        if parent.name == "commands" and parent.parent.name == ".claude":
            return ":".join(path.relative_to(parent).with_suffix("").parts)
    return path.stem


def _own_names(artifact: Artifact, data: dict[Any, Any]) -> set[str]:
    """Return the bare names a skill or command answers to: a command's name, or a skill's folder and frontmatter name."""
    if artifact.kind is Kind.COMMAND:
        return {_command_name(artifact.path)}
    names = {artifact.path.parent.name}
    name = data.get("name")
    if isinstance(name, str) and name.strip():
        names.add(name.strip())
    return names


def _rank(artifact: Artifact) -> tuple[int, int]:
    """Rank a copy for precedence: a skill before a command, then user before repo before plugin."""
    layers = {Layer.USER: 0, Layer.REPO: 1}
    return (0 if artifact.kind is Kind.SKILL else 1, layers.get(artifact.layer, 2))


class _SkillIndex:
    """The skills and commands a skills entry can name: shared names, and each plugin's bare names for its own agents."""

    def __init__(self, rig: Rig) -> None:
        self.shared: dict[str, list[SkillCopy]] = defaultdict(list)
        self.local: dict[str, dict[str, list[SkillCopy]]] = defaultdict(lambda: defaultdict(list))
        for artifact in components(rig, LISTED_KINDS):
            data = load(rig, artifact).data or {}
            copy = (_rank(artifact), as_bool(data.get("disable-model-invocation")) is True)
            plugin = plugin_name(artifact)
            for name in _own_names(artifact, data):
                if plugin is None:
                    self.shared[name].append(copy)
                else:
                    self.shared[f"{plugin}:{name}"].append(copy)
                    self.local[plugin][name].append(copy)

    def _copies(self, agent: Artifact, entry: str) -> list[SkillCopy]:
        own = self.local.get(plugin_name(agent) or "", {})
        return self.shared.get(entry, []) + own.get(entry, [])

    def blocked(self, agent: Artifact, entry: str) -> bool | None:
        """Say whether the winning copy ``entry`` names blocks preloading; None when it names nothing."""
        copies = self._copies(agent, entry)
        return min(copies)[1] if copies else None

    def names(self, agent: Artifact) -> tuple[str, ...]:
        """Return every name ``agent`` can use, for a did-you-mean."""
        own = self.local.get(plugin_name(agent) or "", {})
        return tuple(sorted(set(self.shared) | set(own)))


def _skill_entries(rig: Rig) -> Iterator[tuple[Artifact, Frontmatter, str]]:
    for artifact, parsed, data in loaded_agents(rig):
        for entry in _entries(data.get("skills")):
            yield artifact, parsed, entry


@rule(
    "agent-skill-missing",
    "core",
    Severity.ERROR,
    "Name a skill folder or command that exists (another plugin's as plugin:name), or remove the entry.",
    ("official:AG8",),
)
def agent_skill_missing(rig: Rig) -> Iterator[Finding]:
    """A subagent skills entry that names no skill or command."""
    index = _SkillIndex(rig)
    for artifact, parsed, entry in _skill_entries(rig):
        if index.blocked(artifact, entry) is None:
            hint = _hint(entry, index.names(artifact))
            message = f"skills entry {show(entry)} names no skill or command{hint}, so nothing is preloaded for it"
            yield emit("agent-skill-missing", artifact, message, parsed.key_lines.get("skills", 1))


@rule(
    "agent-skill-not-preloadable",
    "core",
    Severity.WARN,
    "Remove disable-model-invocation from the skill, or drop the skill from the agent's skills list.",
    ("official:AG8",),
)
def agent_skill_not_preloadable(rig: Rig) -> Iterator[Finding]:
    """A subagent skills entry naming a skill that disable-model-invocation keeps out of subagents."""
    index = _SkillIndex(rig)
    for artifact, parsed, entry in _skill_entries(rig):
        if index.blocked(artifact, entry) is True:
            message = f"skills entry {show(entry)} names a skill with disable-model-invocation: true, which also stops preloading into subagents"
            yield emit("agent-skill-not-preloadable", artifact, message, parsed.key_lines.get("skills", 1))


def _agent_name(data: dict[Any, Any]) -> str:
    return str(as_text(data.get("name"))).strip()


def _effective_name(artifact: Artifact, data: dict[Any, Any]) -> str:
    """Return the name Claude Code lists the agent under: ``<plugin>:<name>`` for a plugin agent."""
    plugin = plugin_name(artifact)
    return _agent_name(data) if plugin is None else f"{plugin}:{_agent_name(data)}"


def _display(rig: Rig, path: Path) -> str:
    """Show ``path`` relative to the repo, or to home as ``~/``, or in full."""
    for base, prefix in ((rig.repo_root, ""), (rig.home, "~/")):
        if path.is_relative_to(base):
            return prefix + path.relative_to(base).as_posix()
    return path.as_posix()


@rule(
    "agent-name-collision",
    "core",
    Severity.INFO,
    "Give each agent a name of its own: of two agents with one name, Claude Code uses the project's over the user's, "
    "and the first file within one folder or plugin.",
    ("official:AG11",),
)
def agent_name_collision(rig: Rig) -> Iterator[Finding]:
    """A subagent whose name another agent of higher precedence also uses, so it is never used."""
    groups: dict[str, list[tuple[Artifact, Frontmatter]]] = defaultdict(list)
    for artifact, parsed, data in loaded_agents(rig):
        groups[_effective_name(artifact, data)].append((artifact, parsed))
    for name, agents in groups.items():
        ranked = sorted(agents, key=lambda agent: (agent[0].layer.rank, path_key(agent[0].path)))
        winner = _display(rig, ranked[0][0].path)
        for artifact, parsed in ranked[1:]:
            message = f"agent name {show(name)} is also defined in {winner}, which takes precedence, so this agent is never used"
            yield emit("agent-name-collision", artifact, message, parsed.key_lines.get("name", 1))


def _agent_names(rig: Rig) -> tuple[set[str], dict[str, set[str]]]:
    """Return the agent names any skill can fork to, and each plugin's own agents by bare name."""
    names = set(BUILTIN_AGENTS)
    by_plugin: dict[str, set[str]] = defaultdict(set)
    for artifact, _, data in loaded_agents(rig):
        names.add(_effective_name(artifact, data))
        plugin = plugin_name(artifact)
        if plugin is not None:
            by_plugin[plugin].add(_agent_name(data))
    return names, by_plugin


def _forked_agent(data: dict[Any, Any] | None) -> str | None:
    agent = (data or {}).get("agent")
    if (data or {}).get("context") != "fork" or not isinstance(agent, str) or not agent.strip():
        return None
    return agent.strip()


@rule(
    "skill-agent-missing",
    "core",
    Severity.ERROR,
    "Name a built-in agent (Explore, Plan, general-purpose, ...) or a custom subagent that exists, or remove agent.",
    ("official:SK20", "rigcheck:builtin-tables-probe"),
)
def skill_agent_missing(rig: Rig) -> Iterator[Finding]:
    """A forked skill whose agent names no built-in or custom subagent."""
    names, by_plugin = _agent_names(rig)
    for artifact in components(rig, LISTED_KINDS):
        parsed = load(rig, artifact)
        agent = _forked_agent(parsed.data)
        known = names | by_plugin.get(plugin_name(artifact) or "", set())
        if agent is not None and agent not in known:
            message = f"agent {show(agent)} names no built-in or custom subagent{_hint(agent, tuple(sorted(known)))}"
            yield emit("skill-agent-missing", artifact, message, parsed.key_lines.get("agent", 1))
