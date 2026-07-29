"""Course-scoped identity resolution for graph, cognition and question data.

The graph payload uses the stable public ``node_key`` (``kn_*``), while the
legacy question/cognitive tables use the numeric ``CourseKnowledgeNode.id``.
All conversions must be course-scoped so an ID from another course can never
be accepted accidentally.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.models.graph_production_model import CourseKnowledgeNode


def get_course_knowledge_node(
    session: Session,
    course_id: int,
    ref: int | str | None,
) -> Optional[CourseKnowledgeNode]:
    """Resolve a numeric identity or stable node key within one course."""
    if ref is None or ref == "":
        return None
    if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
        return session.exec(
            select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == course_id,
                CourseKnowledgeNode.id == int(ref),
            )
        ).first()
    return session.exec(
        select(CourseKnowledgeNode).where(
            CourseKnowledgeNode.course_id == course_id,
            CourseKnowledgeNode.node_key == str(ref),
        )
    ).first()


def resolve_node_key(
    session: Session,
    course_id: int,
    ref: int | str | None,
) -> Optional[str]:
    node = get_course_knowledge_node(session, course_id, ref)
    return node.node_key if node else None


def resolve_node_id(
    session: Session,
    course_id: int,
    ref: int | str | None,
) -> Optional[int]:
    node = get_course_knowledge_node(session, course_id, ref)
    return node.id if node else None


def snapshot_node_identity(
    session: Session,
    course_id: int,
    payload: dict[str, Any] | None,
) -> Optional[CourseKnowledgeNode]:
    """Resolve an assembled snapshot node by identity_id or node key."""
    if not isinstance(payload, dict):
        return None
    return get_course_knowledge_node(
        session,
        course_id,
        payload.get("identity_id") or payload.get("id") or payload.get("node_id"),
    )
