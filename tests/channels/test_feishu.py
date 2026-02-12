from __future__ import annotations

from hal.bus.queue import MessageBus
from hal.channels.feishu import FeishuChannel
from hal.infra.config.schema import FeishuConfig


def test_parse_md_table_returns_table_element() -> None:
    table = """| A | B |
|---|---|
| 1 | 2 |
| 3 | 4 |
"""

    parsed = FeishuChannel._parse_md_table(table)
    assert parsed is not None
    assert parsed["tag"] == "table"
    assert len(parsed["columns"]) == 2
    assert parsed["columns"][0]["display_name"] == "A"
    assert parsed["rows"][0]["c0"] == "1"
    assert parsed["rows"][1]["c1"] == "4"


def test_build_card_elements_splits_markdown_and_tables() -> None:
    ch = FeishuChannel(FeishuConfig(enabled=True), MessageBus())
    content = "Intro\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\nOutro"

    elements = ch._build_card_elements(content)
    assert len(elements) == 3
    assert elements[0]["tag"] == "markdown"
    assert "Intro" in elements[0]["content"]
    assert elements[1]["tag"] == "table"
    assert elements[2]["tag"] == "markdown"
    assert "Outro" in elements[2]["content"]


def test_build_card_elements_falls_back_when_no_table() -> None:
    ch = FeishuChannel(FeishuConfig(enabled=True), MessageBus())
    elements = ch._build_card_elements("just text")
    assert elements == [{"tag": "markdown", "content": "just text"}]
