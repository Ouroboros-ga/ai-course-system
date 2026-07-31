"""Dependencies for the PPT mapping optimization pipeline.

``PptMappingOptimizationPort`` is an adapted view of the planned
``PptMappingOptimizationService.optimize_mappings()`` method. The raw
service signature takes a SQLModel ``Session`` plus integer ``course_id``
and a string ``material_version_id``; the agent runtime cannot carry those
across the LangGraph boundary, so an adapter (registered in the agent
composition root) translates the string-typed request fields from
``PptMappingRequestState`` into the service call and returns a plain
``PptMappingOptimizationResult`` DTO. This keeps the workflow node free
of ORM/session concerns and lets the pipeline be tested with a stub port.

``PptMappingDependencies`` composes the cross-cutting
``CommonPrepDependencies`` (structured LLM, run store, event port) with
the pipeline-specific ``ppt_mapping`` port. It is a frozen dataclass,
assembled once at bootstrap.

Persistence boundary: unlike the Incremental pipeline (which returns
proposals for the endpoint to persist), the PPT mapping pipeline
persists directly inside the Service. The Service updates
``CoursePptMapping`` rows with ``status="draft"`` in place; it does NOT
modify mappings flagged ``teacher_locked=True``. No ``PatchProposal``
is created.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..common.dependencies import CommonPrepDependencies


@dataclass(frozen=True)
class PptMappingSuggestion:
    """One LLM-produced mapping suggestion.

    Uses ``page_refs`` (a list of page numbers) instead of a contiguous
    ``page_start``/``page_end`` range, because PPT content for one
    knowledge point often spans non-consecutive slides.

    The Service validates each suggestion against the course outline's
    knowledge-point IDs before applying it. Suggestions referencing
    unknown outline nodes are rejected (not silently dropped).
    """

    outline_node_id: str
    page_refs: list[int]
    confidence: float
    reason: str = ""


@dataclass(frozen=True)
class PptMappingOptimizationResult:
    """DTO mirroring the output of ``PptMappingOptimizationService``.

    Fields match ``PptMappingResultState`` one-for-one. The adapter
    converts the service's return value into this plain dataclass so the
    workflow node never imports ORM/service types.
    """

    total_mappings: int
    updated_count: int
    suggestions: list[PptMappingSuggestion] = field(default_factory=list)


class PptMappingOptimizationPort(Protocol):
    """Adapted port around ``PptMappingOptimizationService.optimize_mappings()``.

    Implementations translate the string-typed request fields into the
    service's native call (session, integer course_id, material_version_id)
    and wrap the returned result into a ``PptMappingOptimizationResult``.

    The port DOES persist: the Service updates ``CoursePptMapping`` rows
    in place. Mappings with ``teacher_locked=True`` are never modified.
    """

    async def optimize_mappings(
        self,
        *,
        course_id: str,
        material_version_id: str,
    ) -> PptMappingOptimizationResult: ...


@dataclass(frozen=True)
class PptMappingDependencies:
    """Dependencies injected into the PPT mapping pipeline.

    Attributes:
        common: Cross-cutting Prep dependencies (structured LLM, run store,
            event port) shared by all three Prep pipelines.
        ppt_mapping: Adapted port around
            ``PptMappingOptimizationService.optimize_mappings()``.
    """

    common: CommonPrepDependencies
    ppt_mapping: PptMappingOptimizationPort


__all__ = [
    "PptMappingSuggestion",
    "PptMappingOptimizationResult",
    "PptMappingOptimizationPort",
    "PptMappingDependencies",
]
