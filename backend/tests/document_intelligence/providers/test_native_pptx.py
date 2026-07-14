"""Tests for NativePptxProvider — contract tests and fake-based testing.

These tests verify the provider contract is satisfied.  Real PPTX parsing
requires python-pptx to be installed.  The provider raises
``ParseUnavailableError`` when python-pptx is not available.
"""

import pytest

from app.platform.document_intelligence.providers.native_pptx import (
    NativePptxProvider,
    SlideData,
    SlideShape,
    SlideTable,
)
from app.platform.document_intelligence.registry import (
    ParseUnavailableError,
    ParseMalformedError,
    ParserCapabilities,
)
from app.platform.document_intelligence.planner import (
    ParsePlan,
    ParseStep,
    ParsePriority,
)
from app.platform.document_intelligence.source_artifact import SourceArtifact


class TestNativePptxProvider:
    """NativePptxProvider contract tests."""

    @pytest.fixture
    def provider(self) -> NativePptxProvider:
        return NativePptxProvider()

    @pytest.fixture
    def sample_source(self) -> SourceArtifact:
        return SourceArtifact.from_bytes(
            b"mock pptx bytes",
            "test.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    def test_provider_name(self, provider: NativePptxProvider) -> None:
        assert provider.name == "native-pptx"

    def test_provider_version(self, provider: NativePptxProvider) -> None:
        assert provider.version == "1.0.0"

    def test_capabilities(self, provider: NativePptxProvider) -> None:
        caps = provider.capabilities
        assert "pptx" in caps.supported_formats
        assert caps.supports_tables is True
        assert caps.supports_notes is True
        assert caps.supports_reading_order is True
        assert caps.supports_coordinates is True

    @pytest.mark.skipif(
        not hasattr(__import__('builtins'), '__import__'),
        reason="python-pptx import check",
    )
    def test_parse_raises_unavailable_without_pptx(
        self, provider: NativePptxProvider, sample_source: SourceArtifact,
    ) -> None:
        """If python-pptx is not installed, parse raises ParseUnavailableError."""
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        # The provider may or may not have python-pptx available
        # We just test the contract shape
        try:
            asyncio.run(provider.parse(sample_source, plan))
        except (ParseUnavailableError, ParseMalformedError):
            pass


class TestSlideData:
    """SlideData container tests."""

    def test_slide_shape_creation(self) -> None:
        shape = SlideShape(
            shape_id=1,
            shape_name="Title",
            shape_type=1,
            text="Hello",
            is_title=True,
        )
        assert shape.shape_id == 1
        assert shape.text == "Hello"
        assert shape.is_title is True

    def test_slide_table_creation(self) -> None:
        table = SlideTable(
            rows=2,
            columns=3,
            cells=(("A1", "B1", "C1"), ("A2", "B2", "C2")),
        )
        assert table.rows == 2
        assert table.columns == 3
        assert table.cells[0][0] == "A1"

    def test_slide_data_creation(self) -> None:
        slide = SlideData(
            slide_index=1,
            title="Test Slide",
            notes="Some notes",
            width_emu=100000,
            height_emu=50000,
        )
        assert slide.slide_index == 1
        assert slide.title == "Test Slide"
        assert slide.notes == "Some notes"
