from app.platform.document_intelligence.canonical.assembler import CanonicalDocumentIRAssembler
from app.platform.document_intelligence.contracts import BoundingBox
from app.platform.document_intelligence.source_artifact import SourceArtifact


def test_assembler_normalizes_object_bbox_and_pipeline_warning():
    source = SourceArtifact.from_bytes(b"fixture", filename="fixture.pdf", mime="application/pdf")

    document_ir = CanonicalDocumentIRAssembler().assemble(
        source=source,
        run_id="run-1",
        parser_run_id="parser-1",
        blocks=[{
            "block_id": "block-1",
            "block_type": "paragraph",
            "text": "Visible text",
            "page_or_slide": 1,
            "bbox": BoundingBox(0.1, 0.2, 0.8, 0.3),
        }],
        units=[],
        assets=[],
        warnings=["native parser emitted a recoverable warning"],
        provider_versions={"fixture-provider": "1.0"},
    )

    assert document_ir.blocks[0].bbox == BoundingBox(0.1, 0.2, 0.8, 0.3)
    assert document_ir.warnings[0].severity.value == "warning"
