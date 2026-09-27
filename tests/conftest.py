from pathlib import Path

import pytest

from support import Workspace


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return Workspace(home=home.resolve())
