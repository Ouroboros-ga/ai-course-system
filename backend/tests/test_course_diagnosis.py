"""课程学情诊断报告（服务 + API）测试（挑战杯 XH-202620）。

覆盖：薄弱节点聚合与排序、判弱门槛（样本量/置信度/表现分）、数据最小化、
API 权限与响应契约。本地 SQLite 测试库，不调用外部服务。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import Session

from app.core.security import create_access_token, get_password_hash
from app.models.cognitive_state_model import COGNITIVE_POLICY_VERSION, CognitiveState
from app.models.course_model import Course, CourseStatus
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.user_model import User, UserRole
from app.services.course_access_service import activate_student_membership, establish_course_access_baseline
from app.services.diagnosis_service import REPORT_TYPE, build_course_diagnosis


def _user(session: Session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    user = User(username=name, hashed_password=get_password_hash("test"), role=role, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _course(session: Session, owner: User, students=()) -> Course:
    course = Course(
        fanya_course_id=f"diag-{owner.id}-{datetime.now().timestamp()}",
        fanya_course_name="Diagnosis",
        title="Diagnosis",
        teacher_id=owner.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, owner.id)
    for student in students:
        activate_student_membership(session, course.id, student.id)
    session.commit()
    return course


def _outline_node(session: Session, course_id: int, title: str) -> CourseOutlineNode:
    node = CourseOutlineNode(
        outline_version_id="diag-v1",
        course_id=course_id,
        node_type=OutlineNodeType.KNOWLEDGE_POINT,
        title=title,
    )
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def _state(session: Session, student_id: int, course_id: int, node_id: int, *, perf: float, conf: float, sample: int):
    state = CognitiveState(
        student_id=student_id,
        course_id=course_id,
        node_id=node_id,
        observed_performance_score=perf,
        evidence_confidence=conf,
        mastery_score=perf,
        mastery_level="weak" if perf < 0.5 else "mastered",
        sample_size=sample,
        is_latest=True,
    )
    session.add(state)
    session.commit()
    session.refresh(state)
    return state


def _token(user: User) -> str:
    return create_access_token({"sub": str(user.id), "username": user.username, "role": user.role.value})


# ---------------------------------------------------------------------------
# 服务层
# ---------------------------------------------------------------------------


def test_diagnosis_aggregates_weak_nodes_and_orders(session: Session):
    teacher = _user(session, "diag-teacher-1")
    s1 = _user(session, "diag-s1", UserRole.STUDENT)
    s2 = _user(session, "diag-s2", UserRole.STUDENT)
    course = _course(session, teacher, students=(s1, s2))
    node_a = _outline_node(session, course.id, "二叉树遍历")
    node_b = _outline_node(session, course.id, "哈希表")

    # A：两名学生均薄弱
    _state(session, s1.id, course.id, node_a.id, perf=0.40, conf=0.90, sample=5)
    _state(session, s2.id, course.id, node_a.id, perf=0.35, conf=0.80, sample=4)
    # B：仅 s1 薄弱
    _state(session, s1.id, course.id, node_b.id, perf=0.30, conf=0.85, sample=6)
    _state(session, s2.id, course.id, node_b.id, perf=0.80, conf=0.90, sample=6)

    report = build_course_diagnosis(session, course_id=course.id)

    assert report["report_type"] == REPORT_TYPE
    assert report["policy_version"] == COGNITIVE_POLICY_VERSION
    assert report["student_count"] == 2
    assert report["weak_node_count"] == 2
    assert report["weak_nodes"][0]["node_id"] == node_a.id  # 薄弱人数多者在前
    assert report["weak_nodes"][0]["title"] == "二叉树遍历"
    assert report["weak_nodes"][0]["weak_student_count"] == 2
    assert report["weak_nodes"][0]["avg_observed_performance"] == pytest.approx(0.375, abs=0.001)
    assert report["weak_nodes"][0]["suggested_action"]
    assert report["weak_nodes"][1]["node_id"] == node_b.id
    assert report["weak_nodes"][1]["weak_student_count"] == 1
    assert any("规则基线" in c for c in report["caveats"])


def test_insufficient_sample_and_low_confidence_not_weak(session: Session):
    teacher = _user(session, "diag-teacher-2")
    s1 = _user(session, "diag-s3", UserRole.STUDENT)
    course = _course(session, teacher, students=(s1,))
    node = _outline_node(session, course.id, "快速排序")

    _state(session, s1.id, course.id, node.id, perf=0.40, conf=0.90, sample=1)  # 样本不足
    report = build_course_diagnosis(session, course_id=course.id)
    assert report["weak_node_count"] == 0

    _state(session, s1.id, course.id, node.id, perf=0.40, conf=0.40, sample=5)  # 置信度不足（覆盖 is_latest）
    report = build_course_diagnosis(session, course_id=course.id)
    assert report["weak_node_count"] == 0

    _state(session, s1.id, course.id, node.id, perf=0.85, conf=0.90, sample=5)  # 表现分达标
    report = build_course_diagnosis(session, course_id=course.id)
    assert report["weak_node_count"] == 0


def test_diagnosis_is_data_minimal(session: Session):
    teacher = _user(session, "diag-teacher-3")
    s1 = _user(session, "diag-s4", UserRole.STUDENT)
    course = _course(session, teacher, students=(s1,))
    node = _outline_node(session, course.id, "动态规划")
    _state(session, s1.id, course.id, node.id, perf=0.40, conf=0.90, sample=5)

    report = build_course_diagnosis(session, course_id=course.id)

    payload = str(report)
    assert "evidence_refs" not in payload
    assert "question_attempt" not in payload
    assert report["weak_nodes"][0]["weak_students_sample"] == [s1.id]


# ---------------------------------------------------------------------------
# API 契约
# ---------------------------------------------------------------------------


def test_diagnosis_api_requires_auth(client):
    resp = client.get("/api/v1/cognitive/course/1/diagnosis")
    assert resp.status_code in (401, 403)


def test_diagnosis_api_teacher_can_read(session: Session, client):
    teacher = _user(session, "diag-teacher-api")
    s1 = _user(session, "diag-s5", UserRole.STUDENT)
    course = _course(session, teacher, students=(s1,))
    node = _outline_node(session, course.id, "TCP 三次握手")
    _state(session, s1.id, course.id, node.id, perf=0.30, conf=0.88, sample=5)

    resp = client.get(
        f"/api/v1/cognitive/course/{course.id}/diagnosis",
        headers={"Authorization": f"Bearer {_token(teacher)}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["student_count"] == 1
    assert data["weak_node_count"] == 1
    assert data["weak_nodes"][0]["title"] == "TCP 三次握手"


def test_diagnosis_api_outsider_denied(session: Session, client):
    teacher = _user(session, "diag-teacher-owner")
    outsider = _user(session, "diag-teacher-outsider")
    course = _course(session, teacher)

    resp = client.get(
        f"/api/v1/cognitive/course/{course.id}/diagnosis",
        headers={"Authorization": f"Bearer {_token(outsider)}"},
    )

    assert resp.status_code == 403
