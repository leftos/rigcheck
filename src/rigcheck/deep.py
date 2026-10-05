"""The ``--deep`` runner: which files go to ``claude -p``, the consent listing, the call itself and its cache.

A deep check family turns one file's text into a prompt, asks Claude for output matching a JSON schema, and
parses that output into verdicts the rules read from ``Rig.verdicts``. Only instruction, rule, skill, command and
agent files of the repo and user layers are ever sent; a file holding a secret or over ``MAX_BYTES`` is listed as
not sent. Answers are cached by family, prompt version, model, schema and file text.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from rigcheck.model import Artifact, Finding, Layer, Rig, Verdict
from rigcheck.rules import REGISTRY
from rigcheck.rules.deep_common import deep_artifacts

type Runner = Callable[[str, str], str]
"""Sends ``(prompt, json_schema_text)`` to Claude and returns its stdout."""

MODEL = "haiku"
MAX_BYTES = 100_000
TIMEOUT_S = 120
SYSTEM_PROMPT = "You classify the coding-agent instruction text you are given and answer only with the structured output its schema asks for."


@dataclass(frozen=True)
class Family:
    """One deep check: how to ask about a file and how to read the answer.

    Attributes:
        id: The family's id, the key of its verdicts in ``Rig.verdicts``.
        prompt_version: Bumped whenever the prompt or parse changes, so cached answers are not reused.
        schema: The JSON schema text passed to ``claude --json-schema``.
        build_prompt: Turns a file's text into the prompt.
        parse: Turns the file's path and the unwrapped ``structured_output`` into verdicts; it may raise on bad output.
    """

    id: str
    prompt_version: str
    schema: str
    build_prompt: Callable[[str], str]
    parse: Callable[[Path, dict], tuple[Verdict, ...]]


FAMILIES: tuple[Family, ...] = ()
"""The deep check families that run under ``--deep``."""


@dataclass(frozen=True)
class Listing:
    """What ``--deep`` would send, shown to the user before any call.

    Attributes:
        sent: Each file to send with its size in UTF-8 bytes.
        not_sent: Each selected file held back, with the reason.
        model: The model the calls use.
        calls: How many calls the run makes: files sent times families.
    """

    sent: tuple[tuple[Path, int], ...]
    not_sent: tuple[tuple[Path, str], ...]
    model: str
    calls: int


class DeepStop(Exception):  # noqa: N818 - a stop, not an error: dry runs end with status 0
    """Ends the run before any call, with the process exit code to return."""

    def __init__(self, exit_code: int) -> None:
        super().__init__(exit_code)
        self.exit_code = exit_code


class DeepUnavailable(Exception):  # noqa: N818 - named for what the user lacks
    """``--deep`` cannot run on this machine."""


def plan(rig: Rig, families: tuple[Family, ...]) -> Listing:
    """Decide which files ``--deep`` sends and which it holds back.

    A file where ``secret-literal`` fires is held back even when ``.rigcheck.toml`` suppresses the finding; when the
    secret scan itself fails, every file is held back. Empty files and files over ``MAX_BYTES`` are held back too.

    Args:
        rig: The discovered setup.
        families: The families that would run.

    Returns:
        The listing of files sent and not sent, the model and the call count.
    """
    secrets = _secret_paths(rig)
    sent: list[tuple[Path, int]] = []
    not_sent: list[tuple[Path, str]] = []
    for artifact in deep_artifacts(rig).values():
        size = len(rig.text(artifact.path).encode("utf-8"))
        reason = _hold_back_reason(artifact.path, size, secrets)
        if reason is None:
            sent.append((artifact.path, size))
        else:
            not_sent.append((artifact.path, reason))
    return Listing(tuple(sent), tuple(not_sent), MODEL, len(sent) * len(families))


def _secret_paths(rig: Rig) -> frozenset[Path] | None:
    """Return the files where ``secret-literal`` fires, or None when the scan raised."""
    try:
        return frozenset(finding.path for finding in REGISTRY["secret-literal"].check(rig) if finding.path is not None)
    except Exception:  # noqa: BLE001 - a failing secret scan must hold every file back, never send it
        return None


def _hold_back_reason(path: Path, size: int, secrets: frozenset[Path] | None) -> str | None:
    """Return why a file is not sent, checking the secret scan, then emptiness, then the size cap; None to send it."""
    if secrets is None:
        return "secret scan failed"
    if path in secrets:
        return "holds a secret"
    if size == 0:
        return "empty"
    if size > MAX_BYTES:
        return f"over {MAX_BYTES:,} bytes"
    return None


def _display(path: Path, layer: Layer | None, rig: Rig) -> str:
    """Return ``path`` relative to the repo root, or as ``~/...`` for user-layer files and files outside the repo."""
    roots = [(rig.home, "~/"), (rig.repo_root, "")] if layer is Layer.USER else [(rig.repo_root, ""), (rig.home, "~/")]
    for root, prefix in roots:
        if path.is_relative_to(root):
            return prefix + path.relative_to(root).as_posix()
    return path.as_posix()


def format_listing(listing: Listing, rig: Rig) -> str:
    """Render the listing as text: one line per file sent, a ``Not sent:`` block, then the model and call count.

    File contents are never printed.
    """
    layers: dict[Path, Layer] = {}
    for artifact in rig.artifacts:
        layers.setdefault(artifact.path, artifact.layer)
    lines = [f"  {_display(path, layers.get(path), rig)}  {size} bytes" for path, size in listing.sent]
    if listing.not_sent:
        lines.append("Not sent:")
        lines.extend(f"  {_display(path, layers.get(path), rig)}  ({reason})" for path, reason in listing.not_sent)
    lines.append(f"Model {listing.model}, {listing.calls} call(s).")
    return "\n".join(lines) + "\n"


def cache_dir(env: Mapping[str, str], home: Path) -> Path:
    """Return the cache folder: ``$XDG_CACHE_HOME/rigcheck`` when set and non-empty, else ``<home>/.cache/rigcheck``."""
    xdg = env.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "rigcheck"
    return home / ".cache" / "rigcheck"


def cache_key(family: Family, model: str, text: str) -> str:
    """Return the cache key of one family's answer for one file text under one model and the current system prompt."""
    parts = (family.id, family.prompt_version, model, SYSTEM_PROMPT, family.schema, text)
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class _BadOutputError(Exception):
    """The runner's stdout was not a successful envelope with a structured output."""


