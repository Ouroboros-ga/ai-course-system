"""Tests for the V1 compatibility adapter."""

import pytest

from app.platform.document_intelligence.contracts import CURRENT_SCHEMA_VERSION
from app.platform.document_intelligence.document_ir.v1_adapter import (
    V1Page,
    V1ParseResult,
    adapt_v1_to_document_ir,
)
from app.platform.document_intelligence.source_artifact import SourceArtifact


@pytest.fixture
def source() -> SourceArtifact:
    return SourceArtifact.from_bytes(
        b"mock content",
        "test.pdf",
        "application/pdf",
    )


class TestV1Adapter:
    def test_basic_mapping(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[
                V1Page(index=1, text="Page one content", label="Page 1"),
                V1Page(index=2, text="Page two content", label="Page 2"),
            ],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        assert doc.document_id != ""
        assert doc.schema_version == CURRENT_SCHEMA_VERSION.serialize()
        assert len(doc.units) == 2
        assert len(doc.blocks) == 2
        assert doc.source_artifact is not None
        assert doc.source_artifact.artifact_id == source.artifact_id

    def test_blocks_have_text(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="Hello world")],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        assert doc.blocks[0].text == "Hello world"
        assert doc.blocks[0].page_or_slide == 1

    def test_units_have_block_references(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="Content")],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        assert len(doc.units[0].block_ids) == 1
        assert doc.units[0].block_ids[0] == doc.blocks[0].block_id

    def test_empty_pages_produces_warnings(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(pages=[])
        doc = adapt_v1_to_document_ir(v1, source)
        assert len(doc.warnings) >= 1
        codes = {w.code for w in doc.warnings}
        assert "V1_ADAPTER_EMPTY_PAGES" in codes

    def test_missing_dimensions_produces_warnings(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="No dims", width=None, height=None)],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        codes = {w.code for w in doc.warnings}
        assert "V1_ADAPTER_MISSING_PAGE_DIMENSIONS" in codes

    def test_no_bounding_boxes_produced(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="x")],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        codes = {w.code for w in doc.warnings}
        assert "V1_ADAPTER_NO_BOUNDING_BOXES" in codes

    def test_no_provenance_produced(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="x")],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        codes = {w.code for w in doc.warnings}
        assert "V1_ADAPTER_NO_PROVENANCE" in codes

    def test_no_invented_bbox_or_confidence(self, source: SourceArtifact) -> None:
        """The adapter must not fabricate bounding boxes or confidence scores."""
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="x")],
        )
        doc = adapt_v1_to_document_ir(v1, source)
        for block in doc.blocks:
            assert block.bbox is None
            assert block.confidence is None

    def test_deterministic_output(self, source: SourceArtifact) -> None:
        v1 = V1ParseResult(
            pages=[V1Page(index=1, text="Stable")],
        )
        doc1 = adapt_v1_to_document_ir(v1, source)
        doc2 = adapt_v1_to_document_ir(v1, source)
        assert doc1.document_id == doc2.document_id
        assert doc1.blocks[0].block_id == doc2.blocks[0].block_id
        assert doc1.units[0].unit_id == doc2.units[0].unit_id
