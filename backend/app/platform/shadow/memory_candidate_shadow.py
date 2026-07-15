"""Product 1 V2 memory-candidate shadow (G3D2).

Generates candidate StudentMemory context from V1 QA context, writes it
to an isolated shadow store for offline comparison. HARD CONSTRAINT
(ADR-0006 §G3D2): the candidate memory is NOT injected into the formal
QA prompt. The V1 answer is unchanged. This shadow only records "what
memory context WOULD be provided if memory were enabled" - it does not
feed the model.

ADR-0006 §G3D2:
- Trigger only when ``STUDENT_MEMORY_MODE`` is effectively ``shadow``
  (requires LEARNING_EVENT_MODE also effectively v2_shadow, per conflict
  rule: memory needs learning events).
- Candidate memory entries retain evidence refs (to P1-07 LearningEvidence)
  and a generation reason. No free-form chat summaries written as truth.
- Disabled memory (flag off) -> not read, not written.
- Cross-course reuse denied by default (course-scoped candidate store).
- Business fail-closed; V1 answer never changes.

G3D2 does NOT call the LLM and does NOT modify the QA prompt.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.feature_flags import (
    STUDENT_MEMORY_MODE,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_SHADOW_ROOT = "./p1_shadow_memory_candidates"


@dataclass(frozen=True)
class MemoryCandidateShadowResult:
    triggered: bool
    effective_mode: str
    trace_path: Optional[str] = None
    candidate_count: int = 0
    would_inject: bool = False  # always False in G3D2 (never injected)
    fallback_reason: Optional[str] = None
    duration_ms: float = 0.0


class MemoryCandidateShadowStore:
    def __init__(self, base_dir: str | Path = DEFAULT_MEMORY_SHADOW_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, run_id: str) -> Path:
        if not run_id or not all(c.isalnum() or c in "_-" for c in run_id):
            raise ValueError(f"unsafe run_id: {run_id!r}")
        if "/" in run_id or "\\" in run_id or "." in run_id:
            raise ValueError(f"unsafe run_id: {run_id!r}")
        return self._base / f"{run_id}.json"

    def write(self, run_id: str, payload: Dict[str, Any]) -> Path:
        path = self._safe_path(run_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def base_dir(self) -> Path:
        return self._base


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_memory_mode():
    return resolve_effective_modes(_configured_modes())[STUDENT_MEMORY_MODE]


def _build_candidate_memory(
    question: str,
    student_id: Any,
    course_id: Any,
    v1_context: Dict[str, Any],
) -> Dict[str, Any]:
    """Build candidate MemoryEntry + candidate context from V1 QA context.

    Fake/offline: derives candidate memory entries from V1 rag_sources
    (each becomes a candidate MemoryEntry with evidence ref placeholder).
    No LLM. No free-form chat summary written as truth - each candidate
    has a generation_reason and an evidence_ref placeholder.

    Imports P1-06 contracts lazily.
    """
    from app.domain.student_memory.models import MemoryEntry, MemorySource, MemoryType

    rag_sources = v1_context.get("rag_sources", [])
    candidates: List[Dict[str, Any]] = []
    for i, src in enumerate(rag_sources):
        path = src.get("path", f"src_{i}")
        content = src.get("content_preview", "")
        if not content:
            continue
        # Candidate memory entry: evidence-ref placeholder + generation reason.
        # NOT a chat summary written as truth.
        entry = MemoryEntry(
            student_id=int(student_id) if student_id is not None else 0,
            course_id=int(course_id) if course_id is not None else 0,
            memory_type=MemoryType.KNOWLEDGE,
            source=MemorySource.EVENT_DERIVED,
            content=content[:500],
            evidence_refs=[f"evidence_shadow_{i}"],  # placeholder ref to P1-07 evidence
            generation_reason=f"rag_source:{path}",
            confidence=float(src.get("score", 0.5)),
        )
        candidates.append({
            "content_preview": entry.content[:100],
            "evidence_refs": entry.evidence_refs,
            "generation_reason": entry.generation_reason,
            "confidence": entry.confidence,
            "source": entry.source.value if hasattr(entry.source, "value") else str(entry.source),
        })

    # The "would-inject" context: what memory context WOULD be provided.
    # In G3D2 this is NEVER actually injected (would_inject=False).
    would_inject_context = {
        "token_budget": min(500, sum(len(c["content_preview"]) for c in candidates)),
        "candidate_entries": len(candidates),
        "note": "G3D2: candidate memory NOT injected into QA prompt (ADR §G3D2)",
    }

    return {
        "candidates": candidates,
        "would_inject_context": would_inject_context,
    }


def trigger_memory_candidate_shadow(
    question: str,
    student_id: Any,
    course_id: Any,
    v1_context: Optional[Dict[str, Any]] = None,
    store: Optional[MemoryCandidateShadowStore] = None,
) -> MemoryCandidateShadowResult:
    """Trigger a V2 memory-candidate shadow after V1 QA retrieval.

    HARD CONSTRAINT: does NOT inject memory into the QA prompt. The V1
    answer is unchanged. Only records candidate memory + would-inject
    context for offline comparison.

    NEVER raises into V1 (business fail-closed).
    """
    import uuid

    start = time.time()
    store = store or MemoryCandidateShadowStore()
    v1_context = v1_context or {}

    effective = _effective_memory_mode()
    if effective.effective != "shadow":
        return MemoryCandidateShadowResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    # RISK-05: student + course scope required.
    if student_id is None or course_id is None:
        fc = shadow_runtime_fail_closed(
            STUDENT_MEMORY_MODE, "shadow", "missing_student_or_course_scope"
        )
        return MemoryCandidateShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )

    run_id = f"mem_{uuid.uuid4().hex}"
    try:
        candidate_data = _build_candidate_memory(question, student_id, course_id, v1_context)
        trace = {
            "run_id": run_id,
            "triggered_at": time.time(),
            "student_id": int(student_id),
            "course_id": int(course_id),
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "effective_mode": "shadow",
            "would_inject": False,  # HARD CONSTRAINT: never injected
            "candidate_memory": candidate_data["candidates"],
            "would_inject_context": candidate_data["would_inject_context"],
        }
        path = store.write(run_id, trace)
        return MemoryCandidateShadowResult(
            triggered=True,
            effective_mode="shadow",
            trace_path=str(path),
            candidate_count=len(candidate_data["candidates"]),
            would_inject=False,
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        fc = shadow_runtime_fail_closed(
            STUDENT_MEMORY_MODE, "shadow", f"runtime:{type(e).__name__}:{e}"
        )
        logger.warning(f"[G3D2 memory shadow] runtime error: {e}", exc_info=True)
        return MemoryCandidateShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
