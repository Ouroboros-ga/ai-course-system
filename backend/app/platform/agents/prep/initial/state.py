"""State schema for the Initial course build pipeline.

The state extends ``PrepCommonState`` with three pipeline-specific blocks:
    - ``request``: the build request parameters (teacher / course / corpus /
      build task). Required fields live in ``InitialPrepRequestState`` so a
      present ``request`` block is always well-formed.
    - ``progress``: the latest stage progress tick. Populated opportunistically;
      the authoritative progress stream flows through ``StageEmitter`` events,
      this block is a best-effort mirror for state inspectors.
    - ``result``: the ``DraftAssetResult``-shaped output of
      ``InitialCoursePrepService.build()`` (outline / script / graph-candidate
      version IDs plus build warnings).

All blocks are optional (``total=False``) so partial LangGraph node updates
remain valid: the single workflow node returns only the keys it changes.
"""

from __future__ import annotations

try:
    from typing import TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import TypedDict

from ..common.state import PrepCommonState


class InitialPrepRequestState(TypedDict):
    """Build request parameters carried into the Initial pipeline.

    All fields are required (``total=True``) so that whenever a ``request``
    block is present in the state it is fully populated. The enclosing
    ``InitialPrepState.request`` key itself remains optional.
    """

    teacher_id: str
    course_id: str
    corpus_snapshot_id: str
    build_task_id: str | None


class PrepProgressState(TypedDict, total=False):
    """Best-effort mirror of the latest stage progress tick."""

    stage: str
    progress: int
    message: str | None


class InitialPrepResultState(TypedDict, total=False):
    """Serialized ``DraftAssetResult`` output of the Initial build."""

    outline_version_id: str
    script_version_id: str
    graph_candidate_batch_id: str
    warnings: list[str]


class InitialPrepState(PrepCommonState, total=False):
    """State schema for the Initial course build pipeline.

    Inherits ``meta`` and ``graph_kind`` from ``PrepCommonState``. The
    ``graph_kind`` value for this pipeline is ``PrepGraphKind.INITIAL``
    (``"initial"``), set by the profile's initial-state builder.
    """

    request: InitialPrepRequestState
    progress: PrepProgressState
    result: InitialPrepResultState


__all__ = [
    "InitialPrepRequestState",
    "PrepProgressState",
    "InitialPrepResultState",
    "InitialPrepState",
]
