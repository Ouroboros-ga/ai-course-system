"""Contracts for the trusted asynchronous course-experiment workflow.

The former synchronous submit/finalize and weighted-score tests were removed
with their public APIs.  These tests keep the replacement boundary explicit:
binary ACM grading, hidden-case redaction, and idempotent 202 task creation.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.core.time_utils import utcnow_aware
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus, StudentEnrollment
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentTestCase,
    ExperimentVersion,
)
from app.models.user_model import User, UserRole
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from app.services.experiment_service import definition_service, version_service


EXPERIMENTS = "/api/v1/experiments"


def _user(session, username: str, role: UserRole) -> User:
    user = User(
        username=username,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _token(user: User) -> dict[str, str]:
    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })
    return {"Authorization": f"Bearer {token}"}


def _course(session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"experiment-contract-{teacher_id}-{datetime.now().timestamp()}",
        fanya_course_name="Trusted experiment contract",
        title="Trusted experiment contract",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    establish_course_access_baseline(session, course.id, teacher_id)
    capability = session.exec(select(CourseCapability).where(
        CourseCapability.course_id == course.id,
    )).first()
    assert capability is not None
    capability.experiment = True
    capability.coding_sandbox = True
    session.add(capability)
    session.commit()
    return course


def _enrol(session, course: Course, student: User) -> None:
    session.add(StudentEnrollment(
        student_id=student.id,
        course_id=course.id,
        overall_progress=0.0,
        last_study_time=datetime.now(),
        is_active=True,
    ))
    activate_student_membership(session, course.id, student.id)
    session.commit()


def _ready_experiment(session, course: Course, teacher: User) -> tuple[ExperimentDefinition, ExperimentVersion]:
    definition = definition_service.create_definition(
        session,
        course_id=course.id,
        title="Sum two numbers",
        description="Return the sum.",
        language_whitelist=["python3"],
        knowledge_node_ids=[],
        max_attempts=3,
        cooldown_minutes=0,
        created_by=teacher.id,
    )
    version = version_service.create_version(
        session,
        course_id=course.id,
        experiment_id=definition.experiment_id,
        label="v1",
        cpu_time_limit=2,
        memory_limit=128000,
        wall_time_limit=4,
        max_processes=10,
        max_file_size=1024,
        passing_score=1.0,
        writes_formal_evidence=False,
        created_by=teacher.id,
        test_cases=[
            {"case_name": "public", "stdin": "1 2\n", "expected_stdout": "3\n", "weight": 0.5, "is_hidden": False},
            {"case_name": "hidden", "stdin": "10 5\n", "expected_stdout": "15\n", "weight": 0.5, "is_hidden": True},
        ],
        activate=True,
    )
    version.is_locked = True
    version.reference_preview_verified_at = utcnow_aware()
    definition.default_version_id = version.version_id
    definition.publish_status = ExperimentPublishStatus.PUBLISHED
    session.add(version)
    session.add(definition)
    session.commit()
    return definition, version


def test_version_rejects_partial_passing_score_and_incomplete_weights(session, teacher_user):
    course = _course(session, teacher_user.id)
    definition = definition_service.create_definition(
        session,
        course_id=course.id,
        title="ACM only",
        description="Binary scoring",
        language_whitelist=["python3"],
        knowledge_node_ids=[],
        max_attempts=1,
        cooldown_minutes=0,
        created_by=teacher_user.id,
    )

    with pytest.raises(Exception):
        version_service.create_version(
            session, course_id=course.id, experiment_id=definition.experiment_id,
            label="invalid score", cpu_time_limit=1, memory_limit=64000,
            wall_time_limit=2, max_processes=5, max_file_size=512,
            passing_score=0.5, writes_formal_evidence=False, created_by=teacher_user.id,
            test_cases=[{"case_name": "one", "stdin": "", "expected_stdout": "", "weight": 1.0}],
        )
    with pytest.raises(Exception):
        version_service.create_version(
            session, course_id=course.id, experiment_id=definition.experiment_id,
            label="invalid weights", cpu_time_limit=1, memory_limit=64000,
            wall_time_limit=2, max_processes=5, max_file_size=512,
            passing_score=1.0, writes_formal_evidence=False, created_by=teacher_user.id,
            test_cases=[{"case_name": "one", "stdin": "", "expected_stdout": "", "weight": 0.8}],
        )


def test_student_version_view_redacts_hidden_input_and_expected_output(client, session, teacher_user):
    student = _user(session, "experiment-hidden-student", UserRole.STUDENT)
    course = _course(session, teacher_user.id)
    _enrol(session, course, student)
    _, version = _ready_experiment(session, course, teacher_user)

    response = client.get(
        f"{EXPERIMENTS}/versions/{version.version_id}?course_id={course.id}",
        headers=_token(student),
    )
    assert response.status_code == 200, response.text
    cases = response.json()["data"]["test_cases"]
    hidden = next(case for case in cases if case["is_hidden"])
    assert "stdin" not in hidden
    assert "expected_stdout" not in hidden


def test_formal_run_requires_idempotency_key_and_returns_same_202_task(client, session, teacher_user, monkeypatch):
    student = _user(session, "experiment-async-student", UserRole.STUDENT)
    course = _course(session, teacher_user.id)
    _enrol(session, course, student)
    definition, _ = _ready_experiment(session, course, teacher_user)

    # Route tests verify durable creation only; a separate worker test owns
    # Judge0 execution and no test calls an external sandbox.
    from app.platform.tasks.worker import local_task_worker
    monkeypatch.setattr(local_task_worker, "has_handler", lambda _: False)

    attempt_response = client.post(
        f"{EXPERIMENTS}/{definition.experiment_id}/attempts?course_id={course.id}",
        json={"return_anchor": {}},
        headers=_token(student),
    )
    assert attempt_response.status_code == 200, attempt_response.text
    attempt_id = attempt_response.json()["data"]["attempt_id"]
    request = {
        "language": "python3",
        "source_code": "a, b = map(int, input().split())\nprint(a + b)\n",
    }
    assert client.post(
        f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
        json=request,
        headers=_token(student),
    ).status_code == 422

    headers = {**_token(student), "Idempotency-Key": "formal-run-1"}
    first = client.post(
        f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
        json=request,
        headers=headers,
    )
    second = client.post(
        f"{EXPERIMENTS}/attempts/{attempt_id}/runs?course_id={course.id}",
        json=request,
        headers=headers,
    )
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["data"]["run_id"] == second.json()["data"]["run_id"]
    assert first.json()["data"]["task_id"] == second.json()["data"]["task_id"]
