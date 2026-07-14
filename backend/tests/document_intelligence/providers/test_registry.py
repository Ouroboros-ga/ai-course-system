"""Tests for ParserProvider protocol and ParserRegistry."""

import pytest

from app.platform.document_intelligence.registry import (
    ParserCapabilities,
    ParserRegistry,
    ParseError,
    ParseTimeoutError,
    ParseUnavailableError,
    ParseMalformedError,
)
from app.platform.document_intelligence.probe import ProbeResult, DetectedFormat


class TestParserCapabilities:
    """ParserCapabilities default values and construction."""

    def test_default_capabilities(self) -> None:
        caps = ParserCapabilities()
        assert caps.supported_formats == ()
        assert caps.supports_tables is False
        assert caps.max_file_size_bytes == 500 * 1024 * 1024

    def test_custom_capabilities(self) -> None:
        caps = ParserCapabilities(
            supported_formats=("pptx",),
            supports_tables=True,
            max_file_size_bytes=100_000_000,
        )
        assert "pptx" in caps.supported_formats
        assert caps.supports_tables is True
        assert caps.max_file_size_bytes == 100_000_000


class TestParseErrors:
    """Parse error types and codes."""

    def test_parse_error_base(self) -> None:
        err = ParseError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.code == "PARSE_ERROR"

    def test_parse_error_custom_code(self) -> None:
        err = ParseError("custom", code="MY_CODE")
        assert err.code == "MY_CODE"

    def test_parse_timeout_error(self) -> None:
        err = ParseTimeoutError("timed out")
        assert err.code == "TIMEOUT"

    def test_parse_unavailable_error(self) -> None:
        err = ParseUnavailableError("not available")
        assert err.code == "UNAVAILABLE"

    def test_parse_malformed_error(self) -> None:
        err = ParseMalformedError("malformed input")
        assert err.code == "MALFORMED"


class TestParserRegistry:
    """ParserRegistry registration and lookup."""

    @pytest.fixture
    def registry(self) -> ParserRegistry:
        return ParserRegistry()

    @pytest.fixture
    def mock_provider(self):
        """Create a minimal mock provider."""
        class MockProvider:
            name = "mock-provider"
            version = "1.0.0"
            capabilities = ParserCapabilities(
                supported_formats=("pptx", "pdf"),
                supports_tables=True,
            )
            async def parse(self, source, plan):
                from app.platform.document_intelligence.registry import ParserOutput
                return ParserOutput(provider=self.name, provider_version=self.version)
        return MockProvider()

    @pytest.fixture
    def ocr_provider(self):
        """Create a mock OCR provider."""
        class OcrMockProvider:
            name = "ocr-mock"
            version = "1.0.0"
            capabilities = ParserCapabilities(
                supported_formats=("image",),
                supports_ocr=True,
            )
            async def parse(self, source, plan):
                from app.platform.document_intelligence.registry import ParserOutput
                return ParserOutput(provider=self.name, provider_version=self.version)
        return OcrMockProvider()

    def test_register_provider(self, registry: ParserRegistry,
                               mock_provider) -> None:
        registry.register(mock_provider)
        assert registry.provider_count() == 1
        assert registry.get("mock-provider") is mock_provider

    def test_register_duplicate_raises(self, registry: ParserRegistry,
                                       mock_provider) -> None:
        registry.register(mock_provider)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_provider)

    def test_unregister_provider(self, registry: ParserRegistry,
                                 mock_provider) -> None:
        registry.register(mock_provider)
        registry.unregister("mock-provider")
        assert registry.provider_count() == 0
        assert registry.get("mock-provider") is None

    def test_list_providers(self, registry: ParserRegistry,
                            mock_provider, ocr_provider) -> None:
        registry.register(mock_provider)
        registry.register(ocr_provider)
        names = registry.list_providers()
        assert "mock-provider" in names
        assert "ocr-mock" in names
        assert len(names) == 2

    def test_find_by_format(self, registry: ParserRegistry,
                            mock_provider, ocr_provider) -> None:
        registry.register(mock_provider)
        registry.register(ocr_provider)
        pptx_providers = registry.find_by_format("pptx")
        assert len(pptx_providers) == 1
        assert pptx_providers[0].name == "mock-provider"

        image_providers = registry.find_by_format("image")
        assert len(image_providers) == 1
        assert image_providers[0].name == "ocr-mock"

    def test_find_by_capability(self, registry: ParserRegistry,
                                mock_provider, ocr_provider) -> None:
        registry.register(mock_provider)
        registry.register(ocr_provider)
        table_providers = registry.find_by_capability(supports_tables=True)
        assert len(table_providers) == 1
        assert table_providers[0].name == "mock-provider"

        ocr_providers = registry.find_by_capability(supports_ocr=True)
        assert len(ocr_providers) == 1
        assert ocr_providers[0].name == "ocr-mock"

    def test_get_probe_hints(self, registry: ParserRegistry,
                             mock_provider) -> None:
        registry.register(mock_provider)
        probe = ProbeResult(detected_format=DetectedFormat.PPTX)
        hints = registry.get_probe_hints(probe)
        assert "mock-provider" in hints

    def test_get_probe_hints_empty_for_unsupported(self, registry: ParserRegistry,
                                                    mock_provider) -> None:
        registry.register(mock_provider)
        probe = ProbeResult(detected_format=DetectedFormat.IMAGE)
        hints = registry.get_probe_hints(probe)
        assert "mock-provider" not in hints

    def test_empty_registry(self, registry: ParserRegistry) -> None:
        assert registry.provider_count() == 0
        assert registry.list_providers() == []
        assert registry.get("nonexistent") is None
