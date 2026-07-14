"""
MisconceptionState: explainable misconception state derived from LearningEvidence.

Every MisconceptionState MUST list LearningEvidence references that support it.
No evidence => no strong conclusion.

Version: 1.0
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

MISCONCEPTION_VERSION = "1.0"


class MisconceptionType(str, enum.Enum):
    """Types of misconceptions that can be identified."""

    CONCEPTUAL = "conceptual"
    """Fundamental misunderstanding of a concept."""
    PROCEDURAL = "procedural"
    """Error in applying a procedure or method."""
    FACTUAL = "factual"
    """Incorrect factual knowledge."""
    PREREQUISITE = "prerequisite"
    """Missing prerequisite knowledge causing misunderstanding."""
    PERSISTENT_ERROR = "persistent_error"
    """Repeated error pattern across multiple attempts."""
    OVERGENERALIZATION = "overgeneralization"
    """Applying a concept too broadly or incorrectly generalizing."""


class MisconceptionSeverity(str, enum.Enum):
    """Severity level of a misconception."""

    LOW = "low"
    """Minor misunderstanding, easily corrected."""
    MEDIUM = "medium"
    """Moderate misunderstanding that may affect related concepts."""
    HIGH = "high"
    """Significant misunderstanding that blocks further learning."""
    CRITICAL = "critical"
    """Fundamental error requiring immediate intervention."""


@dataclass(frozen=True)
class MisconceptionState:
    """An explainable misconception identified for a student.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    misconception_id : str
        Globally unique identifier.
    node_id : int or None
        Optional node-level scope.
    misconception_type : MisconceptionType
        The type of misconception.
    severity : MisconceptionSeverity
        How severe the misconception is.
    concept : str
        The concept or topic the misconception relates to.
    description : str
        Human-readable description of the misconception.
    evidence_refs : list of str
        LearningEvidence evidence_ids supporting this finding.
        MUST be non-empty.
    confidence : float
        Confidence score 0.0-1.0.
    source : str
        The component that identified this misconception.
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
    misconception_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    node_id: Optional[int] = None
    misconception_type: MisconceptionType = MisconceptionType.CONCEPTUAL
    severity: MisconceptionSeverity = MisconceptionSeverity.MEDIUM
    concept: str = ""
    description: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = ""
    source_version: str = "1.0"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = MISCONCEPTION_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "misconception_id": self.misconception_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "node_id": self.node_id,
            "misconception_type": self.misconception_type.value,
            "severity": self.severity.value,
            "concept": self.concept,
            "description": self.description,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "source": self.source,
            "source_version": self.source_version,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> MisconceptionState:
        return MisconceptionState(
            misconception_id=data["misconception_id"],
            student_id=data["student_id"],
            course_id=data["course_id"],
            node_id=data.get("node_id"),
            misconception_type=MisconceptionType(
                data.get("misconception_type", "conceptual")
            ),
            severity=MisconceptionSeverity(
                data.get("severity", "medium")
            ),
            concept=data.get("concept", ""),
            description=data.get("description", ""),
            evidence_refs=data.get("evidence_refs", []),
            confidence=data.get("confidence", 0.0),
            source=data.get("source", ""),
            source_version=data.get("source_version", "1.0"),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", MISCONCEPTION_VERSION),
        )
