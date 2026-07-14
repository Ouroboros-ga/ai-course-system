"""Cross-run block reconciliation — aligning and de-duplicating blocks from
multiple parser providers.

When multiple providers parse the same document (e.g., native-pptx + Docling),
their block-level outputs may overlap, conflict, or complement each other.
Reconciliation aligns these outputs by page, matches blocks using spatial
and textual similarity, resolves conflicts, and produces a unified block set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from .document_ir.models import (
    Block,
    ContentBlock,
    DocumentIR,
    DocumentUnit,
    ParseWarning,
    TableBlock,
    WarningSeverity,
)


# ---------------------------------------------------------------------------
# Match scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockMatch:
    """A matched pair of blocks from different providers."""

    block_a_id: str
    block_b_id: str
    iou_score: float
    text_similarity: float
    type_compatibility: float
    match_score: float
    is_conflict: bool = False  # True if matched but incompatible


@dataclass(frozen=True)
class ReconciliationResult:
    """Result of reconciling multiple parser runs."""

    blocks: Tuple[Block, ...]
    units: Tuple[DocumentUnit, ...]
    matches: Tuple[BlockMatch, ...]
    conflicts: Tuple[BlockMatch, ...]  # unresolved conflicts
    warnings: Tuple[ParseWarning, ...]


# ---------------------------------------------------------------------------
# Reconciliation scoring constants
# ---------------------------------------------------------------------------

# Weights from R2D0 spec: 0.35*IoU + 0.35*text_similarity + 0.15*type + 0.15*order
IOU_WEIGHT = 0.35
TEXT_WEIGHT = 0.35
TYPE_WEIGHT = 0.15
ORDER_WEIGHT = 0.15

MATCH_THRESHOLD = 0.75      # >= 0.75 auto-align
CONFLICT_THRESHOLD = 0.50   # 0.5-0.75 keep as conflict
DEDUP_TEXT_SIMILARITY = 0.95
DEDUP_IOU = 0.70


# ---------------------------------------------------------------------------
# BlockReconciler
# ---------------------------------------------------------------------------


class BlockReconciler:
    """Reconciles blocks from multiple parser runs.

    The reconciler matches blocks by page, computes match scores using
    IoU, text similarity, type compatibility, and reading-order adjacency,
    then resolves duplicates and conflicts.
    """

    def reconcile(
        self,
        primary: DocumentIR,
        secondary: DocumentIR,
        *,
        primary_priority: bool = True,
    ) -> ReconciliationResult:
        """Reconcile two DocumentIR results.

        Args:
            primary: The primary parse result (anchor).
            secondary: The secondary parse result (to merge in).
            primary_priority: If True, prefer primary blocks in conflicts.

        Returns:
            A ReconciliationResult with merged blocks, matches, and conflicts.
        """
        # Index blocks by page
        primary_by_page = self._index_by_page(primary)
        secondary_by_page = self._index_by_page(secondary)

        all_matches: List[BlockMatch] = []
        all_conflicts: List[BlockMatch] = []
        merged_blocks: List[Block] = []
        seen_ids: Set[str] = set()
        warnings: List[ParseWarning] = []

        # Process each page
        all_pages = set(primary_by_page.keys()) | set(secondary_by_page.keys())

        for page in sorted(all_pages):
            p_blocks = primary_by_page.get(page, [])
            s_blocks = secondary_by_page.get(page, [])

            if not p_blocks:
                # All secondary blocks for this page are new
                for b in s_blocks:
                    if b.block_id not in seen_ids:
                        merged_blocks.append(b)
                        seen_ids.add(b.block_id)
                continue

            if not s_blocks:
                for b in p_blocks:
                    if b.block_id not in seen_ids:
                        merged_blocks.append(b)
                        seen_ids.add(b.block_id)
                continue

            # Match blocks
            matches, conflicts = self._match_blocks(p_blocks, s_blocks)
            all_matches.extend(matches)
            all_conflicts.extend(conflicts)

            matched_secondary: Set[str] = set()

            for match in matches:
                if match.is_conflict:
                    if primary_priority:
                        self._add_block(merged_blocks, seen_ids,
                                        self._get_block(primary, match.block_a_id))
                    else:
                        self._add_block(merged_blocks, seen_ids,
                                        self._get_block(secondary, match.block_b_id))
                    matched_secondary.add(match.block_b_id)
                    warnings.append(ParseWarning(
                        code="RECONCILIATION_CONFLICT",
                        severity=WarningSeverity.WARNING,
                        message=(
                            f"Conflict between {match.block_a_id} and "
                            f"{match.block_b_id} (score={match.match_score:.2f})"
                        ),
                        recoverable=True,
                    ))
                else:
                    # Auto-aligned: use primary
                    self._add_block(merged_blocks, seen_ids,
                                    self._get_block(primary, match.block_a_id))
                    matched_secondary.add(match.block_b_id)

            # Add unmatched primary blocks
            for b in p_blocks:
                if b.block_id not in seen_ids:
                    merged_blocks.append(b)
                    seen_ids.add(b.block_id)

            # Add unmatched secondary blocks as new
            for b in s_blocks:
                if b.block_id not in matched_secondary and b.block_id not in seen_ids:
                    merged_blocks.append(b)
                    seen_ids.add(b.block_id)

        # Merge units
        merged_units = self._merge_units(primary, secondary)

        if all_conflicts:
            warnings.append(ParseWarning(
                code="RECONCILIATION_UNRESOLVED_CONFLICTS",
                severity=WarningSeverity.WARNING,
                message=f"{len(all_conflicts)} block conflicts remain unresolved",
                recoverable=True,
            ))

        return ReconciliationResult(
            blocks=tuple(merged_blocks),
            units=tuple(merged_units),
            matches=tuple(all_matches),
            conflicts=tuple(all_conflicts),
            warnings=tuple(warnings),
        )

    def _index_by_page(self, doc: DocumentIR) -> Dict[int, List[Block]]:
        """Index blocks by page_or_slide number."""
        index: Dict[int, List[Block]] = {}
        for block in doc.blocks:
            page = block.page_or_slide or 0
            index.setdefault(page, []).append(block)
        return index

    def _match_blocks(
        self,
        primary: List[Block],
        secondary: List[Block],
    ) -> Tuple[List[BlockMatch], List[BlockMatch]]:
        """Match blocks between two lists using spatial+textual similarity.

        Returns (matches, conflicts).
        """
        matches: List[BlockMatch] = []
        conflicts: List[BlockMatch] = []
        used_secondary: Set[int] = set()

        for p_idx, p_block in enumerate(primary):
            best_score = 0.0
            best_s_idx = -1
            best_iou = 0.0
            best_text_sim = 0.0
            best_type_comp = 0.0

            for s_idx, s_block in enumerate(secondary):
                if s_idx in used_secondary:
                    continue

                iou = self._compute_iou(p_block, s_block)
                text_sim = self._compute_text_similarity(p_block, s_block)
                type_comp = self._compute_type_compatibility(p_block, s_block)
                score = (
                    IOU_WEIGHT * iou
                    + TEXT_WEIGHT * text_sim
                    + TYPE_WEIGHT * type_comp
                )

                if score > best_score:
                    best_score = score
                    best_s_idx = s_idx
                    best_iou = iou
                    best_text_sim = text_sim
                    best_type_comp = type_comp

            if best_score >= MATCH_THRESHOLD and best_s_idx >= 0:
                matches.append(BlockMatch(
                    block_a_id=p_block.block_id,
                    block_b_id=secondary[best_s_idx].block_id,
                    iou_score=best_iou,
                    text_similarity=best_text_sim,
                    type_compatibility=best_type_comp,
                    match_score=best_score,
                    is_conflict=False,
                ))
                used_secondary.add(best_s_idx)
            elif best_score >= CONFLICT_THRESHOLD and best_s_idx >= 0:
                conflicts.append(BlockMatch(
                    block_a_id=p_block.block_id,
                    block_b_id=secondary[best_s_idx].block_id,
                    iou_score=best_iou,
                    text_similarity=best_text_sim,
                    type_compatibility=best_type_comp,
                    match_score=best_score,
                    is_conflict=True,
                ))
                used_secondary.add(best_s_idx)

        return matches, conflicts

    @staticmethod
    def _compute_iou(a: Block, b: Block) -> float:
        """Compute IoU between two blocks' bounding boxes."""
        if a.bbox is None or b.bbox is None:
            return 0.0
        # Intersection
        x0 = max(a.bbox.x0, b.bbox.x0)
        y0 = max(a.bbox.y0, b.bbox.y0)
        x1 = min(a.bbox.x1, b.bbox.x1)
        y1 = min(a.bbox.y1, b.bbox.y1)
        if x0 >= x1 or y0 >= y1:
            return 0.0
        inter = (x1 - x0) * (y1 - y0)
        a_area = a.bbox.width() * a.bbox.height()
        b_area = b.bbox.width() * b.bbox.height()
        union = a_area + b_area - inter
        if union <= 0:
            return 0.0
        return inter / union

    @staticmethod
    def _compute_text_similarity(a: Block, b: Block) -> float:
        """Compute normalized text similarity between two blocks."""
        text_a = _get_block_text(a)
        text_b = _get_block_text(b)
        if not text_a or not text_b:
            return 0.0
        # Simple character-level overlap
        set_a = set(text_a.lower())
        set_b = set(text_b.lower())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / max(len(union), 1)

    @staticmethod
    def _compute_type_compatibility(a: Block, b: Block) -> float:
        """Compute type compatibility between two blocks."""
        type_a = a.block_type if hasattr(a, "block_type") else ""
        type_b = b.block_type if hasattr(b, "block_type") else ""
        if type_a == type_b:
            return 1.0
        # Compatible type groups
        heading_types = {"title", "heading"}
        text_types = {"paragraph", "list_item", "caption", "quote"}
        if type_a in heading_types and type_b in heading_types:
            return 0.8
        if type_a in text_types and type_b in text_types:
            return 0.7
        return 0.3

    @staticmethod
    def _get_block(doc: DocumentIR, block_id: str) -> Optional[Block]:
        """Get a block by ID from a DocumentIR."""
        for block in doc.blocks:
            if block.block_id == block_id:
                return block
        return None

    @staticmethod
    def _add_block(
        blocks: List[Block],
        seen_ids: Set[str],
        block: Optional[Block],
    ) -> None:
        """Add a block to the list if not already seen."""
        if block is None or block.block_id in seen_ids:
            return
        blocks.append(block)
        seen_ids.add(block.block_id)

    @staticmethod
    def _merge_units(
        primary: DocumentIR,
        secondary: DocumentIR,
    ) -> List[DocumentUnit]:
        """Merge units from primary and secondary documents."""
        merged: List[DocumentUnit] = []
        seen_unit_ids: Set[str] = set()

        for unit in primary.units:
            merged.append(unit)
            seen_unit_ids.add(unit.unit_id)

        for unit in secondary.units:
            if unit.unit_id not in seen_unit_ids:
                merged.append(unit)
                seen_unit_ids.add(unit.unit_id)

        return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_block_text(block: Block) -> str:
    """Extract text from any block type."""
    if isinstance(block, ContentBlock):
        return block.text or block.ocr_text or ""
    if isinstance(block, TableBlock):
        return block.text or block.markdown or ""
    return getattr(block, "text", None) or getattr(block, "latex", "") or ""
