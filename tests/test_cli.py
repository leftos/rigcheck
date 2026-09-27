import json

import pytest

from rigcheck import __version__
from rigcheck.cli import main
from support import Workspace


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
