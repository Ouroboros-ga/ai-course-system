"""Citation and CitationValidationResult — stable citation identity and validation.

Design rules (per plan §5):
- ``citation_key`` is a stable, deterministic string derived from evidence data.
- NO evidence -> NO fake citation key. ``citation_key()`` returns None when no
  evidence is provided.
- ``CitationValidationResult`` includes an ``abstain`` field: when evidence is
  missing or insufficient, the validator recommends abstention rather than
  fabricating a citation.
- Reranking and prompt construction MUST NOT discard evidence IDs.

Contract version: ``citation/1.0`` (major=1).

Key semantics:
- ``citation_key()`` produces a deterministic key from (artifact_id, block_id,
  char_start, char_end). Same inputs => same key.
- If ``block_id`` is empty or None, returns None (no fake key).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CitationStatus(str, Enum):
    """Validation status of a citation.

    ``VERIFIED``     — the citation text matches the referenced evidence block.
    ``PARTIAL``      — partial match (text drift, minor differences).
    ``MISMATCH``     — citation text does NOT match the referenced evidence.
    ``STALE``        — the referenced evidence block/version is no longer current.
    ``NO_EVIDENCE``  — no evidence was provided; abstention recommended.
    """

    VERIFIED = "verified"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    STALE = "stale"
    NO_EVIDENCE = "no_evidence"


@dataclass(frozen=True)
class Citation:
    """A citation linking a generated statement to source evidence.

    Fields:
        key:          Stable deterministic citation key (or None for no-evidence).
        statement:    The generated statement this citation supports.
        evidence_ref: The EvidenceSpan (or evidence identifier) backing this
                      citation, if available.
        page_or_slide: Optional page/slide number for display.
        confidence:   Optional confidence score for this citation.
        metadata:     Extensible metadata.
    """

    key: Optional[str]
    statement: str
    evidence_ref: Optional[str] = None
    page_or_slide: Optional[int] = None
    confidence: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CitationValidationResult:
    """Result of validating one or more citations against evidence.

    ``abstain`` is True when the validator recommends the model abstain from
    answering (no evidence, insufficient evidence, or staleness).

    ``status`` is the overall status:
      - NO_EVIDENCE if all citations lack evidence -> abstain=True.
      - VERIFIED if all citations are verified.
      - PARTIAL/MISMATCH/STALE based on the worst status.

    ``details`` provides per-citation validation results.

    ``abstain_reason`` describes why abstention is recommended, if applicable.
    """

    status: CitationStatus
    abstain: bool = False
    abstain_reason: Optional[str] = None
    details: List[Dict[str, Any]] = field(default_factory=list)
    verified_count: int = 0
    total_count: int = 0


def citation_key(
    artifact_id: Optional[str],
    block_id: Optional[str],
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> Optional[str]:
    """Generate a stable citation key from evidence coordinates.

    Returns None when block_id is None or empty — no fake key for no-evidence
    citations.

    The key is deterministic: ``SHA-256(artifact_id|block_id|char_start|char_end)[:12]``.
    Same inputs always produce the same key.

    When char_start/char_end are None, they are omitted from the hash input,
    producing a block-level key rather than a span-level key.
    """
    if not block_id:
        return None

    parts = [artifact_id or "", block_id]
    if char_start is not None:
        parts.append(str(char_start))
    if char_end is not None:
        parts.append(str(char_end))

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
