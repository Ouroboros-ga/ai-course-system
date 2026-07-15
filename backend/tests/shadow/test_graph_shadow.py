"""Tests for P1-09 G3E1 knowledge-graph shadow (ADR-0006 §G3E1).

Covers:
1. Flag disabled (default) -> no trigger, no trace.
2. Flag v2_shadow -> trigger writes isolated trace with units/nodes/relations.
3. HARD CONSTRAINT: no LLM call (llm_calls == 0).
4. Conflict downgrade (upstream not v2) -> no trigger.
5. V1 isolation: NEVER touches V1 KnowledgePoint/KnowledgeRelation.
6. Accepted -> evidence invariant: no evidence -> all PROPOSED; with
   evidence_block_ids -> accepted nodes carry evidence_ids.
7. Structural CONTAINS relations from path hierarchy (PROPOSED, no evidence).
8. Shadow never raises into V1 (business-level fail-closed).
9. Trace isolation from V1.
10. V1-vs-V2 diff shape (contract/integration, not quality).
11. Empty knowledge points / None course_id edge cases.
12. Store path-traversal safety + frozen result.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.platform.shadow.graph_shadow import (
    DEFAULT_GRAPH_SHADOW_ROOT,
    GraphShadowResult,
    GraphShadowStore,
    _stable_suffix,
    trigger_graph_shadow,
)
from app.core import feature_flags as ff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_store(tmp_path):
    return GraphShadowStore(base_dir=tmp_path / "graph_store")


@pytest.fixture
def v2_graph_settings():
    """All flags on the doc->runtime->graph chain v2_shadow so
    KNOWLEDGE_GRAPH_PIPELINE_VERSION is effectively v2_shadow (no conflict)."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v2_shadow"
    configured[ff.KNOWLEDGE_GRAPH_PIPELINE_VERSION] = "v2_shadow"
    with patch(
        "app.platform.shadow.graph_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def v1_only_settings():
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    with patch(
        "app.platform.shadow.graph_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


@pytest.fixture
def conflict_settings():
    """DOCUMENT_KG_RUNTIME_MODE=v1_only downgrades
    KNOWLEDGE_GRAPH_PIPELINE_VERSION (configured v2_shadow) via conflict rule."""
    configured = {f: ff.LEGAL_VALUES[f][0] for f in ff.ALL_FLAGS}
    configured[ff.DOCUMENT_PIPELINE_VERSION] = "v2_shadow"
    configured[ff.DOCUMENT_KG_RUNTIME_MODE] = "v1_only"  # upstream not v2
    configured[ff.KNOWLEDGE_GRAPH_PIPELINE_VERSION] = "v2_shadow"
    with patch(
        "app.platform.shadow.graph_shadow._configured_modes",
        return_value=configured,
    ):
        yield configured


def _kps():
    """V1 RAG knowledge points. kp1 '力学' is the parent of kp2 by path."""
    return [
        {"id": "知识点1", "title": "力学", "content": "力学研究物体运动规律。" * 2,
         "path": "力学", "level": 1},
        {"id": "知识点2", "title": "牛顿第二定律", "content": "F=ma 描述加速度与力的关系。" * 2,
         "path": "力学/牛顿第二定律", "level": 2},
    ]


def _block_ids(kps, course_id=1):
    course_key = str(course_id)
    return {
        f"blk_shadow_{_stable_suffix(course_key, i, kp['path'])}"
        for i, kp in enumerate(kps)
    }


# ---------------------------------------------------------------------------
# Flag-gated
# ---------------------------------------------------------------------------


class TestFlagGated:
    def test_disabled_no_trigger(self, tmp_store, v1_only_settings):
        result = trigger_graph_shadow(_kps(), course_id=101, store=tmp_store)
        assert result.triggered is False
        assert "flag_not_v2_shadow" in (result.fallback_reason or "")
        assert list(tmp_store.base_dir().glob("*.json")) == []

    def test_v2_shadow_triggers_and_writes_trace(self, tmp_store, v2_graph_settings):
        result = trigger_graph_shadow(_kps(), course_id=101, store=tmp_store)
        assert result.triggered is True
        assert result.effective_mode == "v2_shadow"
        assert result.trace_path is not None
        assert Path(result.trace_path).exists()
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["effective_mode"] == "v2_shadow"
        assert trace["course_id"] == "101"
        assert len(trace["v2_nodes"]) == 2
        assert len(trace["v2_units"]) == 2

    def test_conflict_downgrade_no_trigger(self, tmp_store, conflict_settings):
        result = trigger_graph_shadow(_kps(), course_id=101, store=tmp_store)
        assert result.triggered is False
        assert result.effective_mode == "v1_only"  # downgraded


# ---------------------------------------------------------------------------
# HARD CONSTRAINT: no LLM call
# ---------------------------------------------------------------------------


class TestNoLLM:
    def test_llm_calls_always_zero(self, tmp_store, v2_graph_settings):
        result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.llm_calls == 0
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["llm_calls"] == 0

    def test_llm_calls_zero_even_on_fail_closed(self, tmp_store, v2_graph_settings):
        with patch(
            "app.platform.shadow.graph_shadow._build_graph_candidates",
            side_effect=RuntimeError("boom"),
        ):
            result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.triggered is False
        assert result.llm_calls == 0


# ---------------------------------------------------------------------------
# V1 isolation: NEVER touches V1 KnowledgePoint/KnowledgeRelation
# ---------------------------------------------------------------------------


class TestV1Isolation:
    def test_never_calls_v1_knowledge_service(self, tmp_store, v2_graph_settings):
        with patch(
            "app.services.knowledge_service.KnowledgePointService.create_knowledge_point"
        ) as m_create, patch(
            "app.services.knowledge_service.KnowledgePointService.batch_create_knowledge_points"
        ) as m_batch, patch(
            "app.services.knowledge_service.KnowledgeRelationService.create_relation"
        ) as m_rel:
            result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.triggered is True
        assert m_create.called is False
        assert m_batch.called is False
        assert m_rel.called is False
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["v1_tables_touched"] is False

    def test_shadow_never_raises_into_v1(self, tmp_store, v2_graph_settings):
        with patch(
            "app.platform.shadow.graph_shadow._build_graph_candidates",
            side_effect=ValueError("boom"),
        ):
            result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.triggered is False
        assert "shadow_runtime_error" in (result.fallback_reason or "")

    def test_trace_isolated_from_v1(self, tmp_store, v2_graph_settings):
        trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        files = list(tmp_store.base_dir().glob("*.json"))
        assert len(files) == 1
        assert tmp_store.base_dir().name == "graph_store"


# ---------------------------------------------------------------------------
# Accepted -> evidence invariant
# ---------------------------------------------------------------------------


class TestAcceptedTracesEvidence:
    def test_no_evidence_all_proposed(self, tmp_store, v2_graph_settings):
        """Default (no evidence_block_ids) -> all PROPOSED, 0 accepted;
        invariant holds vacuously (no accepts without evidence)."""
        result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.triggered is True
        assert result.accepted_count == 0
        assert result.evidence_backed_count == 0
        assert result.accepted_traces_evidence is True
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert all(n["status"] == "proposed" for n in trace["v2_nodes"])
        # no node carries evidence_ids when nothing accepted
        assert all(not n["evidence_ids"] for n in trace["v2_nodes"])

    def test_evidence_backed_nodes_accepted(self, tmp_store, v2_graph_settings):
        """With evidence_block_ids covering all nodes -> all ACCEPTED, each
        carrying a non-empty evidence_ids list (enforced by accept_node)."""
        kps = _kps()
        evidence_block_ids = _block_ids(kps, course_id=1)
        result = trigger_graph_shadow(
            kps, course_id=1, evidence_block_ids=evidence_block_ids, store=tmp_store
        )
        assert result.triggered is True
        assert result.accepted_count == len(kps)
        assert result.evidence_backed_count == len(kps)
        assert result.accepted_traces_evidence is True
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        for n in trace["v2_nodes"]:
            assert n["status"] == "accepted"
            assert n["evidence_ids"]  # non-empty -> traces to evidence

    def test_partial_evidence_partial_accept(self, tmp_store, v2_graph_settings):
        """Only one node's block_id in evidence -> only that one ACCEPTED."""
        kps = _kps()
        only_first = {f"blk_shadow_{_stable_suffix('1', 0, kps[0]['path'])}"}
        result = trigger_graph_shadow(
            kps, course_id=1, evidence_block_ids=only_first, store=tmp_store
        )
        assert result.accepted_count == 1
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        accepted = [n for n in trace["v2_nodes"] if n["status"] == "accepted"]
        proposed = [n for n in trace["v2_nodes"] if n["status"] == "proposed"]
        assert len(accepted) == 1
        assert len(proposed) == 1
        assert accepted[0]["evidence_ids"]
        assert not proposed[0]["evidence_ids"]


# ---------------------------------------------------------------------------
# Structural relations from path hierarchy
# ---------------------------------------------------------------------------


class TestStructuralRelations:
    def test_contains_relation_from_hierarchy(self, tmp_store, v2_graph_settings):
        result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        assert result.triggered is True
        assert result.relation_count >= 1
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        rels = trace["v2_relations"]
        assert all(r["relation_type"] == "contains" for r in rels)
        # structural relations are PROPOSED (deterministic, no evidence needed)
        assert all(r["status"] == "proposed" for r in rels)
        # the relation links parent '力学' -> child '牛顿第二定律'
        labels = {n["node_id"]: n["label"] for n in trace["v2_nodes"]}
        assert any(
            labels[r["source_id"]] == "力学" and labels[r["target_id"]] == "牛顿第二定律"
            for r in rels
        )

    def test_no_relation_when_no_hierarchy(self, tmp_store, v2_graph_settings):
        """Flat knowledge points (no shared parent path) -> no relations."""
        kps = [{"id": "知识点1", "title": "A", "content": "content A " * 5, "path": "A", "level": 1}]
        result = trigger_graph_shadow(kps, course_id=1, store=tmp_store)
        assert result.relation_count == 0


# ---------------------------------------------------------------------------
# V1-vs-V2 diff shape
# ---------------------------------------------------------------------------


class TestDiffShape:
    def test_diff_is_contract_integration_not_quality(self, tmp_store, v2_graph_settings):
        kps = _kps()
        result = trigger_graph_shadow(kps, course_id=1, store=tmp_store)
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        diff = trace["diff"]
        assert diff["v1_kp_count"] == len(kps)
        assert diff["v2_node_count"] == result.node_count
        assert diff["v2_unit_count"] == result.unit_count
        assert diff["v2_relation_count"] == result.relation_count
        assert "not quality comparison" in diff["note"].lower()
        # no quality/answer fields
        assert "v2_answer" not in trace
        assert "quality_score" not in trace


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_knowledge_points_no_candidates(self, tmp_store, v2_graph_settings):
        result = trigger_graph_shadow([], course_id=1, store=tmp_store)
        assert result.triggered is True
        assert result.node_count == 0
        assert result.unit_count == 0
        assert result.relation_count == 0
        assert result.accepted_count == 0

    def test_none_course_id_allowed(self, tmp_store, v2_graph_settings):
        """Document not course-scoped -> graph shadow still runs (document-scoped)."""
        result = trigger_graph_shadow(_kps(), course_id=None, store=tmp_store)
        assert result.triggered is True
        trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert trace["course_id"] is None
        assert trace["diff"]["v2_node_count"] == 2


# ---------------------------------------------------------------------------
# Store safety + result shape
# ---------------------------------------------------------------------------


class TestStoreAndResult:
    def test_store_rejects_unsafe_run_id(self, tmp_path):
        store = GraphShadowStore(base_dir=tmp_path)
        with pytest.raises(ValueError):
            store.write("../escape", {"x": 1})

    def test_store_atomic_write(self, tmp_store, v2_graph_settings):
        result = trigger_graph_shadow(_kps(), course_id=1, store=tmp_store)
        # no leftover .tmp files
        assert list(tmp_store.base_dir().glob("*.tmp")) == []
        assert Path(result.trace_path).exists()

    def test_frozen(self):
        r = GraphShadowResult(triggered=False, effective_mode="v1_only")
        with pytest.raises(Exception):
            r.triggered = True
