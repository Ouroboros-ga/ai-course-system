"""OJ 作答归属链（PR-18）：活动作业的作答必须能归属回活动。

回归背景（2026-09-12 审计发现）：Activity 域（PR-07/08/11/12/14）只有读路径，
`ExperimentAttempt.activity_id` / `ExperimentRun.activity_id` 在生产链路上
**没有任何写入者**（只有测试直接构造），`assert_submission_open` 零生产调用，
`max_submissions` 列建好但从未执行 —— 榜单与算分恒为空，窗口与上限形同虚设。

本文件钉住修复后的不变式：
- 建 attempt 可带 activity_id：三道门（可见性/类型/窗口）+ 冻结版本；
- run 从 attempt 继承 activity_id；
- max_submissions 在提交语义点执行（取消/基建失败不占预算）；
- 学情高频错题不再因 run 无 experiment 直链而 500；
- 提交列表 total 是命中总数（分页前），offset 真分页；
- 我的状态：SUBMITTED/FAILED 算碰过，CANCELLED 不算。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.core.security import create_access_token
from app.core.time_utils import utcnow_aware
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRun,
    ExperimentVersion,
)
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.experiment_activity_service import ExperimentActivityService
from app.services.experiment_analytics_service import ExperimentAnalyticsService
from app.services.experiment_attempt_service import (
    attempt_service,
    run_service,
)
from app.services.experiment_student_service import ExperimentStudentService


EXPERIMENTS = "/api/v1/experiments"


def _token(user) -> str:
    return create_access_token({
        "sub": str(user.id), "username": user.username,
        "role": user.role.value, "school_id": user.school_id or "t",
    })


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user)}"}


@pytest.fixture
def course(session, teacher_user, student_user):
    course = Course(
        fanya_course_id=f"att-{uuid.uuid4().hex[:8]}",
        fanya_course_name="ATTR", title="ATTR",
        teacher_id=teacher_user.id, status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_user.id)
    session.add(StudentEnrollment(
        student_id=student_user.id, course_id=course.id,
        overall_progress=0.0, is_active=True,
    ))
    session.commit()
    activate_student_membership(session, course.id, student_user.id)
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


def _definition(session, course, teacher, *, title="归属题"):
    d = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title=title, created_by=teacher.id,
        difficulty="easy", tags=[],
        language_whitelist=["python3"],
        publish_status=ExperimentPublishStatus.PUBLISHED,
    )
    session.add(d)
    session.flush()
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=d.experiment_id, course_id=course.id,
        created_by=teacher.id, is_locked=True, is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        cpu_time_limit=5, memory_limit=128_000, wall_time_limit=10,
    )
    session.add(version)
    session.flush()
    d.default_version_id = version.version_id
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


def _new_version(session, course, teacher, definition) -> ExperimentVersion:
    """模拟"挂题后题目又发新版"：新版本激活，definition 默认指向新版。"""
    version = ExperimentVersion(
        version_id=f"ver_{uuid.uuid4().hex[:12]}",
        experiment_id=definition.experiment_id, course_id=course.id,
        version_number=2,
        created_by=teacher.id, is_locked=True, is_active=True,
        reference_preview_verified_at=utcnow_aware(),
        cpu_time_limit=5, memory_limit=128_000, wall_time_limit=10,
    )
    session.add(version)
    session.flush()
    definition.default_version_id = version.version_id
    session.add(definition)
    session.commit()
    return version


def _activity(session, course, teacher, *, max_submissions=0, **kwargs):
    svc = ExperimentActivityService()
    activity = svc.create_activity(
        session, course_id=course.id, owner_id=teacher.id,
        title="作业一", type="homework", max_submissions=max_submissions,
        **kwargs,
    )
    session.commit()
    return activity


def _published_activity(session, course, teacher, definition, **kwargs):
    svc = ExperimentActivityService()
    activity = _activity(session, course, teacher, **kwargs)
    svc.add_problem(
        session, course_id=course.id, activity_id=activity.activity_id,
        problem_definition_id=definition.experiment_id,
    )
    svc.set_scopes(
        session, activity_id=activity.activity_id,
        scopes=[{"scope_type": "course", "scope_id": course.id}],
    )
    svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
    session.commit()
    session.refresh(activity)
    return activity


def _run(session, course, student, attempt, *, outcome="ACCEPTED"):
    r = ExperimentRun(
        run_id=f"run_{uuid.uuid4().hex[:12]}",
        attempt_id=attempt.attempt_id,
        course_id=course.id, student_id=student.id,
        language="python3", source_code="print(1)",
        outcome=outcome, score=1.0 if outcome == "ACCEPTED" else 0.0,
        passed_count=1, total_count=1,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def _attempt_row(session, course, student, definition, *, status, activity_id=None):
    a = ExperimentAttempt(
        attempt_id=f"att_{uuid.uuid4().hex[:10]}",
        experiment_id=definition.experiment_id,
        version_id=definition.default_version_id,
        course_id=course.id, student_id=student.id,
        status=status, activity_id=activity_id,
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


class TestActivityAttribution:
    def test_attempt_pins_frozen_version_not_current_default(
        self, session, teacher_user, student_user, course,
    ):
        """挂题后题目发新版，作业作答仍钉挂题时冻结的版本。"""
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(session, course, teacher_user, definition)
        problems = ExperimentActivityService().list_problems(
            session, activity_id=activity.activity_id,
        )
        frozen_version = problems[0].problem_version_id

        v2 = _new_version(session, course, teacher_user, definition)
        assert v2.version_id != frozen_version

        attempt = attempt_service.create_attempt(
            session, course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
            activity_id=activity.activity_id,
        )
        assert attempt.activity_id == activity.activity_id
        assert attempt.version_id == frozen_version
        assert attempt.version_id != definition.default_version_id

    def test_free_attempt_uses_active_version(
        self, session, teacher_user, student_user, course,
    ):
        """不带 activity 照旧走当前激活版本（自由练习零改动）。"""
        definition = _definition(session, course, teacher_user)
        attempt = attempt_service.create_attempt(
            session, course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
        )
        assert attempt.activity_id is None
        assert attempt.version_id == definition.default_version_id

    def test_run_inherits_activity_id(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(session, course, teacher_user, definition)
        attempt = attempt_service.create_attempt(
            session, course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
            activity_id=activity.activity_id,
        )
        run = asyncio.run(
            run_service.create_run(
                session, course_id=course.id, attempt_id=attempt.attempt_id,
                language="python3", source_code="print(1)",
                student_id=student_user.id,
            )
        )
        assert run.activity_id == activity.activity_id

    def test_window_closed_rejects(self, session, teacher_user, student_user, course):
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(
            session, course, teacher_user, definition,
            end_at=utcnow_aware() - timedelta(hours=1),
        )
        with pytest.raises(HTTPException) as exc:
            attempt_service.create_attempt(
                session, course_id=course.id,
                experiment_id=definition.experiment_id,
                student_id=student_user.id,
                activity_id=activity.activity_id,
            )
        assert exc.value.status_code == 409

    def test_draft_activity_rejects(self, session, teacher_user, student_user, course):
        definition = _definition(session, course, teacher_user)
        svc = ExperimentActivityService()
        activity = _activity(session, course, teacher_user)
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id}],
        )
        session.commit()
        with pytest.raises(HTTPException) as exc:
            attempt_service.create_attempt(
                session, course_id=course.id,
                experiment_id=definition.experiment_id,
                student_id=student_user.id,
                activity_id=activity.activity_id,
            )
        assert exc.value.status_code == 409

    def test_invisible_activity_is_404(
        self, session, teacher_user, student_user, course,
    ):
        """活动 scope 到别的课程：对该学生即不存在（防探测）。"""
        definition = _definition(session, course, teacher_user)
        svc = ExperimentActivityService()
        activity = _activity(session, course, teacher_user)
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id + 999}],
        )
        svc.publish_activity(
            session, course_id=course.id, activity_id=activity.activity_id,
        )
        session.commit()
        with pytest.raises(HTTPException) as exc:
            attempt_service.create_attempt(
                session, course_id=course.id,
                experiment_id=definition.experiment_id,
                student_id=student_user.id,
                activity_id=activity.activity_id,
            )
        assert exc.value.status_code == 404

    def test_experiment_not_in_activity_is_422(
        self, session, teacher_user, student_user, course,
    ):
        in_activity = _definition(session, course, teacher_user, title="在作业里")
        outsider = _definition(session, course, teacher_user, title="不在作业里")
        activity = _published_activity(session, course, teacher_user, in_activity)
        with pytest.raises(HTTPException) as exc:
            attempt_service.create_attempt(
                session, course_id=course.id,
                experiment_id=outsider.experiment_id,
                student_id=student_user.id,
                activity_id=activity.activity_id,
            )
        assert exc.value.status_code == 422

    def test_unknown_activity_is_404(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        with pytest.raises(HTTPException) as exc:
            attempt_service.create_attempt(
                session, course_id=course.id,
                experiment_id=definition.experiment_id,
                student_id=student_user.id,
                activity_id="act_nope",
            )
        assert exc.value.status_code == 404


class TestMaxSubmissions:
    def test_second_submission_over_budget_rejected(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(
            session, course, teacher_user, definition, max_submissions=1,
        )
        attempt = attempt_service.create_attempt(
            session, course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
            activity_id=activity.activity_id,
        )
        asyncio.run(
            run_service.create_run(
                session, course_id=course.id, attempt_id=attempt.attempt_id,
                language="python3", source_code="print(1)",
                student_id=student_user.id,
            )
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                run_service.create_run(
                    session, course_id=course.id, attempt_id=attempt.attempt_id,
                    language="python3", source_code="print(2)",
                    student_id=student_user.id,
                )
            )
        assert exc.value.status_code == 409

    def test_cancelled_and_system_error_do_not_consume_budget(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(
            session, course, teacher_user, definition, max_submissions=1,
        )
        attempt = attempt_service.create_attempt(
            session, course_id=course.id,
            experiment_id=definition.experiment_id,
            student_id=student_user.id,
            activity_id=activity.activity_id,
        )
        bad = asyncio.run(
            run_service.create_run(
                session, course_id=course.id, attempt_id=attempt.attempt_id,
                language="python3", source_code="print(1)",
                student_id=student_user.id,
            )
        )
        # 取消的 run 不占预算
        bad.cancel_requested_at = utcnow_aware()
        session.add(bad)
        session.commit()
        session.refresh(bad)
        assert bad.run_state == "cancelled"
        ok = asyncio.run(
            run_service.create_run(
                session, course_id=course.id, attempt_id=attempt.attempt_id,
                language="python3", source_code="print(2)",
                student_id=student_user.id,
            )
        )
        assert ok.run_id != bad.run_id


class TestAnalyticsRobustness:
    def test_non_accepted_run_does_not_500(
        self, session, teacher_user, student_user, course,
    ):
        """高频错题：run 无 experiment 直链，经 attempt 解析（曾 500）。"""
        definition = _definition(session, course, teacher_user)
        attempt = _attempt_row(
            session, course, student_user, definition, status="finalized",
        )
        _run(session, course, student_user, attempt, outcome="WRONG_ANSWER")
        summary = ExperimentAnalyticsService().get_course_summary(
            session, course_id=course.id, trend_days=7,
        )
        assert summary["submission_count"] == 1
        assert len(summary["high_frequency_wrong"]) == 1
        assert summary["high_frequency_wrong"][0]["experiment_id"] == (
            definition.experiment_id
        )
        assert summary["high_frequency_wrong"][0]["wrong_count"] == 1

    def test_problem_stats_counts_attempts(
        self, session, teacher_user, student_user, course,
    ):
        """逐题统计：教师题目管理「使用次数」列的数据源。"""
        definition = _definition(session, course, teacher_user)
        good = _attempt_row(
            session, course, student_user, definition, status="finalized",
        )
        good.passed = True
        session.add(good)
        _attempt_row(session, course, student_user, definition, status="finalized")
        session.commit()
        summary = ExperimentAnalyticsService().get_course_summary(
            session, course_id=course.id, trend_days=7,
        )
        row = {
            item["experiment_id"]: item
            for item in summary["problem_stats"]
        }[definition.experiment_id]
        assert row["attempt_total"] == 2
        assert row["passed_total"] == 1

    def test_never_submitted_student_not_flagged(
        self, session, teacher_user, student_user, course,
    ):
        """从未作答的在册学生不进"需要关注"（点名册问题不是学情问题）。"""
        summary = ExperimentAnalyticsService().get_course_summary(
            session, course_id=course.id, trend_days=7,
        )
        assert summary["students_needing_attention"] == []

    def test_zero_pass_with_submissions_is_flagged(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        _attempt_row(session, course, student_user, definition, status="finalized")
        summary = ExperimentAnalyticsService().get_course_summary(
            session, course_id=course.id, trend_days=7,
        )
        flagged = [s for s in summary["students_needing_attention"]
                   if s["student_id"] == student_user.id]
        assert len(flagged) == 1


class TestPreviewCannotSubmitFormal:
    """教师/预览身份：运行测试可以（自由沙箱，不落库），正式提交不行。

    正式 attempt 一旦建出来，其 finalized 行会直接污染全班通过率、
    学情看板与活动榜单 —— 且 finalize 会给教师写 LearningEvidence。
    """

    def test_teacher_create_attempt_403(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        resp = client.post(
            f"{EXPERIMENTS}/{definition.experiment_id}/attempts"
            f"?course_id={course.id}",
            json={"return_anchor": {}},
            headers=_auth(teacher_user),
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["data"]["error_code"] == "PREVIEW_CANNOT_SUBMIT_FORMAL"

    def test_teacher_create_run_403(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        attempt = _attempt_row(
            session, course, teacher_user, definition, status="in_progress",
        )
        resp = client.post(
            f"{EXPERIMENTS}/attempts/{attempt.attempt_id}/runs"
            f"?course_id={course.id}",
            json={"language": "python3", "source_code": "print(1)"},
            headers={**_auth(teacher_user), "Idempotency-Key": "t1"},
        )
        assert resp.status_code == 403, resp.text
        assert resp.json()["data"]["error_code"] == "PREVIEW_CANNOT_SUBMIT_FORMAL"

    def test_student_create_attempt_still_ok(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        resp = client.post(
            f"{EXPERIMENTS}/{definition.experiment_id}/attempts"
            f"?course_id={course.id}",
            json={"return_anchor": {}},
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 201


class TestSubmissionTotalsAndStatus:
    def test_total_is_truthful_with_offset(
        self, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        attempt = _attempt_row(
            session, course, student_user, definition, status="finalized",
        )
        for _ in range(3):
            _run(session, course, student_user, attempt, outcome="ACCEPTED")
        svc = ExperimentStudentService()
        total, items = svc.list_my_submissions(
            session, course_id=course.id, student_id=student_user.id, limit=2,
        )
        assert total == 3 and len(items) == 2
        total, items = svc.list_my_submissions(
            session, course_id=course.id, student_id=student_user.id,
            limit=2, offset=2,
        )
        assert total == 3 and len(items) == 1

    def test_status_mapping_submitted_failed_cancelled(
        self, session, teacher_user, student_user, course,
    ):
        submitted = _definition(session, course, teacher_user, title="已交卷")
        failed = _definition(session, course, teacher_user, title="判失败")
        cancelled = _definition(session, course, teacher_user, title="已取消")
        _attempt_row(session, course, student_user, submitted, status="submitted")
        _attempt_row(session, course, student_user, failed, status="failed")
        _attempt_row(session, course, student_user, cancelled, status="cancelled")
        summary = ExperimentStudentService()._my_attempt_summary(
            session, course_id=course.id, student_id=student_user.id,
        )
        assert summary[submitted.experiment_id]["attempted"] is True
        assert summary[failed.experiment_id]["attempted"] is True
        assert summary[cancelled.experiment_id]["attempted"] is False


class TestAttemptEndpointAttribution:
    def test_post_attempt_with_activity(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        activity = _published_activity(session, course, teacher_user, definition)
        resp = client.post(
            f"{EXPERIMENTS}/{definition.experiment_id}/attempts"
            f"?course_id={course.id}",
            json={"return_anchor": {}, "activity_id": activity.activity_id},
            headers=_auth(student_user),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 201, body
        assert body["data"]["activity_id"] == activity.activity_id

    def test_post_attempt_with_unknown_activity_404(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        resp = client.post(
            f"{EXPERIMENTS}/{definition.experiment_id}/attempts"
            f"?course_id={course.id}",
            json={"return_anchor": {}, "activity_id": "act_nope"},
            headers=_auth(student_user),
        )
        assert resp.status_code == 404, resp.text

    def test_teacher_submissions_total_and_student_filter(
        self, client, session, teacher_user, student_user, course,
    ):
        definition = _definition(session, course, teacher_user)
        attempt = _attempt_row(
            session, course, student_user, definition, status="finalized",
        )
        _run(session, course, student_user, attempt, outcome="ACCEPTED")
        _run(session, course, student_user, attempt, outcome="WRONG_ANSWER")
        _run(session, course, teacher_user, attempt, outcome="ACCEPTED")

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/teacher/submissions?limit=1",
            headers=_auth(teacher_user),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total"] == 3 and len(data["items"]) == 1

        resp = client.get(
            f"{EXPERIMENTS}/course/{course.id}/teacher/submissions"
            f"?student_id={student_user.id}",
            headers=_auth(teacher_user),
        )
        data = resp.json()["data"]
        assert data["total"] == 2
        assert all(i["student_id"] == student_user.id for i in data["items"])
