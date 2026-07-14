"""EvidenceSpan and EvidenceBundle — source-level evidence identity.

Every EvidenceSpan MUST reference an existing P1-01 stable ID:
  - ``artifact_id`` from SourceArtifact
  - ``document_id`` from DocumentIR
  - ``unit_id`` from DocumentUnit
  - ``block_id`` from ContentBlock / TableBlock / FormulaBlock

Design rules (per plan §5 and ADR-0003):
- Evidence must always reference a concrete block; no "orphan" evidence.
- Stale evidence (version mismatch) is explicitly flagged via ``EvidenceStatus.STALE``.
- Evidence with status ``STALE`` must never be presented as current.
- Evidence must not fabricate source locations or citation keys.

Version semantics (P1-03 contract, major=1):
- ``evidence/1``: current contract version.
- Changes: adding optional fields is minor; changing block_id semantics is major.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EvidenceStatus(str, Enum):
    """Lifecycle status of an evidence span.

    ``ACTIVE``    — the referenced block/version is current.
    ``STALE``     — the referenced block/version has been superseded.
    ``SUSPENDED`` — temporarily excluded from retrieval/citation.
    """

    ACTIVE = "active"
    STALE = "stale"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class EvidenceSpan:
    """A single span of evidence referencing a stable P1-01 block.

    Fields:
        artifact_id:   Stable SourceArtifact ID (``art_`` prefix).
        document_id:   Stable DocumentIR document ID (``doc_`` prefix).
        unit_id:       Stable DocumentUnit ID (``unit_`` prefix).
        block_id:      Stable ContentBlock/TableBlock/FormulaBlock block_id.
        version_ref:   Optional document version or parser run identifier
                       for staleness detection.
        page_or_slide: Page/slide number (informational, not part of stable ID).
        char_start:    Zero-based start offset into the block's canonical text.
        char_end:      Zero-based end offset (exclusive).
        text_snippet:  The actual text this evidence covers (for display/validation).
        score:         Optional relevance/confidence score from retrieval.
        status:        ``EvidenceStatus.ACTIVE`` (default).
        metadata:      Extensible metadata dict (no stable ID semantics).
    """

    artifact_id: str
    document_id: str
    unit_id: str
    block_id: str

    version_ref: Optional[str] = None
    page_or_slide: Optional[int] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    text_snippet: Optional[str] = None
    score: Optional[float] = None

    status: EvidenceStatus = EvidenceStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_active(self) -> bool:
        """Return True if this evidence is ACTIVE."""
        return self.status == EvidenceStatus.ACTIVE

    def is_stale(self) -> bool:
        """Return True if this evidence is STALE (superseded version)."""
        return self.status == EvidenceStatus.STALE


@dataclass(frozen=True)
class EvidenceBundle:
    """A collection of EvidenceSpan items from one or more sources.

    ``bundle_id`` is a short stable identifier for this bundle.
    ``sources`` lists the distinct source documents referenced.

    Design rule: every evidence in ``items`` MUST reference a concrete
    P1-01 block_id that exists (or existed) in the source document.
    Stale evidence is included explicitly with ``status=STALE`` rather
    than silently dropped — downstream can decide how to handle it.
    """

    bundle_id: str
    items: List[EvidenceSpan] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    total_score: Optional[float] = None
    created_at: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    @property
    def active_items(self) -> List[EvidenceSpan]:
        """Return only ACTIVE evidence spans."""
        return [e for e in self.items if e.is_active()]

    @property
    def stale_items(self) -> List[EvidenceSpan]:
        """Return only STALE evidence spans."""
        return [e for e in self.items if e.is_stale()]
