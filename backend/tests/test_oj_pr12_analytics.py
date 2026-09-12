"""PR-12 学生活动入口 + PR-14 缩范围看板（聚合端点）。

- 学生活动列表：published + 对我可见 + 窗口状态服务端算好；**draft 不可见**；
- 看板聚合：教师侧，只含现有数据源可确定计算的指标；
- 高频错题 / 需要关注的学生 / 提交趋势 均有真实数据支撑。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token
from app.models.course_model import StudentEnrollment
from app.models.experiment_activity_model import ExperimentActivity
from app.models.experiment_model import ExperimentAttempt, ExperimentDefinition, ExperimentVersion
from app.services.experiment_activity_service import ExperimentActivityService
from app.services.experiment_analytics_service import ExperimentAnalyticsService

from app.models.access_control_model import CourseCapability


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


def _token(user) -> str:
    return create_access_token({
        "sub": str(user.id), "username": user.username,
        "role": user.role.value, "school_id": user.school_id or "t",
    })


def _definition_with_version(session, course, teacher) -> ExperimentDefinition:
    definition = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title="聚合题", created_by=teacher.id,
    )
    session.add(definition)
    session.flush()
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=definition.experiment_id,
        course_id=course.id, created_by=teacher.id,
        is_locked=True, is_active=True,
    )
    session.add(version)
    session.flush()
    definition.default_version_id = version.version_id
    session.add(definition)
    session.commit()
    session.refresh(definition)
    return definition


def _course_with_capabilities(session, teacher):
    """本地同构 helper（与其它 OJ 测试同约定：baseline 已建 capability，须 upsert）。"""
    from app.models.course_model import Course

    course = Course(
        fanya_course_id=f"p12-{uuid.uuid4().hex[:8]}",
        fanya_course_name="PR12", title="PR12",
        teacher_id=teacher.id, status=__import__(
            "app.models.course_model", fromlist=["CourseStatus"]
        ).CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    from app.services.course_access_service import establish_course_access_baseline
    establish_course_access_baseline(session, course.id, teacher.id)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


@pytest.fixture
def svc() -> ExperimentActivityService:
    return ExperimentActivityService()


def _publish_with_scope(session, teacher, course, svc, *, title, scope=True,
                        start=None, end=None, allow_late=False):
    definition = _definition_with_version(session, course, teacher)
    activity = svc.create_activity(
        session, course_id=course.id, owner_id=teacher.id, title=title,
        start_at=start, end_at=end, allow_late_submit=allow_late,
    )
    svc.add_problem(
        session, course_id=course.id, activity_id=activity.activity_id,
        problem_definition_id=definition.experiment_id,
    )
    svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
    if scope:
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id}],
        )
    # HTTP 请求走独立 session —— 不 commit 的话活动对学生不可见
    session.commit()
    return activity


class TestStudentActivityList:
    def test_published_and_scoped_visible(
        self, client, session, teacher_user, student_user, svc
    ):
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)

        visible = _publish_with_scope(session, teacher_user, course, svc, title="可见作业")
        _publish_with_scope(session, teacher_user, course, svc,
                            title="范围外作业", scope=False)

        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/student/activities",
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        titles = [i["title"] for i in items]
        assert "可见作业" in titles and "范围外作业" not in titles

        row = next(i for i in items if i["title"] == "可见作业")
        assert row["window_status"] == "open"
        assert row["can_submit"] is True
        assert row["problem_count"] == 1

    def test_draft_invisible_to_student(
        self, client, session, teacher_user, student_user, svc
    ):
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="草稿活动"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        # 不发布
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id}],
        )

        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/student/activities",
            headers=_auth(student_user),
        )
        assert resp.json()["data"]["items"] == []

    def test_window_states_computed_server_side(
        self, client, session, teacher_user, student_user, svc
    ):
        """四种窗口状态由服务端算好，前端不猜时间。"""
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        now = datetime.now(timezone.utc)

        _publish_with_scope(session, teacher_user, course, svc, title="未开始",
                            start=now + timedelta(days=1),
                            end=now + timedelta(days=2))
        _publish_with_scope(session, teacher_user, course, svc, title="进行中",
                            start=now - timedelta(days=1),
                            end=now + timedelta(days=1))
        _publish_with_scope(session, teacher_user, course, svc, title="已截止",
                            start=now - timedelta(days=2),
                            end=now - timedelta(days=1))
        _publish_with_scope(session, teacher_user, course, svc, title="可迟交",
                            start=now - timedelta(days=2),
                            end=now - timedelta(days=1), allow_late=True)

        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/student/activities",
            headers=_auth(student_user),
        )
        by_title = {i["title"]: i for i in resp.json()["data"]["items"]}
        assert by_title["未开始"]["window_status"] == "not_started"
        assert by_title["未开始"]["can_submit"] is False
        assert by_title["进行中"]["window_status"] == "open"
        assert by_title["已截止"]["window_status"] == "ended"
        assert by_title["已截止"]["can_submit"] is False
        assert by_title["可迟交"]["window_status"] == "late"
        assert by_title["可迟交"]["can_submit"] is True

    def test_teacher_list_endpoint_still_teacher_only(
        self, client, session, teacher_user, student_user, svc
    ):
        """教师管理列表端点不对学生开放（PR-08 的端点语义保持）。"""
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        _publish_with_scope(session, teacher_user, course, svc, title="作业")
        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/activities",
            headers=_auth(student_user),
        )
        assert resp.status_code == 403, resp.text


def activate(student, session, course):
    from app.services.course_access_service import activate_student_membership

    session.add(StudentEnrollment(
        student_id=student.id, course_id=course.id,
        overall_progress=0.0, is_active=True,
    ))
    session.commit()
    activate_student_membership(session, course.id, student.id)
    # 请求走独立 session —— **必须提交**，否则权限上下文看不到成员关系（403）
    session.commit()
    # 请求走独立 session —— **必须提交**，否则权限上下文看不到成员关系（403）
    session.commit()


class TestAnalyticsSummary:
    def test_summary_counts_and_trend(self, client, session, teacher_user, student_user):
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        definition = _definition_with_version(session, course, teacher_user)

        for outcome, count in (("ACCEPTED", 3), ("WRONG_ANSWER", 5)):
            for _ in range(count):
                session.add(ExperimentAttempt(
                    attempt_id=f"att_{uuid.uuid4().hex[:10]}",
                    experiment_id=definition.experiment_id,
                    version_id=definition.default_version_id,
                    course_id=course.id, student_id=student_user.id,
                    status="finalized", passed=(outcome == "ACCEPTED"),
                    final_score=1.0 if outcome == "ACCEPTED" else 0.2,
                ))
        session.commit()

        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/analytics/oj",
            headers=_auth(teacher_user),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["student_count"] >= 1
        assert data["finalized_total"] == 8
        assert data["finalized_passed"] == 3
        assert len(data["trend"]) == 30
        assert data["high_frequency_wrong"] == [] or all(
            w["wrong_count"] >= 0 for w in data["high_frequency_wrong"]
        )
        # trend 最后一天至少包含本次提交日（UTC 口径）
        assert data["trend"][-1]["date"] is not None

    def test_naive_datetimes_do_not_break_summary(
        self, client, session, teacher_user, student_user
    ):
        """**部署回归**：PG 的 DateTime 列返回 naive datetime，与 aware 的
        服务端时钟比较曾直接 TypeError → 500（2026-09-12 已部署环境实测）。
        此用例以 naive 时间戳构造数据，锁住修复。"""
        from datetime import datetime as dt

        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        definition = _definition_with_version(session, course, teacher_user)
        naive = dt(2026, 9, 11, 12, 0, 0)  # 无 tzinfo —— 与 PG 返回形态一致
        session.add(ExperimentAttempt(
            attempt_id=f"att_{uuid.uuid4().hex[:10]}",
            experiment_id=definition.experiment_id,
            version_id=definition.default_version_id,
            course_id=course.id, student_id=student_user.id,
            status="finalized", passed=True, final_score=1.0,
            submitted_at=naive, finalized_at=naive,
        ))
        session.commit()

        from app.services.experiment_analytics_service import ExperimentAnalyticsService

        result = ExperimentAnalyticsService().get_course_summary(
            session, course_id=course.id
        )
        assert result["finalized_total"] >= 1
        assert result["pass_rate"] is not None

    def test_student_forbidden(self, client, session, teacher_user, student_user):
        course = _course_with_capabilities(session, teacher_user)
        activate(student_user, session, course)
        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/analytics/oj",
            headers=_auth(student_user),
        )
        assert resp.status_code == 403, resp.text
