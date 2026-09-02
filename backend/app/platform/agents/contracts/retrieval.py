"""Retrieval and scope ports: course access, knowledge graph, evidence."""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class ScopePort(Protocol):
    """Validate the learner subject's course scope.

    The HTTP layer authenticates the caller and resolves course membership.
    Ports retain ``student_id`` for compatibility with persisted cognition
    records, where it means the learner subject rather than the caller.
    """
    async def validate_scope(self, *, student_id: str, course_id: str, resource_id: str | None) -> Mapping[str, Any]: ...


class KnowledgeGraphPort(Protocol):
    async def resolve_concepts(self, *, course_id: str, message: str, candidates: list[Mapping[str, Any]], resource_id: str | None) -> list[Mapping[str, Any]]: ...
    async def get_context(self, *, course_id: str, concept_id: str) -> Mapping[str, Any]: ...


class CourseRetrievalPort(Protocol):
    async def retrieve_course_evidence(self, *, course_id: str, message: str, concept_id: str | None, resource_id: str | None) -> list[Mapping[str, Any]]: ...


class DisciplineKnowledgePort(Protocol):
    """Supplementary CS discipline references (authoritative textbook summaries).

    Results are marked ``is_supplementary`` and carry no ``evidence_id``: they
    ground the teaching answer but never become formal course citations,
    mastery input, or graph edges (AGENTS.md §4.1.5).
    """

    async def search_discipline_knowledge(self, *, course_id: str, message: str, concept_id: str | None, top_k: int = 3) -> list[Mapping[str, Any]]: ...


__all__ = ["ScopePort", "KnowledgeGraphPort", "CourseRetrievalPort", "DisciplineKnowledgePort"]
