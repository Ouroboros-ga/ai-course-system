"""PPT 映射优化服务回归测试。

覆盖 5 个修复点：
1. _apply_suggestions 支持创建新映射（教师新增节点）
2. nodes_payload 补全讲稿 content、父级标题、source_block_refs
3. 建议格式改为 page_refs: list[int] 支持不连续页码
4. prompt 允许一页映射多个知识点
5. 首次映射 source_block_refs 作为优化参考输入
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import select

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    CoursePptMapping,
    OutlineLifecycleStatus,
    OutlineNodeType,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.document_parse_model import DocumentBlock
from app.models.media_release_model import MediaRelease
from app.models.user_model import User, UserRole
from app.platform.document_intelligence.ocr_port import OcrBlock, OcrPageResult, OcrResult
from app.services.course_access_service import establish_course_access_baseline
from app.services.ppt_mapping_optimization_service import (
    PptMappingOptimizationService,
    PptMappingSuggestion,
)


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content
        self.model = "fake"
        self.latency_ms = 10.0
        self.usage = {}


class _FakeLLMClient:
    """记录收到的 payload 并返回预设的 suggestions。"""

    def __init__(self, response_content: str):
        self._response = response_content
        self.received_payload: dict | None = None

    async def chat(self, messages, **kwargs):
        # 解析 user message 中的 payload
        user_msg = messages[1].content
        self.received_payload = json.loads(user_msg)
        return _FakeLLMResponse(content=self._response)


def test_ppt_mapping_adapter_disables_reasoning_and_bounds_json_output():
    from app.core.config import settings
    from app.platform.agents.prep.llm_adapter import PrepLLMAdapter

    captured = {}

    class FakePort:
        async def complete(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content='{"suggestions": []}')

    adapter = PrepLLMAdapter(structured_llm=FakePort())

    async def run():
        return await adapter.optimize_ppt_mappings([], [], [])

    asyncio.run(run())
    assert captured["options"].max_tokens == settings.PREP_PPT_MAPPING_MAX_TOKENS
    assert captured["options"].provider_options == {"thinking": {"type": "disabled"}}


def test_salvage_suggestions_recovers_truncated_json():
    """截断的 LLM JSON 不应整批丢弃：应恢复已完整输出的建议对象。"""
    from app.services.ppt_mapping_optimization_service import salvage_suggestions

    truncated = (
        '{"suggestions": [{"outline_node_id": "kp_1", "page_refs": [1,2],'
        '"confidence": 0.9, "reason": "标题匹配"}, {"outline_node_id": "kp_2",'
    )
    items = salvage_suggestions(truncated)
    assert [item["outline_node_id"] for item in items] == ["kp_1"]


def test_salvage_suggestions_passes_through_valid_envelope():
    """合法 JSON envelope 原样返回。"""
    from app.services.ppt_mapping_optimization_service import salvage_suggestions

    items = salvage_suggestions(
        '{"suggestions": [{"outline_node_id": "a", "page_refs": [1]}]}'
    )
    assert items == [{"outline_node_id": "a", "page_refs": [1]}]


def test_ppt_mapping_adapter_salvages_truncated_llm_json():
    """适配器收到截断响应时返回已完成的建议，而不是空列表。"""
    from app.platform.agents.prep.llm_adapter import PrepLLMAdapter

    truncated = (
        '{"suggestions": [{"outline_node_id": "kp_1", "page_refs": [1,2],'
        '"confidence": 0.9, "reason": "标题匹配"}, {"outline_node_id": "kp_2",'
    )

    class FakePort:
        async def complete(self, **kwargs):
            return SimpleNamespace(content=truncated)

    adapter = PrepLLMAdapter(structured_llm=FakePort())
    result = asyncio.run(adapter.optimize_ppt_mappings([], [], []))
    assert [item["outline_node_id"] for item in result] == ["kp_1"]


def _setup_course_with_outline_and_ppt(
    session,
    *,
    with_existing_mapping: bool = True,
    with_ocr_blocks: bool = True,
):
    """创建课程 + 大纲 + 讲稿 + OCR blocks + (可选)已有映射。"""
    token = uuid4().hex[:10]
    teacher = User(
        username=f"ppt_opt_{token}",
        hashed_password=get_password_hash("pw"),
        role=UserRole.TEACHER,
    )
    session.add(teacher)
    session.commit()
    session.refresh(teacher)
    course = Course(
        fanya_course_id=f"ppt-opt-{token}",
        fanya_course_name="PPT opt test",
        title="PPT opt test",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)

    # 大纲版本
    outline_version = CourseOutlineVersion(
        course_id=course.id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(outline_version)
    session.flush()

    # 章节结构: chapter -> section -> knowledge_point(已有) + knowledge_point(新增)
    chapter = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline_version.outline_version_id,
        node_type=OutlineNodeType.CHAPTER,
        title="第二章 活塞销",
        order_index=0,
    )
    session.add(chapter)
    session.flush()
    section = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline_version.outline_version_id,
        node_type=OutlineNodeType.SECTION,
        title="2.1 活塞销结构",
        parent_node_id=chapter.outline_node_id,
        order_index=0,
    )
    session.add(section)
    session.flush()
    # 已有映射的知识点
    existing_kp = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline_version.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="活塞销内孔形状",
        parent_node_id=section.outline_node_id,
        order_index=0,
        source_block_refs=["block_001", "block_002"],
    )
    session.add(existing_kp)
    session.flush()
    # 教师新增的知识点（无已有映射）
    new_kp = CourseOutlineNode(
        course_id=course.id,
        outline_version_id=outline_version.outline_version_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title="活塞销材料选择",
        parent_node_id=section.outline_node_id,
        order_index=1,
        source_block_refs=[],
    )
    session.add(new_kp)
    session.flush()

    # 讲稿版本
    script_version = TeachingScriptVersion(
        course_id=course.id,
        outline_version_id=outline_version.outline_version_id,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=teacher.id,
    )
    session.add(script_version)
    session.flush()
    # 只为 existing_kp 创建讲稿
    script_node = TeachingScriptNode(
        course_id=course.id,
        script_version_id=script_version.script_version_id,
        outline_node_id=existing_kp.outline_node_id,
        content="活塞销内孔形状有圆柱形孔、锥形扩展、中间封闭式等多种形式。",
        style="academic",
    )
    session.add(script_node)

    # OCR blocks（PPT 每页文本）
    material_version_id = f"mv_{token}"
    run_id = f"run_{token}"
    if with_ocr_blocks:
        for i, text in enumerate([
            "活塞销内孔形状：圆柱形孔、锥形扩展",
            "中间封闭式、单侧封闭式",
            "活塞销材料：20Cr 钢渗碳",
        ], start=1):
            block = DocumentBlock(
                course_id=course.id,
                material_version_id=material_version_id,
                run_id=run_id,
                block_id=f"block_{i:03d}",
                block_type="TEXT",
                page_or_slide=i,
                text=text,
            )
            session.add(block)

    # 已有映射（仅 existing_kp，且未锁定）
    if with_existing_mapping:
        existing_mapping = CoursePptMapping(
            course_id=course.id,
            outline_node_id=existing_kp.outline_node_id,
            material_version_id=material_version_id,
            page_start=1,
            page_end=2,
            page_refs=[1, 2],
            confidence=0.7,
            status="draft",
            teacher_locked=False,
            source_block_refs=["block_001", "block_002"],
        )
        session.add(existing_mapping)

    session.commit()
    return teacher, course, outline_version, existing_kp, new_kp, material_version_id


def test_apply_suggestions_creates_new_mapping_for_teacher_added_node(session, monkeypatch):
    """修复1: _apply_suggestions 为没有已有映射的节点创建新映射。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))

    teacher, course, outline_ver, existing_kp, new_kp, mv_id = _setup_course_with_outline_and_ppt(
        session, with_existing_mapping=True,
    )

    # LLM 返回两条建议：更新 existing_kp + 为 new_kp 创建新映射
    llm_response = json.dumps({
        "suggestions": [
            {
                "outline_node_id": existing_kp.outline_node_id,
                "page_refs": [1, 2],
                "confidence": 0.9,
                "reason": "OCR 匹配内孔形状",
            },
            {
                "outline_node_id": new_kp.outline_node_id,
                "page_refs": [3],
                "confidence": 0.85,
                "reason": "OCR 匹配材料选择",
            },
        ]
    })
    fake_client = _FakeLLMClient(llm_response)
    service = PptMappingOptimizationService(client=fake_client)

    summary = asyncio.run(service.optimize_mappings(
        session, course_id=course.id, material_version_id=mv_id,
    ))

    # 应该有 2 条被 touched（1 更新 + 1 新建）
    assert summary.updated_count == 2
    # 验证 new_kp 的映射确实被创建了
    from sqlmodel import select
    new_mapping = session.exec(
        select(CoursePptMapping).where(
            CoursePptMapping.outline_node_id == new_kp.outline_node_id,
            CoursePptMapping.material_version_id == mv_id,
        )
    ).first()
    assert new_mapping is not None
    assert new_mapping.page_refs == [3]
    assert new_mapping.status == "draft"


