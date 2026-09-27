"""Command-line entry point."""

import argparse
import re
import sys
from pathlib import Path

from rigcheck import __version__, engine
from rigcheck.discover import discover
from rigcheck.model import Severity
from rigcheck.report import budget, terminal
from rigcheck.report import json as json_report
from rigcheck.rules import REGISTRY

USAGE_ERROR = 2
DEFAULT_WINDOW = 200_000
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
    return parser


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
    rig = discover(target, home)
    findings = engine.run(rig, REGISTRY.values())
    report = budget.compute(rig, args.window)
    if args.format == "json":
        output = json_report.render(rig, findings, report)
    else:
        output = terminal.render(rig, findings, report, color=terminal.use_color(sys.stdout))
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.write(output)
    return 1 if any(finding.severity is Severity.ERROR for finding in findings) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 clean, 1 error findings, 2 usage error)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "check":
        parser.print_help(sys.stderr)
        return USAGE_ERROR
    return _check(parser, args)


if __name__ == "__main__":
    sys.exit(main())
