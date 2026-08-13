"""ProviderContainer: process-level dependency assembly.

Transaction model (Mode A — per-method-call sessions):
    The container follows "Mode A" for database access: each provider
    method call opens its own Session internally, uses it, and closes it
    within the call scope. This is simple, concurrency-safe, and matches
    the existing ``make_session_scoped_*_port(session_factory)`` pattern.

    The container does NOT create a Session per Graph Run and inject it
    into all providers (Mode B). Mode B would allow multiple ports to
    share a transaction, but it introduces complex lifecycle and rollback
    semantics that are not justified at this stage.

    Trade-off accepted: a single Graph Run cannot atomically roll back
    across multiple provider calls. This is acceptable because agent
    workflows are designed to be idempotent at the proposal/event level,
    not at the DB-transaction level.

The container holds:
    1. Process-level stateless resources: LLM client, HTTP clients,
       stores, ToolCatalog. These are safe to share across concurrent
       requests.
    2. ``session_factory``: creates call-level DB sessions. The container
       holds the factory, NEVER a live Session.
    3. Session-scoped provider closures: existing
       ``make_session_scoped_*_port(session_factory)`` closures. Each
       closure is process-level shareable; it creates and closes Sessions
       internally per method call (Mode A).

The container does NOT hold:
    1. SQLAlchemy Session instances.
    2. Current student/teacher/course IDs.
    3. Graph State.
    4. Current transactions.

Design rules (per migration design + suggestion #7):
    - The container is process-level and created once at bootstrap.
    - The container does NOT replace existing provider implementations;
      it assembles them into a single access point.
    - ``close()`` releases process-level resources (HTTP clients, etc.).
    - Session-scoped closures manage their own Session lifecycle; the
      container does NOT close Sessions (they are created and closed
      per method call inside each closure).

Backward compatibility:
    The container is optional. Existing bootstrap code that constructs
    providers individually continues to work. The container is the
    preferred assembly point for new code (Gateway, BaseAgentRuntime).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderContainer:
    """Process-level container for stateless providers and session factory.

    Fields are intentionally optional with ``None`` defaults so the
    container can be built incrementally. Agents that don't need a
    particular provider leave it ``None``; the composition root checks
    for required providers before building the runtime.

    The ``session_factory`` is the only required field; all session-scoped
    provider closures derive from it (each closure calls the factory
    internally per method call — Mode A).
    """

    # --- Session management (factory only, never a live Session) ---
    session_factory: Callable[[], Any]

    # --- Stateless LLM (process-level, no session) ---
    structured_llm: Optional[Any] = None  # StructuredLLMPort

    # --- Retrieval & cognition (session-scoped closures, Mode A) ---
    course_access: Optional[Any] = None  # CourseAccessPort
    course_retrieval: Optional[Any] = None  # CourseRetrievalPort
    knowledge_graph: Optional[Any] = None  # KnowledgeGraphPort
    student_modeling: Optional[Any] = None  # StudentModelingPort
    cognition: Optional[Any] = None  # CognitionPort
    student_history: Optional[Any] = None  # StudentHistoryPort

    # --- Teaching context (session-scoped closures, Mode A) ---
    recommendation: Optional[Any] = None  # RecommendationPort
    learning_events: Optional[Any] = None  # LearningEventPort
    conversation_context: Optional[Any] = None  # ConversationContextPort
    question_bank: Optional[Any] = None  # QuestionBankPort

    # --- Sandbox & coding (session-scoped closures, Mode A) ---
    sandbox: Optional[Any] = None  # SandboxPort
    coding_diagnosis: Optional[Any] = None  # CodingDiagnosisPort

    # --- Course build (session-scoped closures, Mode A) ---
    prep_evidence_retrieval: Optional[Any] = None  # PrepEvidenceRetrievalPort
    course_corpus: Optional[Any] = None  # CourseCorpusPort
    course_draft: Optional[Any] = None  # CourseDraftPort
    patch_proposals: Optional[Any] = None  # PatchProposalPort

    # --- Governance & audit (session-scoped closures, Mode A) ---
    tool_governance: Optional[Any] = None  # ToolGovernancePort
    teacher_safety_valve: Optional[Any] = None  # TeacherSafetyValvePort
    web_research: Optional[Any] = None  # WebResearchPort

    # --- Experiment & visualization (session-scoped closures, Mode A) ---
    experiment: Optional[Any] = None  # ExperimentPort
    experiment_dispatch: Optional[Any] = None  # ExperimentDispatchPort
    visualization: Optional[Any] = None  # VisualizationPort

    # --- Run store (process-level, stateless) ---
    run_store: Optional[Any] = None  # AgentRunStorePort
    event_port: Optional[Any] = None  # AgentRunEventPort
    audit_port: Optional[Any] = None  # AgentAuditPort

    # --- Closeable resources (HTTP clients, etc.) ---
    _closeables: list[Any] = field(default_factory=list)

    def register_closeable(self, resource: Any) -> None:
        """Register a resource with a ``close()`` or ``aclose()`` method.

        Registered resources are closed in LIFO order during ``close()``.
        Session-scoped closures are NOT registered here; they manage their
        own Session lifecycles.
        """
        self._closeables.append(resource)

    async def close(self) -> None:
        """Release process-level resources.

        Only process-level resources (HTTP clients, connection pools)
        registered via ``register_closeable`` are closed. Session-scoped
        closures manage their own Session lifecycle internally (Mode A)
        and are NOT closed here.
        """
        for resource in reversed(self._closeables):
            try:
                close_fn = getattr(resource, "aclose", None) or getattr(resource, "close", None)
                if close_fn is None:
                    continue
                result = close_fn()
                if hasattr(result, "__await__"):
                    await result
            except Exception:  # noqa: BLE001 - close failures must not abort shutdown
                logger.warning(
                    "ProviderContainer.close: resource %s raised; continuing.",
                    type(resource).__name__,
                    exc_info=True,
                )
        self._closeables.clear()

    def has(self, name: str) -> bool:
        """Check whether a provider field is set (non-None)."""
        return getattr(self, name, None) is not None

    def require(self, name: str) -> Any:
        """Get a provider field, raising if it is not set.

        Use this in composition roots to fail fast when a required
        dependency is missing.
        """
        value = getattr(self, name, None)
        if value is None:
            raise ValueError(
                f"ProviderContainer: required provider '{name}' is not configured",
            )
        return value


def build_provider_container(
    *,
    session_factory: Callable[[], Any],
    structured_llm: Any | None = None,
    **providers: Any,
) -> ProviderContainer:
    """Build a ``ProviderContainer`` from keyword arguments.

    This is a convenience factory that passes through all provider
    keyword arguments to the dataclass constructor. It exists so
    bootstrap code can be written as::

        container = build_provider_container(
            session_factory=session_factory,
            structured_llm=llm,
            course_retrieval=retrieval,
            ...
        )
    """
    return ProviderContainer(
        session_factory=session_factory,
        structured_llm=structured_llm,
        **providers,
    )


__all__ = [
    "ProviderContainer",
    "build_provider_container",
]
