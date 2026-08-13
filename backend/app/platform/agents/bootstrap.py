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

from sqlmodel import Session

from app.core.config import settings
from app.core.feature_flags import TEACHING_AGENT_MODES
from app.models.database import engine
from app.platform.agents.kg_mest_report_store import KGMestShadowReportStore
from app.platform.agents.platform import LegacyAgentPlatform
from app.platform.agents.registry import TeachingAgentRuntimeRegistry
from app.platform.agents.runtime.profile import AgentType
from app.platform.agents.tools.coding import (
    make_session_scoped_code_submission_port,
    make_session_scoped_coding_ports,
)
from app.platform.agents.tools.cognition import make_session_scoped_cognition_port
from app.platform.agents.tools.conversation_context import (
    make_session_scoped_conversation_context_port,
)
from app.platform.agents.tools.experiment import (
    make_session_scoped_experiment_dispatch_port,
    make_session_scoped_experiment_port,
)
from app.platform.agents.tools.integration import Judge0SandboxPort
from app.platform.agents.tools.learning_event import (
    make_session_scoped_learning_event_port,
)
from app.platform.agents.tools.openai_compatible import OpenAICompatibleTeachingLLM
from app.platform.agents.tools.question_bank import (
    make_session_scoped_question_bank_port,
)
from app.platform.agents.tools.question_generation import (
    make_session_scoped_question_generation_port,
)
from app.platform.agents.tools.recommendation import (
    make_session_scoped_recommendation_port,
)
from app.platform.agents.tools.teacher_safety_valve import (
    make_session_scoped_teacher_safety_valve_port,
)
from app.platform.agents.tools.tool_governance import (
    make_session_scoped_tool_governance_port,
)
from app.platform.agents.tools.visualization import (
    make_session_scoped_visualization_port,
)
from app.platform.agents.tools.web_research import make_session_scoped_web_research_port
from app.platform.agents.providers.governance.teaching_constraints import (
    make_session_scoped_teaching_constraint_port,
)
from app.platform.agents.providers.teaching.conversation_history import (
    make_session_scoped_conversation_history_port,
)
from app.platform.agents.providers.teaching.learning_adjustment import (
    make_session_scoped_learning_adjustment_port,
)
from app.platform.retrieval_demo.service import DemoService

logger = logging.getLogger(__name__)


def bootstrap_coding_agent(app: Any) -> bool:
    """Register CodingAgent independently of TeachingAgent and its LLM gate.

    Coding feedback is useful whenever the server can read a formal run.  Its
    deterministic diagnosis fallback therefore must not disappear because the
    conversational TeachingAgent is disabled or its LLM is unavailable.
    """
    try:
        from .coding.composition import build_coding_graph_factory
        from .coding.profile import build_coding_profile

        platform = getattr(app.state, "agent_platform", None)
        if platform is None:
            platform = LegacyAgentPlatform()
        session_factory = lambda: Session(engine)
        coding_diagnosis, _ = make_session_scoped_coding_ports(session_factory)
        code_submission = make_session_scoped_code_submission_port(session_factory)

        sandbox_port = getattr(app.state, "coding_agent_sandbox_port", None)
        if sandbox_port is None:
            sandbox_port = Judge0SandboxPort(session_factory=session_factory)
            app.state.coding_agent_sandbox_port = sandbox_port
        app.state.coding_agent_diagnosis_port = coding_diagnosis
        app.state.coding_agent_code_submission_port = code_submission

        llm = None
        base_url = (getattr(settings, "LLM_API_BASE", "") or "").strip()
        api_key = (getattr(settings, "LLM_API_KEY", "") or "").strip()
        model = (getattr(settings, "LLM_MODEL_NAME", "") or "").strip()
        if base_url and api_key and model:
            llm = OpenAICompatibleTeachingLLM(
                base_url=base_url,
                api_key=api_key,
                model=model,
            )

        platform.register_generic(
            profile=build_coding_profile(),
            builder=build_coding_graph_factory(
                sandbox=sandbox_port,
                coding_diagnosis=coding_diagnosis,
                code_submission=code_submission,
                llm=llm,
            ),
        )
        app.state.agent_platform = platform
        logger.info(
            "AgentPlatform: registered CodingAgent (llm=%s, sandbox_healthy=%s).",
            "configured" if llm is not None else "rule_fallback",
            getattr(sandbox_port, "is_healthy", False),
        )
        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning("CodingAgent bootstrap failed: %s: %s", type(error).__name__, error)
        return False


