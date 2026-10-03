"""The checked repo's own rigcheck configuration: the suppressions its ``.rigcheck.toml`` declares."""

import re
import tomllib
from pathlib import Path
from typing import Any

from rigcheck.model import Suppression

ENTRY_KEYS = ("rule", "path", "reason")
"""The keys a ``[[suppress]]`` entry may carry."""

_SUPPRESS_KEY = re.compile(r"\s*suppress\s*=")
_SUPPRESS_HEADER = re.compile(r"""^\s*\[\[\s*(?:suppress|"suppress"|'suppress')\s*\]\]\s*(?:#.*)?$""")


def _key_name(key: str) -> str:
    """Return a key name safe to print: control characters escaped, plain names unchanged."""
    return repr(key)[1:-1]


def _read_text(path: Path) -> tuple[str | None, str | None]:
    """Return the file's text, or None and the problem met reading it (None too when the file is absent)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"{path}: cannot read: {exc.strerror or exc}"
    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError as exc:
        return None, f"{path}: not valid TOML: not UTF-8 text (byte {exc.start})"


def _entry_lines(text: str, count: int) -> list[int]:
    """Return the line of each of the first ``count`` ``[[suppress]]`` headers, or the ``suppress`` key's line for all."""
    lines = text.split("\n")
    headers = [number for number, line in enumerate(lines, 1) if _SUPPRESS_HEADER.match(line)]
    if len(headers) >= count:
        return headers[:count]
    key_line = next((number for number, line in enumerate(lines, 1) if _SUPPRESS_KEY.match(line)), 1)
    return [key_line] * count


def _entry_problems(table: dict[str, Any]) -> list[str]:
    """Return what is wrong with one entry, naming keys but never quoting values."""
    problems = []
    if "rule" not in table:
        problems.append("rule is missing")
    elif not isinstance(table["rule"], str) or not table["rule"].strip():
        problems.append("rule must be a non-empty string")
    problems.extend(f"{key} must be a string" for key in ("path", "reason") if key in table and not isinstance(table[key], str))
    problems.extend(f"unknown key `{_key_name(key)}`" for key in table if key not in ENTRY_KEYS)
    return problems


def _entries(path: Path, tables: list[dict[str, Any]], lines: list[int]) -> tuple[tuple[Suppression, ...], list[str]]:
    entries: list[Suppression] = []
    problems: list[str] = []
    for number, (table, line) in enumerate(zip(tables, lines, strict=True), 1):
        wrong = _entry_problems(table)
        problems.extend(f"{path}: [[suppress]] entry {number}: {what}" for what in wrong)
        if not wrong:
            entries.append(Suppression(rule=table["rule"], path=table.get("path"), reason=table.get("reason"), line=line))
    return tuple(entries), problems


def load_suppressions(path: Path) -> tuple[tuple[Suppression, ...], list[str]]:
    """Read the suppression entries of a ``.rigcheck.toml``; never raises for bad content.

    Args:
        path: The file to read; it need not exist.

    Returns:
        The valid entries in file order, and one problem string per thing wrong with the file. A problem names the file
        and at most a key, never a value from it. An absent file yields no entries and no problems.
    """
    text, problem = _read_text(path)
    if text is None:
        return (), [] if problem is None else [problem]
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return (), [f"{path}: not valid TOML: {exc}"]
    problems = [f"{path}: unknown key `{_key_name(key)}`" for key in data if key != "suppress"]
    tables = data.get("suppress", [])
    if not isinstance(tables, list) or not all(isinstance(table, dict) for table in tables):
        problems.append(f"{path}: `suppress` must be an array of tables")
        return (), problems
    entries, entry_problems = _entries(path, tables, _entry_lines(text, len(tables)))
    return entries, problems + entry_problems
