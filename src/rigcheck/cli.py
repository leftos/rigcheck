"""Command-line entry point."""

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

from rigcheck import __version__, deep, engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Finding, Outcome, Rig, Rule, Severity, Suppressed
from rigcheck.report import brief, budget, terminal
from rigcheck.report import json as json_report
from rigcheck.rules import DEFAULT_PACKS, PACKS, REGISTRY

USAGE_ERROR = 2
WINDOW_ERROR = "window must be a positive number of tokens, like 200k or 1m"

_WINDOW = re.compile(r"([1-9][0-9]*)([km]?)", re.IGNORECASE)
_WINDOW_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000}

_RULE_DOCS = Path(__file__).resolve().parents[2] / "docs" / "rules"

_ALWAYS_KEPT = frozenset({"internal-error", "deep-error"})
"""Rule ids ``--only`` never filters out: they report a rule or a ``--deep`` call that could not do its job."""


def _run_flags() -> argparse.ArgumentParser:
    """Return the parser holding the flags ``check`` and ``brief`` share."""
    flags = argparse.ArgumentParser(add_help=False)
    flags.add_argument("path", nargs="?", type=Path, default=None, metavar="PATH", help="directory to check (default: current directory)")
    flags.add_argument("--home", type=Path, default=None, metavar="DIR", help="home directory holding .claude (default: your home)")
    flags.add_argument(
        "--window", type=parse_window, default=DEFAULT_WINDOW, metavar="SIZE", help="model context window in tokens, like 200k or 1m (default: 200k)"
    )
    flags.add_argument(
        "--sibling",
        type=Path,
        action="append",
        default=[],
        metavar="DIR",
        help="a sibling checkout where a path named in a doc, skill, agent or command may exist instead (repeatable)",
    )
    flags.add_argument("--only", type=parse_only, default=None, metavar="ID[,ID...]", help="report only the findings of these rule ids")
    flags.add_argument(
        "--packs",
        type=parse_packs,
        default=DEFAULT_PACKS,
        metavar="PACK[,PACK...]",
        help="packs whose rules run (default: core,advice; house is off unless named)",
    )
    flags.add_argument("--deep", action="store_true", help="ask Claude to judge what code cannot; sends files after showing them")
    flags.add_argument("--yes", action="store_true", help="skip the --deep confirmation prompt; the file listing is still printed")
    flags.add_argument("--dry-run", action="store_true", help="with --deep, print what would be sent and stop")
    return flags


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="rigcheck", description="Validate a coding-agent instruction setup.")
    parser.add_argument("--version", action="version", version=f"rigcheck {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    check = commands.add_parser("check", help="check the effective setup Claude Code loads for a directory", parents=[_run_flags()])
    check.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    check.add_argument(
        "--fail-on",
        choices=[severity.value for severity in Severity],
        default=Severity.ERROR.value,
        help="lowest finding severity that makes the exit status 1 (default: error)",
    )
    brief_command = commands.add_parser("brief", help="write a Markdown fix brief of the findings", parents=[_run_flags()])
    brief_command.add_argument("-o", "--output", type=Path, default=None, metavar="FILE", help="write the brief to FILE instead of stdout")
    rules = commands.add_parser("rules", help="list every rule with its pack, severity and summary")
    rules.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    explain = commands.add_parser("explain", help="explain one rule: its pack, severity, fix and evidence")
    explain.add_argument("rule_id", metavar="RULE_ID")
    explain.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    return parser


def _write_stdout(text: str) -> None:
    """Write ``text`` to stdout as UTF-8, replacing characters the stream cannot encode."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.write(text)


def _closest_ids(rule_id: str) -> list[str]:
    """Return up to three registered rule ids closest to ``rule_id``."""
    return difflib.get_close_matches(rule_id, sorted(REGISTRY), n=3, cutoff=0.0)


def parse_only(value: str) -> frozenset[str]:
    """Parse a comma-separated list of rule ids, each of which must be registered.

    Args:
        value: The command-line value, like ``reference-path-missing,import-unresolved``.

    Returns:
        The rule ids.

    Raises:
        argparse.ArgumentTypeError: When the list is empty or names an unknown rule; the message names the closest ids.
    """
    ids = [part.strip() for part in value.split(",") if part.strip()]
    if not ids:
        raise argparse.ArgumentTypeError("give at least one rule id, like reference-path-missing")
    for rule_id in ids:
        if rule_id not in REGISTRY:
            closest = _closest_ids(rule_id)
            raise argparse.ArgumentTypeError(f"unknown rule id {rule_id!r}; closest: {', '.join(closest)}")
    return frozenset(ids)


def parse_packs(value: str) -> frozenset[str]:
    """Parse a comma-separated list of pack names, each of which must be one of ``PACKS``.

    Args:
        value: The command-line value, like ``core,house``.

    Returns:
        The pack names.

    Raises:
        argparse.ArgumentTypeError: When the list is empty, an item is blank, or a name is unknown.
    """
    names = [part.strip() for part in value.split(",")]
    if not all(names):
        raise argparse.ArgumentTypeError(f"empty pack name in {value!r}; give packs like core,advice")
    for name in names:
        if name not in PACKS:
            raise argparse.ArgumentTypeError(f"unknown pack {name!r}; packs are core, advice and house")
    return frozenset(names)


def parse_window(value: str) -> int:
    """Parse a context window size: a positive integer, optionally suffixed ``k`` (thousands) or ``m`` (millions), any case.

    Args:
        value: The command-line value.

    Returns:
        The window in tokens.

    Raises:
        argparse.ArgumentTypeError: When ``value`` is not such a size.
    """
    match = _WINDOW.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(WINDOW_ERROR)
    return int(match[1]) * _WINDOW_MULTIPLIERS[match[2].lower()]


def _rules_to_run(packs: frozenset[str], only: frozenset[str] | None) -> list[Rule]:
    """Return the rules to run: those whose pack is selected, every rule ``--only`` names, and the engine and suppression rules."""
    return [rule for rule in REGISTRY.values() if rule.pack in packs or rule.id in engine.UNSUPPRESSIBLE or (only is not None and rule.id in only)]


def _ran_ids(rules: list[Rule]) -> frozenset[str]:
    """Return the ids of the rules that ran, the set ``apply_suppressions`` uses to tell a skipped rule's entry apart."""
    return frozenset(rule.id for rule in rules)


def _select(outcome: Outcome, only: frozenset[str] | None) -> tuple[list[Finding], list[Suppressed]]:
    """Return the kept and suppressed findings of the ``--only`` rules, or all of them without ``--only``."""
    if only is None:
        return outcome.findings, outcome.suppressed
    # A selected rule that raised is reported as internal-error, and a failed --deep call as deep-error, so those ids are always kept.
    findings = [finding for finding in outcome.findings if finding.rule_id in only or finding.rule_id in _ALWAYS_KEPT]
    suppressed = [entry for entry in outcome.suppressed if entry.finding.rule_id in only]
    return findings, suppressed


def _analyze(parser: argparse.ArgumentParser, args: argparse.Namespace) -> tuple[Rig, list[Finding], list[Suppressed]]:
    """Resolve the target, discover the rig, run the selected rules and return the kept findings.

    Args:
        parser: The subparser whose ``error`` reports an unusable target or sibling path.
        args: The parsed command-line arguments.

    Returns:
        The rig, its ranked findings with suppressions applied, and the findings a ``.rigcheck.toml`` entry silenced.
    """
    target = (args.path or Path.cwd()).resolve()
    if not target.is_dir():
        parser.error(f"not a directory: {target}")
    home = (args.home or Path.home()).resolve()
    siblings = tuple(sibling.resolve() for sibling in args.sibling)
    for sibling in siblings:
        if not sibling.is_dir():
            parser.error(f"--sibling is not a directory: {sibling}")
    rig = discover(target, home, args.window, siblings=siblings)
    deep_errors = _deep(parser, args, rig, home)
    rules = _rules_to_run(args.packs, args.only)
    outcome = engine.apply_suppressions(rig, [*engine.run(rig, rules), *deep_errors], _ran_ids(rules))
    findings, suppressed = _select(outcome, args.only)
    return rig, findings, suppressed


def _deep(parser: argparse.ArgumentParser, args: argparse.Namespace, rig: Rig, home: Path) -> list[Finding]:
    """Under ``--deep``, list what would be sent, ask, run the families and fill ``rig.verdicts``.

    Args:
        parser: The subparser whose ``error`` reports a flag misuse or a missing ``claude``.
        args: The parsed command-line arguments.
        rig: The discovered setup; its ``verdicts`` are filled in place.
        home: The resolved home directory, under which the cache lives unless ``XDG_CACHE_HOME`` is set.

    Returns:
        The ``deep-error`` findings of the calls that failed; empty without ``--deep``.

    Raises:
        deep.DeepStop: After a ``--dry-run`` listing (status 0), or when consent is not given (status 2).
    """
    if not args.deep:
        if args.yes or args.dry_run:
            parser.error("--yes and --dry-run need --deep")
        return []
    listing = deep.plan(rig, deep.FAMILIES)
    sys.stderr.write(deep.format_listing(listing, rig))
    if args.dry_run:
        raise deep.DeepStop(0)
    if not listing.calls:
        return []
    try:
        runner = deep.make_runner()
    except deep.DeepUnavailable as exc:
        parser.error(str(exc))
    deep.confirm(listing, yes=args.yes, stdin=sys.stdin, stderr=sys.stderr)
    verdicts, errors = deep.run(rig, listing, runner, deep.cache_dir(os.environ, home), deep.FAMILIES)
    rig.verdicts.update(verdicts)
    return errors


def _check(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    rig, findings, suppressed = _analyze(parser, args)
    report = budget.compute(rig)
    if args.format == "json":
        output = json_report.render(rig, findings, suppressed, report)
    else:
        output = terminal.render(rig, findings, suppressed, report, color=terminal.use_color(sys.stdout))
    _write_stdout(output)
    threshold = Severity(args.fail_on)
    return 1 if any(finding.severity.rank <= threshold.rank for finding in findings) else 0


def _brief(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Write a Markdown fix brief of the findings to stdout, or to ``--output`` when given."""
    rig, findings, _ = _analyze(parser, args)
    text = brief.render(rig, findings)
    if args.output is None:
        _write_stdout(text)
        return 0
    if args.output.is_dir():
        parser.error(f"--output is a folder: {args.output}")
    if not args.output.parent.is_dir():
        parser.error(f"--output folder does not exist: {args.output.parent}")
    try:
        with args.output.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as error:
        parser.error(f"cannot write --output {args.output}: {error.strerror or error}")
    return 0


def _ordered_rules() -> list[Rule]:
    """Return every registered rule ordered by pack in ``PACKS`` order, then by id."""
    return sorted(REGISTRY.values(), key=lambda rule: (PACKS.index(rule.pack), rule.id))


def _format_rules_text(rules: list[Rule]) -> str:
    """Render rules as aligned text, one line per rule with no header."""
    if not rules:
        return ""
    id_width = max(len(rule.id) for rule in rules)
    pack_width = max(len(rule.pack) for rule in rules)
    severity_width = max(len(rule.severity.value) for rule in rules)
    lines = [
        f"{rule.id.ljust(id_width)}  {rule.pack.ljust(pack_width)}  {rule.severity.value.ljust(severity_width)}  {rule.summary}".rstrip()
        for rule in rules
    ]
    return "\n".join(lines) + "\n"


def _format_explain_text(rule: Rule, docs: str | None) -> str:
    """Render one rule as labelled lines, aligning the values under the widest label."""
    label_width = len("severity") + 2
    lines = [
        f"{'id':<{label_width}}{rule.id}",
        f"{'pack':<{label_width}}{rule.pack}",
        f"{'severity':<{label_width}}{rule.severity.value}",
        f"{'summary':<{label_width}}{rule.summary}",
        f"{'fix':<{label_width}}{rule.fix}",
        f"{'evidence':<{label_width}}{rule.evidence[0]}",
    ]
    lines.extend(" " * label_width + extra for extra in rule.evidence[1:])
    if docs is not None:
        lines.append(f"{'docs':<{label_width}}{docs}")
    return "\n".join(lines) + "\n"


def _rule_doc(rule_id: str, docs: Path) -> str | None:
    """Return the repo-relative area doc whose rules table lists ``rule_id``, or None when none does."""
    if not docs.is_dir():
        return None
    pattern = re.compile(rf"^\|\s*`{re.escape(rule_id)}`\s*\|", re.MULTILINE)
    for path in sorted(docs.glob("*.md")):
        if path.name == "README.md":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            return f"docs/rules/{path.name}"
    return None


def _rules(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Print every registered rule, ordered by pack then id, as text or JSON."""
    rules = _ordered_rules()
    if args.format == "json":
        payload = [
            {
                "id": rule.id,
                "pack": rule.pack,
                "severity": rule.severity.value,
                "summary": rule.summary,
                "fix": rule.fix,
                "evidence": list(rule.evidence),
            }
            for rule in rules
        ]
        _write_stdout(json.dumps(payload, indent=2) + "\n")
    else:
        _write_stdout(_format_rules_text(rules))
    return 0


def _explain(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Print one rule's metadata and area doc, or report an unknown id as a usage error."""
    rule = REGISTRY.get(args.rule_id)
    if rule is None:
        closest = ", ".join(_closest_ids(args.rule_id))
        sys.stderr.write(f"rigcheck explain: unknown rule id {args.rule_id!r}; closest: {closest}\n")
        return USAGE_ERROR
    docs = _rule_doc(rule.id, _RULE_DOCS)
    if args.format == "json":
        payload = {
            "id": rule.id,
            "pack": rule.pack,
            "severity": rule.severity.value,
            "summary": rule.summary,
            "fix": rule.fix,
            "evidence": list(rule.evidence),
            "docs": docs,
        }
        _write_stdout(json.dumps(payload, indent=2) + "\n")
    else:
        _write_stdout(_format_explain_text(rule, docs))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code.

    Commands are ``check`` (validate a setup), ``brief`` (write a Markdown fix brief), ``rules``
    (list every rule) and ``explain`` (describe one rule). The code is 0 clean, 1 a finding at or
    above ``--fail-on`` and 2 a usage error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"brief": _brief, "check": _check, "explain": _explain, "rules": _rules}
    handler = handlers.get(args.command or "")
    if handler is None:
        parser.print_help(sys.stderr)
        return USAGE_ERROR
    try:
        return handler(parser, args)
    except deep.DeepStop as stop:
        return stop.exit_code


if __name__ == "__main__":
    sys.exit(main())
