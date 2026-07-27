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
    """Real Judge0 sandbox port backed by ``SandboxClient`` and ``ExperimentRun``.

    Implements the ``SandboxPort`` protocol (``get_execution_result``).

    设计要点（修复"Judge0→TeachingAgent 仍未真正接通"）：
    - ``code_submission_id`` 即 ``ExperimentRun.run_id``，由前端在提交代码后传给 TeachingAgent
    - 健康时按 ``run_id`` + ``course_id`` 从本地 ``ExperimentRun`` 表读取已验证结果
      （而非直接暴露 Judge0 token 或调用 Judge0 API）
    - 同时读取关联的 ``ExperimentRunArtifact``（stdout/stderr/compile/test_report）
    - 严格 course_id 隔离：跨课程查询返回 not_found，不泄露他人结果
    - 健康检查失败或沙箱禁用时返回 ``sandbox_unavailable``，保留降级语义
    - DB 查询异常时返回 ``internal_error``，不抛出，保证 Agent/Q&A 不中断
    """

    def __init__(
        self,
        client: Any | None = None,
        *,
        session_factory: Any | None = None,
    ) -> None:
        if client is None:
            # Lazy import to avoid module-level side effects in tests.
            from app.services.sandbox_client import sandbox_client as _default
            client = _default
        self._client = client
        # session_factory 用于查询 ExperimentRun；None 时查询路径降级
        self._session_factory = session_factory
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
        """按 ``run_id`` 从本地 ``ExperimentRun`` 读取已验证结果。

        ``code_submission_id`` 是前端在提交代码后获得的 ``ExperimentRun.run_id``。
        本方法不调用 Judge0 API，而是读取已落库的运行结果（由 experiment_run_handler
        在沙箱执行完成后写入），保证 Agent 只读取已验证结果而非原始 Judge0 token。

        Returns:
            dict 至少包含：
            - ``available``: bool — False 表示沙箱不可用或结果不存在
            - ``status``: RunOutcome 值或 ``sandbox_unavailable`` / ``not_found`` / ``internal_error``
            - ``outcome``: RunOutcome 值（与 status 一致，便于 Agent 消费）
            - ``diagnosis``: 受限诊断摘要（compile_ok、passed_count/total_count、score、error_code）
            - ``stdout``/``stderr``/``compile_output``: 来自 ExperimentRunArtifact（截断保护）
            - ``test_summary``: 分层测试摘要（不泄露隐藏测试详情）
            - ``resource_usage``: cpu_time_ms/wall_time_ms/memory_kb
        """
        # Fast path: disabled or unhealthy → degrade without raising.
        if not self.is_enabled or not self._healthy:
            return {
                "available": False,
                "status": "sandbox_unavailable",
                "outcome": "sandbox_unavailable",
                "message": "代码沙箱未启用或健康检查失败，学习主流程正常降级",
            }

        # session_factory 缺失：查询路径无法执行，降级
        if self._session_factory is None:
            return {
                "available": False,
                "status": "internal_error",
                "outcome": "internal_error",
                "message": "session_factory 未注入，无法查询 ExperimentRun",
            }

        try:
            course_id_int = int(course_id)
        except (TypeError, ValueError):
            return {
                "available": False,
                "status": "not_found",
                "outcome": "not_found",
                "message": f"invalid course_id: {course_id!r}",
            }

        try:
            from app.models.experiment_model import (
                ExperimentRun,
                ExperimentRunArtifact,
            )
            from sqlmodel import select
        except ImportError as error:
            return {
                "available": False,
                "status": "internal_error",
                "outcome": "internal_error",
                "message": f"model import failed: {type(error).__name__}: {error}",
            }

        try:
            session = self._session_factory()
            try:
                # 严格 course_id 隔离：跨课程查询返回 not_found
                run = session.exec(
                    select(ExperimentRun).where(
                        ExperimentRun.run_id == code_submission_id,
                        ExperimentRun.course_id == course_id_int,
                    )
                ).first()
                if run is None:
                    return {
                        "available": False,
                        "status": "not_found",
                        "outcome": "not_found",
                        "message": f"运行 {code_submission_id} 在课程 {course_id} 下不存在",
                    }

                # 读取关联的 ExperimentRunArtifact（stdout/stderr/compile/test_report）
                artifacts_rows = session.exec(
                    select(ExperimentRunArtifact).where(
                        ExperimentRunArtifact.run_id == run.run_id,
                    )
                ).all()
                artifacts: dict[str, str] = {}
                for art in artifacts_rows:
                    artifacts[art.artifact_type] = art.content or ""

                # 截断保护：避免超大输出污染 Agent 上下文
                max_text = 4000

                def _trunc(text: str) -> str:
                    if not text:
                        return ""
                    return text if len(text) <= max_text else text[:max_text] + "\n[truncated]"

                outcome_value = run.outcome.value if hasattr(run.outcome, "value") else str(run.outcome)

                # 构建受限诊断摘要：包含 Agent 诊断所需的最小信息
                # 不泄露隐藏测试详情（test_summary 已由 experiment_run_handler 处理）
                diagnosis = {
                    "outcome": outcome_value,
                    "compile_ok": bool(run.compile_ok),
                    "compile_message": _trunc(run.compile_message),
                    "runtime_message": _trunc(run.runtime_message),
                    "passed_count": int(run.passed_count or 0),
                    "total_count": int(run.total_count or 0),
                    "score": float(run.score) if run.score is not None else None,
                    "error_code": run.error_code or "",
                    "error_message": _trunc(run.error_message),
                    "test_summary": run.test_summary or {},
                }

                return {
                    "available": True,
                    "status": outcome_value,
                    "outcome": outcome_value,
                    "run_id": run.run_id,
                    "attempt_id": run.attempt_id,
                    "language": run.language,
                    "diagnosis": diagnosis,
                    "stdout": _trunc(artifacts.get("stdout", "")),
                    "stderr": _trunc(artifacts.get("stderr", "")),
                    "compile_output": _trunc(artifacts.get("compile", "")),
                    "test_report": _trunc(artifacts.get("test_report", "")),
                    "test_summary": run.test_summary or {},
                    "resource_usage": {
                        "cpu_time_ms": run.cpu_time_ms,
                        "wall_time_ms": run.wall_time_ms,
                        "memory_kb": run.memory_kb,
                    },
                    "submitted_at": run.submitted_at.isoformat() if run.submitted_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
            finally:
                session.close()
        except Exception as error:  # noqa: BLE001 - degrade gracefully
            return {
                "available": False,
                "status": "internal_error",
                "outcome": "internal_error",
                "message": f"查询 ExperimentRun 异常: {type(error).__name__}: {error}",
            }
