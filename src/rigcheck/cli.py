"""Command-line entry point."""

import argparse
import sys
from pathlib import Path

from rigcheck import __version__, engine
from rigcheck.discover import discover
from rigcheck.model import Severity
from rigcheck.report import json as json_report
from rigcheck.report import terminal
from rigcheck.rules import REGISTRY

USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="rigcheck", description="Validate a coding-agent instruction setup.")
    parser.add_argument("--version", action="version", version=f"rigcheck {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    check = commands.add_parser("check", help="check the effective setup Claude Code loads for a directory")
    check.add_argument("path", nargs="?", type=Path, default=None, metavar="PATH", help="directory to check (default: current directory)")
    check.add_argument("--format", choices=("text", "json"), default="text", help="output format (default: text)")
    check.add_argument("--home", type=Path, default=None, metavar="DIR", help="home directory holding .claude (default: your home)")
    return parser


def _check(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    target = (args.path or Path.cwd()).resolve()
    if not target.is_dir():
        parser.error(f"not a directory: {target}")
    home = (args.home or Path.home()).resolve()
    rig = discover(target, home)
    findings = engine.run(rig, REGISTRY.values())
    output = json_report.render(rig, findings) if args.format == "json" else terminal.render(rig, findings, color=terminal.use_color(sys.stdout))
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
