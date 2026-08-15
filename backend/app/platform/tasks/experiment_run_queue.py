"""Restart recovery for durable formal experiment runs.

Formal code evaluation has one authoritative result: ``ExperimentRun``.  A
restart may interrupt task bookkeeping, but it must never evaluate an already
finished run again or turn a cancelled run into a grade.  This module only
requeues pending, uncancelled runs whose attempt remains submitted.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlmodel import select

from app.models.experiment_model import AttemptStatus, ExperimentAttempt, ExperimentRun, RunOutcome
from app.models.task_model import TaskEventRecord, TaskRecord
from app.platform.tasks.worker import LocalTaskWorker, SessionFactory
from app.services.task_service import task_service

logger = logging.getLogger(__name__)


def _payload_for_record(record: TaskRecord) -> dict[str, Any] | None:
    try:
        payload = json.loads(record.input_payload or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _terminal_result_data(run: ExperimentRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "outcome": run.outcome.value,
        "passed_count": run.passed_count,
        "total_count": run.total_count,
        "score": run.score,
    }


async def recover_experiment_run_tasks(
    session_factory: SessionFactory,
    worker: LocalTaskWorker,
) -> int:
    """Requeue only safe formal runs, reconciling already-finished results.

    ``TaskRecord`` rows are locked while their associated run is checked so
    two application instances cannot both transition an interrupted task back
    to pending.  The database execution lease in the handler remains the
    second, cross-process guard around Judge0 itself.
    """
    submissions: list[tuple[str, dict[str, Any]]] = []
    with session_factory() as session:
        records = list(session.exec(
            select(TaskRecord)
            .where(
                TaskRecord.task_type == "experiment_run",
                TaskRecord.status.in_(["pending", "interrupted"]),
            )
            .with_for_update()
        ).all())
        for record in records:
            payload = _payload_for_record(record)
            if payload is None:
                logger.warning("Cannot recover experiment task %s: invalid payload", record.task_id)
                continue

            try:
                course_id = int(payload.get("course_id") or 0)
                student_id = int(payload.get("student_id") or 0)
            except (TypeError, ValueError):
                logger.warning("Cannot recover experiment task %s: invalid scope", record.task_id)
                continue
            attempt_id = str(payload.get("attempt_id") or "")
            run_id = str(payload.get("run_id") or "")
            if (
                not course_id
                or not student_id
                or not attempt_id
                or not run_id
                or record.course_id != course_id
                or record.owner_user_id != student_id
            ):
                logger.warning("Cannot recover experiment task %s: payload does not match task scope", record.task_id)
                continue

            run = session.exec(select(ExperimentRun).where(
                ExperimentRun.task_id == record.task_id,
                ExperimentRun.run_id == run_id,
                ExperimentRun.attempt_id == attempt_id,
                ExperimentRun.course_id == course_id,
                ExperimentRun.student_id == student_id,
            )).first()
            attempt = session.exec(select(ExperimentAttempt).where(
                ExperimentAttempt.attempt_id == attempt_id,
                ExperimentAttempt.course_id == course_id,
                ExperimentAttempt.student_id == student_id,
            )).first()
            if run is None or attempt is None:
                logger.warning("Cannot recover experiment task %s: run or attempt is missing", record.task_id)
                continue

            if run.cancel_requested_at is not None:
                task_service.reconcile_experiment_run_terminal(
                    session,
                    record.task_id,
                    terminal_status="cancelled",
                )
                continue

            if run.outcome != RunOutcome.PENDING or run.finished_at is not None:
                if run.outcome == RunOutcome.SANDBOX_UNAVAILABLE:
                    task_service.reconcile_experiment_run_terminal(
                        session,
                        record.task_id,
                        terminal_status="failed",
                        error_code="SANDBOX_UNAVAILABLE",
                        error_message=run.error_message or "sandbox unavailable",
                        retryable=True,
                    )
                elif run.outcome != RunOutcome.PENDING:
                    task_service.reconcile_experiment_run_terminal(
                        session,
                        record.task_id,
                        terminal_status="succeeded",
                        result_ref=f"experiment_run://{run.run_id}",
                        result_data=_terminal_result_data(run),
                    )
                continue

            if attempt.status != AttemptStatus.SUBMITTED:
                logger.warning(
                    "Cannot recover experiment task %s: attempt is %s",
                    record.task_id,
                    attempt.status.value,
                )
                continue

            if record.status == "interrupted":
                task_service.retry(session, record.task_id)
            else:
                session.add(TaskEventRecord(
                    task_id=record.task_id,
                    event_type="recovered",
                    stage="queued",
                    message="formal experiment task queued during startup recovery",
                ))
                session.commit()
            submissions.append((record.task_id, {
                "course_id": course_id,
                "attempt_id": attempt_id,
                "run_id": run_id,
                "student_id": student_id,
            }))

    for task_id, payload in submissions:
        worker.submit(session_factory, task_id, payload)
    if submissions:
        logger.info("Recovered %d formal experiment run task(s)", len(submissions))
    return len(submissions)
