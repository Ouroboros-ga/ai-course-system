"""Product 1 V2 evidence/retrieval/citation shadow (G3C).

Triggered from ``qa_service.ask_question_with_rag`` AFTER V1 retrieval
succeeds, BEFORE the V1 LLM call. Runs V2 Evidence-aware retrieval +
Citation validation in shadow, writing a trace that compares V1
``ragSources`` against V2 ``RetrievedChunk``/``EvidenceSpan``/``Citation``
candidates.

ADR-0006 §G3C HARD CONSTRAINT: G3C does NOT call the generation model.
It only runs V2 retrieval, evidence binding, and Citation validation.
There is no second LLM call and no second generated answer. The shadow
trace compares retrieval/evidence layers, NOT two generated answers.

V1 behavior is unchanged: shadow failures are business-level fail-closed
(recorded as ``fallback_reason``, V1 continues). Shadow results are NOT
returned to the user (G6 preferred is when V2 feeds the answer).

G3C scope:
- Trigger only when ``EVIDENCE_CITATION_MODE`` is effectively ``v2_shadow``
  (after conflict resolution: requires DOCUMENT_KG_RUNTIME_MODE also
  effectively v2_shadow, which requires DOCUMENT_PIPELINE_VERSION v2_shadow).
- Course isolation: V2 retrieval is scoped to the same course; missing
  scope returns empty (RISK-03). No cross-course leakage.
- No-evidence abstention: citations without evidence -> CitationValidationResult
  abstain=True; no fake citation keys.
- Fake/offline: wraps V1 chunks into V2 RetrievedChunk/EvidenceSpan/Citation
  candidates (no real vector model). Real retrieval quality = G5 canary.
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
    EVIDENCE_CITATION_MODE,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)

DEFAULT_EVIDENCE_TRACE_ROOT = os.environ.get(
    "P1_SHADOW_EVIDENCE_ROOT", "./p1_shadow_evidence"
) if False else "./p1_shadow_evidence"
# (os not imported at top to keep module light; use constant)


# ---------------------------------------------------------------------------
# Shadow trigger result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceShadowResult:
    """Outcome of a G3C evidence/retrieval/citation shadow trigger.

    ``triggered`` is True when a V2 shadow trace was written. When the
    flag is disabled, conflict-downgraded, or a runtime error occurred,
    ``triggered`` is False and ``fallback_reason`` explains why. V1 is
    never affected. ``llm_calls`` is always 0 (G3C hard constraint: no
    second LLM call).
    """

    triggered: bool
    effective_mode: str
    trace_path: Optional[str] = None
    shadow_run_id: Optional[str] = None
    v2_candidate_count: int = 0
    citation_abstain: bool = False
    fallback_reason: Optional[str] = None
    llm_calls: int = 0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Shadow trace store (isolated)
# ---------------------------------------------------------------------------


class EvidenceTraceStore:
    """Writes V2 evidence shadow traces to an isolated directory.

    Path-traversal safe, atomic. Does NOT touch V1 tables, V1 RAG
    registry, or V1 QA responses.
    """

    def __init__(self, base_dir: str | Path = DEFAULT_EVIDENCE_TRACE_ROOT) -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, run_id: str) -> Path:
        if not all(c in "0123456789abcdef-" for c in run_id) or not run_id:
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


def _effective_evidence_mode():
    return resolve_effective_modes(_configured_modes())[EVIDENCE_CITATION_MODE]


# ---------------------------------------------------------------------------
# V2 candidate construction (fake/offline, wraps V1 chunks)
# ---------------------------------------------------------------------------


def _build_v2_candidates(
    question: str,
    course_id: Optional[Any],
    v1_sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build V2 RetrievedChunk/EvidenceSpan/Citation candidates from V1 sources.

    Fake/offline: wraps V1 ragSources into P1-03 contract shapes. No real
    vector model. No LLM. This proves the V2 evidence chain runs, binds
    evidence to (course-scoped) sources, and produces validatable citations.

    Imports P1-03 contracts lazily so the shadow module does not hard-depend
    on them at import time (and so a missing contract is a runtime fail-closed,
    not an import error).
    """
    from app.platform.evidence.contracts import EvidenceSpan, EvidenceStatus
    from app.platform.evidence.citation import citation_key, CitationValidationResult, CitationStatus
    from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope

    # Course-scoped retrieval scope (RISK-03: missing scope -> empty, never global).
    scope = RetrievalScope.course(course_id) if course_id is not None else None

    candidates: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    abstain = True

    for i, src in enumerate(v1_sources):
        path = src.get("path", f"source_{i}")
        content = src.get("content_preview", "")
        score = src.get("score", 0.0)

        # V2 RetrievedChunk with evidence fields (optional, populated here).
        chunk_id = f"chk_{hashlib.sha256(f'{course_id}:{path}:{i}'.encode()).hexdigest()[:20]}"
        chunk = RetrievedChunk(
            chunk_id=chunk_id,
            content=content,
            scope=scope,
            retrieval_score=score,
            match_type=src.get("match_type", "shadow"),
            path=path.split("/") if path else [],
            artifact_id=f"art_shadow_{i}",
            document_id=f"doc_shadow_{course_id}_{i}" if course_id is not None else None,
            block_id=f"blk_shadow_{i}" if content else None,
        )

        # EvidenceSpan referencing the chunk (P1-01 stable-ID-shaped).
        block_id = f"blk_shadow_{i}" if content else None
        if block_id is not None:
            span = EvidenceSpan(
                artifact_id=f"art_shadow_{i}",
                document_id=f"doc_shadow_{course_id}_{i}" if course_id is not None else f"doc_shadow_{i}",
                unit_id=f"unit_shadow_{i}",
                block_id=block_id,
                text_snippet=content[:200] if content else None,
                status=EvidenceStatus.ACTIVE,
            )
            # Citation key (stable; None if no block_id -> no fake key).
            ckey = citation_key(
                artifact_id=span.artifact_id,
                block_id=span.block_id,
            )
            abstain = False  # at least one evidence-backed citation
            evidence_status = span.status.value
        else:
            ckey = None  # no evidence -> no fake key
            evidence_status = None

        candidates.append({
            "chunk_id": chunk.chunk_id,
            "retrieval_score": chunk.retrieval_score,
            "path": path,
            "artifact_id": chunk.artifact_id,
            "document_id": chunk.document_id,
            "block_id": chunk.block_id,
            "evidence_status": evidence_status,
            "citation_key": ckey,
        })
        citations.append({
            "citation_key": ckey,
            "has_evidence": block_id is not None,
            "block_id": block_id,
        })

    # Citation validation result (no-evidence abstention).
    evidence_backed = sum(1 for c in citations if c["has_evidence"])
    validation = CitationValidationResult(
        status=CitationStatus.NO_EVIDENCE if abstain else CitationStatus.VERIFIED,
        abstain=abstain,
        abstain_reason="no_evidence_backed_citations" if abstain else None,
        details=citations,
        verified_count=evidence_backed,
        total_count=len(citations),
    )

    return {
        "scope": scope.scope_type if scope else None,
        "scope_id": str(scope.scope_id) if scope else None,
        "scope_isolated": scope is not None,  # RISK-03: course-scoped, not global
        "candidates": candidates,
        "citation_validation": {
            "status": validation.status.value,
            "abstain": validation.abstain,
            "abstain_reason": validation.abstain_reason,
            "citation_count": len(citations),
            "evidence_backed_count": sum(1 for c in citations if c["has_evidence"]),
        },
    }


