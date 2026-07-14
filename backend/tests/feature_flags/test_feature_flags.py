"""Tests for Product 1 V2 shadow feature flags (P1-09 G3A).

Covers (per ADR-0006 G3A exit gate):
1. Startup fail-fast: illegal flag values reject Settings construction.
2. Defaults: all flags V1/disabled.
3. Legal values accepted.
4. G6-reserved values (v2_preferred_with_v1_fallback, v2_only) rejected.
5. Conflict rule: aggregate vs module flag downgrade.
6. Dependency chain downgrade.
7. Independent flags unaffected by document aggregate.
8. Module-to-module dependency (memory needs learning events).
9. Business-level fail-closed (shadow_runtime_fail_closed).
10. all_default / is_configured_v2 helpers.
"""
import pytest
from pydantic import ValidationError

from app.core import feature_flags as ff
from app.core.feature_flags import (
    DOCUMENT_PIPELINE_VERSION,
    DOCUMENT_KG_RUNTIME_MODE,
    EVIDENCE_CITATION_MODE,
    KNOWLEDGE_GRAPH_PIPELINE_VERSION,
    LEARNING_EVENT_MODE,
    STUDENT_MEMORY_MODE,
    SAFETY_GOVERNANCE_MODE,
    PIPELINE_MODES,
    TOGGLE_MODES,
    ALL_FLAGS,
    LEGAL_VALUES,
    UPSTREAM,
    EffectiveMode,
    resolve_effective_modes,
    shadow_runtime_fail_closed,
    all_default,
    is_configured_v2,
)


# ---------------------------------------------------------------------------
# Settings fail-fast (config.py integration)
# ---------------------------------------------------------------------------