def bootstrap_research_agent(app: Any) -> bool:
    """Register the persisted ResearchAgent Harness without bootstrap I/O.

    arXiv, the configured embedding backend and the optional structured LLM are
    all lazy: no external call or local model load happens during application
    startup.  Missing embeddings degrade memory retrieval to keywords; missing
    LLM routing degrades to the deterministic allowlisted selector.
    """
    try:
        from app.platform.knowledge.embedding import embedding_provider_from_settings

        from .providers.llm.structured import SharedLLMStructuredProvider
        from .providers.persistence import (
            SqlAgentLLMDiagnosticStore,
            SqlAgentRunEventPort,
        )
        from .providers.research.access import CourseAccessResearchScopePort
        from .providers.research.paper_search import ArxivPaperSearchProvider
        from .providers.research.workspace import (
            LazyEmbeddingProvider,
            SqlResearchWorkspaceProvider,
        )
        from .research.composition import build_research_graph_factory
        from .research.profile import build_research_profile

        platform = getattr(app.state, "agent_platform", None)
        if platform is None:
            platform = LegacyAgentPlatform()
        paper_search = ArxivPaperSearchProvider()
        session_factory = lambda: Session(engine)
        # Research runs use the existing minimal append-only event domain.
        # Node logs remain sanitized, and full prompts/model output are never
        # included in event payloads.
        platform.set_event_port(SqlAgentRunEventPort(session_factory))
        scope_access = CourseAccessResearchScopePort(session_factory)
        embedding_provider = None
        embedding_provider_name = settings.GRAPHRAG_EMBEDDING_PROVIDER.strip()
        embedding_model_name = settings.GRAPHRAG_EMBEDDING_MODEL.strip()
        embedding_configured = bool(
            embedding_provider_name
            and embedding_model_name
            and (
                settings.GRAPHRAG_EMBEDDING_LOCAL_PATH.strip()
                if embedding_provider_name.lower() in {"local_bge", "bge-local", "local"}
                else settings.GRAPHRAG_EMBEDDING_API_BASE.strip()
                and settings.GRAPHRAG_EMBEDDING_API_KEY.strip()
            )
        )
        if embedding_configured:
            embedding_provider = LazyEmbeddingProvider(
                factory=embedding_provider_from_settings,
                provider_name=embedding_provider_name,
                model_name=embedding_model_name,
            )
        workspace = SqlResearchWorkspaceProvider(
            session_factory=session_factory,
            embedding_provider=embedding_provider,
        )
        structured_llm = None
        if (
            settings.LLM_API_BASE.strip()
            and settings.LLM_API_KEY.strip()
            and settings.LLM_MODEL_NAME.strip()
        ):
            structured_llm = SharedLLMStructuredProvider(
                diagnostic_sink=SqlAgentLLMDiagnosticStore(session_factory),
            )
        platform.register_generic(
            profile=build_research_profile(),
            builder=build_research_graph_factory(
                scope_access=scope_access,
                paper_search=paper_search,
                workspace=workspace,
                structured_llm=structured_llm,
            ),
        )
        app.state.agent_platform = platform
        app.state.research_paper_search_provider = paper_search
        app.state.research_workspace_provider = workspace
        app.state.research_memory_embedding_configured = embedding_configured
        logger.info(
            "AgentPlatform: registered ResearchAgent Harness (embedding=%s, llm_router=%s).",
            "configured" if embedding_configured else "keyword_degraded",
            "configured" if structured_llm is not None else "deterministic",
        )
        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning("ResearchAgent bootstrap failed: %s: %s", type(error).__name__, error)
        return False