def _unwrap(stdout: str) -> dict:
    """Return the ``structured_output`` of a ``claude -p --output-format json`` envelope, or raise ``_BadOutputError``."""
    try:
        envelope = json.loads(stdout)
    except ValueError as exc:
        raise _BadOutputError("output is not JSON") from exc
    if not isinstance(envelope, dict):
        raise _BadOutputError("output is not a JSON object")
    if envelope.get("is_error") is not False:
        raise _BadOutputError("is_error is not false")
    if envelope.get("subtype") != "success":
        raise _BadOutputError("subtype is not success")
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict):
        raise _BadOutputError("structured_output is missing or not an object")
    return structured


def _cached(entry: Path) -> dict | None:
    """Return the structured output cached at ``entry``, or None when there is none or it does not read back as an object."""
    if not entry.is_file():
        return None
    try:
        data = json.loads(entry.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _store(entry: Path, structured: dict) -> None:
    """Write ``structured`` to ``entry`` atomically, creating the cache folder.

    A write that fails is reported on stderr and otherwise ignored: the answer is still used, only not cached.
    The temporary file's name is unique per process and call, so two runs never write the same one.
    """
    partial = entry.with_name(f"{entry.stem}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(json.dumps(structured), encoding="utf-8", newline="\n")
        partial.replace(entry)
    except OSError as exc:
        sys.stderr.write(f"rigcheck: could not cache a --deep answer: {type(exc).__name__}\n")


def error_finding(family_id: str, artifact: Artifact, reason: str) -> Finding:
    """Return the ``deep-error`` finding for one family's failed call on one file; ``reason`` never holds model output or file text."""
    meta = REGISTRY["deep-error"]
    message = f"deep check {family_id} failed on this file: {reason}"
    return Finding("deep-error", meta.severity, artifact.path, None, message, meta.fix, artifact.layer, artifact.load_class)


def _judge(family: Family, path: Path, text: str, runner: Runner, cache: Path) -> tuple[Verdict, ...]:
    """Return one family's verdicts on one file, from the cache or a runner call; raise ``_BadOutputError`` on any failure."""
    entry = cache / f"{cache_key(family, MODEL, text)}.json"
    structured = _cached(entry)
    fresh = structured is None
    if structured is None:
        try:
            stdout = runner(family.build_prompt(text), family.schema)
        except Exception as exc:
            raise _BadOutputError(f"the call raised {type(exc).__name__}") from exc
        structured = _unwrap(stdout)
    try:
        verdicts = family.parse(path, structured)
    except Exception as exc:
        raise _BadOutputError(f"parse raised {type(exc).__name__}") from exc
    if fresh:
        _store(entry, structured)
    return verdicts


def run(
    rig: Rig, listing: Listing, runner: Runner, cache: Path, families: tuple[Family, ...]
) -> tuple[dict[str, tuple[Verdict, ...]], list[Finding]]:
    """Run every family over every file the listing sends, one call at a time.

    A call that raises or returns output that does not unwrap or parse becomes one ``deep-error`` finding for that
    file and is not cached.

    Args:
        rig: The discovered setup.
        listing: The files to send, from :func:`plan`.
        runner: Sends one prompt and schema to Claude and returns its stdout.
        cache: The cache folder.
        families: The families to run.

    Returns:
        The verdicts grouped by family id, and the ``deep-error`` findings.
    """
    artifacts = deep_artifacts(rig)
    verdicts: dict[str, tuple[Verdict, ...]] = {}
    errors: list[Finding] = []
    for family in families:
        found: list[Verdict] = []
        for path, _ in listing.sent:
            try:
                found.extend(_judge(family, path, rig.text(path), runner, cache))
            except _BadOutputError as exc:
                errors.append(error_finding(family.id, artifacts[path], str(exc)))
        verdicts[family.id] = tuple(found)
    return verdicts, errors


def make_runner() -> Runner:
    """Return the runner that calls the ``claude`` CLI in print mode with no tools and no saved session.

    Raises:
        DeepUnavailable: When ``claude`` is not on PATH, or resolves to a Windows ``.cmd`` or ``.bat`` shim, whose
            ``cmd.exe`` argument parsing could mangle the JSON schema.
    """
    exe = shutil.which("claude")
    if exe is None:
        raise DeepUnavailable("--deep needs the claude CLI on PATH")
    found = Path(exe)
    if found.suffix.lower() in {".cmd", ".bat"}:
        raise DeepUnavailable(f"--deep needs the native claude executable; {found.name} is a cmd shim, which cannot pass the schema safely")

    def runner(prompt: str, schema: str) -> str:
        argv = [
            exe,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--tools",
            "",
            "--no-session-persistence",
            "--safe-mode",
            "--model",
            MODEL,
            "--max-budget-usd",
            "0.50",
            "--system-prompt",
            SYSTEM_PROMPT,
        ]
        # Fixed argv and no shell; the prompt goes in on stdin.
        result = subprocess.run(  # noqa: S603
            argv, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT_S, check=True
        )
        return result.stdout

    return runner


def confirm(listing: Listing, *, yes: bool, stdin: TextIO, stderr: TextIO) -> None:
    """Ask before sending, unless there is nothing to send or ``--yes`` was given.

    Raises:
        DeepStop: With status 2 when stdin is not a terminal, or the answer (an empty line or end of input included)
            is not ``y`` or ``yes``.
    """
    if listing.calls == 0 or yes:
        return
    if not stdin.isatty():
        stderr.write("--deep needs --yes when stdin is not a terminal\n")
        raise DeepStop(2)
    stderr.write(f"Send {len(listing.sent)} file(s) to claude (model {listing.model}, {listing.calls} call(s))? [y/N] ")
    stderr.flush()
    if stdin.readline().strip().lower() not in {"y", "yes"}:
        stderr.write("--deep cancelled; nothing was sent\n")
        raise DeepStop(2)
