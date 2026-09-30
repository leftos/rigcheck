"""Rules for hook definitions: events, handler shapes, matchers and options."""

import math
import re
from collections.abc import Iterator, Mapping

from rigcheck.model import Finding, Rig, Severity
from rigcheck.parse.config import key_line
from rigcheck.parse.frontmatter import as_bool
from rigcheck.rules import emit, rule
from rigcheck.rules.agents import BUILTIN_TOOLS
from rigcheck.rules.config import HookHandler, HookMap, HookSource, handlers, hook_maps

# Headings of the hooks reference, 2026-09-27 (docs/research/official.md, hooks section).
HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "Setup",
        "InstructionsLoaded",
        "UserPromptSubmit",
        "UserPromptExpansion",
        "MessageDisplay",
        "PreToolUse",
        "PermissionRequest",
        "PostToolUse",
        "PostToolUseFailure",
        "PostToolBatch",
        "PermissionDenied",
        "Notification",
        "SubagentStart",
        "SubagentStop",
        "TaskCreated",
        "TaskCompleted",
        "Stop",
        "StopFailure",
        "TeammateIdle",
        "ConfigChange",
        "CwdChanged",
        "DirectoryAdded",
        "FileChanged",
        "WorktreeCreate",
        "WorktreeRemove",
        "PreCompact",
        "PostCompact",
        "PreModelSwitch",
        "PostModelSwitch",
        "SessionEnd",
        "Elicitation",
        "ElicitationResult",
    }
)

TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"})
"""The events whose matcher is a tool name and on which ``if`` is evaluated."""

HANDLER_TYPES = ("command", "http", "mcp_tool", "prompt", "agent")
"""The handler ``type`` values Claude Code runs."""

_REQUIRED_FIELD = {"command": "command", "prompt": "prompt", "agent": "prompt"}
"""The field each handler type needs, for the types this module checks beyond ``type``."""

_EXACT_MATCH = re.compile(r"[A-Za-z0-9_|-]*")
"""A matcher made only of these characters is compared as an exact string (or ``|`` list), not as a regex."""

_JSON_SOURCES = frozenset({HookSource.SETTINGS, HookSource.PLUGIN_HOOKS, HookSource.PLUGIN_MANIFEST})
"""The hook sources written as JSON, whose event keys ``key_line`` can locate."""

_MCP_PREFIX = "mcp__"


def _event_line(rig: Rig, hook_map: HookMap, event: str) -> int:
    """Return the line of ``event``'s key in a JSON source, else the ``hooks`` key's line, else 1."""
    line = None
    if hook_map.source in _JSON_SOURCES:
        line = key_line(rig.text(hook_map.artifact.path), ("hooks", event))
    return line or hook_map.line or 1


def _unknown_event_message(event: str) -> str:
    """Return the finding message for an unknown event name, with a case-fix suggestion when one exists."""
    message = f'event "{event}" is not a Claude Code hook event, so its hooks never run'
    suggestion = next((name for name in sorted(HOOK_EVENTS) if name.casefold() == event.casefold()), None)
    return message if suggestion is None else f'{message}; did you mean "{suggestion}"?'


@rule(
    "hook-event-unknown",
    "core",
    Severity.ERROR,
    "Rename the event to a documented hook event (names are case-sensitive) or remove it; Claude Code skips unknown events.",
    ("official:HK1",),
)
def hook_event_unknown(rig: Rig) -> Iterator[Finding]:
    """A hook event name Claude Code does not know, so its hooks never run."""
    for hook_map in hook_maps(rig):
        for event in hook_map.events:
            if event not in HOOK_EVENTS:
                yield emit("hook-event-unknown", hook_map.artifact, _unknown_event_message(event), _event_line(rig, hook_map, event))


def _handler_problem(event: str, handler: object) -> str | None:
    """Return what is wrong with one handler's shape, or None when it has the fields its type needs."""
    if not isinstance(handler, dict):
        return f"{event} hook is not an object"
    kind = handler.get("type")
    if kind is None:
        return f"{event} hook has no type"
    if kind not in HANDLER_TYPES:
        return f'{event} hook has unknown type "{kind}"'
    field = _REQUIRED_FIELD.get(kind)
    if field is None:
        return None
    value = handler.get(field)
    if isinstance(value, str) and value:
        return None
    return f'{event} hook of type "{kind}" has no {field}'


