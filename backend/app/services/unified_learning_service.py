"""Service for canonical learning events and deterministic projections."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.time_utils import to_aware, utcnow_aware
from app.models.course_build_model import CourseRelease, ReleaseStatus
from app.models.course_outline_model import CourseOutlineNode, OutlineNodeType
from app.models.access_control_model import CourseMembership, MembershipStatus
from app.models.cognitive_state_model import CognitiveState, QuestionDepthRecord, RecommendationRecord
from app.models.graph_production_model import CourseKnowledgeNode
from app.models.question_bank_model import QuestionAttempt
from app.models.agent_run_model import AgentLLMDiagnosticRecord
from app.models.agent_log import AgentLearningEvent
from app.models.unified_learning_model import (
    CourseLearningStatsProjection,
    ExposureStatus,
    LearningEvent,
    LearningEventType,
    StudentLearningProjection,
)

COMPLETION_THRESHOLD = 0.8


def active_release(session: Session, course_id: int) -> CourseRelease | None:
    return session.exec(select(CourseRelease).where(
        CourseRelease.course_id == course_id,
        CourseRelease.status == ReleaseStatus.PUBLISHED,
        CourseRelease.is_active == True,
    )).first()


def ordered_outline_nodes(
    session: Session,
    *,
    outline_version_id: str,
    knowledge_points_only: bool = False,
) -> list[CourseOutlineNode]:
    """Return a deterministic pre-order traversal of a versioned outline.

    ``order_index`` is only unique among siblings, so a flat SQL sort by that
    column can reorder nodes from different sections.  The learner player and
    learning projection must share one tree traversal; ties are resolved by the
    immutable node id rather than a client-generated index.
    """
    nodes = list(session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == outline_version_id,
    )).all())
    children: dict[str | None, list[CourseOutlineNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_node_id, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda node: (node.order_index, node.outline_node_id))

    ordered: list[CourseOutlineNode] = []
    visited: set[str] = set()

    def visit(node: CourseOutlineNode) -> None:
        if node.outline_node_id in visited:
            return
        visited.add(node.outline_node_id)
        if not knowledge_points_only or node.node_type == OutlineNodeType.KNOWLEDGE_POINT:
            ordered.append(node)
        for child in children.get(node.outline_node_id, []):
            visit(child)

    for root in children.get(None, []):
        visit(root)
    # Preserve malformed/orphaned historical rows without looping forever.
    for node in sorted(nodes, key=lambda item: (item.order_index, item.outline_node_id)):
        visit(node)
    return ordered


def release_nodes(session: Session, release: CourseRelease) -> list[CourseOutlineNode]:
    return ordered_outline_nodes(
        session,
        outline_version_id=release.outline_version_id,
        knowledge_points_only=True,
    )


def _node(session: Session, release: CourseRelease, outline_node_id: str) -> CourseOutlineNode | None:
    return session.exec(select(CourseOutlineNode).where(
        CourseOutlineNode.outline_version_id == release.outline_version_id,
        CourseOutlineNode.outline_node_id == outline_node_id,
        CourseOutlineNode.node_type == OutlineNodeType.KNOWLEDGE_POINT,
    )).first()


def _ratio(payload: dict[str, Any], event_type: LearningEventType) -> float:
    if event_type == LearningEventType.EXPLICIT_COMPLETE:
        return 1.0
    for key in ("completion_ratio", "progress_ratio", "ratio"):
        if key in payload:
            try:
                return max(0.0, min(1.0, float(payload[key])))
            except (TypeError, ValueError):
                pass
    if "duration" in payload and "position" in payload:
        try:
            duration = float(payload["duration"])
            return max(0.0, min(1.0, float(payload["position"]) / duration)) if duration > 0 else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    return 0.0


def record_event(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    release_id: str,
    outline_node_id: str,
    event_type: LearningEventType,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    source: str = "learn_page",
) -> tuple[LearningEvent, StudentLearningProjection]:
    release = session.exec(select(CourseRelease).where(
        CourseRelease.course_id == course_id,
        CourseRelease.release_id == release_id,
        CourseRelease.status.in_([ReleaseStatus.PUBLISHED, ReleaseStatus.SUPERSEDED, ReleaseStatus.ROLLED_BACK]),
    )).first()
    if release is None:
        raise ValueError("RELEASE_NOT_FOUND")
    node = _node(session, release, outline_node_id)
    if node is None:
        raise ValueError("NODE_NOT_IN_RELEASE")
    existing = session.exec(select(LearningEvent).where(
        LearningEvent.student_id == student_id,
        LearningEvent.idempotency_key == idempotency_key,
    )).first()
    if existing:
        if (
            existing.course_id != course_id
            or existing.release_id != release_id
            or existing.outline_node_id != outline_node_id
            or existing.event_type != event_type
        ):
            # Reusing a browser/request key for another scope must fail closed;
            # silently treating it as a duplicate would leak or misattribute
            # a learning fact across courses/releases/nodes.
            raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
        projection = session.exec(select(StudentLearningProjection).where(
            StudentLearningProjection.student_id == student_id,
            StudentLearningProjection.course_id == course_id,
            StudentLearningProjection.release_id == release_id,
            StudentLearningProjection.outline_node_id == outline_node_id,
        )).first()
        if projection is None:
            projection = _ensure_projection(session, student_id, course_id, release, node)
        return existing, projection
    payload = dict(payload or {})
    occurred_at = to_aware(occurred_at) if occurred_at else utcnow_aware()
    if occurred_at > utcnow_aware() + timedelta(minutes=5):
        raise ValueError("OCCURRED_AT_IN_FUTURE")
    event = LearningEvent(
        idempotency_key=idempotency_key,
        student_id=student_id,
        course_id=course_id,
        release_id=release_id,
        outline_node_id=outline_node_id,
        knowledge_node_key=node.knowledge_graph_node_id,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
        source=source,
    )
    session.add(event)
    session.flush()
    projection = _ensure_projection(session, student_id, course_id, release, node)
    now = occurred_at
    if projection.first_accessed_at is None:
        projection.first_accessed_at = now
    # SQLite drops timezone information when reloading DateTime columns even
    # when the model declares timezone=True.  Normalize the persisted value
    # before comparing it with the canonical aware event time.
    projection.last_accessed_at = max(
        to_aware(projection.last_accessed_at or now),
        now,
    )
    projection.visit_count += 1 if event_type == LearningEventType.NODE_OPENED else 0
    try:
        time_spent_delta = float(payload.get("time_spent_delta", 0) or 0)
    except (TypeError, ValueError):
        time_spent_delta = 0.0
    try:
        current_timestamp = float(payload.get("current_timestamp", 0) or 0)
    except (TypeError, ValueError):
        current_timestamp = 0.0
    try:
        current_page = int(payload.get("current_page", projection.current_page) or projection.current_page)
    except (TypeError, ValueError):
        current_page = projection.current_page
    projection.exposure_seconds += max(0, min(60, int(time_spent_delta)))
    projection.current_timestamp = max(projection.current_timestamp, max(0.0, current_timestamp))
    projection.current_page = max(1, current_page)
    ratio = _ratio(payload, event_type)
    projection.completion_ratio = max(projection.completion_ratio, ratio)
    if event_type == LearningEventType.EXPLICIT_COMPLETE or ratio >= COMPLETION_THRESHOLD:
        projection.exposure_status = ExposureStatus.COMPLETED
        projection.completion_ratio = 1.0
        projection.completion_reason = "explicit" if event_type == LearningEventType.EXPLICIT_COMPLETE else "threshold"
        projection.completed_at = projection.completed_at or now
    elif projection.first_accessed_at is not None:
        projection.exposure_status = ExposureStatus.IN_PROGRESS
    projection.last_event_id = event.event_id
    projection.updated_at = utcnow_aware()
    session.add(projection)
    return event, projection


def record_agent_learning_action(
    session: Session,
    *,
    student_id: int,
    course_id: int,
    release_id: str,
    outline_node_id: str,
    idempotency_key: str,
    action: str,
    payload: dict[str, Any],
) -> LearningEvent:
    """Persist a bounded review audit event without changing learning state.

    Accepting, dismissing, or returning from review is not evidence of
    exposure, completion, or mastery. It therefore bypasses the learner
    projection and does not queue any downstream evidence work.
    """
    release = session.exec(select(CourseRelease).where(
        CourseRelease.course_id == course_id,
        CourseRelease.release_id == release_id,
        CourseRelease.status.in_([
            ReleaseStatus.PUBLISHED,
            ReleaseStatus.SUPERSEDED,
            ReleaseStatus.ROLLED_BACK,
        ]),
    )).first()
    if release is None:
        raise ValueError("RELEASE_NOT_FOUND")
    node = _node(session, release, outline_node_id)
    if node is None:
        raise ValueError("NODE_NOT_IN_RELEASE")
    existing = session.exec(select(LearningEvent).where(
        LearningEvent.student_id == student_id,
        LearningEvent.idempotency_key == idempotency_key,
    )).first()
    if existing is not None:
        if (
            existing.course_id != course_id
            or existing.release_id != release_id
            or existing.outline_node_id != outline_node_id
            or existing.event_type != LearningEventType.AGENT_LEARNING_ACTION
            or existing.payload.get("action") != action
        ):
            raise ValueError("IDEMPOTENCY_KEY_CONFLICT")
        return existing
    event = LearningEvent(
        idempotency_key=idempotency_key,
        student_id=student_id,
        course_id=course_id,
        release_id=release_id,
        outline_node_id=outline_node_id,
        knowledge_node_key=node.knowledge_graph_node_id,
        event_type=LearningEventType.AGENT_LEARNING_ACTION,
        payload={"action": action, **payload},
        source="learning_adjustment",
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _ensure_projection(session: Session, student_id: int, course_id: int, release: CourseRelease, node: CourseOutlineNode) -> StudentLearningProjection:
    projection = session.exec(select(StudentLearningProjection).where(
        StudentLearningProjection.student_id == student_id,
        StudentLearningProjection.course_id == course_id,
        StudentLearningProjection.release_id == release.release_id,
        StudentLearningProjection.outline_node_id == node.outline_node_id,
    )).first()
    if projection is None:
        projection = StudentLearningProjection(
            student_id=student_id,
            course_id=course_id,
            release_id=release.release_id,
            outline_node_id=node.outline_node_id,
            knowledge_node_key=node.knowledge_graph_node_id,
        )
        session.add(projection)
        session.flush()
    return projection


def student_context(session: Session, *, student_id: int, course_id: int, release_id: str | None = None) -> dict[str, Any]:
    release = active_release(session, course_id) if release_id is None else session.exec(select(CourseRelease).where(
        CourseRelease.course_id == course_id,
        CourseRelease.release_id == release_id,
    )).first()
    if release is None:
        return {"course_id": course_id, "release_id": None, "items": [], "total": 0, "completed": 0}
    nodes = release_nodes(session, release)
    projections = session.exec(select(StudentLearningProjection).where(
        StudentLearningProjection.student_id == student_id,
        StudentLearningProjection.course_id == course_id,
        StudentLearningProjection.release_id == release.release_id,
    )).all()
    by_id = {p.outline_node_id: p for p in projections}
    items = []
    for node in nodes:
        p = by_id.get(node.outline_node_id)
        items.append({
            "outline_node_id": node.outline_node_id,
            "title": node.title,
            "node_type": node.node_type.value,
            "knowledge_node_key": node.knowledge_graph_node_id,
            "learning": {
                "status": p.exposure_status.value if p else ExposureStatus.NOT_STARTED.value,
                "completion_ratio": p.completion_ratio if p else 0.0,
                "exposure_seconds": p.exposure_seconds if p else 0,
                "current_timestamp": p.current_timestamp if p else 0.0,
                "current_page": p.current_page if p else 1,
                "completion_reason": p.completion_reason if p else None,
            },
            "cognition": {"status": "not_available" if not node.knowledge_graph_node_id else "unknown"},
            "recommendation": {"status": "not_available" if not node.knowledge_graph_node_id else "pending"},
        })
    completed = sum(1 for item in items if item["learning"]["status"] == ExposureStatus.COMPLETED.value)
    # SQLite may return legacy timestamps without tzinfo even though the
    # canonical model writes aware datetimes. Compare by epoch seconds so a
    # mixed historical database cannot crash the read model.
    latest = max(
        (p for p in projections if p.last_accessed_at),
        key=lambda p: p.last_accessed_at.timestamp(),
        default=None,
    )
    return {
        "course_id": course_id,
        "release_id": release.release_id,
        "items": items,
        "total": len(items),
        "completed": completed,
        "completion_rate": completed / len(items) if items else 0.0,
        "recent_anchor": {
            "outline_node_id": latest.outline_node_id,
            "current_timestamp": latest.current_timestamp,
            "current_page": latest.current_page,
            "last_accessed_at": latest.last_accessed_at.isoformat() if latest and latest.last_accessed_at else None,
        } if latest else None,
    }


def refresh_course_stats(session: Session, *, course_id: int, release_id: str) -> None:
    release = session.exec(select(CourseRelease).where(CourseRelease.course_id == course_id, CourseRelease.release_id == release_id)).first()
    if release is None:
        return
    nodes = release_nodes(session, release)
    memberships = session.exec(select(CourseMembership).where(CourseMembership.course_id == course_id, CourseMembership.status == MembershipStatus.ACTIVE)).all()
    student_ids = [m.user_id for m in memberships if m.role.value == "student" and not m.analytics_excluded]
    for node in nodes:
        projection_query = select(StudentLearningProjection).where(
            StudentLearningProjection.course_id == course_id,
            StudentLearningProjection.release_id == release_id,
            StudentLearningProjection.outline_node_id == node.outline_node_id,
        )
        if student_ids:
            projection_query = projection_query.where(StudentLearningProjection.student_id.in_(student_ids))
        else:
            projection_query = projection_query.where(StudentLearningProjection.student_id == -1)
        rows = session.exec(projection_query).all()
        counts = {status.value: 0 for status in ExposureStatus}
        for row in rows:
            counts[row.exposure_status.value] += 1
        stat = session.exec(select(CourseLearningStatsProjection).where(
            CourseLearningStatsProjection.course_id == course_id,
            CourseLearningStatsProjection.release_id == release_id,
            CourseLearningStatsProjection.outline_node_id == node.outline_node_id,
        )).first()
        if stat is None:
            stat = CourseLearningStatsProjection(course_id=course_id, release_id=release_id, outline_node_id=node.outline_node_id)
        stat.student_count = len(student_ids)
        stat.not_started_count = max(
            0,
            len(student_ids)
            - counts[ExposureStatus.IN_PROGRESS.value]
            - counts[ExposureStatus.COMPLETED.value],
        )
        stat.in_progress_count = counts[ExposureStatus.IN_PROGRESS.value]
        stat.completed_count = counts[ExposureStatus.COMPLETED.value]
        mastery_distribution: dict[str, int] = {}
        unknown_mastery_count = 0
        low_confidence_count = 0
        pending_recommendation_count = 0
        knowledge = None
        if node.knowledge_graph_node_id:
            knowledge = session.exec(select(CourseKnowledgeNode).where(
                CourseKnowledgeNode.course_id == course_id,
                CourseKnowledgeNode.node_key == node.knowledge_graph_node_id,
            )).first()
        if knowledge is not None:
            states = session.exec(select(CognitiveState).where(
                CognitiveState.course_id == course_id,
                CognitiveState.node_id == knowledge.id,
                CognitiveState.is_latest == True,
                CognitiveState.student_id.in_(student_ids) if student_ids else CognitiveState.student_id == -1,
            )).all()
            for state in states:
                level = state.mastery_level or "unknown"
                mastery_distribution[level] = mastery_distribution.get(level, 0) + 1
                if level == "unknown":
                    unknown_mastery_count += 1
                if state.evidence_confidence is None or state.evidence_confidence < 0.5:
                    low_confidence_count += 1
            recommendations = session.exec(select(RecommendationRecord).where(
                RecommendationRecord.course_id == course_id,
                RecommendationRecord.knowledge_node_id == knowledge.id,
                RecommendationRecord.consumed == False,
                RecommendationRecord.student_id.in_(student_ids) if student_ids else RecommendationRecord.student_id == -1,
            )).all()
            pending_recommendation_count = len({item.student_id for item in recommendations})
        unknown_mastery_count += max(0, len(student_ids) - sum(mastery_distribution.values()))
        stat.mastery_distribution = mastery_distribution
        stat.unknown_mastery_count = unknown_mastery_count
        stat.low_confidence_count = low_confidence_count
        stat.pending_recommendation_count = pending_recommendation_count
        stat.computed_at = utcnow_aware()
        session.add(stat)


def _day_buckets(days: int, now: datetime) -> list[tuple[datetime, datetime]]:
    """Return ``days`` inclusive [start, end] day buckets ending at today."""
    start = (now - timedelta(days=max(1, days - 1))).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    buckets: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor <= end:
        day_end = cursor.replace(hour=23, minute=59, second=59, microsecond=999999)
        buckets.append((cursor, day_end))
        cursor += timedelta(days=1)
    return buckets


def course_trend_and_metrics(
    session: Session,
    *,
    course_id: int,
    days: int = 7,
) -> dict[str, Any]:
    """Aggregate daily trend series and course-lifetime core metrics.

    Trend is near-real-time and windowed: mastery comes from the daily average
    of ``cognitive_states.mastery_score`` recomputation snapshots; activity is
    the distinct active students per day in ``learning_events``; questioning is
    the daily count of scored ``question_attempts``. Core metrics are cumulative
    over the whole course, not just the window, so they stay stable for teachers.
    """
    now = utcnow_aware()
    buckets = _day_buckets(days, now)
    date_strs = [b[0].strftime("%Y-%m-%d") for b in buckets]
    window_start = buckets[0][0]
    window_end = buckets[-1][1]

    active_per_day: dict[str, set[int]] = {ds: set() for ds in date_strs}
    events = session.exec(select(LearningEvent).where(
        LearningEvent.course_id == course_id,
        LearningEvent.occurred_at >= window_start,
        LearningEvent.occurred_at <= window_end,
    )).all()
    for event in events:
        ds = event.occurred_at.strftime("%Y-%m-%d")
        if ds in active_per_day:
            active_per_day[ds].add(event.student_id)

    mastery_per_day: dict[str, list[float]] = {ds: [] for ds in date_strs}
    states = session.exec(select(CognitiveState).where(
        CognitiveState.course_id == course_id,
        CognitiveState.computed_at >= window_start,
        CognitiveState.computed_at <= window_end,
    )).all()
    for state in states:
        if state.mastery_score is None:
            continue
        ds = state.computed_at.strftime("%Y-%m-%d")
        if ds in mastery_per_day:
            mastery_per_day[ds].append(state.mastery_score)

    questioning_per_day: dict[str, int] = {ds: 0 for ds in date_strs}
    attempts = session.exec(select(QuestionAttempt).where(
        QuestionAttempt.course_id == course_id,
        QuestionAttempt.created_at >= window_start,
        QuestionAttempt.created_at <= window_end,
    )).all()
    for attempt in attempts:
        ds = attempt.created_at.strftime("%Y-%m-%d")
        if ds in questioning_per_day:
            questioning_per_day[ds] += 1

    return {
        "trend": {
            "dates": date_strs,
            "activity": [len(active_per_day[ds]) for ds in date_strs],
            "mastery": [
                round(sum(mastery_per_day[ds]) / len(mastery_per_day[ds]), 3)
                if mastery_per_day[ds]
                else None
                for ds in date_strs
            ],
            "questioning": [questioning_per_day[ds] for ds in date_strs],
        },
        "core_metrics": _course_core_metrics(session, course_id=course_id),
    }


def _course_core_metrics(session: Session, *, course_id: int) -> dict[str, Any]:
    projections = session.exec(select(StudentLearningProjection).where(
        StudentLearningProjection.course_id == course_id,
    )).all()

    llm_rows = session.exec(select(AgentLLMDiagnosticRecord).where(
        AgentLLMDiagnosticRecord.course_id == course_id,
    )).all()
    ai_calls = len(llm_rows)
    ai_success = sum(
        1 for row in llm_rows
        if row.finish_reason and row.finish_reason not in ("error", "length", "content_filter")
    )
    ai_avg_latency_ms = round(
        sum(row.latency_ms or 0.0 for row in llm_rows) / ai_calls
    ) if ai_calls else 0.0

    question_count = session.exec(select(func.count()).select_from(QuestionDepthRecord).where(
        QuestionDepthRecord.course_id == course_id,
    )).one()

    interaction_count = session.exec(select(func.count()).select_from(AgentLearningEvent).where(
        AgentLearningEvent.course_id == course_id,
    )).one()

    answer_rows = session.exec(select(QuestionAttempt).where(
        QuestionAttempt.course_id == course_id,
    )).all()
    answer_count = len(answer_rows)
    correct = sum(1 for row in answer_rows if row.is_correct is True)
    answer_accuracy = round(correct / answer_count, 3) if answer_count else 0.0

    total_study_seconds = sum(row.exposure_seconds or 0 for row in projections)
    active_students = len({row.student_id for row in projections if (row.exposure_seconds or 0) > 0})
    return {
        "ai_calls": ai_calls,
        "ai_success_rate": round(ai_success / ai_calls, 3) if ai_calls else 0.0,
        "ai_avg_latency_ms": ai_avg_latency_ms,
        "question_count": int(question_count),
        "interaction_count": int(interaction_count),
        "total_study_seconds": total_study_seconds,
        "avg_study_seconds": round(total_study_seconds / active_students) if active_students else 0,
        "answer_count": answer_count,
        "answer_accuracy": answer_accuracy,
        "active_students": active_students,
    }
