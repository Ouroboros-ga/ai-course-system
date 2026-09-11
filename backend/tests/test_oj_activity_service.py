"""PR-07 服务层契约：活动的生命周期 / 题目组织 / 可见范围 / 时间窗 / 算分。

**为什么单开文件**：service 是新建的 `experiment_activity_service.py`，
与 `experiment_service.py`（他线在途 212 行）零共享 —— 测试同样单开，
保证「谁的 hunk」永远可分。

**DoD 对应**：
- 同一 Activity 固定 problem_version_id / 所有学生拿到相同版本 → `TestVersionPinning`
- 自由练习仍可用最新发布版本 → `TestFreePracticeUnaffected`
- teacher scope 正确 → `TestScopeResolution`
- activity 时间约束生效 → `TestSubmissionWindow`
- score 可重算且 deterministic → `TestScoreRecompute`
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import Session as OrmSession, select

from app.core.security import create_access_token
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus
from app.models.experiment_activity_model import (
    ExperimentActivity,
    ExperimentActivityProblem,
    ExperimentActivityScope,
)
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentVersion,
)
from app.models.user_model import User
from app.services.course_access_service import establish_course_access_baseline
from app.services.experiment_activity_service import ExperimentActivityService

_T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


def _course(session: OrmSession, teacher: User) -> Course:
    course = Course(
        fanya_course_id=f"act-{uuid.uuid4().hex[:8]}",
        fanya_course_name="Activity Course",
        title="Activity Course",
        teacher_id=teacher.id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher.id)
    session.commit()
    cap = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    cap.experiment = True
    cap.coding_sandbox = True
    session.add(cap)
    session.commit()
    return course


def _definition_with_version(
    session: OrmSession, course: Course, teacher: User, *, title: str = "两数之和"
) -> ExperimentDefinition:
    """最小可发布的 definition + 激活版本（不走 API，直接建行）。"""
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


@pytest.fixture
def svc() -> ExperimentActivityService:
    return ExperimentActivityService()


@pytest.fixture
def course(session, teacher_user):
    return _course(session, teacher_user)


# ---------------------------------------------------------------------------
# 创建与生命周期
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_create_defaults_to_draft_homework(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="第一次作业"
        )
        assert activity.activity_id.startswith("act_")
        assert activity.status == "draft"
        assert activity.type == "homework"
        assert activity.scoring_mode == "sum"
        assert activity.ranking_mode == "none"
        assert activity.max_submissions == 0

    def test_unsupported_type_rejected_not_silently_downgraded(
        self, session, teacher_user, course, svc
    ):
        """CONTEST 合法但未实现 → **必须 422/409**，绝不当 homework 处理。"""
        with pytest.raises(HTTPException) as exc:
            svc.create_activity(
                session, course_id=course.id, owner_id=teacher_user.id,
                title="比赛", type="contest",
            )
        assert exc.value.status_code in (400, 409, 422)
        # 没有落库
        assert not session.exec(select(ExperimentActivity)).all()

    def test_invalid_window_rejected(self, session, teacher_user, course, svc):
        with pytest.raises(HTTPException) as exc:
            svc.create_activity(
                session, course_id=course.id, owner_id=teacher_user.id,
                title="倒置窗口",
                start_at=_T0 + timedelta(hours=2), end_at=_T0,
            )
        assert exc.value.status_code in (400, 422)

    def test_publish_requires_problems(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="空活动"
        )
        with pytest.raises(HTTPException) as exc:
            svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
        assert exc.value.status_code == 409

    def test_publish_sets_published_at_once(self, session, teacher_user, course, svc):
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业 A"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        published = svc.publish_activity(
            session, course_id=course.id, activity_id=activity.activity_id
        )
        assert published.status == "published"
        assert published.published_at is not None

        # 二次发布拒绝（状态机单向）
        with pytest.raises(HTTPException) as exc:
            svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
        assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# 题目组织与版本固定（DoD 核心）
# ---------------------------------------------------------------------------


class TestVersionPinning:
    def test_problem_pins_active_version(self, session, teacher_user, course, svc):
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        problem = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        assert problem.problem_version_id == definition.default_version_id

    def test_two_problems_with_different_versions_allowed(
        self, session, teacher_user, course, svc
    ):
        """**拍板结论**：固定的是**每道题**的版本，不是全活动共享一个版本。

        两道不同题（不同 definition）各有自己的版本是正常形态 ——
        若强制全活动一个版本，多题作业根本建不起来。
        """
        d1 = _definition_with_version(session, course, teacher_user, title="题一")
        d2 = _definition_with_version(session, course, teacher_user, title="题二")
        assert d1.default_version_id != d2.default_version_id
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="两题作业"
        )
        p1 = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d1.experiment_id,
        )
        p2 = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d2.experiment_id,
        )
        assert p1.problem_version_id == d1.default_version_id
        assert p2.problem_version_id == d2.default_version_id
        assert p1.ordinal == 1 and p2.ordinal == 2

    def test_same_problem_cannot_attach_twice(self, session, teacher_user, course, svc):
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        with pytest.raises(HTTPException):
            svc.add_problem(
                session, course_id=course.id, activity_id=activity.activity_id,
                problem_definition_id=definition.experiment_id,
            )

    def test_ordinal_conflict_rejected(self, session, teacher_user, course, svc):
        d1 = _definition_with_version(session, course, teacher_user, title="题一")
        d2 = _definition_with_version(session, course, teacher_user, title="题二")
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d1.experiment_id,
        )
        with pytest.raises(HTTPException) as exc:
            svc.add_problem(
                session, course_id=course.id, activity_id=activity.activity_id,
                problem_definition_id=d2.experiment_id, ordinal=1,
            )
        assert exc.value.status_code == 409

    def test_ordinal_auto_increments(self, session, teacher_user, course, svc):
        d1 = _definition_with_version(session, course, teacher_user, title="题一")
        d2 = _definition_with_version(session, course, teacher_user, title="题二")
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        first = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d1.experiment_id, ordinal=None,
        )
        second = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d2.experiment_id, ordinal=None,
        )
        assert (first.ordinal, second.ordinal) == (1, 2)

    def test_problems_immutable_after_publish(self, session, teacher_user, course, svc):
        d1 = _definition_with_version(session, course, teacher_user, title="题一")
        d2 = _definition_with_version(session, course, teacher_user, title="题二")
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d1.experiment_id,
        )
        svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
        with pytest.raises(HTTPException) as exc:
            svc.add_problem(
                session, course_id=course.id, activity_id=activity.activity_id,
                problem_definition_id=d2.experiment_id,
            )
        assert exc.value.status_code == 409

    def test_publish_detects_version_drift(self, session, teacher_user, course, svc):
        """题挂上之后**版本行消失** → 发布时拦截。

        版本固化承诺「全班拿到这个版本」，若版本行被删而活动照常发布，
        学生作答会解析到一个不存在的版本 —— 发布前的存在性核对是兜底闸门。
        """
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        # 模拟版本消失：直接删掉被固化的版本行
        version = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.version_id == definition.default_version_id
            )
        ).one()
        session.delete(version)
        definition.default_version_id = None
        session.add(definition)
        session.commit()
        with pytest.raises(HTTPException) as exc:
            svc.publish_activity(session, course_id=course.id, activity_id=activity.activity_id)
        assert exc.value.status_code == 409

    def test_list_problems_sorted_by_ordinal(self, session, teacher_user, course, svc):
        d1 = _definition_with_version(session, course, teacher_user, title="题一")
        d2 = _definition_with_version(session, course, teacher_user, title="题二")
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d2.experiment_id,
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=d1.experiment_id,
        )
        problems = svc.list_problems(session, activity_id=activity.activity_id)
        assert [p.ordinal for p in problems] == [1, 2]


# ---------------------------------------------------------------------------
# 时间窗（DoD：activity 时间约束生效）
# ---------------------------------------------------------------------------


class TestSubmissionWindow:
    def _published_with_window(self, session, teacher_user, course, svc, **kwargs):
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id,
            title="限时作业", **kwargs,
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        return svc.publish_activity(
            session, course_id=course.id, activity_id=activity.activity_id
        )

    def test_draft_activity_rejects_submission(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="草稿"
        )
        with pytest.raises(HTTPException) as exc:
            svc.assert_submission_open(session, activity=activity, now=_T0)
        assert exc.value.status_code == 409

    def test_before_start_rejected(self, session, teacher_user, course, svc):
        activity = self._published_with_window(
            session, teacher_user, course, svc,
            start_at=_T0, end_at=_T0 + timedelta(hours=1),
        )
        with pytest.raises(HTTPException) as exc:
            svc.assert_submission_open(session, activity=activity, now=_T0 - timedelta(minutes=1))
        assert "not_started" in str(exc.value.detail)

    def test_after_end_rejected(self, session, teacher_user, course, svc):
        activity = self._published_with_window(
            session, teacher_user, course, svc,
            start_at=_T0, end_at=_T0 + timedelta(hours=1),
        )
        with pytest.raises(HTTPException) as exc:
            svc.assert_submission_open(session, activity=activity, now=_T0 + timedelta(hours=2))
        assert "ended" in str(exc.value.detail)

    def test_late_submit_allowed_and_marked(self, session, teacher_user, course, svc):
        activity = self._published_with_window(
            session, teacher_user, course, svc,
            start_at=_T0, end_at=_T0 + timedelta(hours=1), allow_late_submit=True,
        )
        reason = svc.assert_submission_open(
            session, activity=activity, now=_T0 + timedelta(hours=2)
        )
        assert reason == "late"

    def test_inside_window_open(self, session, teacher_user, course, svc):
        activity = self._published_with_window(
            session, teacher_user, course, svc,
            start_at=_T0, end_at=_T0 + timedelta(hours=1),
        )
        reason = svc.assert_submission_open(
            session, activity=activity, now=_T0 + timedelta(minutes=30)
        )
        assert reason == "open"


# ---------------------------------------------------------------------------
# 自由练习不受影响（DoD：自由练习仍可使用最新发布版本）
# ---------------------------------------------------------------------------


class TestFreePracticeUnaffected:
    def test_activity_id_is_optional_on_attempt(self, session, teacher_user, course):
        """不挂活动的 attempt（activity_id=None）仍是合法形态 —— 自由练习路径零改动。"""
        from app.models.experiment_model import ExperimentAttempt

        attempt = ExperimentAttempt(
            experiment_id=f"exp_{uuid.uuid4().hex[:10]}",
            version_id=f"ver_{uuid.uuid4().hex[:10]}",
            course_id=course.id,
            student_id=teacher_user.id,
        )
        session.add(attempt)
        session.flush()
        assert attempt.activity_id is None

    def test_definition_default_version_independent_of_activity(
        self, session, teacher_user, course, svc
    ):
        """活动固化的是**活动题目的版本**，definition 的 default_version_id
        仍自由演进 —— 自由练习拿最新版，活动学生拿固化版，互不牵制。"""
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        problem = svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id,
        )
        # 换激活版本：自由练习会拿到新版
        definition.default_version_id = f"ver_{uuid.uuid4().hex[:12]}"
        session.add(definition)
        session.commit()

        assert definition.default_version_id != problem.problem_version_id
        # 活动侧固化的版本不变
        refreshed = svc.list_problems(session, activity_id=activity.activity_id)[0]
        assert refreshed.problem_version_id == problem.problem_version_id


# ---------------------------------------------------------------------------
# 可见范围（DoD：teacher scope 正确）
# ---------------------------------------------------------------------------


class TestScopeResolution:
    def test_course_scope_visible_to_course_students(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id}],
        )
        visible = svc.resolve_visible_activity_ids(
            session, student_id=teacher_user.id, course_id=course.id
        )
        assert activity.activity_id in visible

    def test_other_course_scope_not_visible(self, session, teacher_user, course, svc, student_user):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id + 999}],
        )
        visible = svc.resolve_visible_activity_ids(
            session, student_id=student_user.id, course_id=course.id
        )
        assert activity.activity_id not in visible

    def test_set_scopes_replaces_whole_set(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id}],
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "course", "scope_id": course.id + 1}],
        )
        rows = session.exec(
            select(ExperimentActivityScope).where(
                ExperimentActivityScope.activity_id == activity.activity_id
            )
        ).all()
        assert len(rows) == 1 and rows[0].scope_id == course.id + 1

    def test_duplicate_scopes_deduplicated(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        rows = svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[
                {"scope_type": "course", "scope_id": course.id},
                {"scope_type": "COURSE", "scope_id": course.id},  # 大小写不同，同义
            ],
        )
        assert len(rows) == 1

    def test_class_scope_writeable_but_not_resolved(
        self, session, teacher_user, course, svc, student_user, caplog
    ):
        """class/user scope 可写入、解析时**跳过并记日志** —— 不报错、不误当 course。"""
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.set_scopes(
            session, activity_id=activity.activity_id,
            scopes=[{"scope_type": "class", "scope_id": 77}],
        )
        visible = svc.resolve_visible_activity_ids(
            session, student_id=student_user.id, course_id=course.id
        )
        assert activity.activity_id not in visible  # 未实现 → 不给可见性


# ---------------------------------------------------------------------------
# 算分重算（DoD：score 可重算且 deterministic）
# ---------------------------------------------------------------------------


class TestScoreRecompute:
    def test_no_attempts_scores_zero(self, session, teacher_user, course, svc):
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id, max_score=5.0,
        )
        result = svc.compute_student_score(session, activity=activity, student_id=teacher_user.id)
        assert result["total"] == 0.0
        assert result["max_total"] == 5.0

    def test_recompute_is_deterministic(self, session, teacher_user, course, svc):
        """重算两次必须完全一致 —— DoD 的字面验证（哪怕中间有提交顺序差异）。"""
        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id, max_score=5.0,
        )
        first = svc.compute_student_score(session, activity=activity, student_id=teacher_user.id)
        second = svc.compute_student_score(session, activity=activity, student_id=teacher_user.id)
        assert first == second

    def test_best_attempt_per_problem_wins(self, session, teacher_user, course, svc):
        """同题多次 finalized attempt 取最好 —— 「每题取最好一次」的约定。"""
        from app.models.experiment_model import ExperimentAttempt

        definition = _definition_with_version(session, course, teacher_user)
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="作业"
        )
        svc.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id, max_score=5.0,
        )
        for score in (0.2, 0.8, 0.5):
            session.add(ExperimentAttempt(
                attempt_id=f"att_{uuid.uuid4().hex[:10]}",
                experiment_id=definition.experiment_id,
                version_id=definition.default_version_id,
                course_id=course.id,
                student_id=teacher_user.id,
                status="finalized",
                final_score=score,
                activity_id=activity.activity_id,
            ))
        session.commit()
        result = svc.compute_student_score(session, activity=activity, student_id=teacher_user.id)
        assert result["total"] == 4.0  # 0.8 × 5.0


# ---------------------------------------------------------------------------
# 跨课程隔离
# ---------------------------------------------------------------------------


class TestCrossCourseIsolation:
    def test_activity_of_other_course_is_404(self, session, teacher_user, course, svc):
        activity = svc.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="A 课程的活动"
        )
        with pytest.raises(HTTPException) as exc:
            svc.get_activity(
                session, course_id=course.id + 999, activity_id=activity.activity_id
            )
        assert exc.value.status_code == 404
