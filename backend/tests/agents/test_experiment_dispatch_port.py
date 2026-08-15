"""TeachingAgent experiment dispatch is proposal-only and course-scoped."""
from __future__ import annotations

import asyncio

from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus
from app.models.experiment_model import (
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentRecommendation,
    ExperimentRun,
    ExperimentVersion,
)
from app.platform.agents.providers.experiment.dispatch import (
    make_session_scoped_experiment_dispatch_port,
)
from app.platform.agents.edu.registry import TeachingAgentRuntimeRegistry
from app.services.course_access_service import (
    activate_student_membership,
    establish_course_access_baseline,
)
from sqlmodel import Session, select


def _create_recommendable_experiment(session, *, teacher_id, student_id, node_id=9):
    course = Course(
        fanya_course_id=f"dispatch-port-{teacher_id}-{student_id}-{node_id}",
        fanya_course_name="Dispatch Port Course",
        title="Dispatch Port Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.flush()
    establish_course_access_baseline(session, course.id, teacher_id)
    activate_student_membership(session, course.id, student_id)
    capability = session.exec(select(CourseCapability).where(
        CourseCapability.course_id == course.id,
    )).one()
    capability.experiment = True
    capability.coding_sandbox = True
    definition = ExperimentDefinition(
        course_id=course.id,
        title="Locked published experiment",
        language_whitelist=["python3"],
        knowledge_node_ids=[node_id],
        publish_status=ExperimentPublishStatus.PUBLISHED,
        created_by=teacher_id,
    )
    session.add(definition)
    session.flush()
    version = ExperimentVersion(
        course_id=course.id,
        experiment_id=definition.experiment_id,
        version_number=1,
        is_active=True,
        is_locked=True,
        created_by=teacher_id,
    )
    definition.default_version_id = version.version_id
    session.add(capability)
    session.add(version)
    session.add(definition)
    session.commit()
    return course, definition, capability


def test_dispatch_port_lists_only_current_course_locked_published_experiments(session, teacher_user, student_user):
    course, definition, _ = _create_recommendable_experiment(
        session, teacher_id=teacher_user.id, student_id=student_user.id,
    )
    other, _, _ = _create_recommendable_experiment(
        session, teacher_id=teacher_user.id, student_id=student_user.id, node_id=10,
    )
    port = make_session_scoped_experiment_dispatch_port(lambda: Session(session.get_bind()))

    items = asyncio.run(port.list_recommendable_experiments(
        course_id=str(course.id), node_id="9",
    ))

    assert [item["experiment_id"] for item in items] == [definition.experiment_id]
    assert asyncio.run(port.list_recommendable_experiments(
        course_id=str(other.id), node_id="9",
    )) == []


def test_dispatch_port_creates_pending_proposal_without_execution_state(session, teacher_user, student_user):
    course, definition, _ = _create_recommendable_experiment(
        session, teacher_id=teacher_user.id, student_id=student_user.id,
    )
    port = make_session_scoped_experiment_dispatch_port(lambda: Session(session.get_bind()))

    proposed = asyncio.run(port.propose_recommendation(
        course_id=str(course.id),
        student_id=str(student_user.id),
        experiment_id=definition.experiment_id,
        outline_node_id="9",
        trace_id="trace-dispatch-port",
        session_id="session-dispatch-port",
    ))

    assert proposed["status"] == "pending"
    assert proposed["requires_confirmation"] is True
    assert session.exec(select(ExperimentAttempt).where(
        ExperimentAttempt.course_id == course.id,
    )).first() is None
    assert session.exec(select(ExperimentRun).where(
        ExperimentRun.course_id == course.id,
    )).first() is None
    assert session.exec(select(ExperimentRecommendation).where(
        ExperimentRecommendation.course_id == course.id,
    )).first() is None


def test_dispatch_port_refuses_disabled_capability_and_invalid_node(session, teacher_user, student_user):
    course, definition, capability = _create_recommendable_experiment(
        session, teacher_id=teacher_user.id, student_id=student_user.id,
    )
    port = make_session_scoped_experiment_dispatch_port(lambda: Session(session.get_bind()))

    invalid_node = asyncio.run(port.propose_recommendation(
        course_id=str(course.id), student_id=str(student_user.id),
        experiment_id=definition.experiment_id, outline_node_id="not-a-course-node",
        trace_id="trace-invalid-node", session_id="session-invalid-node",
    ))
    assert invalid_node["status"] == "outline_node_not_in_experiment"

    capability.experiment = False
    session.add(capability)
    session.commit()
    disabled = asyncio.run(port.propose_recommendation(
        course_id=str(course.id), student_id=str(student_user.id),
        experiment_id=definition.experiment_id, outline_node_id="9",
        trace_id="trace-disabled", session_id="session-disabled",
    ))
    assert disabled["status"] == "experiment_capability_disabled"


def test_teaching_registry_retains_dispatch_port_without_auto_dispatch():
    dispatch = object()
    registry = TeachingAgentRuntimeRegistry(
        demo_service=object(),
        llm=object(),
        recommendation=object(),
        sandbox=object(),
        learning_events=object(),
        experiment_dispatch=dispatch,
    )

    assert registry._experiment_dispatch is dispatch
