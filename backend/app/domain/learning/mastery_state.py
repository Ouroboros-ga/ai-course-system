"""
MasteryState: explainable mastery state derived from LearningEvidence.

Every MasteryState MUST list LearningEvidence references that support it.
No evidence => no strong conclusion.

Version: 1.0
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MASTERY_VERSION = "1.0"


class MasteryLevel(str, enum.Enum):
    """Canonical mastery levels with clear semantics."""

    UNKNOWN = "unknown"
    """No evidence available to determine mastery."""
    BEGINNER = "beginner"
    """Student is at the beginning stage; limited exposure."""
    DEVELOPING = "developing"
    """Student has some understanding but significant gaps remain."""
    PROFICIENT = "proficient"
    """Student demonstrates solid understanding of core concepts."""
    ADVANCED = "advanced"
    """Student demonstrates deep understanding and can apply knowledge."""


class MasterySource(str, enum.Enum):
    """Source of the mastery assessment."""

    RULE_BASED = "rule_based"
    """Deterministic rule-based assessment."""
    BKT = "bkt"
    """Bayesian Knowledge Tracing (interface only)."""
    IRT = "irt"
    """Item Response Theory (interface only)."""
    DKT = "dkt"
    """Deep Knowledge Tracing (interface only)."""
    MANUAL = "manual"
    """Manually assigned by a teacher."""


@dataclass(frozen=True)
class MasteryState:
    """Explainable mastery state for a student on a specific scope.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    mastery_id : str
        Globally unique identifier.
    node_id : int or None
        Optional node-level scope. If None, the state is course-level.
    level : MasteryLevel
        The assessed mastery level.
    score : float
        Numeric mastery score 0.0-1.0.
    confidence : float
        Confidence in the assessment 0.0-1.0.
    evidence_refs : list of str
        LearningEvidence evidence_ids that support this state.
        MUST be non-empty for non-UNKNOWN levels.
    source : MasterySource
        How this state was derived.
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
    mastery_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_id: Optional[int] = None
    level: MasteryLevel = MasteryLevel.UNKNOWN
    score: float = 0.0
    confidence: float = 0.0
    evidence_refs: List[str] = field(default_factory=list)
    source: MasterySource = MasterySource.RULE_BASED
    source_version: str = "1.0"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = MASTERY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mastery_id": self.mastery_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "level": self.level.value,
            "score": self.score,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "source": self.source.value,
            "source_version": self.source_version,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> MasteryState:
        return MasteryState(
            mastery_id=data["mastery_id"],
            student_id=data["student_id"],
            course_id=data["course_id"],
            node_id=data.get("node_id"),
            level=MasteryLevel(data.get("level", "unknown")),
            score=data.get("score", 0.0),
            confidence=data.get("confidence", 0.0),
            evidence_refs=data.get("evidence_refs", []),
            source=MasterySource(data.get("source", "rule_based")),
            source_version=data.get("source_version", "1.0"),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", MASTERY_VERSION),
        )
