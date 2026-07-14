"""
Enums for the student memory domain.

Version: 1.0 (draft)
"""

from __future__ import annotations

import enum


STUDENT_MEMORY_VERSION = "1.0"
"""Current StudentMemory schema version (major.minor)."""


class MemoryType(str, enum.Enum):
    """Canonical types of student memory entries."""

    KNOWLEDGE = "knowledge"
    """Memory about knowledge the student has demonstrated."""

    MISCONCEPTION = "misconception"
    """Memory about a known misconception or error pattern."""

    PREFERENCE = "preference"
    """Memory about student learning preferences."""

    BEHAVIOR = "behavior"
    """Memory about observed learning behavior patterns."""

    STRATEGY = "strategy"
    """Memory about effective teaching strategies for this student."""

    GAP = "gap"
    """Memory about a knowledge gap that needs addressing."""

    STRENGTH = "strength"
    """Memory about a demonstrated strength."""

    PROGRESS = "progress"
    """Memory about overall progress patterns."""


class MemorySource(str, enum.Enum):
    """Source of a memory entry."""

    EVENT_DERIVED = "event_derived"
    """Derived from LearningEvents via aggregation rules."""

    TEACHER_INPUT = "teacher_input"
    """Explicitly provided by the teacher."""

    STUDENT_INPUT = "student_input"
    """Explicitly provided by the student (e.g., self-assessment)."""

    SYSTEM_INFERRED = "system_inferred"
    """Inferred by the system from observed patterns."""

    COMPAT_MAPPER = "compat_mapper"
    """Mapped from existing (pre-event) data for compatibility."""

    CORRECTION = "correction"
    """Result of a correction operation."""


class LifecycleState(str, enum.Enum):
    """Lifecycle state of a memory entry."""

    ACTIVE = "active"
    """The memory is active and can be read/written."""

    EXPIRING = "expiring"
    """The memory is nearing expiry; still readable."""

    EXPIRED = "expired"
    """The memory has expired and should not be used for decisions."""

    CORRECTED = "corrected"
    """The memory has been superseded by a correction."""

    SOFT_DELETED = "soft_deleted"
    """The memory has been soft-deleted (tombstone retained)."""


class AuditAction(str, enum.Enum):
    """Actions that generate audit records."""

    CREATED = "created"
    """A memory entry was created."""

    READ = "read"
    """A memory entry or profile was accessed."""

    UPDATED = "updated"
    """A memory entry was updated."""

    CORRECTED = "corrected"
    """A memory entry was corrected."""

    SOFT_DELETED = "soft_deleted"
    """A memory entry was soft-deleted."""

    HARD_DELETED = "hard_deleted"
    """A memory entry was hard-deleted."""

    EXPIRED = "expired"
    """A memory entry expired."""

    ENABLED = "enabled"
    """Course memory was enabled."""

    DISABLED = "disabled"
    """Course memory was disabled."""

    EXPORTED = "exported"
    """Student memory data was exported."""


class StrategyType(str, enum.Enum):
    """Types of teaching strategies."""

    SCAFFOLDING = "scaffolding"
    """Provide graduated assistance."""

    REMEDIATION = "remediation"
    """Targeted remediation for gaps."""

    ACCELERATION = "acceleration"
    """Move faster through mastered material."""

    ADAPTATION = "adaptation"
    """Adapt presentation style or difficulty."""

    REINFORCEMENT = "reinforcement"
    """Reinforce previously learned material."""

    EXPLICIT_INSTRUCTION = "explicit_instruction"
    """Direct explicit teaching."""

    PRACTICE = "practice"
    """Additional practice opportunities."""
