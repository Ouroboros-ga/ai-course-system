"""P5 quality-gate regressions: explicit Warning acknowledgement and graph cycles."""
from __future__ import annotations

import pytest
import uuid

from app.core.security import get_password_hash
from app.models.course_build_model import CourseQualityGateRun, GateSeverity
from app.models.course_model import Course, CourseStatus
from app.models.graph_production_model import GraphSnapshotRecord, SnapshotStatus
from app.models.user_model import User, UserRole
from app.services.course_build_service import _prerequisite_cycle_nodes, quality_gate_service


def _course_and_teacher(session):
    teacher = User(
        username=f"p5_quality_teacher_{uuid.uuid4().hex[:8]}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(teacher)
    session.flush()
    course = Course(
        fanya_course_id=f"p5-quality-gate-{uuid.uuid4().hex}",
        fanya_course_name="P5 quality gate",
        title="P5 quality gate",
        teacher_id=teacher.id,
        status=CourseStatus.DRAFT,
    )
    session.add(course)
    session.flush()
    return course, teacher


def test_warning_needs_explicit_teacher_confirmation(session):
    course, teacher = _course_and_teacher(session)
    run = CourseQualityGateRun(
        course_id=course.id,
        warning_count=1,
        passed=False,
        checks=[{"check_id": "mapping.confidence", "severity": "warning", "passed": False}],
    )
    session.add(run)
    session.commit()

    confirmed = quality_gate_service.confirm_warning_override(
        session,
        course_id=course.id,
        gate_run_id=run.gate_run_id,
        confirmed_by=teacher.id,
        reason="教师已核对低置信度映射并接受当前发布风险",
    )
    assert confirmed.passed is True
    assert confirmed.warning_override_confirmed_by == teacher.id
    assert confirmed.warning_override_at is not None


def test_error_can_be_confirmed_but_blocker_cannot(session):
    course, teacher = _course_and_teacher(session)
    error_run = CourseQualityGateRun(
        course_id=course.id,
        error_count=1,
        passed=False,
        checks=[{"check_id": "structure.no_isolated_nodes", "severity": "error", "passed": False}],
    )
    session.add(error_run)
    session.commit()

    confirmed = quality_gate_service.confirm_warning_override(
        session,
        course_id=course.id,
        gate_run_id=error_run.gate_run_id,
        confirmed_by=teacher.id,
        reason="教师已检查空 section，并确认当前版本可继续发布",
    )
    assert confirmed.passed is True
    assert confirmed.teacher_confirmation_confirmed_by == teacher.id
    assert confirmed.teacher_confirmation_reason

    run = CourseQualityGateRun(
        course_id=course.id,
        blocker_count=1,
        warning_count=1,
        passed=False,
    )
    session.add(run)
    session.commit()

    with pytest.raises(Exception):
        quality_gate_service.confirm_warning_override(
            session,
            course_id=course.id,
            gate_run_id=run.gate_run_id,
            confirmed_by=teacher.id,
            reason="教师不能绕过必须先处理的问题",
        )


def test_prerequisite_cycle_and_non_prerequisite_relation_detection():
    relations = [
        {"id": "r1", "type": "prerequisite", "source": "a", "target": "b"},
        {"id": "r2", "type": "requires", "source": "b", "target": "c"},
        {"id": "r3", "type": "prerequisite_of", "source": "c", "target": "a"},
        {"id": "r4", "type": "related", "source": "x", "target": "y"},
    ]
    assert _prerequisite_cycle_nodes(relations) == {"a", "b", "c"}


def test_quality_gate_requires_a_published_graph_snapshot(session):
    course, teacher = _course_and_teacher(session)

    without_graph = quality_gate_service.run_checks(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    graph_check = next(item for item in without_graph.checks if item["check_id"] == "graph.release_ready")
    assert graph_check["severity"] == GateSeverity.ERROR.value
    assert graph_check["passed"] is False

    session.add(GraphSnapshotRecord(
        snapshot_id=f"p5-graph-{uuid.uuid4().hex}",
        course_id=course.id,
        status=SnapshotStatus.PUBLISHED,
        is_active=True,
        nodes=[],
        relations=[],
    ))
    session.commit()
    with_graph = quality_gate_service.run_checks(
        session, course_id=course.id, initiated_by=teacher.id,
    )
    graph_check = next(item for item in with_graph.checks if item["check_id"] == "graph.prerequisite_acyclic")
    assert graph_check["passed"] is True
