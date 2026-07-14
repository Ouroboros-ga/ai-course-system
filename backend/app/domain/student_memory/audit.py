"""
Audit records for student memory operations.

Every access, creation, modification, and deletion of student memory
generates an audit record. Audit records retain privacy-minimized metadata:
they reference entry IDs and action types but do not store full memory
content by default.

Version: 1.0 (draft)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.student_memory.enums import AuditAction, STUDENT_MEMORY_VERSION


@dataclass(frozen=True)
class MemoryAuditRecord:
    """An audit record for a student memory operation.

    Parameters
    ----------
    audit_id : str
        Globally unique audit identifier (UUID4).
    timestamp : str
        ISO 8601 UTC timestamp.
    action : AuditAction
        The audited action.
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    actor_id : int
        The user ID who performed the action (student, teacher, or system).
    actor_role : str
        Role of the actor (e.g. ``student``, ``teacher``, ``system``).
    entry_id : str or None
        The affected memory entry ID, if applicable.
    profile_id : str or None
        The affected profile ID, if applicable.
    previous_state : str or None
        Previous lifecycle state if the action changed state.
    new_state : str or None
        New lifecycle state if the action changed state.
    reason : str or None
        Reason for the action (e.g. correction reason, deletion reason).
    metadata : dict
        Privacy-minimized metadata. DO NOT store full memory content here.
        Store references (entry_ids, evidence_refs) instead.
    version : str
        Schema version.
    """

    student_id: int
    course_id: int
    actor_id: int
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    action: AuditAction = AuditAction.CREATED
    actor_role: str = "system"
    entry_id: Optional[str] = None
    profile_id: Optional[str] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = STUDENT_MEMORY_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp,
            "action": self.action.value,
            "student_id": self.student_id,
            "course_id": self.course_id,
            "actor_id": self.actor_id,
            "actor_role": self.actor_role,
            "entry_id": self.entry_id,
            "profile_id": self.profile_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "reason": self.reason,
            "metadata": self.metadata,
            "version": self.version,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> MemoryAuditRecord:
        return MemoryAuditRecord(
            audit_id=data.get("audit_id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", ""),
            action=AuditAction(data.get("action", "created")),
            student_id=data["student_id"],
            course_id=data["course_id"],
            actor_id=data["actor_id"],
            actor_role=data.get("actor_role", "system"),
            entry_id=data.get("entry_id"),
            profile_id=data.get("profile_id"),
            previous_state=data.get("previous_state"),
            new_state=data.get("new_state"),
            reason=data.get("reason"),
            metadata=data.get("metadata", {}),
            version=data.get("version", STUDENT_MEMORY_VERSION),
        )