def _group_problems(event: str, group: object) -> Iterator[str]:
    """Yield what is wrong with one matcher group and the handlers it holds."""
    if not isinstance(group, dict):
        yield f"{event} matcher group is not an object"
        return
    entries = group.get("hooks")
    if not isinstance(entries, list):
        yield f"{event} matcher group has no hooks list"
        return
    for handler in entries:
        problem = _handler_problem(event, handler)
        if problem is not None:
            yield problem


def _event_problems(event: str, groups: object) -> Iterator[str]:
    """Yield what is wrong with one event's value, walking its groups and handlers."""
    if not isinstance(groups, list):
        yield f"{event} hooks are not a list of matcher groups"
        return
    for group in groups:
        yield from _group_problems(event, group)


@rule(
    "hook-handler-invalid",
    "core",
    Severity.ERROR,
    "Give each handler a type (command, http, mcp_tool, prompt or agent) "
    "and the field that type needs (command, or prompt for prompt and agent hooks).",
    ("official:HK2",),
)
def hook_handler_invalid(rig: Rig) -> Iterator[Finding]:
    """A hook entry without the shape Claude Code needs to run it."""
    for hook_map in hook_maps(rig):
        for event, groups in hook_map.events.items():
            for problem in _event_problems(event, groups):
                yield emit("hook-handler-invalid", hook_map.artifact, problem, _event_line(rig, hook_map, event))


def _tool_matchers(hook_map: HookMap) -> Iterator[tuple[str, str]]:
    """Yield ``(event, matcher)`` for each group of a tool event whose ``matcher`` is a string."""
    for event, groups in hook_map.events.items():
        if event not in TOOL_EVENTS or not isinstance(groups, list):
            continue
        for group in groups:
            matcher = group.get("matcher") if isinstance(group, Mapping) else None
            if isinstance(matcher, str):
                yield event, matcher


def _exact_mcp_alternative(matcher: str) -> str | None:
    """Return the first alternative of an exact-match matcher that names an MCP server but no tool, or None."""
    if not _EXACT_MATCH.fullmatch(matcher):
        return None
    for alternative in matcher.split("|"):
        if alternative.startswith(_MCP_PREFIX) and "__" not in alternative.removeprefix(_MCP_PREFIX):
            return alternative
    return None


@rule(
    "hook-matcher-mcp-exact",
    "core",
    Severity.ERROR,
    "Append __.* (for example mcp__memory__.*) so the matcher is a regex over the server's tools.",
    ("official:HK3",),
)
def hook_matcher_mcp_exact(rig: Rig) -> Iterator[Finding]:
    """A tool matcher naming an MCP server without __.*, which matches no tool."""
    for hook_map in hook_maps(rig):
        for event, matcher in _tool_matchers(hook_map):
            alternative = _exact_mcp_alternative(matcher)
            if alternative is not None:
                message = f'matcher "{alternative}" is compared as an exact string and matches no tool'
                yield emit("hook-matcher-mcp-exact", hook_map.artifact, message, _event_line(rig, hook_map, event))


def _partial_matches(matcher: str) -> list[str]:
    """Return the built-in tools a regex matcher finds inside a longer name without matching the whole name."""
    if _EXACT_MATCH.fullmatch(matcher):
        return []
    try:
        pattern = re.compile(matcher)
    except re.error:
        # A pattern re rejects is not an unanchored regex; this rule has nothing to say about it.
        return []
    return [tool for tool in BUILTIN_TOOLS if pattern.search(tool) and not pattern.fullmatch(tool)]


@rule(
    "hook-matcher-unanchored",
    "core",
    Severity.WARN,
    "Wrap the pattern in ^ and $ when you mean a whole tool name.",
    ("official:HK4",),
)
def hook_matcher_unanchored(rig: Rig) -> Iterator[Finding]:
    """A regex tool matcher without ^ and $ that also matches longer tool names."""
    for hook_map in hook_maps(rig):
        for event, matcher in _tool_matchers(hook_map):
            tools = _partial_matches(matcher)
            if tools:
                message = f'matcher "{matcher}" also matches {", ".join(tools[:3])}'
                yield emit("hook-matcher-unanchored", hook_map.artifact, message, _event_line(rig, hook_map, event))


