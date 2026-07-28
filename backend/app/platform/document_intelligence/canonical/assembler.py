"""Assemble provider output into one validated canonical DocumentIR."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from typing import Any, Iterable

from ..contracts import CURRENT_SCHEMA_VERSION, ReadingOrder
from ..document_ir.models import (
    ContentBlock,
    DocumentIR,
    DocumentUnit,
    ParseWarning,
    ParserRun,
    ParserRunStatus,
    QualityReport,
    UnitType,
    VisualAsset,
    WarningSeverity,
    block_from_dict,
    compute_document_id,
    compute_unit_id,
)


class CanonicalDocumentIRAssembler:
    """Turns reconciled provider dictionaries into the canonical contract.

    Mappers may provide detailed units and assets.  Any page/slide that lacks
    a mapper unit receives a deterministic unit built from its final blocks so
    every persisted block has a stable parent unit.
    """

    def assemble(
        self,
        *,
        source: Any,
        run_id: str,
        parser_run_id: str,
        blocks: Iterable[dict[str, Any]],
        units: Iterable[dict[str, Any]],
        assets: Iterable[dict[str, Any]],
        warnings: Iterable[str],
        provider_versions: dict[str, str],
    ) -> DocumentIR:
        document_id = compute_document_id(
            artifact_id=source.artifact_id,
            schema_version=CURRENT_SCHEMA_VERSION.serialize(),
            normalization_version=source.normalization_version,
        )
        raw_blocks = [self._normalise_block(item) for item in blocks]
        # Provider-local identifiers (for example ``slide-2/shape-5``) are
        # deterministic only inside a file.  Namespace them with document_id
        # so different source versions can never collide in the projection.
        id_map = {
            str(item.get("block_id") or f"ordinal-{index}"): self._stable_block_id(
                document_id, str(item.get("block_id") or f"ordinal-{index}")
            )
            for index, item in enumerate(raw_blocks)
        }
        for index, item in enumerate(raw_blocks):
            original = str(item.get("block_id") or f"ordinal-{index}")
            item["block_id"] = id_map[original]
            if item.get("parent_id"):
                item["parent_id"] = id_map.get(str(item["parent_id"]), item["parent_id"])
        normalized_blocks = tuple(block_from_dict(item) for item in raw_blocks)
        blocks_by_unit: dict[int, list[str]] = defaultdict(list)
        unpaged_block_ids: list[str] = []
        for block in normalized_blocks:
            if block.page_or_slide is not None:
                blocks_by_unit[int(block.page_or_slide)].append(block.block_id)
            else:
                unpaged_block_ids.append(block.block_id)

        units_by_index: dict[int, DocumentUnit] = {}
        for raw in units:
            unit = DocumentUnit.from_dict(raw)
            units_by_index[unit.index] = unit
        for index, block_ids in blocks_by_unit.items():
            unit = units_by_index.get(index)
            if unit is None:
                units_by_index[index] = DocumentUnit(
                    unit_id=compute_unit_id(
                        document_id=document_id,
                        unit_type=UnitType.PAGE.value,
                        index=index,
                        normalization_version=source.normalization_version,
                    ),
                    unit_type=UnitType.PAGE,
                    index=index,
                    block_ids=tuple(block_ids),
                    reading_order=ReadingOrder(block_ids=tuple(block_ids)),
                )
                continue
            # Mapper-provided units are authoritative for dimensions and type;
            # replace their references only after reconciliation changed blocks.
            units_by_index[index] = DocumentUnit(
                unit_id=unit.unit_id,
                unit_type=unit.unit_type,
                index=unit.index,
                label=unit.label,
                width=unit.width,
                height=unit.height,
                coordinate_unit=unit.coordinate_unit,
                block_ids=tuple(block_ids),
                reading_order=ReadingOrder(block_ids=tuple(block_ids)),
                notes_block_ids=unit.notes_block_ids,
                asset_ids=unit.asset_ids,
                quality=unit.quality,
                provenance=unit.provenance,
            )
        if unpaged_block_ids:
            units_by_index[0] = DocumentUnit(
                unit_id=compute_unit_id(
                    document_id=document_id,
                    unit_type=UnitType.SECTION.value,
                    index=0,
                    normalization_version=source.normalization_version,
                ),
                unit_type=UnitType.SECTION,
                index=0,
                block_ids=tuple(unpaged_block_ids),
                reading_order=ReadingOrder(block_ids=tuple(unpaged_block_ids)),
            )

        # Asset references are provider-local block locators as well. Rewrite
        # them through the canonical block namespace before integrity checks.
        parsed_assets = tuple(
            VisualAsset.from_dict({
                **asset,
                "linked_block_ids": [
                    id_map.get(str(block_id), str(block_id))
                    for block_id in asset.get("linked_block_ids", [])
                ],
            })
            for asset in assets
        )
        parsed_warnings = tuple(
            ParseWarning(
                code="PIPELINE_WARNING",
                severity=WarningSeverity.WARNING,
                message=str(message),
                run_id=run_id,
            )
            for message in warnings
        )
        parser_runs = tuple(
            ParserRun(
                run_id=run_id,
                parser_run_id=f"{parser_run_id}_{name}",
                provider=name,
                provider_version=version,
                status=ParserRunStatus.SUCCEEDED,
                input_artifact_id=source.artifact_id,
            )
            for name, version in sorted(provider_versions.items())
        )
        quality = self._quality(normalized_blocks, tuple(units_by_index.values()))
        return DocumentIR(
            schema_version=CURRENT_SCHEMA_VERSION.serialize(),
            document_id=document_id,
            source_artifact=source,
            parser_runs=parser_runs,
            units=tuple(sorted(units_by_index.values(), key=lambda item: item.index)),
            blocks=normalized_blocks,
            assets=parsed_assets,
            quality=quality,
            warnings=parsed_warnings,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalise_block(raw: dict[str, Any]) -> dict[str, Any]:
        item = dict(raw)
        # Content blocks emitted by old mappers used order_index.  The public
        # contract uses reading_order, therefore keep both input forms here.
        item.setdefault("reading_order", item.get("order_index", 0))
        item.setdefault("kind", "content")
        provenance = item.get("provenance")
        if provenance and not isinstance(provenance, (list, tuple)):
            item["provenance"] = [provenance.to_dict() if hasattr(provenance, "to_dict") else provenance]
        bbox = item.get("bbox")
        if bbox is not None and hasattr(bbox, "to_dict"):
            item["bbox"] = bbox.to_dict()
        return item

    @staticmethod
    def _stable_block_id(document_id: str, raw_locator: str) -> str:
        digest = hashlib.sha256(f"{document_id}:{raw_locator}".encode("utf-8")).hexdigest()
        return f"blk_{digest[:32]}"

    @staticmethod
    def _quality(blocks: tuple[Any, ...], units: tuple[DocumentUnit, ...]) -> QualityReport:
        text_blocks = [block for block in blocks if (getattr(block, "text", None) or "").strip()]
        ocr_blocks = [
            block for block in blocks
            if any("ocr" in (prov.provider or "").lower() for prov in getattr(block, "provenance", ()))
        ]
        duplicates = len(text_blocks) - len({(block.page_or_slide, (block.text or "").strip()) for block in text_blocks})
        empty_units = sum(1 for unit in units if not unit.block_ids)
        coverage = len(text_blocks) / max(len(blocks), 1)
        return QualityReport(
            overall_score=coverage,
            text_coverage=coverage,
            reading_order_confidence=1.0 if units else 0.0,
            heading_confidence=1.0,
            table_coverage=1.0,
            formula_coverage=1.0,
            duplicate_ratio=max(0.0, duplicates / max(len(text_blocks), 1)),
            empty_unit_ratio=empty_units / max(len(units), 1),
            ocr_ratio=len(ocr_blocks) / max(len(blocks), 1),
            scorer_version="canonical-assembler/1.0",
        )
