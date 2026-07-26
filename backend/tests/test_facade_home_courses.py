"""阶段1 工作首页与课程列表 facade 端到端测试。

覆盖路线图 §4 阶段1 验收与 PageDesign前端API契约规划.md §3.1/§3.2：
- HomeViewModel 聚合（继续学习、我建设的、待审核、系统任务、active_mode）
- 课程列表读模型（learning/building/hall 三视图与游标分页）
- 跨课程/跨用户严格隔离
- hall 视图降级：草稿不进入大厅
- 非法参数返回 422 VALIDATION_FAILED
- 未登录返回 401 AUTH_REQUIRED

四类必备测试：成功、权限拒绝、跨课程拒绝、降级。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.graph_production_model import GraphNodeReview
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.task_model import TaskRecord
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)


FACADE = "/api/v1/facade"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.STUDENT) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _course(
    session,
    teacher_id: int,
    *,
    title: str = "Facade Course",
    status: CourseStatus = CourseStatus.PUBLISHED,
    invite_code: str | None = None,
) -> Course:
    c = Course(
        fanya_course_id=f"fac-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name=title,
        title=title,
        teacher_id=teacher_id,
        status=status,
        invite_code=invite_code,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    # baseline 内部 add 但未 commit；请求 session 与测试 session 不同，必须 commit
    # 让 owner membership 与 capability 对路由层可见。
    session.commit()
    return c


def _enroll_student(session, course_id: int, student_id: int, *, progress: float = 0.0) -> None:
    """建立学生选课关系 + CourseMembership（Course Access v1 是唯一授权来源）。"""
    enr = StudentEnrollment(
        student_id=student_id,
        course_id=course_id,
        overall_progress=progress,
        last_study_time=datetime.utcnow() - timedelta(minutes=10),
        is_active=True,
    )
    session.add(enr)
    activate_student_membership(session, course_id, student_id)
    session.commit()


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question(
    session,
    course_id: int,
    *,
    status: QuestionStatus = QuestionStatus.AUTO_ACCEPTED,
    text: str = "待审核题目",
) -> QuestionBankItem:
    q = QuestionBankItem(
        question_text=text,
        answer="参考答案",
        question_type=QuestionType.SHORT_ANSWER,
        difficulty=QuestionDifficulty.MEDIUM,
        course_id=course_id,
        status=status,
        is_latest=True,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def _graph_review(session, course_id: int, *, target_id: str = "node-1") -> GraphNodeReview:
    r = GraphNodeReview(
        course_id=course_id,
        target_id=target_id,
        target_type="node",
        decision="proposed",
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def _failed_task(
    session,
    owner_user_id: int,
    *,
    course_id: int | None = None,
    task_type: str = "self_check_noop",
) -> TaskRecord:
    t = TaskRecord(
        task_id=f"task_{datetime.utcnow().timestamp()}_{owner_user_id}",
        task_type=task_type,
        owner_user_id=owner_user_id,
        course_id=course_id,
        status="failed",
        progress=0,
        acknowledged=False,
        error_code="DEPENDENCY_UNAVAILABLE",
        error_message="测试失败任务",
        retryable=True,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


# ---------------------------------------------------------------------------
# 1. 成功路径：GET /facade/home 推导 active_mode 与卡片聚合
# ---------------------------------------------------------------------------


def test_home_returns_student_mode_with_continue_learning(client, session):
    """学生登录后调用 /facade/home，返回 active_mode=student，continue_learning 包含已加入课程。"""
    student = _user(session, "facade_home_student", UserRole.STUDENT)
    course = _course(session, teacher_id=_user(session, "facade_home_teacher", UserRole.TEACHER).id, title="学生首页课程")
    _enroll_student(session, course.id, student.id, progress=42.0)

    resp = client.get(FACADE + "/home", headers=_auth(_token(student)))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]

    # active_mode 推导
    assert data["active_mode"] == "student"
    # continue_learning 包含该课程
    cl = data["continue_learning"]
    assert any(c["course_id"] == course.id for c in cl)
    card = next(c for c in cl if c["course_id"] == course.id)
    assert card["role"] == "student"
    assert card["progress"] == 42.0
    assert card["main_action"] == "continue_learning"
    # 学生视图下 building_courses 与 pending_reviews 为空
    assert data["building_courses"] == []
    assert data["pending_reviews"] == []
    # capabilities 必须存在且为成熟度映射（与 SYSTEM_CAPABILITY_MATURITY 对齐）
    assert "course_learning" in data["capabilities"]
    assert "knowledge_graph" in data["capabilities"]


def test_home_returns_teacher_mode_with_building_courses(client, session):
    """教师登录后调用 /facade/home，返回 active_mode=teacher，building_courses 包含其建设的课程。"""
    teacher = _user(session, "facade_home_teacher_main", UserRole.TEACHER)
    course = _course(session, teacher.id, title="教师建设课程")

    resp = client.get(FACADE + "/home", headers=_auth(_token(teacher)))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["active_mode"] == "teacher"
    bc = data["building_courses"]
    assert any(c["course_id"] == course.id for c in bc)
    card = next(c for c in bc if c["course_id"] == course.id)
    assert card["role"] == "owner"
    assert card["main_action"] == "continue_building"
    # teacher 视图下 continue_learning 为空
    assert data["continue_learning"] == []


def test_home_mode_param_forces_student_view_for_dual_role(client, session):
    """同时具备学生和教师成员关系的用户，mode=teacher 强制以教师视角呈现。"""
    user = _user(session, "facade_dual_user", UserRole.TEACHER)
    # 作为教师的课程
    teacher_course = _course(session, user.id, title="双角色教师课程")
    # 作为学生的课程（需另一位教师创建）
    other_teacher = _user(session, "facade_dual_other_teacher", UserRole.TEACHER)
    student_course = _course(session, other_teacher.id, title="双角色学生课程")
    _enroll_student(session, student_course.id, user.id, progress=10.0)

    # 不传 mode -> mixed
    resp = client.get(FACADE + "/home", headers=_auth(_token(user)))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["active_mode"] == "mixed"
    assert any(c["course_id"] == student_course.id for c in data["continue_learning"])
    assert any(c["course_id"] == teacher_course.id for c in data["building_courses"])

    # mode=teacher -> 只展示 building
    resp_t = client.get(FACADE + "/home?mode=teacher", headers=_auth(_token(user)))
    assert resp_t.status_code == 200
    data_t = resp_t.json()["data"]
    assert data_t["active_mode"] == "teacher"
    assert data_t["continue_learning"] == []
    assert any(c["course_id"] == teacher_course.id for c in data_t["building_courses"])


def test_home_aggregates_pending_reviews_and_system_tasks(client, session):
    """教师视图下 pending_reviews 包含题目审核、图谱审核、失败任务；system_tasks 包含失败任务摘要。"""
    teacher = _user(session, "facade_home_pending_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id, title="待审核课程")
    _question(session, course.id, status=QuestionStatus.AUTO_ACCEPTED, text="阶段1题目")
    _graph_review(session, course.id, target_id="kg-node-1")
    _failed_task(session, teacher.id, course_id=course.id, task_type="self_check_noop")

    resp = client.get(FACADE + "/home", headers=_auth(_token(teacher)))
    assert resp.status_code == 200
    data = resp.json()["data"]

    kinds = {p["kind"] for p in data["pending_reviews"]}
    assert "question_review" in kinds
    assert "graph_review" in kinds
    assert "failed_task" in kinds
    # 所有 pending 项都归属教师拥有的课程
    for p in data["pending_reviews"]:
        assert p["course_id"] == course.id

    # 系统任务摘要包含失败任务
    assert any(t["task_type"] == "self_check_noop" and t["status"] == "failed"
               for t in data["system_tasks"])


# ---------------------------------------------------------------------------
# 2. 权限拒绝：未登录与非法参数
# ---------------------------------------------------------------------------


def test_home_requires_authentication(client):
    """未登录调用 /facade/home 返回 401。"""
    resp = client.get(FACADE + "/home")
    assert resp.status_code == 401
    body = resp.json()
    # 契约要求统一响应体；401 由 security 抛 HTTPException(detail=str)，data 可能为 null
    assert body["code"] == 401


def test_courses_requires_authentication(client):
    """未登录调用 /facade/courses 返回 401。"""
    resp = client.get(FACADE + "/courses?view=learning")
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 401


def test_home_invalid_mode_returns_422(client, session):
    """非法 mode 参数返回 422 VALIDATION_FAILED。"""
    user = _user(session, "facade_invalid_mode_user", UserRole.STUDENT)
    resp = client.get(FACADE + "/home?mode=admin", headers=_auth(_token(user)))
    assert resp.status_code == 422
    err = resp.json()["data"]
    assert err["error_code"] == "VALIDATION_FAILED"


def test_courses_invalid_view_returns_422(client, session):
    """非法 view 参数返回 422 VALIDATION_FAILED。"""
    user = _user(session, "facade_invalid_view_user", UserRole.STUDENT)
    resp = client.get(FACADE + "/courses?view=secret", headers=_auth(_token(user)))
    assert resp.status_code == 422
    err = resp.json()["data"]
    assert err["error_code"] == "VALIDATION_FAILED"


def test_courses_page_size_out_of_range_returns_422(client, session):
    """page_size 超过上限返回 422 VALIDATION_FAILED。"""
    user = _user(session, "facade_page_size_user", UserRole.STUDENT)
    resp = client.get(FACADE + "/courses?view=learning&page_size=999", headers=_auth(_token(user)))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 3. 跨课程/跨用户隔离
# ---------------------------------------------------------------------------


def test_learning_view_isolates_by_user(client, session):
    """view=learning 只返回当前用户作为学生加入的课程，不泄露他人课程。"""
    student_a = _user(session, "facade_iso_student_a", UserRole.STUDENT)
    student_b = _user(session, "facade_iso_student_b", UserRole.STUDENT)
    teacher = _user(session, "facade_iso_teacher", UserRole.TEACHER)
    course_a = _course(session, teacher.id, title="课程 A（学生 A 加入）")
    course_b = _course(session, teacher.id, title="课程 B（学生 B 加入）")
    _enroll_student(session, course_a.id, student_a.id, progress=10.0)
    _enroll_student(session, course_b.id, student_b.id, progress=20.0)

    resp_a = client.get(FACADE + "/courses?view=learning", headers=_auth(_token(student_a)))
    assert resp_a.status_code == 200
    items_a = resp_a.json()["data"]["items"]
    course_ids_a = {c["course_id"] for c in items_a}
    assert course_a.id in course_ids_a
    assert course_b.id not in course_ids_a

    resp_b = client.get(FACADE + "/courses?view=learning", headers=_auth(_token(student_b)))
    items_b = resp_b.json()["data"]["items"]
    course_ids_b = {c["course_id"] for c in items_b}
    assert course_b.id in course_ids_b
    assert course_a.id not in course_ids_b


def test_building_view_isolates_by_user(client, session):
    """view=building 只返回当前用户作为教师/owner/TA 的课程。"""
    teacher_a = _user(session, "facade_build_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "facade_build_teacher_b", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="教师 A 的课程")
    course_b = _course(session, teacher_b.id, title="教师 B 的课程")

    resp_a = client.get(FACADE + "/courses?view=building", headers=_auth(_token(teacher_a)))
    assert resp_a.status_code == 200
    items_a = resp_a.json()["data"]["items"]
    course_ids_a = {c["course_id"] for c in items_a}
    assert course_a.id in course_ids_a
    assert course_b.id not in course_ids_a


def test_home_system_tasks_isolated_by_owner(client, session):
    """system_tasks 仅返回当前用户拥有的任务，不泄露他人任务。"""
    user_a = _user(session, "facade_task_user_a", UserRole.TEACHER)
    user_b = _user(session, "facade_task_user_b", UserRole.TEACHER)
    _course(session, user_a.id, title="任务隔离课程 A")
    _course(session, user_b.id, title="任务隔离课程 B")
    _failed_task(session, user_a.id, task_type="self_check_noop")
    _failed_task(session, user_b.id, task_type="self_check_noop")

    resp_a = client.get(FACADE + "/home", headers=_auth(_token(user_a)))
    assert resp_a.status_code == 200
    # 用户 A 的 system_tasks 至少 1 条，且都是其本人任务
    tasks_a = resp_a.json()["data"]["system_tasks"]
    assert len(tasks_a) >= 1
    for t in tasks_a:
        # owner_user_id 不直接暴露，但 task_id 应与 user_a 创建的任务匹配
        # 通过查询 user_b 的接口验证不出现相同 task_id
        pass

    resp_b = client.get(FACADE + "/home", headers=_auth(_token(user_b)))
    tasks_b = resp_b.json()["data"]["system_tasks"]
    a_task_ids = {t["task_id"] for t in tasks_a}
    b_task_ids = {t["task_id"] for t in tasks_b}
    assert a_task_ids.isdisjoint(b_task_ids)


def test_pending_reviews_isolated_by_course_membership(client, session):
    """教师只能看到自己课程里的待审核项。"""
    teacher_a = _user(session, "facade_pending_teacher_a", UserRole.TEACHER)
    teacher_b = _user(session, "facade_pending_teacher_b", UserRole.TEACHER)
    course_a = _course(session, teacher_a.id, title="待审核课程 A")
    course_b = _course(session, teacher_b.id, title="待审核课程 B")
    _question(session, course_a.id, text="课程 A 题目")
    _question(session, course_b.id, text="课程 B 题目")

    resp_a = client.get(FACADE + "/home", headers=_auth(_token(teacher_a)))
    pending_a = resp_a.json()["data"]["pending_reviews"]
    for p in pending_a:
        assert p["course_id"] == course_a.id
    # 课程 B 的题目不应出现在教师 A 的待审核列表
    assert not any(p["course_id"] == course_b.id for p in pending_a)


# ---------------------------------------------------------------------------
# 4. 降级：hall 视图只展示 published；草稿/已关闭不进入大厅
# ---------------------------------------------------------------------------


def test_hall_view_only_returns_published_courses(client, session):
    """hall 视图只返回 status=published 的课程；草稿、已关闭、已归档不进入大厅。"""
    teacher = _user(session, "facade_hall_teacher", UserRole.TEACHER)
    published = _course(session, teacher.id, title="已发布课程", status=CourseStatus.PUBLISHED)
    draft = _course(session, teacher.id, title="草稿课程", status=CourseStatus.DRAFT)
    closed = _course(session, teacher.id, title="已关闭课程", status=CourseStatus.CLOSED)
    archived = _course(session, teacher.id, title="已归档课程", status=CourseStatus.ARCHIVED)

    # 由另一普通学生调用 hall 视图
    student = _user(session, "facade_hall_student", UserRole.STUDENT)
    resp = client.get(FACADE + "/courses?view=hall", headers=_auth(_token(student)))
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    course_ids = {c["course_id"] for c in items}
    assert published.id in course_ids
    assert draft.id not in course_ids
    assert closed.id not in course_ids
    assert archived.id not in course_ids
    # hall 视图的 view 字段标识
    assert resp.json()["data"]["view"] == "hall"


def test_hall_view_marks_joined_courses(client, session):
    """hall 视图对已加入课程标记 joined=True。"""
    teacher = _user(session, "facade_hall_joined_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id, title="Hall 已加入课程", status=CourseStatus.PUBLISHED)
    student = _user(session, "facade_hall_joined_student", UserRole.STUDENT)
    _enroll_student(session, course.id, student.id, progress=5.0)

    resp = client.get(FACADE + "/courses?view=hall", headers=_auth(_token(student)))
    items = resp.json()["data"]["items"]
    card = next(c for c in items if c["course_id"] == course.id)
    assert card["access"]["joined"] is True
    assert card["role"] == "student"


def test_learning_view_excludes_draft_courses(client, session):
    """learning 视图不返回 draft 状态课程（学生未发布课程不可学习）。"""
    teacher = _user(session, "facade_learning_draft_teacher", UserRole.TEACHER)
    student = _user(session, "facade_learning_draft_student", UserRole.STUDENT)
    published = _course(session, teacher.id, title="可学习课程", status=CourseStatus.PUBLISHED)
    draft = _course(session, teacher.id, title="未发布课程", status=CourseStatus.DRAFT)
    _enroll_student(session, published.id, student.id, progress=0.0)
    _enroll_student(session, draft.id, student.id, progress=0.0)

    resp = client.get(FACADE + "/courses?view=learning", headers=_auth(_token(student)))
    items = resp.json()["data"]["items"]
    course_ids = {c["course_id"] for c in items}
    assert published.id in course_ids
    assert draft.id not in course_ids


# ---------------------------------------------------------------------------
# 5. 游标分页与课程卡片契约
# ---------------------------------------------------------------------------


def test_learning_view_cursor_pagination(client, session):
    """page_size=1 + cursor 翻页，next_cursor 不为空且能取到下一页。"""
    teacher = _user(session, "facade_pagination_teacher", UserRole.TEACHER)
    student = _user(session, "facade_pagination_student", UserRole.STUDENT)
    # 创建 3 个已发布课程并让学生加入
    for i in range(3):
        c = _course(session, teacher.id, title=f"分页课程 {i}", status=CourseStatus.PUBLISHED)
        _enroll_student(session, c.id, student.id, progress=float(i) * 10)

    # 第一页
    resp1 = client.get(
        FACADE + "/courses?view=learning&page_size=1",
        headers=_auth(_token(student)),
    )
    assert resp1.status_code == 200
    page1 = resp1.json()["data"]
    assert len(page1["items"]) == 1
    assert page1["has_next"] is True
    assert page1["next_cursor"]
    assert page1["view"] == "learning"

    # 第二页使用 next_cursor
    resp2 = client.get(
        FACADE + f"/courses?view=learning&page_size=1&cursor={page1['next_cursor']}",
        headers=_auth(_token(student)),
    )
    assert resp2.status_code == 200
    page2 = resp2.json()["data"]
    assert len(page2["items"]) == 1
    # 两页 course_id 不同
    assert page1["items"][0]["course_id"] != page2["items"][0]["course_id"]


def test_course_card_contract_fields(client, session):
    """CourseCard 必须包含 course_id/title/cover/status/role/access/capabilities 字段。"""
    teacher = _user(session, "facade_contract_teacher", UserRole.TEACHER)
    student = _user(session, "facade_contract_student", UserRole.STUDENT)
    course = _course(session, teacher.id, title="契约校验课程", status=CourseStatus.PUBLISHED)
    _enroll_student(session, course.id, student.id, progress=15.0)

    resp = client.get(FACADE + "/courses?view=learning", headers=_auth(_token(student)))
    items = resp.json()["data"]["items"]
    card = next(c for c in items if c["course_id"] == course.id)
    # 必填字段
    for field in ("course_id", "title", "cover", "status", "role", "access", "capabilities"):
        assert field in card, f"CourseCard 缺少字段 {field}"
    # 学生视图必须带 progress
    assert "progress" in card
    assert card["progress"]["overall_progress"] == 15.0


def test_building_view_includes_build_status(client, session):
    """building 视图的 CourseCard 必须包含 build_status（pending_review_count 等）。"""
    teacher = _user(session, "facade_build_status_teacher", UserRole.TEACHER)
    course = _course(session, teacher.id, title="建设状态课程")
    _question(session, course.id, text="建设视图题目")

    resp = client.get(FACADE + "/courses?view=building", headers=_auth(_token(teacher)))
    items = resp.json()["data"]["items"]
    card = next(c for c in items if c["course_id"] == course.id)
    assert "build_status" in card
    assert card["build_status"]["pending_review_count"] >= 1


# ---------------------------------------------------------------------------
# 6. 非法 cursor 与边界
# ---------------------------------------------------------------------------


def test_invalid_cursor_returns_422(client, session):
    """非法 cursor 格式返回 422 VALIDATION_FAILED。"""
    student = _user(session, "facade_cursor_user", UserRole.STUDENT)
    resp = client.get(
        FACADE + "/courses?view=learning&cursor=not-a-valid-cursor",
        headers=_auth(_token(student)),
    )
    assert resp.status_code == 422
    err = resp.json()["data"]
    assert err["error_code"] == "VALIDATION_FAILED"


def test_empty_home_returns_zero_arrays(client, session):
    """无任何成员关系的用户调用 /facade/home，返回 active_mode=student 与空数组。"""
    user = _user(session, "facade_empty_user", UserRole.STUDENT)
    resp = client.get(FACADE + "/home", headers=_auth(_token(user)))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["active_mode"] == "student"
    assert data["continue_learning"] == []
    assert data["building_courses"] == []
    assert data["pending_reviews"] == []
    assert data["system_tasks"] == []
