"""
Repository Protocol for student memory persistence.

Defines the abstract interface (typing.Protocol) for storing and retrieving
StudentProfile, CourseMemory, MemoryEntry, MemoryAuditRecord, and
TeachingStrategy instances.

The Protocol enforces:
- student + course scope on all queries (cross-course access denied by default)
- memory enable/disable behavior (disabled => not read AND not written)
- soft-delete + hard-delete semantics
- deletion propagation list

Do NOT implement ORM/sql here -- P1-09 owns production persistence.
Use InMemoryStudentMemoryStore (in fake.py) for tests.

Version: 1.0 (draft)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Set

from app.domain.student_memory.audit import MemoryAuditRecord
from app.domain.student_memory.enums import AuditAction, LifecycleState
from app.domain.student_memory.models import (
    CourseMemory,
    MemoryDisabledError,
    MemoryEntry,
    StudentProfile,
    TeachingStrategy,
)


class StudentMemoryRepository(Protocol):
    """Protocol for student memory persistence operations.

    All queries are scoped by student_id + course_id.
    Cross-course access raises CrossCourseAccessError.
    """

    # ── Profile operations ──

    def get_profile(
        self, student_id: int, course_id: int
    ) -> Optional[StudentProfile]:
        """Get the student profile for a given student+course scope.
        Returns None if no profile exists.
        """
        ...

    def save_profile(self, profile: StudentProfile) -> None:
        """Create or update a student profile.

        Raises CrossCourseAccessError if the profile's student_id or
        course_id is accessed from the wrong scope.
        """
        ...

    def delete_profile(
        self, student_id: int, course_id: int
    ) -> None:
        """Delete (hard) a student profile for a student+course scope."""
        ...

    # ── Memory entry operations ──

    def get_entry(
        self, student_id: int, course_id: int, entry_id: str
    ) -> Optional[MemoryEntry]:
        """Get a specific memory entry within a student+course scope.
        Returns None if not found or soft-deleted.
        """
        ...

    def get_entries(
        self, student_id: int, course_id: int,
        include_soft_deleted: bool = False,
    ) -> List[MemoryEntry]:
        """Get all memory entries for a student+course scope.

        By default, soft-deleted entries are excluded.
        """
        ...

    def save_entry(self, entry: MemoryEntry) -> None:
        """Create or update a memory entry.

        Raises MemoryDisabledError if memory is disabled for this
        student+course pair.
        Raises CrossCourseAccessError on scope mismatch.
        """
        ...

    def soft_delete_entry(
        self,
        student_id: int,
        course_id: int,
        entry_id: str,
        reason: str = "",
        actor_id: int = 0,
    ) -> None:
        """Soft-delete a memory entry (tombstone retained).

        The entry's lifecycle_state becomes SOFT_DELETED but the record
        is retained for audit.
        """
        ...

    def hard_delete_entry(
        self,
        student_id: int,
        course_id: int,
        entry_id: str,
        reason: str = "",
        actor_id: int = 0,
    ) -> None:
        """Hard-delete a memory entry (removed from store).

        Only possible if the entry was already soft-deleted, or with
        explicit force. Audit records are preserved.
        """
        ...

    def hard_delete_all_entries(
        self,
        student_id: int,
        course_id: int,
        reason: str = "",
        actor_id: int = 0,
    ) -> int:
        """Hard-delete ALL memory entries for a student+course scope.

        Returns the number of entries deleted.
        This is part of the deletion propagation list.
        """
        ...

    def correct_entry(
        self,
        original_entry: MemoryEntry,
        correction: MemoryEntry,
        reason: str = "",
        actor_id: int = 0,
    ) -> MemoryEntry:
        """Correct a memory entry by creating a new entry that references
        the original as ``correction_for``.

        The original entry's lifecycle_state becomes CORRECTED.

        Raises MemoryDisabledError if memory is disabled.
        """
        ...

    # ── CourseMemory (aggregate) operations ──

    def get_course_memory(
        self, student_id: int, course_id: int
    ) -> Optional[CourseMemory]:
        """Get the full CourseMemory aggregate for a student+course scope.
        Returns None if no memory exists for this scope.
        """
        ...

    def is_memory_enabled(
        self, student_id: int, course_id: int
    ) -> bool:
        """Check if memory is enabled for a student+course scope."""
        ...

    def set_memory_enabled(
        self, student_id: int, course_id: int,
        enabled: bool, actor_id: int = 0,
    ) -> None:
        """Enable or disable memory for a student+course scope.

        When disabled, memory is neither read nor written.
        """
        ...

    # ── Strategy operations ──

    def get_strategies(
        self, student_id: int, course_id: int,
    ) -> List[TeachingStrategy]:
        """Get teaching strategies for a student+course scope."""
        ...

    def save_strategy(self, strategy: TeachingStrategy) -> None:
        """Save a teaching strategy."""
        ...

    def delete_strategies(
        self, student_id: int, course_id: int,
    ) -> None:
        """Delete all strategies for a student+course scope."""
        ...

    # ── Audit operations ──

    def get_audit_records(
        self,
        student_id: int,
        course_id: int,
        action: Optional[AuditAction] = None,
        limit: int = 100,
    ) -> List[MemoryAuditRecord]:
        """Get audit records for a student+course scope.

        Optionally filter by action type.
        """
        ...

    def save_audit_record(self, record: MemoryAuditRecord) -> None:
        """Save an audit record."""
        ...

    # ── Deletion propagation (bulk operations) ──

    def get_deletion_propagation_list(
        self,
    ) -> List[str]:
        """Return the list of scopes/collections that must be deleted
        when a student's memory is fully purged.

        Returns a human-readable list of what gets deleted:
        - StudentProfile
        - MemoryEntry (all)
        - TeachingStrategy
        - MemoryAuditRecord (retained with minimized metadata)
        """
        return [
            "StudentProfile",
            "MemoryEntry (all)",
            "TeachingStrategy",
            "MemoryAuditRecord (retained with minimized metadata)",
        ]


class CrossCourseAccessError(Exception):
    """Raised when a cross-course memory access is attempted."""


def validate_scope(
    entry_student_id: int,
    entry_course_id: int,
    expected_student_id: int,
    expected_course_id: int,
) -> None:
    """Validate that the entry scope matches the expected scope.

    Cross-course access is denied by default (RISK-05).
    """
    if entry_student_id != expected_student_id:
        raise CrossCourseAccessError(
            f"Student ID {entry_student_id} does not match "
            f"expected {expected_student_id}"
        )
    if entry_course_id != expected_course_id:
        raise CrossCourseAccessError(
            f"Course ID {entry_course_id} does not match "
            f"expected {expected_course_id}"
        )
