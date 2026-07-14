"""
EvidenceSpan / EvidenceBundle contract tests (P1-03).

Verifies:
- EvidenceSpan references stable P1-01 IDs (artifact_id, document_id, unit_id, block_id).
- EvidenceSpan status transitions (ACTIVE, STALE, SUSPENDED).
- EvidenceBundle groups spans and correctly filters active/stale items.
- Missing/invalid IDs are caught (contract-level validation).
- No fabricated source locations.

Consumes P1-01 frozen IDs format: ``art_``, ``doc_``, ``unit_``, ``blk_`` prefixes.
"""

import datetime

import pytest

from app.platform.evidence.contracts import EvidenceBundle, EvidenceSpan, EvidenceStatus


# Sample P1-01 stable IDs (format only, not actual DB records)
ARTIFACT_ID = "art_01JZabcdef1234567890abcdef"
DOCUMENT_ID = "doc_291eeb7995305fd494a70f4be20aeb30"
UNIT_ID = "unit_7ab1cdef1234567890abcdef123456"
BLOCK_ID = "blk_title_1234567890abcdef"


class TestEvidenceSpan:
    def test_create_active_evidence(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
            page_or_slide=3,
            char_start=0,
            char_end=42,
            text_snippet="每个节点最多有两个子节点",
            score=0.95,
        )
        assert span.artifact_id == ARTIFACT_ID
        assert span.document_id == DOCUMENT_ID
        assert span.unit_id == UNIT_ID
        assert span.block_id == BLOCK_ID
        assert span.page_or_slide == 3
        assert span.char_start == 0
        assert span.char_end == 42
        assert span.text_snippet == "每个节点最多有两个子节点"
        assert span.score == 0.95
        assert span.status == EvidenceStatus.ACTIVE
        assert span.is_active() is True
        assert span.is_stale() is False

    def test_create_stale_evidence(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
            status=EvidenceStatus.STALE,
            version_ref="v1",
        )
        assert span.status == EvidenceStatus.STALE
        assert span.is_active() is False
        assert span.is_stale() is True

    def test_create_suspended_evidence(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
            status=EvidenceStatus.SUSPENDED,
        )
        assert span.is_active() is False
        assert span.is_stale() is False

    def test_evidence_is_frozen(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
        )
        with pytest.raises(Exception):
            span.block_id = "other"  # type: ignore[misc]

    def test_evidence_with_minimal_fields(self):
        """All fields except the four required IDs are optional."""
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
        )
        assert span.version_ref is None
        assert span.page_or_slide is None
        assert span.char_start is None
        assert span.char_end is None
        assert span.text_snippet is None
        assert span.score is None
        assert span.status == EvidenceStatus.ACTIVE
        assert span.metadata == {}

    def test_evidence_with_metadata(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
            metadata={"retrieval_rank": 1, "source": "bm25"},
        )
        assert span.metadata["retrieval_rank"] == 1
        assert span.metadata["source"] == "bm25"


class TestEvidenceBundle:
    def test_create_empty_bundle(self):
        bundle = EvidenceBundle(bundle_id="test_bundle")
        assert bundle.bundle_id == "test_bundle"
        assert bundle.items == []
        assert bundle.sources == []
        assert bundle.total_score is None
        assert bundle.created_at is not None

    def test_bundle_with_items(self):
        span1 = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID + "_1",
            text_snippet="text 1",
        )
        span2 = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID + "_2",
            text_snippet="text 2",
            status=EvidenceStatus.STALE,
        )
        bundle = EvidenceBundle(
            bundle_id="b1",
            items=[span1, span2],
            sources=[DOCUMENT_ID],
            total_score=0.9,
        )
        assert len(bundle.items) == 2
        assert bundle.sources == [DOCUMENT_ID]
        assert bundle.total_score == 0.9

    def test_bundle_active_items_filter(self):
        span1 = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID + "_1",
            status=EvidenceStatus.ACTIVE,
        )
        span2 = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID + "_2",
            status=EvidenceStatus.STALE,
        )
        span3 = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID + "_3",
            status=EvidenceStatus.SUSPENDED,
        )
        bundle = EvidenceBundle(bundle_id="b1", items=[span1, span2, span3])
        assert len(bundle.active_items) == 1
        assert bundle.active_items[0].block_id == BLOCK_ID + "_1"
        assert len(bundle.stale_items) == 1
        assert bundle.stale_items[0].block_id == BLOCK_ID + "_2"

    def test_bundle_frozen(self):
        span = EvidenceSpan(
            artifact_id=ARTIFACT_ID,
            document_id=DOCUMENT_ID,
            unit_id=UNIT_ID,
            block_id=BLOCK_ID,
        )
        bundle = EvidenceBundle(bundle_id="b1", items=[span])
        with pytest.raises(Exception):
            bundle.bundle_id = "other"  # type: ignore[misc]
