"""
Audit events and AuditSink protocol for safety decisions.

Data minimization: audit logs MUST NOT store secrets, tokens, or
unnecessary full user content.  Decisions reference reason codes and
rule IDs rather than storing the full text that triggered them.
"""

from __future__ import annotations

import abc
import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .decision import SafetyDecision, SourceAccessDecision


class AuditLevel(str, enum.Enum):
    """Severity level for audit events."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# AuditEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditEvent:
    """An auditable safety event.

    Data minimization principles:
    - ``user_content_snippet`` stores at most 100 characters of the original
      content, and only when necessary for audit traceability.
    - ``metadata`` must NOT contain secrets, tokens, passwords, API keys,
      or full user content.
    - ``matched_rule_ids`` and ``reason_code`` are preferred over storing
      original content.

    Parameters
    ----------
    event_id : str
        Unique event identifier.
    event_type : str
        Type of event (e.g., ``"input_check"``, ``"source_check"``,
        ``"output_check"``).
    stage : str
        The decision stage (``"input"``, ``"source"``, ``"output"``).
    outcome : str
        The outcome (``"pass"``, ``"block"``, ``"restrict"``, etc.).
    reason_code : str
        Stable reason code.
    reason_detail : str
        Human-readable explanation.
    matched_rule_ids : list of str
        The rule IDs that triggered.
    user_content_snippet : str or None
        At most 100 chars of the triggering content, or None.
        Only set when needed for traceability.
    user_id : str or None
        The user who triggered the event (if available).
    course_id : str or None
        The course context (if available).
    decision_id : str or None
        Reference to the original SafetyDecision ID.
    level : AuditLevel
        Severity level.
    timestamp : str
        ISO 8601 timestamp.
    metadata : dict
        Additional context (minimized; no secrets/tokens).
    """

    event_id: str
    event_type: str
    stage: str
    outcome: str
    reason_code: str
    reason_detail: str = ""
    matched_rule_ids: List[str] = field(default_factory=list)
    user_content_snippet: Optional[str] = None
    user_id: Optional[str] = None
    course_id: Optional[str] = None
    decision_id: Optional[str] = None
    level: AuditLevel = AuditLevel.INFO
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Truncate user content snippet to 100 chars (data minimization)
        if self.user_content_snippet is not None and len(self.user_content_snippet) > 100:
            object.__setattr__(
                self,
                "user_content_snippet",
                self.user_content_snippet[:100],
            )
        # Set timestamp if not provided
        if not self.timestamp:
            object.__setattr__(
                self,
                "timestamp",
                datetime.now(timezone.utc).isoformat(),
            )

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "stage": self.stage,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
            "matched_rule_ids": list(self.matched_rule_ids),
            "user_content_snippet": self.user_content_snippet,
            "user_id": self.user_id,
            "course_id": self.course_id,
            "decision_id": self.decision_id,
            "level": self.level.value,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_decision(
        cls,
        decision: SafetyDecision,
        event_type: str = "",
        user_content_snippet: Optional[str] = None,
        user_id: Optional[str] = None,
        course_id: Optional[str] = None,
        level: AuditLevel = AuditLevel.INFO,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AuditEvent":
        """Create an AuditEvent from a SafetyDecision.

        Data minimization is applied automatically: the snippet is
        truncated to 100 characters.

        WARNING: ``metadata`` must NOT contain secrets, tokens, or
        full user content. Data minimization is enforced at the
        application layer.
        """
        return cls(
            event_id=f"evt-{uuid.uuid4().hex[:12]}",
            event_type=event_type or f"{decision.stage.value}_check",
            stage=decision.stage.value,
            outcome=decision.outcome.value,
            reason_code=decision.reason_code.value,
            reason_detail=decision.reason_detail,
            matched_rule_ids=decision.matched_rule_ids,
            user_content_snippet=user_content_snippet,
            user_id=user_id,
            course_id=course_id,
            decision_id=decision.decision_id,
            level=level,
            metadata=metadata if metadata is not None else decision.metadata,
        )


# ---------------------------------------------------------------------------
# AuditSink Protocol
# ---------------------------------------------------------------------------


class AuditSink(abc.ABC):
    """Abstract base for audit event sinks.

    Implementations must ensure they do NOT log secrets, tokens, or
    full user content.  Data minimization is applied at the
    ``AuditEvent`` level before it reaches the sink.
    """

    @abc.abstractmethod
    def emit(self, event: AuditEvent) -> None:
        """Emit an audit event.

        Raises ``IOError`` on failure (fail-closed: callers should
        treat a failed emit as a safety concern).
        """
        ...

    @abc.abstractmethod
    def flush(self) -> None:
        """Flush any buffered events."""
        ...


# ---------------------------------------------------------------------------
# ConsoleAuditSink
# ---------------------------------------------------------------------------


class ConsoleAuditSink(AuditSink):
    """Simple console-based audit sink for development/testing.

    In production, replace with a persistent sink (database, log
    aggregator, etc.).
    """

    def __init__(self, level_filter: AuditLevel = AuditLevel.INFO) -> None:
        self._level_filter = level_filter
        self._events: List[AuditEvent] = []

    @property
    def events(self) -> List[AuditEvent]:
        return list(self._events)

    def emit(self, event: AuditEvent) -> None:
        """Emit an event if its level meets the filter threshold.

        Stores the event in memory for test inspection.
        """
        level_order = {
            AuditLevel.DEBUG: 0,
            AuditLevel.INFO: 1,
            AuditLevel.WARNING: 2,
            AuditLevel.ERROR: 3,
            AuditLevel.CRITICAL: 4,
        }
        if level_order.get(event.level, 0) >= level_order.get(self._level_filter, 1):
            self._events.append(event)

    def flush(self) -> None:
        """No-op for console sink."""
        pass

    def clear(self) -> None:
        """Clear stored events (for testing)."""
        self._events.clear()


# ---------------------------------------------------------------------------
# NoOpAuditSink
# ---------------------------------------------------------------------------


class NoOpAuditSink(AuditSink):
    """No-op audit sink that discards all events.

    Use only in tests where audit is not under test.
    """

    def emit(self, event: AuditEvent) -> None:
        pass

    def flush(self) -> None:
        pass
