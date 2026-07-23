"""Small adapters around existing services; LangGraph nodes only see Ports."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ..errors import ScopeRejectedError, ServiceUnavailableError


class RetrievalDemoScopePort:
    """Course-first scope adapter for the isolated R2 course-sidecar provider."""

    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def validate_scope(self, *, student_id: str, course_id: str, resource_id: str | None) -> Mapping[str, Any]:
        if not student_id.strip() or course_id not in self._service.active_provider.course_ids:
            return {"allowed": False, "reason": "course_not_available"}
        return {"allowed": True, "source": "retrieval_demo_course_sidecar"}


class RetrievalDemoKnowledgeGraphPort:
    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def resolve_concepts(self, *, course_id: str, message: str, candidates: list[Mapping[str, Any]], resource_id: str | None) -> list[Mapping[str, Any]]:
        snapshot = self._service.active_provider.graph_snapshot(course_id)
        lowered = message.lower()
        matches = [node for node in snapshot.get("nodes", []) if str(node.get("label", "")).lower() in lowered or any(str(candidate.get("name", "")).lower() == str(node.get("label", "")).lower() for candidate in candidates)]
        return [{"concept_id": str(node["id"]), "name": node.get("label", node["id"]), "confidence": 0.8} for node in matches]

    async def get_context(self, *, course_id: str, concept_id: str) -> Mapping[str, Any]:
        snapshot = self._service.active_provider.graph_snapshot(course_id)
        edges = snapshot.get("edges", [])
        prerequisites = [{"concept_id": edge["source"]} for edge in edges if str(edge.get("target")) == concept_id and edge.get("relation") == "REQUIRES"]
        successors = [{"concept_id": edge["target"]} for edge in edges if str(edge.get("source")) == concept_id and edge.get("relation") == "REQUIRES"]
        return {"graph_version": snapshot.get("graph_version", "course-sidecar"), "concept_id": concept_id, "prerequisites": prerequisites, "successors": successors}


class RetrievalDemoEvidencePort:
    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def retrieve_course_evidence(self, *, course_id: str, message: str, concept_id: str | None, resource_id: str | None) -> list[Mapping[str, Any]]:
        result = self._service.query(course_id=course_id, question=message)
        if result.get("result", {}).get("status") != "ok":
            return []
        hits = result["result"].get("hits", [])
        # Map the R2 sidecar hit shape into the CourseRetrievalPort contract
        # ({evidence_id, resource_id, page_start, page_end, text}). The R2
        # provider's hits do NOT carry those names on the top level: the
        # citation-closed evidence identity lives in ``citations[0]`` and the
        # page anchor is ``page_or_slide`` (sidecar chunks are single-page).
        evidence: list[Mapping[str, Any]] = []
        for hit in hits:
            citations = hit.get("citations") or []
            if not citations:
                continue
            citation = citations[0]
            page = hit.get("page_or_slide")
            if page is None:
                page = citation.get("page_or_slide")
            evidence.append({
                "evidence_id": citation.get("research_evidence_id"),
                "resource_id": citation.get("artifact_id"),
                "page_start": page,
                "page_end": page,
                "text": hit.get("text_snippet", ""),
            })
        return [item for item in evidence if item.get("evidence_id")]


class CallableStudentModelingPort:
    """Wrap an application-owned read service without exposing it to graph nodes."""

    def __init__(self, get_state: Callable[..., Awaitable[Mapping[str, Any]]], get_weak: Callable[..., Awaitable[list[Mapping[str, Any]]]]) -> None:
        self._get_state, self._get_weak = get_state, get_weak

    async def get_concept_state(self, **kwargs: Any) -> Mapping[str, Any]: return await self._get_state(**kwargs)
    async def get_weak_concepts(self, **kwargs: Any) -> list[Mapping[str, Any]]: return await self._get_weak(**kwargs)


class CallableRecommendationPort:
    def __init__(self, recommend: Callable[..., Awaitable[Mapping[str, Any]]]) -> None: self._recommend = recommend
    async def recommend_next_action(self, **kwargs: Any) -> Mapping[str, Any]: return await self._recommend(**kwargs)


class CallableLearningEventPort:
    def __init__(self, record_event: Callable[..., Awaitable[None]], record_trace: Callable[..., Awaitable[None]]) -> None:
        self._record_event, self._record_trace = record_event, record_trace
    async def record_learning_event(self, **kwargs: Any) -> None: await self._record_event(**kwargs)
    async def record_agent_trace(self, **kwargs: Any) -> None: await self._record_trace(**kwargs)


class UnavailableSandboxPort:
    async def get_execution_result(self, **_: Any) -> Mapping[str, Any]:
        raise ServiceUnavailableError("sandbox port was not injected")