def test_manifest_pages_are_ocr_matched_when_document_blocks_are_pending(session, monkeypatch):
    """A usable ppt-manifest/v1 must not be rejected by parse_status alone."""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    teacher, course, _outline_ver, existing_kp, _new_kp, material_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
        with_ocr_blocks=False,
    )

    manifest_key = f"ppt-manifest/course{course.id}/test/manifest.json"
    page_key = f"ppt-manifest/course{course.id}/test/page-1.png"
    session.add(MediaRelease(
        course_id=course.id,
        created_by=teacher.id,
        ppt_manifest_object_key=manifest_key,
    ))
    session.commit()

    class FakeStorage:
        def get(self, object_key):
            payloads = {
                manifest_key: json.dumps({
                    "schema": "ppt-manifest/v1",
                    "pages": [{"page": 1, "image_object_key": page_key}],
                }).encode("utf-8"),
                page_key: b"rendered-ppt-page",
            }
            return payloads[object_key]

    class FakeOcrPort:
        is_available = True

        def ocr_image(self, image_bytes, *, lang="ch", page=1):
            assert image_bytes == b"rendered-ppt-page"
            assert lang == "ch"
            return OcrResult(
                pages=[OcrPageResult(
                    page=page,
                    blocks=[OcrBlock("活塞销内孔形状与封闭式结构", [0, 0, 1, 1], 0.98)],
                )],
                provider_version="fake-ocr",
                model_hash="fake-model",
            )

    fake_client = _FakeLLMClient(json.dumps({"suggestions": [{
        "outline_node_id": existing_kp.outline_node_id,
        "page_refs": [1],
        "confidence": 0.91,
        "reason": "manifest OCR 语义匹配",
    }]}))
    service = PptMappingOptimizationService(
        client=fake_client,
        storage=FakeStorage(),
        ocr_port=FakeOcrPort(),
    )

    summary = asyncio.run(service.optimize_mappings(
        session,
        course_id=course.id,
        material_version_id=material_version_id,
    ))

    assert summary.updated_count == 1
    assert fake_client.received_payload["blocks"] == [{
        "page": 1,
        "text": "活塞销内孔形状与封闭式结构",
        "source_kind": "ppt_manifest_ocr",
    }]


