"""
Domain models for student memory.

StudentProfile: stable student learning profile (course-scoped).
MemoryEntry: a single piece of memory with evidence refs, confidence, lifecycle.
CourseMemory: aggregate of MemoryEntry instances for a student+course scope.
TeachingStrategy: recommended strategy derived from memory.
MemoryContext: token-budgeted context for injection into QA prompts.

Version: 1.0 (draft)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.student_memory.enums import (
    STUDENT_MEMORY_VERSION,
    LifecycleState,
    MemorySource,
    MemoryType,
    StrategyType,
)


@dataclass(frozen=True)
class StudentProfile:
    """Stable student learning profile, scoped to a single course.

    This represents explicit information about a student relevant to
    their learning in a specific course context. It is NOT a free-form
    chat summary -- every field has a defined source.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID this profile belongs to.
    profile_id : str
        Globally unique identifier (UUID4).
    preferred_difficulty : str or None
        Student's preferred difficulty level (e.g. ``easy``, ``medium``, ``hard``).
    learning_style : str or None
        Stated learning style preference (e.g. ``visual``, ``auditory``).
    known_background : str or None
        Known background or prerequisite knowledge.
    goals : list of str
        Student's stated learning goals for this course.
    accommodations : list of str
        Accessibility or accommodation needs.
    source : str
        Originating system identifier.
    timestamp : str
        ISO 8601 UTC timestamp.
    metadata : dict
        Additional structured data.
    version : str
        Schema version.
    """

    student_id: int = field(compare=False)
    course_id: int = field(compare=False)
    profile_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    preferred_difficulty: Optional[str] = None
    learning_style: Optional[str] = None
    known_background: Optional[str] = None
    goals: List[str] = field(default_factory=list)
    accommodations: List[str] = field(default_factory=list)
    source: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = STUDENT_MEMORY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "course_id": self.course_id,
            "profile_id": self.profile_id,
            "preferred_difficulty": self.preferred_difficulty,
            "learning_style": self.learning_style,
            "known_background": self.known_background,
            "goals": self.goals,
            "accommodations": self.accommodations,
            "source": self.source,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> StudentProfile:
        return StudentProfile(
            student_id=data["student_id"],
            course_id=data["course_id"],
            profile_id=data.get("profile_id", str(uuid.uuid4())),
            preferred_difficulty=data.get("preferred_difficulty"),
            learning_style=data.get("learning_style"),
            known_background=data.get("known_background"),
            goals=data.get("goals", []),
            accommodations=data.get("accommodations", []),
            source=data.get("source", ""),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", STUDENT_MEMORY_VERSION),
        )


@dataclass(frozen=True)
class MemoryEntry:
    """A single piece of student memory with evidence references.

    Every derived memory MUST retain evidence refs (to P1-07 LearningEvidence
    evidence_ids) and a generation reason. Free-form chat summaries MUST NOT
    be written directly into long-term memory.

    Parameters
    ----------
    entry_id : str
        Globally unique identifier (UUID4).
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    memory_type : MemoryType
        The type of memory.
    source : MemorySource
        The source of this memory entry.
    content : str
        The memory content text.
    confidence : float
        Confidence score 0.0-1.0.
    evidence_refs : list of str
        List of P1-07 LearningEvidence evidence_ids that support this memory.
        MUST be non-empty for derived memories.
    generation_reason : str
        Human-readable explanation of why this memory was generated.
    lifecycle_state : LifecycleState
        Current lifecycle state (default ACTIVE).
    node_id : int or None
        Optional node-level scope.
    expires_at : str or None
        ISO 8601 UTC timestamp when this entry expires.
    corrected_by : str or None
        entry_id of the correction if this entry was corrected.
    correction_for : str or None
        entry_id of the entry this entry corrects.
    timestamp : str
        ISO 8601 UTC creation timestamp.
    metadata : dict
        Additional structured data.
    version : str
        Schema version.
    """

    student_id: int = field(compare=False)
    course_id: int = field(compare=False)
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = MemoryType.KNOWLEDGE
    source: MemorySource = MemorySource.EVENT_DERIVED
    content: str = ""
    confidence: float = 0.0
    evidence_refs: List[str] = field(default_factory=list)
    generation_reason: str = ""
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    node_id: Optional[int] = None
    expires_at: Optional[str] = None
    corrected_by: Optional[str] = None
    correction_for: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = STUDENT_MEMORY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "memory_type": self.memory_type.value,
            "source": self.source.value,
            "content": self.content,
            "confidence": self.confidence,
            "evidence_refs": self.evidence_refs,
            "generation_reason": self.generation_reason,
            "lifecycle_state": self.lifecycle_state.value,
            "node_id": self.node_id,
            "expires_at": self.expires_at,
            "corrected_by": self.corrected_by,
            "correction_for": self.correction_for,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> MemoryEntry:
        return MemoryEntry(
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            student_id=data["student_id"],
            course_id=data["course_id"],
            memory_type=MemoryType(data.get("memory_type", "knowledge")),
            source=MemorySource(data.get("source", "event_derived")),
            content=data.get("content", ""),
            confidence=data.get("confidence", 0.0),
            evidence_refs=data.get("evidence_refs", []),
            generation_reason=data.get("generation_reason", ""),
            lifecycle_state=LifecycleState(
                data.get("lifecycle_state", "active")
            ),
            node_id=data.get("node_id"),
            expires_at=data.get("expires_at"),
            corrected_by=data.get("corrected_by"),
            correction_for=data.get("correction_for"),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", STUDENT_MEMORY_VERSION),
        )

    def is_readable(self) -> bool:
        """Check if this entry should be readable.

        Returns False if soft-deleted or hard-deleted or expired.
        """
        return self.lifecycle_state not in (
            LifecycleState.SOFT_DELETED,
            LifecycleState.EXPIRED,
        )

    def is_writable(self) -> bool:
        """Check if this entry can be written to (not soft-deleted)."""
        return self.lifecycle_state != LifecycleState.SOFT_DELETED


@dataclass
class CourseMemory:
    """Aggregate of MemoryEntry instances for a student+course scope.

    Controls memory enable/disable state. When disabled, memory is neither
    read nor written for this student+course pair.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    enabled : bool
        Whether memory is enabled for this student+course (default True).
    entries : dict of str -> MemoryEntry
        Map of entry_id to MemoryEntry.
    profile : StudentProfile or None
        The student profile for this course.
    """

    student_id: int
    course_id: int
    enabled: bool = True
    entries: Dict[str, MemoryEntry] = field(default_factory=dict)
    profile: Optional[StudentProfile] = None

    def add_entry(self, entry: MemoryEntry) -> None:
        """Add a memory entry if memory is enabled."""
        if not self.enabled:
            raise MemoryDisabledError(
                f"Memory is disabled for student {self.student_id} "
                f"in course {self.course_id}"
            )
        if entry.student_id != self.student_id:
            raise ValueError(
                f"Entry student_id {entry.student_id} does not match "
                f"CourseMemory student_id {self.student_id}"
            )
        if entry.course_id != self.course_id:
            raise ValueError(
                f"Entry course_id {entry.course_id} does not match "
                f"CourseMemory course_id {self.course_id}"
            )
        self.entries[entry.entry_id] = entry

    def get_readable_entries(self) -> List[MemoryEntry]:
        """Return all readable (not deleted, not expired) entries."""
        return [
            e for e in self.entries.values()
            if e.is_readable() and not self._is_expired(e)
        ]

    def _is_expired(self, entry: MemoryEntry) -> bool:
        """Check if an entry has passed its expiry time."""
        if entry.expires_at is None:
            return False
        try:
            now = datetime.now(timezone.utc)
            expiry = datetime.fromisoformat(entry.expires_at)
            return now >= expiry
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "course_id": self.course_id,
            "enabled": self.enabled,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
            "profile": self.profile.to_dict() if self.profile else None,
        }


class MemoryDisabledError(Exception):
    """Raised when an operation is attempted on disabled memory."""


@dataclass(frozen=True)
class TeachingStrategy:
    """A recommended teaching strategy derived from student memory.

    Parameters
    ----------
    strategy_id : str
        Globally unique identifier (UUID4).
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    strategy_type : StrategyType
        The type of teaching strategy.
    priority : float
        Priority score 0.0-1.0 (higher = more recommended).
    reason : str
        Human-readable explanation of why this strategy is recommended.
    memory_refs : list of str
        MemoryEntry entry_ids that support this strategy.
    evidence_refs : list of str
        LearningEvidence evidence_ids that support this strategy.
    parameters : dict
        Strategy-specific parameters.
    timestamp : str
        ISO 8601 UTC timestamp.
    metadata : dict
        Additional structured data.
    version : str
        Schema version.
    """

    student_id: int
    course_id: int
    strategy_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    strategy_type: StrategyType = StrategyType.SCAFFOLDING
    priority: float = 0.5
    reason: str = ""
    memory_refs: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = STUDENT_MEMORY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "strategy_type": self.strategy_type.value,
            "priority": self.priority,
            "reason": self.reason,
            "memory_refs": self.memory_refs,
            "evidence_refs": self.evidence_refs,
            "parameters": self.parameters,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> TeachingStrategy:
        return TeachingStrategy(
            strategy_id=data.get("strategy_id", str(uuid.uuid4())),
            student_id=data["student_id"],
            course_id=data["course_id"],
            strategy_type=StrategyType(
                data.get("strategy_type", "scaffolding")
            ),
            priority=data.get("priority", 0.5),
            reason=data.get("reason", ""),
            memory_refs=data.get("memory_refs", []),
            evidence_refs=data.get("evidence_refs", []),
            parameters=data.get("parameters", {}),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            version=data.get("version", STUDENT_MEMORY_VERSION),
        )


@dataclass(frozen=True)
class MemoryContext:
    """Token-budgeted memory context for injection into QA prompts.

    This is the output of the context selector: a filtered, prioritized
    subset of memory entries within a token budget, ready for prompt
    injection.

    Parameters
    ----------
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    entries : list of MemoryEntry
        The selected memory entries (may be empty).
    profile : StudentProfile or None
        The student profile (may be None if excluded by budget).
    strategies : list of TeachingStrategy
        Selected teaching strategies.
    total_tokens : int
        Estimated token count of the context.
    budget_tokens : int
        The token budget that was applied.
    truncated : bool
        Whether entries were truncated due to budget.
    """
    student_id: int
    course_id: int
    entries: List[MemoryEntry] = field(default_factory=list)
    profile: Optional[StudentProfile] = None
    strategies: List[TeachingStrategy] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 0
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "student_id": self.student_id,
            "course_id": self.course_id,
            "entries": [e.to_dict() for e in self.entries],
            "profile": self.profile.to_dict() if self.profile else None,
            "strategies": [s.to_dict() for s in self.strategies],
            "total_tokens": self.total_tokens,
            "budget_tokens": self.budget_tokens,
            "truncated": self.truncated,
        }
