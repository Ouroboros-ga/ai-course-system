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


__all__ = ["ScopePort", "KnowledgeGraphPort", "CourseRetrievalPort"]