def test_nodes_payload_includes_script_content_parent_title_and_block_refs(session, monkeypatch):
    """修复2+5: nodes_payload 补全讲稿content、父级标题、source_block_refs。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))

    teacher, course, outline_ver, existing_kp, new_kp, mv_id = _setup_course_with_outline_and_ppt(
        session, with_existing_mapping=True,
    )

    llm_response = json.dumps({"suggestions": []})
    fake_client = _FakeLLMClient(llm_response)
    service = PptMappingOptimizationService(client=fake_client)

    asyncio.run(service.optimize_mappings(
        session, course_id=course.id, material_version_id=mv_id,
    ))

    payload = fake_client.received_payload
    assert payload is not None
    assert "nodes" in payload

    # 找到 existing_kp 的 node payload
    existing_node_payload = next(
        n for n in payload["nodes"] if n["outline_node_id"] == existing_kp.outline_node_id
    )
    # 验证 script_content 已传入
    assert "script_content" in existing_node_payload
    assert "活塞销内孔形状" in existing_node_payload["script_content"]
    # 验证 parent_title 已传入（应包含 section 标题）
    assert "parent_title" in existing_node_payload
    assert "活塞销结构" in existing_node_payload["parent_title"]
    # 验证 source_block_refs 已传入
    assert "source_block_refs" in existing_node_payload
    assert "block_001" in existing_node_payload["source_block_refs"]


def test_page_refs_supports_non_consecutive_pages(session, monkeypatch):
    """修复3: page_refs 支持不连续页码 [1,3]。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))

    teacher, course, outline_ver, existing_kp, new_kp, mv_id = _setup_course_with_outline_and_ppt(
        session, with_existing_mapping=True,
    )

    # LLM 返回不连续页码 [1, 3]
    llm_response = json.dumps({
        "suggestions": [
            {
                "outline_node_id": existing_kp.outline_node_id,
                "page_refs": [1, 3],
                "confidence": 0.8,
                "reason": "不连续页码匹配",
            },
        ]
    })
    fake_client = _FakeLLMClient(llm_response)
    service = PptMappingOptimizationService(client=fake_client)

    summary = asyncio.run(service.optimize_mappings(
        session, course_id=course.id, material_version_id=mv_id,
    ))

    from sqlmodel import select
    mapping = session.exec(
        select(CoursePptMapping).where(
            CoursePptMapping.outline_node_id == existing_kp.outline_node_id,
        )
    ).first()
    assert mapping.page_refs == [1, 3]
    # page_start/page_end 应从 page_refs 派生
    assert mapping.page_start == 1
    assert mapping.page_end == 3


