"""Course-serial durable scheduler for GraphRAG and vector build tasks."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.knowledge_bundle_model import (
    CourseKnowledgeBuildLease,
    CourseKnowledgeBundle,
    CourseVectorIndex,
    GraphRagRun,
    GraphRagRunStatus,
    KnowledgeBundleStatus,
    VectorIndexStatus,
)
from app.models.task_model import TaskEventRecord, TaskRecord
from app.platform.tasks.worker import LocalTaskWorker, SessionFactory


TASK_KIND = {
    "knowledge.graphrag_build": "graphrag",
    "knowledge.vector_index": "vector",
}


class KnowledgeBuildQueue:
    def __init__(self) -> None:
        self._runners: dict[tuple[int, str], asyncio.Task[None]] = {}

    def submit(
        self, session_factory: SessionFactory, worker: LocalTaskWorker, task_id: str
    ) -> None:
        with session_factory() as session:
            task = session.exec(select(TaskRecord).where(
                TaskRecord.task_id == task_id,
            )).first()
            if task is None or task.task_type not in TASK_KIND or task.course_id is None:
                return
            key = (int(task.course_id), TASK_KIND[task.task_type])
        self._start(session_factory, worker, key)

    async def recover(
        self, session_factory: SessionFactory, worker: LocalTaskWorker
    ) -> None:
        keys: set[tuple[int, str]] = set()
        with session_factory() as session:
            for lease in list(session.exec(select(CourseKnowledgeBuildLease)).all()):
                task = session.exec(select(TaskRecord).where(
                    TaskRecord.task_id == lease.task_id,
                )).first()
                if task is not None and task.status == "running":
                    task.status = "pending"
                    task.stage = "queued"
                    task.started_at = None
                    task.updated_at = utcnow_aware()
                    session.add(task)
                    self._reset_domain_state(session, task)
                    session.add(TaskEventRecord(
                        task_id=task.task_id,
                        event_type="recovered",
                        stage="queued",
                        message="服务重启后知识构建任务已重新排队",
                    ))
                session.delete(lease)
            pending = session.exec(select(TaskRecord).where(
                TaskRecord.task_type.in_(list(TASK_KIND)),
                TaskRecord.status == "pending",
            )).all()
            for task in pending:
                if task.course_id is not None:
                    keys.add((int(task.course_id), TASK_KIND[task.task_type]))
            session.commit()
        for key in keys:
            self._start(session_factory, worker, key)

    def _start(
        self,
        session_factory: SessionFactory,
        worker: LocalTaskWorker,
        key: tuple[int, str],
    ) -> None:
        current = self._runners.get(key)
        if current is None or current.done():
            self._runners[key] = asyncio.create_task(
                self._drain(session_factory, worker, key)
            )

    async def _drain(
        self,
        session_factory: SessionFactory,
        worker: LocalTaskWorker,
        key: tuple[int, str],
    ) -> None:
        while True:
            claim = self._claim_next(session_factory, key)
            if claim is None:
                return
            task_id, payload, token = claim
            try:
                await worker.run_inline(session_factory, task_id, payload)
            finally:
                self._release(session_factory, key, token)

    @staticmethod
    def _claim_next(
        session_factory: SessionFactory, key: tuple[int, str]
    ) -> tuple[str, dict, str] | None:
        course_id, kind = key
        with session_factory() as session:
            now = utcnow_aware()
            lease = session.exec(select(CourseKnowledgeBuildLease).where(
                CourseKnowledgeBuildLease.course_id == course_id,
                CourseKnowledgeBuildLease.lease_kind == kind,
            )).first()
            if lease is not None and lease.lease_expires_at > now:
                return None
            task_types = [
                task_type for task_type, lease_kind in TASK_KIND.items()
                if lease_kind == kind
            ]
            task = session.exec(select(TaskRecord).where(
                TaskRecord.course_id == course_id,
                TaskRecord.task_type.in_(task_types),
                TaskRecord.status == "pending",
            ).order_by(TaskRecord.created_at)).first()
            if task is None:
                if lease is not None:
                    session.delete(lease)
                    session.commit()
                return None
            token = uuid.uuid4().hex
            if lease is None:
                lease = CourseKnowledgeBuildLease(
                    course_id=course_id,
                    lease_kind=kind,
                    task_id=task.task_id,
                    lease_token=token,
                    lease_expires_at=now + timedelta(minutes=35),
                )
            else:
                lease.task_id = task.task_id
                lease.lease_token = token
                lease.lease_expires_at = now + timedelta(minutes=35)
            session.add(lease)
            session.commit()
            try:
                payload = json.loads(task.input_payload or "{}")
            except (TypeError, ValueError):
                payload = {}
            return task.task_id, payload, token

    @staticmethod
    def _release(
        session_factory: SessionFactory,
        key: tuple[int, str],
        token: str,
    ) -> None:
        with session_factory() as session:
            lease = session.exec(select(CourseKnowledgeBuildLease).where(
                CourseKnowledgeBuildLease.course_id == key[0],
                CourseKnowledgeBuildLease.lease_kind == key[1],
                CourseKnowledgeBuildLease.lease_token == token,
            )).first()
            if lease is not None:
                session.delete(lease)
                session.commit()

    @staticmethod
    def _reset_domain_state(session, task: TaskRecord) -> None:
        try:
            payload = json.loads(task.input_payload or "{}")
        except (TypeError, ValueError):
            payload = {}
        if task.task_type == "knowledge.graphrag_build":
            run = session.exec(select(GraphRagRun).where(
                GraphRagRun.run_id == payload.get("run_id"),
                GraphRagRun.course_id == task.course_id,
            )).first()
            if run is not None and run.status in {
                GraphRagRunStatus.EXPORTING,
                GraphRagRunStatus.EXTRACTING,
                GraphRagRunStatus.CLASSIFYING,
                GraphRagRunStatus.RECONCILING,
            }:
                run.status = GraphRagRunStatus.QUEUED
                session.add(run)
        elif task.task_type == "knowledge.vector_index":
            vector = session.exec(select(CourseVectorIndex).where(
                CourseVectorIndex.vector_index_id == payload.get("vector_index_id"),
                CourseVectorIndex.course_id == task.course_id,
            )).first()
            bundle = session.exec(select(CourseKnowledgeBundle).where(
                CourseKnowledgeBundle.bundle_id == payload.get("bundle_id"),
                CourseKnowledgeBundle.course_id == task.course_id,
            )).first()
            if vector is not None and vector.status in {
                VectorIndexStatus.BUILDING, VectorIndexStatus.VALIDATING,
            }:
                vector.status = VectorIndexStatus.QUEUED
                session.add(vector)
            if bundle is not None and bundle.status == KnowledgeBundleStatus.INDEXING:
                bundle.status = KnowledgeBundleStatus.APPROVED_PENDING_INDEX
                session.add(bundle)


knowledge_build_queue = KnowledgeBuildQueue()
