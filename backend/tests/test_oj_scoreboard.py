"""契约：作业榜（PR-11）—— 域规则 + 服务聚合 + 教师端点。

DoD 对应：**score 可重算且 deterministic** 在榜层面的验证 —— 同一组作答
任何顺序重算，整张榜逐字节相同。

口径：榜只认 finalized attempts（与正式学习证据同口径）；
每生每题取最好分；`ranking_mode="none"` 下不给名次、按学号升序。
"""
from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token
from app.domain.oj.scoreboard import (
    BoardRow,
    assert_scoreboard_supported,
    build_homework_board,
)
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_activity_model import ExperimentActivity
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentVersion,
)
from app.services.experiment_scoreboard_service import ExperimentScoreboardService


_T0 = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 域规则
# ---------------------------------------------------------------------------


class TestBoardPolicy:
    def test_rows_sorted_by_student_id_asc(self):
        """none 模式 = 学号自然序，不随输入顺序漂移。"""
        data = [(7, {"total": 9.0, "max_total": 10.0, "per_problem": []}),
                (3, {"total": 5.0, "max_total": 10.0, "per_problem": []})]
        board = build_homework_board(data, ranking_mode="none")
        assert [r["student_id"] for r in board["rows"]] == [3, 7]
        assert all(r["rank"] is None for r in board["rows"])

    def test_no_ranks_in_none_mode(self):
        """没有罚时语义的并列名次是纯负债 —— none 模式不给名次。"""
        data = [(1, {"total": 8.0, "max_total": 10.0, "per_problem": []}),
                (2, {"total": 8.0, "max_total": 10.0, "per_problem": []})]
        board = build_homework_board(data, ranking_mode="none")
        assert all(r["rank"] is None for r in board["rows"])

    def test_duplicate_student_rejected(self):
        """同生两行是上游聚合 bug，静默去重会掩盖它。"""
        with pytest.raises(ValueError, match="两行"):
            build_homework_board(
                [(1, {"total": 1.0, "max_total": 1.0, "per_problem": []})] * 2,
                ranking_mode="none",
            )

    def test_empty_board_is_legal(self):
        board = build_homework_board([], ranking_mode="none")
        assert board == {"ranking_mode": "none", "rows": [], "total_rows": 0}

    def test_icpc_mode_rejected_until_pr15(self):
        """icpc 是合法词但属 PR-15 —— 显式拒绝，绝不静默按作业榜渲染。"""
        with pytest.raises(ValueError, match="PR-15"):
            build_homework_board([], ranking_mode="icpc")
        with pytest.raises(ValueError, match="PR-15"):
            assert_scoreboard_supported(ranking_mode="icpc", scoring_mode="sum")

    def test_unimplemented_scoring_mode_rejected(self):
        with pytest.raises(ValueError, match="算分模式"):
            assert_scoreboard_supported(ranking_mode="none", scoring_mode="weighted")


# ---------------------------------------------------------------------------
# 服务聚合
# ---------------------------------------------------------------------------


