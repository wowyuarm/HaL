from __future__ import annotations

import runpy
import sys

import pytest


def test_python_m_hal_help_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["hal", "--help"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("hal.__main__", run_name="__main__")
    assert exc.value.code == 0
