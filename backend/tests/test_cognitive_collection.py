"""认知采集测试：提问深度标定记录 + 观看时长置信度佐证。

覆盖 cognitive_service 的采集链路：
1. record_question_depth 写入 + compute_cognitive_state 计算 inquiry_depth
2. 样本不足时 inquiry_depth 保持 unknown
3. 观看时长达到阈值时 evidence_confidence 提升（佐证，不直接进表现分）
4. _parse_inquiry_depth 边界（LLM 标定值容错）
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from app.models.cognitive_state_model import CognitiveState, QuestionDepthRecord
from app.models.course_model import Course
from app.models.question_bank_model import (
    QuestionAttempt,
    QuestionBankItem,
    QuestionDifficulty,
    QuestionStatus,
)
from app.models.progress_model import LearningProgress, NodeProgress
from app.services.cognitive_service import (
    MIN_SAMPLE_FOR_CONFIDENCE,
    MIN_SAMPLE_FOR_INQUIRY,
    MIN_WATCH_SECONDS_FOR_BOOST,
    compute_cognitive_state,
    record_question_depth,
)
from app.platform.agents.edu.workflow import _parse_inquiry_depth


def _make_course(session, teacher_user) -> Course:
    course = Course(
        fanya_course_id=f"fanya_{uuid.uuid4().hex[:8]}",
        fanya_course_name="认知采集测试课程",
        title=f"认知采集测试课程{uuid.uuid4().hex[:6]}",
        teacher_id=teacher_user.id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _make_question(session, course, student_user, *, node_id: int = 1, count: int = 5) -> QuestionBankItem:
    question = QuestionBankItem(
        course_id=course.id,
        question_type="single_choice",
        difficulty=QuestionDifficulty.MEDIUM.value,
        status=QuestionStatus.PUBLISHED,
        stem=f"测试题干 {uuid.uuid4().hex[:6]}",
        question_text=f"测试题干全文 {uuid.uuid4().hex[:6]}",
        knowledge_node_ids=[node_id],
        is_latest=True,
    )
    session.add(question)
    session.commit()
    session.refresh(question)
    for index in range(count):
        attempt = QuestionAttempt(
            question_id=question.id,
            course_id=course.id,
            student_id=student_user.id,
            is_correct=True,
            score=0.9,
            measurement_role="scored_performance",
        )
        session.add(attempt)
    session.commit()
    return question


def _add_watch_time(session, course, student_user, *, node_id: int = 1, seconds: int = 400) -> LearningProgress:
    progress = LearningProgress(
        user_id=student_user.id,
        course_id=course.id,
        current_node_id=node_id,
        current_node_index=0,
        status="in_progress",
    )
    session.add(progress)
    session.commit()
    session.refresh(progress)
    node = NodeProgress(
        progress_id=progress.id,
        node_id=node_id,
        node_index=0,
        time_spent=seconds,
    )
    session.add(node)
    session.commit()
    return progress


def test_record_question_depth_persists_scoped_row(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    record = record_question_depth(
        session,
        student_id=student_user.id,
        course_id=course.id,
        node_id=7,
        depth_score=0.8,
        trace_id="trace-1",
    )
    assert record.depth_score == 0.8
    assert record.node_id == 7
    assert record.trace_id == "trace-1"
    rows = session.exec(select(QuestionDepthRecord)).all()
    assert len(rows) == 1
    assert rows[0].course_id == course.id
    assert rows[0].student_id == student_user.id


def test_record_question_depth_clamps_score(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    high = record_question_depth(session, student_id=student_user.id, course_id=course.id, node_id=None, depth_score=1.5)
    low = record_question_depth(session, student_id=student_user.id, course_id=course.id, node_id=None, depth_score=-0.3)
    assert high.depth_score == 1.0
    assert low.depth_score == 0.0


def test_compute_inquiry_depth_from_llm_calibration(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    node_id = 3
    record_question_depth(session, student_id=student_user.id, course_id=course.id, node_id=node_id, depth_score=0.4)
    record_question_depth(session, student_id=student_user.id, course_id=course.id, node_id=node_id, depth_score=0.8)

    state = compute_cognitive_state(session, student_user.id, course.id, node_id=node_id)
    assert state.inquiry_depth == pytest.approx(0.6)
    assert "inquiry_depth_from_llm_calibration" in state.reason_codes


def test_compute_inquiry_depth_insufficient_samples_unknown(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    node_id = 3
    record_question_depth(session, student_id=student_user.id, course_id=course.id, node_id=node_id, depth_score=0.4)

    state = compute_cognitive_state(session, student_user.id, course.id, node_id=node_id)
    assert state.inquiry_depth is None
    assert "inquiry_insufficient_samples" in state.reason_codes


def test_compute_inquiry_depth_unknown_without_records(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    state = compute_cognitive_state(session, student_user.id, course.id, node_id=3)
    assert state.inquiry_depth is None
    assert "inquiry_no_calibration_records" in state.reason_codes


def test_watch_time_boosts_evidence_confidence(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    _make_question(session, course, student_user, count=MIN_SAMPLE_FOR_CONFIDENCE)
    _add_watch_time(session, course, student_user, node_id=1, seconds=MIN_WATCH_SECONDS_FOR_BOOST + 100)

    state = compute_cognitive_state(session, student_user.id, course.id, node_id=1)
    # 基础置信 0.85 + 观看时长佐证 0.05 = 0.90
    assert state.evidence_confidence == pytest.approx(0.90)
    assert "confidence_boosted_by_watch_time" in state.reason_codes


def test_watch_time_below_threshold_no_boost(session, student_user, teacher_user):
    course = _make_course(session, teacher_user)
    _make_question(session, course, student_user, count=MIN_SAMPLE_FOR_CONFIDENCE)
    _add_watch_time(session, course, student_user, node_id=1, seconds=MIN_WATCH_SECONDS_FOR_BOOST - 100)

    state = compute_cognitive_state(session, student_user.id, course.id, node_id=1)
    assert state.evidence_confidence == 0.85
    assert "confidence_boosted_by_watch_time" not in state.reason_codes


def test_parse_inquiry_depth_boundaries():
    assert _parse_inquiry_depth(None) is None
    assert _parse_inquiry_depth("") is None
    assert _parse_inquiry_depth("not-a-number") is None
    assert _parse_inquiry_depth(1.5) is None
    assert _parse_inquiry_depth(-0.1) is None
    assert _parse_inquiry_depth(0.0) == 0.0
    assert _parse_inquiry_depth(1.0) == 1.0
    assert _parse_inquiry_depth("0.65") == 0.65