def _course(session, teacher) -> Course:
    course = Course(
        fanya_course_id=f"sb-{uuid.uuid4().hex[:8]}",
        fanya_course_name="SB Course", title="SB Course",
        teacher_id=teacher.id, status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def _definition_with_version(session, course, teacher) -> ExperimentDefinition:
    definition = ExperimentDefinition(
        experiment_id=f"exp_{uuid.uuid4().hex[:12]}",
        course_id=course.id, title="题", created_by=teacher.id,
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


def _activity_with_two_problems(session, teacher, course) -> ExperimentActivity:
    svc = ExperimentScoreboardService()
    d1 = _definition_with_version(session, course, teacher)
    d2 = _definition_with_version(session, course, teacher)
    activity = svc._activity_service.create_activity(
        session, course_id=course.id, owner_id=teacher.id, title="榜测试作业"
    )
    svc._activity_service.add_problem(
        session, course_id=course.id, activity_id=activity.activity_id,
        problem_definition_id=d1.experiment_id, max_score=5.0,
    )
    svc._activity_service.add_problem(
        session, course_id=course.id, activity_id=activity.activity_id,
        problem_definition_id=d2.experiment_id, max_score=5.0,
    )
    return activity, (d1, d2)


def _finalized_attempt(session, course, student_id, definition, activity, score: float):
    session.add(ExperimentAttempt(
        attempt_id=f"att_{uuid.uuid4().hex[:10]}",
        experiment_id=definition.experiment_id,
        version_id=definition.default_version_id,
        course_id=course.id,
        student_id=student_id,
        status="finalized",
        final_score=score,
        activity_id=activity.activity_id,
    ))


class TestScoreboardAggregation:
    def test_board_reflects_best_scores(self, session, teacher_user, student_user):
        from app.models.user_model import User

        other_student = User(
            username=f"sb_s_{uuid.uuid4().hex[:6]}",
            hashed_password="x", role=__import__(
                "app.models.user_model", fromlist=["UserRole"]
            ).UserRole.STUDENT, is_active=True,
        )
        session.add(other_student)
        session.commit()
        session.refresh(other_student)

        course = _course(session, teacher_user)
        activity, (d1, d2) = _activity_with_two_problems(session, teacher_user, course)
        # 甲：题一 0.8、题二 0.4（各两次提交取最好）
        _finalized_attempt(session, course, other_student.id, d1, activity, 0.8)
        _finalized_attempt(session, course, other_student.id, d1, activity, 0.6)
        _finalized_attempt(session, course, other_student.id, d2, activity, 0.4)
        # 乙：只做题一 1.0
        _finalized_attempt(session, course, teacher_user.id, d1, activity, 1.0)
        session.commit()

        board = ExperimentScoreboardService().get_homework_board(
            session, course_id=course.id, activity_id=activity.activity_id
        )
        assert board["total_rows"] == 2
        rows = {r["student_id"]: r for r in board["rows"]}
        assert rows[other_student.id]["total"] == pytest.approx(6.0)  # 0.8*5 + 0.4*5
        assert rows[teacher_user.id]["total"] == pytest.approx(5.0)   # 未答题按 0 分

    def test_recompute_is_deterministic(self, session, teacher_user, student_user):
        course = _course(session, teacher_user)
        activity, (d1, _) = _activity_with_two_problems(session, teacher_user, course)
        _finalized_attempt(session, course, student_user.id, d1, activity, 0.7)
        session.commit()

        svc = ExperimentScoreboardService()
        first = svc.get_homework_board(
            session, course_id=course.id, activity_id=activity.activity_id
        )
        for _ in range(5):
            assert svc.get_homework_board(
                session, course_id=course.id, activity_id=activity.activity_id
            ) == first

    def test_unfinalized_attempts_excluded(self, session, teacher_user, student_user):
        """榜只认 finalized —— 进行中的尝试不进榜（与正式证据同口径）。"""
        course = _course(session, teacher_user)
        activity, (d1, _) = _activity_with_two_problems(session, teacher_user, course)
        session.add(ExperimentAttempt(
            attempt_id=f"att_{uuid.uuid4().hex[:10]}",
            experiment_id=d1.experiment_id,
            version_id=d1.default_version_id,
            course_id=course.id, student_id=student_user.id,
            status="in_progress", final_score=None,
            activity_id=activity.activity_id,
        ))
        session.commit()
        board = ExperimentScoreboardService().get_homework_board(
            session, course_id=course.id, activity_id=activity.activity_id
        )
        assert board["rows"] == []

    def test_single_student_score_matches_board_row(self, session, teacher_user, student_user):
        """单生视图（compute_student_score）与榜**同源同式** —— 两个入口重算一致。"""
        course = _course(session, teacher_user)
        activity, (d1, d2) = _activity_with_two_problems(session, teacher_user, course)
        _finalized_attempt(session, course, student_user.id, d1, activity, 0.9)
        session.commit()

        activity_svc = ExperimentScoreboardService()._activity_service
        single = activity_svc.compute_student_score(
            session, activity=activity, student_id=student_user.id
        )
        board = ExperimentScoreboardService().get_homework_board(
            session, course_id=course.id, activity_id=activity.activity_id
        )
        row = next(r for r in board["rows"] if r["student_id"] == student_user.id)
        assert row["total"] == single["total"]
        assert row["max_total"] == single["max_total"]

    def test_cross_course_activity_is_404(self, session, teacher_user):
        course_a = _course(session, teacher_user)
        course_b = _course(session, teacher_user)
        activity, _ = _activity_with_two_problems(session, teacher_user, course_a)
        with pytest.raises(HTTPException) as exc:
            ExperimentScoreboardService().get_homework_board(
                session, course_id=course_b.id, activity_id=activity.activity_id
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 教师端点（E2E）
# ---------------------------------------------------------------------------


class TestScoreboardEndpoint:
    def test_teacher_gets_board(self, client, session, teacher_user, student_user):
        from app.models.access_control_model import CourseCapability

        course = Course(
            fanya_course_id=f"sbe-{uuid.uuid4().hex[:8]}",
            fanya_course_name="SBE", title="SBE",
            teacher_id=teacher_user.id, status=CourseStatus.PUBLISHED,
        )
        session.add(course)
        session.commit()
        session.refresh(course)
        from app.services.course_access_service import establish_course_access_baseline
        establish_course_access_baseline(session, course.id, teacher_user.id)
        cap = session.exec(
            select(CourseCapability).where(CourseCapability.course_id == course.id)
        ).one()
        cap.experiment = True
        cap.coding_sandbox = True
        session.add(cap)
        session.commit()

        definition = _definition_with_version(session, course, teacher_user)
        svc = ExperimentScoreboardService()
        activity = svc._activity_service.create_activity(
            session, course_id=course.id, owner_id=teacher_user.id, title="端点榜"
        )
        svc._activity_service.add_problem(
            session, course_id=course.id, activity_id=activity.activity_id,
            problem_definition_id=definition.experiment_id, max_score=5.0,
        )
        _finalized_attempt(session, course, student_user.id, definition, activity, 0.8)
        session.add(StudentEnrollment(
            student_id=student_user.id, course_id=course.id,
            overall_progress=0.0, is_active=True,
        ))
        session.commit()

        token = create_access_token({
            "sub": str(teacher_user.id), "username": teacher_user.username,
            "role": teacher_user.role.value, "school_id": teacher_user.school_id or "t",
        })
        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/activities/{activity.activity_id}/scoreboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ranking_mode"] == "none"
        assert data["total_rows"] == 1
        assert data["rows"][0]["student_id"] == student_user.id
        assert data["rows"][0]["total"] == pytest.approx(4.0)

    def test_student_cannot_get_board(self, client, session, teacher_user, student_user):
        """学生侧看榜是 PR-12/15 的教学策略口径，本端点不开放。"""
        course = _course(session, teacher_user)
        activity, _ = _activity_with_two_problems(session, teacher_user, course)
        token = create_access_token({
            "sub": str(student_user.id), "username": student_user.username,
            "role": student_user.role.value, "school_id": student_user.school_id or "t",
        })
        resp = client.get(
            f"/api/v1/experiments/course/{course.id}/activities/{activity.activity_id}/scoreboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 域纯度
# ---------------------------------------------------------------------------


class TestScoreboardPurity:
    def test_policy_module_imports_nothing_from_models_or_services(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "app" / "domain" / "oj" / "scoreboard" / "policy.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        for mod in imported:
            for forbidden in ("app.models", "app.services", "sqlmodel", "sqlalchemy"):
                assert not (mod == forbidden or mod.startswith(forbidden + "."))

    def test_no_utf8_bom(self):
        for name in ("policy.py", "__init__.py"):
            path = (
                Path(__file__).resolve().parents[1]
                / "app" / "domain" / "oj" / "scoreboard" / name
            )
            assert path.read_bytes()[:3] != b"\xef\xbb\xbf", f"{name} 带了 UTF-8 BOM"

    def test_board_row_to_dict_shape(self):
        row = BoardRow(student_id=1, total=2.0, max_total=4.0)
        assert row.to_dict() == {
            "student_id": 1, "total": 2.0, "max_total": 4.0,
            "per_problem": [], "rank": None,
        }
