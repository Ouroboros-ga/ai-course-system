"""Step 4 - 统一课程建设九步实施计划：草稿资产生成测试。

覆盖决策验收：
- 解析后生成草稿 RAG/图谱/目录/讲稿/Markdown 资源（可观测子阶段）。
- 目录与讲稿版本对齐（同一 outline_version_id），发布状态一致（都 draft）。
- Markdown 写为 ResourceItem/ResourceVersion（lifecycle_status=draft, visibility=teachers），
  带 source_block_refs，不塞任务 JSON。
- 学生只读已发布版；草稿仅建设角色（visibility=teachers）。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §8 Step 4。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session as _Session, select

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_build_model import MaterialStatus, SourceMaterial, SourceMaterialVersion
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.database import engine
from app.models.document_parse_model import DocumentBlock, DocumentParseRun
from app.models.resource_model import (
    ResourceItem,
    ResourceLifecycleStatus,
    ResourceVersion,
    ResourceVisibility,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.document_draft_builders import build_draft_assets
from app.services.document_parse_service import document_parse_service


def _session_factory():
    return _Session(engine)


def _user(session, name):
    u = User(username=name, hashed_password=get_password_hash("pw"), role=UserRole.TEACHER, is_active=True)
    session.add(u); session.commit(); session.refresh(u); return u


def _course(session, teacher_id):
    c = Course(
        fanya_course_id=f"s4-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="S4 Course", title="S4 Course",
        teacher_id=teacher_id, status=CourseStatus.DRAFT,
    )
    session.add(c); session.commit(); session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    return c


def _seed_run_and_blocks(session, course_id, teacher_id, n_blocks=3):
    """创建 parse_run + n 个 DocumentBlock，作为草稿资产构建的输入。"""
    m = SourceMaterial(course_id=course_id, name="t.pptx", created_by=teacher_id)
    session.add(m); session.commit(); session.refresh(m)
    v = SourceMaterialVersion(
        material_id=m.material_id, course_id=course_id, version=1,
        file_path="course-source/s4/source.pptx", file_hash="h4", file_size=10,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        parse_status=MaterialStatus.PARSING, created_by=teacher_id,
    )
    session.add(v); session.commit(); session.refresh(v)
    run = document_parse_service.create_run(
        session, course_id=course_id, material_id=m.material_id,
        material_version_id=v.version_id, document_id=None, initiated_by=teacher_id,
    )
    document_parse_service.mark_running(session, run_id=run.run_id, course_id=course_id)
    for i in range(n_blocks):
        document_parse_service.add_block(
            session, course_id=course_id, run_id=run.run_id, document_id=None,
            page_number=i + 1, block_type="text", text=f"这是第 {i+1} 个知识点的讲解内容",
            material_version_id=v.version_id, page_or_slide=i + 1,
            source_kind="native", confidence=1.0, provider_version="native-pptx=1.0",
        )
    session.commit()
    return run, v


# ---------------------------------------------------------------------------
# 1. build_draft_assets 生成全部草稿资产
# ---------------------------------------------------------------------------


def test_build_draft_assets_produces_all_artifacts(session):
    """解析后生成草稿 RAG/图谱/目录/讲稿/Markdown 资源。"""
    user = _user(session, "s4_build_user")
    course = _course(session, user.id)
    run, version = _seed_run_and_blocks(session, course.id, user.id, n_blocks=3)

    result = build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=version.version_id, created_by=user.id,
    )

    assert result.rag_indexed_chunks == 3
    assert result.graph_node_candidates == 3
    assert result.outline_version_id is not None
    assert result.outline_node_count == 3
    assert result.script_version_id is not None
    assert result.script_node_count == 3
    assert result.markdown_resource_id is not None
    assert result.markdown_resource_version_id is not None


# ---------------------------------------------------------------------------
# 2. 目录与讲稿版本对齐（同一 outline_version_id，都 draft）
# ---------------------------------------------------------------------------


def test_outline_and_script_versions_aligned_and_draft(session):
    """讲稿的 outline_version_id 指向目录版本；两者 lifecycle_status 都是 draft。"""
    user = _user(session, "s4_align_user")
    course = _course(session, user.id)
    run, version = _seed_run_and_blocks(session, course.id, user.id, n_blocks=2)

    result = build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=version.version_id, created_by=user.id,
    )

    sf = _session_factory()
    with sf as s:
        ov = s.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.outline_version_id == result.outline_version_id
        )).first()
        sv = s.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.script_version_id == result.script_version_id
        )).first()
        assert ov is not None and sv is not None
        # 对齐：讲稿指向目录版本
        assert sv.outline_version_id == ov.outline_version_id
        # 发布状态一致：都 draft
        assert ov.lifecycle_status == OutlineLifecycleStatus.DRAFT
        assert sv.lifecycle_status == OutlineLifecycleStatus.DRAFT


# ---------------------------------------------------------------------------
# 3. Markdown 资源是 draft + teachers，带 source_block_refs
# ---------------------------------------------------------------------------


def test_markdown_resource_is_draft_teachers_with_refs(session):
    """Markdown ResourceVersion: lifecycle=draft, visibility=teachers, 带 source_block_refs。"""
    user = _user(session, "s4_md_user")
    course = _course(session, user.id)
    run, version = _seed_run_and_blocks(session, course.id, user.id, n_blocks=2)

    result = build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=version.version_id, created_by=user.id,
    )

    sf = _session_factory()
    with sf as s:
        item = s.exec(select(ResourceItem).where(
            ResourceItem.resource_id == result.markdown_resource_id
        )).first()
        rv = s.exec(select(ResourceVersion).where(
            ResourceVersion.version_id == result.markdown_resource_version_id
        )).first()
        assert item is not None and rv is not None
        # 草稿 + 仅建设角色
        assert item.lifecycle_status == ResourceLifecycleStatus.DRAFT
        assert item.visibility == ResourceVisibility.TEACHERS
        # 解析溯源
        assert rv.material_version_id == version.version_id
        assert rv.parse_run_id == run.run_id
        assert rv.source_block_refs  # 非空，指向 DocumentBlock
        # object_key 指向对象存储，不塞任务 JSON
        assert rv.object_key.startswith("course-md/")


# ---------------------------------------------------------------------------
# 4. 草稿目录节点带 source_block_refs（Evidence 可追溯）
# ---------------------------------------------------------------------------


def test_outline_nodes_carry_source_block_refs(session):
    """CourseOutlineNode.source_block_refs 指向 DocumentBlock，Evidence 可追溯。"""
    user = _user(session, "s4_refs_user")
    course = _course(session, user.id)
    run, version = _seed_run_and_blocks(session, course.id, user.id, n_blocks=2)

    result = build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=version.version_id, created_by=user.id,
    )

    sf = _session_factory()
    with sf as s:
        nodes = s.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_version_id == result.outline_version_id
        )).all()
        # 每个节点的 source_block_refs 指向真实存在的 block
        block_ids = set()
        with _Session(engine) as s2:
            for blk in s2.exec(select(DocumentBlock).where(DocumentBlock.run_id == run.run_id)).all():
                block_ids.add(blk.block_id)
        for node in nodes:
            assert node.source_block_refs
            for ref in node.source_block_refs:
                assert ref in block_ids


# ---------------------------------------------------------------------------
# 5. 进度回调被逐阶段调用
# ---------------------------------------------------------------------------


def test_progress_callback_invoked_per_stage(session):
    """progress_cb 在每个子阶段被调用（前端可见分阶段进度）。"""
    user = _user(session, "s4_prog_user")
    course = _course(session, user.id)
    run, version = _seed_run_and_blocks(session, course.id, user.id, n_blocks=2)

    stages: list[str] = []

    def cb(stage_name: str):
        stages.append(stage_name)

    build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=version.version_id, created_by=user.id,
        progress_cb=cb,
    )
    # 五个子阶段都被回调
    assert "rag_index_draft" in stages
    assert "graph_draft" in stages
    assert "outline_draft" in stages
    assert "teaching_script_draft" in stages
    assert "markdown_resource_draft" in stages


# ---------------------------------------------------------------------------
# 6. 空 blocks 不崩溃
# ---------------------------------------------------------------------------


def test_build_draft_assets_handles_empty_blocks(session):
    """无 DocumentBlock 时安全返回空结果，不抛异常。"""
    user = _user(session, "s4_empty_user")
    course = _course(session, user.id)
    # 创建 run 但不写 block
    m = SourceMaterial(course_id=course.id, name="empty.pptx", created_by=user.id)
    session.add(m); session.commit(); session.refresh(m)
    v = SourceMaterialVersion(
        material_id=m.material_id, course_id=course.id, version=1,
        file_path="course-source/s4/empty.pptx", file_hash="he", file_size=0,
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        parse_status=MaterialStatus.PARSING, created_by=user.id,
    )
    session.add(v); session.commit(); session.refresh(v)
    run = document_parse_service.create_run(
        session, course_id=course.id, material_id=m.material_id,
        material_version_id=v.version_id, document_id=None, initiated_by=user.id,
    )
    document_parse_service.mark_running(session, run_id=run.run_id, course_id=course.id)

    result = build_draft_assets(
        session, course_id=course.id, run_id=run.run_id,
        material_version_id=v.version_id, created_by=user.id,
    )
    assert result.outline_version_id is None
    assert result.rag_indexed_chunks == 0
    assert any("no DocumentBlock" in w for w in result.warnings)
