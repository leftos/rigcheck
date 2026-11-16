from collections.abc import Iterator
from pathlib import Path

import pytest

from rigcheck.parse import frontmatter, markdown
from support import Workspace


@pytest.fixture(scope="session", autouse=True)
def _isolate_git_config(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep the user's global and system git config, and their global ignore file, out of every git process the tests start."""
    config_dir = tmp_path_factory.mktemp("git-config")
    global_config = config_dir / "gitconfig"
    global_config.write_text("", encoding="utf-8", newline="\n")
    user_config_home = config_dir / "xdg-config"
    user_config_home.mkdir()
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(user_config_home))
        yield


@pytest.fixture(autouse=True)
def _clear_parse_caches() -> Iterator[None]:
    yield
    markdown._parsed.cache_clear()
    markdown._stripped.cache_clear()
    frontmatter._parse.cache_clear()


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    home = tmp_path / "home"
    home.mkdir()
    return Workspace(home=home.resolve())
