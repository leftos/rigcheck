"""Helpers shared by the test modules: a fake home with rigs inside it, and CLI runs."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from rigcheck.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def git_add(repo: Path, paths: list[str]) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is not on PATH")
    # Test-owned arguments: a tmp repo path and fixture-listed file names.
    subprocess.run([git, "-C", str(repo), "init", "-q"], check=True)  # noqa: S603
    subprocess.run([git, "-C", str(repo), "add", "--", *paths], check=True)  # noqa: S603


def symlink_or_skip(link: Path, target: str) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"cannot create symlinks here: {exc}")


@dataclass(frozen=True)
class Workspace:
    """A fake home directory; rigs live under ``home/work`` so the upward walk stops at the fake home."""

    home: Path

    def rig(self, name: str = "repo") -> Path:
        path = self.home / "work" / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def run_cli(capsys: pytest.CaptureFixture[str], target: Path, home: Path, output_format: str) -> tuple[int, str]:
    code = main(["check", str(target), "--home", str(home), "--format", output_format])
    return code, capsys.readouterr().out


def run_json(capsys: pytest.CaptureFixture[str], target: Path, home: Path) -> tuple[int, dict[str, Any]]:
    code, out = run_cli(capsys, target, home, "json")
    return code, json.loads(out)
