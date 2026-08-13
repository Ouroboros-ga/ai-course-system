"""CodingEduAgent/EduAgent boundary tests.

These tests use only the isolated SQLite fixture.  They prove that a verified
run can produce a bounded diagnosis and that the history adapter does not
expose source code or chat transcripts to TeachingAgent.
"""
from __future__ import annotations

from app.models.course_model import Course
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentRun,
    ExperimentRunArtifact,
    RunOutcome,
)
from app.models.graph_production_model import CourseKnowledgeNode
from app.platform.agents.tools.coding import (
    SessionScopedCodeSubmissionPort,
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


def test_diagnosis_port_exposes_source_free_learning_signal_and_submission_port_is_scoped(
    session, teacher_user, student_user,
):
    course = _course(session, teacher_user.id)
    node = CourseKnowledgeNode(
        course_id=course.id,
        node_key="kn_coding_signal",
        title="Loop boundary",
    )
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Loop exercise",
        created_by=teacher_user.id,
        knowledge_node_ids=[],
    )
    session.add(node)
    session.add(definition)
    session.flush()
    definition.knowledge_node_ids = [node.id]
    first_attempt = ExperimentAttempt(
        experiment_id=definition.experiment_id,
        version_id="expv_signal_1",
        course_id=course.id,
        student_id=student_user.id,
    )
    second_attempt = ExperimentAttempt(
        experiment_id=definition.experiment_id,
        version_id="expv_signal_2",
        course_id=course.id,
        student_id=student_user.id,
    )
    session.add(first_attempt)
    session.add(second_attempt)
    session.flush()
    first_run = ExperimentRun(
        run_id="run_signal_1",
        attempt_id=first_attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('first private source')",
        outcome=RunOutcome.WRONG_ANSWER,
    )
    second_run = ExperimentRun(
        run_id="run_signal_2",
        attempt_id=second_attempt.attempt_id,
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('second private source')",
        outcome=RunOutcome.WRONG_ANSWER,
    )
    session.add(first_run)
    session.add(second_run)
    session.commit()
    coding_eduagent.diagnose_run(
        session, course_id=course.id, student_id=student_user.id, run_id=first_run.run_id,
    )
    coding_eduagent.diagnose_run(
        session, course_id=course.id, student_id=student_user.id, run_id=second_run.run_id,
    )
    session.commit()

    factory = lambda: Session(session.get_bind())
    diagnosis_port = SessionScopedCodingDiagnosisPort(factory)
    history_port = SessionScopedStudentHistoryPort(factory)
    source_port = SessionScopedCodeSubmissionPort(factory)
    import asyncio

    payload = asyncio.run(diagnosis_port.get_latest_diagnosis(
        student_id=str(student_user.id), course_id=str(course.id), run_id=second_run.run_id,
    ))
    assert payload is not None
    assert payload["learning_signal"] == {
        "schema_version": "coding-learning-signal/1",
        "run_id": second_run.run_id,
        "outcome": "wrong_answer",
        "error_class": "logic",
        "knowledge_node_ids": [node.id],
        "repeated_error": {"error_class": "logic", "recent_count": 2, "is_repeated": True},
        "recommended_actions": payload["debug_steps"][:3],
        "evidence_refs": [f"experiment_run:{second_run.run_id}"],
    }
    assert "private source" not in str(payload)

    history = asyncio.run(history_port.get_history(
        student_id=str(student_user.id), course_id=str(course.id),
    ))
    assert history["recent_coding_diagnoses"][0]["learning_signal"]["knowledge_node_ids"] == [node.id]
    assert "private source" not in str(history)
    assert asyncio.run(source_port.get_submission_for_diagnosis(
        student_id=str(student_user.id), course_id=str(course.id), run_id=second_run.run_id,
    )) == {
        "run_id": second_run.run_id,
        "language": "python3",
        "source_code": "print('second private source')",
    }
    assert asyncio.run(source_port.get_submission_for_diagnosis(
        student_id=str(teacher_user.id), course_id=str(course.id), run_id=second_run.run_id,
    )) is None


def test_submission_port_requires_a_verified_terminal_outcome(
    session, teacher_user, student_user,
):
    course = _course(session, teacher_user.id)
    verified = ExperimentRun(
        run_id="run_source_terminal_verified",
        attempt_id="attempt_source_terminal_verified",
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('verified source')",
        outcome=RunOutcome.RUNTIME_ERROR,
    )
    pending = ExperimentRun(
        run_id="run_source_terminal_pending",
        attempt_id="attempt_source_terminal_pending",
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('pending source')",
        outcome=RunOutcome.PENDING,
    )
    unavailable = ExperimentRun(
        run_id="run_source_terminal_unavailable",
        attempt_id="attempt_source_terminal_unavailable",
        course_id=course.id,
        student_id=student_user.id,
        language="python3",
        source_code="print('unavailable source')",
        outcome=RunOutcome.SANDBOX_UNAVAILABLE,
    )
    session.add_all([verified, pending, unavailable])
    session.commit()

    port = SessionScopedCodeSubmissionPort(lambda: Session(session.get_bind()))
    import asyncio

    assert asyncio.run(port.get_submission_for_diagnosis(
        student_id=str(student_user.id), course_id=str(course.id), run_id=verified.run_id,
    )) == {
        "run_id": verified.run_id,
        "language": "python3",
        "source_code": "print('verified source')",
    }
    assert asyncio.run(port.get_submission_for_diagnosis(
        student_id=str(student_user.id), course_id=str(course.id), run_id=pending.run_id,
    )) is None
    assert asyncio.run(port.get_submission_for_diagnosis(
        student_id=str(student_user.id), course_id=str(course.id), run_id=unavailable.run_id,
    )) is None
