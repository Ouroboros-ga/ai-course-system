"""Frozen chapter-distance semantics for future B-R2 feature reuse.

This module defines only the feature contract.  It does not implement mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class ChapterDistance:
    basis: str
    distance: Optional[int]
    proximity: float
    missing: bool


def chapter_distance(
    left_path: Optional[Sequence[str]],
    right_path: Optional[Sequence[str]],
    *,
    left_document_id: Optional[str] = None,
    right_document_id: Optional[str] = None,
    left_page: Optional[int] = None,
    right_page: Optional[int] = None,
) -> ChapterDistance:
    """Return a deterministic tree distance or same-document page fallback.

    Priority is frozen: valid chapter paths first; otherwise use absolute page
    gap only when both pages belong to the same document.  Missing context has
    feature value 0 and is never silently treated as distance 0.
    """

    if left_path and right_path:
        if left_path[0] != right_path[0]:
            raise ValueError("chapter paths from different courses cannot be compared")
        common = 0
        for left, right in zip(left_path, right_path):
            if left != right:
                break
            common += 1
        distance = (len(left_path) - common) + (len(right_path) - common)
        return ChapterDistance(
            basis="tree_edges",
            distance=distance,
            proximity=1.0 / (1.0 + distance),
            missing=False,
        )

    if (
        left_document_id
        and left_document_id == right_document_id
        and isinstance(left_page, int)
        and isinstance(right_page, int)
        and left_page >= 1
        and right_page >= 1
    ):
        distance = abs(left_page - right_page)
        return ChapterDistance(
            basis="same_document_page_gap",
            distance=distance,
            proximity=1.0 / (1.0 + distance),
            missing=False,
        )

    return ChapterDistance(
        basis="unknown",
        distance=None,
        proximity=0.0,
        missing=True,
    )