def bootstrap_prep_agent(app: Any) -> bool:
    """Register Prep runtimes and inject the shared structured LLM adapter.

    Prep is a teacher-side capability and must not disappear when the
    student-facing TeachingAgent feature flag is disabled.
    """
    try:
        base_url = (settings.LLM_API_BASE or "").strip()
        api_key = (settings.LLM_API_KEY or "").strip()
        model = (settings.LLM_MODEL_NAME or "").strip()
        if not base_url or not api_key or not model:
            logger.info("PrepAgent LLM is not configured; batch/agent endpoints remain unavailable.")
            return False

        from app.services.controlled_prep_workflow import (
            ControlledPrepWorkflow,
            controlled_prep_workflow,
        )
        from app.services.course_prep_agent_service import (
            CoursePrepAgentService,
            course_prep_agent_service,
        )
        from app.services.ppt_mapping_optimization_service import (
            PptMappingOptimizationService,
            ppt_mapping_optimization_service,
        )

        from .gateway import AgentGateway
        from .platform import LegacyAgentPlatform
        from .prep.llm_adapter import PrepLLMAdapter
        from .providers.llm.structured import SharedLLMStructuredProvider
        from .providers.retrieval.active_bundle import ActiveBundleCourseRetrievalPort

        session_factory = lambda: Session(engine)
        from .providers.persistence import SqlAgentLLMDiagnosticStore
        structured_llm = SharedLLMStructuredProvider(
            diagnostic_sink=SqlAgentLLMDiagnosticStore(session_factory),
        )
        prep_llm = PrepLLMAdapter(structured_llm=structured_llm)
        prep_retrieval = ActiveBundleCourseRetrievalPort()
        course_prep_agent_service._llm = prep_llm
        course_prep_agent_service._course_retrieval = prep_retrieval
        ppt_mapping_optimization_service._llm = prep_llm
        workflow = ControlledPrepWorkflow(client=prep_llm)
        # The durable first-build handler uses the service singleton directly.
        # Point its default workflow at the same registered port adapter.
        controlled_prep_workflow.client = prep_llm

        platform = getattr(app.state, "agent_platform", None)
        if platform is None:
            platform = LegacyAgentPlatform()
        _register_prep_pipeline_definitions(
            platform=platform,
            session_factory=session_factory,
            structured_llm=structured_llm,
            incremental_service=CoursePrepAgentService(
                llm=prep_llm,
                course_retrieval=prep_retrieval,
            ),
            initial_workflow=workflow,
            ppt_service=PptMappingOptimizationService(llm=prep_llm),
        )
        # _register_prep_pipeline_definitions owns the durable ports shared by
        # the Prep runtimes; wire the same store into the gateway for lifecycle
        # status and diagnostic lookup.
        from .providers.persistence import SqlAgentRunStorePort
        platform.set_gateway(AgentGateway(
            registry=platform.runtime_registry,
            event_port=platform.event_port,
            run_store=SqlAgentRunStorePort(session_factory),
        ))
        app.state.agent_platform = platform
        # The durable course-build worker is already the queue boundary for
        # Initial Prep, so it invokes the registered runtime directly.
        from app.platform.tasks.worker import local_task_worker
        local_task_worker.set_agent_platform(platform)
        logger.info("PrepAgent registered independently of TeachingAgent feature flags.")
        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning(
            "PrepAgent bootstrap failed: %s: %s",
            type(error).__name__,
            error,
        )
        return False


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
        # CodingAgent owns its independent startup gate. Reuse its immutable
        # read-only sandbox port when already registered; direct TeachingAgent
        # bootstrap remains backward-compatible for tests and legacy callers.
        sandbox_port = getattr(app.state, "coding_agent_sandbox_port", None)
        if sandbox_port is None:
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
            question_generation=make_session_scoped_question_generation_port(session_factory),
            web_research=make_session_scoped_web_research_port(session_factory),
            # 阶段9：工具治理、教师安全阀、实验与可视化只读端口
            tool_governance=make_session_scoped_tool_governance_port(session_factory),
            teacher_safety_valve=make_session_scoped_teacher_safety_valve_port(session_factory),
            experiment=make_session_scoped_experiment_port(session_factory),
            experiment_dispatch=make_session_scoped_experiment_dispatch_port(session_factory),
            visualization=make_session_scoped_visualization_port(session_factory),
            coding_diagnosis=coding_diagnosis,
            student_history=student_history,
            teaching_constraints=make_session_scoped_teaching_constraint_port(
                session_factory
            ),
            conversation_history=make_session_scoped_conversation_history_port(
                session_factory
            ),
            learning_adjustment=make_session_scoped_learning_adjustment_port(
                session_factory
            ),
        )
        app.state.teaching_agent_runtime_registry = registry

        # Commit 5: register EDU agent with the unified AgentPlatform.
        # The platform wraps the legacy registry; existing endpoints are unaffected.
        # Phase 1 fix: use LegacyAgentPlatform to mark that core infrastructure
        # (Gateway, ProviderContainer) is NOT yet wired. Formal AgentPlatform
        # will require these once Phase 3 completes EDU migration.
        platform = getattr(app.state, "agent_platform", None)
        if platform is None:
            platform = LegacyAgentPlatform()
        platform.register_legacy(
            AgentType.EDU,
            resolver=registry.get_or_create,
        )

        app.state.agent_platform = platform
        logger.info("TeachingAgent registry injected; AgentPlatform registered EDU agent.")

        return True
    except Exception as error:  # noqa: BLE001 - never block app startup
        logger.warning("TeachingAgent bootstrap failed (endpoint stays 503): %s: %s", type(error).__name__, error)
        return False


