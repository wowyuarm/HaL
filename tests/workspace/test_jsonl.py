from __future__ import annotations

from pathlib import Path

from hal.workspace.jsonl import append_jsonl_line, read_jsonl_lines


def test_append_jsonl_line_creates_parent_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "logs" / "events.jsonl"

    append_jsonl_line(file_path, '{"type":"user_message"}')

    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8").strip() == '{"type":"user_message"}'


def test_read_jsonl_lines_returns_stripped_non_empty_rows(tmp_path: Path) -> None:
    file_path = tmp_path / "logs" / "events.jsonl"
    file_path.parent.mkdir(parents=True)
    file_path.write_text('{"a":1}\n\n{"b":2}\n', encoding="utf-8")

    assert read_jsonl_lines(file_path) == ['{"a":1}', '{"b":2}']