def test_parse_suggestions_accepts_legacy_page_start_end_format():
    """修复3 兼容性: _parse_suggestions 兼容旧版 page_start/page_end 格式。"""
    legacy_raw = [
        {"outline_node_id": "on_test", "page_start": 2, "page_end": 5, "confidence": 0.7},
    ]
    result = PptMappingOptimizationService._parse_suggestions(legacy_raw)
    assert len(result) == 1
    assert result[0].page_refs == [2, 3, 4, 5]


def test_scoped_matching_limits_llm_to_selected_node_and_pages(session, monkeypatch):
    """Workbench actions must not resend every page/node to the model."""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, _existing_kp, new_kp, material_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    fake_client = _FakeLLMClient(json.dumps({"suggestions": [{
        "outline_node_id": new_kp.outline_node_id,
        "page_refs": [3],
        "confidence": 0.88,
        "reason": "selected slide matches the selected knowledge point",
    }]}))
    summary = asyncio.run(PptMappingOptimizationService(client=fake_client).optimize_mappings(
        session,
        course_id=course.id,
        material_version_id=material_version_id,
        outline_node_ids=[new_kp.outline_node_id],
        page_refs_by_material={material_version_id: [3]},
        seed_from_evidence=False,
    ))

    assert summary.updated_count == 1
    assert [item["page"] for item in fake_client.received_payload["blocks"]] == [3]
    assert [item["outline_node_id"] for item in fake_client.received_payload["nodes"]] == [new_kp.outline_node_id]
    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.outline_node_id == new_kp.outline_node_id,
        CoursePptMapping.material_version_id == material_version_id,
    )).one()
    assert mapping.page_refs == [3]


