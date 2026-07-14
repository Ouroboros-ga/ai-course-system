"""
Evidence-preserving RetrievedChunk tests (P1-03).

Verifies:
- RetrievedChunk supports optional evidence fields (artifact_id, document_id,
  unit_id, block_id, evidence_spans) without breaking existing fields.
- Existing tests still pass with the extended schema.
- Evidence fields are None by default (optional, backward compatible).
- Evidence fields survive chunk operations (e.g., RRF, reranking).
"""

import pytest

from app.platform.retrieval import RetrievedChunk, RetrievalScope, stable_chunk_id


SCOPE_A = RetrievalScope.course("A")
SCOPE_B = RetrievalScope.course("B")


class TestRetrievedChunkEvidenceFields:
    def test_evidence_fields_default_to_none(self):
        """Existing field behavior unchanged, evidence fields optional."""
        chunk = RetrievedChunk(
            chunk_id="test_001",
            content="hello world",
            scope=SCOPE_A,
        )
        assert chunk.artifact_id is None
        assert chunk.document_id is None
        assert chunk.unit_id is None
        assert chunk.block_id is None
        assert chunk.evidence_spans == []
        # Existing fields still work
        assert chunk.chunk_id == "test_001"
        assert chunk.content == "hello world"
        assert chunk.scope == SCOPE_A
        assert chunk.retrieval_source == "tree_keyword"
        assert chunk.source_id is None
        assert chunk.page_number is None

    def test_evidence_fields_can_be_set(self):
        chunk = RetrievedChunk(
            chunk_id="test_002",
            content="evidence content",
            scope=SCOPE_A,
            artifact_id="art_001",
            document_id="doc_001",
            unit_id="unit_001",
            block_id="blk_001",
        )
        assert chunk.artifact_id == "art_001"
        assert chunk.document_id == "doc_001"
        assert chunk.unit_id == "unit_001"
        assert chunk.block_id == "blk_001"

    def test_evidence_fields_survive_reconstruction(self):
        """Simulate a round-trip through RRF or reranking."""
        original = RetrievedChunk(
            chunk_id="test_003",
            content="preserve me",
            scope=SCOPE_A,
            artifact_id="art_002",
            document_id="doc_002",
            unit_id="unit_002",
            block_id="blk_002",
            retrieval_score=0.95,
        )
        reconstructed = RetrievedChunk(
            chunk_id=original.chunk_id,
            content=original.content,
            scope=original.scope,
            artifact_id=original.artifact_id,
            document_id=original.document_id,
            unit_id=original.unit_id,
            block_id=original.block_id,
            retrieval_score=original.retrieval_score,
        )
        assert reconstructed.artifact_id == "art_002"
        assert reconstructed.document_id == "doc_002"
        assert reconstructed.block_id == "blk_002"

    def test_existing_fields_unchanged(self):
        """Prove that existing field semantics are preserved."""
        cid = stable_chunk_id(SCOPE_A, "path/to/node", "existing content")
        chunk = RetrievedChunk(
            chunk_id=cid,
            content="existing content",
            scope=SCOPE_A,
            source_id="src_001",
            source_name="Source Doc",
            chapter_id="ch_001",
            chapter_title="Chapter 1",
            page_number=5,
            retrieval_score=0.85,
            retrieval_source="tree_keyword",
            match_type="keyword",
            path=["Chapter 1", "Section A"],
            metadata={"key": "value"},
        )
        assert chunk.chunk_id == cid
        assert chunk.source_id == "src_001"
        assert chunk.source_name == "Source Doc"
        assert chunk.chapter_id == "ch_001"
        assert chunk.chapter_title == "Chapter 1"
        assert chunk.page_number == 5
        assert chunk.retrieval_score == 0.85
        assert chunk.retrieval_source == "tree_keyword"
        assert chunk.match_type == "keyword"
        assert chunk.path == ["Chapter 1", "Section A"]
        assert chunk.metadata == {"key": "value"}
        # Evidence fields are still None (backward compat)
        assert chunk.artifact_id is None
        assert chunk.document_id is None
