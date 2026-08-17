"""M4：explanation_need 确定性投影 + 客户端分数封堵 测试。

覆盖：
- explanation_need 由可信维度确定性投影（困惑/低掌握/提示依赖加权），
  不再读取 NodeProgress.understanding_score（旧 LLM 链路）；
- 无证据时 explanation_need 保持 None；
- 旧数据（NodeProgress.understanding_score）不再影响认知；
- /progress/sync 端点忽略客户端自报 understandingScore（封堵 §4.3.5）；
- handle_student_question 停写旧 LLM 理解度（UnderstandingAnalysis / NodeProgress）。
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlmodel import select

from app.models.course_model import Course, CourseScript, ScriptNode, ScriptNodeType
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
)
from app.models.question_bank_model import (
    QuestionAttempt,
    QuestionBankItem,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.user_model import User, UserRole
from app.services.cognitive_service import compute_cognitive_state


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
        fanya_course_id=f"m4-{teacher_id}-{uuid.uuid4().hex[:6]}",
        fanya_course_name="M4投影测试课程",
        title="M4投影测试课程",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _question(session, course_id, node_id):
    q = QuestionBankItem(
        question_text=f"m4 question {uuid.uuid4().hex[:6]}",
        answer="answer",
        options={},
        similar_questions=[],
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM.value,
        course_id=course_id,
        knowledge_node_ids=[node_id] if node_id else [],
        prerequisite_node_ids=[],
        status=QuestionStatus.PUBLISHED,
        version=1,
        is_latest=True,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _attempt(session, student_id, course_id, question_id, *, is_correct, hint=False):
    session.add(QuestionAttempt(
        question_id=question_id,
        course_id=course_id,
        student_id=student_id,
        student_answer="test",
        is_correct=is_correct,
        cognitive_context={"hint_used": bool(hint)},
    ))
    session.commit()


# ---------------------------------------------------------------------------
# 认知层：确定性投影
# ---------------------------------------------------------------------------


def test_explanation_need_deterministic_projection(session):
    """M4：explanation = confusion*0.5 + (1-perf)*0.3（hint 缺失时）。"""
    teacher = _user(session, f"m4_proj_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m4_proj_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    # 5 次答题 1 对 4 错（不同题，无重复错误）
    for i in range(5):
        q = _question(session, course.id, None)
        _attempt(session, student.id, course.id, q.id, is_correct=(i == 0))

    state = compute_cognitive_state(session, student.id, course.id)
    # confusion = 0.8*0.7 + 0*0.3 = 0.56；explanation = 0.56*0.5 + 0.8*0.3 = 0.52
    assert state.explanation_need == pytest.approx(0.52)
    assert "explanation_need_from_deterministic_projection" in state.reason_codes
    assert "explanation_need_from_understanding" not in state.reason_codes


def test_explanation_need_with_hint_factor(session):
    """M4：hint_dependency 参与投影。"""
    teacher = _user(session, f"m4_hint_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m4_hint_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    # 4 次全错，其中 2 次使用提示 -> hint_dependency=0.5
    for i in range(4):
        q = _question(session, course.id, None)
        _attempt(session, student.id, course.id, q.id, is_correct=False, hint=(i < 2))

    state = compute_cognitive_state(session, student.id, course.id)
    # confusion = 1.0*0.7 = 0.7；explanation = 0.7*0.5 + 1.0*0.3 + 0.5*0.2 = 0.75
    assert state.explanation_need == pytest.approx(0.75)


def test_explanation_need_none_without_evidence(session):
    teacher = _user(session, f"m4_none_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m4_none_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    state = compute_cognitive_state(session, student.id, course.id)
    assert state.explanation_need is None


def test_explanation_need_ignores_stale_node_progress_understanding(session):
    """M4：旧 NodeProgress.understanding_score 不再影响认知（链路停写）。"""
    teacher = _user(session, f"m4_stale_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m4_stale_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    # 预置旧链路数据：理解度 0.1（低理解）。新链路不应反映它。
    progress = LearningProgress(
        user_id=student.id, course_id=course.id, status="in_progress",
    )
    session.add(progress)
    session.commit()
    session.refresh(progress)
    session.add(NodeProgress(
        progress_id=progress.id,
        node_id=1,
        node_index=0,
        understanding_score=0.1,
    ))
    session.commit()

    # 学生新答题表现良好（5 次全对 -> perf=1.0）
    for _ in range(5):
        q = _question(session, course.id, 1)
        _attempt(session, student.id, course.id, q.id, is_correct=True)

    state = compute_cognitive_state(session, student.id, course.id, node_id=1)
    # 旧链路会算 low_understanding 比例 = 1.0；新链路投影 = 0.0（confusion=0, perf=1）
    assert state.explanation_need == pytest.approx(0.0)
    assert "explanation_need_from_deterministic_projection" in state.reason_codes


# ---------------------------------------------------------------------------
# 端点层：客户端分数封堵
# ---------------------------------------------------------------------------


def test_progress_sync_ignores_client_understanding_score(client, session):
    from test_cognitive_recommendation import _setup_course, _token
    from test_cognitive_recommendation import _user as cr_user

    from app.models.progress_model import LearningStatus

    teacher = cr_user(session, f"m4_sync_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = cr_user(session, f"m4_sync_s_{uuid.uuid4().hex[:6]}")
    course = _setup_course(session, teacher, student)

    progress = LearningProgress(
        user_id=student.id, course_id=course.id, status=LearningStatus.IN_PROGRESS,
    )
    session.add(progress)
    session.commit()
    session.refresh(progress)
    node = NodeProgress(progress_id=progress.id, node_id=1, node_index=0, question_count=2)
    session.add(node)
    session.commit()
    session.refresh(node)

    resp = client.post(
        "/api/v1/progress/sync",
        json={
            "courseId": course.id,
            "nodeId": 1,
            "timestamp": 10.0,
            "understandingScore": 0.95,
            "timeSpent": 10,
        },
        headers={"Authorization": f"Bearer {_token(student)}"},
    )
    assert resp.status_code == 200, resp.text
    row = session.exec(select(NodeProgress).where(NodeProgress.id == node.id)).first()
    # 客户端自报分数被忽略，未写入认知读取源
    assert row.understanding_score is None
    assert row.question_count == 2


# ---------------------------------------------------------------------------
# 服务层：旧链路停写
# ---------------------------------------------------------------------------


async def _handle_question(session, user_id, course_id, node_id):
    from app.services.progress_service import progress_service

    return await progress_service.handle_student_question(
        session=session,
        user_id=user_id,
        course_id=course_id,
        question="数组是什么？",
        current_node_id=node_id,
        chat_messages=None,
    )


def _setup_progress_env(session, teacher, student, course):
    script = CourseScript(
        course_id=course.id, version=1, script_content={}, created_by=teacher.id,
    )
    session.add(script)
    session.commit()
    session.refresh(script)
    node = ScriptNode(
        script_id=script.id,
        node_index=0,
        node_type=ScriptNodeType.LECTURE,
        title="数组",
        content="数组是用于存储同类型元素的容器。",
    )
    session.add(node)
    session.commit()
    session.refresh(node)
    progress = LearningProgress(
        user_id=student.id, course_id=course.id, status="in_progress",
    )
    session.add(progress)
    session.commit()
    session.refresh(progress)
    node_progress = NodeProgress(
        progress_id=progress.id,
        node_id=node.id,
        node_index=0,
        understanding_score=0.9,
        question_count=5,
    )
    session.add(node_progress)
    session.commit()
    session.refresh(node_progress)
    return script, node, progress, node_progress


def test_handle_student_question_no_longer_writes_understanding(session):
    """M4：handle_student_question 不再写 UnderstandingAnalysis / NodeProgress 理解度。"""
    teacher = _user(session, f"m4_svc_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m4_svc_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    _, node, _, node_progress = _setup_progress_env(session, teacher, student, course)

    result = asyncio.run(_handle_question(session, student.id, course.id, node.id))

    assert "error" not in result
    # 返回确定性默认理解度（score=0.5，不再经 LLM 分析）
    assert result["understanding"]["score"] == 0.5
    # 无新 UnderstandingAnalysis 写入（限定本测试 progress，避免跨测试历史数据干扰）
    analyses = session.exec(
        select(UnderstandingAnalysis).where(
            UnderstandingAnalysis.progress_id == node_progress.progress_id,
        )
    ).all()
    assert len(analyses) == 0
    # NodeProgress 理解度保持原值（未被改写）
    row = session.exec(
        select(NodeProgress).where(NodeProgress.id == node_progress.id)
    ).first()
    assert row.understanding_score == 0.9
    # 提问计数仍递增（进度记录不受影响）
    assert row.question_count == 6
