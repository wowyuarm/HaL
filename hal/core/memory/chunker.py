"""Heading-based markdown chunker for semantic search indexing.

Splits markdown files into chunks at heading boundaries, with configurable
maximum size and overlap for large sections.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """A single chunk of markdown content with source metadata."""

    content: str
    source: str  # Relative path to source file
    heading: str
    heading_level: int  # 0 = preamble (before first heading), 1-6 for h1-h6
    start_line: int
    end_line: int
    content_hash: str = field(default="", repr=False)

    def __post_init__(self):
        if not self.content_hash:
            h = hashlib.sha256(self.content.encode()).hexdigest()[:16]
            object.__setattr__(self, "content_hash", h)

    @property
    def chunk_id(self) -> str:
        """Content-addressable ID for deduplication and Milvus PK."""
        raw = f"{self.source}:{self.start_line}:{self.end_line}:{self.content_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_chunk_id(chunk: Chunk, model: str) -> str:
    """Compute model-aware chunk ID for Milvus PK.

    Includes the embedding model name so that switching models
    invalidates old chunks and forces re-embedding.
    """
    raw = (
        f"markdown:{chunk.source}:{chunk.start_line}:{chunk.end_line}:{chunk.content_hash}:{model}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class MarkdownChunker:
    """Split markdown into heading-based chunks.

    Algorithm:
    1. Find all headings via regex.
    2. Split into sections at heading boundaries.
    3. If a section <= max_size chars, emit as one chunk.
    4. If a section > max_size, split on blank lines with overlap.
    """

    def __init__(self, max_size: int = 1000, overlap_lines: int = 2):
        self._max_size = max_size
        self._overlap_lines = overlap_lines

    def chunk_file(self, path: Path, base_path: Path | None = None) -> list[Chunk]:
        """Chunk a markdown file. Source is set relative to base_path if provided."""
        text = path.read_text(encoding="utf-8")
        if base_path:
            source = str(path.relative_to(base_path))
        else:
            source = path.name
        return self.chunk_text(text, source)

    def chunk_text(self, text: str, source: str) -> list[Chunk]:
        """Chunk raw markdown text."""
        if not text.strip():
            return []

        lines = text.split("\n")
        sections = self._split_into_sections(lines)
        chunks: list[Chunk] = []

        for heading, heading_level, start_line, section_lines in sections:
            section_text = "\n".join(section_lines)
            if len(section_text) <= self._max_size:
                if section_text.strip():
                    chunks.append(
                        Chunk(
                            content=section_text,
                            source=source,
                            heading=heading,
                            heading_level=heading_level,
                            start_line=start_line,
                            end_line=start_line + len(section_lines) - 1,
                        )
                    )
            else:
                chunks.extend(
                    self._split_large_section(
                        section_lines, source, heading, heading_level, start_line
                    )
                )

        return chunks

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _split_into_sections(
        lines: list[str],
    ) -> list[tuple[str, int, int, list[str]]]:
        """Split lines into (heading, level, start_line, lines) sections."""
        sections: list[tuple[str, int, int, list[str]]] = []
        heading_positions: list[tuple[int, str, int]] = []  # (line_idx, heading_text, level)

        for i, line in enumerate(lines):
            m = _HEADING_RE.match(line)
            if m:
                heading_positions.append((i, m.group(2).strip(), len(m.group(1))))

        if not heading_positions:
            # No headings — entire file is one chunk
            return [("", 0, 0, lines)]

        # Preamble before first heading
        first_idx = heading_positions[0][0]
        if first_idx > 0:
            preamble = lines[:first_idx]
            if any(line.strip() for line in preamble):
                sections.append(("", 0, 0, preamble))

        # Sections between headings
        for i, (line_idx, heading_text, level) in enumerate(heading_positions):
            if i + 1 < len(heading_positions):
                end_idx = heading_positions[i + 1][0]
            else:
                end_idx = len(lines)
            section_lines = lines[line_idx:end_idx]
            sections.append((heading_text, level, line_idx, section_lines))

        return sections

    def _split_large_section(
        self,
        section_lines: list[str],
        source: str,
        heading: str,
        heading_level: int,
        base_start: int,
    ) -> list[Chunk]:
        """Split an oversized section on blank lines with overlap."""
        # Find blank-line boundaries for paragraph splitting
        paragraphs: list[tuple[int, int]] = []  # (start, end) indices into section_lines
        para_start = 0

        for i, line in enumerate(section_lines):
            if not line.strip() and i > para_start:
                paragraphs.append((para_start, i))
                para_start = i + 1
        if para_start < len(section_lines):
            paragraphs.append((para_start, len(section_lines)))

        if not paragraphs:
            return []

        chunks: list[Chunk] = []
        current_lines: list[str] = []
        current_start = paragraphs[0][0]

        for para_start_idx, para_end_idx in paragraphs:
            para_lines = section_lines[para_start_idx:para_end_idx]
            candidate = current_lines + para_lines
            candidate_text = "\n".join(candidate)

            if len(candidate_text) > self._max_size and current_lines:
                # Emit current chunk
                content = "\n".join(current_lines)
                if content.strip():
                    chunks.append(
                        Chunk(
                            content=content,
                            source=source,
                            heading=heading,
                            heading_level=heading_level,
                            start_line=base_start + current_start,
                            end_line=base_start + current_start + len(current_lines) - 1,
                        )
                    )
                # Start new chunk with overlap
                overlap = current_lines[-self._overlap_lines :] if self._overlap_lines else []
                current_lines = overlap + para_lines
                current_start = para_start_idx - len(overlap)
            else:
                current_lines = candidate

        # Final chunk
        if current_lines:
            content = "\n".join(current_lines)
            if content.strip():
                chunks.append(
                    Chunk(
                        content=content,
                        source=source,
                        heading=heading,
                        heading_level=heading_level,
                        start_line=base_start + current_start,
                        end_line=base_start + current_start + len(current_lines) - 1,
                    )
                )

        return chunks
