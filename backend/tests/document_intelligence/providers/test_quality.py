"""Tests for QualityDecision, QualityScorer, fallback reasons."""

import pytest

from app.platform.document_intelligence.quality import (
    QualityDecision,
    QualityScorer,
    QualityVerdict,
    FallbackReason,
    DEFAULT_QUALITY_THRESHOLDS,
)
from app.platform.document_intelligence.document_ir.models import (
    DocumentIR,
    QualityReport,
    ParseWarning,
    WarningSeverity,
    ContentBlock,
    DocumentUnit,
    UnitType,
)


class TestQualityDecision:
    """QualityDecision creation and properties."""

    def test_runtime_failure(self) -> None:
        decision = QualityDecision.runtime_failure(
            reason=FallbackReason.TIMEOUT,
            message="Parser timed out after 60s",
        )
        assert decision.verdict == QualityVerdict.FAIL
        assert decision.is_runtime_failure
        assert not decision.is_quality_failure
        assert FallbackReason.TIMEOUT in decision.reasons

    def test_quality_failure(self) -> None:
        decision = QualityDecision.quality_failure(
            reasons=[FallbackReason.TEXT_COVERAGE_TOO_LOW],
            overall_score=0.3,
        )
        assert decision.verdict == QualityVerdict.FAIL
        assert decision.is_quality_failure
        assert not decision.is_runtime_failure

    def test_needs_review_decision(self) -> None:
        decision = QualityDecision.needs_review_decision(
            reasons=[FallbackReason.PARTIAL_RESULT],
            overall_score=0.5,
        )
        assert decision.verdict == QualityVerdict.NEEDS_REVIEW
        assert decision.needs_review is True

    def test_pass_decision(self) -> None:
        decision = QualityDecision(
            verdict=QualityVerdict.PASS,
            overall_score=0.95,
        )
        assert decision.verdict == QualityVerdict.PASS
        assert not decision.needs_review
        assert not decision.is_quality_failure
        assert not decision.is_runtime_failure


