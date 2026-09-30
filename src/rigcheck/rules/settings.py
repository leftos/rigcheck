"""Rules for settings files: the keys Claude Code reads, their values, and how layers shadow each other."""

import functools
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from importlib import resources

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from rigcheck.model import Artifact, Finding, Kind, Rig, Severity
from rigcheck.parse import config
from rigcheck.rules import emit, rule

SCHEMA_FILE = "claude-code-settings.schema.json"
"""The vendored SchemaStore settings schema, in the package's ``data`` folder."""

_JSON_KINDS = frozenset({Kind.SETTINGS, Kind.HOOKS_CONFIG, Kind.MCP_CONFIG, Kind.PLUGIN_MANIFEST})
"""The artifact kinds Claude Code reads as a JSON object."""

_JSON_TYPES: dict[type, str] = {list: "an array", str: "a string", bool: "a boolean", int: "a number", float: "a number", type(None): "null"}
"""How a loaded top-level value that is not an object is named, by its Python type."""

MAX_SCHEMA_FINDINGS = 8
"""The most schema findings one settings file reports; the last one shown counts the rest."""

_MAX_LISTED_KEYS = 3
"""The most unknown keys one finding names."""

_RULE_LISTS = frozenset({"allow", "ask", "deny"})
"""The ``permissions`` lists whose entries are permission rule strings."""

_NAMING = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependencies"})
"""Schema keywords whose members are named by the author, so a member called ``propertyNames`` is not the keyword."""

_BOUNDS = {"minimum": ">=", "maximum": "<=", "exclusiveMinimum": ">", "exclusiveMaximum": "<"}
"""The comparison each numeric bound keyword demands."""

_SIZES = {
    "minLength": "must have length >=",
    "maxLength": "must have length <=",
    "minItems": "must have item count >=",
    "maxItems": "must have item count <=",
}
"""The wording of each size bound keyword, before its limit."""


def settings_docs(rig: Rig) -> Iterator[tuple[Artifact, dict[str, object]]]:
    """Yield every settings file whose JSON loads to an object, with the object it holds.

    Args:
        rig: The discovered setup.

    Yields:
        Each repo or user ``settings.json`` / ``settings.local.json`` that loads to an object, in rig order.
    """
    for artifact in rig.artifacts:
        if artifact.kind is Kind.SETTINGS:
            data = config.load(rig.text(artifact.path)).data
            if isinstance(data, dict):
                yield artifact, data


@functools.cache
def _validator() -> Draft7Validator:
    """Return the validator for the vendored settings schema, loaded once per process."""
    text = (resources.files("rigcheck") / "data" / SCHEMA_FILE).read_text(encoding="utf-8")
    return Draft7Validator(json.loads(text))


def _json_problem(rig: Rig, artifact: Artifact) -> Finding | None:
    """Return the finding for a JSON config file that does not load to an object, or None when it does or is blank."""
    text = rig.text(artifact.path)
    if not text.removeprefix(config.BOM).strip():
        return None
    doc = config.load(text)
    name = artifact.path.name
    if doc.problem is not None:
        return emit("config-json-invalid", artifact, f"{name} does not load as JSON: {doc.problem}", doc.line)
    if isinstance(doc.data, dict):
        return None
    held = _JSON_TYPES.get(type(doc.data), "a value")
    return emit("config-json-invalid", artifact, f"{name} holds {held} where Claude Code expects an object", None)


@rule(
    "config-json-invalid",
    "core",
    Severity.ERROR,
    "Fix the JSON so it parses to an object; Claude Code skips a config file it cannot load.",
    ("official:ST1",),
)
def config_json_invalid(rig: Rig) -> Iterator[Finding]:
    """A settings, MCP, plugin hooks or plugin manifest file does not load as a JSON object."""
    for artifact in rig.artifacts:
        if artifact.kind in _JSON_KINDS:
            finding = _json_problem(rig, artifact)
            if finding is not None:
                yield finding


