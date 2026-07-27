"""Parse planning — selecting providers and strategies based on probe results.

The ``ParsePlanner`` takes a ``ProbeResult`` and available providers, and
produces a ``ParsePlan`` that defines which providers to invoke, in which
order, with which configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# ParsePlan
# ---------------------------------------------------------------------------


class ParsePriority(str, Enum):
    """Priority for provider selection in a plan."""

    PRIMARY = "primary"
    SECONDARY = "secondary"
    ENRICHMENT = "enrichment"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class ParseStep:
    """A single parsing step in a parse plan."""

    provider_name: str
    priority: ParsePriority = ParsePriority.PRIMARY
    timeout_ms: int = 60000
    config: Dict[str, Any] = field(default_factory=dict)
    enrichment_for: Optional[str] = None  # provider name to enrich

    def __post_init__(self) -> None:
        if self.timeout_ms <= 0:
            object.__setattr__(self, "timeout_ms", 60000)


@dataclass(frozen=True)
class ParsePlan:
    """Plan for parsing a document.

    Defines the ordered steps (providers to invoke), fallback strategy,
    enrichment configuration, and quality thresholds.
    """

    artifact_id: str
    steps: Tuple[ParseStep, ...] = field(default_factory=tuple)
    fallback_providers: Tuple[str, ...] = field(default_factory=tuple)
    quality_gate: Optional[Dict[str, float]] = None
    enable_ocr_enrichment: bool = False
    enable_vlm_enrichment: bool = False
    max_enrichment_pages: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def primary_step(self) -> Optional[ParseStep]:
        """Return the first primary step, if any."""
        for step in self.steps:
            if step.priority == ParsePriority.PRIMARY:
                return step
        return None

    @property
    def enrichment_steps(self) -> Tuple[ParseStep, ...]:
        """Return all enrichment steps."""
        return tuple(s for s in self.steps if s.priority == ParsePriority.ENRICHMENT)


# ---------------------------------------------------------------------------
# ParsePlanner
# ---------------------------------------------------------------------------


class ParsePlanner:
    """Plans parsing strategies based on probe results and available providers.

    The planner is stateless and idempotent: the same probe + same set of
    available provider names produces the same plan.
    """

    # Quality thresholds (initial proposed values per R2D0 spec)
    DEFAULT_QUALITY_GATE: Dict[str, float] = {
        "text_coverage": 0.85,
        "empty_unit_ratio": 0.05,
        "duplicate_ratio": 0.08,
        "ocr_confidence": 0.75,
        "table_coverage": 0.70,
        "formula_coverage": 0.70,
    }

    def __init__(self, available_providers: Optional[List[str]] = None) -> None:
        self._available_providers = set(available_providers or [])

    def set_available_providers(self, providers: List[str]) -> None:
        """Set the list of available provider names."""
        self._available_providers = set(providers)

    def plan(self, probe: ProbeResult, artifact_id: str) -> ParsePlan:
        """Create a parse plan based on probe results.

        Args:
            probe: The probe result for the document.
            artifact_id: The stable artifact ID.

        Returns:
            A ParsePlan with ordered steps.
        """
        if not probe.is_parseable():
            return ParsePlan(
                artifact_id=artifact_id,
                steps=(),
                metadata={"error": f"Unparseable document: {probe.error}"},
            )

        fmt = probe.detected_format.value
        steps: List[ParseStep] = []
        fallbacks: List[str] = []
        enable_ocr = False
        max_enrich = 0

        if fmt == "pptx":
            self._plan_pptx(probe, steps, fallbacks)
        elif fmt == "pdf":
            self._plan_pdf(probe, steps, fallbacks)
        elif fmt == "docx":
            self._plan_docx(probe, steps, fallbacks)
        elif fmt == "image":
            self._plan_image(probe, steps, fallbacks)
        else:
            # Unknown/unsupported: use first available provider
            if self._available_providers:
                first = next(iter(self._available_providers))
                steps.append(ParseStep(
                    provider_name=first,
                    priority=ParsePriority.FALLBACK,
                ))

        # Check if OCR enrichment is needed
        if probe.needs_ocr() and "tesseract-ocr" in self._available_providers:
            enable_ocr = True
            max_enrich = max(max_enrich, len(probe.image_only_pages))

        return ParsePlan(
            artifact_id=artifact_id,
            steps=tuple(steps),
            fallback_providers=tuple(fallbacks),
            quality_gate=dict(self.DEFAULT_QUALITY_GATE),
            enable_ocr_enrichment=enable_ocr,
            max_enrichment_pages=max_enrich,
        )

    def _plan_pptx(
        self,
        probe: ProbeResult,
        steps: List[ParseStep],
        fallbacks: List[str],
    ) -> None:
        """Plan for PPTX documents."""
        if "native-pptx" in self._available_providers:
            steps.append(ParseStep(
                provider_name="native-pptx",
                priority=ParsePriority.PRIMARY,
                timeout_ms=120000,
            ))

        # OCR enrichment for image-heavy slides
        if probe.image_only_pages and "tesseract-ocr" in self._available_providers:
            steps.append(ParseStep(
                provider_name="tesseract-ocr",
                priority=ParsePriority.ENRICHMENT,
                timeout_ms=300000,
                enrichment_for="native-pptx",
                config={"pages": list(probe.image_only_pages)},
            ))

    def _plan_pdf(
        self,
        probe: ProbeResult,
        steps: List[ParseStep],
        fallbacks: List[str],
    ) -> None:
        """Plan for PDF documents.

        P1-3: Primary parser is now ``pdf-plumber`` (real pdfplumber).
        OCR enrichment uses ``tesseract-ocr`` for image-only pages.
        """
        if "pdf-plumber" in self._available_providers:
            steps.append(ParseStep(
                provider_name="pdf-plumber",
                priority=ParsePriority.PRIMARY,
                timeout_ms=180000,
            ))

        if "tesseract-ocr" in self._available_providers:
            fallbacks.append("tesseract-ocr")
            # Add OCR enrichment for image-only pages
            if probe.image_only_pages:
                steps.append(ParseStep(
                    provider_name="tesseract-ocr",
                    priority=ParsePriority.ENRICHMENT,
                    timeout_ms=300000,
                    enrichment_for="pdf-plumber",
                    config={"pages": list(probe.image_only_pages)},
                ))

    def _plan_docx(
        self,
        probe: ProbeResult,
        steps: List[ParseStep],
        fallbacks: List[str],
    ) -> None:
        """Plan for DOCX documents.

        P1-3: No real DOCX parser registered yet (DoclingFakeProvider
        removed). If no provider is available, no steps are added — the
        pipeline will fail with PARSE_FAILED rather than fabricate output.
        To enable DOCX, register a real DOCX provider (e.g. python-docx
        wrapper) in ``document_parse_pipeline._get_parser_registry``.
        """
        # Intentionally empty: no real DOCX provider available.
        return

    def _plan_image(
        self,
        probe: ProbeResult,
        steps: List[ParseStep],
        fallbacks: List[str],
    ) -> None:
        """Plan for standalone image files."""
        if "tesseract-ocr" in self._available_providers:
            steps.append(ParseStep(
                provider_name="tesseract-ocr",
                priority=ParsePriority.PRIMARY,
                timeout_ms=300000,
            ))
