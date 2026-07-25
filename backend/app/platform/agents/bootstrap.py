"""Startup auto-injection of the TeachingAgent runtime.

Opt-in: the runtime is injected only when ``TEACHING_AGENT_MODE == "enabled"``
AND an approved KG-MEST Shadow report is present in the report store AND a
course-scoped retrieval/ KG/ scope provider (the isolated R2 ``DemoService``)
is available AND the LLM adapter is configurable. Otherwise the
``/api/v1/teaching-agent/respond`` endpoint stays 503 (``TEACHING_AGENT_NOT_CONFIGURED``).

Hard constraints:
- No V1 DB writes, no auto LLM calls at startup (the LLM port is only invoked
  when ``/respond`` is actually called).
- No fabricated reports: a missing report -> no injection -> 503.
- Any bootstrap error is caught and logged; the app still starts with the
  endpoint at 503. Bootstrap never blocks startup.

批次4：注入一个 ``TeachingAgentRuntimeRegistry``，按 (student_id, course_id)
动态构建/缓存运行时。为兼容旧测试，仍把首份报告对应的运行时写入
``app.state.teaching_agent_runtime`` 和 ``app.state.teaching_agent_scope``，
但端点优先使用 ``teaching_agent_runtime_registry`` 进行多报告路由。
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.feature_flags import TEACHING_AGENT_MODES
from app.platform.agents.composition import build_kg_mest_shadow_sidecar_runtime
from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.tools.integration import (
    CallableLearningEventPort,
    CallableRecommendationPort,
    UnavailableSandboxPort,
)
from app.platform.agents.tools.openai_compatible import OpenAICompatibleTeachingLLM
from app.platform.retrieval_demo.service import DemoService

logger = logging.getLogger(__name__)


def _noop_event(*_: Any, **__: Any) -> None:  # pragma: no cover - trivial
    return None


async def _noop_event_async(*_: Any, **__: Any) -> None:  # pragma: no cover - trivial
    return None


async def _empty_recommendation(**kwargs: Any) -> dict[str, Any]:
    return {"resource_ids": [], "reason": "teaching_agent_recommendation_not_configured"}


def bootstrap_teaching_agent(app: Any, *, demo_service: DemoService | None = None) -> bool:
    """Inject the TeachingAgent runtime into ``app.state`` when all gates pass.

    Returns True when the runtime was injected (endpoint goes live), False
    otherwise (endpoint stays 503). Never raises.
    """
    try:
        mode = getattr(settings, "TEACHING_AGENT_MODE", "disabled")
        if mode not in TEACHING_AGENT_MODES or mode != "enabled":
            logger.info("TeachingAgent disabled (TEACHING_AGENT_MODE=%r); endpoint stays 503.", mode)
            return False

        store = KGMestShadowReportStore()
        reports = store.list_reports()
        if not reports:
            logger.info("TeachingAgent enabled but no KG-MEST Shadow report in store; endpoint stays 503.")
            return False

        # Course-scoped retrieval / KG / scope come from the isolated R2
        # DemoService (the same one the retrieval-demo endpoint uses).
        service = demo_service or DemoService(
            configured_mode=settings.DEMO_RETRIEVAL_MODE,
            environment=settings.DEMO_RETRIEVAL_ENVIRONMENT,
        )

        # LLM adapter: only when configured. No config -> no injection (no
        # silent paid calls with empty credentials).
        base_url = (settings.LLM_API_BASE or "").strip()
        api_key = (settings.LLM_API_KEY or "").strip()
        model = (settings.LLM_MODEL_NAME or "").strip()
        if not base_url or not api_key or not model:
            logger.info(
                "TeachingAgent enabled but LLM not configured (LLM_API_BASE/LLM_API_KEY/LLM_MODEL_NAME); endpoint stays 503."
            )
            return False
        llm = OpenAICompatibleTeachingLLM(base_url=base_url, api_key=api_key, model=model)

        # 批次4：注入 registry，按 (student_id, course_id) 动态构建运行时。
        # 多报告场景下，每个 (student, course) 报告对应一个独立运行时；
        # 无报告的请求 fail-closed 返回 None，端点保持 503。
        registry = TeachingAgentRuntimeRegistry(
            demo_service=service,
            llm=llm,
            recommendation=CallableRecommendationPort(_empty_recommendation),
            sandbox=UnavailableSandboxPort(),
            learning_events=CallableLearningEventPort(_noop_event_async, _noop_event_async),
            store=store,
        )
        app.state.teaching_agent_runtime_registry = registry

        # 兼容旧测试/旧端点：仍注入首个报告对应的运行时和 scope。
        # 端点优先使用 registry；若 registry 缺失则回退到该单运行时。
        student_id, course_id = reports[0]
        report = store.read(student_id, course_id)
        if report is None:
            logger.warning("TeachingAgent report vanished between list and read; endpoint stays 503.")
            return False
        runtime = build_kg_mest_shadow_sidecar_runtime(
            demo_service=service,
            shadow_report=report,
            expected_student_id=student_id,
            expected_course_id=course_id,
            recommendation=CallableRecommendationPort(_empty_recommendation),
            sandbox=UnavailableSandboxPort(),
            learning_events=CallableLearningEventPort(_noop_event_async, _noop_event_async),
            llm=llm,
        )
        app.state.teaching_agent_runtime = runtime
        app.state.teaching_agent_scope = {"student_id": student_id, "course_id": course_id}
        logger.info(
            "TeachingAgent registry injected with %d report(s); first scope student=%s course=%s; /api/v1/teaching-agent/respond is live.",
            len(reports), student_id, course_id,
        )
        return True
    except Exception as error:  # noqa: BLE001 -- bootstrap must never block startup
        logger.warning("TeachingAgent bootstrap failed (endpoint stays 503): %s: %s", type(error).__name__, error)
        return False
