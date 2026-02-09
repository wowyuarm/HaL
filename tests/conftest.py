from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated HOME directory for tests that touch ~/.hal.

    Many HaL components use Path.home() to write under ~/.hal/.
    This fixture ensures tests don't write to the developer's real home.
    """

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    return home
