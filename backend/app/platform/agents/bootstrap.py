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
from app.platform.agents.platform import LegacyAgentPlatform
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
        # Phase 1 fix: use LegacyAgentPlatform to mark that core infrastructure
        # (Gateway, ProviderContainer) is NOT yet wired. Formal AgentPlatform
        # will require these once Phase 3 completes EDU migration.
        platform = LegacyAgentPlatform()
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
            logger.info("AgentPlatform: registered Prep agent (Incremental pipeline).")
        except Exception as prep_error:  # noqa: BLE001 - never block app startup
            logger.warning("AgentPlatform: Prep agent registration failed: %s: %s", type(prep_error).__name__, prep_error)

        # Phase 4: register Prep Initial and PPT-mapping pipelines via the
        # definition-keyed AgentRuntimeRegistry. These share AgentType.PREP
        # with the Incremental pipeline above but are distinct workflows
        # routed via extras["graph_kind"] by the future AgentGateway.
        # The Incremental pipeline registered via register_generic remains
        # the platform's default for AgentType.PREP.
        try:
            _register_prep_pipeline_definitions(
                platform=platform,
                session_factory=session_factory,
            )
        except Exception as pipeline_error:  # noqa: BLE001 - never block app startup
            logger.warning(
                "AgentPlatform: Prep pipeline definition registration failed: %s: %s",
                type(pipeline_error).__name__, pipeline_error,
            )

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


def _register_prep_pipeline_definitions(
    *,
    platform: Any,
    session_factory: Any,
) -> None:
    """Register Prep Initial and PPT-mapping pipelines in the runtime registry.

    These pipelines share ``AgentType.PREP`` with the Incremental pipeline
    (registered via ``register_generic`` above) but are distinct workflows.
    They are registered via the definition-keyed ``AgentRuntimeRegistry``
    so the future ``AgentGateway`` can route to them via
    ``extras["graph_kind"]``.

    The Incremental pipeline is also registered here (using the new
    ``prep/incremental/`` subpackage) so all three share a consistent
    registration path for the gateway.
    """
    from .prep.common.dependencies import CommonPrepDependencies
    from .prep.enums import PrepGraphKind
    from .prep.initial.composition import build_initial_graph_factory
    from .prep.initial.dependencies import InitialPrepDependencies
    from .prep.initial.profile import build_initial_profile
    from .prep.incremental.composition import build_incremental_graph_factory
    from .prep.incremental.dependencies import IncrementalPrepDependencies
    from .prep.incremental.profile import build_incremental_profile
    from .prep.ppt_mapping.composition import build_ppt_mapping_graph_factory
    from .prep.ppt_mapping.dependencies import PptMappingDependencies
    from .prep.ppt_mapping.profile import build_ppt_mapping_profile
    from .providers.llm.structured import SharedLLMStructuredProvider
    from .providers.prep.initial_course_prep import InitialCoursePrepProvider
    from .providers.prep.incremental_prep import IncrementalPrepProvider
    from .providers.prep.ppt_mapping_optimization import PptMappingOptimizationProvider
    from .runtime.dispatcher import BaseAgentRuntime
    from .runtime.events import NullAgentRunEventPort, NullAgentRunStorePort
    from .runtime.registry import AgentDefinitionKey

    event_port = NullAgentRunEventPort()
    run_store = NullAgentRunStorePort()
    structured_llm = SharedLLMStructuredProvider()

    common_deps = CommonPrepDependencies(
        structured_llm=structured_llm,
        run_store=run_store,
        event_port=event_port,
    )

    # --- Initial pipeline ---
    initial_provider = InitialCoursePrepProvider(session_factory=session_factory)
    initial_deps = InitialPrepDependencies(common=common_deps, initial_prep=initial_provider)
    initial_profile = build_initial_profile()
    _register_pipeline_factory(
        platform=platform,
        key=AgentDefinitionKey(
            agent_type=AgentType.PREP.value,
            agent_version=PrepGraphKind.INITIAL.value,
        ),
        profile=initial_profile,
        builder=build_initial_graph_factory(initial_deps),
        event_port=event_port,
    )

    # --- Incremental pipeline (new subpackage version) ---
    incremental_provider = IncrementalPrepProvider(session_factory=session_factory)
    incremental_deps = IncrementalPrepDependencies(
        common=common_deps, incremental_prep=incremental_provider,
    )
    incremental_profile = build_incremental_profile()
    _register_pipeline_factory(
        platform=platform,
        key=AgentDefinitionKey(
            agent_type=AgentType.PREP.value,
            agent_version=PrepGraphKind.INCREMENTAL.value,
        ),
        profile=incremental_profile,
        builder=build_incremental_graph_factory(incremental_deps),
        event_port=event_port,
    )

    # --- PPT mapping pipeline ---
    ppt_provider = PptMappingOptimizationProvider(session_factory=session_factory)
    ppt_deps = PptMappingDependencies(common=common_deps, ppt_mapping=ppt_provider)
    ppt_profile = build_ppt_mapping_profile()
    _register_pipeline_factory(
        platform=platform,
        key=AgentDefinitionKey(
            agent_type=AgentType.PREP.value,
            agent_version=PrepGraphKind.PPT_MAPPING.value,
        ),
        profile=ppt_profile,
        builder=build_ppt_mapping_graph_factory(ppt_deps),
        event_port=event_port,
    )

    logger.info(
        "AgentPlatform: registered 3 Prep pipeline definitions "
        "(initial, incremental, ppt_mapping) in AgentRuntimeRegistry."
    )


def _register_pipeline_factory(
    *,
    platform: Any,
    key: Any,
    profile: Any,
    builder: Any,
    event_port: Any,
) -> None:
    """Register a single pipeline factory in the ``AgentRuntimeRegistry``.

    The factory compiles the graph (via ``builder``) and wraps it in a
    ``BaseAgentRuntime`` with the given profile. Compilation is deferred
    to factory call-time (lazy), matching the registry's lazy contract.
    """
    from .runtime.dispatcher import BaseAgentRuntime

    def factory() -> Any:
        graph = builder(())
        if graph is None:
            from .runtime.errors import AgentNotAvailableError
            raise AgentNotAvailableError(
                f"Workflow compilation failed for {key}",
            )
        return BaseAgentRuntime(
            profile=profile,
            graph=graph,
            event_port=event_port,
            timeout_seconds=profile.default_timeout_seconds,
        )

    platform.runtime_registry.register_factory(key, factory)
    logger.info("AgentPlatform: registered pipeline definition %s", key)
