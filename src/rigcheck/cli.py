"""Command-line entry point."""

import argparse
import difflib
import re
import sys
from pathlib import Path

from rigcheck import __version__, engine
from rigcheck.discover import discover
from rigcheck.model import DEFAULT_WINDOW, Severity
from rigcheck.report import budget, terminal
from rigcheck.report import json as json_report
from rigcheck.rules import REGISTRY

USAGE_ERROR = 2
WINDOW_ERROR = "window must be a positive number of tokens, like 200k or 1m"

_WINDOW = re.compile(r"([1-9][0-9]*)([km]?)", re.IGNORECASE)
_WINDOW_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="rigcheck", description="Validate a coding-agent instruction setup.")
    parser.add_argument("--version", action="version", version=f"rigcheck {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    check = commands.add_parser("check", help="check the effective setup Claude Code loads for a directory")
    check.add_argument("path", nargs="?", type=Path, default=None, metavar="PATH", help="directory to check (default: current directory)")
    check.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    check.add_argument("--home", type=Path, default=None, metavar="DIR", help="home directory holding .claude (default: your home)")
    check.add_argument(
        "--window", type=parse_window, default=DEFAULT_WINDOW, metavar="SIZE", help="model context window in tokens, like 200k or 1m (default: 200k)"
    )
    check.add_argument("--only", type=parse_only, default=None, metavar="ID[,ID...]", help="report only the findings of these rule ids")
    check.add_argument(
        "--fail-on",
        choices=[severity.value for severity in Severity],
        default=Severity.ERROR.value,
        help="lowest finding severity that makes the exit status 1 (default: error)",
    )
    return parser


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
            closest = difflib.get_close_matches(rule_id, sorted(REGISTRY), n=3, cutoff=0.0)
            raise argparse.ArgumentTypeError(f"unknown rule id {rule_id!r}; closest: {', '.join(closest)}")
    return frozenset(ids)


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


def _check(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    target = (args.path or Path.cwd()).resolve()
    if not target.is_dir():
        parser.error(f"not a directory: {target}")
    home = (args.home or Path.home()).resolve()
    rig = discover(target, home, args.window)
    findings = engine.run(rig, REGISTRY.values())
    if args.only is not None:
        # A selected rule that raised is reported as internal-error, so that id is always kept.
        findings = [finding for finding in findings if finding.rule_id in args.only or finding.rule_id == "internal-error"]
    report = budget.compute(rig)
    if args.format == "json":
        output = json_report.render(rig, findings, report)
    else:
        output = terminal.render(rig, findings, report, color=terminal.use_color(sys.stdout))
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.write(output)
    threshold = Severity(args.fail_on)
    return 1 if any(finding.severity.rank <= threshold.rank for finding in findings) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 clean, 1 a finding at or above --fail-on, 2 usage error)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help(sys.stderr)
        return USAGE_ERROR
    return _check(parser, args)


if __name__ == "__main__":
    sys.exit(main())
