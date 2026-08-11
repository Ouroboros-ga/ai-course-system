"""Restart recovery for deterministic PPT manifest workers.

Unlike paid media providers, a PPT manifest task is a deterministic binding of
already-uploaded course assets.  It is therefore safe to requeue after a
process restart.  The actual resource limit remains in ``LocalTaskWorker``.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import select

from app.models.media_release_model import MediaGenerationJob, MediaGenerationStatus
from app.models.task_model import TaskRecord
from app.platform.tasks.worker import LocalTaskWorker, SessionFactory
from app.services.task_service import task_service

logger = logging.getLogger(__name__)


async def recover_media_manifest_tasks(
    session_factory: SessionFactory,
    worker: LocalTaskWorker,
) -> int:
    """Requeue only restart-interrupted PPT manifest jobs with safe payloads."""
    submissions: list[tuple[str, dict]] = []
    with session_factory() as session:
        records = list(session.exec(select(TaskRecord).where(
            TaskRecord.task_type == "media.ppt_manifest",
            TaskRecord.status == "interrupted",
        )).all())
        for record in records:
            try:
                payload = json.loads(record.input_payload or "{}")
            except (TypeError, ValueError):
                logger.warning("Cannot recover PPT manifest task %s: invalid payload", record.task_id)
                continue
            course_id = int(payload.get("course_id") or 0)
            job_id = str(payload.get("job_id") or "")
            release_id = str(payload.get("release_id") or "")
            if not course_id or not job_id or not release_id:
                logger.warning("Cannot recover PPT manifest task %s: incomplete payload", record.task_id)
                continue
            job = session.exec(select(MediaGenerationJob).where(
                MediaGenerationJob.course_id == course_id,
                MediaGenerationJob.job_id == job_id,
                MediaGenerationJob.task_id == record.task_id,
            )).first()
            if job is None or job.status == MediaGenerationStatus.SUCCEEDED:
                continue
            task_service.retry(session, record.task_id)
            job.status = MediaGenerationStatus.PENDING
            job.error_code = ""
            job.error_message_safe = ""
            job.finished_at = None
            session.add(job)
            session.commit()
            submissions.append((record.task_id, payload))
    for task_id, payload in submissions:
        worker.submit(session_factory, task_id, payload)
    if submissions:
        logger.info("Recovered %d PPT manifest task(s)", len(submissions))
    return len(submissions)
