"""Parsing quality decisions — distinguishing quality failure from runtime failure.

Defines ``QualityDecision``, fallback reasons, ``needs_review`` logic, and
the quality-scoring engine that evaluates DocumentIR against configurable
thresholds.

Runtime failure (timeout, unavailable, malformed) is handled by the provider
and registry layers.  This module focuses on **quality failure**: the parse
technically succeeded but the output is low-confidence, partial, or
needs human review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from .document_ir.models import DocumentIR, QualityReport, WarningSeverity


# ---------------------------------------------------------------------------
# QualityDecision
# ---------------------------------------------------------------------------


class QualityVerdict(str, Enum):
    """Overall quality verdict for a parse result."""

    PASS = "pass"                    # Quality meets all thresholds
    BORDERLINE = "borderline"        # Below some thresholds but usable
    NEEDS_REVIEW = "needs_review"    # Quality too low; human review needed
    FAIL = "fail"                    # Quality unacceptably low


class FallbackReason(str, Enum):
    """Standardized reasons for quality-driven fallback or review."""

    TEXT_COVERAGE_TOO_LOW = "text_coverage_too_low"
    EMPTY_UNITS = "empty_units"
    DUPLICATE_BLOCKS = "duplicate_blocks"
    READING_ORDER_POOR = "reading_order_poor"
    HEADING_CONFIDENCE_LOW = "heading_confidence_low"
    TABLE_COVERAGE_LOW = "table_coverage_low"
    FORMULA_COVERAGE_LOW = "formula_coverage_low"
    OCR_CONFIDENCE_LOW = "ocr_confidence_low"
    MISSING_COORDINATES = "missing_coordinates"
    MISSING_PROVENANCE = "missing_provenance"
    HIGH_OCR_RATIO = "high_ocr_ratio"
    TOO_MANY_WARNINGS = "too_many_warnings"
    UNRESOLVED_CONFLICTS = "unresolved_conflicts"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    MALFORMED = "malformed"
    NO_PARSEABLE_CONTENT = "no_parseable_content"
    PARTIAL_RESULT = "partial_result"
    BUDGET_EXCEEDED = "budget_exceeded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QualityDecision:
    """Decision about the quality of a parse result.

    Distinguishes quality failure from runtime failure.  A ``PASS`` or
    ``BORDERLINE`` verdict means the parse succeeded with acceptable quality.
    ``NEEDS_REVIEW`` means the output should not be used without human review.
    ``FAIL`` means the output should be discarded.
    """

    verdict: QualityVerdict
    overall_score: float = 0.0
    reasons: Tuple[FallbackReason, ...] = field(default_factory=tuple)
    details: Dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False
    is_quality_failure: bool = False
    is_runtime_failure: bool = False

    @classmethod
    def runtime_failure(
        cls,
        reason: FallbackReason,
        message: str = "",
    ) -> "QualityDecision":
        """Create a decision for a runtime failure (timeout, unavailable, etc.)."""
        return cls(
            verdict=QualityVerdict.FAIL,
            overall_score=0.0,
            reasons=(reason,),
            details={"message": message},
            is_runtime_failure=True,
        )

    @classmethod
    def quality_failure(
        cls,
        reasons: List[FallbackReason],
        overall_score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> "QualityDecision":
        """Create a decision for a quality failure (low coverage, etc.)."""
        return cls(
            verdict=QualityVerdict.FAIL,
            overall_score=overall_score,
            reasons=tuple(reasons),
            details=details or {},
            is_quality_failure=True,
        )

    @classmethod
    def needs_review_decision(
        cls,
        reasons: List[FallbackReason],
        overall_score: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> "QualityDecision":
        """Create a decision that requires human review."""
        return cls(
            verdict=QualityVerdict.NEEDS_REVIEW,
            overall_score=overall_score,
            reasons=tuple(reasons),
            details=details or {},
            needs_review=True,
        )


# ---------------------------------------------------------------------------
# Quality thresholds (initial proposed values)
# ---------------------------------------------------------------------------

DEFAULT_QUALITY_THRESHOLDS: Dict[str, float] = {
    "text_coverage_min": 0.85,
    "empty_unit_ratio_max": 0.05,
    "duplicate_ratio_max": 0.08,
    "reading_order_confidence_min": 0.70,
    "heading_confidence_min": 0.70,
    "table_coverage_min": 0.70,
    "formula_coverage_min": 0.70,
    "ocr_confidence_min": 0.75,
    "ocr_ratio_max": 0.50,
    "overall_score_min": 0.60,
}

BORDERLINE_THRESHOLDS: Dict[str, float] = {
    "text_coverage_min": 0.70,
    "overall_score_min": 0.40,
}


# ---------------------------------------------------------------------------
# QualityScorer
# ---------------------------------------------------------------------------


class QualityScorer:
    """Evaluates DocumentIR quality against configured thresholds.

    Produces a ``QualityDecision`` that distinguishes acceptable quality
    from quality failure and identifies specific reasons for falling
    below thresholds.
    """

    def __init__(
        self,
        thresholds: Optional[Dict[str, float]] = None,
        scorer_version: str = "quality/1.0.0",
    ) -> None:
        self._thresholds = dict(DEFAULT_QUALITY_THRESHOLDS)
        if thresholds:
            self._thresholds.update(thresholds)
        self._borderline = dict(BORDERLINE_THRESHOLDS)
        self._scorer_version = scorer_version

    def evaluate(self, doc: DocumentIR) -> QualityDecision:
        """Evaluate the quality of a parsed DocumentIR.

        Args:
            doc: The DocumentIR to evaluate.

        Returns:
            A QualityDecision with verdict, score, and reasons.
        """
        reasons: List[FallbackReason] = []
        quality = doc.quality or QualityReport()

        # Compute overall score from available metrics
        scores: List[float] = []
        if quality.text_coverage is not None:
            scores.append(quality.text_coverage)
        if quality.reading_order_confidence is not None:
            scores.append(quality.reading_order_confidence)
        if quality.heading_confidence is not None:
            scores.append(quality.heading_confidence)
        if quality.formula_coverage is not None:
            scores.append(quality.formula_coverage)
        if quality.table_coverage is not None:
            scores.append(quality.table_coverage)
        if quality.visual_coverage is not None:
            scores.append(quality.visual_coverage)
        if quality.overall_score is not None:
            scores.append(quality.overall_score)

        overall = sum(scores) / max(len(scores), 1) if scores else 0.0

        # Check each threshold
        tc = quality.text_coverage
        if tc is not None and tc < self._thresholds["text_coverage_min"]:
            reasons.append(FallbackReason.TEXT_COVERAGE_TOO_LOW)

        eur = quality.empty_unit_ratio
        if eur is not None and eur > self._thresholds["empty_unit_ratio_max"]:
            reasons.append(FallbackReason.EMPTY_UNITS)

        dr = quality.duplicate_ratio
        if dr is not None and dr > self._thresholds["duplicate_ratio_max"]:
            reasons.append(FallbackReason.DUPLICATE_BLOCKS)

        roc = quality.reading_order_confidence
        if roc is not None and roc < self._thresholds["reading_order_confidence_min"]:
            reasons.append(FallbackReason.READING_ORDER_POOR)

        hc = quality.heading_confidence
        if hc is not None and hc < self._thresholds["heading_confidence_min"]:
            reasons.append(FallbackReason.HEADING_CONFIDENCE_LOW)

        tc_val = quality.table_coverage
        if tc_val is not None and tc_val < self._thresholds["table_coverage_min"]:
            reasons.append(FallbackReason.TABLE_COVERAGE_LOW)

        fc = quality.formula_coverage
        if fc is not None and fc < self._thresholds["formula_coverage_min"]:
            reasons.append(FallbackReason.FORMULA_COVERAGE_LOW)

        ocr_ratio = quality.ocr_ratio
        if ocr_ratio is not None and ocr_ratio > self._thresholds["ocr_ratio_max"]:
            reasons.append(FallbackReason.HIGH_OCR_RATIO)

        # Check hard failures
        if quality.hard_failures:
            reasons.append(FallbackReason.UNRESOLVED_CONFLICTS)

        # Check warnings
        if len(doc.warnings) > 10:
            reasons.append(FallbackReason.TOO_MANY_WARNINGS)

        # Check for missing data
        has_blocks = len(doc.blocks) > 0
        has_units = len(doc.units) > 0
        if not has_blocks or not has_units:
            reasons.append(FallbackReason.NO_PARSEABLE_CONTENT)

        # Determine verdict
        verdict, needs_review, is_quality_failure = self._decide_verdict(
            overall, reasons
        )

        return QualityDecision(
            verdict=verdict,
            overall_score=round(overall, 4),
            reasons=tuple(reasons),
            details={
                "scorer_version": self._scorer_version,
                "thresholds": dict(self._thresholds),
            },
            needs_review=needs_review,
            is_quality_failure=is_quality_failure,
        )

    def _decide_verdict(
        self,
        overall_score: float,
        reasons: List[FallbackReason],
    ) -> Tuple[QualityVerdict, bool, bool]:
        """Determine verdict from score and reasons."""
        if overall_score >= self._thresholds["overall_score_min"] and not reasons:
            return QualityVerdict.PASS, False, False

        if overall_score >= self._borderline["overall_score_min"]:
            if len(reasons) <= 2:
                return QualityVerdict.BORDERLINE, False, False
            return QualityVerdict.NEEDS_REVIEW, True, False

        return QualityVerdict.FAIL, False, True

    def needs_review(self, doc: DocumentIR) -> bool:
        """Quick check: does this document need human review?"""
        decision = self.evaluate(doc)
        return decision.needs_review

    def should_fallback(self, doc: DocumentIR) -> bool:
        """Quick check: should an alternative provider be tried?"""
        decision = self.evaluate(doc)
        return decision.is_quality_failure or decision.verdict == QualityVerdict.FAIL
