"""Command-line entry point."""

import argparse
import sys

from rigcheck import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="rigcheck", description="Validate a coding-agent instruction setup.")
    parser.add_argument("--version", action="version", version=f"rigcheck {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
