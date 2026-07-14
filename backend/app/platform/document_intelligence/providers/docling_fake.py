"""Docling parser provider (fake/capability-only).

This module defines the Docling provider capability contract and a fake
implementation for offline testing.  Real Docling integration requires
dependency approval and cannot be installed or activated during R2D1.

The fake provider simulates Docling-like output for test fixtures and
offline development, producing structured page-level results compatible
with the DocumentIR mapper.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..registry import (
    ParserCapabilities,
    ParserOutput,
    ParseError,
    ParseTimeoutError,
    ParseUnavailableError,
    ParseMalformedError,
)
from ..planner import ParsePlan
from ..source_artifact import SourceArtifact


# ---------------------------------------------------------------------------
# Check real Docling availability
# ---------------------------------------------------------------------------

try:
    import docling  # noqa: F401
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False


# ---------------------------------------------------------------------------
# Fake Docling provider
# ---------------------------------------------------------------------------


class DoclingFakeProvider:
    """Fake Docling provider for offline testing and development.

    This provider simulates Docling-like parsing behavior.  It does NOT
    invoke real Docling — it returns structured test data based on the
    source artifact filename/mime and a built-in fixture set.

    Use this for:
    - Contract tests (proves the provider contract is satisfied)
    - Offline development when Docling is unavailable
    - Fake-based integration tests

    Do NOT use this for:
    - Real parsing quality measurement
    - Production workloads

    When real Docling is installed and approved, replace this with
    ``DoclingProvider`` (same contract, different implementation).
    """

    name = "docling-fake"
    version = "1.0.0-fake"
    capabilities = ParserCapabilities(
        supported_formats=("pdf", "pptx", "docx", "image"),
        supports_tables=True,
        supports_formulas=True,
        supports_reading_order=True,
        supports_heading_detection=True,
        supports_visual_assets=True,
        supports_coordinates=True,
        supports_provenance=True,
        max_file_size_bytes=500 * 1024 * 1024,
        max_pages=500,
    )

    def __init__(self) -> None:
        self._real_available = HAS_DOCLING

    @property
    def is_real(self) -> bool:
        """Return True if real Docling is available.

        Always returns False for the fake provider.  Even if the ``docling``
        package happens to be installed in the environment, this provider
        does NOT use it — it returns deterministic fake output.
        """
        return False

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Parse a document using the fake Docling provider.

        Args:
            source: The source artifact.
            plan: The parse plan.

        Returns:
            Fake ParserOutput with structured page data.

        Raises:
            ParseTimeoutError: If timeout is exceeded.
            ParseMalformedError: If the source type is unsupported.
        """
        timeout_ms = 180000
        if plan.steps:
            primary = plan.primary_step
            if primary:
                timeout_ms = primary.timeout_ms

        start = time.perf_counter()

        # Determine number of pages from filename/mime hints
        page_count = self._estimate_page_count(source)

        # Simulate parsing delay
        import asyncio
        delay = min(page_count * 0.05, 2.0)  # 50ms per page, max 2s
        await asyncio.sleep(delay)

        elapsed = (time.perf_counter() - start) * 1000
        if elapsed > timeout_ms:
            raise ParseTimeoutError(
                f"Docling fake parsing timed out after {timeout_ms}ms"
            )

        # Generate fake page data
        pages: List[Dict[str, Any]] = []
        for i in range(1, page_count + 1):
            page = self._generate_fake_page(i, source)
            pages.append(page)

        return ParserOutput(
            provider=self.name,
            provider_version=self.version,
            pages=tuple(pages),
            metadata={
                "page_count": page_count,
                "duration_ms": int(elapsed),
                "is_fake": True,
            },
            warnings=["Using fake Docling provider — results are not real parse output"],
        )

    def _estimate_page_count(self, source: SourceArtifact) -> int:
        """Estimate page count from source artifact metadata."""
        mime = source.mime.lower()
        size = source.size_bytes

        if "presentation" in mime:
            # Estimate slides from file size (~100KB per slide avg)
            return max(1, size // 100000)
        if "pdf" in mime:
            return max(1, size // 50000)
        if "image" in mime:
            return 1

        return 3  # default

    def _generate_fake_page(
        self,
        index: int,
        source: SourceArtifact,
    ) -> Dict[str, Any]:
        """Generate a single page of fake Docling output."""
        return {
            "page_no": index,
            "text": f"Fake Docling page {index} content for {source.filename}.",
            "width": 8.5,
            "height": 11.0,
            "coordinate_unit": "inch",
            "blocks": [
                {
                    "bbox": [0.5, 0.5 + (index * 0.1), 7.5, 1.5 + (index * 0.1)],
                    "text": f"Page {index} heading",
                    "label": "heading",
                    "order": 1,
                    "confidence": 0.95,
                },
                {
                    "bbox": [0.5, 1.8 + (index * 0.1), 7.5, 3.0 + (index * 0.1)],
                    "text": (
                        f"This is fake paragraph text for page {index}. "
                        f"It simulates Docling-like block output."
                    ),
                    "label": "paragraph",
                    "order": 2,
                    "confidence": 0.90,
                },
            ],
            "tables": [],
            "formulas": [],
            "images": [],
        }


# ---------------------------------------------------------------------------
# Real Docling provider (capability contract only)
# ---------------------------------------------------------------------------


class DoclingProvider:
    """Docling parser provider — capability contract.

    This class defines the contract that a real Docling integration would
    satisfy.  It is NOT implemented — it raises ``ParseUnavailableError``
    until the dependency is approved and the implementation is completed.

    To activate:
    1. Get dependency approval for docling.
    2. Install docling in the target environment.
    3. Implement the real ``parse`` method using the Docling API.
    4. Register ``DoclingProvider`` instead of ``DoclingFakeProvider``.
    """

    name = "docling"
    version = "1.0.0"
    capabilities = ParserCapabilities(
        supported_formats=("pdf", "pptx", "docx", "image"),
        supports_tables=True,
        supports_formulas=True,
        supports_reading_order=True,
        supports_heading_detection=True,
        supports_visual_assets=True,
        supports_coordinates=True,
        supports_provenance=True,
        requires_network=False,
        max_file_size_bytes=500 * 1024 * 1024,
        max_pages=500,
    )

    def __init__(self) -> None:
        if not HAS_DOCLING:
            self._available = False
        else:
            self._available = True

    async def parse(
        self,
        source: SourceArtifact,
        plan: ParsePlan,
    ) -> ParserOutput:
        """Parse a document using Docling.

        Raises:
            ParseUnavailableError: Always — real Docling needs dependency approval.
        """
        if not self._available:
            raise ParseUnavailableError(
                "Real Docling provider is not available. "
                "Docling is not installed.  To use: "
                "1. Get dependency approval. "
                "2. Install docling. "
                "3. Implement the real parse method."
            )

        # When real Docling is available and implemented, this would:
        # 1. Convert source data to a format Docling can read
        # 2. Call docling's pipeline
        # 3. Map the output to ParserOutput
        # 4. Return structured page data
        raise ParseUnavailableError(
            "Real Docling parse is not yet implemented. "
            "Use DoclingFakeProvider for testing."
        )


# ---------------------------------------------------------------------------
# IR mapper helper
# ---------------------------------------------------------------------------


def map_docling_output_to_ir(
    output: ParserOutput,
    source: SourceArtifact,
    run_id: str,
    parser_run_id: str,
    normalization_version: str = "1",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Map Docling ParserOutput to DocumentIR block/unit/asset dicts.

    Args:
        output: The ParserOutput from a Docling provider.
        source: The source artifact.
        run_id: The pipeline run ID.
        parser_run_id: The parser run ID.
        normalization_version: Normalization version for stable IDs.

    Returns:
        Tuple of (blocks, units, assets) as dicts.
    """
    from ..contracts import CURRENT_SCHEMA_VERSION
    from ..document_ir.models import (
        compute_document_id, compute_unit_id,
        ContentBlock, DocumentUnit, Provenance, UnitType,
    )

    doc_id = compute_document_id(
        artifact_id=source.artifact_id,
        schema_version=CURRENT_SCHEMA_VERSION.serialize(),
        normalization_version=normalization_version,
    )

    blocks: List[Dict[str, Any]] = []
    units: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []

    for page_dict in output.pages:
        page_no = page_dict.get("page_no", 0)
        unit_id = compute_unit_id(
            document_id=doc_id,
            unit_type="page",
            index=page_no,
            normalization_version=normalization_version,
        )

        block_ids: List[str] = []
        page_blocks = page_dict.get("blocks", [])

        for b_idx, block in enumerate(page_blocks):
            block_id = f"blk_docling_p{page_no}_b{b_idx}"

            text = block.get("text", "")
            label = block.get("label", "paragraph")

            # Map Docling label to block_type
            block_type = _docling_label_to_block_type(label)

            heading_level = None
            if block_type in ("heading", "title"):
                heading_level = 1 if block_type == "title" else 2

            bbox = None
            raw_bbox = block.get("bbox")
            if raw_bbox and len(raw_bbox) == 4:
                from ..contracts import BoundingBox, CoordinateSpace
                page_width = page_dict.get("width", 8.5)
                page_height = page_dict.get("height", 11.0)
                try:
                    bbox = BoundingBox(
                        x0=round(raw_bbox[0] / page_width, 6),
                        y0=round(raw_bbox[1] / page_height, 6),
                        x1=round(raw_bbox[2] / page_width, 6),
                        y1=round(raw_bbox[3] / page_height, 6),
                        coordinate_space=CoordinateSpace.NORMALIZED,
                    )
                except (ValueError, ZeroDivisionError):
                    bbox = None

            provenance = Provenance(
                artifact_id=source.artifact_id,
                run_id=run_id,
                parser_run_id=parser_run_id,
                provider=output.provider,
                raw_locator=f"pages/{page_no}/blocks/{b_idx}",
                page_or_slide=page_no,
                bbox=bbox,
                confidence=block.get("confidence"),
            )

            content_block = ContentBlock(
                block_id=block_id,
                page_or_slide=page_no,
                bbox=bbox,
                reading_order=block.get("order"),
                block_type=block_type,
                heading_level=heading_level,
                text=text or None,
                confidence=block.get("confidence"),
                provider=output.provider,
                provenance=(provenance,),
            )
            blocks.append(content_block.to_dict())
            block_ids.append(block_id)

        # Create unit
        unit = DocumentUnit(
            unit_id=unit_id,
            unit_type=UnitType.PAGE,
            index=page_no,
            width=page_dict.get("width"),
            height=page_dict.get("height"),
            coordinate_unit=page_dict.get("coordinate_unit", "inch"),
            block_ids=tuple(block_ids),
            provenance=(
                Provenance(
                    artifact_id=source.artifact_id,
                    run_id=run_id,
                    parser_run_id=parser_run_id,
                    provider=output.provider,
                    raw_locator=f"pages/{page_no}",
                    page_or_slide=page_no,
                ),
            ),
        )
        units.append(unit.to_dict())

    return blocks, units, assets


def _docling_label_to_block_type(label: str) -> str:
    """Map a Docling item label to a DocumentIR BlockType value."""
    mapping = {
        "title": "title",
        "heading": "heading",
        "paragraph": "paragraph",
        "list-item": "list_item",
        "caption": "caption",
        "footnote": "footnote",
        "header": "header",
        "footer": "footer",
        "code": "code",
        "quote": "quote",
        "table": "table",
        "formula": "formula",
        "figure": "image",
        "picture": "image",
        "chart": "chart",
        "diagram": "diagram",
    }
    return mapping.get(label.lower(), "unknown")
