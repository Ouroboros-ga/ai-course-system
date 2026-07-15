"""Product 1 V2 learning-event shadow (G3D1).

Triggered from V1 learning-behavior write points (e.g.
``prerequisite_service.create_jump_record``) AFTER the V1 record is
committed. Maps the V1 behavior into a P1-07 ``LearningEvent`` and
writes it to an INDEPENDENT shadow event store. V1 behavior is
unchanged: shadow failures are business-level fail-closed.

ADR-0006 §G3D1:
- Trigger only when ``LEARNING_EVENT_MODE`` is effectively ``v2_shadow``
  (LEARNING_EVENT_MODE is a root independent flag, not bundled with the
  document aggregate).
- Append-only facts: each shadow event is a new record; corrections are
  new events (never mutate). Idempotency key = (event_type, student_id,
  course_id, sequence_number) per P1-07 contract.
- Shadow event store is isolated from V1 LearningProgress/NodeProgress/
  LearningJumpHistory/UnderstandingAnalysis tables.
- No LLM. No real mastery computation. The shadow event is the raw V1
  behavior mapped to LearningEvent shape; aggregation/mastery is G3D2.

G3D1 does NOT inject anything into QA (that is G3D2 Memory Candidate,
which itself must NOT inject the QA prompt per ADR §G3D2).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.feature_flags import (
    LEARNING_EVENT_MODE,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)

DEFAULT_LEARNING_SHADOW_ROOT = "./p1_shadow_learning_events"


# ---------------------------------------------------------------------------
# Shadow trigger result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LearningShadowResult:
    triggered: bool
    effective_mode: str
    event_id: Optional[str] = None
    trace_path: Optional[str] = None
    fallback_reason: Optional[str] = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Shadow event store (isolated)
# ---------------------------------------------------------------------------


class LearningEventShadowStore:
    """Append-only shadow event store, isolated from V1 tables."""

    def __init__(self, base_dir: str | Path = DEFAULT_LEARNING_SHADOW_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, event_id: str) -> Path:
        # event_id is "evt_" + hex; allow alphanumerics, underscore, hyphen.
        if not event_id or not all(c.isalnum() or c in "_-" for c in event_id):
            raise ValueError(f"unsafe event_id: {event_id!r}")
        # still reject path separators / dots explicitly
        if "/" in event_id or "\\" in event_id or "." in event_id:
            raise ValueError(f"unsafe event_id: {event_id!r}")
        return self._base / f"{event_id}.json"

    def append(self, event_id: str, payload: Dict[str, Any]) -> Path:
        path = self._safe_path(event_id)
        if path.exists():
            # Idempotent: same event_id already appended. Do not overwrite
            # (append-only). Return existing.
            return path
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def exists(self, event_id: str) -> bool:
        return self._safe_path(event_id).exists()

    def base_dir(self) -> Path:
        return self._base


# ---------------------------------------------------------------------------
# Configured-mode reader
# ---------------------------------------------------------------------------


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_learning_mode():
    return resolve_effective_modes(_configured_modes())[LEARNING_EVENT_MODE]


# ---------------------------------------------------------------------------
# V1 -> LearningEvent mapping (P1-07 shape)
# ---------------------------------------------------------------------------


def _idempotency_key(
    event_type: str, student_id: Any, course_id: Any, sequence_number: int
) -> str:
    raw = f"{event_type}:{student_id}:{course_id}:{sequence_number}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _build_learning_event(
    event_type: str,
    student_id: Any,
    course_id: Any,
    sequence_number: int,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Map a V1 learning behavior into a P1-07 LearningEvent-shaped dict.

    Uses P1-07 LearningEvent contract fields (event_type, student_id,
    course_id, sequence_number, idempotency_key, source, metadata).
    Imports P1-07 lazily so a contract issue is runtime fail-closed.
    """
    from app.domain.learning.event import LearningEvent, EventType

    # Map V1 event_type strings to P1-07 EventType where possible.
    etype_map = {
        "node_accessed": EventType.NODE_ACCESSED,
        "node_completed": EventType.NODE_COMPLETED,
        "quiz_answered": EventType.QUIZ_ANSWERED,
        "quiz_correct": EventType.QUIZ_CORRECT,
        "quiz_incorrect": EventType.QUIZ_INCORRECT,
        "prerequisite_jump": EventType.PREREQ_JUMP_STARTED,
        "question_asked": EventType.QUESTION_ASKED,
    }
    mapped = etype_map.get(event_type)
    if mapped is None:
        # Unknown V1 event type -> still record as a generic event with the
        # raw type in metadata (do not drop the behavior; do not fake a
        # known type).
        mapped = EventType.NODE_ACCESSED  # placeholder; raw kept in metadata

    idem = _idempotency_key(event_type, student_id, course_id, sequence_number)
    event_id = f"evt_{idem}"

    event = LearningEvent(
        event_type=mapped,
        student_id=int(student_id) if student_id is not None else 0,
        course_id=int(course_id) if course_id is not None else 0,
        sequence_number=sequence_number,
        source="v1_shadow_mapper",
        metadata={**payload, "v1_raw_event_type": event_type},
    )

    return {
        "event_id": event_id,
        "idempotency_key": idem,
        "learning_event": {
            "event_type": event.event_type.value,
            "student_id": event.student_id,
            "course_id": event.course_id,
            "sequence_number": event.sequence_number,
            "source": event.source,
            "metadata": event.metadata,
        },
    }


