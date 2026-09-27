import pytest

from rigcheck import __version__
from rigcheck.cli import main


def test_version_flag_prints_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"rigcheck {__version__}"


def test_unknown_flag_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--no-such-flag"])
    assert exit_info.value.code == 2
