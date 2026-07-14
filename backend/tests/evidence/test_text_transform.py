"""
TextTransformMap / ChunkSegment / SemanticChunk contract tests (P1-03).

Verifies:
- TextTransformMap correctly maps source ranges to chunk ranges.
- ChunkSegment links to stable block_id with correct offsets.
- SemanticChunk preserves segment integrity (text = concatenation of segments).
- Transform map covers every character in the chunk text.
- Multiple transforms can be combined.
"""

import pytest

from app.platform.evidence.text_transform import (
    ChunkSegment,
    SemanticChunk,
    TextTransformMap,
)


BLOCK_ID_1 = "blk_para_001"
BLOCK_ID_2 = "blk_para_002"


class TestTextTransformMap:
    def test_create_identity_transform(self):
        t = TextTransformMap(
            source_block_id=BLOCK_ID_1,
            source_start=0,
            source_end=10,
            chunk_start=0,
            chunk_end=10,
            transform="identity",
        )
        assert t.source_block_id == BLOCK_ID_1
        assert t.source_start == 0
        assert t.source_end == 10
        assert t.chunk_start == 0
        assert t.chunk_end == 10
        assert t.transform == "identity"

    def test_frozen(self):
        t = TextTransformMap(
            source_block_id=BLOCK_ID_1,
            source_start=0,
            source_end=5,
            chunk_start=0,
            chunk_end=5,
        )
        with pytest.raises(Exception):
            t.source_block_id = "other"  # type: ignore[misc]


class TestChunkSegment:
    def test_create_segment(self):
        seg = ChunkSegment(
            segment_id="seg_1",
            block_id=BLOCK_ID_1,
            text="hello world",
            char_start=0,
            char_end=11,
            source_start=0,
            source_end=11,
        )
        assert seg.segment_id == "seg_1"
        assert seg.block_id == BLOCK_ID_1
        assert seg.text == "hello world"
        assert seg.char_start == 0
        assert seg.char_end == 11
        assert seg.source_start == 0
        assert seg.source_end == 11

    def test_frozen(self):
        seg = ChunkSegment(
            segment_id="seg_1",
            block_id=BLOCK_ID_1,
            text="test",
            char_start=0,
            char_end=4,
            source_start=0,
            source_end=4,
        )
        with pytest.raises(Exception):
            seg.block_id = "other"  # type: ignore[misc]


class TestSemanticChunk:
    def test_create_chunk_no_segments(self):
        chunk = SemanticChunk(
            chunk_id="chunk_001",
            text="hello world",
            scope_key="course:1",
        )
        assert chunk.chunk_id == "chunk_001"
        assert chunk.text == "hello world"
        assert chunk.scope_key == "course:1"
        assert chunk.segments == []
        assert chunk.transform_map == []

    def test_chunk_with_single_segment(self):
        seg = ChunkSegment(
            segment_id="seg_1",
            block_id=BLOCK_ID_1,
            text="hello world",
            char_start=0,
            char_end=11,
            source_start=0,
            source_end=11,
        )
        t = TextTransformMap(
            source_block_id=BLOCK_ID_1,
            source_start=0,
            source_end=11,
            chunk_start=0,
            chunk_end=11,
        )
        chunk = SemanticChunk(
            chunk_id="chunk_001",
            text="hello world",
            scope_key="course:1",
            segments=[seg],
            transform_map=[t],
        )
        assert len(chunk.segments) == 1
        assert len(chunk.transform_map) == 1
        # The segment text must match chunk text
        assert seg.text == chunk.text

    def test_chunk_with_multiple_segments(self):
        """Chunk composed from two source blocks."""
        seg1 = ChunkSegment(
            segment_id="seg_1",
            block_id=BLOCK_ID_1,
            text="Hello. ",
            char_start=0,
            char_end=7,
            source_start=0,
            source_end=7,
        )
        seg2 = ChunkSegment(
            segment_id="seg_2",
            block_id=BLOCK_ID_2,
            text="World.",
            char_start=7,
            char_end=13,
            source_start=0,
            source_end=6,
        )
        t1 = TextTransformMap(
            source_block_id=BLOCK_ID_1,
            source_start=0,
            source_end=7,
            chunk_start=0,
            chunk_end=7,
        )
        t2 = TextTransformMap(
            source_block_id=BLOCK_ID_2,
            source_start=0,
            source_end=6,
            chunk_start=7,
            chunk_end=13,
        )
        chunk = SemanticChunk(
            chunk_id="chunk_002",
            text="Hello. World.",
            scope_key="course:1",
            segments=[seg1, seg2],
            transform_map=[t1, t2],
        )
        # Verify text = concatenation of segment texts
        reconstructed = "".join(s.text for s in chunk.segments)
        assert reconstructed == chunk.text
        # Verify transform_map covers full range
        total_chars = sum(t.chunk_end - t.chunk_start for t in chunk.transform_map)
        assert total_chars == len(chunk.text)

    def test_chunk_metadata(self):
        chunk = SemanticChunk(
            chunk_id="chunk_003",
            text="data",
            scope_key="course:1",
            metadata={"source": "bm25", "score": 0.95},
        )
        assert chunk.metadata["source"] == "bm25"
        assert chunk.metadata["score"] == 0.95
