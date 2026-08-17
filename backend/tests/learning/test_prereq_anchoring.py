"""M3：薄弱前置加固 + 选题锚定前置节点 测试。

覆盖：
- 仅当前节点表现不佳时触发 prereq_review（当前节点良好时不打扰先修复习）；
- 课件顺序双确认：图谱一跳前置必须排在课件前序之前（反序不判弱）；
- 无课件顺序数据时回退 fail-open（prereq_order_unverifiable）；
- PREREQ_REVIEW 的练习题锚定到薄弱前置节点。
"""
from __future__ import annotations

import uuid

from sqlmodel import select

from app.models.access_control_model import CourseCapability
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
)
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionDifficulty,
)
from app.services.recommendation_service import generate_recommendation


def _publish_outline(session, course, *, order):
    """发布课程目录：order = [(knowledge_graph_node_id, order_index), ...]"""
    outline = CourseOutlineVersion(
        course_id=course.id,
        version=1,
        lifecycle_status=OutlineLifecycleStatus.PUBLISHED,
    )
    session.add(outline)
    session.flush()
    for kg_id, order_index in order:
        session.add(CourseOutlineNode(
            outline_version_id=outline.outline_version_id,
            course_id=course.id,
            node_type=OutlineNodeType.KNOWLEDGE_POINT,
            title=f"知识点{kg_id}",
            order_index=order_index,
            knowledge_graph_node_id=kg_id,
        ))
    release = CourseRelease(
        course_id=course.id,
        version=1,
        status=ReleaseStatus.PUBLISHED,
        is_active=True,
        outline_version_id=outline.outline_version_id,
    )
    session.add(release)
    session.commit()
    return release


def _setup_graph(session, course, teacher, *, nodes, relations):
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
    )
    from app.services.graph_production_service import (
        publish_snapshot,
    )

    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).first()
    if cap:
        cap.knowledge_graph = True
        session.add(cap)
        session.commit()
    evidence = create_graph_evidence(
        session, course_id=course.id, text_snippet="前置知识证据"
    )
    publish_snapshot(
        session, course_id=course.id,
        nodes=nodes,
        relations=[
            {**relation, "evidence_ids": [evidence.evidence_id]}
            for relation in relations
        ],
        user_id=teacher.id,
    )


def _attempts(session, student_id, course_id, node_id, *, correct, wrong):
    from test_cognitive_recommendation import (
        _create_attempt,
        _create_published_question,
    )

    for _ in range(correct):
        q = _create_published_question(session, course_id)
        q.knowledge_node_ids = [node_id]
        session.add(q)
        session.commit()
        _create_attempt(session, student_id, course_id, q.id, is_correct=True)
    for _ in range(wrong):
        q = _create_published_question(session, course_id)
        q.knowledge_node_ids = [node_id]
        session.add(q)
        session.commit()
        _create_attempt(session, student_id, course_id, q.id, is_correct=False)


def _prereq_course(session):
    from test_cognitive_recommendation import (
        _setup_course,
    )
    from test_cognitive_recommendation import (
        _user as cr_user,
    )

    from app.models.user_model import UserRole

    suffix = uuid.uuid4().hex[:8]
    teacher = cr_user(session, f"m3_anchor_teacher_{suffix}", UserRole.TEACHER)
    student = cr_user(session, f"m3_anchor_student_{suffix}")
    course = _setup_course(session, teacher, student)
    _setup_graph(session, course, teacher, nodes=[
        {"node_id": "101", "label": "当前知识点", "type": "knowledge_point"},
        {"node_id": "202", "label": "前置知识点", "type": "knowledge_point"},
    ], relations=[{
        "relation_id": "r1", "source": "202", "target": "101",
        "type": "prerequisite_of", "evidence_ids": [],
    }])
    return teacher, student, course


def _compute_states(session, student_id, course_id):
    """计算前置 202 与当前 101 的认知状态（判弱需要前置状态行）。"""
    from app.services.cognitive_service import compute_cognitive_state

    compute_cognitive_state(session, student_id, course_id, node_id=202)
    compute_cognitive_state(session, student_id, course_id, node_id=101)


def test_prereq_review_skipped_when_current_node_strong(session):
    """M3：当前节点表现良好（perf >= 0.7）时不触发前置复习。"""
    _teacher, student, course = _prereq_course(session)
    # 前置 202 薄弱（5 次全错）
    _attempts(session, student.id, course.id, 202, correct=0, wrong=5)
    # 当前 101 表现良好（5 次全对 -> perf=1.0 >= 0.7）
    _attempts(session, student.id, course.id, 101, correct=5, wrong=0)

    _compute_states(session, student.id, course.id)
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec.recommendation_type != "prereq_review"
    assert not any("confirmed_weak_prerequisite" in rc for rc in rec.reason_codes)


def test_prereq_order_validation_blocks_reversed_order(session):
    """M3：图谱一跳前置在课件前序中排在当前节点之后 -> 顺序不符不判弱。"""
    _teacher, student, course = _prereq_course(session)
    # 课件顺序反置：101 在前、202 在后
    _publish_outline(session, course, order=[("101", 0), ("202", 1)])

    _attempts(session, student.id, course.id, 202, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 101, correct=2, wrong=1)

    _compute_states(session, student.id, course.id)
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec.recommendation_type != "prereq_review"
    assert not any("confirmed_weak_prerequisite" in rc for rc in rec.reason_codes)


def test_prereq_order_validation_passes_correct_order(session):
    """M3：课件顺序正确（前置在前）时双确认通过并判弱。"""
    _teacher, student, course = _prereq_course(session)
    _publish_outline(session, course, order=[("202", 0), ("101", 1)])

    _attempts(session, student.id, course.id, 202, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 101, correct=2, wrong=1)

    _compute_states(session, student.id, course.id)
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec.recommendation_type == "prereq_review"
    assert "prereq_order_validated" in rec.reason_codes


def test_prereq_review_without_outline_falls_back_open(session):
    """M3：无课件顺序数据（无 active release）时回退 fail-open 兼容判弱。"""
    _teacher, student, course = _prereq_course(session)
    _attempts(session, student.id, course.id, 202, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 101, correct=2, wrong=1)

    _compute_states(session, student.id, course.id)
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec.recommendation_type == "prereq_review"
    assert "prereq_order_unverifiable" in rec.reason_codes


def test_prereq_review_question_anchored_to_prerequisite_node(session):
    """M3：PREREQ_REVIEW 的练习题锚定到薄弱前置节点（修复"文案与题目脱节"）。

    当前节点与前置节点各有一道 EASY 题；推荐必须选中前置节点的题。
    """
    from test_cognitive_recommendation import _create_published_question

    _teacher, student, course = _prereq_course(session)
    _attempts(session, student.id, course.id, 202, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 101, correct=2, wrong=1)

    # 前置节点题（202）+ 当前节点题（101），均为 EASY
    prereq_q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
    prereq_q.knowledge_node_ids = [202]
    session.add(prereq_q)
    session.commit()
    current_q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
    current_q.knowledge_node_ids = [101]
    session.add(current_q)
    session.commit()

    _compute_states(session, student.id, course.id)
    rec = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec.recommendation_type == "prereq_review"
    assert rec.question_id is not None
    selected = session.exec(
        select(QuestionBankItem).where(QuestionBankItem.id == rec.question_id)
    ).first()
    assert selected is not None
    # 题目必须锚定到薄弱前置节点 202，而非当前节点 101
    assert 202 in (selected.knowledge_node_ids or [])