def _register_prep_pipeline_definitions(
    *,
    platform: Any,
    session_factory: Any,
    structured_llm: Any | None = None,
    incremental_service: Any | None = None,
    initial_workflow: Any | None = None,
    ppt_service: Any | None = None,
) -> None:
    """Register Prep Initial, Incremental and PPT-mapping pipelines in the runtime registry.

    The three pipelines share ``AgentType.PREP`` but are distinct workflows,
    registered via the definition-keyed ``AgentRuntimeRegistry`` so the
    ``AgentGateway`` can route to them via ``extras["graph_kind"]``
    (``PrepGraphKind.INITIAL`` / ``INCREMENTAL`` / ``PPT_MAPPING``).
    """
    from .prep.common.dependencies import CommonPrepDependencies
    from .prep.enums import PrepGraphKind
    from .prep.incremental.composition import build_incremental_graph_factory
    from .prep.incremental.dependencies import IncrementalPrepDependencies
    from .prep.incremental.profile import build_incremental_profile
    from .prep.initial.composition import build_initial_graph_factory
    from .prep.initial.dependencies import InitialPrepDependencies
    from .prep.initial.profile import build_initial_profile
    from .prep.ppt_mapping.composition import build_ppt_mapping_graph_factory
    from .prep.ppt_mapping.dependencies import PptMappingDependencies
    from .prep.ppt_mapping.profile import build_ppt_mapping_profile
    from .providers.llm.structured import SharedLLMStructuredProvider
    from .providers.persistence import (
        SqlAgentLLMDiagnosticStore,
        SqlAgentRunEventPort,
        SqlAgentRunStorePort,
    )
    from .providers.prep.incremental_prep import IncrementalPrepProvider
    from .providers.prep.initial_course_prep import InitialCoursePrepProvider
    from .providers.prep.ppt_mapping_optimization import PptMappingOptimizationProvider
    from .runtime.registry import AgentDefinitionKey

    event_port = SqlAgentRunEventPort(session_factory)
    run_store = SqlAgentRunStorePort(session_factory)
    diagnostic_sink = SqlAgentLLMDiagnosticStore(session_factory)
    structured_llm = structured_llm or SharedLLMStructuredProvider(diagnostic_sink=diagnostic_sink)

    common_deps = CommonPrepDependencies(
        structured_llm=structured_llm,
        run_store=run_store,
        event_port=event_port,
    )

    # --- Initial pipeline ---
    initial_provider = InitialCoursePrepProvider(
        session_factory=session_factory,
        workflow=initial_workflow,
    )
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
    incremental_provider = IncrementalPrepProvider(
        session_factory=session_factory,
        service=incremental_service,
    )
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
    ppt_provider = PptMappingOptimizationProvider(
        session_factory=session_factory,
        service=ppt_service,
    )
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
