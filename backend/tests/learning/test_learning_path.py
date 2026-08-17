"""M8：学习路径规划 测试。

覆盖：
- 课件前序推荐（当前节点之后的节点序列，position 正确）；
- 薄弱优先（薄弱节点排前面）；
- 无 active release 返回空；
- 当前节点不在课件前序中时从头推荐；
- /player/progress/save 响应携带 next_nodes 数组。
"""
from __future__ import annotations

import uuid

from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_model import Course
from app.models.course_outline_model import (
    CourseOutlineNode,
    CourseOutlineVersion,
    OutlineLifecycleStatus,
    OutlineNodeType,
)
from app.models.user_model import User, UserRole
from app.services.learning_path_service import plan_next_nodes


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
        fanya_course_id=f"m8-{teacher_id}-{uuid.uuid4().hex[:6]}",
        fanya_course_name="M8路径测试课程",
        title="M8路径测试课程",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _publish_outline(session, course, *, order):
    """order = [(knowledge_graph_node_id, order_index), ...]"""
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


def _compute(session, student_id, course_id, node_id):
    from app.services.cognitive_service import compute_cognitive_state

    compute_cognitive_state(session, student_id, course_id, node_id=node_id)


def test_plan_next_nodes_returns_following_sequence(session):
    teacher = _user(session, f"m8_seq_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_seq_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    _publish_outline(session, course, order=[("n1", 0), ("n2", 1), ("n3", 2), ("n4", 3)])

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="n1", max_next=3,
    )
    assert [r["knowledge_graph_node_id"] for r in rows] == ["n2", "n3", "n4"]
    assert [r["position"] for r in rows] == [1, 2, 3]
    assert all(r["is_locked"] is False for r in rows)
    assert all(r["outline_node_id"] for r in rows)


def test_plan_next_nodes_weak_first(session):
    teacher = _user(session, f"m8_weak_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_weak_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    # 数字 key：无 CourseKnowledgeNode identity 行时走 isdigit 兼容回退
    _publish_outline(session, course, order=[("1", 0), ("2", 1), ("3", 2)])

    # 节点 3 薄弱（5 次全错），节点 2 良好（5 次全对）
    _attempts(session, student.id, course.id, 3, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 2, correct=5, wrong=0)
    _compute(session, student.id, course.id, 3)
    _compute(session, student.id, course.id, 2)

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="1", max_next=3,
    )
    # 薄弱优先：节点 3 排到节点 2 前面
    assert [r["knowledge_graph_node_id"] for r in rows] == ["3", "2"]
    assert rows[0]["is_weak"] is True
    assert rows[1]["is_weak"] is False


def test_plan_next_nodes_no_release_returns_empty(session):
    teacher = _user(session, f"m8_empty_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_empty_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)  # 无 release

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="n1",
    )
    assert rows == []


def test_plan_next_nodes_current_not_in_outline_starts_from_head(session):
    teacher = _user(session, f"m8_head_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_head_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    _publish_outline(session, course, order=[("n1", 0), ("n2", 1), ("n3", 2)])

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="unknown-node", max_next=2,
    )
    assert [r["knowledge_graph_node_id"] for r in rows] == ["n1", "n2"]


def test_plan_next_nodes_includes_legacy_weak_before_current(session):
    """M8 增强：当前节点之前的薄弱节点（历史遗留）纳入推荐并排最前。"""
    teacher = _user(session, f"m8_legacy_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_legacy_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    _publish_outline(session, course, order=[("1", 0), ("2", 1), ("3", 2), ("4", 3)])

    # 节点 2（当前节点 3 之前）薄弱；节点 4（之后）良好
    _attempts(session, student.id, course.id, 2, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 4, correct=5, wrong=0)
    _compute(session, student.id, course.id, 2)
    _compute(session, student.id, course.id, 4)

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="3", max_next=3,
    )
    # 历史遗留薄弱节点 2 排最前，随后是后续节点 4
    assert [r["knowledge_graph_node_id"] for r in rows] == ["2", "4"]
    assert rows[0]["is_weak"] is True
    assert rows[0]["position"] == 1  # 保留前序位置（供展示层定位）


def test_plan_next_nodes_legacy_weak_limited_by_max_next(session):
    """M8 增强：历史遗留薄弱节点最多取 max_next 个（离当前最近的优先）。"""
    teacher = _user(session, f"m8_legacy2_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = _user(session, f"m8_legacy2_s_{uuid.uuid4().hex[:6]}")
    course = _course(session, teacher.id)
    _publish_outline(session, course, order=[("1", 0), ("2", 1), ("3", 2), ("4", 3)])

    # 节点 1、2 都薄弱（历史遗留），当前节点 3
    _attempts(session, student.id, course.id, 1, correct=0, wrong=5)
    _attempts(session, student.id, course.id, 2, correct=0, wrong=5)
    _compute(session, student.id, course.id, 1)
    _compute(session, student.id, course.id, 2)

    rows = plan_next_nodes(
        session, student_id=student.id, course_id=course.id,
        current_node_key="3", max_next=2,
    )
    # 薄弱优先：两个遗留薄弱节点占满名额（节点 1、2），后续节点 4 被截断
    assert [r["knowledge_graph_node_id"] for r in rows] == ["1", "2"]
    assert all(r["is_weak"] for r in rows)


def test_progress_save_response_includes_next_nodes(client, session):
    from test_cognitive_recommendation import _setup_course, _token
    from test_cognitive_recommendation import _user as cr_user

    teacher = cr_user(session, f"m8_save_t_{uuid.uuid4().hex[:6]}", UserRole.TEACHER)
    student = cr_user(session, f"m8_save_s_{uuid.uuid4().hex[:6]}")
    course = _setup_course(session, teacher, student)
    _publish_outline(session, course, order=[("n1", 0), ("n2", 1), ("n3", 2)])

    resp = client.post(
        "/api/v1/player/progress/save",
        json={
            "course_id": course.id,
            "current_node_id": None,
            "current_timestamp": 10.0,
            "current_page": 1,
            "completed_nodes": [],
            "time_spent_delta": 0,
        },
        headers={"Authorization": f"Bearer {_token(student)}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "next_nodes" in data
    # 无当前节点 -> 从头推荐
    assert [n["knowledge_graph_node_id"] for n in data["next_nodes"]] == ["n1", "n2", "n3"]