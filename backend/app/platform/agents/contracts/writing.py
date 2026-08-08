"""Academic-writing ports for the ResearchAgent.

The contracts deliberately require evidence identifiers.  Implementations may
help structure or rewrite text, but they cannot invent citations or promote a
generated passage to verified course evidence.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class LiteratureReviewPort(Protocol):
    async def draft_review(
        self,
        *,
        course_id: str,
        research_question: str,
        evidence_ids: list[str],
        review_protocol: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class PaperStructurePort(Protocol):
    async def propose_structure(
        self,
        *,
        course_id: str,
        research_question: str,
        evidence_ids: list[str],
        template_id: str,
    ) -> Mapping[str, Any]: ...


__all__ = ["LiteratureReviewPort", "PaperStructurePort"]