def test_existing_mapping_source_block_refs_passed_to_llm(session, monkeypatch):
    """修复5: 已有映射的 source_block_refs 作为优化参考输入传给 LLM。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))

    teacher, course, outline_ver, existing_kp, new_kp, mv_id = _setup_course_with_outline_and_ppt(
        session, with_existing_mapping=True,
    )

    llm_response = json.dumps({"suggestions": []})
    fake_client = _FakeLLMClient(llm_response)
    service = PptMappingOptimizationService(client=fake_client)

    asyncio.run(service.optimize_mappings(
        session, course_id=course.id, material_version_id=mv_id,
    ))

    payload = fake_client.received_payload
    assert "mappings" in payload
    existing_mapping_payload = payload["mappings"][0]
    # 验证已有映射的 source_block_refs 已传入
    assert "source_block_refs" in existing_mapping_payload
    assert "block_001" in existing_mapping_payload["source_block_refs"]
    # 验证 page_refs 已传入（而非 page_start/page_end）
    assert "page_refs" in existing_mapping_payload


def test_multiple_ppt_versions_are_optimized_independently(session, monkeypatch):
    """Page 1 in two decks produces two mappings with distinct provenance."""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, existing_kp, new_kp, first_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    second_version_id = f"{first_version_id}_second"
    for page, text in enumerate(["第二份课件：活塞销内孔", "第二份课件：活塞销材料"], start=1):
        session.add(DocumentBlock(
            course_id=course.id,
            material_version_id=second_version_id,
            run_id=f"run_{second_version_id}",
            block_id=f"{second_version_id}_{page}",
            block_type="TEXT",
            page_or_slide=page,
            text=text,
        ))
    session.commit()

    fake_client = _FakeLLMClient(json.dumps({"suggestions": [
        {
            "outline_node_id": existing_kp.outline_node_id,
            "page_refs": [1],
            "confidence": 0.9,
            "reason": "PPT 页内标题匹配",
        },
        {
            "outline_node_id": new_kp.outline_node_id,
            "page_refs": [2],
            "confidence": 0.8,
            "reason": "PPT 页内正文匹配",
        },
    ]}))
    summary = asyncio.run(PptMappingOptimizationService(client=fake_client).optimize_mappings(
        session,
        course_id=course.id,
        material_version_ids=[first_version_id, second_version_id],
    ))

    assert summary.updated_count == 4
    assert summary.material_version_ids == [first_version_id, second_version_id]
    assert {item.material_version_id for item in summary.suggestions} == {
        first_version_id,
        second_version_id,
    }
    second_deck_mappings = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.material_version_id == second_version_id,
    )).all()
    assert {item.outline_node_id for item in second_deck_mappings} == {
        existing_kp.outline_node_id,
        new_kp.outline_node_id,
    }


def test_source_evidence_moves_legacy_mapping_to_its_actual_ppt_version(session, monkeypatch):
    """OCR provenance repairs rows previously written under the first deck."""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, existing_kp, _new_kp, first_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    second_version_id = f"{first_version_id}_second"
    session.add(DocumentBlock(
        course_id=course.id,
        material_version_id=second_version_id,
        run_id="run_second",
        block_id="block_second_deck",
        block_type="TEXT",
        page_or_slide=4,
        text="活塞销内孔形状",
    ))
    existing_kp.source_block_refs = ["block_second_deck"]
    legacy_mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.outline_node_id == existing_kp.outline_node_id,
        CoursePptMapping.material_version_id == first_version_id,
    )).one()
    legacy_mapping.source_block_refs = ["block_second_deck"]
    legacy_mapping.page_refs = [4]
    legacy_mapping.page_start = 4
    legacy_mapping.page_end = 4
    session.add(existing_kp)
    session.add(legacy_mapping)
    session.commit()

    service = PptMappingOptimizationService(client=_FakeLLMClient(json.dumps({"suggestions": []})))
    summary = asyncio.run(service.optimize_mappings(
        session,
        course_id=course.id,
        material_version_ids=[first_version_id, second_version_id],
    ))

    assert summary.updated_count == 1
    moved_mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.outline_node_id == existing_kp.outline_node_id,
    )).one()
    assert moved_mapping.material_version_id == second_version_id
    assert moved_mapping.page_refs == [4]
    assert moved_mapping.source_block_refs == ["block_second_deck"]
    assert summary.suggestions[0].reason == "根据课程原始 OCR 证据块定位到对应 PPT 页码"


def test_out_of_range_suggestions_are_not_applied_to_shorter_deck(session, monkeypatch):
    """A stale page 55 cannot survive an optimization of a 3-page deck."""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, existing_kp, _new_kp, material_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    fake_client = _FakeLLMClient(json.dumps({"suggestions": [{
        "outline_node_id": existing_kp.outline_node_id,
        "page_refs": [55],
        "confidence": 0.9,
        "reason": "invalid page",
    }]}))

    summary = asyncio.run(PptMappingOptimizationService(client=fake_client).optimize_mappings(
        session,
        course_id=course.id,
        material_version_id=material_version_id,
    ))

    assert summary.updated_count == 0
    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.course_id == course.id,
        CoursePptMapping.outline_node_id == existing_kp.outline_node_id,
        CoursePptMapping.material_version_id == material_version_id,
    )).one()
    assert mapping.page_refs == [1, 2]


def test_optimize_mappings_reports_node_coverage(session, monkeypatch):
    """摘要应给出知识点覆盖口径：updated_count 是行数，覆盖统计以节点计。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, existing_kp, new_kp, material_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    # LLM 只为 existing_kp 出建议；new_kp（教师新增、无建议）仍无映射
    fake_client = _FakeLLMClient(json.dumps({"suggestions": [{
        "outline_node_id": existing_kp.outline_node_id,
        "page_refs": [1],
        "confidence": 0.9,
        "reason": "标题匹配",
    }]}))
    summary = asyncio.run(PptMappingOptimizationService(client=fake_client).optimize_mappings(
        session,
        course_id=course.id,
        material_version_id=material_version_id,
    ))

    assert summary.total_knowledge_points == 2
    assert summary.unmapped_node_ids == [new_kp.outline_node_id]


def test_optimize_mappings_salvages_truncated_llm_json(session, monkeypatch):
    """LLM 输出被截断时，已完整输出的建议仍应写入，而不是整批丢弃。"""
    monkeypatch.setattr(PptMappingOptimizationService, "_llm_is_configured", staticmethod(lambda: True))
    _teacher, course, _outline_ver, _existing_kp, new_kp, material_version_id = _setup_course_with_outline_and_ppt(
        session,
        with_existing_mapping=True,
    )
    truncated = (
        '{"suggestions": [{"outline_node_id": "' + new_kp.outline_node_id
        + '", "page_refs": [3], "confidence": 0.85, "reason": "材料匹配"},'
        '{"outline_node_id": "partially"'
    )
    fake_client = _FakeLLMClient(truncated)
    summary = asyncio.run(PptMappingOptimizationService(client=fake_client).optimize_mappings(
        session,
        course_id=course.id,
        material_version_id=material_version_id,
    ))

    mapping = session.exec(select(CoursePptMapping).where(
        CoursePptMapping.outline_node_id == new_kp.outline_node_id,
        CoursePptMapping.material_version_id == material_version_id,
    )).first()
    assert mapping is not None
    assert mapping.page_refs == [3]
    assert summary.updated_count >= 1
