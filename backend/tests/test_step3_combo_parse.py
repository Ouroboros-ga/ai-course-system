"""Step 3 - 统一课程建设九步实施计划：组合式解析接线测试。

覆盖关键不变式：
- DocumentBlock 写入溯源字段（material_version_id/source_kind/confidence/provider_version/page_or_slide）。
- pipeline 不再"第一个成功 provider 就 break"：PRIMARY 收集后仍执行 ENRICHMENT。
- 有 enrichment 时经 BlockReconciler 合并（原生优先，OCR 补充，去重）。
- OCR 服务不可用时 fail-closed 回退，不伪造输出。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §7 Step 3。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session as _Session, select

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_build_model import SourceMaterial, SourceMaterialVersion, MaterialStatus
from app.models.database import engine
from app.models.document_parse_model import DocumentBlock, DocumentParseRun
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.document_parse_service import document_parse_service


def _session_factory():
    return _Session(engine)


def _user(session, name):
    u = User(username=name, hashed_password=get_password_hash("pw"), role=UserRole.TEACHER, is_active=True)
    session.add(u); session.commit(); session.refresh(u); return u


def _course(session, teacher_id):
    c = Course(
        fanya_course_id=f"s3-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="S3 Course", title="S3 Course",
        teacher_id=teacher_id, status=CourseStatus.DRAFT,
    )
    session.add(c); session.commit(); session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    return c


def _material(session, course_id, teacher_id):
    m = SourceMaterial(course_id=course_id, name="t.pptx", created_by=teacher_id)
    session.add(m); session.commit(); session.refresh(m)
    v = SourceMaterialVersion(
        material_id=m.material_id, course_id=course_id, version=1,
        file_path="course-source/test/source.pptx", file_hash="h", file_size=10,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        parse_status=MaterialStatus.PARSING, created_by=teacher_id,
    )
    session.add(v); session.commit(); session.refresh(v)
    run = document_parse_service.create_run(
        session, course_id=course_id, material_id=m.material_id,
        material_version_id=v.version_id, document_id=None, initiated_by=teacher_id,
    )
    return m, v, run


# ---------------------------------------------------------------------------
# 1. add_block 写入溯源字段
# ---------------------------------------------------------------------------


def test_add_block_writes_provenance_fields(session):
    """add_block 把 material_version_id/source_kind/confidence/provider_version 持久化。"""
    user = _user(session, "s3_prov_user")
    course = _course(session, user.id)
    _, _, run = _material(session, course.id, user.id)

    document_parse_service.add_block(
        session, course_id=course.id, run_id=run.run_id, document_id=None,
        page_number=2, block_type="text", text="原生文本块",
        material_version_id="smv_test", page_or_slide=2,
        source_kind="native", confidence=1.0, provider_version="native-pptx=1.0",
    )
    document_parse_service.add_block(
        session, course_id=course.id, run_id=run.run_id, document_id=None,
        page_number=3, block_type="text", text="OCR 文本块",
        material_version_id="smv_test", page_or_slide=3,
        source_kind="ocr", confidence=0.87, provider_version="paddleocr-service=2.7",
    )
    session.commit()

    sf = _session_factory()
    with sf as s:
        blocks = s.exec(
            select(DocumentBlock).where(DocumentBlock.run_id == run.run_id)
            .order_by(DocumentBlock.page_number)
        ).all()
        assert len(blocks) == 2
        native = blocks[0]
        assert native.source_kind == "native"
        assert native.confidence == 1.0
        assert native.material_version_id == "smv_test"
        assert native.page_or_slide == 2
        assert "native-pptx" in native.provider_version
        ocr = blocks[1]
        assert ocr.source_kind == "ocr"
        assert ocr.confidence == pytest.approx(0.87)
        assert "paddleocr" in ocr.provider_version


# ---------------------------------------------------------------------------
# 2. planner 为 DOCX 规划 python-docx PRIMARY + paddleocr ENRICHMENT
# ---------------------------------------------------------------------------


def test_planner_docx_emits_primary_and_enrichment():
    """_plan_docx 不再为空：python-docx PRIMARY + OCR ENRICHMENT。"""
    from app.platform.document_intelligence.planner import ParsePlanner, ParsePriority
    from app.platform.document_intelligence.probe import ProbeResult, DetectedFormat

    planner = ParsePlanner()
    planner.set_available_providers(["python-docx", "paddleocr", "tesseract-ocr"])
    probe = ProbeResult(detected_format=DetectedFormat.DOCX, image_only_pages=(1, 2))
    plan = planner.plan(probe, "art_docx")
    priorities = {s.provider_name: s.priority for s in plan.steps}
    assert "python-docx" in priorities
    assert priorities["python-docx"] == ParsePriority.PRIMARY
    assert "paddleocr" in priorities
    assert priorities["paddleocr"] == ParsePriority.ENRICHMENT


# ---------------------------------------------------------------------------
# 3. BlockReconciler 合并：原生优先，OCR 补充，去重
# ---------------------------------------------------------------------------


def test_reconcile_blocks_keeps_native_and_adds_ocr():
    """_reconcile_blocks：原生块保留，OCR 新块补充；不丢失任何一方。"""
    from app.services.document_parse_pipeline import _reconcile_blocks

    primary = [
        {"block_id": "b1", "block_type": "paragraph", "text": "原生第一段",
         "page_or_slide": 1, "bbox": None, "order_index": 0},
        {"block_id": "b2", "block_type": "paragraph", "text": "原生第二段",
         "page_or_slide": 1, "bbox": None, "order_index": 1},
    ]
    enrichment = [
        {"block_id": "o1", "block_type": "paragraph", "text": "OCR 扫描补充",
         "page_or_slide": 2, "bbox": None, "order_index": 0},
    ]
    warnings: list[str] = []
    merged = _reconcile_blocks(primary, enrichment, "r1", "pr1", warnings)
    # 原生两块都在
    texts = [b["text"] for b in merged]
    assert "原生第一段" in texts
    assert "原生第二段" in texts
    # OCR 补充块也在（不同页，不应被去重）
    assert "OCR 扫描补充" in texts
    # 不应因 reconcile 丢失块
    assert len(merged) >= 2


def test_reconcile_blocks_empty_enrichment_returns_primary():
    """enrichment 为空时直接返回 primary（不调用 reconciler）。"""
    from app.services.document_parse_pipeline import _reconcile_blocks
    primary = [{"block_id": "b1", "text": "x", "page_or_slide": 1}]
    merged = _reconcile_blocks(primary, [], "r1", "pr1", [])
    assert merged is primary


def test_docx_rendition_alignment_preserves_native_locator(monkeypatch):
    """DOCX page coordinates are attached as rendition metadata, never native facts."""
    from app.services.document_parse_pipeline import _align_docx_native_to_rendition, _merge_docx_native_and_rendition
    from app.platform.document_intelligence.document_ir.models import Provenance
    from app.platform.document_intelligence.contracts import BoundingBox

    native = [{
        "block_id": "native", "text": "The course introduces binary search.",
        "page_or_slide": None, "style_hints": {"native_locator": "word/document.xml#/w:body/w:p[1]"},
        "provenance": Provenance("art", "run", "parser", "python-docx", "word/document.xml#/w:body/w:p[1]"),
    }]
    ocr = [{
        "block_id": "ocr", "text": "The course introduces binary search.", "page_or_slide": 4,
        "bbox": BoundingBox(0.1, 0.2, 0.8, 0.3),
        "provenance": Provenance("art", "run", "parser", "paddleocr-service", "rendition/pdf/4/blocks/0", page_or_slide=4),
    }]
    warnings = []

    matched = _align_docx_native_to_rendition(native, ocr, warnings)
    merged = _merge_docx_native_and_rendition(native, ocr, matched)

    assert native[0]["page_or_slide"] is None
    assert native[0]["style_hints"]["rendition_page"] == 4
    assert native[0]["style_hints"]["alignment_confidence"] == 1.0
    assert next(block for block in merged if block["block_id"] == "native")["style_hints"]["native_locator"].startswith("word/document.xml#")
    assert [block["block_id"] for block in merged] == ["native"]


def test_docx_rendition_alignment_keeps_unmatched_page_unknown():
    from app.services.document_parse_pipeline import _align_docx_native_to_rendition

    native = [{"text": "native course text", "style_hints": {}}]
    ocr = [{"text": "unrelated rendered content", "page_or_slide": 3}]
    warnings = []

    _align_docx_native_to_rendition(native, ocr, warnings)

    assert "rendition_page" not in native[0]["style_hints"]
    assert warnings == ["DOCX_RENDITION_ALIGNMENT_UNRESOLVED:1"]


def test_docx_merge_keeps_visually_new_ocr_blocks():
    from app.services.document_parse_pipeline import _merge_docx_native_and_rendition

    merged = _merge_docx_native_and_rendition(
        [{"block_id": "native"}],
        [{"block_id": "matched"}, {"block_id": "visual-only"}],
        {"matched"},
    )

    assert [block["block_id"] for block in merged] == ["native", "visual-only"]


# ---------------------------------------------------------------------------
# 4. OCR enrichment 经 DocumentOcrPort：服务不可用时回退，不伪造
# ---------------------------------------------------------------------------


def test_ocr_enrichment_via_port_returns_empty_when_unavailable(monkeypatch):
    """DocumentOcrPort 不可用时，_ocr_enrichment_via_port 返回空（不伪造），由调用方回退。"""
    import asyncio
    from app.services import document_parse_pipeline as pipe
    from app.platform.document_intelligence.ocr_port import UnavailableOcrPort
    from app.platform.document_intelligence.planner import ParseStep, ParsePriority
    import app.platform.document_intelligence.ocr_port as ocr_port_mod

    monkeypatch.setattr(ocr_port_mod, "get_ocr_port", lambda: UnavailableOcrPort())

    class FakeSource:
        artifact_id = "a1"
        uri = "course-source/test/source.pptx"
        mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

    step = ParseStep(provider_name="paddleocr", priority=ParsePriority.ENRICHMENT,
                     config={"pages": [1]})
    warnings: list[str] = []

    async def _go():
        return await pipe._ocr_enrichment_via_port(
            FakeSource(), None, step, warnings, "r1", "pr1",
        )
    blocks = asyncio.run(_go())
    assert blocks == []
    # 应有 warning 说明不可用
    assert any("unavailable" in w.lower() or "ocr" in w.lower() for w in warnings)


def test_office_ocr_renders_each_requested_page_before_recognition(monkeypatch):
    """Office bytes are rendered to page images; raw ZIP bytes never reach OCR."""
    from types import SimpleNamespace
    from app.platform.document_intelligence.ocr_port import OcrBlock, OcrPageResult, OcrResult
    from app.services import document_parse_pipeline as pipe
    import app.platform.document_intelligence.libreoffice_converter as converter_module

    class FakeConverter:
        def convert_to_pdf(self, source_path, *, output_dir):
            return SimpleNamespace(pdf_path=source_path + ".pdf")

        def render_pages(self, pdf_path, *, output_dir):
            pages = []
            for number in (1, 2):
                path = f"{output_dir}/page-{number}.png"
                with open(path, "wb") as handle:
                    handle.write(f"png-{number}".encode())
                pages.append(path)
            return pages

    class FakePort:
        def __init__(self):
            self.calls = []

        def ocr_image(self, image_bytes, *, page):
            self.calls.append((image_bytes, page))
            return OcrResult(
                pages=[OcrPageResult(page=page, blocks=[
                    OcrBlock(text=f"page {page}", bbox=[0, 0, 1, 1], confidence=0.9),
                ])],
                provider_version="fake-ocr", model_hash="test",
            )

    monkeypatch.setattr(converter_module, "libreoffice_converter", FakeConverter())
    port = FakePort()
    source = SimpleNamespace(
        artifact_id="art_test", filename="slides.pptx", uri="slides.pptx", data=b"zip-bytes",
    )
    blocks = pipe._ocr_office_pages_via_port(port, b"zip-bytes", source, [1, 2], [], "run", "parser")

    assert [page for _, page in port.calls] == [1, 2]
    assert [item["page_or_slide"] for item in blocks] == [1, 2]
    assert all(image_bytes != b"zip-bytes" for image_bytes, _ in port.calls)


def test_office_ocr_persists_course_scoped_page_render(session, monkeypatch):
    from types import SimpleNamespace
    from app.services import document_parse_pipeline as pipe
    import app.platform.document_intelligence.libreoffice_converter as converter_module
    from app.platform.document_intelligence.ocr_port import OcrBlock, OcrPageResult, OcrResult
    from app.models.document_parse_model import EvidenceRenderAsset

    user = _user(session, "s3_render_asset_user")
    course = _course(session, user.id)
    _, _, run = _material(session, course.id, user.id)

    class FakeConverter:
        def convert_to_pdf(self, source_path, *, output_dir):
            return SimpleNamespace(pdf_path=source_path + ".pdf")
        def render_pages(self, pdf_path, *, output_dir):
            path = f"{output_dir}/page-1.png"
            from PIL import Image
            Image.new("RGBA", (1, 1), "white").save(path, "PNG")
            return [path]
    class FakePort:
        def ocr_image(self, image_bytes, *, page):
            return OcrResult(pages=[OcrPageResult(page=page, blocks=[OcrBlock("render text", [0, 0, 1, 1], 1.0)])], provider_version="fake", model_hash="x")

    monkeypatch.setattr(converter_module, "libreoffice_converter", FakeConverter())
    warnings = []
    blocks = pipe._ocr_office_pages_via_port(
        FakePort(), b"office", SimpleNamespace(artifact_id="art", filename="s.pptx", uri="s.pptx"),
        [1], warnings, run.run_id, "parser", session=session, course_id=course.id, document_id="doc_render",
    )
    assert not warnings, warnings
    asset = session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course.id, EvidenceRenderAsset.document_id == "doc_render",
    )).one()
    assert blocks[0]["text"] == "render text"
    assert asset.page_number == 1
    assert asset.object_key.endswith("/page-1.png")
    assert asset.width == 1 and asset.height == 1


def test_pdf_rendered_ocr_persists_course_scoped_page_render(session):
    from types import SimpleNamespace
    from PIL import Image
    from io import BytesIO
    from app.platform.document_intelligence.ocr_port import OcrBlock, OcrPageResult, OcrResult
    from app.platform.document_intelligence.page_renderer import RenderedPage
    from app.models.document_parse_model import EvidenceRenderAsset
    from app.services import document_parse_pipeline as pipe

    user = _user(session, "s3_pdf_render_asset_user")
    course = _course(session, user.id)
    _, _, run = _material(session, course.id, user.id)
    buffer = BytesIO()
    Image.new("RGBA", (2, 3), "white").save(buffer, "PNG")

    class FakePort:
        def ocr_image(self, image_bytes, *, page):
            return OcrResult(
                pages=[OcrPageResult(page=page, blocks=[OcrBlock("pdf text", [0, 0, 1, 1], 1.0)])],
                provider_version="fake", model_hash="x",
            )

    blocks = pipe._ocr_rendered_pages(
        FakePort(), [RenderedPage(2, buffer.getvalue(), 2, 3, "pdfium:2:180")],
        SimpleNamespace(artifact_id="art"), run.run_id, "parser",
        session=session, course_id=course.id, document_id="doc_pdf_render", warnings=[],
    )

    asset = session.exec(select(EvidenceRenderAsset).where(
        EvidenceRenderAsset.course_id == course.id,
        EvidenceRenderAsset.run_id == run.run_id,
        EvidenceRenderAsset.page_number == 2,
    )).one()
    assert blocks[0]["text"] == "pdf text"
    assert asset.document_id == "doc_pdf_render"
    assert asset.width == 2 and asset.height == 3


def test_canonical_page_assets_sign_stored_render_only(session):
    from app.api.v1.endpoints.document_parse import _canonical_page_assets
    from app.models.document_parse_model import EvidenceAnchor, EvidenceRenderAsset

    user = _user(session, "s3_viewer_asset_user")
    course = _course(session, user.id)
    _, _, run = _material(session, course.id, user.id)
    session.add(EvidenceRenderAsset(
        course_id=course.id, run_id=run.run_id, document_id="doc_view", page_number=2,
        object_key="evidence-render/course/page-2.png", width=640, height=480,
        content_hash="render-hash",
    ))
    session.flush()
    anchors = [
        EvidenceAnchor(course_id=course.id, ir_version_id="ir", run_id="run", document_id="doc_view", block_id="b1", page_or_slide=2),
        EvidenceAnchor(course_id=course.id, ir_version_id="ir", run_id="run", document_id="doc_view", block_id="b2", page_or_slide=3),
    ]

    pages = _canonical_page_assets(session, course.id, run.run_id, anchors)

    assert pages[0]["page_or_slide"] == 2
    assert pages[0]["rendition_url"].endswith("/evidence-renders/" + session.exec(
        select(EvidenceRenderAsset.asset_id).where(EvidenceRenderAsset.run_id == run.run_id)
    ).one() + "/content")
    assert pages[0]["width"] == 640
    assert pages[1]["page_or_slide"] == 3
    assert pages[1]["rendition_url"] is None


def test_reparse_creation_does_not_stale_existing_evidence(session):
    """A failed replacement parse cannot invalidate a confirmed citation."""
    user = _user(session, "s3_reparse_user")
    course = _course(session, user.id)
    material, version, old_run = _material(session, course.id, user.id)
    document_parse_service.mark_succeeded(session, run_id=old_run.run_id, course_id=course.id)
    block = document_parse_service.add_block(
        session, course_id=course.id, run_id=old_run.run_id, document_id=None,
        page_number=1, block_type="text", text="confirmed source",
    )
    span = document_parse_service.add_evidence_span(
        session, course_id=course.id, run_id=old_run.run_id, block_id=block.block_id,
        document_id=None, page_number=1, text_snippet="confirmed source",
    )
    document_parse_service.confirm_evidence_span(
        session, course_id=course.id, span_id=span.span_id, confirmed_by=user.id,
    )
    session.commit()

    new_run = document_parse_service.create_run(
        session, course_id=course.id, material_id=material.material_id,
        material_version_id=version.version_id, document_id=None, initiated_by=user.id,
    )
    session.refresh(span)

    assert new_run.prev_run_id == old_run.run_id
    assert new_run.affected_evidence_count == 0
    assert span.status.value == "confirmed"


def test_canonical_projection_preserves_block_id_across_ir_versions(session):
    """Canonical source locators recur across reparses without ID rewrites."""
    from app.models.document_parse_model import EvidenceAnchor, EvidenceSpan
    from app.platform.document_intelligence.canonical.projector import DocumentIRProjector
    from app.platform.document_intelligence.document_ir.models import ContentBlock, DocumentIR, DocumentUnit, Provenance, QualityReport, UnitType
    from app.platform.document_intelligence.quality import QualityDecision, QualityVerdict
    from app.platform.document_intelligence.source_artifact import SourceArtifact

    user = _user(session, "s3_canonical_id_user")
    course = _course(session, user.id)
    material, version, first_run = _material(session, course.id, user.id)
    document_parse_service.mark_succeeded(session, run_id=first_run.run_id, course_id=course.id)
    second_run = document_parse_service.create_run(
        session, course_id=course.id, material_id=material.material_id,
        material_version_id=version.version_id, document_id=None, initiated_by=user.id,
    )
    source = SourceArtifact.from_bytes(b"test", filename="source.pdf", mime="application/pdf")
    decision = QualityDecision(verdict=QualityVerdict.PASS)

    def document(run_id):
        block = ContentBlock(
            block_id="blk_stable_source_locator", block_type="paragraph", text="stable evidence",
            page_or_slide=1, reading_order=0,
            provenance=(Provenance(
                artifact_id=source.artifact_id, run_id=run_id, parser_run_id="parser",
                provider="native", raw_locator="pages/1/blocks/0", page_or_slide=1,
            ),),
        )
        return DocumentIR(
            document_id="doc_stable", source_artifact=source, blocks=(block,),
            units=(DocumentUnit(unit_id="unit_1", unit_type=UnitType.PAGE, index=1, block_ids=(block.block_id,)),),
            quality=QualityReport(overall_score=1.0),
        )

    projector = DocumentIRProjector()
    first, _, _ = projector.persist_and_project(
        session, course_id=course.id, material_version_id=version.version_id,
        run_id=first_run.run_id, previous_run_id=None, document_ir=document(first_run.run_id),
        quality_decision=decision, provider_versions={"native": "1"}, parse_outcome="native_complete",
    )
    second, _, _ = projector.persist_and_project(
        session, course_id=course.id, material_version_id=version.version_id,
        run_id=second_run.run_id, previous_run_id=first_run.run_id, document_ir=document(second_run.run_id),
        quality_decision=decision, provider_versions={"native": "1"}, parse_outcome="native_complete",
    )
    session.commit()
    blocks = session.exec(select(DocumentBlock).where(
        DocumentBlock.block_id == "blk_stable_source_locator",
    )).all()
    assert {block.document_ir_version_id for block in blocks} == {first.ir_version_id, second.ir_version_id}
    assert all(block.block_id == "blk_stable_source_locator" for block in blocks)
    assert len(session.exec(select(EvidenceAnchor).where(EvidenceAnchor.block_id == "blk_stable_source_locator")).all()) == 2
    assert len(session.exec(select(EvidenceSpan).where(EvidenceSpan.block_id == "blk_stable_source_locator")).all()) == 2


def test_retrieval_snapshot_requires_explicit_reparse_adoption(session):
    """A replacement IR cannot alter formal retrieval before teacher adoption."""
    from app.models.document_parse_model import RetrievalIndexSnapshot
    from app.platform.document_intelligence.canonical.projector import DocumentIRProjector
    from app.platform.document_intelligence.document_ir.models import ContentBlock, DocumentIR, DocumentUnit, QualityReport, UnitType
    from app.platform.document_intelligence.quality import QualityDecision, QualityVerdict
    from app.platform.document_intelligence.source_artifact import SourceArtifact

    user = _user(session, "s3_snapshot_user")
    course = _course(session, user.id)
    material, version, first_run = _material(session, course.id, user.id)
    document_parse_service.mark_succeeded(session, run_id=first_run.run_id, course_id=course.id)
    second_run = document_parse_service.create_run(
        session, course_id=course.id, material_id=material.material_id,
        material_version_id=version.version_id, initiated_by=user.id,
    )
    source = SourceArtifact.from_bytes(b"snapshot", "source.pdf", "application/pdf")
    decision = QualityDecision(verdict=QualityVerdict.PASS)

    def document(run_id, text):
        block = ContentBlock(block_id="blk_snapshot", block_type="paragraph", text=text, page_or_slide=1)
        return DocumentIR(
            document_id="doc_snapshot", source_artifact=source, blocks=(block,),
            units=(DocumentUnit(unit_id=f"unit_{run_id}", unit_type=UnitType.PAGE, index=1, block_ids=(block.block_id,)),),
            quality=QualityReport(overall_score=1.0),
        )

    projector = DocumentIRProjector()
    first, _, _ = projector.persist_and_project(
        session, course_id=course.id, material_version_id=version.version_id,
        run_id=first_run.run_id, previous_run_id=None, document_ir=document(first_run.run_id, "first"),
        quality_decision=decision, provider_versions={"native": "1"}, parse_outcome="native_complete",
    )
    second, _, _ = projector.persist_and_project(
        session, course_id=course.id, material_version_id=version.version_id,
        run_id=second_run.run_id, previous_run_id=first_run.run_id, document_ir=document(second_run.run_id, "second"),
        quality_decision=decision, provider_versions={"native": "1"}, parse_outcome="native_complete",
    )
    first_run.document_ir_version_id = first.ir_version_id
    second_run.document_ir_version_id = second.ir_version_id
    session.add(first_run); session.add(second_run)
    document_parse_service.activate_initial_retrieval_snapshot(
        session, course_id=course.id, run_id=first_run.run_id,
    )
    document_parse_service.mark_succeeded(session, run_id=second_run.run_id, course_id=course.id)
    before = session.exec(select(RetrievalIndexSnapshot).where(
        RetrievalIndexSnapshot.course_id == course.id,
        RetrievalIndexSnapshot.status == "active",
    )).one()
    assert before.ir_version_id == first.ir_version_id

    document_parse_service.apply_reparse(session, course_id=course.id, run_id=second_run.run_id)
    after = session.exec(select(RetrievalIndexSnapshot).where(
        RetrievalIndexSnapshot.course_id == course.id,
        RetrievalIndexSnapshot.status == "active",
    )).one()
    assert after.ir_version_id == second.ir_version_id


def test_quality_review_marks_parse_run_partial_success(session):
    """Persisted manual-review quality is visible in the parse run lifecycle."""
    from app.models.document_parse_model import DocumentIRVersion, ParseRunStatus

    user = _user(session, "s3_quality_status_user")
    course = _course(session, user.id)
    _, _, run = _material(session, course.id, user.id)
    version = DocumentIRVersion(
        course_id=course.id, material_version_id=run.material_version_id, run_id=run.run_id,
        document_id="doc_quality", artifact_id="art_quality", parse_outcome="manual_review_required",
        needs_review=True,
    )
    session.add(version); session.flush()
    run.document_ir_version_id = version.ir_version_id
    session.add(run)

    completed = document_parse_service.mark_succeeded(
        session, run_id=run.run_id, course_id=course.id,
    )

    assert completed.status == ParseRunStatus.PARTIAL_SUCCESS
