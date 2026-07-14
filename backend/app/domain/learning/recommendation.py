"""
Recommendation: explainable learning recommendation derived from evidence.

Every Recommendation MUST list LearningEvidence references that support it.
No evidence => no strong recommendation.

Version: 1.0
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

RECOMMENDATION_VERSION = "1.0"


class RecommendationType(str, enum.Enum):
    """Types of learning recommendations."""

    REVIEW_NODE = "review_node"
    """Recommend reviewing a specific node."""
    PRACTICE_QUIZ = "practice_quiz"
    """Recommend additional quiz practice."""
    PREREQ_REVIEW = "prereq_review"
    """Recommend reviewing prerequisite material."""
    ADVANCE_NEXT = "advance_next"
    """Recommend advancing to the next node."""
    EXTRA_MATERIAL = "extra_material"
    """Recommend supplementary learning material."""
    TEACHER_CONSULT = "teacher_consult"
    """Recommend consulting the teacher."""
    REPEAT_MODULE = "repeat_module"
    """Recommend repeating an entire module."""
    CONTINUE = "continue"
    """No specific action needed; continue current path."""


class RecommendationPriority(str, enum.Enum):
    """Priority level for a recommendation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Recommendation:
    """An explainable recommendation for a student.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    recommendation_id : str
        Globally unique identifier.
    node_id : int or None
        Optional target node ID.
    recommendation_type : RecommendationType
        The type of recommendation.
    priority : RecommendationPriority
        Urgency/priority level.
    title : str
        Short title for the recommendation.
    description : str
        Human-readable explanation.
    evidence_refs : list of str
        LearningEvidence evidence_ids supporting this recommendation.
        MUST be non-empty for non-CONTINUE types.
    source : str
        The component that generated this recommendation.
    source_version : str
        Version of the source component.
    timestamp : str
        ISO 8601 UTC timestamp.
    metadata : dict
        Additional structured data.
    version : str
        Schema version.
    """

    student_id: int = field(compare=False)
    course_id: int = field(compare=False)
    recommendation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_id: Optional[int] = None
    recommendation_type: RecommendationType = RecommendationType.CONTINUE
    priority: RecommendationPriority = RecommendationPriority.LOW
    title: str = ""
    description: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    source: str = ""
    source_version: str = "1.0"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = RECOMMENDATION_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "recommendation_type": self.recommendation_type.value,
            "priority": self.priority.value,
            "title": self.title,
            "description": self.description,
            "evidence_refs": self.evidence_refs,
            "source": self.source,
            "source_version": self.source_version,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> Recommendation:
        return Recommendation(
            recommendation_id=data["recommendation_id"],
            student_id=data["student_id"],
            course_id=data["course_id"],
            node_id=data.get("node_id"),
            recommendation_type=RecommendationType(
                data.get("recommendation_type", "continue")
            ),
            priority=RecommendationPriority(
                data.get("priority", "low")
            ),
            title=data.get("title", ""),
            description=data.get("description", ""),
            evidence_refs=data.get("evidence_refs", []),
            source=data.get("source", ""),
            source_version=data.get("source_version", "1.0"),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", RECOMMENDATION_VERSION),
        )
