"""Vendor SchemaStore's Claude Code settings schema, at one commit, into ``src/rigcheck/data/``.

Usage: ``uv run python scripts/update_schema.py [COMMIT]``. The schema is written byte for byte, and a
meta file beside it records where it came from.
"""

import argparse
import json
import re
import urllib.request
from pathlib import Path

PINNED_COMMIT = "d2cbdcde9855c1bf9ea99c336163cc6c93753e39"
"""The SchemaStore commit the vendored schema is taken from when no other is given."""

URL = "https://raw.githubusercontent.com/SchemaStore/schemastore/{commit}/src/schemas/json/claude-code-settings.json"
"""Where the schema lives in SchemaStore at a given commit."""

DATA = Path(__file__).resolve().parent.parent / "src" / "rigcheck" / "data"
"""The package folder the schema and its meta file are written to."""

SCHEMA_NAME = "claude-code-settings.schema.json"
META_NAME = "claude-code-settings.schema.meta.json"


def _download(url: str) -> bytes:
    """Return the body at ``url``, failing when it is not a JSON object."""
    # The URL is the fixed https template above with a hex commit id checked by main().
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
        body = response.read()
    if not isinstance(json.loads(body), dict):
        raise SystemExit(f"{url} did not return a JSON object; the schema was not updated")
    return body


def main(argv: list[str] | None = None) -> int:
    """Download the schema at the given commit and write it and its meta file into the package.

    Args:
        argv: The command-line arguments, without the program name; None reads them from ``sys.argv``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("commit", nargs="?", default=PINNED_COMMIT, help=f"SchemaStore commit id (default {PINNED_COMMIT})")
    args = parser.parse_args(argv)
    commit = args.commit.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        parser.error(f"commit must be a full 40-character hex id, got {args.commit!r}")
    url = URL.format(commit=commit)
    body = _download(url)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / SCHEMA_NAME).write_bytes(body)
    meta = {"source": url, "commit": commit, "license": "Apache-2.0"}
    (DATA / META_NAME).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {DATA / SCHEMA_NAME} ({len(body)} bytes) from {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
