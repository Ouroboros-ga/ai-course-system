"""Owner-serial scheduler for durable document_parse tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlmodel import select

from app.core.time_utils import utcnow_aware
from app.models.document_parse_model import DocumentParseOwnerLease, DocumentParseRun, ParseRunStatus
from app.models.task_model import TaskEventRecord, TaskRecord
from app.platform.tasks.worker import LocalTaskWorker, SessionFactory

logger = logging.getLogger(__name__)


class DocumentParseQueue:
    """One active parser per account, while independent owners run in parallel."""

    def __init__(self) -> None:
        self._runners: dict[int, asyncio.Task[None]] = {}

    def submit(self, session_factory: SessionFactory, worker: LocalTaskWorker, task_id: str) -> None:
        with session_factory() as session:
            task = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
            if task is None or task.task_type != "document_parse":
                return
            owner_id = task.owner_user_id
        current = self._runners.get(owner_id)
        if current is None or current.done():
            self._runners[owner_id] = asyncio.create_task(self._drain(session_factory, worker, owner_id))

    async def recover(self, session_factory: SessionFactory, worker: LocalTaskWorker) -> None:
        owners: set[int] = set()
        with session_factory() as session:
            leases = list(session.exec(select(DocumentParseOwnerLease)).all())
            for lease in leases:
                task = session.exec(select(TaskRecord).where(TaskRecord.task_id == lease.task_id)).first()
                if task and task.status == "running":
                    task.status = "pending"; task.stage = "queued"; task.started_at = None; task.updated_at = utcnow_aware()
                    session.add(task)
                    run = session.exec(select(DocumentParseRun).where(DocumentParseRun.task_id == task.task_id)).first()
                    if run and run.status == ParseRunStatus.RUNNING:
                        run.status = ParseRunStatus.PENDING; run.started_at = None; run.updated_at = utcnow_aware(); session.add(run)
                    session.add(TaskEventRecord(task_id=task.task_id, event_type="recovered", stage="queued", message="服务重启后已重新排队"))
                session.delete(lease)
            owners.update(session.exec(select(TaskRecord.owner_user_id).where(
                TaskRecord.task_type == "document_parse", TaskRecord.status == "pending"
            )).all())
            session.commit()
        for owner_id in owners:
            self._start_owner(session_factory, worker, owner_id)

    def _start_owner(self, session_factory: SessionFactory, worker: LocalTaskWorker, owner_id: int) -> None:
        current = self._runners.get(owner_id)
        if current is None or current.done():
            self._runners[owner_id] = asyncio.create_task(self._drain(session_factory, worker, owner_id))

    async def _drain(self, session_factory: SessionFactory, worker: LocalTaskWorker, owner_id: int) -> None:
        while True:
            claim = self._claim_next(session_factory, owner_id)
            if claim is None:
                return
            task_id, payload, token = claim
            try:
                await worker.run_inline(session_factory, task_id, payload)
            finally:
                self._release(session_factory, owner_id, token)

    @staticmethod
    def _claim_next(session_factory: SessionFactory, owner_id: int) -> tuple[str, dict[str, Any], str] | None:
        with session_factory() as session:
            now = utcnow_aware()
            lease = session.exec(select(DocumentParseOwnerLease).where(
                DocumentParseOwnerLease.owner_user_id == owner_id
            )).first()
            if lease and lease.lease_expires_at and lease.lease_expires_at > now:
                return None
            task = session.exec(select(TaskRecord).where(
                TaskRecord.owner_user_id == owner_id,
                TaskRecord.task_type == "document_parse",
                TaskRecord.status == "pending",
            ).order_by(TaskRecord.created_at)).first()
            if task is None:
                if lease: session.delete(lease); session.commit()
                return None
            token = uuid.uuid4().hex
            if lease is None:
                lease = DocumentParseOwnerLease(owner_user_id=owner_id)
            lease.task_id = task.task_id; lease.lease_token = token
            lease.lease_expires_at = now + timedelta(minutes=30); lease.updated_at = now
            session.add(lease); session.commit()
            try: payload = json.loads(task.input_payload or "{}")
            except (TypeError, ValueError): payload = {}
            return task.task_id, payload, token

    @staticmethod
    def _release(session_factory: SessionFactory, owner_id: int, token: str) -> None:
        with session_factory() as session:
            lease = session.exec(select(DocumentParseOwnerLease).where(
                DocumentParseOwnerLease.owner_user_id == owner_id,
                DocumentParseOwnerLease.lease_token == token,
            )).first()
            if lease:
                session.delete(lease); session.commit()


document_parse_queue = DocumentParseQueue()
