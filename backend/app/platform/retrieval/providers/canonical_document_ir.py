"""Course-scoped retrieval over teacher-confirmed Canonical DocumentIR chunks."""
from __future__ import annotations

import re
from typing import List

from sqlmodel import select

from app.models.course_build_model import CourseRelease, CourseRetrievalSnapshot, ReleaseStatus
from app.models.document_parse_model import RetrievalChunk
from app.models.database import session_factory
from app.platform.retrieval.schemas import RetrievedChunk, RetrievalScope


class CanonicalDocumentIRRetriever:
    """Read-only database retriever; Canonical projections remain authoritative."""

    @staticmethod
    def has_active_release(scope: RetrievalScope) -> bool:
        """Whether a course is governed by the P4 frozen-release boundary."""
        if scope.scope_type != "course":
            return False
        try:
            course_id = int(scope.scope_id)
        except (TypeError, ValueError):
            return False
        try:
            with session_factory() as session:
                return session.exec(select(CourseRelease).where(
                    CourseRelease.course_id == course_id,
                    CourseRelease.is_active == True,  # noqa: E712
                    CourseRelease.status == ReleaseStatus.PUBLISHED,
                )).first() is not None
        except Exception:
            return False

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
            # A student-facing course must read the exact IR set frozen by its
            # active release. A later reparse may create a newer active
            # material snapshot, but must not silently change published QA.
            release = session.exec(select(CourseRelease).where(
                CourseRelease.course_id == course_id,
                CourseRelease.is_active == True,  # noqa: E712
                CourseRelease.status == ReleaseStatus.PUBLISHED,
            )).first()
            # No active course release means this provider must fail closed.
            # Teacher-side candidate retrieval uses a dedicated endpoint and
            # never reaches the learner QA gateway.
            if release is None:
                return []
            frozen_snapshot = None
            if release.retrieval_snapshot_id:
                frozen_snapshot = session.exec(select(CourseRetrievalSnapshot).where(
                    CourseRetrievalSnapshot.course_id == course_id,
                    CourseRetrievalSnapshot.retrieval_snapshot_id == release.retrieval_snapshot_id,
                    CourseRetrievalSnapshot.snapshot_kind == "release",
                    CourseRetrievalSnapshot.status == "ready",
                )).first()
            # Releases made before P4 do not have a frozen chunk manifest.
            # Keep their historical IR-version compatibility path, but never
            # fall back to a newer active parse index.
            released_ir_versions = list(release.document_ir_version_ids or [])
            if frozen_snapshot is None and not released_ir_versions:
                return []
            chunk_stmt = select(RetrievalChunk).where(
                RetrievalChunk.course_id == course_id,
            )
            if frozen_snapshot is not None:
                chunk_ids = list(frozen_snapshot.retrieval_chunk_ids or [])
                if not chunk_ids:
                    return []
                # Status is deliberately not re-evaluated here: the snapshot
                # already proved these chunks were evidence-confirmed when
                # published, and later teacher-side review must not mutate an
                # existing learner release.
                chunk_stmt = chunk_stmt.where(RetrievalChunk.chunk_id.in_(chunk_ids))
            elif released_ir_versions:
                chunk_stmt = chunk_stmt.where(RetrievalChunk.status == "active")
                chunk_stmt = chunk_stmt.where(RetrievalChunk.ir_version_id.in_(released_ir_versions))
            chunks = list(session.exec(chunk_stmt).all())
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
