"""
Citation / CitationValidationResult contract tests (P1-03).

Verifies:
- citation_key() produces deterministic keys from evidence coordinates.
- citation_key() returns None when block_id is None/empty (no fake key).
- Citation stores statement + evidence reference correctly.
- CitationValidationResult handles all statuses (VERIFIED, NO_EVIDENCE, etc.).
- No-evidence abstention: NO_EVIDENCE status => abstain=True.
- citation_key() produces block-level keys when char offsets are omitted.
"""

import pytest

from app.platform.evidence.citation import (
    Citation,
    CitationStatus,
    CitationValidationResult,
    citation_key,
)


ARTIFACT_ID = "art_01JZabcdef1234567890abcdef"
BLOCK_ID = "blk_title_1234567890abcdef"


class TestCitationKey:
    def test_key_is_deterministic(self):
        k1 = citation_key(ARTIFACT_ID, BLOCK_ID, 0, 42)
        k2 = citation_key(ARTIFACT_ID, BLOCK_ID, 0, 42)
        assert k1 == k2
        assert len(k1) == 12  # SHA-256[:12]
        # Verify hex chars
        int(k1, 16)

    def test_different_inputs_different_keys(self):
        k1 = citation_key(ARTIFACT_ID, BLOCK_ID, 0, 42)
        k2 = citation_key(ARTIFACT_ID, BLOCK_ID, 0, 43)
        assert k1 != k2

    def test_block_level_key_without_char_offsets(self):
        """When char offsets are None, produce a block-level key."""
        k = citation_key(ARTIFACT_ID, BLOCK_ID)
        assert k is not None
        assert len(k) == 12

    def test_no_block_id_returns_none(self):
        """NO evidence => NO fake citation key."""
        assert citation_key(ARTIFACT_ID, None) is None
        assert citation_key(ARTIFACT_ID, "") is None

    def test_no_artifact_still_generates_key_with_block(self):
        """Key can be generated from block_id alone (artifact optional)."""
        k = citation_key(None, BLOCK_ID)
        assert k is not None
        assert len(k) == 12


class TestCitation:
    def test_create_citation_with_key(self):
        c = Citation(
            key="abc123def456",
            statement="二叉树每个节点最多有两个子节点",
            evidence_ref=BLOCK_ID,
            page_or_slide=3,
            confidence=0.95,
        )
        assert c.key == "abc123def456"
        assert c.statement == "二叉树每个节点最多有两个子节点"
        assert c.evidence_ref == BLOCK_ID
        assert c.page_or_slide == 3
        assert c.confidence == 0.95

    def test_citation_no_evidence(self):
        """No-evidence citation has key=None and no evidence_ref."""
        c = Citation(
            key=None,
            statement="I don't know the answer",
        )
        assert c.key is None
        assert c.evidence_ref is None

    def test_citation_frozen(self):
        c = Citation(key="k1", statement="test")
        with pytest.raises(Exception):
            c.key = "other"  # type: ignore[misc]

    def test_citation_with_metadata(self):
        c = Citation(
            key="k1",
            statement="test",
            metadata={"rank": 1, "source": "bm25"},
        )
        assert c.metadata["rank"] == 1


class TestCitationValidationResult:
    def test_verified(self):
        result = CitationValidationResult(
            status=CitationStatus.VERIFIED,
            abstain=False,
            verified_count=3,
            total_count=3,
        )
        assert result.status == CitationStatus.VERIFIED
        assert result.abstain is False
        assert result.verified_count == 3
        assert result.total_count == 3

    def test_no_evidence_abstain(self):
        """No evidence => abstain=True."""
        result = CitationValidationResult(
            status=CitationStatus.NO_EVIDENCE,
            abstain=True,
            abstain_reason="No evidence provided for any citation",
            total_count=2,
        )
        assert result.abstain is True
        assert result.abstain_reason is not None
        assert result.verified_count == 0

    def test_stale_citation(self):
        result = CitationValidationResult(
            status=CitationStatus.STALE,
            abstain=True,
            abstain_reason="Referenced evidence version is stale",
            total_count=1,
        )
        assert result.status == CitationStatus.STALE
        assert result.abstain is True

    def test_mismatch(self):
        result = CitationValidationResult(
            status=CitationStatus.MISMATCH,
            abstain=False,
            details=[
                {"citation_key": "k1", "expected": "text A", "actual": "text B"}
            ],
            total_count=1,
        )
        assert result.status == CitationStatus.MISMATCH
        assert len(result.details) == 1

    def test_frozen(self):
        result = CitationValidationResult(
            status=CitationStatus.VERIFIED,
            abstain=False,
            total_count=1,
        )
        with pytest.raises(Exception):
            result.status = CitationStatus.MISMATCH  # type: ignore[misc]
