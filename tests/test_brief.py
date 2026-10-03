"""Tests for the Markdown fix brief: ``report/brief.py`` and the ``brief`` command."""

import re
from pathlib import Path
from typing import Any

import pytest

from rigcheck.cli import main
from rigcheck.model import DEFAULT_WINDOW, Finding, Layer, LoadClass, Rig, Severity
from rigcheck.report import brief
from rigcheck.rules import REGISTRY
from support import Workspace, write


def _warn_rig(workspace: Workspace) -> Path:
    """A rig whose one finding is reference-path-missing (warn)."""
    rig = workspace.rig()
    write(rig / "docs" / "other.md", "x\n")
    write(rig / "CLAUDE.md", "Read `docs/gone.md`.\n")
    return rig


def _suppress(rig: Path, *entries: str) -> None:
    write(rig / ".rigcheck.toml", "\n".join(f"[[suppress]]\n{entry}" for entry in entries))


def _brief(workspace: Workspace, rig: Path, *flags: str) -> int:
    return main(["brief", str(rig), "--home", str(workspace.home), *flags])


def _fake_rig(workspace: Workspace) -> Rig:
    """A rig that carries no artifacts, for rendering hand-built findings."""
    root = workspace.rig()
    return Rig(
        target=root,
        repo_root=root,
        home=workspace.home,
        artifacts=(),
        problems=(),
        user_mcp_servers=(),
        window=DEFAULT_WINDOW,
    )


def _file_finding(rig: Rig, name: str, line: int | None = None, message: str = "stale") -> Finding:
    return Finding("reference-path-missing", Severity.WARN, rig.repo_root / name, line, message, "Fix it.", Layer.REPO, LoadClass.EVERY_TURN)


