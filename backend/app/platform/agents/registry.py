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
import time
from collections import OrderedDict
from typing import Any, Optional

from .composition import build_course_sidecar_runtime, build_kg_mest_shadow_sidecar_runtime
from .contracts import (
    CognitionPort,
    CodingDiagnosisPort,
    ConversationContextPort,
    ExperimentPort,
    LearningEventPort,
    QuestionBankPort,
    RecommendationPort,
    SandboxPort,
    StudentHistoryPort,
    TeacherSafetyValvePort,
    TeachingLLMPort,
    ToolGovernancePort,
    VisualizationPort,
    WebResearchPort,
)
from .kg_mest_report_store import KGMestShadowReportStore
from .runtime import TeachingAgentRuntime
from .tools.cognition_student_modeling import CognitionStudentModelingPort, UnknownStudentModelingPort

logger = logging.getLogger(__name__)

# P1-E3: 缓存容量与 TTL 上限，避免 runtime 缓存无界增长。
# 使用 LRU（OrderedDict）+ TTL（monotonic 时间戳）双重淘汰。
MAX_CACHE_SIZE = 256
CACHE_TTL_SECONDS = 1800  # 30 分钟


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
        conversation_context: Optional[ConversationContextPort] = None,
        tool_governance: Optional[ToolGovernancePort] = None,
        teacher_safety_valve: Optional[TeacherSafetyValvePort] = None,
        experiment: Optional[ExperimentPort] = None,
        visualization: Optional[VisualizationPort] = None,
        coding_diagnosis: Optional[CodingDiagnosisPort] = None,
        student_history: Optional[StudentHistoryPort] = None,
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
        self._conversation_context = conversation_context
        self._tool_governance = tool_governance
        self._teacher_safety_valve = teacher_safety_valve
        self._experiment = experiment
        self._visualization = visualization
        self._coding_diagnosis = coding_diagnosis
        self._student_history = student_history
        # P1-E3: OrderedDict 实现 LRU；值为 (runtime, created_at_monotonic) 元组以支持 TTL 淘汰。
        self._cache: "OrderedDict[tuple[str, str], tuple[TeachingAgentRuntime, float]]" = OrderedDict()

    def get_or_create(
        self,
        student_id: str,
        course_id: str,
    ) -> Optional[TeachingAgentRuntime]:
        """Build for every valid scope; an optional report only enriches it."""
        key = (str(student_id), str(course_id))
        cached = self._cache.get(key)
        if cached is not None:
            runtime, created_at = cached
            # P1-E3: TTL 过期则剔除并重建；未过期则 LRU 标记为最近使用。
            if (time.monotonic() - created_at) < CACHE_TTL_SECONDS:
                self._cache.move_to_end(key)
                return runtime
            self._cache.pop(key, None)
        report = None
        try:
            report = self._store.read(key[0], key[1])
        except Exception as error:  # noqa: BLE001 -- report is optional, do not block Q&A
            logger.warning(
                "TeachingAgent registry: optional report read failed for student=%s course=%s: %s: %s",
                key[0], key[1], type(error).__name__, error,
            )
        try:
            if report is not None:
                try:
                    runtime = build_kg_mest_shadow_sidecar_runtime(
                        demo_service=self._demo_service, shadow_report=report, expected_student_id=key[0], expected_course_id=key[1],
                        recommendation=self._recommendation, sandbox=self._sandbox, learning_events=self._learning_events, llm=self._llm,
                        web_research=self._web_research, cognition=self._cognition, question_bank=self._question_bank,
                        conversation_context=self._conversation_context,
                        tool_governance=self._tool_governance, teacher_safety_valve=self._teacher_safety_valve,
                        experiment=self._experiment, visualization=self._visualization,
                        coding_diagnosis=self._coding_diagnosis, student_history=self._student_history,
                    )
                except (TypeError, ValueError) as error:
                    # A stale/malformed optional report must not deny normal Q&A.
                    logger.warning("TeachingAgent registry: ignored optional report for student=%s course=%s: %s", key[0], key[1], error)
                    report = None
            if report is None and self._cognition is not None:
                runtime = build_course_sidecar_runtime(
                    demo_service=self._demo_service, student_modeling=CognitionStudentModelingPort(self._cognition),
                    recommendation=self._recommendation, sandbox=self._sandbox, learning_events=self._learning_events, llm=self._llm,
                    web_research=self._web_research, cognition=self._cognition, question_bank=self._question_bank,
                    conversation_context=self._conversation_context,
                    tool_governance=self._tool_governance, teacher_safety_valve=self._teacher_safety_valve,
                    experiment=self._experiment, visualization=self._visualization,
                    coding_diagnosis=self._coding_diagnosis, student_history=self._student_history,
                )
            elif report is None:
                runtime = build_course_sidecar_runtime(
                    demo_service=self._demo_service, student_modeling=UnknownStudentModelingPort(),
                    recommendation=self._recommendation, sandbox=self._sandbox, learning_events=self._learning_events, llm=self._llm,
                    web_research=self._web_research, cognition=None, question_bank=self._question_bank,
                    conversation_context=self._conversation_context,
                    tool_governance=self._tool_governance, teacher_safety_valve=self._teacher_safety_valve,
                    experiment=self._experiment, visualization=self._visualization,
                    coding_diagnosis=self._coding_diagnosis, student_history=self._student_history,
                )
        except Exception as error:  # noqa: BLE001 -- fail-closed: never raise
            logger.warning(
                "TeachingAgent registry: runtime build failed for student=%s course=%s: %s: %s",
                key[0], key[1], type(error).__name__, error,
            )
            return None
        # P1-E3: 写入 (runtime, created_at)；超过容量时按 LRU 淘汰最久未用的条目。
        self._cache[key] = (runtime, time.monotonic())
        if len(self._cache) > MAX_CACHE_SIZE:
            self._cache.popitem(last=False)
        return runtime

    def list_cached_scopes(self) -> list[tuple[str, str]]:
        """Return the (student_id, course_id) pairs currently cached."""
        return list(self._cache.keys())

    def invalidate(self, student_id: str, course_id: str) -> None:
        """Drop a cached runtime so the next request rebuilds it."""
        self._cache.pop((str(student_id), str(course_id)), None)
