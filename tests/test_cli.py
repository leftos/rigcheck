import json
from pathlib import Path

import pytest

from rigcheck import __version__
from rigcheck.cli import main
from support import Workspace, write


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"rigcheck {__version__}"


def test_unknown_flag_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-flag"])
    assert exit_info.value.code == 2


@pytest.mark.parametrize(("value", "window"), [("200k", 200_000), ("200K", 200_000), ("1m", 1_000_000), ("1M", 1_000_000), ("1500", 1_500)])
def test_window_accepts_k_and_m_suffixes(workspace: Workspace, capsys: pytest.CaptureFixture[str], value: str, window: int) -> None:
    main(["check", str(workspace.rig()), "--home", str(workspace.home), "--format", "json", "--window", value])
    assert json.loads(capsys.readouterr().out)["budget"]["window"] == window


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5m", "k", "200kb", ""])
def test_window_rejects_garbage(workspace: Workspace, capsys: pytest.CaptureFixture[str], value: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["check", str(workspace.rig()), "--home", str(workspace.home), "--window", value])
    assert exit_info.value.code == 2
    assert "window must be a positive number of tokens, like 200k or 1m" in capsys.readouterr().err


def _warn_rig(workspace: Workspace, claude_md: str = "Read `docs/gone.md`.\n") -> Path:
    """A rig whose one finding is reference-path-missing (warn), plus whatever ``claude_md`` adds."""
    rig = workspace.rig()
    write(rig / "docs" / "other.md", "x\n")
    write(rig / "CLAUDE.md", claude_md)
    return rig


def _check(workspace: Workspace, rig: Path, *flags: str) -> int:
    return main(["check", str(rig), "--home", str(workspace.home), *flags])


def test_only_filters_json_findings(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace, "Read `docs/gone.md`.\n\n@missing.md\n")
    assert _check(workspace, rig, "--format", "json") == 1
    assert {finding["rule"] for finding in json.loads(capsys.readouterr().out)["findings"]} == {"reference-path-missing", "import-unresolved"}
    assert _check(workspace, rig, "--format", "json", "--only", "reference-path-missing") == 0
    assert [finding["rule"] for finding in json.loads(capsys.readouterr().out)["findings"]] == ["reference-path-missing"]


def test_only_filters_text_findings(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    rig = _warn_rig(workspace, "Read `docs/gone.md`.\n\n@missing.md\n")
    assert _check(workspace, rig, "--only", "import-unresolved, reference-script-missing") == 1
    out = capsys.readouterr().out
    assert "import-unresolved" in out
    assert "reference-path-missing" not in out


def test_only_with_an_unknown_rule_id_names_the_closest(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--only", "reference-path-missing,reference-path-mising")
    assert exit_info.value.code == 2
    assert "unknown rule id 'reference-path-mising'; closest: reference-path-missing" in capsys.readouterr().err


def test_only_with_no_rule_id_is_a_usage_error(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--only", " , ")
    assert exit_info.value.code == 2
    assert "give at least one rule id" in capsys.readouterr().err


@pytest.mark.parametrize(("flags", "code"), [((), 0), (("--fail-on", "error"), 0), (("--fail-on", "warn"), 1), (("--fail-on", "info"), 1)])
def test_fail_on_sets_the_lowest_failing_severity(
    workspace: Workspace, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...], code: int
) -> None:
    rig = _warn_rig(workspace)
    assert _check(workspace, rig, "--format", "json", *flags) == code
    assert {finding["severity"] for finding in json.loads(capsys.readouterr().out)["findings"]} == {"warn"}


def test_fail_on_rejects_an_unknown_severity(workspace: Workspace) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _check(workspace, workspace.rig(), "--fail-on", "warning")
    assert exit_info.value.code == 2
