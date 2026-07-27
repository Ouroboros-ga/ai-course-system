"""CodingEduAgent/EduAgent boundary tests.

These tests use only the isolated SQLite fixture.  They prove that a verified
run can produce a bounded diagnosis and that the history adapter does not
expose source code or chat transcripts to TeachingAgent.
"""
from __future__ import annotations

from app.models.course_model import Course
from app.models.experiment_model import ExperimentRun, ExperimentRunArtifact, RunOutcome
from app.platform.agents.tools.coding import (
    SessionScopedCodingDiagnosisPort,
    SessionScopedStudentHistoryPort,
)
from app.services.coding_eduagent_service import coding_eduagent, serialize_diagnosis
from sqlmodel import Session


def _course(session: Session, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id="coding-agent-test-course",
        fanya_course_name="Coding Agent Test",
        title="Coding Agent Test",
        teacher_id=teacher_id,
    )
    session.add(course)
    session.commit()
    session.refresh(course)
    return course


def test_diagnosis_is_idempotent_and_does_not_return_source_code(session, teacher_user, student_user):
    course = _course(session, teacher_user.id)
    run = ExperimentRun(
        run_id="run_coding_agent_test",
        attempt_id="attempt_coding_agent_test",
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('secret student code')",
        outcome=RunOutcome.WRONG_ANSWER,
        error_message="wrong output",
    )
    session.add(run)
    session.add(ExperimentRunArtifact(
        run_id=run.run_id,
        course_id=course.id,
        artifact_type="stderr",
        content="private execution detail",
    ))
    session.commit()

    first = coding_eduagent.diagnose_run(
        session,
        course_id=course.id,
        student_id=student_user.id,
        run_id=run.run_id,
    )
    second = coding_eduagent.diagnose_run(
        session,
        course_id=course.id,
        student_id=student_user.id,
        run_id=run.run_id,
    )
    payload = serialize_diagnosis(first)
    assert first.id == second.id
    assert payload["error_class"] == "logic"
    assert payload["evidence_refs"] == [f"experiment_run:{run.run_id}"]
    assert "source_code" not in payload
    assert "secret student code" not in str(payload)


def test_history_port_is_course_student_scoped_and_bounded(session, teacher_user, student_user):
    course = _course(session, teacher_user.id)
    other = _course(session, teacher_user.id)
    run = ExperimentRun(
        run_id="run_history_scope_test",
        attempt_id="attempt_history_scope_test",
        course_id=course.id,
        student_id=student_user.id,
        source_code="do not expose",
        outcome=RunOutcome.ACCEPTED,
    )
    session.add(run)
    session.commit()
    coding_eduagent.diagnose_run(
        session,
        course_id=course.id,
        student_id=student_user.id,
        run_id=run.run_id,
    )

    other_course_id = int(other.id)
    factory = lambda: Session(session.get_bind())
    history_port = SessionScopedStudentHistoryPort(factory)
    diagnosis_port = SessionScopedCodingDiagnosisPort(factory)
    import asyncio

    history = asyncio.run(history_port.get_history(
        student_id=str(student_user.id), course_id=str(course.id),
    ))
    assert history["student_id"] == student_user.id
    assert history["course_id"] == course.id
    assert "source_code" not in str(history)
    assert "do not expose" not in str(history)
    assert asyncio.run(diagnosis_port.get_latest_diagnosis(
        student_id=str(student_user.id), course_id=str(other_course_id), run_id=run.run_id,
    )) is None