# ---------------------------------------------------------------------------
# Public trigger API
# ---------------------------------------------------------------------------


def trigger_learning_event_shadow(
    event_type: str,
    student_id: Any,
    course_id: Any,
    sequence_number: int,
    payload: Optional[Dict[str, Any]] = None,
    store: Optional[LearningEventShadowStore] = None,
) -> LearningShadowResult:
    """Trigger a V2 learning-event shadow record after a V1 behavior write.

    Called from V1 write points AFTER session.commit succeeds. NEVER
    raises into V1: all shadow errors are business-level fail-closed.

    Idempotent: same (event_type, student_id, course_id, sequence_number)
    -> same event_id; re-trigger is a no-op (append-only, no overwrite).
    """
    start = time.time()
    store = store or LearningEventShadowStore()
    payload = payload or {}

    # 1. Flag check.
    effective = _effective_learning_mode()
    if effective.effective != "v2_shadow":
        return LearningShadowResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_v2_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    # 2. RISK-06: must have student + course scope for a meaningful event.
    if student_id is None or course_id is None:
        fc = shadow_runtime_fail_closed(
            LEARNING_EVENT_MODE, "v2_shadow", "missing_student_or_course_scope"
        )
        return LearningShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )

    try:
        mapped = _build_learning_event(
            event_type, student_id, course_id, sequence_number, payload
        )
        event_id = mapped["event_id"]

        # 3. Idempotency: if event already appended, no-op (not an error).
        if store.exists(event_id):
            return LearningShadowResult(
                triggered=False,
                effective_mode="v2_shadow",
                event_id=event_id,
                fallback_reason="idempotent_skip:event_exists",
                duration_ms=(time.time() - start) * 1000,
            )

        trace = {
            "event_id": event_id,
            "triggered_at": time.time(),
            "idempotency_key": mapped["idempotency_key"],
            "learning_event": mapped["learning_event"],
            "shadow_store": "p1_shadow_learning_events",
        }
        path = store.append(event_id, trace)

        return LearningShadowResult(
            triggered=True,
            effective_mode="v2_shadow",
            event_id=event_id,
            trace_path=str(path),
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        fc = shadow_runtime_fail_closed(
            LEARNING_EVENT_MODE, "v2_shadow", f"runtime:{type(e).__name__}:{e}"
        )
        logger.warning(f"[G3D1 learning shadow] runtime error: {e}", exc_info=True)
        return LearningShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
