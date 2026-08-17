"""M2：证据时间衰减（读取投影，不落库）测试。

覆盖：
- 衰减函数标定（半衰期 14 天，2^(-elapsed/half_life)）；
- 投影不落库（CognitiveState 行不被修改）；
- 认知端口序列化按衰减后置信度输出并追加 evidence_decayed；
- 薄弱前置判弱使用衰减后置信度（旧证据跌破门槛则不判弱）。
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.cognitive_state_model import CognitiveState
from app.models.course_model import Course
from app.models.user_model import User, UserRole
from app.services.cognitive_decay_service import (
    decay_factor_for,
    decayed_confidence,
    decayed_mastery_score,
    project_time_decay,
)
from app.services.cognitive_service import compute_cognitive_state
from app.services.recommendation_service import generate_recommendation


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


# ---------------------------------------------------------------------------
# 衰减函数标定
# ---------------------------------------------------------------------------


def test_decay_factor_fresh_state_is_one():
    assert decay_factor_for(utcnow_aware()) == 1.0


def test_decay_factor_halves_after_half_life():
    assert decay_factor_for(_ago(14.0)) == pytest.approx(0.5)


def test_decay_factor_seven_days_is_sqrt_half():
    assert decay_factor_for(_ago(7.0)) == pytest.approx(0.7071, abs=0.01)


def test_decay_factor_naive_datetime_treated_as_utc():
    naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=14)
    assert decay_factor_for(naive) == pytest.approx(0.5)


def test_decay_factor_none_computed_at_is_one():
    assert decay_factor_for(None) == 1.0


def test_decay_factor_custom_half_life():
    assert decay_factor_for(_ago(7.0), half_life_days=7.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 投影与不落库
# ---------------------------------------------------------------------------


def test_decayed_projection_none_stays_none():
    assert decayed_confidence(None, computed_at=_ago(14)) is None
    assert decayed_mastery_score(None, computed_at=_ago(14)) is None


def test_project_time_decay_does_not_mutate_state(session):
    teacher = _user(session, "decay_nomut_teacher", UserRole.TEACHER)
    student = _user(session, "decay_nomut_student")
    course = _course(session, teacher.id)
    question = _question(session, course.id, student.id)
    _attempt(session, student.id, course.id, question.id, is_correct=False, count=5)

    state = compute_cognitive_state(session, student.id, course.id)
    original_conf = state.evidence_confidence
    original_mastery = state.mastery_score

    stale_at = _ago(14.0)
    state.computed_at = stale_at
    session.commit()

    decayed_conf, decayed_mastery, factor = project_time_decay(
        session.exec(select(CognitiveState).where(CognitiveState.id == state.id)).first()
    )
    assert factor == pytest.approx(0.5)
    assert decayed_conf == pytest.approx(original_conf * 0.5)
    assert decayed_mastery == pytest.approx(original_mastery * 0.5)

    # 不落库：行内原值保持（project_time_decay 不修改任何字段；
    # SQLite 以 naive UTC 存储 datetime）
    row = session.exec(select(CognitiveState).where(CognitiveState.id == state.id)).first()
    assert row.evidence_confidence == original_conf
    assert row.mastery_score == original_mastery
    assert row.computed_at == stale_at.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# 认知端口序列化接入
# ---------------------------------------------------------------------------


def test_cognition_port_serialization_applies_decay(session):
    from app.models.database import session_factory
    from app.platform.agents.providers.cognition.cognition import (
        make_session_scoped_cognition_port,
    )

    teacher = _user(session, "decay_port_teacher", UserRole.TEACHER)
    student = _user(session, "decay_port_student")
    course = _course(session, teacher.id)
    question = _question(session, course.id, student.id)
    _attempt(session, student.id, course.id, question.id, is_correct=False, count=5)

    state = compute_cognitive_state(session, student.id, course.id)
    fresh_conf = state.evidence_confidence
    state.computed_at = _ago(14.0)
    session.commit()

    port = make_session_scoped_cognition_port(session_factory)
    serialized = asyncio.run(port.get_state(
        student_id=str(student.id), course_id=str(course.id),
    ))
    assert serialized is not None
    assert serialized["evidence_confidence"] == pytest.approx(fresh_conf * 0.5)
    assert "evidence_decayed" in serialized["reason_codes"]

    # 对照组：新状态不衰减、无 evidence_decayed
    state.computed_at = utcnow_aware()
    session.commit()
    fresh = asyncio.run(port.get_state(
        student_id=str(student.id), course_id=str(course.id),
    ))
    assert fresh is not None
    assert fresh["evidence_confidence"] == pytest.approx(fresh_conf)
    assert "evidence_decayed" not in fresh["reason_codes"]


# ---------------------------------------------------------------------------
# 薄弱前置判弱接入
# ---------------------------------------------------------------------------


def test_stale_prerequisite_not_flagged_weak_after_decay(session):
    """M2：前置节点证据超过半衰期（衰减后置信度跌破 0.6）时不判弱。

    对照组（computed_at=now）仍判弱，证明衰减是唯一变量。
    """
    from test_cognitive_recommendation import (
        _create_attempt,
        _create_published_question,
        _setup_course,
    )
    from test_cognitive_recommendation import (
        _user as cr_user,
    )

    from app.models.access_control_model import CourseCapability
    from app.models.question_bank_model import QuestionDifficulty
    from app.services.graph_production_service import (
        create_evidence as create_graph_evidence,
    )
    from app.services.graph_production_service import (
        publish_snapshot,
    )

    teacher = cr_user(session, "decay_prereq_teacher", UserRole.TEACHER)
    student = cr_user(session, "decay_prereq_student")
    course = _setup_course(session, teacher, student)
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
        nodes=[
            {"node_id": "101", "label": "当前知识点", "type": "knowledge_point"},
            {"node_id": "202", "label": "前置知识点", "type": "knowledge_point"},
        ],
        relations=[{
            "relation_id": "r1", "source": "202", "target": "101",
            "type": "prerequisite_of", "evidence_ids": [evidence.evidence_id],
        }],
        user_id=teacher.id,
    )

    # 前置节点 202：5 次全错 -> 连续置信度 0.625（>= 0.6 判弱门槛）
    for _ in range(5):
        q = _create_published_question(session, course.id, QuestionDifficulty.EASY)
        q.knowledge_node_ids = [202]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=False)
    prereq_state = compute_cognitive_state(session, student.id, course.id, node_id=202)
    assert prereq_state.evidence_confidence >= 0.6

    # 当前节点 101 也有答题数据
    for i in range(3):
        q = _create_published_question(session, course.id)
        q.knowledge_node_ids = [101]
        session.add(q)
        session.commit()
        _create_attempt(session, student.id, course.id, q.id, is_correct=(i < 2))

    # 对照组：新证据 -> 判弱
    rec_fresh = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec_fresh.recommendation_type == "prereq_review"

    # 实验组：把前置节点证据改为 14 天前 -> 衰减后 0.3125 < 0.6 -> 不判弱
    prereq_state.computed_at = _ago(14.0)
    session.add(prereq_state)
    session.commit()
    rec_stale = generate_recommendation(
        session, student.id, course.id, node_id=101, force_recompute=False,
    )
    assert rec_stale.recommendation_type != "prereq_review"
    assert not any("confirmed_weak_prerequisite" in rc for rc in rec_stale.reason_codes)


# ---------------------------------------------------------------------------
# 轻量构造 helper
# ---------------------------------------------------------------------------


def _user(session, name, role=UserRole.STUDENT):
    from app.core.security import get_password_hash

    user = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id):
    course = Course(
        fanya_course_id=f"decay-{teacher_id}-{datetime.now(UTC).timestamp()}",
        fanya_course_name="衰减测试课程",
        title="衰减测试课程",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _question(session, course_id, student_id):
    from app.models.question_bank_model import (
        QuestionBankItem,
        QuestionDifficulty,
        QuestionStatus,
        QuestionType,
    )

    q = QuestionBankItem(
        question_text="decay test question",
        answer="answer",
        options={},
        similar_questions=[],
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM.value,
        course_id=course_id,
        knowledge_node_ids=[],
        prerequisite_node_ids=[],
        status=QuestionStatus.PUBLISHED,
        version=1,
        is_latest=True,
        created_by=student_id,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _attempt(session, student_id, course_id, question_id, *, is_correct, count=1):
    from app.models.question_bank_model import QuestionAttempt

    for _ in range(count):
        session.add(QuestionAttempt(
            question_id=question_id,
            course_id=course_id,
            student_id=student_id,
            student_answer="test",
            is_correct=is_correct,
            cognitive_context={},
        ))
    session.commit()
