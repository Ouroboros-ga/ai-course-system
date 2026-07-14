"""Tests for the parser-provider contract version constant.

Verifies that ``PARSER_PROVIDER_VERSION`` is defined in the canonical source
(``registry.py``), has the expected value ``"parser-provider/1.0"``, and
matches the contract registry declaration in
``docs/refactor/product1/contracts/registry.md``.
"""

from app.platform.document_intelligence.registry import PARSER_PROVIDER_VERSION


class TestParserProviderVersion:
    """PARSER_PROVIDER_VERSION contract identity."""

    def test_constant_defined(self) -> None:
        """The constant must be a non-empty string."""
        assert isinstance(PARSER_PROVIDER_VERSION, str)
        assert len(PARSER_PROVIDER_VERSION) > 0

    def test_expected_value(self) -> None:
        """Must match the registry declaration ``parser-provider/1.0``."""
        assert PARSER_PROVIDER_VERSION == "parser-provider/1.0"

    def test_format_two_part(self) -> None:
        """Must follow ``prefix/major.minor`` format."""
        parts = PARSER_PROVIDER_VERSION.split("/")
        assert len(parts) == 2, "Expected format: prefix/version"
        prefix, version = parts
        assert prefix == "parser-provider", f"Expected prefix 'parser-provider', got {prefix!r}"
        semver_parts = version.split(".")
        assert len(semver_parts) == 2, f"Expected major.minor, got {version!r}"
        assert all(p.isdigit() for p in semver_parts), f"Version parts must be numeric, got {version!r}"

    def test_quality_scorer_exposes_constant(self) -> None:
        """The QualityScorer must include the contract version in its details."""
        from app.platform.document_intelligence.quality import QualityScorer
        from app.platform.document_intelligence.document_ir.models import (
            DocumentIR,
            QualityReport,
        )

        scorer = QualityScorer()
        doc = DocumentIR(
            document_id="version_check",
            units=(),
            blocks=(),
            quality=QualityReport(overall_score=0.5),
        )
        decision = scorer.evaluate(doc)
        assert decision.details.get("parser_provider_version") == PARSER_PROVIDER_VERSION
