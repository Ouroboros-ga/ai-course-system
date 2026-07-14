"""
In-memory fake implementation of StudentMemoryRepository for testing.

This store uses plain dicts and is NOT thread-safe. It is intended for
unit/contract tests only -- P1-09 owns the production ORM implementation.

Version: 1.0 (draft)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.domain.student_memory.audit import MemoryAuditRecord
from app.domain.student_memory.enums import AuditAction, LifecycleState
from app.domain.student_memory.models import (
    CourseMemory,
    MemoryDisabledError,
    MemoryEntry,
    StudentProfile,
    TeachingStrategy,
)
from app.domain.student_memory.repository import (
    CrossCourseAccessError,
    validate_scope,
)


class InMemoryStudentMemoryStore:
    """In-memory fake implementation of StudentMemoryRepository.

    Stores data in plain dicts keyed by (student_id, course_id).
    Cross-course access is denied by default.
    """

    def __init__(self) -> None:
        self._profiles: Dict[tuple, StudentProfile] = {}
        self._entries: Dict[tuple, Dict[str, MemoryEntry]] = {}
        self._enabled: Dict[tuple, bool] = {}
        self._strategies: Dict[tuple, List[TeachingStrategy]] = {}
        self._audit_records: List[MemoryAuditRecord] = []

    def _scope_key(
        self, student_id: int, course_id: int
    ) -> tuple:
        return (student_id, course_id)

    def _check_enabled(
        self, student_id: int, course_id: int
    ) -> None:
        """Raise MemoryDisabledError if memory is disabled for this scope."""
        key = self._scope_key(student_id, course_id)
        if not self._enabled.get(key, True):
            raise MemoryDisabledError(
                f"Memory is disabled for student {student_id} "
                f"in course {course_id}"
            )

    # ── Profile operations ──

    def get_profile(
        self, student_id: int, course_id: int
    ) -> Optional[StudentProfile]:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        return self._profiles.get(key)

    def save_profile(self, profile: StudentProfile) -> None:
        self._check_enabled(profile.student_id, profile.course_id)
        key = self._scope_key(profile.student_id, profile.course_id)
        self._profiles[key] = profile

    def delete_profile(
        self, student_id: int, course_id: int
    ) -> None:
        key = self._scope_key(student_id, course_id)
        self._profiles.pop(key, None)

    # ── Memory entry operations ──

    def get_entry(
        self, student_id: int, course_id: int, entry_id: str
    ) -> Optional[MemoryEntry]:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        entries = self._entries.get(key, {})
        entry = entries.get(entry_id)
        if entry is None:
            return None
        if not entry.is_readable():
            return None
        return entry

    def get_entries(
        self, student_id: int, course_id: int,
        include_soft_deleted: bool = False,
    ) -> List[MemoryEntry]:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        entries = self._entries.get(key, {})
        if include_soft_deleted:
            return list(entries.values())
        return [e for e in entries.values() if e.is_readable()]

    def save_entry(self, entry: MemoryEntry) -> None:
        self._check_enabled(entry.student_id, entry.course_id)
        key = self._scope_key(entry.student_id, entry.course_id)
        if key not in self._entries:
            self._entries[key] = {}
        self._entries[key][entry.entry_id] = entry

    def soft_delete_entry(
        self,
        student_id: int,
        course_id: int,
        entry_id: str,
        reason: str = "",
        actor_id: int = 0,
    ) -> None:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        entries = self._entries.get(key, {})
        entry = entries.get(entry_id)
        if entry is None:
            return
        if entry.lifecycle_state == LifecycleState.SOFT_DELETED:
            return
        # Frozen dataclass -- create a new instance with updated state
        new_entry = MemoryEntry(
            entry_id=entry.entry_id,
            student_id=entry.student_id,
            course_id=entry.course_id,
            memory_type=entry.memory_type,
            source=entry.source,
            content=entry.content,
            confidence=entry.confidence,
            evidence_refs=entry.evidence_refs,
            generation_reason=entry.generation_reason,
            lifecycle_state=LifecycleState.SOFT_DELETED,
            node_id=entry.node_id,
            expires_at=entry.expires_at,
            corrected_by=entry.corrected_by,
            correction_for=entry.correction_for,
            timestamp=entry.timestamp,
            metadata={**entry.metadata, "soft_delete_reason": reason},
            version=entry.version,
        )
        entries[entry_id] = new_entry

    def hard_delete_entry(
        self,
        student_id: int,
        course_id: int,
        entry_id: str,
        reason: str = "",
        actor_id: int = 0,
    ) -> None:
        key = self._scope_key(student_id, course_id)
        entries = self._entries.get(key, {})
        entry = entries.get(entry_id)
        if entry is None:
            return
        # Allow hard-delete only if already soft-deleted (safety)
        if entry.lifecycle_state != LifecycleState.SOFT_DELETED:
            raise ValueError(
                f"Cannot hard-delete entry {entry_id}: "
                f"must be soft-deleted first. "
                f"Current state: {entry.lifecycle_state.value}"
            )
        del entries[entry_id]

    def hard_delete_all_entries(
        self,
        student_id: int,
        course_id: int,
        reason: str = "",
        actor_id: int = 0,
    ) -> int:
        key = self._scope_key(student_id, course_id)
        entries = self._entries.pop(key, {})
        return len(entries)

    def correct_entry(
        self,
        original_entry: MemoryEntry,
        correction: MemoryEntry,
        reason: str = "",
        actor_id: int = 0,
    ) -> MemoryEntry:
        self._check_enabled(
            original_entry.student_id, original_entry.course_id
        )
        # Mark original as corrected
        corrected = MemoryEntry(
            entry_id=original_entry.entry_id,
            student_id=original_entry.student_id,
            course_id=original_entry.course_id,
            memory_type=original_entry.memory_type,
            source=original_entry.source,
            content=original_entry.content,
            confidence=original_entry.confidence,
            evidence_refs=original_entry.evidence_refs,
            generation_reason=original_entry.generation_reason,
            lifecycle_state=LifecycleState.CORRECTED,
            node_id=original_entry.node_id,
            expires_at=original_entry.expires_at,
            corrected_by=correction.entry_id,
            correction_for=original_entry.correction_for,
            timestamp=original_entry.timestamp,
            metadata={**original_entry.metadata, "correction_reason": reason},
            version=original_entry.version,
        )
        self.save_entry(corrected)
        self.save_entry(correction)
        return corrected

    # ── CourseMemory (aggregate) operations ──

    def get_course_memory(
        self, student_id: int, course_id: int
    ) -> Optional[CourseMemory]:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        entries = self._entries.get(key, {})
        if not entries and key not in self._profiles:
            return None
        cm = CourseMemory(
            student_id=student_id,
            course_id=course_id,
            enabled=self._enabled.get(key, True),
            entries=entries.copy(),
            profile=self._profiles.get(key),
        )
        return cm

    def is_memory_enabled(
        self, student_id: int, course_id: int
    ) -> bool:
        key = self._scope_key(student_id, course_id)
        return self._enabled.get(key, True)

    def set_memory_enabled(
        self, student_id: int, course_id: int,
        enabled: bool, actor_id: int = 0,
    ) -> None:
        key = self._scope_key(student_id, course_id)
        self._enabled[key] = enabled

    # ── Strategy operations ──

    def get_strategies(
        self, student_id: int, course_id: int,
    ) -> List[TeachingStrategy]:
        self._check_enabled(student_id, course_id)
        key = self._scope_key(student_id, course_id)
        return self._strategies.get(key, [])

    def save_strategy(self, strategy: TeachingStrategy) -> None:
        key = self._scope_key(strategy.student_id, strategy.course_id)
        if key not in self._strategies:
            self._strategies[key] = []
        # Replace if exists, otherwise append
        for i, s in enumerate(self._strategies[key]):
            if s.strategy_id == strategy.strategy_id:
                self._strategies[key][i] = strategy
                return
        self._strategies[key].append(strategy)

    def delete_strategies(
        self, student_id: int, course_id: int,
    ) -> None:
        key = self._scope_key(student_id, course_id)
        self._strategies.pop(key, None)

    # ── Audit operations ──

    def get_audit_records(
        self,
        student_id: int,
        course_id: int,
        action: Optional[AuditAction] = None,
        limit: int = 100,
    ) -> List[MemoryAuditRecord]:
        records = [
            r for r in self._audit_records
            if r.student_id == student_id and r.course_id == course_id
        ]
        if action:
            records = [r for r in records if r.action == action]
        return records[:limit]

    def save_audit_record(self, record: MemoryAuditRecord) -> None:
        self._audit_records.append(record)

    # ── Deletion propagation ──

    def get_deletion_propagation_list(self) -> List[str]:
        return [
            "StudentProfile",
            "MemoryEntry (all)",
            "TeachingStrategy",
            "MemoryAuditRecord (retained with minimized metadata)",
        ]

    # ── Utility for tests ──

    def clear(self) -> None:
        """Clear all stored data. For test isolation."""
        self._profiles.clear()
        self._entries.clear()
        self._enabled.clear()
        self._strategies.clear()
        self._audit_records.clear()
