"""Rules for subagent definitions (.claude/agents/*.md): files Claude Code skips, unknown keys and invalid values."""

import json
import re
import unicodedata
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

from rigcheck.model import Artifact, Finding, Kind, Layer, Rig, Severity
from rigcheck.parse.frontmatter import Frontmatter, as_bool
from rigcheck.rules import emit, rule
from rigcheck.rules.components import (
    AGENT_KEYS,
    case_match,
    components,
    load,
    misplaced_fence,
    unknown_key_message,
    yaml_line,
    yaml_reason,
)

# Built-in names measured from Claude Code 2.1.283 on 2026-09-27 (docs/research/builtin-tables-probe.md).
BUILTIN_TOOLS = (
    "Agent",
    "Artifact",
    "ArtifactCheck",
    "ArtifactComments",
    "ArtifactData",
    "AskUserQuestion",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Edit",
    "EndConversation",
    "EnterPlanMode",
    "EnterWorktree",
    "ExitPlanMode",
    "ExitWorktree",
    "Glob",
    "Grep",
    "LSP",
    "ListAgents",
    "ListMcpResourcesTool",
    "Monitor",
    "NotebookEdit",
    "PowerShell",
    "PushNotification",
    "REPL",
    "Read",
    "ReadMcpResourceDirTool",
    "ReadMcpResourceTool",
    "RemoteTrigger",
    "ReportFindings",
    "ScheduleWakeup",
    "SendFeedback",
    "SendMessage",
    "SendUserFile",
    "SendUserMessage",
    "ShareOnboardingGuide",
    "Skill",
    "SubagentHandback",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskOutput",
    "TaskStop",
    "TaskUpdate",
    "TodoWrite",
    "ToolSearch",
    "WaitForMcpServers",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write",
)
"""The tool names Claude Code builds in, core and deferred."""

TOOL_ALIASES = {
    "Brief": "SendUserMessage",
    "KillBash": "TaskStop",
    "KillShell": "TaskStop",
    "ListMcpResources": "ListMcpResourcesTool",
    "ListPeers": "ListAgents",
    "ReadMcpResource": "ReadMcpResourceTool",
    "ReadMcpResourceDir": "ReadMcpResourceDirTool",
    "RunWorkflow": "Workflow",
    "Task": "Agent",
}
"""Older tool names Claude Code still resolves, each to the built-in tool it now names (the probe's bin alias map)."""

PERMISSION_ONLY_TOOLS = ("LS", "MultiEdit", "NotebookRead")
"""Legacy names Claude Code accepts only in permission lists; no tool answers to them (the probe's legacy permission lists)."""

BUILTIN_AGENTS = ("Explore", "Plan", "claude", "claude-code-guide", "fork", "general-purpose", "statusline-setup", "web-fetch")
"""The subagent names Claude Code builds in."""

MODEL_ALIASES = ("sonnet", "opus", "haiku", "fable", "inherit", "opusplan", "best", "default", "sonnet[1m]", "opus[1m]", "fable[1m]")
"""The model aliases Claude Code accepts in an agent's ``model`` (agent-values-probe.md); a full id starts with ``claude-``."""

EFFORTS = ("low", "medium", "high", "xhigh", "max")
COLORS = ("red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan")
PERMISSION_MODES = ("default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan", "manual")
MEMORY_SCOPES = ("user", "project", "local")
ISOLATIONS = ("worktree",)
CACHE_TTLS = ("5m", "1h")

_PLUGIN_IGNORED = frozenset({"permissionMode", "hooks", "mcpServers", "initialPrompt"})
"""Keys Claude Code ignores in a plugin's agent, so their values are not checked there (official.md AG5)."""

_DIGITS = re.compile(r"[0-9]+")
_SKIPS = "so Claude Code skips the agent"
_IGNORED = "Claude Code ignores it"
_FAILS = "so the agent fails when it starts"
_INVALID = "agent-value-invalid"
_CASE = "agent-value-case"

Problem = tuple[str, str]
"""A value finding: its rule id and message."""


def show(value: Any) -> str:
    """Return ``value`` as JSON, the way finding messages quote a frontmatter value.

    Args:
        value: A frontmatter value.

    Returns:
        Its JSON text, non-ASCII kept and unknown types shown through ``str``.
    """
    return json.dumps(value, ensure_ascii=False, default=str)


def as_text(value: Any) -> Any:
    """Read a YAML 1.1 boolean, date or datetime as the string Claude Code's YAML 1.2 parser keeps.

    Args:
        value: A frontmatter value.

    Returns:
        The value as a string when it is a boolean or date; otherwise the value unchanged.
    """
    return str(value) if isinstance(value, bool | date) else value


def _name_problem(data: dict[Any, Any]) -> str | None:
    name = as_text(data.get("name"))
    if name is None:
        return "no name, so Claude Code treats the file as documentation and skips it"
    if not isinstance(name, str):
        return f"name is not a string, {_SKIPS}"
    if not name.strip():
        return f"name is empty, {_SKIPS}"
    if name.strip().startswith("-"):
        return f'name {show(name)} starts with "-", {_SKIPS}'
    if ":" in unicodedata.normalize("NFKC", name):
        return f'name {show(name)} holds ":", {_SKIPS}'
    return None


