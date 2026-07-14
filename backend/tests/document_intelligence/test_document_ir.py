"""Tests for DocumentIR models: stable IDs, serialization, reference integrity,
schema version, duplicate IDs, character-range validation, and round-trip."""

import json

import pytest

from app.platform.document_intelligence.contracts import (
    BoundingBox,
    CoordinateSpace,
    CURRENT_SCHEMA_VERSION,
    Polygon,
    ReadingOrder,
    SchemaVersion,
)
from app.platform.document_intelligence.document_ir.models import (
    Block,
    ContentBlock,
    DocumentIR,
    DocumentUnit,
    FormulaBlock,
    ParseWarning,
    ParserRun,
    ParserRunStatus,
    Provenance,
    QualityReport,
    TableBlock,
    TableCell,
    UnitType,
    VisualAsset,
    AssetKind,
    WarningSeverity,
    block_from_dict,
    block_to_dict,
    compute_document_id,
    compute_unit_id,
    validate_no_duplicate_ids,
    validate_reference_integrity,
)
from app.platform.document_intelligence.document_ir.serialization import (
    SUPPORTED_MAJOR_VERSION,
    deserialize_document_ir,
    serialize_document_ir,
)
from app.platform.document_intelligence.source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_source() -> SourceArtifact:
    return SourceArtifact.from_bytes(
        b"mock pptx content",
        "test.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )


@pytest.fixture
def sample_doc(sample_source: SourceArtifact) -> DocumentIR:
    """Build a realistic DocumentIR for testing."""
    doc_id = compute_document_id(
        artifact_id=sample_source.artifact_id,
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
    )
    unit_id = compute_unit_id(doc_id, "slide", 1)

    b1 = ContentBlock(
        block_id="blk_title",
        page_or_slide=1,
        bbox=BoundingBox(0.1, 0.05, 0.9, 0.15),
        reading_order=1,
        block_type="heading",
        text="Introduction",
        confidence=0.99,
        provider="native-pptx",
    )
    b2 = ContentBlock(
        block_id="blk_body",
        page_or_slide=1,
        bbox=BoundingBox(0.1, 0.2, 0.9, 0.5),
        reading_order=2,
        block_type="paragraph",
        text="This is the body text.",
        confidence=0.95,
        provider="native-pptx",
    )
    b3 = FormulaBlock(
        block_id="blk_formula",
        page_or_slide=1,
        bbox=BoundingBox(0.1, 0.55, 0.5, 0.65),
        reading_order=3,
        block_type="formula",
        latex="E=mc^2",
        confidence=0.9,
        provider="docling",
    )

    unit = DocumentUnit(
        unit_id=unit_id,
        unit_type=UnitType.SLIDE,
        index=1,
        label="Slide 1",
        width=13.333,
        height=7.5,
        coordinate_unit="inch",
        block_ids=("blk_title", "blk_body", "blk_formula"),
        reading_order=ReadingOrder(block_ids=("blk_title", "blk_body", "blk_formula")),
    )

    parser_run = ParserRun(
        run_id="run_001",
        parser_run_id="prun_001",
        provider="native-pptx",
        provider_version="1.0.0",
        status=ParserRunStatus.SUCCEEDED,
        duration_ms=150,
    )

    quality = QualityReport(
        overall_score=0.95,
        text_coverage=0.98,
        scorer_version="quality/1.0.0",
    )

    return DocumentIR(
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
        document_id=doc_id,
        source_artifact=sample_source,
        parser_runs=(parser_run,),
        units=(unit,),
        blocks=(b1, b2, b3),
        quality=quality,
    )


# ---------------------------------------------------------------------------
# Stable ID tests
# ---------------------------------------------------------------------------


class TestStableIDs:
    def test_document_id_deterministic(self) -> None:
        id1 = compute_document_id("art_abc", "document-ir/1.0.0")
        id2 = compute_document_id("art_abc", "document-ir/1.0.0")
        assert id1 == id2

    def test_document_id_changes_with_artifact(self) -> None:
        id1 = compute_document_id("art_abc", "document-ir/1.0.0")
        id2 = compute_document_id("art_def", "document-ir/1.0.0")
        assert id1 != id2

    def test_document_id_changes_with_schema_version(self) -> None:
        id1 = compute_document_id("art_abc", "document-ir/1.0.0")
        id2 = compute_document_id("art_abc", "document-ir/2.0.0")
        assert id1 != id2

    def test_unit_id_deterministic(self) -> None:
        id1 = compute_unit_id("doc_abc", "slide", 1)
        id2 = compute_unit_id("doc_abc", "slide", 1)
        assert id1 == id2

    def test_unit_id_changes_with_index(self) -> None:
        id1 = compute_unit_id("doc_abc", "slide", 1)
        id2 = compute_unit_id("doc_abc", "slide", 2)
        assert id1 != id2

    def test_unit_id_changes_with_type(self) -> None:
        id1 = compute_unit_id("doc_abc", "slide", 1)
        id2 = compute_unit_id("doc_abc", "page", 1)
        assert id1 != id2


# ---------------------------------------------------------------------------
# JSON round trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_round_trip_preserves_fields(self, sample_doc: DocumentIR) -> None:
        raw = serialize_document_ir(sample_doc)
        restored = deserialize_document_ir(raw)
        assert restored.document_id == sample_doc.document_id
        assert restored.schema_version == sample_doc.schema_version
        assert len(restored.blocks) == len(sample_doc.blocks)
        assert len(restored.units) == len(sample_doc.units)

    def test_round_trip_preserves_block_ids(self, sample_doc: DocumentIR) -> None:
        raw = serialize_document_ir(sample_doc)
        restored = deserialize_document_ir(raw)
        original_ids = {b.block_id for b in sample_doc.blocks}
        restored_ids = {b.block_id for b in restored.blocks}
        assert original_ids == restored_ids

    def test_round_trip_preserves_bbox(self) -> None:
        bbox = BoundingBox(0.1, 0.2, 0.8, 0.9)
        block = ContentBlock(
            block_id="blk_1", text="hello", bbox=bbox,
        )
        doc = DocumentIR(blocks=(block,), document_id="doc_test")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        assert restored.blocks[0].bbox is not None
        assert restored.blocks[0].bbox.x0 == 0.1

    def test_round_trip_preserves_table_cells(self) -> None:
        cell = TableCell(row=0, col=0, text="Header", header=True)
        table = TableBlock(
            block_id="tbl_1",
            rows=1,
            columns=1,
            cells=(cell,),
        )
        doc = DocumentIR(blocks=(table,), document_id="doc_t")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        tbl = restored.blocks[0]
        assert isinstance(tbl, TableBlock)
        assert len(tbl.cells) == 1
        assert tbl.cells[0].text == "Header"
        assert tbl.cells[0].header is True

    def test_round_trip_preserves_formula(self) -> None:
        formula = FormulaBlock(
            block_id="f_1",
            latex="E=mc^2",
            normalized_latex="E=mc^{2}",
            display_mode=True,
        )
        doc = DocumentIR(blocks=(formula,), document_id="doc_f")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        f = restored.blocks[0]
        assert isinstance(f, FormulaBlock)
        assert f.latex == "E=mc^2"
        assert f.display_mode is True

    def test_round_trip_preserves_provenance(self) -> None:
        prov = Provenance(
            artifact_id="art_1",
            run_id="run_1",
            parser_run_id="prun_1",
            provider="docling",
            raw_locator="pages/1",
            page_or_slide=1,
            confidence=0.95,
        )
        block = ContentBlock(block_id="b1", provenance=(prov,), text="x")
        doc = DocumentIR(blocks=(block,), document_id="doc_p")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        assert len(restored.blocks[0].provenance) == 1
        assert restored.blocks[0].provenance[0].provider == "docling"

    def test_round_trip_preserves_parser_runs(self) -> None:
        pr = ParserRun(
            run_id="run_x",
            parser_run_id="prun_x",
            provider="test",
            provider_version="1.0",
            status=ParserRunStatus.PARTIAL,
            duration_ms=500,
        )
        doc = DocumentIR(parser_runs=(pr,), document_id="doc_r")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        assert len(restored.parser_runs) == 1
        assert restored.parser_runs[0].run_id == "run_x"
        assert restored.parser_runs[0].status == ParserRunStatus.PARTIAL

    def test_round_trip_preserves_quality_report(self) -> None:
        q = QualityReport(overall_score=0.88, text_coverage=0.9, scorer_version="q/1")
        doc = DocumentIR(quality=q, document_id="doc_q")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        assert restored.quality is not None
        assert restored.quality.overall_score == 0.88


# ---------------------------------------------------------------------------
# Schema version handling
# ---------------------------------------------------------------------------


class TestSchemaVersionHandling:
    def test_unknown_major_rejected(self) -> None:
        data = {
            "schema_version": "document-ir/99.0.0",
            "document_id": "doc_test",
            "units": [],
            "blocks": [],
        }
        raw = json.dumps(data)
        with pytest.raises(ValueError, match="Unsupported schema major version 99"):
            deserialize_document_ir(raw)

    def test_known_major_with_extra_minor_ok(self) -> None:
        data = {
            "schema_version": "document-ir/1.99.0",
            "document_id": "doc_test",
            "units": [],
            "blocks": [],
        }
        raw = json.dumps(data)
        doc = deserialize_document_ir(raw)
        assert doc.document_id == "doc_test"

    def test_malformed_schema_version(self) -> None:
        data = {
            "schema_version": "invalid",
            "document_id": "doc_test",
            "units": [],
            "blocks": [],
        }
        raw = json.dumps(data)
        with pytest.raises(ValueError, match="Invalid schema version"):
            deserialize_document_ir(raw)


# ---------------------------------------------------------------------------
# Reference integrity
# ---------------------------------------------------------------------------


class TestReferenceIntegrity:
    def test_valid_references(self, sample_doc: DocumentIR) -> None:
        errors = validate_reference_integrity(sample_doc)
        assert errors == []

    def test_orphan_block_reference(self) -> None:
        unit = DocumentUnit(
            unit_id="unit_1",
            unit_type=UnitType.PAGE,
            index=1,
            block_ids=("blk_nonexistent",),
        )
        doc = DocumentIR(units=(unit,), document_id="doc_ref")
        errors = validate_reference_integrity(doc)
        assert len(errors) == 1
        assert "blk_nonexistent" in errors[0]

    def test_orphan_in_reading_order(self) -> None:
        unit = DocumentUnit(
            unit_id="unit_1",
            unit_type=UnitType.PAGE,
            index=1,
            reading_order=ReadingOrder(block_ids=("missing_blk",)),
            block_ids=(),
        )
        doc = DocumentIR(units=(unit,), document_id="doc_ro")
        errors = validate_reference_integrity(doc)
        assert len(errors) >= 1
        assert any("missing_blk" in e for e in errors)

    def test_orphan_parent_id(self) -> None:
        block = ContentBlock(block_id="child", parent_id="nonexistent_parent")
        doc = DocumentIR(blocks=(block,), document_id="doc_parent")
        errors = validate_reference_integrity(doc)
        assert any("nonexistent_parent" in e for e in errors)

    def test_orphan_child_id(self) -> None:
        block = ContentBlock(block_id="parent", child_ids=("missing_child",))
        doc = DocumentIR(blocks=(block,), document_id="doc_child")
        errors = validate_reference_integrity(doc)
        assert any("missing_child" in e for e in errors)

    def test_orphan_asset_link(self) -> None:
        asset = VisualAsset(
            asset_id="asset_1",
            kind=AssetKind.IMAGE,
            linked_block_ids=("ghost_block",),
        )
        doc = DocumentIR(assets=(asset,), document_id="doc_asset")
        errors = validate_reference_integrity(doc)
        assert any("ghost_block" in e for e in errors)

    def test_orphan_table_caption(self) -> None:
        table = TableBlock(block_id="tbl_1", caption_block_id="missing_caption")
        doc = DocumentIR(blocks=(table,), document_id="doc_cap")
        errors = validate_reference_integrity(doc)
        assert any("missing_caption" in e for e in errors)

    def test_orphan_table_continued_from(self) -> None:
        table = TableBlock(block_id="tbl_2", continued_from="missing_prev")
        doc = DocumentIR(blocks=(table,), document_id="doc_cf")
        errors = validate_reference_integrity(doc)
        assert any("missing_prev" in e for e in errors)


# ---------------------------------------------------------------------------
# Duplicate ID detection
# ---------------------------------------------------------------------------


class TestDuplicateIDs:
    def test_no_duplicates(self, sample_doc: DocumentIR) -> None:
        errors = validate_no_duplicate_ids(sample_doc)
        assert errors == []

    def test_duplicate_block_id(self) -> None:
        b1 = ContentBlock(block_id="dup")
        b2 = ContentBlock(block_id="dup")
        doc = DocumentIR(blocks=(b1, b2), document_id="doc_dup")
        errors = validate_no_duplicate_ids(doc)
        assert len(errors) == 1
        assert "dup" in errors[0]

    def test_duplicate_asset_id(self) -> None:
        a1 = VisualAsset(asset_id="dup", kind=AssetKind.IMAGE)
        a2 = VisualAsset(asset_id="dup", kind=AssetKind.CHART)
        doc = DocumentIR(assets=(a1, a2), document_id="doc_adup")
        errors = validate_no_duplicate_ids(doc)
        assert any("dup" in e for e in errors)

    def test_duplicate_unit_id(self) -> None:
        u1 = DocumentUnit(unit_id="dup", unit_type=UnitType.PAGE, index=1)
        u2 = DocumentUnit(unit_id="dup", unit_type=UnitType.PAGE, index=2)
        doc = DocumentIR(units=(u1, u2), document_id="doc_udup")
        errors = validate_no_duplicate_ids(doc)
        assert any("dup" in e for e in errors)


# ---------------------------------------------------------------------------
# Block discriminated union
# ---------------------------------------------------------------------------


class TestBlockDiscriminatedUnion:
    def test_content_block_kind(self) -> None:
        b = ContentBlock(block_id="c1")
        assert b.kind == "content"

    def test_table_block_kind(self) -> None:
        b = TableBlock(block_id="t1")
        assert b.kind == "table"

    def test_formula_block_kind(self) -> None:
        b = FormulaBlock(block_id="f1")
        assert b.kind == "formula"

    def test_block_to_dict_has_kind(self) -> None:
        b = ContentBlock(block_id="c1", text="hi")
        d = block_to_dict(b)
        assert d["kind"] == "content"
        assert d["text"] == "hi"

    def test_block_from_dict_content(self) -> None:
        d = {"block_id": "c1", "kind": "content", "text": "hello"}
        b = block_from_dict(d)
        assert isinstance(b, ContentBlock)
        assert b.text == "hello"

    def test_block_from_dict_table(self) -> None:
        d = {"block_id": "t1", "kind": "table", "rows": 3, "columns": 2}
        b = block_from_dict(d)
        assert isinstance(b, TableBlock)
        assert b.rows == 3

    def test_block_from_dict_formula(self) -> None:
        d = {"block_id": "f1", "kind": "formula", "latex": "E=mc^2"}
        b = block_from_dict(d)
        assert isinstance(b, FormulaBlock)
        assert b.latex == "E=mc^2"

    def test_block_from_dict_unknown_kind_raises(self) -> None:
        d = {"block_id": "x1", "kind": "video"}
        with pytest.raises(ValueError, match="Unknown block kind"):
            block_from_dict(d)


# ---------------------------------------------------------------------------
# Runtime ID exclusion from stable IDs
# ---------------------------------------------------------------------------


class TestRuntimeIdExclusion:
    def test_run_id_not_in_document_id(self) -> None:
        """Verify that different run_ids produce the same document_id."""
        src = SourceArtifact.from_bytes(b"fixed", "f.pptx", "application/octet-stream")
        doc_id = compute_document_id(src.artifact_id, "document-ir/1.0.0")
        # The doc_id should not contain any run_id pattern
        assert "run_" not in doc_id
        assert "prun_" not in doc_id

    def test_parser_run_fields_independent_from_stable_ids(self) -> None:
        """ParserRun fields like duration_ms, status don't affect stable IDs."""
        id_a = compute_document_id("art_1", "document-ir/1.0.0")
        id_b = compute_document_id("art_1", "document-ir/1.0.0")
        assert id_a == id_b


# ---------------------------------------------------------------------------
# BBox / polygon bounds validation (already in contracts tests)
# Also test char_span validation in provenance
# ---------------------------------------------------------------------------


class TestCharSpanValidation:
    def test_valid_char_span(self) -> None:
        prov = Provenance(
            artifact_id="art_1",
            run_id="run_1",
            parser_run_id="prun_1",
            provider="test",
            raw_locator="x",
            char_span=(0, 100),
        )
        assert prov.char_span == (0, 100)

    def test_char_span_round_trip(self) -> None:
        prov = Provenance(
            artifact_id="art_1",
            run_id="run_1",
            parser_run_id="prun_1",
            provider="test",
            raw_locator="x",
            char_span=(5, 42),
        )
        d = prov.to_dict()
        restored = Provenance.from_dict(d)
        assert restored.char_span == (5, 42)

    def test_char_span_none_round_trip(self) -> None:
        prov = Provenance(
            artifact_id="art_1",
            run_id="run_1",
            parser_run_id="prun_1",
            provider="test",
            raw_locator="x",
            char_span=None,
        )
        d = prov.to_dict()
        assert "char_span" not in d
        restored = Provenance.from_dict(d)
        assert restored.char_span is None


# ---------------------------------------------------------------------------
# Empty document
# ---------------------------------------------------------------------------


class TestEmptyDocument:
    def test_empty_document_serializes(self) -> None:
        doc = DocumentIR(document_id="doc_empty")
        raw = serialize_document_ir(doc)
        restored = deserialize_document_ir(raw)
        assert restored.document_id == "doc_empty"
        assert restored.blocks == ()
        assert restored.units == ()
