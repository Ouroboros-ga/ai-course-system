"""Opt-in TeachingAgent registry bootstrap.

The Agent needs an enabled mode and a configured LLM.  KG-MEST reports and R2
course sidecars are optional enrichments: a missing report or unparsed course
must never make ordinary course Q&A unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.feature_flags import TEACHING_AGENT_MODES
from app.models.database import engine
from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.tools.cognition import make_session_scoped_cognition_port
from app.platform.agents.tools.conversation_context import make_session_scoped_conversation_context_port
from app.platform.agents.tools.experiment import make_session_scoped_experiment_port
from app.platform.agents.tools.integration import UnavailableSandboxPort
from app.platform.agents.tools.learning_event import make_session_scoped_learning_event_port
from app.platform.agents.tools.openai_compatible import OpenAICompatibleTeachingLLM
from app.platform.agents.tools.question_bank import make_session_scoped_question_bank_port
from app.platform.agents.tools.recommendation import make_session_scoped_recommendation_port
from app.platform.agents.tools.teacher_safety_valve import make_session_scoped_teacher_safety_valve_port
from app.platform.agents.tools.tool_governance import make_session_scoped_tool_governance_port
from app.platform.agents.tools.visualization import make_session_scoped_visualization_port
from app.platform.agents.tools.web_research import make_session_scoped_web_research_port
from app.platform.retrieval_demo.service import DemoService
from sqlmodel import Session

logger = logging.getLogger(__name__)


def bootstrap_teaching_agent(app: Any, *, demo_service: DemoService | None = None) -> bool:
    """Inject a request-scoped runtime registry without blocking application startup."""
    try:
        mode = getattr(settings, "TEACHING_AGENT_MODE", "disabled")
        if mode not in TEACHING_AGENT_MODES or mode != "enabled":
            logger.info("TeachingAgent disabled (TEACHING_AGENT_MODE=%r); endpoint stays 503.", mode)
            return False

        base_url = (settings.LLM_API_BASE or "").strip()
        api_key = (settings.LLM_API_KEY or "").strip()
        model = (settings.LLM_MODEL_NAME or "").strip()
        if not base_url or not api_key or not model:
            logger.info("TeachingAgent enabled but LLM is not configured; endpoint stays 503.")
            return False

        service = demo_service or DemoService(
            configured_mode=settings.DEMO_RETRIEVAL_MODE,
            environment=settings.DEMO_RETRIEVAL_ENVIRONMENT,
        )
        session_factory = lambda: Session(engine)
        registry = TeachingAgentRuntimeRegistry(
            demo_service=service,
            llm=OpenAICompatibleTeachingLLM(base_url=base_url, api_key=api_key, model=model),
            recommendation=make_session_scoped_recommendation_port(session_factory),
            sandbox=UnavailableSandboxPort(),
            learning_events=make_session_scoped_learning_event_port(session_factory),
            conversation_context=make_session_scoped_conversation_context_port(session_factory),
            store=KGMestShadowReportStore(),
            cognition=make_session_scoped_cognition_port(session_factory),
            question_bank=make_session_scoped_question_bank_port(session_factory),
            web_research=make_session_scoped_web_research_port(session_factory),
            # 阶段9：工具治理、教师安全阀、实验与可视化只读端口
            tool_governance=make_session_scoped_tool_governance_port(session_factory),
            teacher_safety_valve=make_session_scoped_teacher_safety_valve_port(session_factory),
            experiment=make_session_scoped_experiment_port(session_factory),
            visualization=make_session_scoped_visualization_port(session_factory),
        )
        app.state.teaching_agent_runtime_registry = registry
        logger.info("TeachingAgent registry injected; KG-MEST reports and course sidecars are optional enhancements.")
        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning("TeachingAgent bootstrap failed (endpoint stays 503): %s: %s", type(error).__name__, error)
        return False
