"""State schema for the Incremental draft modification pipeline.

The state extends ``PrepCommonState`` with three pipeline-specific blocks:
    - ``request``: the planning request (teacher / course / instruction /
      optional outline_node_id selector).
    - ``context``: editable-target allow-list and locked-target exclusion
      list computed by the Service before the LLM call. Populated
      opportunistically; the authoritative allow-list lives inside the
      Service.
    - ``result``: the ``CoursePrepAgentResult``-shaped output of
      ``CoursePrepAgentService.plan()`` (summary + operations + evidence +
      excluded locked targets + planner name).

All blocks are optional (``total=False``) so partial LangGraph node updates
remain valid: the single workflow node returns only the keys it changes.
"""

from __future__ import annotations

try:
    from typing import TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import TypedDict

from ..common.state import PrepCommonState


class IncrementalPrepRequestState(TypedDict):
    """Planning request parameters carried into the Incremental pipeline.

    All fields are required (``total=True``) so that whenever a ``request``
    block is present in the state it is fully populated. The enclosing
    ``IncrementalPrepState.request`` key itself remains optional.
    """

    teacher_id: str
    course_id: str
    instruction: str
    outline_node_id: str | None


class IncrementalPrepContextState(TypedDict, total=False):
    """Editable-target context computed by the Service.

    Populated opportunistically by the workflow node after the Service
    returns; the authoritative allow-list enforcement stays inside the
    Service (evidence_refs hard gate + locked-node exclusion).
    """

    editable_target_ids: list[str]
    excluded_locked_targets: list[str]
    allowed_evidence_ids: list[str]


class IncrementalPrepResultState(TypedDict, total=False):
    """Serialized ``CoursePrepAgentResult`` output of the Incremental plan."""

    summary: str
    operations: list[dict]
    evidence: list[dict]
    excluded_locked_targets: list[str]
    planner: str


class IncrementalPrepState(PrepCommonState, total=False):
    """State schema for the Incremental draft modification pipeline.

    Inherits ``meta`` and ``graph_kind`` from ``PrepCommonState``. The
    ``graph_kind`` value for this pipeline is ``PrepGraphKind.INCREMENTAL``
    (``"incremental"``), set by the profile's initial-state builder.
    """

    request: IncrementalPrepRequestState
    context: IncrementalPrepContextState
    result: IncrementalPrepResultState


__all__ = [
    "IncrementalPrepRequestState",
    "IncrementalPrepContextState",
    "IncrementalPrepResultState",
    "IncrementalPrepState",
]