# ---------------------------------------------------------------------------
# Public trigger API (called from qa_service seam)
# ---------------------------------------------------------------------------


def trigger_evidence_shadow(
    question: str,
    course_id: Optional[Any],
    v1_sources: List[Dict[str, Any]],
    store: Optional[EvidenceTraceStore] = None,
) -> EvidenceShadowResult:
    """Trigger a V2 evidence/retrieval/citation shadow run after V1 retrieval.

    Called from ``qa_service.ask_question_with_rag`` AFTER
    ``retrieve_rag_context`` returns, BEFORE the V1 LLM call. NEVER raises
    into V1: all shadow errors are caught and returned as
    ``fallback_reason`` (business-level fail-closed).

    HARD CONSTRAINT (ADR §G3C): does NOT call the generation model.
    ``llm_calls`` is always 0.

    Parameters
    ----------
    question : str
        The user question (V1 already has it). Used only for trace; not
        sent to any model.
    course_id : Any, optional
        Course scope for V2 retrieval (RISK-03 isolation).
    v1_sources : list of dict
        V1 ragSources (path/score/match_type/content_preview). Read only.
    store : EvidenceTraceStore, optional
        Inject for tests.
    """
    start = time.time()
    store = store or EvidenceTraceStore()

    # 1. Flag check (conflict-aware).
    effective = _effective_evidence_mode()
    if effective.effective != "v2_shadow":
        return EvidenceShadowResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_v2_shadow",
            duration_ms=(time.time() - start) * 1000,
        )

    # 2. RISK-03: if no course scope, do NOT run V2 retrieval (would risk
    #    global leakage). Fail-closed with reason.
    if course_id is None:
        fc = shadow_runtime_fail_closed(EVIDENCE_CITATION_MODE, "v2_shadow", "missing_course_scope")
        return EvidenceShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )

    run_id = str(uuid.uuid4())
    try:
        v2 = _build_v2_candidates(question, course_id, v1_sources)

        # 3. Build the V1-vs-V2 comparison trace (contract/integration diff,
        #    NOT a quality comparison; NO second answer).
        trace = {
            "shadow_run_id": run_id,
            "triggered_at": time.time(),
            "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            "course_id": str(course_id),
            "effective_mode": "v2_shadow",
            "llm_calls": 0,  # HARD CONSTRAINT: no second LLM call
            "v1_rag_sources": v1_sources,
            "v2_candidates": v2["candidates"],
            "v2_scope_isolated": v2["scope_isolated"],
            "v2_citation_validation": v2["citation_validation"],
            "diff": {
                "v1_source_count": len(v1_sources),
                "v2_candidate_count": len(v2["candidates"]),
                "v2_evidence_backed_count": v2["citation_validation"]["evidence_backed_count"],
                "v2_abstain": v2["citation_validation"]["abstain"],
                "note": "contract/integration diff (not quality comparison)",
            },
        }
        path = store.write(run_id, trace)

        return EvidenceShadowResult(
            triggered=True,
            effective_mode="v2_shadow",
            trace_path=str(path),
            shadow_run_id=run_id,
            v2_candidate_count=len(v2["candidates"]),
            citation_abstain=v2["citation_validation"]["abstain"],
            duration_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        # Business-level fail-closed: any shadow error -> V1 continues.
        fc = shadow_runtime_fail_closed(
            EVIDENCE_CITATION_MODE, "v2_shadow", f"runtime:{type(e).__name__}:{e}"
        )
        logger.warning(f"[G3C evidence shadow] runtime error: {e}", exc_info=True)
        return EvidenceShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=fc.fallback_reason,
            duration_ms=(time.time() - start) * 1000,
        )
