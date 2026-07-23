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

Single-report limit: the current TeachingAgent runtime is bound to one
(student, course) report. If the store holds multiple reports, the first
sorted pair is injected and a warning is logged; multi-report session routing
is a follow-up (see TODO).
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.feature_flags import TEACHING_AGENT_MODES
from app.platform.agents.composition import build_kg_mest_shadow_sidecar_runtime
from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.tools.integration import (
    CallableLearningEventPort,
    CallableRecommendationPort,
    UnavailableSandboxPort,
)
from app.platform.agents.tools.kg_mest_shadow import KGMetShadowReportStudentModelingPort
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
        if len(reports) > 1:
            logger.warning(
                "TeachingAgent store has %d reports; injecting the first (%s). Multi-report routing is not yet supported.",
                len(reports), reports[0],
            )
        student_id, course_id = reports[0]
        report = store.read(student_id, course_id)
        if report is None:
            logger.warning("TeachingAgent report vanished between list and read; endpoint stays 503.")
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
            "TeachingAgent runtime injected for student=%s course=%s; /api/v1/teaching-agent/respond is live.",
            student_id, course_id,
        )
        return True
    except Exception as error:  # noqa: BLE001 -- bootstrap must never block startup
        logger.warning("TeachingAgent bootstrap failed (endpoint stays 503): %s: %s", type(error).__name__, error)
        return False
