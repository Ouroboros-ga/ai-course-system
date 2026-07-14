"""Product 1 V2 shadow pipeline (G3B+).

Isolated V2 shadow execution triggered after V1 success. Shadow writes
only to independent artifact stores; V1 tables/behavior are never
modified. See ADR-0006 (Accepted-G3A-only + G3B authorized).
"""
from app.platform.shadow.doc_shadow import (
    ShadowArtifactStore,
    ShadowTriggerResult,
    trigger_doc_shadow,
)

__all__ = [
    "ShadowArtifactStore",
    "ShadowTriggerResult",
    "trigger_doc_shadow",
]
