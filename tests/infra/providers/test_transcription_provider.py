from __future__ import annotations

from pathlib import Path

import pytest

from hal.infra.providers.transcription import GroqTranscriptionProvider


@pytest.mark.asyncio
async def test_transcribe_returns_empty_when_no_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    p = GroqTranscriptionProvider(api_key=None)

    f = tmp_path / "a.wav"
    f.write_bytes(b"data")

    assert await p.transcribe(f) == ""


@pytest.mark.asyncio
async def test_transcribe_returns_empty_when_file_missing(tmp_path: Path) -> None:
    p = GroqTranscriptionProvider(api_key="k")
    assert await p.transcribe(tmp_path / "missing.wav") == ""


@pytest.mark.asyncio
async def test_transcribe_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "a.wav"
    f.write_bytes(b"data")

    calls = {}

    class DummyResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"text": "hello"}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, headers=None, files=None, timeout=None):
            calls["url"] = url
            calls["headers"] = headers
            calls["files"] = files
            calls["timeout"] = timeout
            return DummyResp()

    monkeypatch.setattr(
        "hal.infra.providers.transcription.httpx.AsyncClient", lambda: DummyClient()
    )

    p = GroqTranscriptionProvider(api_key="k")
    out = await p.transcribe(f)

    assert out == "hello"
    assert calls["headers"]["Authorization"] == "Bearer k"
    assert calls["timeout"] == 60.0


@pytest.mark.asyncio
async def test_transcribe_handles_http_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "a.wav"
    f.write_bytes(b"data")

    class DummyResp:
        def raise_for_status(self) -> None:
            raise RuntimeError("http fail")

        def json(self) -> dict:
            return {"text": "no"}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, headers=None, files=None, timeout=None):
            return DummyResp()

    monkeypatch.setattr(
        "hal.infra.providers.transcription.httpx.AsyncClient", lambda: DummyClient()
    )

    p = GroqTranscriptionProvider(api_key="k")
    assert await p.transcribe(f) == ""
