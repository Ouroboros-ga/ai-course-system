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
