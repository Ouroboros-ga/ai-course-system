"""Product 1 R2 sidecar retrieval shadow -- mainline wiring.

Plugs the real R2 retrieval (BM25 + local BGE Dense + RRF, with Evidence /
Citation closure) into the V1 QA mainline ``qa_service.ask_question_with_rag``
WITHOUT changing default V1 behavior.

Activation (ADR-0006 shadow discipline):
- Trigger only when ``DOCUMENT_KG_RUNTIME_MODE`` is effectively ``v2_shadow``
  (after conflict resolution: requires ``DOCUMENT_PIPELINE_VERSION`` also
  effectively v2_shadow). This is the retrieval-runtime flag; it is the
  parent of ``EVIDENCE_CITATION_MODE`` and ``KNOWLEDGE_GRAPH_PIPELINE_VERSION``.
- When triggered, R2 retrieval REPLACES the V1 ``rag_context`` / ``rag_sources``
  that feed the (single, still-V1) LLM call. There is NO second LLM call.
- When the flag is off, the course has no Evidence sidecar, R2 abstains, or
  any runtime error occurs: ``triggered=False`` and the caller keeps the V1
  retrieval result untouched (business fail-closed). V1 is never affected.

HARD CONSTRAINTS:
- No fabricated hits: a course without a sidecar, or an R2 abstain, returns
  ``triggered=False`` and falls back to V1. R2 never synthesizes citations.
- Course isolation (RISK-03): ``course_id`` is required; missing scope returns
  ``triggered=False`` (no global retrieval).
- The R2 provider is the same real implementation used by the retrieval-demo
  endpoint (``CourseSidecarR2Provider``); it never opens Reviewed Silver,
  qrels, query labels, or the production ORM.

The V1 ``rag_sources`` shape is ``{path, score, match_type, content_preview}``;
R2 hits are mapped into that shape so the existing prompt builder and the
``/chat/ask`` response contract are unchanged.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.feature_flags import (
    DOCUMENT_KG_RUNTIME_MODE,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shadow trigger result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class R2RetrievalShadowResult:
    """Outcome of an R2 sidecar retrieval shadow trigger on the QA mainline.

    ``triggered`` is True when R2 retrieval succeeded and the V1
    ``rag_context`` / ``rag_sources`` SHOULD be replaced by ``rag_context`` /
    ``rag_sources`` carried on this result. When the flag is disabled, the
    course has no sidecar, R2 abstained, or a runtime error occurred,
    ``triggered`` is False, ``fallback_reason`` explains why, and the caller
    MUST keep the V1 values. V1 is never affected. ``llm_calls`` is always 0
    (no LLM call here; the single LLM call is still made by the V1 mainline).
    """

    triggered: bool
    effective_mode: str
    rag_context: Optional[str] = None
    rag_sources: Optional[List[Dict[str, Any]]] = None
    hit_count: int = 0
    fallback_reason: Optional[str] = None
    llm_calls: int = 0
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Configured-mode reader (mirrors evidence_shadow._configured_modes)
# ---------------------------------------------------------------------------


def _configured_modes() -> Dict[str, str]:
    try:
        from app.core.config import settings
        from app.core.feature_flags import ALL_FLAGS

        return {f: getattr(settings, f) for f in ALL_FLAGS}
    except Exception:
        return {}


def _effective_runtime_mode():
    return resolve_effective_modes(_configured_modes())[DOCUMENT_KG_RUNTIME_MODE]


# ---------------------------------------------------------------------------
# R2 hit -> V1 rag_sources shape
# ---------------------------------------------------------------------------


def _hit_to_source(hit: Dict[str, Any]) -> Dict[str, Any]:
    """Map one R2 hit into the V1 ``rag_sources`` shape.

    The R2 provider exposes ``research_chunk_id`` (a stable, sidecar-anchored
    identifier) on each hit but does not surface ``unit_id``; the latter stays
    on the internal corpus row. We use ``research_chunk_id`` as ``path`` -- it
    is stable and traceable. ``match_type`` distinguishes R2 hybrid retrieval
    from V1 tree keyword matches; ``content_preview`` carries the
    citation-closed snippet.
    """
    snippet = str(hit.get("text_snippet") or "")
    chunk_id = str(hit.get("research_chunk_id") or "")
    return {
        "path": chunk_id,
        "score": hit.get("score"),
        "match_type": "rrf_hybrid_bm25_dense",
        "content_preview": snippet,
    }


def _build_context(question: str, sources: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for i, src in enumerate(sources, 1):
        parts.append(f"【来源{i}: {src['path']}】\n{src['content_preview']}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


def trigger_r2_retrieval_shadow(
    *,
    question: str,
    course_id: Any,
    v1_context: str,
    v1_sources: List[Dict[str, Any]],
) -> R2RetrievalShadowResult:
    """Run R2 sidecar retrieval in shadow; optionally replace V1 context.

    Called from ``qa_service.ask_question_with_rag`` AFTER V1 retrieval
    succeeds and BEFORE the V1 LLM call. The caller only applies the result
    when ``triggered`` is True; otherwise V1 ``rag_context`` / ``rag_sources``
    are left untouched.

    Returns a result regardless of outcome; never raises (business
    fail-closed). Any unexpected error is recorded as ``fallback_reason``
    and ``triggered=False`` so V1 continues unaffected.
    """
    started = time.perf_counter()
    effective = _effective_runtime_mode()
    if effective.effective != "v2_shadow":
        return R2RetrievalShadowResult(
            triggered=False,
            effective_mode=effective.effective,
            fallback_reason=effective.fallback_reason or "flag_not_v2_shadow",
        )

    # RISK-03: no course scope -> no global retrieval.
    if course_id is None:
        fc = shadow_runtime_fail_closed(
            DOCUMENT_KG_RUNTIME_MODE, "v2_shadow", "missing_course_scope"
        )
        return R2RetrievalShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason="missing_course_scope",
        )

    try:
        from app.platform.retrieval_demo.course_provider import (
            CourseSidecarR2Provider,
        )

        provider = CourseSidecarR2Provider()

        # Course without a sidecar -> silent fallback to V1 (not an error).
        try:
            available = course_id in provider.course_ids
        except Exception:
            available = False
        if not available:
            return R2RetrievalShadowResult(
                triggered=False,
                effective_mode="v2_shadow",
                fallback_reason="course_sidecar_not_available",
            )

        result = provider.retrieve(course_id=str(course_id), question=question)

        status = result.get("status")
        hits = result.get("hits") or []
        if status != "ok" or not hits:
            return R2RetrievalShadowResult(
                triggered=False,
                effective_mode="v2_shadow",
                fallback_reason=f"r2_abstained:{result.get('abstain_reason') or status}",
            )

        # Map R2 hits into the V1 rag_sources shape and rebuild the context
        # text that feeds the (single, still-V1) LLM call.
        sources = [_hit_to_source(hit) for hit in hits[:10]]
        context = _build_context(question, sources)
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        return R2RetrievalShadowResult(
            triggered=True,
            effective_mode="v2_shadow",
            rag_context=context,
            rag_sources=sources,
            hit_count=len(sources),
            duration_ms=duration_ms,
        )
    except Exception as error:  # noqa: BLE001 -- business fail-closed
        logger.warning("[R2 retrieval shadow] suppressed (V1 unaffected): %s", error)
        fc = shadow_runtime_fail_closed(
            DOCUMENT_KG_RUNTIME_MODE, "v2_shadow", "runtime_error"
        )
        return R2RetrievalShadowResult(
            triggered=False,
            effective_mode=fc.effective,
            fallback_reason=f"runtime_error:{type(error).__name__}",
        )