def _description_problem(data: dict[Any, Any]) -> str | None:
    description = as_text(data.get("description"))
    if description is None:
        return f"no description, {_SKIPS}"
    if not isinstance(description, str):
        return f"description is not a string, {_SKIPS}"
    if not description.strip():
        return f"description is empty, {_SKIPS}"
    return None


def _skip_reason(rig: Rig, artifact: Artifact, parsed: Frontmatter) -> tuple[str, int] | None:
    """Say why Claude Code skips the agent, or drops its settings, and where; None when it loads."""
    misplaced = misplaced_fence(rig.text(artifact.path))
    if misplaced is not None:
        line, problem = misplaced
        return f"{problem}, {_SKIPS}", line
    if not parsed.present:
        return None
    if parsed.load_error is not None:
        error = parsed.load_error
        message = f'Claude Code rejects the frontmatter ({yaml_reason(error)}), so the agent loads as "{artifact.path.stem}" with no settings'
        return message, yaml_line(error)
    data = parsed.data or {}
    for key, problem in (("name", _name_problem(data)), ("description", _description_problem(data))):
        if problem is not None:
            return problem, parsed.key_lines.get(key, 1)
    return None


def loaded_agents(rig: Rig) -> Iterator[tuple[Artifact, Frontmatter, dict[Any, Any]]]:
    """Yield each agent Claude Code loads with its settings.

    Args:
        rig: The discovered setup.

    Yields:
        The agent file, its parsed frontmatter and the frontmatter mapping; skipped agents are left out.
    """
    for artifact in components(rig, (Kind.AGENT,)):
        parsed = load(rig, artifact)
        if parsed.data is not None and _skip_reason(rig, artifact, parsed) is None:
            yield artifact, parsed, parsed.data


@rule(
    "agent-skipped",
    "core",
    Severity.ERROR,
    "Put the opening --- alone on line 1, keep the frontmatter valid YAML with LF line endings, "
    "and give the agent a name (no leading -, no :) and a non-empty description.",
    ("official:AG1", "rigcheck:frontmatter-probe"),
)
def agent_skipped(rig: Rig) -> Iterator[Finding]:
    """A subagent file Claude Code skips without a word, or loads with none of its settings."""
    for artifact in components(rig, (Kind.AGENT,)):
        reason = _skip_reason(rig, artifact, load(rig, artifact))
        if reason is not None:
            yield emit("agent-skipped", artifact, *reason)


def _unknown_keys(parsed: Frontmatter, data: dict[Any, Any]) -> Iterator[tuple[str, int]]:
    """Yield the message and line of each top-level key, and each ``experimental`` sub-key, Claude Code ignores."""
    for key in (key for key in data if isinstance(key, str)):
        line = parsed.key_lines.get(key, 1)
        if key == "cacheTtl":
            yield f'unknown key "cacheTtl" (write it inside experimental); {_IGNORED}', line
        elif key not in AGENT_KEYS:
            yield unknown_key_message(key, AGENT_KEYS), line
    experimental = data.get("experimental")
    if isinstance(experimental, dict):
        line = parsed.key_lines.get("experimental", 1)
        for sub in experimental:
            if isinstance(sub, str) and sub != "cacheTtl":
                yield unknown_key_message(f"experimental.{sub}", frozenset({"experimental.cacheTtl"})), line


@rule(
    "agent-key-unknown",
    "core",
    Severity.WARN,
    "Rename the key to the camelCase field Claude Code recognizes, or remove it; write cacheTtl inside experimental.",
    ("official:AG2",),
)
def agent_key_unknown(rig: Rig) -> Iterator[Finding]:
    """A subagent frontmatter key Claude Code does not recognize, so it is ignored."""
    for artifact, parsed, data in loaded_agents(rig):
        for message, line in _unknown_keys(parsed, data):
            yield emit("agent-key-unknown", artifact, message, line)


@rule(
    "agent-key-ignored-in-plugin",
    "core",
    Severity.WARN,
    "Remove the key, or move the agent out of the plugin, if it runs as a subagent: Claude Code ignores this key for a plugin's subagents.",
    ("official:AG5", "official:PL3", "rigcheck:agent-values-probe"),
)
def agent_key_ignored_in_plugin(rig: Rig) -> Iterator[Finding]:
    """A plugin agent's key Claude Code ignores when the agent runs as a subagent."""
    for artifact, parsed, data in loaded_agents(rig):
        if artifact.layer is not Layer.PLUGIN:
            continue
        for key in (key for key in data if isinstance(key, str) and key in _PLUGIN_IGNORED):
            message = f"{key} is ignored when a plugin's agent runs as a subagent"
            yield emit("agent-key-ignored-in-plugin", artifact, message, parsed.key_lines.get(key, 1))


