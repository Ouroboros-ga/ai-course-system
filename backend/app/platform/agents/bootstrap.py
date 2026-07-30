"""Opt-in TeachingAgent registry bootstrap.

The Agent needs an enabled mode and a configured LLM.  KG-MEST reports and R2
course sidecars are optional enrichments: a missing report or unparsed course
must never make ordinary course Q&A unavailable.

Commit 5: the bootstrap also registers the EDU agent with the unified
``AgentPlatform`` so that new endpoints can resolve all agent types through
a single entry point. The platform wraps the legacy registry; existing
endpoints that read ``app.state.teaching_agent_runtime_registry`` are
unaffected.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.core.feature_flags import TEACHING_AGENT_MODES
from app.models.database import engine
from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.platform import AgentPlatform
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.runtime.profile import AgentType
from app.platform.agents.tools.cognition import make_session_scoped_cognition_port
from app.platform.agents.tools.coding import make_session_scoped_coding_ports
from app.platform.agents.tools.conversation_context import make_session_scoped_conversation_context_port
from app.platform.agents.tools.experiment import make_session_scoped_experiment_port
from app.platform.agents.tools.integration import Judge0SandboxPort
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
        coding_diagnosis, student_history = make_session_scoped_coding_ports(session_factory)
        # P1-7: 注入真实 Judge0 沙箱 Port；构造时执行 health_check 并缓存结果。
        # 健康检查失败时 Port 仍接受调用，但每次返回 sandbox_unavailable，
        # 保证 Agent/Q&A 主流程在 Judge0 不可用时不中断（降级语义）。
        # 修复：注入 session_factory，使 Port 能按 run_id 从 ExperimentRun 读取已验证结果。
        # Commit 7: 单例共享给 EDU 和 Coding agent，避免重复 health_check。
        sandbox_port = Judge0SandboxPort(session_factory=session_factory)
        registry = TeachingAgentRuntimeRegistry(
            demo_service=service,
            llm=OpenAICompatibleTeachingLLM(base_url=base_url, api_key=api_key, model=model),
            recommendation=make_session_scoped_recommendation_port(session_factory),
            sandbox=sandbox_port,
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
            coding_diagnosis=coding_diagnosis,
            student_history=student_history,
        )
        app.state.teaching_agent_runtime_registry = registry

        # Commit 5: register EDU agent with the unified AgentPlatform.
        # The platform wraps the legacy registry; existing endpoints are unaffected.
        platform = AgentPlatform()
        platform.register_legacy(
            AgentType.EDU,
            resolver=registry.get_or_create,
        )

        # Commit 6: register Prep agent with the unified AgentPlatform.
        # The Prep agent wraps the existing CoursePrepAgentService in a thin
        # LangGraph workflow. evidence_refs hard gate is preserved in the service.
        try:
            from .prep.composition import build_prep_graph_factory
            from .prep.profile import build_prep_profile as _prep_profile
            platform.register_generic(
                profile=_prep_profile(),
                builder=build_prep_graph_factory(session_factory=session_factory),
            )
            logger.info("AgentPlatform: registered Prep agent.")
        except Exception as prep_error:  # noqa: BLE001 - never block app startup
            logger.warning("AgentPlatform: Prep agent registration failed: %s: %s", type(prep_error).__name__, prep_error)

        app.state.agent_platform = platform
        logger.info("TeachingAgent registry injected; AgentPlatform registered EDU agent.")

        # Commit 7: register Coding agent with the unified AgentPlatform.
        # The Coding Agent is a new skeleton with a 3-node workflow:
        # load_sandbox_result → load_coding_diagnosis → generate_diagnosis_response.
        # It reuses the same SandboxPort and CodingDiagnosisPort already wired for EDU.
        # Governance is prompt-level (read-only tools are LOW-risk).
        try:
            from .coding.composition import build_coding_graph_factory
            from .coding.profile import build_coding_profile as _coding_profile
            platform.register_generic(
                profile=_coding_profile(),
                builder=build_coding_graph_factory(
                    sandbox=sandbox_port,
                    coding_diagnosis=coding_diagnosis,
                    llm=OpenAICompatibleTeachingLLM(base_url=base_url, api_key=api_key, model=model),
                ),
            )
            logger.info("AgentPlatform: registered Coding agent.")
        except Exception as coding_error:  # noqa: BLE001 - never block app startup
            logger.warning("AgentPlatform: Coding agent registration failed: %s: %s", type(coding_error).__name__, coding_error)

        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning("TeachingAgent bootstrap failed (endpoint stays 503): %s: %s", type(error).__name__, error)
        return False
