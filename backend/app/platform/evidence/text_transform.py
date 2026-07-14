"""TextTransformMap, ChunkSegment, and SemanticChunk — character mapping contracts.

These types preserve the mapping from original document text to chunked/
transformed text. This is critical for:
- Citation validation (mapping cited text back to original blocks)
- Evidence viewer highlighting (mapping character offsets)
- RAG evaluation (measuring what was actually retrieved)

Design rules (per plan §5):
- Chunk transformations MUST NOT lose the original character mapping.
- ``TextTransformMap`` records how original char offsets map to chunk offsets.
- ``ChunkSegment`` is a contiguous segment within a chunk, linked to a source block.
- ``SemanticChunk`` is the final retrieval unit with its transform history.

Consumes P1-01 stable IDs:
  - ``block_id`` from ContentBlock / TableBlock / FormulaBlock

Contract version: ``text-transform/1.0`` (major=1, registered in registry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

TEXT_TRANSFORM_VERSION = "text-transform/1.0"


@dataclass(frozen=True)
class TextTransformMap:
    """Records how original source text maps to a chunk's text.

    Each entry maps a range in the original source to a range in the
    chunk text. Multiple entries can cover a single chunk (e.g., when
    merging paragraphs).

    Fields:
        source_block_id:  Stable P1-01 block_id this segment comes from.
        source_start:     Zero-based start offset in the source block's text.
        source_end:       Zero-based end offset (exclusive) in source block's text.
        chunk_start:      Zero-based start offset in the chunk's text.
        chunk_end:        Zero-based end offset (exclusive) in chunk's text.
        transform:        Description of transform applied (e.g., "identity",
                          "whitespace_normalized", "html_stripped").
    """

    source_block_id: str
    source_start: int
    source_end: int
    chunk_start: int
    chunk_end: int
    transform: str = "identity"


@dataclass(frozen=True)
class ChunkSegment:
    """A contiguous segment of text within a chunk, linked to a source block.

    Fields:
        segment_id:    Unique identifier for this segment within the chunk.
        block_id:      Stable P1-01 block_id this segment originated from.
        text:          The actual text content of this segment.
        char_start:    Zero-based start offset within the chunk's full text.
        char_end:      Zero-based end offset (exclusive) within the chunk's text.
        source_start:  Zero-based start offset in the original source block.
        source_end:    Zero-based end offset (exclusive) in the original source.
    """

    segment_id: str
    block_id: str
    text: str
    char_start: int
    char_end: int
    source_start: int
    source_end: int


@dataclass
class SemanticChunk:
    """A retrieval-ready chunk with full provenance to original source blocks.

    ``chunk_id`` is a stable identifier (may be the transition chunk_id from
    ``stable_chunk_id()``, or a future persistent DB key).

    ``segments`` list all original-source segments composing this chunk.
    ``transform_map`` records the full transform history.

    Design rules:
    - The concatenation of ``segments[].text`` MUST equal ``text``.
    - ``transform_map`` MUST cover every character in ``text``.
    - When a chunk is built from a single block with no transforms,
      there is exactly one segment and one transform entry.
    """

    chunk_id: str
    text: str
    scope_key: str
    segments: List[ChunkSegment] = field(default_factory=list)
    transform_map: List[TextTransformMap] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