def _check_model(key: str, value: Any) -> Problem | None:
    if isinstance(value, str) and (value in MODEL_ALIASES or value.startswith("claude-")):
        return None
    alias = case_match(value, MODEL_ALIASES)
    if alias is not None:
        return _CASE, f'{key} {show(value)}: use the documented spelling "{alias}"'
    if isinstance(value, str) and value.lower().startswith("claude-"):
        return _INVALID, f'{key} {show(value)} is not a model id (did you mean "{value.lower()}"?), {_FAILS}'
    return _INVALID, f"{key} {show(value)} is not a model alias or a claude- model id, {_FAILS}"


def _check_effort(key: str, value: Any) -> Problem | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return None
    if isinstance(value, str) and (value in EFFORTS or _DIGITS.fullmatch(value)):
        return None
    level = case_match(value, EFFORTS)
    if level is not None:
        return _CASE, f'{key} {show(value)}: use the documented spelling "{level}"'
    return _INVALID, f"{key} {show(value)} is not one of {', '.join(EFFORTS)} or an integer; {_IGNORED}"


def _enum(allowed: tuple[str, ...]) -> Callable[[str, Any], Problem | None]:
    """Build the check of a key whose value must be one of ``allowed``, spelled exactly."""

    def check(key: str, value: Any) -> Problem | None:
        if isinstance(value, str) and value in allowed:
            return None
        match = case_match(value, allowed)
        if match is not None:
            return _INVALID, f'{key} {show(value)} is not valid (did you mean "{match}"?); {_IGNORED}'
        return _INVALID, f"{key} {show(value)} is not one of {', '.join(allowed)}; {_IGNORED}"

    return check


def _check_max_turns(key: str, value: Any) -> Problem | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
        return None
    return _INVALID, f"{key} {show(value)} is not a positive integer; {_IGNORED}"


def _check_bool(key: str, value: Any) -> Problem | None:
    if as_bool(value) is not None:
        return None
    return _INVALID, f"{key} {show(value)} is not true or false; {_IGNORED}"


def _check_names(key: str, value: Any) -> Problem | None:
    if isinstance(value, str):
        return None
    if not isinstance(value, list):
        return _INVALID, f"{key} {show(value)} is not a string or a list of strings"
    bad = [item for item in value if not isinstance(item, str)]
    return (_INVALID, f"{key} holds {show(bad[0])}, which is not a string") if bad else None


def _check_string(key: str, value: Any) -> Problem | None:
    return None if isinstance(value, str) else (_INVALID, f"{key} {show(value)} is not a string")


def _check_experimental(key: str, value: Any) -> Problem | None:
    if not isinstance(value, dict):
        return _INVALID, f"{key} {show(value)} is not a mapping"
    ttl = value.get("cacheTtl")
    return None if ttl is None else _enum(CACHE_TTLS)(f"{key}.cacheTtl", ttl)


_CHECKS: dict[str, Callable[[str, Any], Problem | None]] = {
    "model": _check_model,
    "effort": _check_effort,
    "color": _enum(COLORS),
    "permissionMode": _enum(PERMISSION_MODES),
    "memory": _enum(MEMORY_SCOPES),
    "isolation": _enum(ISOLATIONS),
    "maxTurns": _check_max_turns,
    "background": _check_bool,
    "omitClaudeMd": _check_bool,
    "tools": _check_names,
    "disallowedTools": _check_names,
    "skills": _check_names,
    "initialPrompt": _check_string,
    "experimental": _check_experimental,
}
"""The value check of each agent key that has one; ``hooks`` and ``mcpServers`` have none."""


def _value_problems(artifact: Artifact, parsed: Frontmatter, data: dict[Any, Any]) -> Iterator[tuple[str, str, int]]:
    """Yield the rule id, message and line of each key whose value Claude Code cannot use; at most one per key."""
    for key, value in data.items():
        check = _CHECKS.get(key) if isinstance(key, str) else None
        if check is None or value is None or (artifact.layer is Layer.PLUGIN and key in _PLUGIN_IGNORED):
            continue
        problem = check(key, value)
        if problem is not None:
            yield problem[0], problem[1], parsed.key_lines.get(key, 1)


def _value_findings(rig: Rig, rule_id: str) -> Iterator[Finding]:
    for artifact, parsed, data in loaded_agents(rig):
        for found_id, message, line in _value_problems(artifact, parsed, data):
            if found_id == rule_id:
                yield emit(rule_id, artifact, message, line)


@rule(
    _INVALID,
    "core",
    Severity.ERROR,
    "Use a value the message names, with its exact spelling and type; Claude Code drops a value it cannot use.",
    ("official:AG3", "rigcheck:agent-values-probe"),
)
def agent_value_invalid(rig: Rig) -> Iterator[Finding]:
    """A subagent setting whose value Claude Code drops, or whose model fails when the agent starts."""
    yield from _value_findings(rig, _INVALID)


@rule(
    _CASE,
    "core",
    Severity.WARN,
    "Write the value in its documented lower-case spelling.",
    ("official:AG3", "rigcheck:agent-values-probe"),
)
def agent_value_case(rig: Rig) -> Iterator[Finding]:
    """A model or effort value Claude Code reads only because it folds case."""
    yield from _value_findings(rig, _CASE)