def _if_problems(hook: HookHandler) -> Iterator[str]:
    """Yield why a handler's ``if`` is never evaluated or is not one permission rule."""
    if "if" not in hook.handler:
        return
    if hook.event in HOOK_EVENTS and hook.event not in TOOL_EVENTS:
        yield f'"if" on {hook.event} is never evaluated, so this hook never runs'
    condition = hook.handler["if"]
    compound = isinstance(condition, str) and ("&&" in condition or "||" in condition)
    if isinstance(condition, list) or compound:
        yield '"if" takes one permission rule; it has no &&, || or list form'


@rule(
    "hook-if-ignored",
    "core",
    Severity.ERROR,
    "Move the hook to a tool event (PreToolUse, PostToolUse, PostToolUseFailure, PermissionRequest, PermissionDenied) "
    "and give if a single permission rule.",
    ("official:HK5",),
)
def hook_if_ignored(rig: Rig) -> Iterator[Finding]:
    """A hook whose if is on a non-tool event or is not one permission rule, so the hook never runs."""
    for hook_map in hook_maps(rig):
        for hook in handlers(hook_map):
            for problem in _if_problems(hook):
                yield emit("hook-if-ignored", hook_map.artifact, problem, _event_line(rig, hook_map, hook.event))


@rule(
    "hook-once-ignored",
    "core",
    Severity.WARN,
    "Remove once, or declare the hook in a skill's frontmatter.",
    ("official:HK6",),
)
def hook_once_ignored(rig: Rig) -> Iterator[Finding]:
    """A hook with once outside skill frontmatter, where Claude Code ignores it."""
    for hook_map in hook_maps(rig):
        if hook_map.source is HookSource.SKILL_FRONTMATTER:
            continue
        for hook in handlers(hook_map):
            if "once" in hook.handler:
                message = '"once" is honored only in skill frontmatter; here it is ignored'
                yield emit("hook-once-ignored", hook_map.artifact, message, _event_line(rig, hook_map, hook.event))


def _timeout(handler: Mapping[str, object]) -> int | float | None:
    """Return the handler's ``timeout`` when it is a finite number, else None; a bool is not a number here."""
    value = handler.get("timeout")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        finite = math.isfinite(float(value))
    except OverflowError:
        # JSON integers are unbounded; one too large for a float is no timeout Claude Code can honor either.
        return None
    return value if finite else None


def _is_async(hook: HookHandler) -> bool:
    """Return whether the handler sets ``async``: JSON ``true``, or a frontmatter flag Claude Code reads as true."""
    value = hook.handler.get("async")
    if hook.map.source in _JSON_SOURCES:
        return value is True
    return as_bool(value) is True


def _timeout_problems(hook: HookHandler) -> Iterator[str]:
    """Yield why a handler's numeric ``timeout`` is longer than its event allows or is not enforced."""
    timeout = _timeout(hook.handler)
    if timeout is None:
        return
    if hook.event == "UserPromptSubmit" and timeout > 30:
        yield f"a stuck UserPromptSubmit hook stalls the session for up to {timeout:g} s; the default is 30 s"
    if hook.event == "SessionEnd" and timeout > 1.5:
        yield f"SessionEnd hooks share a 1.5 s budget, so a {timeout:g} s timeout is never reached"
    if _is_async(hook):
        yield "timeout is not enforced on an async hook"


@rule(
    "hook-timeout-long",
    "core",
    Severity.INFO,
    "Lower the timeout, or drop it on async hooks.",
    ("official:HK13",),
)
def hook_timeout_long(rig: Rig) -> Iterator[Finding]:
    """A hook timeout past what its event allows, or on an async hook where it is not enforced."""
    for hook_map in hook_maps(rig):
        for hook in handlers(hook_map):
            for problem in _timeout_problems(hook):
                yield emit("hook-timeout-long", hook_map.artifact, problem, _event_line(rig, hook_map, hook.event))
