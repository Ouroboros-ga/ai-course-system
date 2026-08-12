"""Regression contracts for the trusted course experiment boundary.

These tests deliberately exercise the smallest server-owned invariants first:
students cannot write laboratory grades, and formal grading is binary ACM/ICPC.
"""
from __future__ import annotations

import uuid

from fastapi.routing import APIRoute
from sqlmodel import Session

from app.models.experiment_model import (
    AttemptStatus,
    ExperimentAttempt,
    ExperimentRun,
    ExperimentVersion,
    RunOutcome,
)
from app.services.experiment_service import (
    finalize_service,
    free_sandbox_quota_service,
    sandbox_execution_lease_service,
)


def _terminal_attempt(session: Session, *, outcome: RunOutcome, score: float):
    """Persist only the server-owned records needed to verify grading semantics."""
    suffix = uuid.uuid4().hex
    version = ExperimentVersion(
        version_id=f"expv_contract_{suffix}",
        experiment_id=f"exp_contract_{suffix}",
        course_id=1,
        version_number=1,
        passing_score=0.6,
        writes_formal_evidence=False,
        created_by=1,
    )
    attempt = ExperimentAttempt(
        attempt_id=f"att_contract_{suffix}",
        experiment_id=version.experiment_id,
        version_id=version.version_id,
        course_id=1,
        student_id=2,
        status=AttemptStatus.SUBMITTED,
    )
    run = ExperimentRun(
        run_id=f"run_contract_{suffix}",
        attempt_id=attempt.attempt_id,
        course_id=1,
        student_id=2,
        outcome=outcome,
        score=score,
        passed_count=1 if outcome == RunOutcome.ACCEPTED else 0,
        total_count=2,
    )
    session.add(version)
    session.add(attempt)
    session.add(run)
    session.commit()
    return attempt


def test_student_facing_lab_record_write_route_is_not_registered(fastapi_app):
    """Lab records are projections, never a public student grade-write API."""
    assert not any(
        isinstance(route, APIRoute)
        and getattr(route.endpoint, "__name__", "") == "record_lab_result"
        and "POST" in route.methods
        for route in fastapi_app.routes
    )


def test_acm_finalize_sets_full_score_only_for_all_accepted_cases(session):
    """A stale weighted score cannot turn an all-AC attempt into a partial grade."""
    attempt = _terminal_attempt(session, outcome=RunOutcome.ACCEPTED, score=0.5)

    finalized = finalize_service.finalize_attempt(
        session,
        course_id=1,
        attempt_id=attempt.attempt_id,
        student_id=2,
    )

    assert finalized.status == AttemptStatus.FINALIZED
    assert finalized.passed is True
    assert finalized.final_score == 1.0


def test_acm_finalize_sets_zero_for_any_non_accepted_terminal_run(session):
    """Passing some weighted cases is diagnostic data, not a formal partial score."""
    attempt = _terminal_attempt(session, outcome=RunOutcome.WRONG_ANSWER, score=0.9)

    finalized = finalize_service.finalize_attempt(
        session,
        course_id=1,
        attempt_id=attempt.attempt_id,
        student_id=2,
    )

    assert finalized.status == AttemptStatus.FAILED
    assert finalized.passed is False
    assert finalized.final_score == 0.0


def test_free_sandbox_quota_allows_only_ten_runs_per_student_course_window(session):
    """The non-scored port stores a small counter, never a code artifact."""
    for _ in range(10):
        assert free_sandbox_quota_service.consume(session, course_id=701, student_id=702) == 0
    assert free_sandbox_quota_service.consume(session, course_id=701, student_id=702) > 0


def test_formal_execution_lease_is_single_holder_across_worker_processes(session):
    """A database lease complements, rather than replaces, the local semaphore."""
    assert sandbox_execution_lease_service.acquire(session, task_id="formal-task-a") is True
    session.commit()
    assert sandbox_execution_lease_service.acquire(session, task_id="formal-task-b") is False
    sandbox_execution_lease_service.release(session, task_id="formal-task-a")
    session.commit()
    assert sandbox_execution_lease_service.acquire(session, task_id="formal-task-b") is True
