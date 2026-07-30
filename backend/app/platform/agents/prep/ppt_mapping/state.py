"""State schema for the PPT mapping optimization pipeline.

The state extends ``PrepCommonState`` with two pipeline-specific blocks:
    - ``request``: the optimization request (teacher / course /
      material_version_id).
    - ``result``: the optimization summary (total/updated counts plus
      per-suggestion details).

All blocks are optional (``total=False``) so partial LangGraph node updates
remain valid: the single workflow node returns only the keys it changes.
"""

from __future__ import annotations

try:
    from typing import TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import TypedDict

from ..common.state import PrepCommonState


class PptMappingRequestState(TypedDict):
    """Optimization request parameters carried into the PPT mapping pipeline.

    All fields are required (``total=True``) so that whenever a ``request``
    block is present in the state it is fully populated. The enclosing
    ``PptMappingState.request`` key itself remains optional.
    """

    teacher_id: str
    course_id: str
    material_version_id: str


class PptMappingResultState(TypedDict, total=False):
    """Serialized optimization result output of the PPT mapping pipeline."""

    total_mappings: int
    updated_count: int
    suggestions: list[dict]


class PptMappingState(PrepCommonState, total=False):
    """State schema for the PPT mapping optimization pipeline.

    Inherits ``meta`` and ``graph_kind`` from ``PrepCommonState``. The
    ``graph_kind`` value for this pipeline is ``PrepGraphKind.PPT_MAPPING``
    (``"ppt_mapping"``), set by the profile's initial-state builder.
    """

    request: PptMappingRequestState
    result: PptMappingResultState


__all__ = [
    "PptMappingRequestState",
    "PptMappingResultState",
    "PptMappingState",
]
