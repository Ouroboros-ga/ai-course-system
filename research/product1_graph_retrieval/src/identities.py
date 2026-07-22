"""Stable research-only identities for the B-G0 sidecar.

The resulting IDs are not fields of any production contract.  Their explicit
``research_`` names are intentional and must be preserved in exported data.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Optional


def _stable_id(prefix: str, parts: Iterable[object]) -> str:
    values: list[str] = []
    for part in parts:
        value = "" if part is None else str(part)
        if "\x00" in value:
            raise ValueError("stable ID parts must not contain NUL")
        values.append(value)
    digest = hashlib.sha256("\x00".join(values).encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:24]}"


def research_evidence_id(
    *,
    course_id: str,
    artifact_id: str,
    document_id: str,
    unit_id: str,
    block_id: str,
    version_ref: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> str:
    return _stable_id(
        "rev_",
        (
            course_id,
            artifact_id,
            document_id,
            unit_id,
            block_id,
            version_ref,
            char_start,
            char_end,
        ),
    )


def research_chunk_id(
    *,
    course_id: str,
    document_id: str,
    unit_id: str,
    block_id: str,
    research_evidence_ids: Iterable[str],
    text_sha256: str,
) -> str:
    return _stable_id(
        "rch_",
        (
            course_id,
            document_id,
            unit_id,
            block_id,
            ",".join(sorted(research_evidence_ids)),
            text_sha256,
        ),
    )


def research_slide_id(*, course_id: str, document_id: str, unit_id: str) -> str:
    return _stable_id("rsl_", (course_id, document_id, unit_id))


def research_query_id(*, course_id: str, text: str) -> str:
    return _stable_id("rq_", (course_id, text))


def research_knowledge_point_id(*, course_id: str, canonical_label: str) -> str:
    return _stable_id("rkp_", (course_id, canonical_label))


def production_compatible_citation_key(
    *,
    artifact_id: Optional[str],
    block_id: Optional[str],
    char_start: Optional[int],
    char_end: Optional[int],
) -> Optional[str]:
    """Mirror ``platform.evidence.citation_key`` without importing app code."""

    if not block_id:
        return None
    parts = [artifact_id or "", block_id]
    if char_start is not None:
        parts.append(str(char_start))
    if char_end is not None:
        parts.append(str(char_end))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
