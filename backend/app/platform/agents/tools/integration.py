"""Small adapters around existing services; LangGraph nodes only see Ports."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Mapping

from ..errors import ScopeRejectedError, ServiceUnavailableError


class RetrievalDemoScopePort:
    """Validate input identity only; endpoint Course Access is authoritative.

    Course-sidecar availability is an optional enhancement signal, never an
    authorization decision. A missing sidecar must not turn ordinary course
    Q&A into a scope rejection.
    """

    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def validate_scope(self, *, student_id: str, course_id: str, resource_id: str | None) -> Mapping[str, Any]:
        if not student_id.strip() or not course_id.strip():
            return {"allowed": False, "reason": "scope_invalid"}
        available = course_id in self._service.active_provider.course_ids
        return {"allowed": True, "course_sidecar_available": available, "source": "retrieval_demo_course_sidecar" if available else "course_sidecar_pending"}


class RetrievalDemoKnowledgeGraphPort:
    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def resolve_concepts(self, *, course_id: str, message: str, candidates: list[Mapping[str, Any]], resource_id: str | None) -> list[Mapping[str, Any]]:
        if course_id not in self._service.active_provider.course_ids:
            raise ServiceUnavailableError("course knowledge graph pending")
        snapshot = self._service.active_provider.graph_snapshot(course_id)
        lowered = message.lower()
        matches = [node for node in snapshot.get("nodes", []) if str(node.get("label", "")).lower() in lowered or any(str(candidate.get("name", "")).lower() == str(node.get("label", "")).lower() for candidate in candidates)]
        return [{"concept_id": str(node["id"]), "name": node.get("label", node["id"]), "confidence": 0.8} for node in matches]

    async def get_context(self, *, course_id: str, concept_id: str) -> Mapping[str, Any]:
        if course_id not in self._service.active_provider.course_ids:
            raise ServiceUnavailableError("course knowledge graph pending")
        snapshot = self._service.active_provider.graph_snapshot(course_id)
        edges = snapshot.get("edges", [])
        prerequisites = [{"concept_id": edge["source"]} for edge in edges if str(edge.get("target")) == concept_id and edge.get("relation") == "REQUIRES"]
        successors = [{"concept_id": edge["target"]} for edge in edges if str(edge.get("source")) == concept_id and edge.get("relation") == "REQUIRES"]
        return {"graph_version": snapshot.get("graph_version", "course-sidecar"), "concept_id": concept_id, "prerequisites": prerequisites, "successors": successors}


class RetrievalDemoEvidencePort:
    def __init__(self, demo_service: Any) -> None:
        self._service = demo_service

    async def retrieve_course_evidence(self, *, course_id: str, message: str, concept_id: str | None, resource_id: str | None) -> list[Mapping[str, Any]]:
        # 课程不在 R2 白名单时回退到空证据（V1 路径），不抛异常：
        # 约束：R2 失败/无 sidecar 不得影响正常 Q&A。
        if course_id not in self._service.active_provider.course_ids:
            return []
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


class Judge0SandboxPort:
    """P1-7: Real Judge0 sandbox port backed by ``SandboxClient``.

    Implements the ``SandboxPort`` protocol (``get_execution_result``).
    Constructed with a ``SandboxClient`` instance (or the module-level
    singleton). The port always returns a structured dict; it never
    raises — when the sandbox is unavailable, ``status`` is set to
    ``sandbox_unavailable`` so the Agent can degrade gracefully.

    Health-check degradation:
    - On construction, we run ``client.health_check()`` and cache the
      result. If the health check fails, the port still accepts calls
      but every call returns ``sandbox_unavailable``. This preserves
      the constraint that Agent/Q&A must not crash when Judge0 is down.
    - The health-check result is exposed via ``is_healthy`` for
      observability, but the Agent workflow does not gate on it.
    """

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            # Lazy import to avoid module-level side effects in tests.
            from app.services.sandbox_client import sandbox_client as _default
            client = _default
        self._client = client
        try:
            self._healthy = bool(client.health_check())
        except Exception:  # noqa: BLE001 - never block agent startup
            self._healthy = False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def is_enabled(self) -> bool:
        return bool(getattr(self._client, "enabled", False))

    async def get_execution_result(
        self,
        *,
        student_id: str,
        course_id: str,
        code_submission_id: str,
        **_: Any,
    ) -> Mapping[str, Any]:
        """Look up a prior sandbox submission by its token.

        The Agent only reads prior execution results — it does not
        submit new code. Code submission happens through the experiment
        endpoints, which create ``ExperimentRun`` rows and dispatch
        ``experiment_run`` tasks. The ``code_submission_id`` here is
        the Judge0 token (stored as ``ExperimentRun.run_id`` or a
        dedicated token column).

        Returns a dict with at least:
        - ``status``: SubmissionStatus value or ``sandbox_unavailable``
        - ``available``: bool — False when sandbox is down/disabled
        """
        # Fast path: disabled or unhealthy → degrade without raising.
        if not self.is_enabled or not self._healthy:
            return {
                "available": False,
                "status": "sandbox_unavailable",
                "message": "代码沙箱未启用或健康检查失败，学习主流程正常降级",
            }

        try:
            # We do not call submit_code here; the Agent port is read-only.
            # A future method on SandboxClient (get_submission_by_token)
            # can be wired in when Judge0 async polling is needed. For now
            # we return a structured "not_implemented" result so callers
            # know the lookup path is not yet wired, without raising.
            return {
                "available": True,
                "status": "not_implemented",
                "message": (
                    "Judge0 沙箱可用但按 token 查询接口尚未实现；"
                    "请通过 experiment_run_handler 获取执行结果"
                ),
                "code_submission_id": code_submission_id,
            }
        except Exception as error:  # noqa: BLE001 - degrade gracefully
            return {
                "available": False,
                "status": "sandbox_unavailable",
                "message": f"沙箱查询异常: {type(error).__name__}: {error}",
            }
