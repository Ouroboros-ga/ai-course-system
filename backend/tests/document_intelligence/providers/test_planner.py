"""Tests for ParsePlanner and ParsePlan."""

import pytest

from app.platform.document_intelligence.planner import (
    ParsePlanner,
    ParsePlan,
    ParseStep,
    ParsePriority,
)
from app.platform.document_intelligence.probe import (
    DetectedFormat,
    ProbeResult,
)


class TestParsePlan:
    """ParsePlan basic properties."""

    def test_primary_step_returns_first_primary(self) -> None:
        plan = ParsePlan(
            artifact_id="art_123",
            steps=(
                ParseStep(provider_name="secondary", priority=ParsePriority.SECONDARY),
                ParseStep(provider_name="primary", priority=ParsePriority.PRIMARY),
            ),
        )
        primary = plan.primary_step
        assert primary is not None
        assert primary.provider_name == "primary"

    def test_primary_step_none_when_no_primary(self) -> None:
        plan = ParsePlan(
            artifact_id="art_123",
            steps=(),
        )
        assert plan.primary_step is None

    def test_enrichment_steps(self) -> None:
        plan = ParsePlan(
            artifact_id="art_123",
            steps=(
                ParseStep(provider_name="main", priority=ParsePriority.PRIMARY),
                ParseStep(provider_name="ocr", priority=ParsePriority.ENRICHMENT),
                ParseStep(provider_name="vlm", priority=ParsePriority.ENRICHMENT),
            ),
        )
        enrich = plan.enrichment_steps
        assert len(enrich) == 2
        assert enrich[0].provider_name == "ocr"

    def test_timeout_defaults_to_positive(self) -> None:
        step = ParseStep(provider_name="test", timeout_ms=0)
        assert step.timeout_ms == 60000  # reset to default

    def test_negative_timeout_reset(self) -> None:
        step = ParseStep(provider_name="test", timeout_ms=-100)
        assert step.timeout_ms == 60000


class TestParsePlanner:
    """ParsePlanner strategy generation."""

    @pytest.fixture
    def planner_with_providers(self) -> ParsePlanner:
        planner = ParsePlanner()
        planner.set_available_providers([
            "native-pptx", "pdf-plumber", "tesseract-ocr",
        ])
        return planner

    @pytest.fixture
    def planner_empty(self) -> ParsePlanner:
        return ParsePlanner()

    def test_plan_pptx_with_providers(self, planner_with_providers: ParsePlanner) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            page_or_slide_count=10,
            has_text_content=True,
            image_only_pages=(),
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_123")
        assert len(plan.steps) >= 1
        assert plan.primary_step is not None
        assert plan.primary_step.provider_name == "native-pptx"
        assert plan.quality_gate is not None

    def test_plan_pptx_with_image_pages_adds_ocr(
        self, planner_with_providers: ParsePlanner,
    ) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            page_or_slide_count=10,
            has_text_content=True,
            image_only_pages=(3, 7),
            estimated_text_coverage=0.2,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_123")
        assert plan.enable_ocr_enrichment is True
        enrich = plan.enrichment_steps
        assert any(s.provider_name == "tesseract-ocr" for s in enrich)

    def test_plan_pdf_with_providers(self, planner_with_providers: ParsePlanner) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PDF,
            page_or_slide_count=5,
            has_text_content=True,
            image_only_pages=(),
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_456")
        assert len(plan.steps) >= 1
        assert plan.primary_step is not None

    def test_plan_pdf_image_pages_adds_ocr(
        self, planner_with_providers: ParsePlanner,
    ) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PDF,
            page_or_slide_count=5,
            has_text_content=True,
            image_only_pages=(2, 4),
            estimated_text_coverage=0.2,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_789")
        assert plan.enable_ocr_enrichment is True

    def test_plan_image_uses_ocr(self, planner_with_providers: ParsePlanner) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.IMAGE,
            page_or_slide_count=1,
            has_text_content=False,
            image_only_pages=(1,),
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_img")
        assert len(plan.steps) >= 1
        assert plan.primary_step is not None
        assert plan.primary_step.provider_name == "tesseract-ocr"

    def test_plan_corrupt_returns_empty_steps(
        self, planner_with_providers: ParsePlanner,
    ) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.CORRUPT,
            error="File corrupted",
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_corrupt")
        assert len(plan.steps) == 0
        assert "error" in plan.metadata

    def test_plan_encrypted_returns_empty_steps(
        self, planner_with_providers: ParsePlanner,
    ) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.ENCRYPTED,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_enc")
        assert len(plan.steps) == 0

    def test_plan_unsupported_format(
        self, planner_with_providers: ParsePlanner,
    ) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.UNSUPPORTED,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_unsup")
        assert len(plan.steps) == 0

    def test_plan_empty_providers(self, planner_empty: ParsePlanner) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            page_or_slide_count=5,
        )
        plan = planner_empty.plan(probe, artifact_id="art_123")
        assert len(plan.steps) == 0

    def test_plan_docx_no_real_provider(self, planner_with_providers: ParsePlanner) -> None:
        """P1-3: No real DOCX provider registered — planner must NOT fabricate steps.

        Honest failure: returns empty steps so the pipeline can raise
        PARSE_FAILED instead of running a fake parser.
        """
        probe = ProbeResult(
            detected_format=DetectedFormat.DOCX,
            page_or_slide_count=3,
            has_text_content=True,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_docx")
        assert len(plan.steps) == 0
        assert plan.primary_step is None

    def test_plan_sets_quality_gate(self, planner_with_providers: ParsePlanner) -> None:
        probe = ProbeResult(
            detected_format=DetectedFormat.PPTX,
            page_or_slide_count=5,
            has_text_content=True,
        )
        plan = planner_with_providers.plan(probe, artifact_id="art_qual")
        assert plan.quality_gate is not None
        assert "text_coverage" in plan.quality_gate
        assert plan.quality_gate["text_coverage"] == 0.85

    def test_set_available_providers_replaces(self) -> None:
        planner = ParsePlanner(available_providers=["native-pptx"])
        planner.set_available_providers(["tesseract-ocr"])
        assert planner._available_providers == {"tesseract-ocr"}
