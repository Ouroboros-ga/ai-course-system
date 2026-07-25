"""Per-(student, course) runtime registry for the TeachingAgent.

批次4：将单报告 Shadow 的 TeachingAgent 改成按课程/学生创建的正式运行时。

设计要点：
- 按 ``(student_id, course_id)`` 动态构建并缓存 ``TeachingAgentRuntime``。
- 每个运行时绑定其对应的 KGMestShadowReport（来自 ``KGMestShadowReportStore``）。
- fail-closed：无报告/无 LLM/无侧车时返回 ``None``，端点保持 503。
- 不在启动时预加载所有报告；运行时按需构建。
- 缓存按 ``(student_id, course_id)`` 字符串对，键值与 store 一致。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .composition import build_kg_mest_shadow_sidecar_runtime
from .contracts import (
    CognitionPort,
    LearningEventPort,
    QuestionBankPort,
    RecommendationPort,
    SandboxPort,
    TeachingLLMPort,
    WebResearchPort,
)
from .kg_mest_report_store import KGMestShadowReportStore
from .runtime import TeachingAgentRuntime

logger = logging.getLogger(__name__)


class TeachingAgentRuntimeRegistry:
    """Cache and build ``TeachingAgentRuntime`` instances per (student_id, course_id).

    The registry is constructed once at startup with the shared dependencies
    (demo service, LLM adapter, recommendation / sandbox / event ports). Each
    (student, course) pair gets its own runtime bound to its own KG-MEST
    Shadow report the first time it is requested; subsequent requests reuse
    the cached runtime.
    """

    def __init__(
        self,
        *,
        demo_service: Any,
        llm: TeachingLLMPort,
        recommendation: RecommendationPort,
        sandbox: SandboxPort,
        learning_events: LearningEventPort,
        store: Optional[KGMestShadowReportStore] = None,
        web_research: Optional[WebResearchPort] = None,
        cognition: Optional[CognitionPort] = None,
        question_bank: Optional[QuestionBankPort] = None,
    ) -> None:
        self._demo_service = demo_service
        self._llm = llm
        self._recommendation = recommendation
        self._sandbox = sandbox
        self._learning_events = learning_events
        self._store = store or KGMestShadowReportStore()
        self._web_research = web_research
        self._cognition = cognition
        self._question_bank = question_bank
        self._cache: dict[tuple[str, str], TeachingAgentRuntime] = {}

    def get_or_create(
        self,
        student_id: str,
        course_id: str,
    ) -> Optional[TeachingAgentRuntime]:
        """Return the runtime for ``(student_id, course_id)``, or ``None``.

        Returns ``None`` when:
        - the report store has no approved report for this pair, or
        - building the runtime raises (fail-closed; logged but not raised).
        """
        key = (str(student_id), str(course_id))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            report = self._store.read(key[0], key[1])
        except Exception as error:  # noqa: BLE001 -- fail-closed: never raise
            logger.warning(
                "TeachingAgent registry: report read failed for student=%s course=%s: %s: %s",
                key[0], key[1], type(error).__name__, error,
            )
            return None
        if report is None:
            return None
        try:
            runtime = build_kg_mest_shadow_sidecar_runtime(
                demo_service=self._demo_service,
                shadow_report=report,
                expected_student_id=key[0],
                expected_course_id=key[1],
                recommendation=self._recommendation,
                sandbox=self._sandbox,
                learning_events=self._learning_events,
                llm=self._llm,
                web_research=self._web_research,
                cognition=self._cognition,
                question_bank=self._question_bank,
            )
        except Exception as error:  # noqa: BLE001 -- fail-closed: never raise
            logger.warning(
                "TeachingAgent registry: runtime build failed for student=%s course=%s: %s: %s",
                key[0], key[1], type(error).__name__, error,
            )
            return None
        self._cache[key] = runtime
        return runtime

    def list_cached_scopes(self) -> list[tuple[str, str]]:
        """Return the (student_id, course_id) pairs currently cached."""
        return list(self._cache.keys())

    def invalidate(self, student_id: str, course_id: str) -> None:
        """Drop a cached runtime so the next request rebuilds it."""
        self._cache.pop((str(student_id), str(course_id)), None)
