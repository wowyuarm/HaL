from __future__ import annotations

from pathlib import Path

import pytest

from hal.utils import helpers


def test_truncate_string_noop_and_truncates() -> None:
    assert helpers.truncate_string("abc", max_len=5) == "abc"
    assert helpers.truncate_string("abcdef", max_len=5) == "ab..."


def test_safe_filename_replaces_unsafe_chars() -> None:
    assert helpers.safe_filename('a<>:"/\\|?*b') == "a_________b"


def test_parse_session_key_valid() -> None:
    assert helpers.parse_session_key("telegram:123") == ("telegram", "123")


def test_parse_session_key_invalid_raises() -> None:
    with pytest.raises(ValueError):
        helpers.parse_session_key("no-colon")


def test_get_workspace_path_default_uses_home_and_creates(tmp_home: Path) -> None:
    ws = helpers.get_workspace_path()
    assert ws.exists()
    assert str(ws).endswith("/.hal/workspace")


def test_get_workspace_path_custom_expands_and_creates(tmp_home: Path) -> None:
    ws = helpers.get_workspace_path("~/custom-ws")
    assert ws.exists()
    assert ws == (Path(tmp_home) / "custom-ws")


def test_get_data_path_creates_dir(tmp_home: Path) -> None:
    data = helpers.get_data_path()
    assert data.exists()
    assert str(data).endswith("/.hal")


def test_today_date_and_timestamp_format() -> None:
    d = helpers.today_date()
    assert len(d) == 10
    assert d.count("-") == 2

    ts = helpers.timestamp()
    assert "T" in ts


def test_ensure_dir_creates(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b"
    out = helpers.ensure_dir(p)
    assert out.exists()
    assert out == p
