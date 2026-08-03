"""Dependencies for the Initial course build pipeline.

``InitialCoursePrepPort`` is an adapted view of the existing
``InitialCoursePrepService.build()`` method. The raw service signature takes a
SQLModel ``Session`` plus integer IDs and a ``ControlledPrepWorkflow``; the
agent runtime cannot carry those across the LangGraph boundary, so an adapter
(registered in the agent composition root) translates the string-typed
request fields from ``InitialPrepRequestState`` into the service call and
returns a plain ``InitialPrepResult`` DTO. This keeps the workflow node free
of ORM/session concerns and lets the pipeline be tested with a stub port.

``InitialPrepDependencies`` composes the cross-cutting ``CommonPrepDependencies``
(structured LLM, run store, event port) with the pipeline-specific
``initial_prep`` port. It is a frozen dataclass, assembled once at bootstrap.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from ..common.dependencies import CommonPrepDependencies


@dataclass(frozen=True)
class InitialPrepResult:
    """DTO mirroring the relevant fields of ``DraftAssetResult``.

    The adapter converts the service's ``DraftAssetResult`` into this plain
    dataclass so the workflow node never imports ORM/service types. Fields
    match ``InitialPrepResultState`` one-for-one.
    """

    outline_version_id: str
    script_version_id: str
    graph_candidate_batch_id: str
    warnings: list[str] = field(default_factory=list)
    rag_indexed_chunks: int = 0
    graph_node_candidates: int = 0
    graph_relation_candidates: int = 0
    outline_node_count: int = 0
    script_node_count: int = 0
    markdown_resource_id: str = ""
    markdown_resource_version_id: str = ""


class InitialCoursePrepPort(Protocol):
    """Adapted port around ``InitialCoursePrepService.build()``.

    Implementations translate the string-typed request fields into the
    service's native call (session, integer IDs, workflow, ...) and wrap the
    returned ``DraftAssetResult`` into an ``InitialPrepResult``.

    The ``on_stage`` callback shape matches ``ControlledPrepWorkflow.on_stage``
    (``Callable[[str, int, Any], Awaitable[None] | None]``) and is produced by
    ``StageEmitter.make_callback()`` in the workflow node.
    """

    async def build(
        self,
        *,
        teacher_id: str,
        course_id: str,
        corpus_snapshot_id: str,
        build_task_id: str | None,
        on_stage: Callable[[str, int, Any], Awaitable[None] | None] | None,
        replace_unreviewed_initial: bool,
    ) -> InitialPrepResult: ...


@dataclass(frozen=True)
class InitialPrepDependencies:
    """Dependencies injected into the Initial pipeline.

    Attributes:
        common: Cross-cutting Prep dependencies (structured LLM, run store,
            event port) shared by all three Prep pipelines.
        initial_prep: Adapted port around ``InitialCoursePrepService.build()``.
    """

    common: CommonPrepDependencies
    initial_prep: InitialCoursePrepPort


__all__ = [
    "InitialPrepResult",
    "InitialCoursePrepPort",
    "InitialPrepDependencies",
]
