"""Tests for DoclingFakeProvider and DoclingProvider capability contract."""

import pytest

from app.platform.document_intelligence.providers.docling_fake import (
    DoclingFakeProvider,
    DoclingProvider,
    _docling_label_to_block_type,
)
from app.platform.document_intelligence.registry import (
    ParseUnavailableError,
    ParseTimeoutError,
    ParserCapabilities,
)
from app.platform.document_intelligence.planner import (
    ParsePlan,
    ParseStep,
    ParsePriority,
)
from app.platform.document_intelligence.source_artifact import SourceArtifact


class TestDoclingFakeProvider:
    """DoclingFakeProvider contract tests."""

    @pytest.fixture
    def provider(self) -> DoclingFakeProvider:
        return DoclingFakeProvider()

    @pytest.fixture
    def sample_source(self) -> SourceArtifact:
        return SourceArtifact.from_bytes(
            b"mock pdf content for testing",
            "test.pdf",
            "application/pdf",
        )

    def test_provider_name(self, provider: DoclingFakeProvider) -> None:
        assert provider.name == "docling-fake"

    def test_provider_version(self, provider: DoclingFakeProvider) -> None:
        assert provider.version == "1.0.0-fake"

    def test_capabilities(self, provider: DoclingFakeProvider) -> None:
        caps = provider.capabilities
        assert "pdf" in caps.supported_formats
        assert "pptx" in caps.supported_formats
        assert "docx" in caps.supported_formats
        assert "image" in caps.supported_formats
        assert caps.supports_tables is True
        assert caps.supports_reading_order is True
        assert caps.supports_coordinates is True

    def test_is_real_false(self, provider: DoclingFakeProvider) -> None:
        assert provider.is_real is False

    def test_parse_returns_pages(self, provider: DoclingFakeProvider,
                                  sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        assert result.provider == "docling-fake"
        assert len(result.pages) >= 1
        assert result.metadata.get("is_fake") is True

    def test_parse_generates_fake_warning(self, provider: DoclingFakeProvider,
                                           sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        assert len(result.warnings) >= 1
        assert "fake" in result.warnings[0].lower()

    def test_parse_pdf_source(self, provider: DoclingFakeProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"pdf content", "doc.pdf", "application/pdf",
        )
        plan = ParsePlan(artifact_id=source.artifact_id)
        result = asyncio.run(provider.parse(source, plan))
        assert len(result.pages) >= 1

    def test_parse_pptx_source(self, provider: DoclingFakeProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"pptx content" * 2000,
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
        plan = ParsePlan(artifact_id=source.artifact_id)
        result = asyncio.run(provider.parse(source, plan))
        assert len(result.pages) >= 1

    def test_parse_image_source(self, provider: DoclingFakeProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"image data", "photo.png", "image/png",
        )
        plan = ParsePlan(artifact_id=source.artifact_id)
        result = asyncio.run(provider.parse(source, plan))
        assert len(result.pages) == 1

    def test_parse_page_structure(self, provider: DoclingFakeProvider,
                                   sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        page = result.pages[0]
        assert "page_no" in page
        assert "blocks" in page
        assert len(page["blocks"]) >= 1

    def test_parse_blocks_have_required_fields(
        self, provider: DoclingFakeProvider, sample_source: SourceArtifact,
    ) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        for page in result.pages:
            for block in page.get("blocks", []):
                assert "bbox" in block
                assert "text" in block
                assert "label" in block
                assert "confidence" in block


class TestDoclingProvider:
    """DoclingProvider capability contract tests."""

    @pytest.fixture
    def provider(self) -> DoclingProvider:
        return DoclingProvider()

    def test_provider_name(self, provider: DoclingProvider) -> None:
        assert provider.name == "docling"

    def test_provider_version(self, provider: DoclingProvider) -> None:
        assert provider.version == "1.0.0"

    def test_capabilities(self, provider: DoclingProvider) -> None:
        caps = provider.capabilities
        assert "pdf" in caps.supported_formats
        assert caps.supports_tables is True
        assert caps.supports_formulas is True

    def test_parse_raises_unavailable(self, provider: DoclingProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"test", "test.pdf", "application/pdf",
        )
        plan = ParsePlan(artifact_id=source.artifact_id)
        with pytest.raises(ParseUnavailableError):
            asyncio.run(provider.parse(source, plan))


class TestDoclingLabelMapping:
    """Docling label to BlockType mapping."""

    def test_title_mapping(self) -> None:
        assert _docling_label_to_block_type("title") == "title"

    def test_heading_mapping(self) -> None:
        assert _docling_label_to_block_type("heading") == "heading"

    def test_paragraph_mapping(self) -> None:
        assert _docling_label_to_block_type("paragraph") == "paragraph"

    def test_list_item_mapping(self) -> None:
        assert _docling_label_to_block_type("list-item") == "list_item"

    def test_figure_mapping(self) -> None:
        assert _docling_label_to_block_type("figure") == "image"

    def test_table_mapping(self) -> None:
        assert _docling_label_to_block_type("table") == "table"

    def test_formula_mapping(self) -> None:
        assert _docling_label_to_block_type("formula") == "formula"

    def test_unknown_label(self) -> None:
        assert _docling_label_to_block_type("unknown_label") == "unknown"

    def test_case_insensitive(self) -> None:
        assert _docling_label_to_block_type("Heading") == "heading"
