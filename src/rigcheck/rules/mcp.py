"""Rules for MCP server definitions: transport type, unexpanded references, credential literals and scope conflicts.

A server's ``type`` must be one Claude Code accepts. A project ``.mcp.json`` must give
``${CLAUDE_PROJECT_DIR}`` a default in ``command`` and ``args``, a remote server's ``url`` and
``headers`` must not reference a variable Claude Code reads as empty there, and a stdio server's
``command``, ``args`` and ``env`` must not reference one Claude Code blanks in every server. A
git-tracked project file or a plugin config must not hold a credential literal in ``env``,
``headers``, ``args`` or ``url``, and the same server name defined in a project file and in
``~/.claude.json`` with a different endpoint is a conflict.
"""

import re
from collections.abc import Iterator, Mapping

from rigcheck.model import Finding, McpScope, Rig, Severity
from rigcheck.parse import config
from rigcheck.parse.secrets import SecretHit, find_secrets
from rigcheck.rules import emit, rule
from rigcheck.rules.config import McpServer, McpSource, mcp_servers
from rigcheck.rules.mcp_credentials import plain_blanked, remote_blanked

_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}")
"""A ``${NAME}`` or ``${NAME:-default}`` reference; a bare ``$NAME`` is not expanded in ``.mcp.json``."""

_VALID_TYPES = frozenset({"stdio", "http", "streamable-http", "sse", "ws"})
_REMOTE_TYPES = frozenset({"http", "streamable-http", "sse", "ws"})


def _configured(rig: Rig) -> Iterator[tuple[McpServer, Mapping[str, object]]]:
    """Yield every server whose value is an object, with that object."""
    for server in mcp_servers(rig):
        if isinstance(server.config, dict):
            yield server, server.config


def _key_line(rig: Rig, server: McpServer, *keys: str) -> int | None:
    """Return the line of the deepest of ``keys`` the server's entry shows, or the server's own line.

    Args:
        rig: The discovered setup.
        server: The server whose entry is searched.
        *keys: The key path below the server's own path, outermost first.
    """
    text = rig.text(server.artifact.path)
    for depth in range(len(keys), 0, -1):
        line = config.key_line(text, (*server.path, *keys[:depth]))
        if line is not None:
            return line
    return server.line


def _type_problem(name: str, value: object) -> str | None:
    if isinstance(value, str):
        if value == "sdk":
            return f"server `{name}` has type `sdk`, which Claude Code skips outside an Agent SDK host"
        if value in _VALID_TYPES:
            return None
        return f"server `{name}` has unknown type `{value}`; Claude Code accepts stdio, http (streamable-http), sse and ws"
    return f"server `{name}` has a type that is not a string"


@rule(
    "mcp-type-invalid",
    "core",
    Severity.ERROR,
    "Set type to stdio, http, sse or ws; an sdk server runs only inside an Agent SDK host.",
    ("official:MC5",),
)
def mcp_type_invalid(rig: Rig) -> Iterator[Finding]:
    """An MCP server whose ``type`` Claude Code does not accept, or ``sdk``, which it skips outside an Agent SDK host."""
    for server, value in _configured(rig):
        if "type" not in value:
            continue
        message = _type_problem(server.name, value["type"])
        if message is not None:
            yield emit("mcp-type-invalid", server.artifact, message, _key_line(rig, server, "type"))


def _project_dir_without_default(text: object) -> bool:
    if not isinstance(text, str):
        return False
    return any(match.group(1) == "CLAUDE_PROJECT_DIR" and match.group(2) is None for match in _REFERENCE.finditer(text))


def _project_dir_field(value: Mapping[str, object]) -> str | None:
    """Return ``command`` or ``args``, whichever first references the project dir with no default."""
    if _project_dir_without_default(value.get("command")):
        return "command"
    args = value.get("args")
    if isinstance(args, list) and any(_project_dir_without_default(item) for item in args):
        return "args"
    return None


@rule(
    "mcp-project-dir-no-default",
    "core",
    Severity.WARN,
    "Write ${CLAUDE_PROJECT_DIR:-.}: the variable is set in the server's environment, not Claude Code's, so the reference needs a default.",
    ("official:MC4",),
)
def mcp_project_dir_no_default(rig: Rig) -> Iterator[Finding]:
    """A project ``.mcp.json`` server whose ``command`` or ``args`` reference ``${CLAUDE_PROJECT_DIR}`` with no default."""
    for server, value in _configured(rig):
        if server.source is not McpSource.REPO_FILE:
            continue
        field = _project_dir_field(value)
        if field is not None:
            message = f"server `{server.name}` references ${{CLAUDE_PROJECT_DIR}} in {field} with no default"
            yield emit("mcp-project-dir-no-default", server.artifact, message, _key_line(rig, server, field))


def _is_remote(value: Mapping[str, object]) -> bool:
    if "type" in value:
        kind = value["type"]
        return isinstance(kind, str) and kind in _REMOTE_TYPES
    return "url" in value


