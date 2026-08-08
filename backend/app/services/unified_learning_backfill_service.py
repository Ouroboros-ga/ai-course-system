"""Idempotent historical backfill for the canonical learning projection.

This is deliberately a callable service rather than an application-startup
side effect. Deployment runs it with an explicit batch id after Alembic.
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.models.course_build_model import CourseRelease
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.progress_model import LearningProgress, NodeProgress
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.unified_learning_model import LearningEventType
from app.services.learning_evidence_context_service import upsert_learning_evidence_context
from app.services.unified_learning_service import record_event


def backfill_learning_projection(session: Session, *, batch_id: str, course_id: int | None = None) -> dict[str, int | str]:
    """Backfill only deterministically mappable node rows.

    Legacy numeric node ids are not guessed against new outline ids. Rows that
    cannot be mapped are counted as unknown and left untouched for audit.
    """
    releases = session.exec(select(CourseRelease).where(CourseRelease.course_id == course_id) if course_id else select(CourseRelease)).all()
    emitted = 0
    unknown = 0
    evidence_contexts = 0
    for release in releases:
        if not release.outline_version_id:
            continue
        nodes = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.outline_version_id == release.outline_version_id,
            CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
        )).all()
        by_outline = {node.outline_node_id: node for node in nodes}
        progress_rows = session.exec(select(LearningProgress).where(LearningProgress.course_id == release.course_id)).all()
        for progress in progress_rows:
            node_rows = session.exec(select(NodeProgress).where(NodeProgress.progress_id == progress.id)).all()
            for row in node_rows:
                # Old numeric ids have no safe relationship to outline_node_id.
                candidate = by_outline.get(str(row.node_id))
                if candidate is None:
                    unknown += 1
                    continue
                event_type = LearningEventType.EXPLICIT_COMPLETE if row.is_completed else LearningEventType.NODE_OPENED
                try:
                    record_event(
                        session,
                        student_id=progress.user_id,
                        course_id=release.course_id,
                        release_id=release.release_id,
                        outline_node_id=candidate.outline_node_id,
                        event_type=event_type,
                        idempotency_key=f"backfill:{batch_id}:{progress.user_id}:{release.release_id}:{candidate.outline_node_id}",
                        payload={"source": "legacy_progress", "time_spent_delta": row.time_spent, "completion_ratio": 1.0 if row.is_completed else 0.0},
                        source="migration_backfill",
                    )
                    emitted += 1
                except ValueError:
                    unknown += 1
    evidence_query = select(LearningEvidenceRecord)
    if course_id is not None:
        evidence_query = evidence_query.where(LearningEvidenceRecord.course_id == course_id)
    for evidence in session.exec(evidence_query).all():
        upsert_learning_evidence_context(session, evidence)
        evidence_contexts += 1
    session.commit()
    return {"batch_id": batch_id, "emitted": emitted, "unknown": unknown, "evidence_contexts": evidence_contexts}
