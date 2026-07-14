"""Evidence — source identity, span mapping, and citation contracts.

Provides:
- EvidenceSpan / EvidenceBundle: reference stable P1-01 artifact/version/block IDs.
- TextTransformMap / ChunkSegment / SemanticChunk: preserve original char mapping
  across chunk transformations.
- Citation / CitationValidationResult: stable citation keys; no-evidence abstention.

Consumes P1-01 frozen contracts (document-ir/1.0):
  - SourceArtifact.artifact_id
  - DocumentIR.document_id
  - ContentBlock/TableBlock/FormulaBlock.block_id
  - Provenance (run_id, parser_run_id, provider)
  - BoundingBox, Polygon, CoordinateSpace (Geometry)
"""

from app.platform.evidence.citation import (
    Citation,
    CitationValidationResult,
    CitationStatus,
    citation_key,
)
from app.platform.evidence.contracts import (
    EvidenceBundle,
    EvidenceSpan,
    EvidenceStatus,
)
from app.platform.evidence.text_transform import (
    ChunkSegment,
    SemanticChunk,
    TextTransformMap,
)

__all__ = [
    "EvidenceSpan",
    "EvidenceBundle",
    "EvidenceStatus",
    "TextTransformMap",
    "ChunkSegment",
    "SemanticChunk",
    "Citation",
    "CitationValidationResult",
    "CitationStatus",
    "citation_key",
]
