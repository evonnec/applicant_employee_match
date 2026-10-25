from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def make_csv(tmp_path: Path) -> Callable[..., Path]:
    """Write ``text`` verbatim (no newline translation) to ``tmp_path / name`` and return the path."""

    def _make(name: str, text: str, *, encoding: str = "utf-8") -> Path:
        path = tmp_path / name
        path.write_bytes(text.encode(encoding))
        return path

    return _make
