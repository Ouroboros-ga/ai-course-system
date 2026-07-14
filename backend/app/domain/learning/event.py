"""
LearningEvent: append-only fact representing student learning activity.

Events are immutable once created. Corrections are represented as new events
with a correction reference (never mutate existing events). Every event has
a stable idempotency key derived from (event_type, student_id, course_id,
sequence_number) so retries are safe.

Version: 1.0
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

EVENT_VERSION = "1.0"
"""Current event schema version (major.minor)."""


class EventType(str, enum.Enum):
    """Canonical learning event types."""

    # Progress events
    NODE_ACCESSED = "node_accessed"
    """Student accessed/started a learning node."""
    NODE_COMPLETED = "node_completed"
    """Student marked or reached completion of a node."""
    COURSE_ACCESSED = "course_accessed"
    """Student accessed the course."""
    COURSE_COMPLETED = "course_completed"
    """Student completed the course."""

    # Quiz events
    QUIZ_ANSWERED = "quiz_answered"
    """Student answered a quiz question."""
    QUIZ_CORRECT = "quiz_correct"
    """Student answered correctly (derived)."""
    QUIZ_INCORRECT = "quiz_incorrect"
    """Student answered incorrectly (derived)."""

    # Chat/QA events
    QUESTION_ASKED = "question_asked"
    """Student asked a question in chat."""
    ANSWER_RECEIVED = "answer_received"
    """Student received an answer."""

    # Prerequisite/jump events
    PREREQ_GAP_DETECTED = "prereq_gap_detected"
    """A prerequisite knowledge gap was identified."""
    PREREQ_JUMP_STARTED = "prereq_jump_started"
    """Student started a prerequisite review jump."""
    PREREQ_JUMP_RETURNED = "prereq_jump_returned"
    """Student returned from a prerequisite review jump."""

    # Correction events
    CORRECTION = "correction"
    """A correction event that references a previous event."""

    # Placeholder for future expansion
    EXERCISE_SUBMITTED = "exercise_submitted"
    """Student submitted an exercise."""
    FEEDBACK_RECEIVED = "feedback_received"
    """Student received explicit feedback."""


@dataclass(frozen=True)
class LearningEvent:
    """An append-only fact about student learning activity.

    Parameters
    ----------
    event_type : EventType
        The type of event.
    student_id : int
        The student user ID.
    course_id : int
        The course ID this event belongs to.
    sequence_number : int
        Monotonically increasing sequence for the student+course scope,
        used in the idempotency key.
    event_id : str
        Globally unique event identifier (UUID4).
    node_id : int or None
        The script node ID if applicable.
    timestamp : str
        ISO 8601 UTC timestamp of when the event occurred.
    idempotency_key : str
        Stable key for retry safety: ``{event_type}:{student_id}:{course_id}:{seq}``.
    metadata : dict
        Additional structured data (e.g. score, question text, answer).
    source : str
        The originating system (e.g. ``progress_service``, ``qa_service``,
        ``prerequisite_service``, ``quiz``, ``compat_mapper``).
    corrected_event_id : str or None
        If this event is a correction of a previous event, the corrected
        event's ID. None for non-correction events.
    version : str
        Schema version at creation time.
    """

    event_type: EventType = field(compare=False)
    student_id: int = field(compare=False)
    course_id: int = field(compare=False)
    sequence_number: int
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_id: Optional[int] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    idempotency_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)
    source: str = ""
    corrected_event_id: Optional[str] = None
    version: str = EVENT_VERSION

    def __post_init__(self) -> None:
        """Auto-generate idempotency_key if not provided."""
        if not self.idempotency_key:
            # Frozen dataclass workaround
            object.__setattr__(
                self,
                "idempotency_key",
                self._build_idempotency_key(),
            )

    def _build_idempotency_key(self) -> str:
        return (
            f"{self.event_type.value}:{self.student_id}:"
            f"{self.course_id}:{self.sequence_number}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "sequence_number": self.sequence_number,
            "idempotency_key": self.idempotency_key,
            "metadata": self.metadata,
            "source": self.source,
            "corrected_event_id": self.corrected_event_id,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> LearningEvent:
        """Deserialize from a dict (for round-trip compatibility)."""
        return LearningEvent(
            event_id=data["event_id"],
            event_type=EventType(data["event_type"]),
            student_id=data["student_id"],
            course_id=data["course_id"],
            node_id=data.get("node_id"),
            timestamp=data.get("timestamp", ""),
            sequence_number=data.get("sequence_number", 0),
            idempotency_key=data.get("idempotency_key", ""),
            metadata=data.get("metadata", {}),
            source=data.get("source", ""),
            corrected_event_id=data.get("corrected_event_id"),
            version=data.get("version", EVENT_VERSION),
        )


@dataclass(frozen=True)
class EventCorrection:
    """A correction record referencing an original event and providing new data.

    This is a convenience wrapper around creating a correction-type LearningEvent.
    The actual correction is represented as a new event, not a mutation.
    """

    original_event_id: str
    corrected_event_id: str
    reason: str
    corrected_fields: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_event_id": self.original_event_id,
            "corrected_event_id": self.corrected_event_id,
            "reason": self.reason,
            "corrected_fields": self.corrected_fields,
            "timestamp": self.timestamp,
        }


def build_correction_event(
    original_event: LearningEvent,
    reason: str,
    new_sequence_number: int,
    corrected_metadata: Optional[Dict[str, Any]] = None,
    student_id: Optional[int] = None,
    course_id: Optional[int] = None,
    source: str = "correction",
) -> LearningEvent:
    """Create a new correction LearningEvent that references an original event.

    Parameters
    ----------
    original_event : LearningEvent
        The event being corrected.
    reason : str
        Human-readable reason for the correction.
    new_sequence_number : int
        The next sequence number for this student+course.
    corrected_metadata : dict or None
        Replacement metadata. If None, original metadata is kept.
    student_id : int or None
        Override student_id (defaults to original).
    course_id : int or None
        Override course_id (defaults to original).
    source : str
        Source identifier for the correction.

    Returns
    -------
    LearningEvent
        A new event of type CORRECTION referencing the original.
    """
    return LearningEvent(
        event_type=EventType.CORRECTION,
        student_id=student_id or original_event.student_id,
        course_id=course_id or original_event.course_id,
        node_id=original_event.node_id,
        sequence_number=new_sequence_number,
        metadata={
            "reason": reason,
            "original_event_type": original_event.event_type.value,
            "corrected_metadata": corrected_metadata or original_event.metadata,
        },
        source=source,
        corrected_event_id=original_event.event_id,
    )
