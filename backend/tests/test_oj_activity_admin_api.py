"""PR-08 端到端：OJ Activity 管理 API（教师侧）。

覆盖：创建 / 列表 / 详情 / PATCH 更新 / 发布 / 归档 / 挂题 / 移题 / 可见范围、
权限拒绝（学生不可 configure）、未实现类型显式拒绝、跨课程 404。

前端契约注意：路由挂在**既有前缀** `/api/v1/experiments` 下（ADR ⑥ 不引入 `/oj`）；
权限全部 `experiment.configure`。学生可见性接口属 PR-12，本文件不含。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus
from app.models.experiment_activity_model import ExperimentActivity
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentVersion,
)
from app.services.course_access_service import (
    establish_course_access_baseline,
    require_course_permission,
)


ACTIVITIES = "/api/v1/experiments"
_T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _token(user) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def pr08_course(session, teacher_user):
    course = Course(
        fanya_course_id=f"act08-{uuid.uuid4().hex[:8]}",
        fanya_course_name="Activity Admin Course",
        title="Activity Admin Course",
        teacher_id=teacher_user.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.commit()
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


def _definition_with_version(session, course, teacher, *, title="冒泡排序") -> ExperimentDefinition:
    definition = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id,
        title=title,
        created_by=teacher.id,
    )
    session.add(definition)
    session.flush()
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=definition.experiment_id,
        course_id=course.id,
        created_by=teacher.id,
        is_locked=True,
        is_active=True,
    )
    session.add(version)
    session.flush()
    definition.default_version_id = version.version_id
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return definition


def _create_activity(client, token, course_id: int, **overrides) -> dict:
    payload = {"title": "第一次作业"}
    payload.update(overrides)
    resp = client.post(
        f"{ACTIVITIES}/course/{course_id}/activities",
        json=payload, headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _publish(client, token, course_id: int, activity_id: str) -> dict:
    resp = client.post(
        f"{ACTIVITIES}/course/{course_id}/activities/{activity_id}/publish",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


class TestActivityCrud:
    def test_create_defaults(self, client, teacher_user, pr08_course):
        token = _token(teacher_user)
        data = _create_activity(client, token, pr08_course.id)
        assert data["activity_id"].startswith("act_")
        assert data["status"] == "draft"
        assert data["type"] == "homework"
        assert data["scoring_mode"] == "sum"

    def test_create_rejects_unimplemented_type(self, client, teacher_user, pr08_course):
        """contest 合法但未实现 → 422 显式拒绝，绝不静默当 homework。"""
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities",
            json={"title": "比赛", "type": "contest"},
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 422, resp.text

    def test_list_contains_created(self, client, session, teacher_user, pr08_course):
        token = _token(teacher_user)
        created = _create_activity(client, token, pr08_course.id, title="作业甲")
        resp = client.get(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert any(i["activity_id"] == created["activity_id"] for i in items)

    def test_detail_carries_problems_and_scopes(self, client, session, teacher_user, pr08_course):
        token = _token(teacher_user)
        definition = _definition_with_version(session, pr08_course, teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
            json={"problem_definition_id": definition.experiment_id},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 201

        client.put(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/scopes",
            json={"scopes": [{"scope_type": "course", "scope_id": pr08_course.id}]},
            headers=_auth(token),
        )

        detail = client.get(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}",
            headers=_auth(token),
        )
        data = detail.json()["data"]
        assert len(data["problems"]) == 1
        assert data["problems"][0]["problem_version_id"] == definition.default_version_id
        assert data["scopes"] == [{"scope_type": "course", "scope_id": pr08_course.id}]

    def test_patch_updates_and_preserves_unspecified(self, client, teacher_user, pr08_course):
        """PATCH 语义：不传的字段不动。"""
        token = _token(teacher_user)
        created = _create_activity(
            client, token, pr08_course.id,
            title="原题",
            start_at=(_T0).isoformat(),
            end_at=(_T0 + timedelta(hours=1)).isoformat(),
        )
        resp = client.put(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}",
            json={"title": "改了标题"},
            headers=_auth(token),
        )
        data = resp.json()["data"]
        assert data["title"] == "改了标题"
        assert data["start_at"] is not None and data["end_at"] is not None

    def test_clear_window(self, client, teacher_user, pr08_course):
        token = _token(teacher_user)
        created = _create_activity(
            client, token, pr08_course.id,
            start_at=_T0.isoformat(),
            end_at=(_T0 + timedelta(hours=1)).isoformat(),
        )
        resp = client.put(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}",
            json={"clear_window": True},
            headers=_auth(token),
        )
        data = resp.json()["data"]
        assert data["start_at"] is None and data["end_at"] is None

    def test_inverted_window_rejected(self, client, teacher_user, pr08_course):
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities",
            json={
                "title": "倒置",
                "start_at": (_T0 + timedelta(hours=2)).isoformat(),
                "end_at": _T0.isoformat(),
            },
            headers=_auth(_token(teacher_user)),
        )
        assert resp.status_code == 422, resp.text


class TestPublishFlow:
    def test_publish_requires_problem(self, client, teacher_user, pr08_course):
        token = _token(teacher_user)
        created = _create_activity(client, token, pr08_course.id, title="空活动")
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/publish",
            headers=_auth(token),
        )
        assert resp.status_code == 409, resp.text

    def test_publish_then_archive(self, client, session, teacher_user, pr08_course):
        token = _token(teacher_user)
        definition = _definition_with_version(session, pr08_course, teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
            json={"problem_definition_id": definition.experiment_id},
            headers=_auth(token),
        )
        published = _publish(client, token, pr08_course.id, created["activity_id"])
        assert published["status"] == "published" and published["published_at"]

        # 发布后不可挂题（题目集合冻结）
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
            json={"problem_definition_id": definition.experiment_id, "ordinal": 2},
            headers=_auth(token),
        )
        assert resp.status_code == 409, resp.text

        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/archive",
            headers=_auth(token),
        )
        assert resp.json()["data"]["status"] == "archived"


class TestProblemEndpoints:
    def test_add_and_remove(self, client, session, teacher_user, pr08_course):
        token = _token(teacher_user)
        definition = _definition_with_version(session, pr08_course, teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
            json={"problem_definition_id": definition.experiment_id, "max_score": 5.0},
            headers=_auth(token),
        )
        problem = resp.json()["data"]
        assert problem["ordinal"] == 1 and problem["max_score"] == 5.0

        resp = client.delete(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems/1",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text

        detail = client.get(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}",
            headers=_auth(token),
        )
        assert detail.json()["data"]["problems"] == []

    def test_unknown_definition_404(self, client, teacher_user, pr08_course):
        token = _token(teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
            json={"problem_definition_id": "exp_missing"},
            headers=_auth(token),
        )
        assert resp.status_code == 404, resp.text

    def test_duplicate_attach_rejected(self, client, session, teacher_user, pr08_course):
        token = _token(teacher_user)
        definition = _definition_with_version(session, pr08_course, teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        for _ in range(2):
            resp = client.post(
                f"{ACTIVITIES}/course/{pr08_course.id}/activities/{created['activity_id']}/problems",
                json={"problem_definition_id": definition.experiment_id},
                headers=_auth(token),
            )
        assert resp.status_code == 409, resp.text


class TestPermissionsAndIsolation:
    def test_student_cannot_create(self, client, session, teacher_user, student_user, pr08_course):
        from app.models.course_model import StudentEnrollment

        session.add(StudentEnrollment(
            student_id=student_user.id, course_id=pr08_course.id,
            overall_progress=0.0, is_active=True,
        ))
        session.commit()
        resp = client.post(
            f"{ACTIVITIES}/course/{pr08_course.id}/activities",
            json={"title": "学生建的"},
            headers=_auth(_token(student_user)),
        )
        assert resp.status_code == 403, resp.text

    def test_cross_course_activity_is_404(self, client, session, teacher_user, pr08_course):
        other = Course(
            fanya_course_id=f"act08b-{uuid.uuid4().hex[:8]}",
            fanya_course_name="Other", title="Other",
            teacher_id=teacher_user.id, status=CourseStatus.PUBLISHED,
        )
        session.add(other)
        session.commit()
        session.refresh(other)
        establish_course_access_baseline(session, other.id, teacher_user.id)
        cap = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == other.id)
        ).one()
        cap.experiment = True
        cap.coding_sandbox = True
        session.add(cap)
        session.commit()

        token = _token(teacher_user)
        created = _create_activity(client, token, pr08_course.id)
        # 教师对 other 课程**有** configure 权限 → 走到 service 的归属 404。
        # 这是比 403 更锐利的隔离断言：有权访问 B，也看不到 A 的活动。
        resp = client.get(
            f"{ACTIVITIES}/course/{other.id}/activities/{created['activity_id']}",
            headers=_auth(token),
        )
        assert resp.status_code == 404, resp.text