def _schema_properties(error: ValidationError) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Return the ``properties`` and ``patternProperties`` of the schema an error was raised by."""
    schema = error.schema if isinstance(error.schema, Mapping) else {}
    properties = schema.get("properties")
    patterns = schema.get("patternProperties")
    return (properties if isinstance(properties, Mapping) else {}), (patterns if isinstance(patterns, Mapping) else {})


def _extra_keys(error: ValidationError) -> list[str]:
    """Return the keys of an ``additionalProperties`` error's object that its schema neither names nor patterns."""
    if not isinstance(error.instance, Mapping):
        return []
    properties, patterns = _schema_properties(error)
    return [
        key for key in error.instance if isinstance(key, str) and key not in properties and not any(re.search(pattern, key) for pattern in patterns)
    ]


def _quoted(names: Sequence[str]) -> str:
    """Return up to the first few ``names`` quoted and joined, counting the rest."""
    listed = ", ".join(f'"{name}"' for name in names[:_MAX_LISTED_KEYS])
    rest = len(names) - _MAX_LISTED_KEYS
    return f"{listed} and {rest} more" if rest > 0 else listed


def _unknown_keys(extras: Sequence[str]) -> str:
    """Name the keys an object's schema does not allow; key names are never values."""
    if not extras:
        return "has a key the schema does not allow"
    noun = "key" if len(extras) == 1 else "keys"
    return f"unknown {noun} {_quoted(extras)}"


def _misnamed_keys(names: Sequence[str]) -> str:
    """Name the keys whose names break the schema's ``propertyNames``; key names are never values."""
    if len(names) == 1:
        return f"key {_quoted(names)} does not match the expected form"
    return f"keys {_quoted(names)} do not match the expected form"


def _from_property_names(error: ValidationError) -> bool:
    """Return True when ``error`` was raised checking a key's name against a ``propertyNames`` schema."""
    path = list(error.schema_path)
    return any(part == "propertyNames" and (index == 0 or path[index - 1] not in _NAMING) for index, part in enumerate(path))


def _failing_names(errors: Sequence[ValidationError]) -> dict[tuple[str | int, ...], list[str]]:
    """Return, per object path, the keys whose names fail its ``propertyNames`` schema, in file order."""
    names: dict[tuple[str | int, ...], list[str]] = {}
    for error in errors:
        if _from_property_names(error) and isinstance(error.instance, str):
            found = names.setdefault(tuple(error.absolute_path), [])
            if error.instance not in found:
                found.append(error.instance)
    return names


def _listed(value: object) -> list[object]:
    """Return a schema keyword's value as a list: its items when it is a list, else the value alone."""
    return list(value) if isinstance(value, list) else [value]


def _wrong_type(error: ValidationError) -> str:
    """Name the type or types the schema expects."""
    return "must be " + " or ".join(str(expected) for expected in _listed(error.validator_value))


def _not_allowed(error: ValidationError) -> str:
    """List the values the schema allows, taken from the schema and never from the file."""
    allowed = _listed(error.validator_value) if error.validator == "enum" else [error.validator_value]
    return "must be one of " + ", ".join(json.dumps(value) for value in allowed)


def _missing(error: ValidationError) -> str:
    """Name the required keys the object lacks."""
    present = error.instance if isinstance(error.instance, Mapping) else {}
    missing = [str(key) for key in _listed(error.validator_value) if key not in present]
    return f"missing {_quoted(missing)}"


def _bound(error: ValidationError) -> str:
    """State the numeric bound the value breaks."""
    return f"must be {_BOUNDS[str(error.validator)]} {error.validator_value}"


def _size(error: ValidationError) -> str:
    """State the length or item-count bound the value breaks."""
    return f"{_SIZES[str(error.validator)]} {error.validator_value}"


_REASONS: dict[str, Callable[[ValidationError], str]] = {
    "type": _wrong_type,
    "enum": _not_allowed,
    "const": _not_allowed,
    "required": _missing,
    "pattern": lambda _error: "does not match the expected form",
    "uniqueItems": lambda _error: "must not repeat an item",
    **dict.fromkeys(_BOUNDS, _bound),
    **dict.fromkeys(_SIZES, _size),
}
"""How each schema keyword's failure is worded; none of them repeats the offending value."""


