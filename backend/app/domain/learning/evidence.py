"""
LearningEvidence: derived evidence from LearningEvents.

Evidence is computed by aggregating one or more LearningEvents according
to defined rules. Every evidence record references the events that support it.
No evidence => no strong conclusion.

Version: 1.0
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

EVIDENCE_VERSION = "1.0"


class EvidenceType(str, enum.Enum):
    """Canonical evidence types derived from events."""

    # Completion evidence
    NODE_COMPLETION = "node_completion"
    """Evidence that a node was completed."""
    COURSE_COMPLETION = "course_completion"
    """Evidence that a course was completed."""

    # Quiz evidence
    QUIZ_ACCURACY = "quiz_accuracy"
    """Evidence of quiz accuracy over a window of quiz events."""
    QUIZ_PATTERN = "quiz_pattern"
    """Evidence of repeated error patterns in quizzes."""

    # Engagement evidence
    ENGAGEMENT = "engagement"
    """Evidence of student engagement (access frequency, time spent)."""
    QUESTIONING = "questioning"
    """Evidence of questioning activity."""

    # Prerequisite evidence
    PREREQ_GAP = "prereq_gap"
    """Evidence of prerequisite knowledge gaps."""
    PREREQ_RECOVERY = "prereq_recovery"
    """Evidence of successful prerequisite gap recovery."""

    # Correction evidence
    CORRECTION = "correction"
    """Evidence that a prior evidence or event was corrected."""

    # Mastery-derived evidence
    MASTERY = "mastery"
    """Evidence used to compute or justify a mastery score."""

    # Recommendation evidence
    RECOMMENDATION = "recommendation"
    """Evidence supporting a recommendation."""


@dataclass(frozen=True)
class LearningEvidence:
    """A piece of evidence derived from one or more LearningEvents.

    Parameters
    ----------
    evidence_type : EvidenceType
        The type of evidence.
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    evidence_id : str
        Globally unique evidence identifier (UUID4).
    node_id : int or None
        The script node ID if scoped to a node.
    event_refs : list of str
        List of LearningEvent event_ids that support this evidence.
    confidence : float
        Confidence score 0.0-1.0 for this evidence.
    value : float or None
        Numeric value if applicable (e.g. accuracy rate 0.85).
    label : str
        Human-readable label for this evidence.
    description : str
        Human-readable description.
    source : str
        The component that generated this evidence
        (e.g. ``aggregation``, ``rule_baseline``, ``compat_mapper``).
    timestamp : str
        ISO 8601 UTC timestamp.
    metadata : dict
        Additional structured data.
    version : str
        Schema version.
    """

    evidence_type: EvidenceType = field(compare=False)
    student_id: int = field(compare=False)
    course_id: int = field(compare=False)
    # evidence_id 默认使用 ev_ 前缀 + UUID hex，符合 project_memory.md 硬约束。
    evidence_id: str = field(default_factory=lambda: "ev_" + uuid.uuid4().hex)
    node_id: Optional[int] = None
    event_refs: List[str] = field(default_factory=list)
    confidence: float = 0.0
    value: Optional[float] = None
    label: str = ""
    description: str = ""
    source: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = EVIDENCE_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "event_refs": self.event_refs,
            "confidence": self.confidence,
            "value": self.value,
            "label": self.label,
            "description": self.description,
            "source": self.source,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> LearningEvidence:
        return LearningEvidence(
            evidence_id=data["evidence_id"],
            evidence_type=EvidenceType(data["evidence_type"]),
            student_id=data["student_id"],
            course_id=data["course_id"],
            node_id=data.get("node_id"),
            event_refs=data.get("event_refs", []),
            confidence=data.get("confidence", 0.0),
            value=data.get("value"),
            label=data.get("label", ""),
            description=data.get("description", ""),
            source=data.get("source", ""),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", EVIDENCE_VERSION),
        )


@dataclass(frozen=True)
class EvidenceAggregationRule:
    """Declarative rule describing how evidence is aggregated from events.

    Parameters
    ----------
    rule_id : str
        Stable rule identifier.
    name : str
        Human-readable rule name.
    description : str
        What this rule does.
    evidence_type : EvidenceType
        The type of evidence this rule produces.
    min_events : int
        Minimum number of events required to produce evidence.
    window_seconds : int or None
        Time window in seconds for sliding-window aggregation.
    aggregation_method : str
        How to aggregate: ``count``, ``rate``, ``latest``, ``average``,
        ``trend``, ``pattern``.
    source : str
        Component that owns this rule.
    """

    rule_id: str
    name: str
    description: str
    evidence_type: EvidenceType
    min_events: int = 1
    window_seconds: Optional[int] = None
    aggregation_method: str = "count"
    source: str = "aggregation"
