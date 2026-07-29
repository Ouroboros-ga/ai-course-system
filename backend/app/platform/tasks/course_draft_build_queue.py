"""Recovery for durable course-draft build tasks.

Unlike document parsing, a course build is not owner-serial.  It is still a
durable task, though: a local-process restart must not leave an otherwise ready
corpus with a permanently empty course structure.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.course_build_model import (
    CourseCorpusSnapshot,
    CourseDraftBuildStatus,
    CourseDraftBuildTask,
)
from app.models.task_model import TaskEventRecord, TaskRecord
from app.platform.tasks.worker import LocalTaskWorker, SessionFactory
from app.services.course_corpus_service import course_corpus_service
from app.services.task_service import task_service


logger = logging.getLogger(__name__)


async def recover_course_draft_build_queue(
    session_factory: SessionFactory,
    worker: LocalTaskWorker,
) -> int:
    """Requeue current corpus builds interrupted solely by process restart.

    We intentionally recover only records the startup sweep marked
    ``interrupted``.  Explicitly failed/cancelled builds remain visible for a
    teacher retry, and a superseded corpus is cancelled instead of generating
    a stale draft.
    """
    submissions: list[tuple[str, dict]] = []
    with session_factory() as session:
        builds = list(session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.status.in_([
                CourseDraftBuildStatus.QUEUED,
                CourseDraftBuildStatus.RUNNING,
            ]),
        )).all())
        for build in builds:
            if not build.task_id:
                continue
            task = session.exec(select(TaskRecord).where(
                TaskRecord.task_id == build.task_id,
                TaskRecord.task_type == "course_draft_build",
            )).first()
            if task is None or task.status != "interrupted":
                continue
            corpus = session.exec(select(CourseCorpusSnapshot).where(
                CourseCorpusSnapshot.corpus_snapshot_id == build.corpus_snapshot_id,
                CourseCorpusSnapshot.course_id == build.course_id,
            )).first()
            if corpus is None or not course_corpus_service.is_snapshot_current(session, corpus=corpus):
                build.status = CourseDraftBuildStatus.CANCELLED
                build.error_code = "CORPUS_CHANGED"
                build.error_message = "服务重启期间课程材料已变化，已等待新的课程语料快照"
                build.finished_at = utcnow_aware()
                session.add(build)
                session.add(TaskEventRecord(
                    task_id=task.task_id,
                    event_type="recovery_cancelled",
                    stage="course_corpus",
                    message=build.error_message,
                    error_code=build.error_code,
                    created_at=build.finished_at,
                ))
                continue

            task_service.retry(session, task.task_id)
            build.status = CourseDraftBuildStatus.QUEUED
            build.started_at = None
            build.finished_at = None
            build.error_code = ""
            build.error_message = ""
            session.add(build)
            session.add(TaskEventRecord(
                task_id=task.task_id,
                event_type="recovered",
                stage="course_corpus",
                message="服务重启后已恢复课程草稿构建队列",
                created_at=utcnow_aware(),
            ))
            try:
                payload = json.loads(task.input_payload or "{}")
            except (TypeError, ValueError):
                payload = {}
            submissions.append((task.task_id, payload))
        session.commit()

    for task_id, payload in submissions:
        worker.submit(session_factory, task_id, payload)
    if submissions:
        logger.info("Recovered %d course-draft build task(s)", len(submissions))
    return len(submissions)
