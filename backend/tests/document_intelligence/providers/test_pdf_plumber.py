"""Tests for PdfPlumberProvider — real PDF parser.

P1-3: Validates that the real pdfplumber-backed provider:
1. Reports correct capabilities (no fake flag).
2. Raises ParseUnavailableError when pdfplumber is missing (no fake output).
3. Maps real output to DocumentIR blocks via map_pdf_plumber_output_to_ir.
"""
from __future__ import annotations

import pytest

from app.platform.document_intelligence.providers.pdf_plumber import (
    PdfPlumberProvider,
    HAS_PDFPLUMBER,
    map_pdf_plumber_output_to_ir,
)
from app.platform.document_intelligence.registry import (
    ParseUnavailableError,
    ParserOutput,
)
from app.platform.document_intelligence.planner import ParsePlan
from app.platform.document_intelligence.source_artifact import SourceArtifact


class TestPdfPlumberProviderContract:
    """Provider contract — passes regardless of whether pdfplumber installed."""

    @pytest.fixture
    def provider(self) -> PdfPlumberProvider:
        return PdfPlumberProvider()

    def test_provider_name(self, provider: PdfPlumberProvider) -> None:
        assert provider.name == "pdf-plumber"

    def test_provider_version(self, provider: PdfPlumberProvider) -> None:
        assert provider.version == "1.0.0"

    def test_is_real_true(self, provider: PdfPlumberProvider) -> None:
        """P1-3 hard requirement: real providers must not claim to be fake."""
        assert provider.is_real is True

    def test_supports_pdf_only(self, provider: PdfPlumberProvider) -> None:
        assert "pdf" in provider.capabilities.supported_formats
        assert "pptx" not in provider.capabilities.supported_formats
        assert "image" not in provider.capabilities.supported_formats

    def test_capabilities_no_ocr(self, provider: PdfPlumberProvider) -> None:
        """PDF text-layer parser must NOT claim OCR capability."""
        assert provider.capabilities.supports_ocr is False


class TestPdfPlumberAvailability:
    """Behavior when pdfplumber is / is not installed."""

    @pytest.fixture
    def plan(self) -> ParsePlan:
        return ParsePlan(steps=(), artifact_id="art_test")

    @pytest.fixture
    def source(self) -> SourceArtifact:
        return SourceArtifact.from_bytes(
            b"%PDF-1.4 fake pdf bytes",
            filename="doc.pdf",
            mime="application/pdf",
            uri="test/doc.pdf",
        )

    def test_unavailable_raises_not_fake(self, plan: ParsePlan, source: SourceArtifact) -> None:
        """If pdfplumber missing, provider must raise — never return fake output."""
        if HAS_PDFPLUMBER:
            pytest.skip("pdfplumber is installed; unavailability path not testable")
        provider = PdfPlumberProvider()
        with pytest.raises(ParseUnavailableError):
            import asyncio
            asyncio.get_event_loop().run_until_complete(provider.parse(source, plan))


