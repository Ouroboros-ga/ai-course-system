"""Read-only laboratory projection contracts.

Independent laboratory creation and student-authored records were retired.
Only finalized server-owned experiment attempts may appear in this projection.
"""
from __future__ import annotations

import uuid

from fastapi.routing import APIRoute
from sqlmodel import select

from app.models.experiment_model import (
    AttemptStatus,
    ExperimentAttempt,
    ExperimentDefinition,
    ExperimentVersion,
)
from app.models.resource_model import LabRecord
from app.services.resource_service import lab_projection_service


def _finalized_attempt(session, *, course_id: int = 1, student_id: int = 2):
    suffix = uuid.uuid4().hex
    version = ExperimentVersion(
        version_id=f"projection-version-{suffix}",
        experiment_id=f"projection-experiment-{suffix}",
        course_id=course_id,
        version_number=1,
        passing_score=1.0,
        writes_formal_evidence=False,
        created_by=1,
    )
    definition = ExperimentDefinition(
        experiment_id=version.experiment_id,
        course_id=course_id,
        title="Projected experiment",
        description="",
        language_whitelist=["python3"],
        created_by=1,
    )
    attempt = ExperimentAttempt(
        attempt_id=f"projection-attempt-{suffix}",
        experiment_id=version.experiment_id,
        version_id=version.version_id,
        course_id=course_id,
        student_id=student_id,
        status=AttemptStatus.FINALIZED,
        final_score=1.0,
        passed=True,
        evidence_id=f"server-evidence-{suffix}",
    )
    session.add(definition)
    session.add(version)
    session.add(attempt)
    session.commit()
    return attempt


def test_legacy_lab_write_routes_are_not_registered(fastapi_app):
    forbidden = {"create_lab", "publish_lab", "join_lab", "record_lab_result"}
    assert not any(
        isinstance(route, APIRoute)
        and getattr(route.endpoint, "__name__", "") in forbidden
        and "POST" in route.methods
        for route in fastapi_app.routes
    )


def test_finalized_attempt_projects_exactly_one_trusted_lab_record(session):
    attempt = _finalized_attempt(session)

    first = lab_projection_service.project_finalized_attempt(
        session, attempt_id=attempt.attempt_id,
    )
    session.commit()
    second = lab_projection_service.project_finalized_attempt(
        session, attempt_id=attempt.attempt_id,
    )
    session.commit()

    assert first.record_id == second.record_id
    records = list(session.exec(select(LabRecord).where(
        LabRecord.attempt_id == attempt.attempt_id,
        LabRecord.record_source == "experiment_finalization",
    )).all())
    assert len(records) == 1
    assert records[0].student_id == attempt.student_id
    assert records[0].final_score == 1.0
    assert records[0].evidence_id == attempt.evidence_id


def test_unfinalized_attempt_cannot_be_projected_as_a_lab_record(session):
    attempt = _finalized_attempt(session)
    attempt.status = AttemptStatus.SUBMITTED
    session.add(attempt)
    session.commit()

    try:
        lab_projection_service.project_finalized_attempt(session, attempt_id=attempt.attempt_id)
    except Exception:
        pass
    else:
        raise AssertionError("unfinalized attempts must not create trusted lab records")

    assert session.exec(select(LabRecord).where(
        LabRecord.attempt_id == attempt.attempt_id,
        LabRecord.record_source == "experiment_finalization",
    )).first() is None
