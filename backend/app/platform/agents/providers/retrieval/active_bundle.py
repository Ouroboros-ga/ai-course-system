"""Read-only TeachingAgent adapters over the active CourseKnowledgeBundle."""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from fastapi import HTTPException

from app.models.database import session_factory
from app.platform.knowledge.sql_lance_provider import SqlLanceCourseKnowledgeProvider
from app.services.course_access_service import resolve_course_access

from ...errors import ScopeRejectedError, ServiceUnavailableError


class ActiveBundleScopePort:
    """Fail-closed Course Access v1 gate for non-HTTP agent invocations."""

    async def validate_scope(
        self,
        *,
        student_id: str,
        course_id: str,
        resource_id: str | None,
    ) -> Mapping[str, Any]:
        try:
            user_id = int(student_id)
            course = _course_id(course_id)
            with session_factory() as session:
                access = resolve_course_access(
                    session,
                    {"user_id": user_id},
                    course,
                )
                allowed = (
                    access.allows("knowledge.view")
                    and access.allows("course.citation.read")
                )
        except (TypeError, ValueError, HTTPException):
            allowed = False
        if not allowed:
            raise ScopeRejectedError("course knowledge scope rejected")
        return {
            "allowed": True,
            "source": "course_access_v1",
            "resource_id": resource_id,
        }


class ActiveBundleKnowledgeGraphPort:
    def __init__(self, provider=None) -> None:
        self._provider = provider or SqlLanceCourseKnowledgeProvider()

    async def resolve_concepts(
        self,
        *,
        course_id: str,
        message: str,
        candidates: list[Mapping[str, Any]],
        resource_id: str | None,
    ) -> list[Mapping[str, Any]]:
        course = _course_id(course_id)
        graph = await asyncio.to_thread(self._provider.get_graph, course)
        if graph is None:
            raise ServiceUnavailableError("active course knowledge bundle pending")
        lowered = message.casefold()
        exact = [
            node for node in graph.nodes
            if str(node.get("title") or node.get("label") or "").casefold() in lowered
        ]
        candidate_names = {
            str(item.get("name") or "").casefold() for item in candidates
        }
        exact.extend(
            node for node in graph.nodes
            if str(node.get("title") or node.get("label") or "").casefold() in candidate_names
            and node not in exact
        )
        if not exact and message.strip():
            result = await asyncio.to_thread(
                self._provider.search_evidence,
                course,
                message,
                top_k=6,
            )
            if result is not None:
                matched_keys = {
                    item.node_key for item in result.items if item.node_key
                }
                exact = [
                    node for node in graph.nodes
                    if str(node.get("id")) in matched_keys
                ]
        return [{
            "concept_id": str(node["id"]),
            "name": node.get("title") or node.get("label") or node["id"],
            "confidence": 0.9,
            "bundle_id": graph.bundle.bundle_id,
            "graph_snapshot_id": graph.bundle.graph_snapshot_id,
        } for node in exact[:12]]

    async def get_context(
        self,
        *,
        course_id: str,
        concept_id: str,
    ) -> Mapping[str, Any]:
        course = _course_id(course_id)
        node = await asyncio.to_thread(self._provider.get_node, course, concept_id)
        bundle = await asyncio.to_thread(self._provider.get_active_bundle, course)
        if node is None or bundle is None:
            raise ServiceUnavailableError("active course knowledge node unavailable")
        return {
            "bundle_id": bundle.bundle_id,
            "graph_snapshot_id": bundle.graph_snapshot_id,
            "concept_id": node.node_key,
            "knowledge_node_id": node.knowledge_node_id,
            "name": node.title,
            "description": node.description,
            "prerequisites": [{"concept_id": item} for item in node.prerequisites],
            "successors": [{"concept_id": item} for item in node.successors],
            "citation_ids": list(node.citation_ids),
        }


class ActiveBundleCourseRetrievalPort:
    def __init__(self, provider=None) -> None:
        self._provider = provider or SqlLanceCourseKnowledgeProvider()

    async def retrieve_course_evidence(
        self,
        *,
        course_id: str,
        message: str,
        concept_id: str | None,
        resource_id: str | None,
    ) -> list[Mapping[str, Any]]:
        course = _course_id(course_id)
        result = await asyncio.to_thread(
            self._provider.search_evidence,
            course,
            message,
            top_k=6,
            node_keys=(concept_id,) if concept_id else (),
        )
        if result is None:
            return []
        return [{
            "evidence_id": item.evidence_ids[0] if item.evidence_ids else None,
            "resource_id": item.document_id,
            "page_start": item.page_number,
            "page_end": item.page_number,
            "text": item.content,
            "node_key": item.node_key,
            "knowledge_node_id": item.knowledge_node_id,
            "citation_ids": list(item.citation_ids),
            "bundle_id": result.bundle.bundle_id,
            "graph_snapshot_id": result.bundle.graph_snapshot_id,
            "vector_index_id": result.bundle.vector_index_id,
            "retrieval_sources": list(item.retrieval_sources),
        } for item in result.items if item.evidence_ids and item.citation_ids]


def _course_id(value: str) -> int:
    try:
        course_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ServiceUnavailableError("invalid course scope") from exc
    if course_id <= 0:
        raise ServiceUnavailableError("invalid course scope")
    return course_id