def _is_stdio(value: Mapping[str, object]) -> bool:
    """Return whether Claude Code runs a server over stdio: no ``type`` key, or the string ``stdio``.

    A server whose ``type`` is any other value, string or not, is neither remote nor stdio;
    ``mcp-type-invalid`` reports it.
    """
    if "type" in value:
        return value["type"] == "stdio"
    return "url" not in value


def _string_values(value: object) -> Iterator[tuple[str, str]]:
    """Yield each string value of a JSON object under its string key, in written order."""
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, str):
            yield key, item


def _field_texts(value: Mapping[str, object]) -> Iterator[tuple[str, str]]:
    """Yield ``(field, text)`` for the ``url`` and each string header value."""
    url = value.get("url")
    if isinstance(url, str):
        yield "url", url
    for _header, text in _string_values(value.get("headers")):
        yield "headers", text


def _credential_references(value: Mapping[str, object]) -> list[tuple[str, str]]:
    """Return each ``(field, variable)`` credential reference once, in the order first written.

    Names are compared upper-cased, as Claude Code compares them, so two spellings of one name in a
    field report once, under the first spelling written.
    """
    found: dict[tuple[str, str], str] = {}
    for field, text in _field_texts(value):
        for match in _REFERENCE.finditer(text):
            variable = match.group(1)
            if remote_blanked(variable):
                found.setdefault((field, variable.upper()), variable)
    return [(field, variable) for (field, _upper), variable in found.items()]


@rule(
    "mcp-credential-var-remote",
    "core",
    Severity.ERROR,
    "Do not reference a variable Claude Code blanks toward a remote server (its own and cloud credentials, tokens, proxies, "
    "package indexes, telemetry) in the url or headers; the server receives an empty value.",
    ("official:MC3",),
)
def mcp_credential_var_remote(rig: Rig) -> Iterator[Finding]:
    """A remote MCP server whose url or headers reference a variable Claude Code reads as empty there."""
    for server, value in _configured(rig):
        if not _is_remote(value):
            continue
        for field, variable in _credential_references(value):
            message = (
                f"server `{server.name}` references `{variable}` in its {field}; "
                "Claude Code reads that variable as empty there, so the server gets none"
            )
            yield emit("mcp-credential-var-remote", server.artifact, message, _key_line(rig, server, field))


def _stdio_field_texts(value: Mapping[str, object]) -> Iterator[tuple[str, tuple[str, ...], str]]:
    """Yield ``(field, keys, text)`` for a stdio server's ``command``, each ``args`` item and each ``env`` value.

    ``keys`` is the entry key of one ``env`` value, and empty for ``command`` and ``args``.
    """
    command = value.get("command")
    if isinstance(command, str):
        yield "command", (), command
    args = value.get("args")
    if isinstance(args, list):
        for item in args:
            if isinstance(item, str):
                yield "args", (), item
    for key, text in _string_values(value.get("env")):
        yield "env", (key,), text


def _stdio_references(value: Mapping[str, object]) -> list[tuple[str, tuple[str, ...], str]]:
    """Return each ``(field, keys, variable)`` a stdio server references that Claude Code blanks, once.

    Names are compared upper-cased, as Claude Code compares them, so two spellings of one name in a
    field report once, under the first spelling written.
    """
    found: dict[tuple[str, str], tuple[str, tuple[str, ...], str]] = {}
    for field, keys, text in _stdio_field_texts(value):
        for match in _REFERENCE.finditer(text):
            variable = match.group(1)
            if plain_blanked(variable):
                found.setdefault((field, variable.upper()), (field, keys, variable))
    return list(found.values())


@rule(
    "mcp-credential-var-stdio",
    "core",
    Severity.WARN,
    "Do not pass a variable Claude Code blanks in every MCP server (its own session tokens and state, "
    "MCP_CLIENT_SECRET-type secrets, OTEL_* telemetry settings) through a stdio server's command, args or env; "
    "the server receives an empty value whenever the variable is set.",
    ("rigcheck:mcp-blanking-probe",),
)
def mcp_credential_var_stdio(rig: Rig) -> Iterator[Finding]:
    """A stdio MCP server references a variable that Claude Code blanks in every server."""
    for server, value in _configured(rig):
        if not _is_stdio(value):
            continue
        for field, keys, variable in _stdio_references(value):
            message = (
                f"server `{server.name}` references `{variable}` in its {field}; "
                "Claude Code reads that variable as empty in a stdio server whenever it is set, so the server never gets its value"
            )
            yield emit("mcp-credential-var-stdio", server.artifact, message, _key_line(rig, server, field, *keys))


def _args_text(value: object) -> str | None:
    """Return a server's ``args`` string items joined for scanning, or None when it holds none."""
    if not isinstance(value, list):
        return None
    items = [item for item in value if isinstance(item, str)]
    return "\n".join(items) or None


