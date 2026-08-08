"""Governed linkage between formal evidence and learning identity.

Formal evidence is produced by the cognition/experiment services.  This
adapter records only the identity context that can be established safely; it
never turns exposure events into evidence and never guesses a release when a
knowledge node exists in more than one release.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from app.models.course_build_model import CourseRelease
from app.models.course_outline_model import CourseOutlineNode
from app.models.cognitive_state_model import LearningEvidenceRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.unified_learning_model import LearningEvidenceContext, LearningEvent


def _validate_source_identity(
    session: Session,
    evidence: LearningEvidenceRecord,
    *,
    source_release_id: Optional[str],
    outline_node_id: Optional[str],
    event_id: Optional[str],
) -> None:
    """Fail closed when a caller supplies release/node identity."""
    if bool(source_release_id) != bool(outline_node_id):
        raise ValueError("SOURCE_RELEASE_AND_OUTLINE_NODE_REQUIRED")
    if source_release_id:
        release = session.exec(select(CourseRelease).where(
            CourseRelease.course_id == evidence.course_id,
            CourseRelease.release_id == source_release_id,
        )).first()
        node = session.exec(select(CourseOutlineNode).where(
            CourseOutlineNode.course_id == evidence.course_id,
            CourseOutlineNode.outline_version_id == (release.outline_version_id if release else None),
            CourseOutlineNode.outline_node_id == outline_node_id,
        )).first()
        if release is None or node is None:
            raise ValueError("EVIDENCE_CONTEXT_NODE_NOT_IN_RELEASE")
    if event_id:
        event = session.exec(select(LearningEvent).where(
            LearningEvent.event_id == event_id,
            LearningEvent.course_id == evidence.course_id,
        )).first()
        if event is None:
            raise ValueError("EVIDENCE_CONTEXT_EVENT_NOT_IN_COURSE")
        if source_release_id and (
            event.release_id != source_release_id or event.outline_node_id != outline_node_id
        ):
            raise ValueError("EVIDENCE_CONTEXT_EVENT_IDENTITY_CONFLICT")


def upsert_learning_evidence_context(
    session: Session,
    evidence: LearningEvidenceRecord,
    *,
    source_release_id: Optional[str] = None,
    outline_node_id: Optional[str] = None,
    event_id: Optional[str] = None,
) -> LearningEvidenceContext:
    """Create or update the identity context for a formal evidence record.

    Callers may provide release/node/event identity when it is available from
    the scoring request.  A scored question currently carries no immutable
    release identity, so this adapter deliberately leaves those fields null
    rather than inferring them from the presently published outline. Existing
    values are never erased by a retry.
    """
    _validate_source_identity(
        session, evidence,
        source_release_id=source_release_id,
        outline_node_id=outline_node_id,
        event_id=event_id,
    )
    context = session.exec(
        select(LearningEvidenceContext).where(
            LearningEvidenceContext.evidence_id == evidence.evidence_id,
        )
    ).first()
    if context is None:
        context = LearningEvidenceContext(
            evidence_id=evidence.evidence_id,
            course_id=evidence.course_id,
            knowledge_node_key=None,
            source_release_id=source_release_id,
            outline_node_id=outline_node_id,
            event_id=event_id,
        )
    else:
        if source_release_id and context.source_release_id not in (None, source_release_id):
            raise ValueError("EVIDENCE_CONTEXT_RELEASE_CONFLICT")
        if outline_node_id and context.outline_node_id not in (None, outline_node_id):
            raise ValueError("EVIDENCE_CONTEXT_NODE_CONFLICT")
        if event_id and context.event_id not in (None, event_id):
            raise ValueError("EVIDENCE_CONTEXT_EVENT_CONFLICT")
        if source_release_id:
            context.source_release_id = source_release_id
        if outline_node_id:
            context.outline_node_id = outline_node_id
        if event_id and context.event_id is None:
            context.event_id = event_id

    if evidence.node_id is not None:
        knowledge = session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == evidence.course_id,
                CourseKnowledgeNode.id == evidence.node_id,
            )
        ).first()
        if knowledge is not None:
            context.knowledge_node_key = knowledge.node_key
    session.add(context)
    return context
