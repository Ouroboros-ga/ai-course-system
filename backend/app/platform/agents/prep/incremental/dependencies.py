"""Dependencies for the Incremental draft modification pipeline.

``IncrementalPrepPort`` is an adapted view of the existing
``CoursePrepAgentService.plan()`` method. The raw service signature takes a
SQLModel ``Session`` plus integer ``course_id`` and a string ``instruction``;
the agent runtime cannot carry those across the LangGraph boundary, so an
adapter (registered in the agent composition root) translates the
string-typed request fields from ``IncrementalPrepRequestState`` into the
service call and returns a plain ``IncrementalPrepResult`` DTO. This keeps
the workflow node free of ORM/session concerns and lets the pipeline be
tested with a stub port.

``IncrementalPrepDependencies`` composes the cross-cutting
``CommonPrepDependencies`` (structured LLM, run store, event port) with the
pipeline-specific ``incremental_prep`` port. It is a frozen dataclass,
assembled once at bootstrap.

Persistence boundary: the Incremental pipeline does NOT persist. The
``IncrementalPrepPort.plan()`` returns a proposal; the endpoint layer
creates the ``PatchProposal`` row. This matches the existing service
behaviour where ``CoursePrepAgentService.plan()`` returns a
``CoursePrepAgentResult`` without writing to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..common.dependencies import CommonPrepDependencies


@dataclass(frozen=True)
class IncrementalPrepResult:
    """DTO mirroring the relevant fields of ``CoursePrepAgentResult``.

    The adapter converts the service's ``CoursePrepAgentResult`` into this
    plain dataclass so the workflow node never imports ORM/service types.
    Fields match ``IncrementalPrepResultState`` one-for-one.
    """

    summary: str
    operations: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    excluded_locked_targets: list[str] = field(default_factory=list)
    planner: str = "llm"


class IncrementalPrepPort(Protocol):
    """Adapted port around ``CoursePrepAgentService.plan()``.

    Implementations translate the string-typed request fields into the
    service's native call (session, integer course_id, instruction,
    optional outline_node_id) and wrap the returned
    ``CoursePrepAgentResult`` into an ``IncrementalPrepResult``.

    The port does NOT persist. The endpoint layer is responsible for
    creating the ``PatchProposal`` row from the returned operations.
    """

    async def plan(
        self,
        *,
        course_id: str,
        instruction: str,
        outline_node_id: str | None,
    ) -> IncrementalPrepResult: ...


@dataclass(frozen=True)
class IncrementalPrepDependencies:
    """Dependencies injected into the Incremental pipeline.

    Attributes:
        common: Cross-cutting Prep dependencies (structured LLM, run store,
            event port) shared by all three Prep pipelines.
        incremental_prep: Adapted port around ``CoursePrepAgentService.plan()``.
    """

    common: CommonPrepDependencies
    incremental_prep: IncrementalPrepPort


__all__ = [
    "IncrementalPrepResult",
    "IncrementalPrepPort",
    "IncrementalPrepDependencies",
]
