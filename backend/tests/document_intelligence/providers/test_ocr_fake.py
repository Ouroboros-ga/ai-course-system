"""Tests for OcrFakeProvider and OcrProvider capability contract."""

import pytest

from app.platform.document_intelligence.providers.ocr_fake import (
    OcrFakeProvider,
    OcrProvider,
)
from app.platform.document_intelligence.registry import (
    ParseUnavailableError,
    ParserCapabilities,
)
from app.platform.document_intelligence.planner import (
    ParsePlan,
    ParseStep,
    ParsePriority,
)
from app.platform.document_intelligence.source_artifact import SourceArtifact


class TestOcrFakeProvider:
    """OcrFakeProvider contract tests."""

    @pytest.fixture
    def provider(self) -> OcrFakeProvider:
        return OcrFakeProvider()

    @pytest.fixture
    def sample_source(self) -> SourceArtifact:
        return SourceArtifact.from_bytes(
            b"mock image data",
            "page.png",
            "image/png",
        )

    def test_provider_name(self, provider: OcrFakeProvider) -> None:
        assert provider.name == "ocr-fake"

    def test_provider_version(self, provider: OcrFakeProvider) -> None:
        assert provider.version == "1.0.0-fake"

    def test_capabilities(self, provider: OcrFakeProvider) -> None:
        caps = provider.capabilities
        assert caps.supports_ocr is True
        assert caps.supports_coordinates is True

    def test_parse_returns_pages(self, provider: OcrFakeProvider,
                                  sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        assert result.provider == "ocr-fake"
        assert len(result.pages) >= 1

    def test_parse_has_text_blocks(self, provider: OcrFakeProvider,
                                    sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        for page in result.pages:
            assert "text_blocks" in page
            assert len(page["text_blocks"]) >= 1
            block = page["text_blocks"][0]
            assert "bbox" in block
            assert "text" in block
            assert "confidence" in block

    def test_parse_fake_warning(self, provider: OcrFakeProvider,
                                 sample_source: SourceArtifact) -> None:
        import asyncio
        plan = ParsePlan(artifact_id=sample_source.artifact_id)
        result = asyncio.run(provider.parse(sample_source, plan))
        assert len(result.warnings) >= 1
        assert "fake" in result.warnings[0].lower()

    def test_parse_respects_target_pages(self, provider: OcrFakeProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"image data", "page.png", "image/png",
        )
        plan = ParsePlan(
            artifact_id=source.artifact_id,
            steps=(
                ParseStep(
                    provider_name="ocr-fake",
                    priority=ParsePriority.ENRICHMENT,
                    config={"pages": [1, 3, 5]},
                ),
            ),
        )
        result = asyncio.run(provider.parse(source, plan))
        assert result.metadata.get("target_pages") == [1, 3, 5]


class TestOcrProvider:
    """OcrProvider capability contract tests."""

    @pytest.fixture
    def provider(self) -> OcrProvider:
        return OcrProvider()

    def test_provider_name(self, provider: OcrProvider) -> None:
        assert provider.name == "paddleocr"

    def test_capabilities(self, provider: OcrProvider) -> None:
        caps = provider.capabilities
        assert caps.supports_ocr is True
        assert caps.requires_gpu is True

    def test_parse_raises_unavailable(self, provider: OcrProvider) -> None:
        import asyncio
        source = SourceArtifact.from_bytes(
            b"test", "test.png", "image/png",
        )
        plan = ParsePlan(artifact_id=source.artifact_id)
        with pytest.raises(ParseUnavailableError):
            asyncio.run(provider.parse(source, plan))