class TestMapPdfPlumberOutputToIr:
    """IR mapper unit tests — no external dependencies required."""

    def test_maps_text_blocks_to_ir_blocks(self) -> None:
        source = SourceArtifact.from_bytes(
            b"fake-pdf",
            filename="doc.pdf",
            mime="application/pdf",
        )
        output = ParserOutput(
            provider="pdf-plumber",
            provider_version="1.0.0",
            pages=(
                {
                    "page_no": 1,
                    "width": 612.0,
                    "height": 792.0,
                    "text_blocks": [
                        {
                            "bbox": [0.1, 0.1, 0.9, 0.2],
                            "text": "Heading text",
                            "confidence": 1.0,
                            "is_heading": True,
                        },
                        {
                            "bbox": [0.1, 0.3, 0.9, 0.4],
                            "text": "Paragraph body",
                            "confidence": 1.0,
                            "is_heading": False,
                        },
                    ],
                    "tables": [],
                },
            ),
            metadata={"is_fake": False},
        )

        blocks, units, assets = map_pdf_plumber_output_to_ir(
            output, source, run_id="run_1", parser_run_id="prun_1",
        )

        assert len(blocks) == 2
        assert blocks[0]["block_type"] == "heading"
        assert blocks[0]["text"] == "Heading text"
        assert blocks[0]["page_or_slide"] == 1
        assert blocks[0]["bbox"] is not None
        assert blocks[1]["block_type"] == "paragraph"
        assert blocks[1]["text"] == "Paragraph body"

    def test_maps_tables_as_table_blocks(self) -> None:
        source = SourceArtifact.from_bytes(
            b"fake-pdf",
            filename="doc.pdf",
            mime="application/pdf",
        )
        output = ParserOutput(
            provider="pdf-plumber",
            provider_version="1.0.0",
            pages=(
                {
                    "page_no": 2,
                    "width": 612.0,
                    "height": 792.0,
                    "text_blocks": [],
                    "tables": [
                        {
                            "rows": 2,
                            "columns": 2,
                            "cells": (("a", "b"), ("c", "d")),
                        },
                    ],
                },
            ),
            metadata={"is_fake": False},
        )

        blocks, _, _ = map_pdf_plumber_output_to_ir(
            output, source, run_id="run_1", parser_run_id="prun_1",
        )

        assert len(blocks) == 1
        assert blocks[0]["block_type"] == "table"
        assert "a\tb" in blocks[0]["text"]
        assert "c\td" in blocks[0]["text"]
        assert blocks[0]["page_or_slide"] == 2
        assert blocks[0]["kind"] == "table"
        assert blocks[0]["cells"][0]["row"] == 0
        assert blocks[0]["cells"][0]["col"] == 0
        assert blocks[0]["cells"][0]["header"] is True

    def test_preserves_table_and_cell_geometry(self) -> None:
        source = SourceArtifact.from_bytes(b"fake-pdf", "doc.pdf", "application/pdf")
        output = ParserOutput(
            provider="pdf-plumber",
            provider_version="1.0.0",
            pages=({
                "page_no": 1,
                "text_blocks": [],
                "tables": [{
                    "rows": 2,
                    "columns": 2,
                    "cells": (("h1", "h2"), ("a", "b")),
                    "bbox": [0.1, 0.2, 0.9, 0.6],
                    "cell_bboxes": [
                        [[0.1, 0.2, 0.5, 0.4], [0.5, 0.2, 0.9, 0.4]],
                        [[0.1, 0.4, 0.5, 0.6], [0.5, 0.4, 0.9, 0.6]],
                    ],
                }],
            },),
        )

        blocks, _, _ = map_pdf_plumber_output_to_ir(output, source, "run_1", "prun_1")

        assert blocks[0]["bbox"]["x0"] == 0.1
        assert blocks[0]["cells"][3]["bbox"]["y1"] == 0.6
        assert "warnings" not in blocks[0]

    def test_marks_geometry_less_table_for_review(self) -> None:
        source = SourceArtifact.from_bytes(b"fake-pdf", "doc.pdf", "application/pdf")
        output = ParserOutput(
            provider="pdf-plumber",
            provider_version="1.0.0",
            pages=({
                "page_no": 1,
                "text_blocks": [],
                "tables": [{
                    "rows": 1, "columns": 1, "cells": (("a",),),
                    "structure_unresolved": True,
                }],
            },),
        )

        blocks, _, _ = map_pdf_plumber_output_to_ir(output, source, "run_1", "prun_1")

        assert blocks[0]["warnings"][0]["code"] == "TABLE_STRUCTURE_UNRESOLVED"

    def test_skips_empty_tables(self) -> None:
        source = SourceArtifact.from_bytes(
            b"fake-pdf",
            filename="doc.pdf",
            mime="application/pdf",
        )
        output = ParserOutput(
            provider="pdf-plumber",
            provider_version="1.0.0",
            pages=(
                {
                    "page_no": 1,
                    "width": 612.0,
                    "height": 792.0,
                    "text_blocks": [],
                    "tables": [
                        {"rows": 0, "columns": 0, "cells": ()},
                    ],
                },
            ),
            metadata={"is_fake": False},
        )

        blocks, _, _ = map_pdf_plumber_output_to_ir(
            output, source, run_id="run_1", parser_run_id="prun_1",
        )

        assert blocks == []
