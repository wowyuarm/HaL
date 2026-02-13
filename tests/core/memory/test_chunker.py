"""Tests for MarkdownChunker — heading-based markdown splitting."""

import pytest

from hal.core.memory.chunker import MarkdownChunker


@pytest.fixture
def chunker():
    return MarkdownChunker(max_size=200, overlap_lines=2)


class TestChunkText:
    def test_empty_text(self, chunker):
        assert chunker.chunk_text("", "test.md") == []
        assert chunker.chunk_text("   \n  \n  ", "test.md") == []

    def test_no_headings(self, chunker):
        text = "Just a paragraph.\n\nAnother paragraph."
        chunks = chunker.chunk_text(text, "test.md")
        assert len(chunks) == 1
        assert chunks[0].heading == ""
        assert chunks[0].heading_level == 0

    def test_heading_split(self, chunker):
        text = "# Title\n\nContent A\n\n## Section\n\nContent B"
        chunks = chunker.chunk_text(text, "test.md")
        assert len(chunks) == 2
        assert chunks[0].heading == "Title"
        assert chunks[0].heading_level == 1
        assert chunks[1].heading == "Section"
        assert chunks[1].heading_level == 2

    def test_preamble_before_heading(self, chunker):
        text = "Preamble text\n\n# Title\n\nContent"
        chunks = chunker.chunk_text(text, "test.md")
        assert len(chunks) == 2
        assert chunks[0].heading == ""
        assert chunks[0].heading_level == 0
        assert chunks[1].heading == "Title"

    def test_large_section_splits(self):
        chunker = MarkdownChunker(max_size=50, overlap_lines=1)
        text = "# Title\n\n" + "Word " * 20 + "\n\n" + "More " * 20
        chunks = chunker.chunk_text(text, "test.md")
        assert len(chunks) > 1

    def test_chunk_has_hash(self, chunker):
        text = "# Title\n\nContent here"
        chunks = chunker.chunk_text(text, "test.md")
        assert chunks[0].content_hash
        assert len(chunks[0].content_hash) == 16

    def test_chunk_id_is_unique(self, chunker):
        text = "# A\n\nContent A\n\n# B\n\nContent B"
        chunks = chunker.chunk_text(text, "test.md")
        ids = {c.chunk_id for c in chunks}
        assert len(ids) == len(chunks)

    def test_chunk_id_deterministic(self, chunker):
        text = "# Title\n\nContent"
        chunks1 = chunker.chunk_text(text, "test.md")
        chunks2 = chunker.chunk_text(text, "test.md")
        assert chunks1[0].chunk_id == chunks2[0].chunk_id

    def test_different_source_different_id(self, chunker):
        text = "# Title\n\nContent"
        chunks_a = chunker.chunk_text(text, "a.md")
        chunks_b = chunker.chunk_text(text, "b.md")
        assert chunks_a[0].chunk_id != chunks_b[0].chunk_id


class TestChunkFile:
    def test_reads_file(self, chunker, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Title\n\nContent here")
        chunks = chunker.chunk_file(f)
        assert len(chunks) == 1
        assert chunks[0].source == "test.md"

    def test_relative_source(self, chunker, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "doc.md"
        f.write_text("# Title\n\nContent")
        chunks = chunker.chunk_file(f, base_path=tmp_path)
        assert chunks[0].source == "sub/doc.md"


class TestLineNumbers:
    def test_start_end_line(self, chunker):
        text = "# Title\n\nLine 1\nLine 2\n\n# Other\n\nLine 3"
        chunks = chunker.chunk_text(text, "test.md")
        assert chunks[0].start_line == 0
        assert chunks[1].start_line == 5
