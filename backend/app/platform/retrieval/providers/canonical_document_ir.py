"""Course-scoped retrieval over teacher-confirmed Canonical DocumentIR chunks."""
from __future__ import annotations

import re
from typing import List

from sqlmodel import select

from app.models.document_parse_model import RetrievalChunk, RetrievalIndexSnapshot
from app.models.database import session_factory
from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope


class CanonicalDocumentIRRetriever:
    """Read-only database retriever; Canonical projections remain authoritative."""

    @staticmethod
    def retrieve(
        query: str,
        *,
        scope: RetrievalScope,
        top_k: int,
    ) -> List[RetrievedChunk]:
        if scope.scope_type != "course" or not query or not query.strip():
            return []
        try:
            course_id = int(scope.scope_id)
        except (TypeError, ValueError):
            return []
        terms = _terms(query)
        if not terms:
            return []
        with session_factory() as session:
            active_snapshot = session.exec(select(RetrievalIndexSnapshot).where(
                RetrievalIndexSnapshot.course_id == course_id,
                RetrievalIndexSnapshot.status == "active",
            )).first()
            if active_snapshot is None:
                return []
            chunks = list(session.exec(select(RetrievalChunk).where(
                RetrievalChunk.course_id == course_id,
                RetrievalChunk.ir_version_id == active_snapshot.ir_version_id,
                RetrievalChunk.status == "active",
            )).all())
        ranked = []
        for chunk in chunks:
            text = (chunk.text or "").lower()
            score = sum(text.count(term) for term in terms)
            if score:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                content=chunk.text,
                scope=scope,
                retrieval_score=float(score),
                retrieval_source="canonical_document_ir",
                document_id=chunk.document_id,
                unit_id=chunk.unit_id,
                block_id=(chunk.block_ids or [None])[0],
                metadata={
                    "ir_version_id": chunk.ir_version_id,
                    "block_ids": list(chunk.block_ids or []),
                    "anchor_ids": list(chunk.anchor_ids or []),
                    "citation_closed": bool(chunk.anchor_ids),
                },
            )
            for score, chunk in ranked[:top_k]
        ]


def _terms(query: str) -> list[str]:
    """Use token terms when available, otherwise individual CJK characters."""
    normalized = query.lower().strip()
    tokens = [item for item in re.split(r"\s+", normalized) if item]
    if len(tokens) == 1 and len(tokens[0]) > 1 and not tokens[0].isascii():
        return list(dict.fromkeys(tokens[0]))
    return list(dict.fromkeys(tokens))
