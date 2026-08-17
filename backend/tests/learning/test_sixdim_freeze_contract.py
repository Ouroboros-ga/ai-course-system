"""M9：旧统计冻结 + 六维冻结契约 测试。

覆盖：
- 泛雅回调不再更新 avg_understanding_score（冻结，total_nodes_completed 仍递增）；
- /progress/visualization 旧理解度展示标注 deprecated（顶层 + 每条分析）。
"""
from __future__ import annotations

import asyncio
import uuid

from sqlmodel import select

from app.models.course_model import Course, StudentEnrollment
from app.models.progress_model import (
    LearningProgress,
    UnderstandingAnalysis,
    UnderstandingLevel,
)
from app.models.user_model import User, UserRole


def _user(session, name, role=UserRole.STUDENT, fanya_account_id=None):
    from app.core.security import get_password_hash

    user = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
        fanya_account_id=fanya_account_id,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session, teacher_id, fanya_course_id=None):
    course = Course(
        fanya_course_id=fanya_course_id or f"m9-{teacher_id}-{uuid.uuid4().hex[:6]}",
        fanya_course_name="M9冻结测试课程",
        title="M9冻结测试课程",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def test_fanya_callback_freezes_avg_understanding_score(client, session):
    """M9：泛雅回调的 understanding_score 不再更新 avg_understanding_score。"""
    teacher = _user(session, f"m9_fz_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    fanya_user_id = f"fanya-{uuid.uuid4().hex[:8]}"
    student = _user(
        session, f"m9_fz_s_{uuid.uuid4().hex[:6]}",
        fanya_account_id=fanya_user_id,
    )
    course = _course(session, teacher.id)
    enrollment = StudentEnrollment(
        student_id=student.id,
        course_id=course.id,
        avg_understanding_score=0.8,
        total_nodes_completed=2,
    )
    session.add(enrollment)
    session.commit()

    resp = client.post(
        "/api/v1/platform/callback/progress",
        json={
            "fanya_user_id": fanya_user_id,
            "fanya_course_id": course.fanya_course_id,
            "understanding_score": 0.9,
            "study_minutes": 5,
            "progress_percent": 60.0,
        },
    )
    assert resp.status_code == 200, resp.text
    row = session.exec(
        select(StudentEnrollment).where(StudentEnrollment.id == enrollment.id)
    ).first()
    # 冻结：avg_understanding_score 保持历史值；完成节点数仍递增
    assert row.avg_understanding_score == 0.8
    assert row.total_nodes_completed == 3
    assert row.total_study_minutes == 5


def test_progress_visualization_marks_understanding_deprecated(session):
    """M9：旧理解度展示标注 deprecated（顶层 + 每条分析）。"""
    from app.services.progress_service import progress_service

    teacher = _user(session, f"m9_viz_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m9_viz_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    progress = LearningProgress(
        user_id=student.id, course_id=course.id, status="in_progress",
    )
    session.add(progress)
    session.commit()
    session.refresh(progress)
    session.add(UnderstandingAnalysis(
        progress_id=progress.id,
        node_id=1,
        understanding_level=UnderstandingLevel.MEDIUM,
        understanding_score=0.5,
        analysis_reason="历史数据（旧 LLM 链路）",
    ))
    session.commit()

    result = asyncio.run(progress_service.get_progress_visualization(
        session=session, user_id=student.id, course_id=course.id,
    ))
    assert result["understanding_deprecated"] is True
    assert result["recent_analyses"][0]["deprecated"] is True
    assert result["recent_analyses"][0]["score"] == 0.5  # 历史数据仍可审计