def _scanned_leaves(value: Mapping[str, object]) -> Iterator[tuple[str, str, tuple[str, ...], str]]:
    """Yield ``(field, where, keys, text)`` for every string leaf the literal scan reads, in reporting order.

    ``keys`` is the key path below the field: the entry key of one ``env`` or ``headers`` value, and
    empty for the single ``command``, ``args`` and ``url`` leaves. The ``args`` items are one leaf,
    so a server reports at most one finding for the whole list.
    """
    for key, text in _string_values(value.get("env")):
        yield "env", f"`env.{key}`", (key,), text
    for key, text in _string_values(value.get("headers")):
        yield "headers", f"`headers.{key}`", (key,), text
    command = value.get("command")
    if isinstance(command, str):
        yield "command", "`command`", (), command
    args = _args_text(value.get("args"))
    if args is not None:
        yield "args", "`args`", (), args
    url = value.get("url")
    if isinstance(url, str):
        yield "url", "`url`", (), url


def _leaf_hit(text: str) -> SecretHit | None:
    """Return the first credential literal in a leaf, or the first one inside a ``${VAR:-default}`` it writes.

    ``find_secrets`` refuses a literal that follows a ``-``, as the ``:-`` of a default does, so a
    leaf whose text holds no hit on its own has each default body scanned by itself.
    """
    hits = find_secrets(text)
    if hits:
        return hits[0]
    for match in _REFERENCE.finditer(text):
        default = match.group(2)
        if default is None or default == ":-":
            continue
        found = find_secrets(default[2:])
        if found:
            return found[0]
    return None


def _scan_for_literals(rig: Rig, server: McpServer) -> bool:
    """True when the rule reads this server: a plugin config always, a repo file only when git tracks it."""
    if server.source is not McpSource.REPO_FILE:
        return True
    return rig.is_tracked(server.artifact.path)


@rule(
    "mcp-secret-literal",
    "core",
    Severity.ERROR,
    "Replace the literal with a ${VAR} reference and set the variable in the environment; "
    "a committed or shipped .mcp.json is read by everyone who has it. In an installed plugin, "
    "report it to the plugin's author.",
    ("official:MC1",),
)
def mcp_secret_literal(rig: Rig) -> Iterator[Finding]:
    """A git-tracked project ``.mcp.json`` or a plugin's MCP config that holds a credential literal.

    The literal may be in ``env``, ``headers``, ``args``, ``command`` or ``url``.
    """
    for server, value in _configured(rig):
        if not _scan_for_literals(rig, server):
            continue
        for field, where, keys, text in _scanned_leaves(value):
            hit = _leaf_hit(text)
            if hit is None:
                continue
            message = f"{hit.kind} literal ({hit.length} characters) in {where} of server `{server.name}`; the value is not shown"
            yield emit("mcp-secret-literal", server.artifact, message, _key_line(rig, server, field, *keys))


def _endpoint(value: Mapping[str, object]) -> tuple[object, ...]:
    """Return a server's endpoint as written: its ``url``, or its ``command`` and ``args``."""
    if "url" in value:
        return ("url", value["url"])
    args = value.get("args")
    items = tuple(args) if isinstance(args, list) else ()
    return ("command", value.get("command"), items)


def _conflicting_scopes(rig: Rig, name: str, endpoint: tuple[object, ...]) -> list[str]:
    """Return the home scopes declaring ``name`` with a different endpoint, local scope first."""
    scopes: list[str] = []
    for scope in (McpScope.LOCAL, McpScope.USER):
        for home_server in rig.user_mcp_servers:
            if home_server.scope is not scope or home_server.name != name:
                continue
            if not isinstance(home_server.config, dict):
                continue
            if _endpoint(home_server.config) != endpoint:
                scopes.append(scope.value)
                break
    return scopes


def _has_local_scope(rig: Rig, name: str) -> bool:
    """True when ``~/.claude.json`` declares a local-scope server of this name, whatever its endpoint and fields."""
    return any(server.scope is McpScope.LOCAL and server.name == name and isinstance(server.config, dict) for server in rig.user_mcp_servers)


@rule(
    "mcp-server-conflict",
    "core",
    Severity.WARN,
    "Keep one definition of the server and remove the others with claude mcp remove <name> --scope <scope>; "
    "Claude Code loads only the highest-precedence one.",
    ("official:MC6",),
)
def mcp_server_conflict(rig: Rig) -> Iterator[Finding]:
    """A project ``.mcp.json`` server whose name a user- or local-scope server in ``~/.claude.json`` also defines with a different endpoint."""
    for server, value in _configured(rig):
        if server.source is not McpSource.REPO_FILE:
            continue
        scopes = _conflicting_scopes(rig, server.name, _endpoint(value))
        if not scopes:
            continue
        winner = "local" if _has_local_scope(rig, server.name) else "project"
        message = (
            f"server `{server.name}` is also defined in {' and '.join(scopes)} scope in ~/.claude.json "
            f"with a different endpoint; Claude Code loads the {winner} scope definition"
        )
        yield emit("mcp-server-conflict", server.artifact, message, server.line)
