"""Rules for MCP server definitions: the transport type, and the variable references Claude Code does not expand.

A server's ``type`` must be one Claude Code accepts. A project ``.mcp.json`` must give
``${CLAUDE_PROJECT_DIR}`` a default in ``command`` and ``args``, and a remote server's ``url`` and
``headers`` must not reference a credential variable, which Claude Code reads as empty there.
"""

import re
from collections.abc import Iterator, Mapping

from rigcheck.model import Finding, Rig, Severity
from rigcheck.parse import config
from rigcheck.rules import emit, rule
from rigcheck.rules.config import McpServer, McpSource, mcp_servers

_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}")
"""A ``${NAME}`` or ``${NAME:-default}`` reference; a bare ``$NAME`` is not expanded in ``.mcp.json``."""

_VALID_TYPES = frozenset({"stdio", "http", "streamable-http", "sse", "ws"})
_REMOTE_TYPES = frozenset({"http", "streamable-http", "sse", "ws"})
_CREDENTIALS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "AWS_BEARER_TOKEN_BEDROCK", "HTTPS_PROXY", "NPM_TOKEN"})


def _configured(rig: Rig) -> Iterator[tuple[McpServer, Mapping[str, object]]]:
    """Yield every server whose value is an object, with that object."""
    for server in mcp_servers(rig):
        if isinstance(server.config, dict):
            yield server, server.config


def _key_line(rig: Rig, server: McpServer, key: str) -> int | None:
    """Return the line of ``key`` inside the server's entry, or the server's own line."""
    return config.key_line(rig.text(server.artifact.path), (*server.path, key)) or server.line


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


def _is_credential(name: str) -> bool:
    if name in _CREDENTIALS:
        return True
    if name.startswith("ANTHROPIC_"):
        return name.endswith(("_KEY", "_TOKEN"))
    if name.startswith("AWS_"):
        return name.endswith(("_KEY", "_KEY_ID", "_TOKEN"))
    return False


def _is_remote(value: Mapping[str, object]) -> bool:
    if "type" in value:
        kind = value["type"]
        return isinstance(kind, str) and kind in _REMOTE_TYPES
    return "url" in value


def _field_texts(value: Mapping[str, object]) -> Iterator[tuple[str, str]]:
    """Yield ``(field, text)`` for the ``url`` and each string header value."""
    url = value.get("url")
    if isinstance(url, str):
        yield "url", url
    headers = value.get("headers")
    if isinstance(headers, dict):
        for header in headers.values():
            if isinstance(header, str):
                yield "headers", header


def _credential_references(value: Mapping[str, object]) -> list[tuple[str, str]]:
    """Return each ``(field, variable)`` credential reference once, in the order first written."""
    found: dict[tuple[str, str], None] = {}
    for field, text in _field_texts(value):
        for match in _REFERENCE.finditer(text):
            if _is_credential(match.group(1)):
                found.setdefault((field, match.group(1)))
    return list(found)


@rule(
    "mcp-credential-var-remote",
    "core",
    Severity.ERROR,
    "Do not reference Claude Code or cloud-provider credentials in a remote server's url or headers; Claude Code reads them as empty there.",
    ("official:MC3",),
)
def mcp_credential_var_remote(rig: Rig) -> Iterator[Finding]:
    """A remote MCP server whose ``url`` or ``headers`` reference a credential variable, which Claude Code reads as empty."""
    for server, value in _configured(rig):
        if not _is_remote(value):
            continue
        for field, variable in _credential_references(value):
            message = (
                f"server `{server.name}` references `{variable}` in its {field}; "
                "Claude Code reads that credential as empty there, so the server gets none"
            )
            yield emit("mcp-credential-var-remote", server.artifact, message, _key_line(rig, server, field))
