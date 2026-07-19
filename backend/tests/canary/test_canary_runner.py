"""Tests for P1-09 G5A canary runner (ADR-0006 §G5A).

Covers:
1. All-flags-on canary -> all 6 paths triggered, traces written, quality
   gate PASS.
2. Scope control: course NOT in allowlist -> skipped (not run).
3. Empty allowlist -> no courses run (no global canary).
4. No real services: llm_client is never invoked (G5A invariant).
5. Hard constraints hold post-canary: would_inject=False, v1_blocked=False,
   accepted_traces_evidence=True, llm_calls=0.
6. real_services_called is always False.
"""
from unittest.mock import patch

import pytest

from app.platform.canary.canary_runner import (
    CanaryConfig,
    CanaryRunResult,
    run_canary,
)
from app.platform.shadow.doc_shadow import ShadowArtifactStore
from app.platform.shadow.evidence_shadow import EvidenceTraceStore
from app.platform.shadow.learning_shadow import LearningEventShadowStore
from app.platform.shadow.memory_candidate_shadow import MemoryCandidateShadowStore
from app.platform.shadow.safety_dryrun_shadow import SafetyDryRunStore
from app.platform.shadow.graph_shadow import GraphShadowStore


# ---------------------------------------------------------------------------
# Fixtures: isolated stores per shadow path
# ---------------------------------------------------------------------------


@pytest.fixture
def config(tmp_path):
    doc_file = tmp_path / "canary_source.md"
    doc_file.write_bytes(b"canary document bytes for sha256")
    return CanaryConfig(
        course_ids=[101],
        doc_file_path=doc_file,
        doc_store=ShadowArtifactStore(base_dir=tmp_path / "doc"),
        evidence_store=EvidenceTraceStore(base_dir=tmp_path / "ev"),
        learning_store=LearningEventShadowStore(base_dir=tmp_path / "lr"),
        memory_store=MemoryCandidateShadowStore(base_dir=tmp_path / "mem"),
        safety_store=SafetyDryRunStore(base_dir=tmp_path / "sf"),
        graph_store=GraphShadowStore(base_dir=tmp_path / "gr"),
    )


# ---------------------------------------------------------------------------
# End-to-end canary
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_all_paths_triggered_quality_pass(self, config):
        result = run_canary(config)
        assert isinstance(result, CanaryRunResult)
        assert len(result.course_results) == 1
        cr = result.course_results[0]
        # All 6 paths triggered.
        for pid in ("G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"):
            assert cr.path_results[pid]["triggered"] is True, f"{pid} not triggered"
        # Traces written for each path.
        for pid in ("G3B", "G3C", "G3D1", "G3D2", "G3D3", "G3E1"):
            assert len(cr.trace_paths_by_path[pid]) == 1, f"{pid} no trace"
        # Quality gate PASS (execution_safety + contract_integrity pass;
        # model_quality not_evaluated).
        assert result.quality_gate is not None
        assert result.quality_gate.verdict.value == "pass"
        assert result.overall_passed is True

    def test_hard_constraints_hold(self, config):
        result = run_canary(config)
        qg = result.quality_gate
        assert qg.aggregate_invariants["all_llm_calls_zero"] is True
        assert qg.aggregate_invariants["memory_never_injects"] is True
        assert qg.aggregate_invariants["safety_never_blocks"] is True
        assert qg.aggregate_invariants["v1_tables_never_touched"] is True
        assert qg.aggregate_invariants["accepted_traces_evidence"] is True
        assert qg.aggregate_invariants["evidence_scope_isolated"] is True

    def test_model_quality_not_evaluated(self, config):
        result = run_canary(config)
        qg = result.quality_gate
        assert qg.aggregate_invariants["model_quality"] == "not_evaluated"
        assert qg.model_quality_not_evaluated is True

    def test_real_services_called_log_derived_empty(self, config):
        """G5A.1: real_services_called derived from provider_call_log.
        Empty log (no real providers in G5A) -> False."""
        result = run_canary(config)
        assert result.provider_call_log == []  # no real providers in G5A
        assert result.real_services_called is False  # derived from empty log

    def test_real_services_called_log_derived_with_real_call(self, config):
        """Prove derivation (not hardcoded): a log with invoked_real=True -> True."""
        from app.platform.canary.canary_runner import (
            ProviderCallRecord,
            derive_real_services_called,
        )
        log = [ProviderCallRecord(provider_name="docling", invoked_real=True,
                                  stage="parse", detail="real")]
        assert derive_real_services_called(log) is True
        assert derive_real_services_called([]) is False


# ---------------------------------------------------------------------------
# Scope control
# ---------------------------------------------------------------------------


class TestScopeControl:
    def test_course_not_in_allowlist_skipped(self, tmp_path):
        # allowlist empty -> no courses run.
        config = CanaryConfig(
            course_ids=[],
            doc_store=ShadowArtifactStore(base_dir=tmp_path / "doc"),
            evidence_store=EvidenceTraceStore(base_dir=tmp_path / "ev"),
            learning_store=LearningEventShadowStore(base_dir=tmp_path / "lr"),
            memory_store=MemoryCandidateShadowStore(base_dir=tmp_path / "mem"),
            safety_store=SafetyDryRunStore(base_dir=tmp_path / "sf"),
            graph_store=GraphShadowStore(base_dir=tmp_path / "gr"),
        )
        result = run_canary(config)
        assert result.course_results == []
        # No courses ran -> no traces -> quality gate not pass (insufficient/
        # not_evaluated), so overall_passed False. NOT a FAIL (no violation).
        assert result.overall_passed is False
        assert result.quality_gate.verdict.value != "pass"

    def test_only_allowlisted_courses_run(self, tmp_path):
        config = CanaryConfig(
            course_ids=[201, 202],
            doc_store=ShadowArtifactStore(base_dir=tmp_path / "doc"),
            evidence_store=EvidenceTraceStore(base_dir=tmp_path / "ev"),
            learning_store=LearningEventShadowStore(base_dir=tmp_path / "lr"),
            memory_store=MemoryCandidateShadowStore(base_dir=tmp_path / "mem"),
            safety_store=SafetyDryRunStore(base_dir=tmp_path / "sf"),
            graph_store=GraphShadowStore(base_dir=tmp_path / "gr"),
        )
        result = run_canary(config)
        assert len(result.course_results) == 2
        assert {cr.course_id for cr in result.course_results} == {201, 202}


# ---------------------------------------------------------------------------
# No real services (llm_client never invoked)
# ---------------------------------------------------------------------------


class TestNoRealServices:
    def test_llm_client_never_invoked(self, config):
        """G5A invariant: canary must not call the real LLM client."""
        with patch("app.common.llm_client.llm_client.chat") as mock_chat:
            run_canary(config)
        assert mock_chat.called is False
