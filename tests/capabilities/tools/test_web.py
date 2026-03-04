from __future__ import annotations

import json
from unittest.mock import AsyncMock, Mock

import pytest

from hal.capabilities.tools.web import (
    WebFetchTool,
    WebSearchTool,
    _normalize,
    _strip_tags,
    _validate_url,
)


def test_validate_url_rejects_non_http_and_missing_domain() -> None:
    ok, msg = _validate_url("file:///etc/passwd")
    assert ok is False
    assert "http" in msg

    ok, msg = _validate_url("https://")
    assert ok is False
    assert "domain" in msg.lower()

    ok, msg = _validate_url("https://example.com/path")
    assert ok is True
    assert msg == ""


def test_strip_tags_and_normalize() -> None:
    html = "<style>bad</style><script>evil</script><p>Hello&nbsp; <b>world</b></p>\n\n\nmore"
    stripped = _strip_tags(html)
    assert "bad" not in stripped
    assert "evil" not in stripped
    assert "Hello" in stripped
    assert "world" in stripped

    normalized = _normalize("a\n\n\n\n\tb")
    assert normalized == "a\n\n b"  # whitespace normalization


@pytest.mark.asyncio
async def test_web_search_requires_api_key() -> None:
    tool = WebSearchTool(api_key="")
    out = await tool.execute(query="hi")
    assert "TAVILY_API_KEY" in out


@pytest.mark.asyncio
async def test_web_search_success_truncates_content(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "results": [
            {
                "title": "t",
                "url": "https://example.com",
                "content": "x" * 500,
            }
        ]
    }

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    client.post.return_value = resp
    monkeypatch.setattr("hal.capabilities.tools.web.httpx.AsyncClient", lambda: client)

    tool = WebSearchTool(api_key="k", max_results=5)
    out = await tool.execute(query="q", count=1)

    assert "Results for: q" in out
    assert "1." in out
    assert "https://example.com" in out
    assert "..." in out  # truncated content


@pytest.mark.asyncio
async def test_web_search_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"results": []}

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr("hal.capabilities.tools.web.httpx.AsyncClient", lambda: DummyClient())

    tool = WebSearchTool(api_key="k")
    out = await tool.execute(query="q")
    assert "No results" in out


@pytest.mark.asyncio
async def test_web_search_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("hal.capabilities.tools.web.httpx.AsyncClient", lambda: DummyClient())

    tool = WebSearchTool(api_key="k")
    out = await tool.execute(query="q")
    assert out.startswith("Error:")


@pytest.mark.asyncio
async def test_web_fetch_invalid_url_returns_json_error() -> None:
    tool = WebFetchTool()
    out = await tool.execute(url="file:///etc/passwd")
    data = json.loads(out)
    assert "error" in data


@pytest.mark.asyncio
async def test_web_fetch_json_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResp:
        status_code = 200
        url = "https://example.com/final"
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"a": 1}

        @property
        def text(self) -> str:
            return '{"a":1}'

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr(
        "hal.capabilities.tools.web.httpx.AsyncClient", lambda **kwargs: DummyClient()
    )

    tool = WebFetchTool(max_chars=1000)
    out = await tool.execute(url="https://example.com")
    data = json.loads(out)

    assert data["extractor"] == "json"
    assert data["status"] == 200
    assert "\n" in data["text"]  # pretty-printed JSON


@pytest.mark.asyncio
async def test_web_fetch_html_markdown_and_text_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyDoc:
        def __init__(self, html: str):
            self._html = html

        def title(self) -> str:
            return "My Title"

        def summary(self) -> str:
            return "<h2>H</h2><p>Hello <a href='https://x'>world</a></p><ul><li>Item</li></ul>"

    class DummyResp:
        status_code = 200
        url = "https://example.com/final"
        headers = {"content-type": "text/html"}
        text = "<html><body>hi</body></html>"

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr("readability.Document", DummyDoc)
    monkeypatch.setattr(
        "hal.capabilities.tools.web.httpx.AsyncClient", lambda **kwargs: DummyClient()
    )

    tool = WebFetchTool(max_chars=1000)

    out_md = await tool.execute(url="https://example.com", extractMode="markdown")
    data_md = json.loads(out_md)
    assert data_md["extractor"] == "readability"
    assert "# My Title" in data_md["text"]
    assert "[world](https://x)" in data_md["text"]
    assert "- Item" in data_md["text"]

    out_txt = await tool.execute(url="https://example.com", extractMode="text")
    data_txt = json.loads(out_txt)
    assert "Hello" in data_txt["text"]
    assert "world" in data_txt["text"]


@pytest.mark.asyncio
async def test_web_fetch_raw_and_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyResp:
        status_code = 200
        url = "https://example.com/final"
        headers = {"content-type": "text/plain"}
        text = "0123456789ABCDEF"

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr(
        "hal.capabilities.tools.web.httpx.AsyncClient", lambda **kwargs: DummyClient()
    )

    tool = WebFetchTool(max_chars=5)
    out = await tool.execute(url="https://example.com", maxChars=5)
    data = json.loads(out)

    assert data["extractor"] == "raw"
    assert data["truncated"] is True
    assert data["length"] == 5


@pytest.mark.asyncio
async def test_web_fetch_handles_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "hal.capabilities.tools.web.httpx.AsyncClient", lambda **kwargs: DummyClient()
    )

    tool = WebFetchTool()
    out = await tool.execute(url="https://example.com")
    data = json.loads(out)
    assert "error" in data