def _reason(error: ValidationError) -> str:
    """Word why the schema rejects the value, from the failing keyword alone."""
    keyword = str(error.validator)
    wording = _REASONS.get(keyword)
    return wording(error) if wording is not None else f"does not match the schema ({keyword})"


def _describe(error: ValidationError, names: Mapping[tuple[str | int, ...], list[str]]) -> tuple[str, Sequence[str]]:
    """Return why the schema rejects the value, and the keys that reason names (none when it names no key)."""
    if _from_property_names(error):
        misnamed = names.get(tuple(error.absolute_path), [])
        return _misnamed_keys(misnamed), misnamed
    if error.validator == "additionalProperties":
        extras = _extra_keys(error)
        return _unknown_keys(extras), extras
    return _reason(error), ()


def _dotted(path: Sequence[str | int]) -> str:
    """Return a value's path as ``a.b[0].c``, or ``top level`` for the root."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text or "top level"


def _line(text: str, path: Sequence[str | int], named: Sequence[str]) -> int:
    """Return the line of the key nearest the rejected value.

    That is the first key the reason names, else the value's own key, else the closest enclosing
    one, else line 1.
    """
    keys: list[str] = []
    for part in path:
        if not isinstance(part, str):
            break
        keys.append(part)
    candidates: list[tuple[str, ...]] = []
    if named and len(keys) == len(path):
        candidates.append((*keys, named[0]))
    candidates.extend(tuple(keys[:end]) for end in range(len(keys), 0, -1))
    for candidate in candidates:
        found = config.key_line(text, candidate)
        if found is not None:
            return found
    return 1


def _order(error: ValidationError) -> tuple[list[tuple[int, int | str]], str]:
    """Return the sort key of an error: its path, array indexes compared as numbers, then its message."""
    return [(0, part) if isinstance(part, int) else (1, part) for part in error.absolute_path], error.message


def _one_per_path(errors: Sequence[ValidationError]) -> list[ValidationError]:
    """Return the first error of each rejected path, in path order."""
    chosen: dict[tuple[str | int, ...], ValidationError] = {}
    for error in sorted(errors, key=_order):
        chosen.setdefault(tuple(error.absolute_path), error)
    return list(chosen.values())


def _left_to_other_rules(path: Sequence[str | int]) -> bool:
    """Return True for a path whose shape other rules own: the hook map, or one permission rule string.

    The hook rules check the ``hooks`` map. The permission rules check each rule string, whose
    grammar the schema's pattern gets wrong (it forbids parentheses inside a specifier, which Claude
    Code reads literally) and whose tool list lags Claude Code's tools. The ``allow``, ``ask`` and
    ``deny`` lists themselves stay checked here.
    """
    if path[:1] == ["hooks"]:
        return True
    return len(path) >= 3 and path[0] == "permissions" and path[1] in _RULE_LISTS and isinstance(path[2], int)


def _schema_findings(rig: Rig, artifact: Artifact, data: dict[str, object]) -> Iterator[Finding]:
    """Yield the capped schema findings of one settings file, the paths other rules own left out."""
    text = rig.text(artifact.path)
    errors = [error for error in _validator().iter_errors(data) if not _left_to_other_rules(list(error.absolute_path))]
    names = _failing_names(errors)
    chosen = _one_per_path(errors)
    shown = chosen[:MAX_SCHEMA_FINDINGS]
    hidden = len(chosen) - len(shown)
    for index, error in enumerate(shown, start=1):
        path = list(error.absolute_path)
        reason, named = _describe(error, names)
        message = f"{_dotted(path)}: {reason}"
        if hidden and index == len(shown):
            message += f" (and {hidden} more)"
        yield emit("settings-schema-invalid", artifact, message, _line(text, path, named))


@rule(
    "settings-schema-invalid",
    "core",
    Severity.ERROR,
    "Correct the value to match Claude Code's settings schema (json.schemastore.org/claude-code-settings.json).",
    ("official:ST1",),
)
def settings_schema_invalid(rig: Rig) -> Iterator[Finding]:
    """A settings file holds a value Claude Code's settings schema rejects."""
    for artifact, data in settings_docs(rig):
        yield from _schema_findings(rig, artifact, data)
