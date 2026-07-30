"""Durable post-answer cognition and recommendation projection."""
from __future__ import annotations

import asyncio
import threading
from typing import Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.database import session_factory
from app.models.knowledge_bundle_model import (
    LearningProjectionOutbox,
    ProjectionOutboxStatus,
)
from app.services.recommendation_service import refresh_cognition_and_recommendation


MAX_RETRIES = 5
RETRY_DELAYS_SECONDS = (1, 2, 5, 10, 30)
_dispatch_lock = threading.Lock()
_dispatching_event_ids: set[str] = set()


def enqueue_learning_projection(
    session: Session,
    *,
    attempt_id: int,
    student_id: int,
    course_id: int,
    knowledge_node_id: int | None,
) -> Optional[LearningProjectionOutbox]:
    if knowledge_node_id is None:
        return None
    existing = session.exec(select(LearningProjectionOutbox).where(
        LearningProjectionOutbox.attempt_id == attempt_id,
        LearningProjectionOutbox.knowledge_node_id == knowledge_node_id,
    )).first()
    if existing is not None:
        if existing.status in {
            ProjectionOutboxStatus.PENDING,
            ProjectionOutboxStatus.PROCESSING,
            ProjectionOutboxStatus.SUCCEEDED,
        }:
            return existing
        existing.status = ProjectionOutboxStatus.PENDING
        existing.retry_count = 0
        existing.last_error = ""
        existing.processed_at = None
        session.add(existing)
        return existing
    event = LearningProjectionOutbox(
        attempt_id=attempt_id,
        student_id=student_id,
        course_id=course_id,
        knowledge_node_id=knowledge_node_id,
        status=ProjectionOutboxStatus.PENDING,
    )
    session.add(event)
    session.flush()
    return event


def consume_learning_projection(event_id: str) -> tuple[int | None, str | None]:
    with session_factory() as session:
        event = session.exec(select(LearningProjectionOutbox).where(
            LearningProjectionOutbox.event_id == event_id,
        )).first()
        if event is None:
            return None, None
        if event.status == ProjectionOutboxStatus.SUCCEEDED:
            return None, None
        if event.status == ProjectionOutboxStatus.PROCESSING:
            return None, None
        if event.retry_count >= MAX_RETRIES:
            return None, None
        event.status = ProjectionOutboxStatus.PROCESSING
        event.retry_count += 1
        session.add(event)
        session.commit()
        try:
            state, recommendation = refresh_cognition_and_recommendation(
                session,
                student_id=event.student_id,
                course_id=event.course_id,
                node_id=event.knowledge_node_id,
            )
            event = session.exec(select(LearningProjectionOutbox).where(
                LearningProjectionOutbox.event_id == event_id,
            )).first()
            if event is None:
                return (
                    state.id if state else None,
                    recommendation.recommendation_id if recommendation else None,
                )
            event.status = ProjectionOutboxStatus.SUCCEEDED
            event.last_error = ""
            event.processed_at = utcnow_aware()
            session.add(event)
            session.commit()
            return (
                state.id if state else None,
                recommendation.recommendation_id if recommendation else None,
            )
        except Exception as exc:
            session.rollback()
            event = session.exec(select(LearningProjectionOutbox).where(
                LearningProjectionOutbox.event_id == event_id,
            )).first()
            if event is not None:
                event.status = (
                    ProjectionOutboxStatus.FAILED
                    if event.retry_count >= MAX_RETRIES
                    else ProjectionOutboxStatus.PENDING
                )
                event.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                session.add(event)
                session.commit()
            return None, None


def _projection_status(event_id: str) -> ProjectionOutboxStatus | None:
    with session_factory() as session:
        event = session.exec(select(LearningProjectionOutbox).where(
            LearningProjectionOutbox.event_id == event_id,
        )).first()
        return event.status if event else None


async def _consume_with_retries(event_id: str) -> None:
    try:
        while True:
            await asyncio.to_thread(consume_learning_projection, event_id)
            status = await asyncio.to_thread(_projection_status, event_id)
            if status != ProjectionOutboxStatus.PENDING:
                return
            with session_factory() as session:
                event = session.exec(select(LearningProjectionOutbox).where(
                    LearningProjectionOutbox.event_id == event_id,
                )).first()
                retry_count = event.retry_count if event else MAX_RETRIES
            if retry_count >= MAX_RETRIES:
                return
            delay_index = min(max(retry_count - 1, 0), len(RETRY_DELAYS_SECONDS) - 1)
            await asyncio.sleep(RETRY_DELAYS_SECONDS[delay_index])
    finally:
        with _dispatch_lock:
            _dispatching_event_ids.discard(event_id)


def _run_dispatch_loop(event_id: str) -> None:
    asyncio.run(_consume_with_retries(event_id))


def dispatch_learning_projection(event_id: str | None) -> None:
    if not event_id:
        return
    with _dispatch_lock:
        if event_id in _dispatching_event_ids:
            return
        _dispatching_event_ids.add(event_id)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        threading.Thread(
            target=_run_dispatch_loop,
            args=(event_id,),
            name=f"learning-projection-{event_id}",
            daemon=True,
        ).start()
        return
    loop.create_task(_consume_with_retries(event_id))


async def recover_learning_projection_outbox() -> None:
    with session_factory() as session:
        events = session.exec(select(LearningProjectionOutbox).where(
            LearningProjectionOutbox.status.in_([
                ProjectionOutboxStatus.PENDING,
                ProjectionOutboxStatus.PROCESSING,
            ]),
            LearningProjectionOutbox.retry_count < MAX_RETRIES,
        ).order_by(LearningProjectionOutbox.created_at).limit(100)).all()
        event_ids = [event.event_id for event in events]
        for event in events:
            if event.status == ProjectionOutboxStatus.PROCESSING:
                event.status = ProjectionOutboxStatus.PENDING
                session.add(event)
        session.commit()
    for event_id in event_ids:
        dispatch_learning_projection(event_id)