def test_brief_header_names_target_and_never_edits(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    assert _brief(workspace, rig) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"# rigcheck fix brief: {rig.resolve().as_posix()}"
    assert (
        "rigcheck never edits the files it checks. Work through the findings below and tick each box once it is fixed; "
        "`rigcheck explain <rule-id>` shows a rule's evidence."
    ) in out


def test_brief_checkbox_lines_have_fix_and_evidence(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    assert _brief(workspace, rig) == 0
    out = capsys.readouterr().out
    assert "## CLAUDE.md" in out
    lines = out.splitlines()
    index = next(
        position for position, candidate in enumerate(lines) if re.fullmatch(r"- \[ \] CLAUDE\.md:\d+ reference-path-missing \(warn\): .+", candidate)
    )
    rule = REGISTRY["reference-path-missing"]
    assert lines[index + 1] == f"  Fix: {rule.fix}"
    assert lines[index + 2] == f"  Evidence: {', '.join(rule.evidence)}"


def test_brief_puts_setup_findings_first(workspace: Workspace) -> None:
    rig = _fake_rig(workspace)
    setup = Finding("not-a-rule", Severity.WARN, None, None, "The setup has a problem.", "Fix it.", None, LoadClass.EVERY_TURN)
    out = brief.render(rig, [_file_finding(rig, "CLAUDE.md", 1), setup])
    assert out.index("## Setup") < out.index("## CLAUDE.md")
    assert "- [ ] not-a-rule (warn): The setup has a problem." in out
    assert "  Evidence: none" in out


def test_brief_orders_sections_by_first_ranked_finding(workspace: Workspace) -> None:
    rig = _fake_rig(workspace)
    out = brief.render(rig, [_file_finding(rig, "b.md", 2), _file_finding(rig, "a.md", 1)])
    assert out.index("## b.md") < out.index("## a.md")


def test_brief_line_none_has_no_colon(workspace: Workspace) -> None:
    rig = _fake_rig(workspace)
    out = brief.render(rig, [_file_finding(rig, "CLAUDE.md", None)])
    assert "- [ ] CLAUDE.md reference-path-missing (warn): stale" in out
    assert "CLAUDE.md:" not in out


def test_brief_full_text_with_sections(workspace: Workspace) -> None:
    rig = _fake_rig(workspace)
    setup = Finding("not-a-rule", Severity.WARN, None, None, "The setup has a problem.", "Fix the setup.", None, LoadClass.EVERY_TURN)
    first = _file_finding(rig, "CLAUDE.md", 3, "stale one")
    second = _file_finding(rig, "CLAUDE.md", None, "stale two")
    expected = (
        f"# rigcheck fix brief: {rig.target.as_posix()}\n"
        "\n"
        "rigcheck never edits the files it checks. Work through the findings below and tick each box once it is fixed; "
        "`rigcheck explain <rule-id>` shows a rule's evidence.\n"
        "\n"
        "## Setup\n"
        "\n"
        "- [ ] not-a-rule (warn): The setup has a problem.\n"
        "  Fix: Fix the setup.\n"
        "  Evidence: none\n"
        "\n"
        "## CLAUDE.md\n"
        "\n"
        "- [ ] CLAUDE.md:3 reference-path-missing (warn): stale one\n"
        "  Fix: Fix it.\n"
        "  Evidence: sota:#2 (A), sota:#23 (B)\n"
        "- [ ] CLAUDE.md reference-path-missing (warn): stale two\n"
        "  Fix: Fix it.\n"
        "  Evidence: sota:#2 (A), sota:#23 (B)\n"
    )
    assert brief.render(rig, [setup, first, second]) == expected


def test_brief_omits_suppressed_findings(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    _suppress(rig, 'rule = "reference-path-missing"\nreason = "moved"\n')
    assert _brief(workspace, rig) == 0
    out = capsys.readouterr().out
    assert "No findings." in out
    assert "reference-path-missing" not in out


def test_brief_no_findings(workspace: Workspace) -> None:
    rig = _fake_rig(workspace)
    assert brief.render(rig, []) == (
        f"# rigcheck fix brief: {rig.target.as_posix()}\n\n"
        "rigcheck never edits the files it checks. Work through the findings below and tick each box once it is fixed; "
        "`rigcheck explain <rule-id>` shows a rule's evidence.\n\nNo findings.\n"
    )


def test_brief_output_file_written_and_stdout_empty(workspace: Workspace, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rig = _warn_rig(workspace)
    out_file = tmp_path / "out.md"
    assert _brief(workspace, rig, "-o", str(out_file)) == 0
    assert capsys.readouterr().out == ""
    data = out_file.read_bytes()
    assert b"\r\n" not in data
    assert data.decode("utf-8").startswith(f"# rigcheck fix brief: {rig.resolve().as_posix()}\n")


def test_brief_output_missing_folder_exits_2(workspace: Workspace, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _brief(workspace, _warn_rig(workspace), "-o", str(tmp_path / "nope" / "out.md"))
    assert exit_info.value.code == 2
    assert "--output folder does not exist" in capsys.readouterr().err


def test_brief_output_is_folder_exits_2(workspace: Workspace, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _brief(workspace, _warn_rig(workspace), "-o", str(tmp_path))
    assert exit_info.value.code == 2
    assert "--output is a folder" in capsys.readouterr().err


def test_brief_output_write_failure_exits_2(
    workspace: Workspace, capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_file = tmp_path / "out.md"
    real_open = Path.open

    def deny(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == out_file:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny)
    with pytest.raises(SystemExit) as exit_info:
        _brief(workspace, _warn_rig(workspace), "-o", str(out_file))
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "cannot write --output" in err
    assert "Permission denied" in err


def test_brief_writes_nothing_into_the_repo(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace)
    before = sorted(path for path in rig.rglob("*"))
    assert _brief(workspace, rig) == 0
    capsys.readouterr()
    assert sorted(path for path in rig.rglob("*")) == before


def test_brief_takes_check_flags(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    assert _brief(workspace, _warn_rig(workspace), "--only", "reference-path-missing", "--packs", "core") == 0
    assert "reference-path-missing" in capsys.readouterr().out