class TestQualityScorer:
    """QualityScorer evaluation logic."""

    @pytest.fixture
    def scorer(self) -> QualityScorer:
        return QualityScorer()

    @pytest.fixture
    def high_quality_doc(self) -> DocumentIR:
        """Document with high quality metrics."""
        return DocumentIR(
            document_id="doc_high",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                overall_score=0.95,
                text_coverage=0.95,
                reading_order_confidence=0.95,
                heading_confidence=0.95,
                empty_unit_ratio=0.0,
                duplicate_ratio=0.0,
            ),
        )

    @pytest.fixture
    def low_quality_doc(self) -> DocumentIR:
        """Document with poor quality metrics."""
        return DocumentIR(
            document_id="doc_low",
            units=(),
            blocks=(),
            quality=QualityReport(
                overall_score=0.15,
                text_coverage=0.10,
                reading_order_confidence=0.20,
                empty_unit_ratio=0.8,
                duplicate_ratio=0.3,
            ),
            warnings=(
                ParseWarning(
                    code="WARN_1",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 1",
                ),
                ParseWarning(
                    code="WARN_2",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 2",
                ),
                ParseWarning(
                    code="WARN_3",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 3",
                ),
                ParseWarning(
                    code="WARN_4",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 4",
                ),
                ParseWarning(
                    code="WARN_5",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 5",
                ),
                ParseWarning(
                    code="WARN_6",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 6",
                ),
                ParseWarning(
                    code="WARN_7",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 7",
                ),
                ParseWarning(
                    code="WARN_8",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 8",
                ),
                ParseWarning(
                    code="WARN_9",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 9",
                ),
                ParseWarning(
                    code="WARN_10",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 10",
                ),
                ParseWarning(
                    code="WARN_11",
                    severity=WarningSeverity.WARNING,
                    message="Test warning 11",
                ),
            ),
        )

    @pytest.fixture
    def borderline_doc(self) -> DocumentIR:
        """Document with borderline quality."""
        return DocumentIR(
            document_id="doc_border",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                overall_score=0.50,
                text_coverage=0.75,
                empty_unit_ratio=0.0,
                duplicate_ratio=0.0,
            ),
        )

    def test_high_quality_passes(self, scorer: QualityScorer,
                                  high_quality_doc: DocumentIR) -> None:
        decision = scorer.evaluate(high_quality_doc)
        assert decision.verdict == QualityVerdict.PASS
        assert decision.overall_score >= 0.9
        assert len(decision.reasons) == 0

    def test_low_quality_fails(self, scorer: QualityScorer,
                                low_quality_doc: DocumentIR) -> None:
        decision = scorer.evaluate(low_quality_doc)
        assert decision.verdict == QualityVerdict.FAIL
        assert decision.is_quality_failure
        assert len(decision.reasons) >= 1

    def test_borderline_quality(self, scorer: QualityScorer,
                                 borderline_doc: DocumentIR) -> None:
        decision = scorer.evaluate(borderline_doc)
        # Borderline: score 0.5 >= 0.4, but text_coverage 0.75 < 0.85
        assert decision.verdict in (QualityVerdict.BORDERLINE, QualityVerdict.NEEDS_REVIEW)

    def test_needs_review_quick_check(self, scorer: QualityScorer,
                                       low_quality_doc: DocumentIR) -> None:
        # FAIL docs should NOT need review (they need fallback instead)
        assert scorer.needs_review(low_quality_doc) is False

    def test_should_fallback_quick_check(self, scorer: QualityScorer,
                                          low_quality_doc: DocumentIR) -> None:
        assert scorer.should_fallback(low_quality_doc) is True

    def test_high_quality_does_not_need_review(self, scorer: QualityScorer,
                                                high_quality_doc: DocumentIR) -> None:
        assert scorer.needs_review(high_quality_doc) is False
        assert scorer.should_fallback(high_quality_doc) is False

    def test_text_coverage_below_threshold(self, scorer: QualityScorer) -> None:
        doc = DocumentIR(
            document_id="doc",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                text_coverage=0.30,
                overall_score=0.60,
            ),
        )
        decision = scorer.evaluate(doc)
        assert FallbackReason.TEXT_COVERAGE_TOO_LOW in decision.reasons

    def test_empty_units_above_threshold(self, scorer: QualityScorer) -> None:
        doc = DocumentIR(
            document_id="doc",
            units=(),
            blocks=(),
            quality=QualityReport(
                empty_unit_ratio=0.5,
                overall_score=0.60,
            ),
        )
        decision = scorer.evaluate(doc)
        reasons = set(decision.reasons)
        assert FallbackReason.EMPTY_UNITS in reasons
        assert FallbackReason.NO_PARSEABLE_CONTENT in reasons

    def test_duplicate_blocks_detected(self, scorer: QualityScorer) -> None:
        doc = DocumentIR(
            document_id="doc",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                duplicate_ratio=0.3,
                overall_score=0.60,
            ),
        )
        decision = scorer.evaluate(doc)
        assert FallbackReason.DUPLICATE_BLOCKS in decision.reasons

    def test_hard_failures_detected(self, scorer: QualityScorer) -> None:
        doc = DocumentIR(
            document_id="doc",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                hard_failures=["RECONCILIATION_FAILURE"],
                overall_score=0.60,
            ),
        )
        decision = scorer.evaluate(doc)
        assert FallbackReason.UNRESOLVED_CONFLICTS in decision.reasons

    def test_custom_thresholds(self) -> None:
        custom_scorer = QualityScorer(thresholds={"text_coverage_min": 0.95})
        doc = DocumentIR(
            document_id="doc",
            units=(
                DocumentUnit(unit_id="u1", unit_type=UnitType.PAGE, index=1),
            ),
            blocks=(
                ContentBlock(block_id="b1", text="Hello"),
            ),
            quality=QualityReport(
                text_coverage=0.90,
                overall_score=0.90,
            ),
        )
        decision = custom_scorer.evaluate(doc)
        assert FallbackReason.TEXT_COVERAGE_TOO_LOW in decision.reasons

    def test_scorer_version_in_details(self, scorer: QualityScorer,
                                        high_quality_doc: DocumentIR) -> None:
        decision = scorer.evaluate(high_quality_doc)
        assert decision.details["scorer_version"] == "quality/1.0.0"
