from collections.abc import Iterator
from pathlib import Path

import pytest

from rigcheck.parse import frontmatter, markdown
from support import Workspace


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
