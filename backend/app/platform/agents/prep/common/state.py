"""PrepCommonState: shared state fields for all Prep Agent pipelines.

Every Prep pipeline (Initial, Incremental, PPT mapping) carries the same
runtime metadata and graph-kind discriminator. Pipeline-specific fields
(evidence, outline, scripts, patch operations, PPT mappings, ...) live in
their own pipeline state types; ``PrepCommonState`` is the minimal common
base they nest or extend.

Design rules:
    - ``meta`` is the unified ``RuntimeMeta`` block owned by the runtime
      layer (see ``shared/state.py``). Agent nodes may append to its
      ``warnings`` / ``errors`` / ``degraded_services`` / ``node_trace`` but
      must not overwrite run identity fields.
    - ``graph_kind`` is the string value of ``PrepGraphKind`` (``"initial"``,
      ``"incremental"``, ``"ppt_mapping"``). It is typed as ``str`` (not the
      enum) so this common module does not import the Prep-specific enum,
      keeping the dependency direction one-way (the enum may import common;
      common must not import the enum).
    - ``total=False`` so partial LangGraph node updates remain valid.
"""

from __future__ import annotations

try:
    from typing import TypedDict
except ImportError:  # Python < 3.11
    from typing_extensions import TypedDict

from ...shared.state import RuntimeMeta


class PrepCommonState(TypedDict, total=False):
    """Shared state fields for every Prep Agent pipeline.

    Attributes:
        meta: Unified runtime metadata (run identity, trace, warnings, ...).
        graph_kind: The ``PrepGraphKind`` value identifying the active
            pipeline (``"initial"`` / ``"incremental"`` / ``"ppt_mapping"``).
    """

    meta: RuntimeMeta
    graph_kind: str


__all__ = ["PrepCommonState"]
