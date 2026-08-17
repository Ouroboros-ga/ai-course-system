"""M7：每学生每课程学习轨迹持久化 测试。

覆盖：
- 幂等追加（dedup_key）；
- 倒序读取；
- 紧凑上下文只保留标量快照（剥离嵌套结构与可能含原文的长文本）；
- 保留窗口清理（90 天）；
- SessionTrajectoryPort 端口 roundtrip（供 workflow load_learning_history / record_event）。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.course_model import Course
from app.models.trajectory_model import (
    LearningTrajectoryRecord,
    TrajectoryEventType,
)
from app.models.user_model import User, UserRole
from app.services.learning_trajectory_service import (
    append_event,
    compact_context,
    get_recent,
    prune_older_than,
)


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
        fanya_course_id=f"m7-{teacher_id}-{uuid.uuid4().hex[:6]}",
        fanya_course_name="M7轨迹测试课程",
        title="M7轨迹测试课程",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def test_append_event_persists_scalar_payload(session):
    teacher = _user(session, f"m7_append_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_append_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    record = append_event(
        session,
        student_id=student.id,
        course_id=course.id,
        event_type=TrajectoryEventType.TEACHING_RESPONSE,
        concept_id="ordered-array",
        payload={
            "teaching_action": "diagnostic_question",
            "intent": "concept_question",
            "constraint_level": "balanced",
        },
        dedup_key="trace-001",
    )
    assert record is not None
    assert record.event_type == "teaching_response"
    assert record.payload["teaching_action"] == "diagnostic_question"


def test_append_event_idempotent_by_dedup_key(session):
    teacher = _user(session, f"m7_dedup_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_dedup_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    first = append_event(
        session, student_id=student.id, course_id=course.id,
        event_type="teaching_response", dedup_key="same-trace",
    )
    second = append_event(
        session, student_id=student.id, course_id=course.id,
        event_type="teaching_response", dedup_key="same-trace",
    )
    assert first is not None
    assert second is None  # 幂等：重复追加跳过
    rows = session.exec(
        select(LearningTrajectoryRecord).where(
            LearningTrajectoryRecord.dedup_key == "same-trace",
        )
    ).all()
    assert len(rows) == 1


def test_get_recent_orders_descending(session):
    teacher = _user(session, f"m7_recent_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_recent_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    for i in range(3):
        append_event(
            session, student_id=student.id, course_id=course.id,
            event_type="teaching_response", dedup_key=f"t-{i}",
            payload={"turn": i},
        )
    recent = get_recent(session, student_id=student.id, course_id=course.id)
    assert len(recent) == 3
    assert [r.payload["turn"] for r in recent] == [2, 1, 0]  # 倒序


def test_compact_context_strips_non_scalar_and_original_text(session):
    teacher = _user(session, f"m7_compact_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_compact_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    append_event(
        session, student_id=student.id, course_id=course.id,
        event_type="teaching_response", concept_id="binary-search",
        payload={
            "teaching_action": "hint_scaffolding",
            "mastery_score": 0.4,
            # 可能含原文的嵌套结构必须被剥离
            "conversation_snippet": {"role": "user", "content": "请问什么是二分查找？"},
            "evidence_list": [1, 2, 3],
        },
        dedup_key="compact-1",
    )
    rows = compact_context(get_recent(session, student_id=student.id, course_id=course.id))
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "teaching_response"
    assert row["concept_id"] == "binary-search"
    assert row["payload"]["teaching_action"] == "hint_scaffolding"
    assert row["payload"]["mastery_score"] == 0.4
    # 嵌套结构（dict/list）被过滤，不含原文
    assert "conversation_snippet" not in row["payload"]
    assert "evidence_list" not in row["payload"]
    assert "请问什么是二分查找" not in str(row)


def test_prune_older_than_removes_stale(session):
    teacher = _user(session, f"m7_prune_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_prune_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    fresh = append_event(
        session, student_id=student.id, course_id=course.id,
        event_type="teaching_response", dedup_key="fresh",
    )
    stale = append_event(
        session, student_id=student.id, course_id=course.id,
        event_type="teaching_response", dedup_key="stale",
    )
    stale.created_at = utcnow_aware() - timedelta(days=120)
    session.add(stale)
    session.commit()

    deleted = prune_older_than(session, course_id=course.id, days=90)
    assert deleted == 1
    remaining = session.exec(
        select(LearningTrajectoryRecord).where(
            LearningTrajectoryRecord.course_id == course.id,
        )
    ).all()
    assert len(remaining) == 1
    assert remaining[0].id == fresh.id


def test_session_trajectory_port_roundtrip(session):
    from app.models.database import session_factory
    from app.platform.agents.providers.cognition.trajectory import (
        SessionTrajectoryPort,
    )

    teacher = _user(session, f"m7_port_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m7_port_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)

    port = SessionTrajectoryPort(session_factory)
    asyncio.run(port.append(
        student_id=str(student.id), course_id=str(course.id),
        event_type="teaching_response", concept_id="graph",
        payload={"teaching_action": "normal_answer"},
        dedup_key="port-trace-1",
    ))
    # 幂等：同 dedup_key 第二次追加不新增
    asyncio.run(port.append(
        student_id=str(student.id), course_id=str(course.id),
        event_type="teaching_response", dedup_key="port-trace-1",
    ))
    history = asyncio.run(port.get_compact_history(
        student_id=str(student.id), course_id=str(course.id),
    ))
    assert history["status"] == "available"
    assert history["source"] == "learning_trajectory"
    assert history["count"] == 1
    assert history["records"][0]["payload"]["teaching_action"] == "normal_answer"