class TestStartupFailFast:
    """Illegal flag values must reject Settings construction (fail-fast)."""

    def test_defaults_construct_cleanly(self):
        from app.core.config import Settings

        s = Settings()
        assert s.DOCUMENT_PIPELINE_VERSION == "v1_only"
        assert s.STUDENT_MEMORY_MODE == "disabled"
        assert s.SAFETY_GOVERNANCE_MODE == "disabled"

    def test_typo_rejected(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(DOCUMENT_PIPELINE_VERSION="v2_shdaow")  # typo

    def test_invalid_value_rejected(self):
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(EVIDENCE_CITATION_MODE="v2")

    def test_g6_reserved_rejected(self):
        """v2_preferred_with_v1_fallback and v2_only are NOT legal in G3."""
        from app.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(DOCUMENT_PIPELINE_VERSION="v2_preferred_with_v1_fallback")
        with pytest.raises(ValidationError):
            Settings(DOCUMENT_KG_RUNTIME_MODE="v2_only")

    def test_toggle_flag_rejects_pipeline_value(self):
        from app.core.config import Settings

        # STUDENT_MEMORY_MODE is a toggle (disabled/shadow); v2_shadow illegal.
        with pytest.raises(ValidationError):
            Settings(STUDENT_MEMORY_MODE="v2_shadow")
        with pytest.raises(ValidationError):
            Settings(SAFETY_GOVERNANCE_MODE="v1_only")

    def test_legal_values_accepted(self):
        from app.core.config import Settings

        s = Settings(
            DOCUMENT_PIPELINE_VERSION="v2_shadow",
            STUDENT_MEMORY_MODE="shadow",
            SAFETY_GOVERNANCE_MODE="shadow",
        )
        assert s.DOCUMENT_PIPELINE_VERSION == "v2_shadow"
        assert s.STUDENT_MEMORY_MODE == "shadow"


# ---------------------------------------------------------------------------
# Legal values / structure
# ---------------------------------------------------------------------------


class TestLegalValues:
    def test_pipeline_modes(self):
        assert PIPELINE_MODES == ("v1_only", "v2_shadow")

    def test_toggle_modes(self):
        assert TOGGLE_MODES == ("disabled", "shadow")

    def test_seven_flags(self):
        assert len(ALL_FLAGS) == 7

    def test_each_flag_has_legal_values(self):
        for flag in ALL_FLAGS:
            assert flag in LEGAL_VALUES
            assert len(LEGAL_VALUES[flag]) == 2

    def test_toggle_flags(self):
        assert LEGAL_VALUES[STUDENT_MEMORY_MODE] == TOGGLE_MODES
        assert LEGAL_VALUES[SAFETY_GOVERNANCE_MODE] == TOGGLE_MODES

    def test_pipeline_flags(self):
        for flag in ALL_FLAGS:
            if flag not in (STUDENT_MEMORY_MODE, SAFETY_GOVERNANCE_MODE):
                assert LEGAL_VALUES[flag] == PIPELINE_MODES


# ---------------------------------------------------------------------------
# Conflict rule: aggregate vs module
# ---------------------------------------------------------------------------


class TestConflictRule:
    def test_all_v2_no_conflict(self):
        """When every flag (including roots) is v2_shadow, no downgrade."""
        cfg = {f: "v2_shadow" for f in ALL_FLAGS if ff.FLAG_KINDS[f] == "pipeline"}
        cfg[STUDENT_MEMORY_MODE] = "shadow"
        cfg[SAFETY_GOVERNANCE_MODE] = "shadow"
        modes = resolve_effective_modes(cfg)
        for flag in ALL_FLAGS:
            assert modes[flag].downgraded is False, flag
            assert modes[flag].effective == cfg[flag], flag

    def test_aggregate_v1_downgrades_module(self):
        """DOCUMENT_PIPELINE_VERSION=v1_only downgrades DOCUMENT_KG_RUNTIME_MODE
        (which is v2_shadow configured) to v1_only."""
        cfg = {
            DOCUMENT_PIPELINE_VERSION: "v1_only",
            DOCUMENT_KG_RUNTIME_MODE: "v2_shadow",
            EVIDENCE_CITATION_MODE: "v2_shadow",
            KNOWLEDGE_GRAPH_PIPELINE_VERSION: "v2_shadow",
            LEARNING_EVENT_MODE: "v1_only",
            STUDENT_MEMORY_MODE: "disabled",
            SAFETY_GOVERNANCE_MODE: "disabled",
        }
        modes = resolve_effective_modes(cfg)
        # aggregate root v1_only, not downgraded
        assert modes[DOCUMENT_PIPELINE_VERSION].effective == "v1_only"
        assert modes[DOCUMENT_PIPELINE_VERSION].downgraded is False
        # runtime wants v2_shadow but upstream v1_only -> downgraded
        assert modes[DOCUMENT_KG_RUNTIME_MODE].effective == "v1_only"
        assert modes[DOCUMENT_KG_RUNTIME_MODE].downgraded is True
        assert modes[DOCUMENT_KG_RUNTIME_MODE].fallback_reason is not None
        # evidence + graph also downgraded (chain)
        assert modes[EVIDENCE_CITATION_MODE].effective == "v1_only"
        assert modes[EVIDENCE_CITATION_MODE].downgraded is True
        assert modes[KNOWLEDGE_GRAPH_PIPELINE_VERSION].effective == "v1_only"
        assert modes[KNOWLEDGE_GRAPH_PIPELINE_VERSION].downgraded is True

    def test_chain_downgrade_cascades(self):
        """Full chain: root v1_only -> runtime downgraded -> evidence downgraded,
        even though evidence itself is configured v2_shadow."""
        cfg = {
            DOCUMENT_PIPELINE_VERSION: "v1_only",
            DOCUMENT_KG_RUNTIME_MODE: "v2_shadow",
            EVIDENCE_CITATION_MODE: "v2_shadow",
        }
        modes = resolve_effective_modes(cfg)
        assert modes[EVIDENCE_CITATION_MODE].effective == "v1_only"
        assert modes[EVIDENCE_CITATION_MODE].downgraded is True
        # fallback_reason references the immediate upstream
        assert "DOCUMENT_KG_RUNTIME_MODE" in modes[EVIDENCE_CITATION_MODE].fallback_reason

    def test_module_v1_no_downgrade(self):
        """A module configured v1_only with upstream v2_shadow is just v1_only
        (not 'downgraded' - it matches its configured intent)."""
        cfg = {
            DOCUMENT_PIPELINE_VERSION: "v2_shadow",
            DOCUMENT_KG_RUNTIME_MODE: "v2_shadow",
            EVIDENCE_CITATION_MODE: "v1_only",
        }
        modes = resolve_effective_modes(cfg)
        assert modes[EVIDENCE_CITATION_MODE].effective == "v1_only"
        assert modes[EVIDENCE_CITATION_MODE].downgraded is False


# ---------------------------------------------------------------------------
# Independent flags
# ---------------------------------------------------------------------------


class TestIndependentFlags:
    def test_learning_safety_independent_of_document_aggregate(self):
        """LEARNING_EVENT_MODE and SAFETY_GOVERNANCE_MODE are not downgraded
        by DOCUMENT_PIPELINE_VERSION being v1_only."""
        cfg = {
            DOCUMENT_PIPELINE_VERSION: "v1_only",
            DOCUMENT_KG_RUNTIME_MODE: "v1_only",
            LEARNING_EVENT_MODE: "v2_shadow",
            SAFETY_GOVERNANCE_MODE: "shadow",
        }
        modes = resolve_effective_modes(cfg)
        assert modes[LEARNING_EVENT_MODE].effective == "v2_shadow"
        assert modes[LEARNING_EVENT_MODE].downgraded is False
        assert modes[SAFETY_GOVERNANCE_MODE].effective == "shadow"
        assert modes[SAFETY_GOVERNANCE_MODE].downgraded is False

    def test_memory_requires_learning_events(self):
        """STUDENT_MEMORY_MODE=shadow requires LEARNING_EVENT_MODE=v2_shadow.
        If learning events are v1_only, memory downgrades to disabled."""
        cfg = {
            LEARNING_EVENT_MODE: "v1_only",
            STUDENT_MEMORY_MODE: "shadow",
        }
        modes = resolve_effective_modes(cfg)
        assert modes[STUDENT_MEMORY_MODE].effective == "disabled"
        assert modes[STUDENT_MEMORY_MODE].downgraded is True
        assert "LEARNING_EVENT_MODE" in modes[STUDENT_MEMORY_MODE].fallback_reason

    def test_memory_shadow_when_learning_v2(self):
        cfg = {
            LEARNING_EVENT_MODE: "v2_shadow",
            STUDENT_MEMORY_MODE: "shadow",
        }
        modes = resolve_effective_modes(cfg)
        assert modes[STUDENT_MEMORY_MODE].effective == "shadow"
        assert modes[STUDENT_MEMORY_MODE].downgraded is False


# ---------------------------------------------------------------------------
# Business-level fail-closed
# ---------------------------------------------------------------------------


class TestShadowRuntimeFailClosed:
    def test_runtime_failure_downgrades_with_reason(self):
        """Valid config (v2_shadow) but runtime error -> fail-closed to v1_only."""
        result = shadow_runtime_fail_closed(
            DOCUMENT_PIPELINE_VERSION, "v2_shadow", "docling_timeout"
        )
        assert result.flag == DOCUMENT_PIPELINE_VERSION
        assert result.configured == "v2_shadow"
        assert result.effective == "v1_only"
        assert result.downgraded is True
        assert "shadow_runtime_error" in result.fallback_reason
        assert "docling_timeout" in result.fallback_reason

    def test_runtime_failure_toggle_flag(self):
        result = shadow_runtime_fail_closed(
            STUDENT_MEMORY_MODE, "shadow", "repo_unavailable"
        )
        assert result.effective == "disabled"
        assert result.downgraded is True

    def test_runtime_failure_distinct_from_config_error(self):
        """A runtime fail-closed result carries the configured value, proving
        config was legal (passed startup) and only runtime failed."""
        result = shadow_runtime_fail_closed(
            EVIDENCE_CITATION_MODE, "v2_shadow", "vector_index_down"
        )
        assert result.configured == "v2_shadow"  # was legal
        assert result.effective == "v1_only"     # but running V1
        assert result.fallback_reason is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_all_default_true_when_empty(self):
        assert all_default({}) is True

    def test_all_default_false_when_any_v2(self):
        assert all_default({DOCUMENT_PIPELINE_VERSION: "v2_shadow"}) is False

    def test_is_configured_v2(self):
        cfg = {DOCUMENT_PIPELINE_VERSION: "v2_shadow", EVIDENCE_CITATION_MODE: "v1_only"}
        assert is_configured_v2(cfg, DOCUMENT_PIPELINE_VERSION) is True
        assert is_configured_v2(cfg, EVIDENCE_CITATION_MODE) is False

    def test_upstream_graph_acyclic(self):
        """Dependency graph must be a DAG (no cycles)."""
        seen = set()

        def visit(flag, path):
            if flag in path:
                raise AssertionError(f"cycle detected: {' -> '.join(path + [flag])}")
            if flag in seen:
                return
            seen.add(flag)
            up = UPSTREAM[flag]
            if up is not None:
                visit(up, path + [flag])

        for flag in ALL_FLAGS:
            visit(flag, [])

    def test_effective_mode_is_frozen(self):
        em = EffectiveMode(flag="X", configured="v2_shadow", effective="v1_only")
        with pytest.raises(Exception):
            em.effective = "v2_shadow"  # frozen dataclass
