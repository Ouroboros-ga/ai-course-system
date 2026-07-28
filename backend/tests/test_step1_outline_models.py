"""Step 1 - 统一课程建设九步实施计划：课程树/讲稿/提案模型测试。

覆盖决策验收：
- 一门课可同时存在草稿目录与已发布目录；
- 课程 A 的目录不可被课程 B 成员读取（按 course_id 隔离）；
- 目录顺序、父子关系、Evidence 来源、锁定状态可追溯；
- CourseOutlineNode 是真正的有序树（parent_node_id FK 自引用），区别于旧 ScriptNode.chapter_id 字符串；
- PatchProposal 结构化（before/after/evidence_refs/external_ref）。

见 docs/phase1/decisions/2026-07-27-统一课程建设九步实施计划.md §5 Step 1。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import Session as _Session, select

from app.core.security import get_password_hash
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
    PatchOperation,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
    TeachingScriptNode,
    TeachingScriptVersion,
)
from app.models.database import engine
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline


def _session_factory():
    return _Session(engine)


def _user(session, name):
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(session, teacher_id, title):
    c = Course(
        fanya_course_id=f"s1-{teacher_id}-{datetime.now(timezone.utc).timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=CourseStatus.DRAFT,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    return c


# ---------------------------------------------------------------------------
# 1. 草稿目录与已发布目录可共存
# ---------------------------------------------------------------------------


def test_course_can_have_draft_and_published_outline(session):
    """一门课同时存在 draft 与 published 两个 CourseOutlineVersion。"""
    user = _user(session, "s1_draft_user")
    course = _course(session, user.id, "Draft+Published Course")

    draft = CourseOutlineVersion(
        course_id=course.id, version=1,
        lifecycle_status=OutlineLifecycleStatus.DRAFT,
        created_by=user.id,
    )
    published = CourseOutlineVersion(
        course_id=course.id, version=2,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
        created_by=user.id,
    )
    session.add_all([draft, published])
    session.commit()
    session.refresh(draft)
    session.refresh(published)

    sf = _session_factory()
    with sf as s:
        versions = s.exec(
            select(CourseOutlineVersion).where(CourseOutlineVersion.course_id == course.id)
        ).all()
        statuses = {v.lifecycle_status for v in versions}
        assert OutlineLifecycleStatus.DRAFT in statuses
        assert OutlineLifecycleStatus.PUBLISHED in statuses


# ---------------------------------------------------------------------------
# 2. 课程树是真正的有序树（parent_node_id FK 自引用）
# ---------------------------------------------------------------------------


def test_outline_node_is_real_ordered_tree(session):
    """CourseOutlineNode 用 parent_node_id FK 构成 chapter->section->knowledge_point 树，
    且 order_index 维持顺序；区别于旧 ScriptNode.chapter_id 字符串。"""
    user = _user(session, "s1_tree_user")
    course = _course(session, user.id, "Tree Course")

    ov = CourseOutlineVersion(course_id=course.id, version=1, created_by=user.id)
    session.add(ov)
    session.commit()
    session.refresh(ov)

    chapter = CourseOutlineNode(
        outline_version_id=ov.outline_version_id, course_id=course.id,
        node_type=OutlineNodeType.CHAPTER, title="第一章", order_index=0,
    )
    session.add(chapter)
    session.commit()
    session.refresh(chapter)

    section = CourseOutlineNode(
        outline_version_id=ov.outline_version_id, course_id=course.id,
        parent_node_id=chapter.outline_node_id,
        node_type=OutlineNodeType.SECTION, title="1.1 节", order_index=0,
    )
    kp = CourseOutlineNode(
        outline_version_id=ov.outline_version_id, course_id=course.id,
        parent_node_id=section.outline_node_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT, title="知识点A", order_index=0,
        source_block_refs=["blk_001", "blk_002"], confidence=0.92,
    )
    session.add_all([section, kp])
    session.commit()

    sf = _session_factory()
    with sf as s:
        loaded_kp = s.exec(
            select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == kp.outline_node_id)
        ).first()
        assert loaded_kp is not None
        # 真正的父子链：知识点 -> 节 -> 章
        assert loaded_kp.parent_node_id == section.outline_node_id
        loaded_section = s.exec(
            select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == loaded_kp.parent_node_id)
        ).first()
        assert loaded_section.parent_node_id == chapter.outline_node_id
        # 溯源字段保留
        assert loaded_kp.source_block_refs == ["blk_001", "blk_002"]
        assert loaded_kp.confidence == 0.92


# ---------------------------------------------------------------------------
# 3. 课程 A/B 隔离：课程 A 的目录不出现在课程 B
# ---------------------------------------------------------------------------


def test_outline_isolation_between_courses(session):
    user = _user(session, "s1_iso_user")
    course_a = _course(session, user.id, "Course A")
    course_b = _course(session, user.id, "Course B")

    ov_a = CourseOutlineVersion(course_id=course_a.id, version=1, created_by=user.id)
    session.add(ov_a)
    session.commit()
    session.refresh(ov_a)
    node_a = CourseOutlineNode(
        outline_version_id=ov_a.outline_version_id, course_id=course_a.id,
        node_type=OutlineNodeType.CHAPTER, title="A 章独有",
    )
    session.add(node_a)
    session.commit()

    sf = _session_factory()
    with sf as s:
        # 课程 B 查不到课程 A 的节点
        b_nodes = s.exec(
            select(CourseOutlineNode).where(CourseOutlineNode.course_id == course_b.id)
        ).all()
        assert b_nodes == []
        # 课程 A 能查到
        a_nodes = s.exec(
            select(CourseOutlineNode).where(CourseOutlineNode.course_id == course_a.id)
        ).all()
        assert any(n.title == "A 章独有" for n in a_nodes)


# ---------------------------------------------------------------------------
# 4. 教师锁定后，锁定状态可追溯
# ---------------------------------------------------------------------------


def test_outline_node_lock_is_persisted(session):
    user = _user(session, "s1_lock_user")
    course = _course(session, user.id, "Lock Course")

    ov = CourseOutlineVersion(course_id=course.id, version=1, created_by=user.id)
    session.add(ov)
    session.commit()
    session.refresh(ov)

    node = CourseOutlineNode(
        outline_version_id=ov.outline_version_id, course_id=course.id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT, title="锁定知识点",
        locked_by=user.id,
    )
    session.add(node)
    session.commit()

    sf = _session_factory()
    with sf as s:
        loaded = s.exec(
            select(CourseOutlineNode).where(CourseOutlineNode.outline_node_id == node.outline_node_id)
        ).first()
        assert loaded.locked_by == user.id
        # 锁定语义：后续 Agent 提案不得覆盖（PatchProposal 服务层在 Step 6 实现，此处只验状态可追溯）


# ---------------------------------------------------------------------------
# 5. 讲稿节点按课程树组织，与目录版本对齐
# ---------------------------------------------------------------------------


def test_teaching_script_aligned_to_outline(session):
    user = _user(session, "s1_script_user")
    course = _course(session, user.id, "Script Course")

    ov = CourseOutlineVersion(course_id=course.id, version=1, created_by=user.id)
    session.add(ov)
    session.commit()
    session.refresh(ov)
    node = CourseOutlineNode(
        outline_version_id=ov.outline_version_id, course_id=course.id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT, title="KP",
    )
    session.add(node)
    session.commit()
    session.refresh(node)

    tsv = TeachingScriptVersion(
        course_id=course.id, outline_version_id=ov.outline_version_id, version=1,
        created_by=user.id,
    )
    session.add(tsv)
    session.commit()
    session.refresh(tsv)

    tsn = TeachingScriptNode(
        script_version_id=tsv.script_version_id, course_id=course.id,
        outline_node_id=node.outline_node_id,
        content="这是讲稿正文", style="beginner",
        evidence_refs=["es_001"],
    )
    session.add(tsn)
    session.commit()

    sf = _session_factory()
    with sf as s:
        loaded = s.exec(
            select(TeachingScriptNode).where(TeachingScriptNode.script_node_id == tsn.script_node_id)
        ).first()
        assert loaded.outline_node_id == node.outline_node_id
        assert loaded.evidence_refs == ["es_001"]
        # 目录与讲稿版本对齐同一 outline_version_id
        assert tsv.outline_version_id == ov.outline_version_id


# ---------------------------------------------------------------------------
# 6. PatchProposal 结构化：before/after/evidence_refs/external_ref
# ---------------------------------------------------------------------------


def test_patch_proposal_structured_with_diff_and_external_ref(session):
    """Agent 提案是结构化数据：operation/target/before/after/evidence_refs。
    外网资料走 external_ref，不进入 evidence_refs。"""
    user = _user(session, "s1_prop_user")
    course = _course(session, user.id, "Proposal Course")

    proposal = PatchProposal(
        course_id=course.id, tool_name="ScriptProposalTool",
        policy_version="agent-policy-1.0",
        status=PatchProposalStatus.PENDING, reason="降低术语密度",
        created_by=user.id,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)

    op = PatchProposalOperation(
        proposal_id=proposal.proposal_id, course_id=course.id,
        operation=PatchOperation.REPLACE, target="script_node_12.content",
        before="原内容（术语密集）", after="建议内容（更通俗）",
        reason="降低术语密度",
        evidence_refs=["es_001"],  # 仅课程 Evidence
        external_ref="https://example.com/external-ref",  # 外网资料，不进 evidence_refs
        policy_version="agent-policy-1.0",
    )
    session.add(op)
    session.commit()

    sf = _session_factory()
    with sf as s:
        loaded_op = s.exec(
            select(PatchProposalOperation).where(PatchProposalOperation.op_id == op.op_id)
        ).first()
        assert loaded_op.operation == PatchOperation.REPLACE
        assert loaded_op.before == "原内容（术语密集）"
        assert loaded_op.after == "建议内容（更通俗）"
        assert loaded_op.evidence_refs == ["es_001"]
        assert loaded_op.external_ref == "https://example.com/external-ref"
        # 关键不变式：external_ref 与 evidence_refs 分离，外网资料不伪装为课程 Evidence
        assert "https://example.com/external-ref" not in (loaded_op.evidence_refs or [])
