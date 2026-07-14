"""Retrieval provider contracts — BM25, vector, fusion (RRF), and rerank.

These are Protocol definitions only. Real model implementations require
approval (dependency install, model download). Fakes are provided for
contract testing.

Design rules (per plan §5 and RISK-10):
- No real vector model / BM25 / cross-encoder may be installed.
- Fakes must prove control flow, error semantics, and isolation.
- Reranking/prompt construction must NOT discard evidence IDs.
- Fusion (RRF) must work with mixed sparse+dense inputs.

Contract version: ``retrieval-provider/1.0`` (major=1).
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, runtime_checkable

from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BM25 Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class BM25Provider(Protocol):
    """Sparse retrieval provider using BM25 scoring.

    ``index`` builds a BM25 index for the given scope.
    ``retrieve`` returns BM25-scored chunks.
    ``has_scope`` / ``clear_scope`` manage lifecycle.
    """

    def index(self, scope: RetrievalScope, documents: List[str]) -> None:
        """Build BM25 index from a list of document texts."""
        ...

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        ...

    def has_scope(self, scope: RetrievalScope) -> bool:
        ...

    def clear_scope(self, scope: RetrievalScope) -> bool:
        ...


# ---------------------------------------------------------------------------
# Vector Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorProvider(Protocol):
    """Dense retrieval provider using vector embeddings.

    ``index`` builds a vector index for the given scope.
    ``retrieve`` returns vector-scored chunks.
    ``has_scope`` / ``clear_scope`` manage lifecycle.

    Real implementations require approval — do not install embedding models.
    """

    def index(self, scope: RetrievalScope, documents: List[str]) -> None:
        ...

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        ...

    def has_scope(self, scope: RetrievalScope) -> bool:
        ...

    def clear_scope(self, scope: RetrievalScope) -> bool:
        ...


# ---------------------------------------------------------------------------
# Fusion (RRF)
# ---------------------------------------------------------------------------


@dataclass
class FusionConfig:
    """Configuration for Reciprocal Rank Fusion.

    ``k`` is the RRF constant (default 60, standard in literature).
    ``weights`` optionally weights per-source results (must sum to 1.0).
    """

    k: int = 60
    weights: Optional[Dict[str, float]] = None


def rrf_fuse(
    results_by_source: Dict[str, List[RetrievedChunk]],
    config: FusionConfig = FusionConfig(),
    top_k: int = 10,
) -> List[RetrievedChunk]:
    """Reciprocal Rank Fusion for combining sparse + dense results.

    Each source produces its own ranked list. RRF computes:
        score(d) = sum_over_sources( weight_s / (k + rank_s(d)) )

    The fused list is sorted descending by RRF score.
    Evidence IDs from the original chunks are preserved in the output.

    Args:
        results_by_source:  Dict mapping source name (e.g. "bm25", "vector")
                            to its ranked RetrievedChunk list.
        config:             FusionConfig (k constant, optional weights).
        top_k:              Max items in the fused result.

    Returns:
        Fused list of RetrievedChunk, sorted by descending RRF score.
        Each chunk carries its original evidence fields.
    """
    if not results_by_source:
        return []

    weights = config.weights or {}
    rrf_scores: Dict[str, float] = {}
    chunk_map: Dict[str, RetrievedChunk] = {}

    for source_name, chunks in results_by_source.items():
        weight = weights.get(source_name, 1.0)
        for rank, chunk in enumerate(chunks):
            cid = chunk.chunk_id
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + weight / (
                config.k + rank + 1
            )
            chunk_map[cid] = chunk

    sorted_chunks = sorted(
        chunk_map.values(),
        key=lambda c: rrf_scores.get(c.chunk_id, 0.0),
        reverse=True,
    )
    return sorted_chunks[:top_k]


# ---------------------------------------------------------------------------
# Reranker Provider
# ---------------------------------------------------------------------------


@runtime_checkable
class RerankerProvider(Protocol):
    """Cross-encoder reranker provider.

    ``rerank`` takes a query and candidate chunks, returns re-ranked chunks
    with updated scores.

    Real implementations require approval — do not install cross-encoder models.
    """

    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        *,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        ...


# ---------------------------------------------------------------------------
# Fakes (for contract testing)
# ---------------------------------------------------------------------------


class FakeBM25Provider:
    """Fake BM25 for contract testing — simple word overlap scoring.

    Not a real BM25 implementation. Proves control flow, not retrieval quality.
    """

    def __init__(self) -> None:
        self._indices: Dict[str, List[str]] = {}

    def index(self, scope: RetrievalScope, documents: List[str]) -> None:
        self._indices[scope.key] = documents
        logger.info(f"[FakeBM25] indexed {len(documents)} docs for {scope.key}")

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        if not query or not query.strip():
            return []
        docs = self._indices.get(scope.key)
        if not docs:
            return []
        query_lower = query.lower().strip()
        # Use substring matching (works for Chinese which has no word delimiters)
        scored = []
        for i, doc in enumerate(docs):
            doc_lower = doc.lower()
            if query_lower in doc_lower:
                # Score based on how many times the query appears
                count = doc_lower.count(query_lower)
                scored.append((doc, count))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=f"fake_bm25_{i}",
                content=doc,
                scope=scope,
                retrieval_score=float(score) / 10.0,
                retrieval_source="bm25",
            )
            for i, (doc, score) in enumerate(scored[:top_k])
        ]

    def has_scope(self, scope: RetrievalScope) -> bool:
        return scope.key in self._indices

    def clear_scope(self, scope: RetrievalScope) -> bool:
        return self._indices.pop(scope.key, None) is not None


class FakeVectorProvider:
    """Fake vector provider for contract testing — simple token overlap.

    Not a real embedding model. Proves control flow, not retrieval quality.
    """

    def __init__(self) -> None:
        self._indices: Dict[str, List[str]] = {}

    def index(self, scope: RetrievalScope, documents: List[str]) -> None:
        self._indices[scope.key] = documents
        logger.info(f"[FakeVector] indexed {len(documents)} docs for {scope.key}")

    def retrieve(
        self,
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        if not query or not query.strip():
            return []
        docs = self._indices.get(scope.key)
        if not docs:
            return []
        query_lower = query.lower().strip()
        scored = []
        for i, doc in enumerate(docs):
            doc_lower = doc.lower()
            if query_lower in doc_lower:
                count = doc_lower.count(query_lower)
                scored.append((doc, count))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            RetrievedChunk(
                chunk_id=f"fake_vec_{i}",
                content=doc,
                scope=scope,
                retrieval_score=float(score) / 10.0,
                retrieval_source="vector",
            )
            for i, (doc, score) in enumerate(scored[:top_k])
        ]

    def has_scope(self, scope: RetrievalScope) -> bool:
        return scope.key in self._indices

    def clear_scope(self, scope: RetrievalScope) -> bool:
        return self._indices.pop(scope.key, None) is not None


class FakeRerankerProvider:
    """Fake reranker for contract testing — identity rerank with score tweak.

    Returns candidates in the same order with a confidence-adjusted score.
    Does NOT discard evidence IDs (preserves all original fields).
    """

    def rerank(
        self,
        query: str,
        candidates: List[RetrievedChunk],
        *,
        top_k: int = 5,
    ) -> List[RetrievedChunk]:
        if not candidates:
            return []
        # Simple identity rerank: preserve order, tweak score
        reranked = []
        for i, chunk in enumerate(candidates):
            reranked.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    scope=chunk.scope,
                    source_id=chunk.source_id,
                    source_name=chunk.source_name,
                    chapter_id=chunk.chapter_id,
                    chapter_title=chunk.chapter_title,
                    page_number=chunk.page_number,
                    retrieval_score=(chunk.retrieval_score or 0.0) * 1.05,
                    retrieval_source="reranked",
                    match_type=chunk.match_type,
                    path=chunk.path,
                    metadata={**chunk.metadata, "reranked": True},
                    artifact_id=chunk.artifact_id,
                    document_id=chunk.document_id,
                    unit_id=chunk.unit_id,
                    block_id=chunk.block_id,
                    evidence_spans=list(chunk.evidence_spans),
                )
            )
        return reranked[:top_k]
