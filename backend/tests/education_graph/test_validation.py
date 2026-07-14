"""Tests for the graph validation layer (P1-05 charter: types, loops,
direction, isolation, prerequisites).

Covers:
- Type-matrix enforcement (source/target type allowed per relation type)
- Self-loop rejection (all relation types)
- Duplicate-edge detection (directed vs undirected)
- Prerequisite-cycle detection (PREREQUISITE_OF DAG enforcement)
- Review-status suggestion mapping (hard vs soft violations)
- Isolation advisory (accepted nodes with no accepted edges)
- Unknown relation type handling

Reference: docs/refactor/document_kg_v2/R2D0教育知识图谱本体与构建算法.md §3.
"""
import pytest

from app.domain.education_graph.models import (
    GraphNode,
    GraphRelation,
    NodeId,
    RelationId,
    EducationalUnitId,
)
from app.domain.education_graph.enums import (
    NodeType,
    RelationType,
    ReviewStatus,
)
from app.domain.education_graph.validation import (
    ValidationReason,
    ValidationResult,
    detect_prerequisite_cycle,
    find_isolated_accepted_nodes,
    suggest_review_status,
    validate_relation,
    validate_relation_full,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(nid: str, ntype: NodeType) -> GraphNode:
    return GraphNode(
        node_id=NodeId(nid),
        unit_id=EducationalUnitId("u-test"),
        node_type=ntype,
        label=nid,
        canonical_key=nid,
    )


def _relation(
    rid: str,
    source: str,
    target: str,
    rtype: RelationType,
    directed: bool = True,
) -> GraphRelation:
    return GraphRelation(
        relation_id=RelationId(rid),
        source_id=NodeId(source),
        target_id=NodeId(target),
        relation_type=rtype,
        directed=directed,
    )


# ---------------------------------------------------------------------------
# Self-loop
# ---------------------------------------------------------------------------


class TestSelfLoop:
    def test_self_loop_rejected_for_directed(self):
        node = _node("n1", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "n1", "n1", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, node, node)
        assert not result.ok
        assert result.has_hard_violation
        assert any(v.reason == ValidationReason.SELF_LOOP for v in result.violations)

    def test_self_loop_rejected_for_undirected(self):
        node = _node("n1", NodeType.CONCEPT)
        rel = _relation("r1", "n1", "n1", RelationType.RELATED_TO)
        result = validate_relation(rel, node, node)
        assert not result.ok
        assert result.has_hard_violation


# ---------------------------------------------------------------------------
# Type matrix
# ---------------------------------------------------------------------------


class TestTypeMatrix:
    def test_prerequisite_of_valid_pair(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_prerequisite_of_skill_to_concept(self):
        src = _node("s1", NodeType.SKILL)
        tgt = _node("c1", NodeType.CONCEPT)
        rel = _relation("r1", "s1", "c1", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_prerequisite_of_invalid_source_type(self):
        # FORMULA is not an allowed source for PREREQUISITE_OF
        src = _node("f1", NodeType.FORMULA)
        tgt = _node("kp1", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "f1", "kp1", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt)
        assert not result.ok
        assert any(
            v.reason == ValidationReason.TYPE_MATRIX_VIOLATION_SOURCE
            for v in result.violations
        )

    def test_prerequisite_of_invalid_target_type(self):
        # PAGE is not an allowed target for PREREQUISITE_OF
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("p1", NodeType.PAGE)
        rel = _relation("r1", "kp1", "p1", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt)
        assert not result.ok
        assert any(
            v.reason == ValidationReason.TYPE_MATRIX_VIOLATION_TARGET
            for v in result.violations
        )

    def test_contains_valid_hierarchy(self):
        src = _node("course1", NodeType.COURSE)
        tgt = _node("chap1", NodeType.CHAPTER)
        rel = _relation("r1", "course1", "chap1", RelationType.CONTAINS)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_contains_invalid_source(self):
        # KNOWLEDGE_POINT cannot CONTAINS anything
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("chap1", NodeType.CHAPTER)
        rel = _relation("r1", "kp1", "chap1", RelationType.CONTAINS)
        result = validate_relation(rel, src, tgt)
        assert not result.ok
        assert result.has_hard_violation

    def test_uses_formula_valid(self):
        src = _node("m1", NodeType.METHOD)
        tgt = _node("f1", NodeType.FORMULA)
        rel = _relation("r1", "m1", "f1", RelationType.USES_FORMULA)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_supported_by_any_semantic_to_sourceblock(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("blk1", NodeType.SOURCE_BLOCK)
        rel = _relation("r1", "kp1", "blk1", RelationType.SUPPORTED_BY)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_appears_on_to_page(self):
        src = _node("blk1", NodeType.SOURCE_BLOCK)
        tgt = _node("page1", NodeType.PAGE)
        rel = _relation("r1", "blk1", "page1", RelationType.APPEARS_ON)
        result = validate_relation(rel, src, tgt)
        assert result.ok

    def test_both_source_and_target_invalid(self):
        src = _node("p1", NodeType.PAGE)
        tgt = _node("page2", NodeType.PAGE)
        rel = _relation("r1", "p1", "page2", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt)
        assert not result.ok
        reasons = {v.reason for v in result.violations}
        assert ValidationReason.TYPE_MATRIX_VIOLATION_SOURCE in reasons
        assert ValidationReason.TYPE_MATRIX_VIOLATION_TARGET in reasons


# ---------------------------------------------------------------------------
# Duplicate edge
# ---------------------------------------------------------------------------


class TestDuplicateEdge:
    def test_directed_duplicate_detected(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        existing = [_relation("r0", "kp1", "kp2", RelationType.PREREQUISITE_OF)]
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt, existing_relations=existing)
        assert not result.ok
        assert any(v.reason == ValidationReason.DUPLICATE_EDGE for v in result.violations)

    def test_directed_reverse_not_duplicate(self):
        # A->B is distinct from B->A for directed relations
        src = _node("kp2", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp1", NodeType.KNOWLEDGE_POINT)
        existing = [_relation("r0", "kp1", "kp2", RelationType.PREREQUISITE_OF)]
        rel = _relation("r1", "kp2", "kp1", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt, existing_relations=existing)
        assert result.ok

    def test_undirected_duplicate_detected_both_directions(self):
        # For undirected RELATED_TO, A-B == B-A
        src = _node("c2", NodeType.CONCEPT)
        tgt = _node("c1", NodeType.CONCEPT)
        existing = [_relation("r0", "c1", "c2", RelationType.RELATED_TO, directed=False)]
        rel = _relation("r1", "c2", "c1", RelationType.RELATED_TO, directed=False)
        result = validate_relation(rel, src, tgt, existing_relations=existing)
        assert not result.ok
        assert any(v.reason == ValidationReason.DUPLICATE_EDGE for v in result.violations)

    def test_self_update_not_duplicate(self):
        # Updating an existing relation by same id is not a duplicate
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        existing = [_relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)]
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        result = validate_relation(rel, src, tgt, existing_relations=existing)
        assert result.ok


# ---------------------------------------------------------------------------
# Prerequisite cycle detection
# ---------------------------------------------------------------------------


class TestPrerequisiteCycle:
    def test_no_cycle_simple_chain(self):
        # kp1 -> kp2 -> kp3 (DAG, no cycle)
        accepted = [
            _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF),
            _relation("r2", "kp2", "kp3", RelationType.PREREQUISITE_OF),
        ]
        candidate = _relation("r3", "kp3", "kp4", RelationType.PREREQUISITE_OF)
        cycle = detect_prerequisite_cycle(candidate, accepted)
        assert cycle is None

    def test_direct_cycle_detected(self):
        # kp1 -> kp2 exists; candidate kp2 -> kp1 creates a 2-cycle
        accepted = [
            _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF),
        ]
        candidate = _relation("r2", "kp2", "kp1", RelationType.PREREQUISITE_OF)
        cycle = detect_prerequisite_cycle(candidate, accepted)
        assert cycle is not None
        assert "kp1" in cycle and "kp2" in cycle

    def test_longer_cycle_detected(self):
        # kp1->kp2->kp3 exists; candidate kp3->kp1 closes the cycle
        accepted = [
            _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF),
            _relation("r2", "kp2", "kp3", RelationType.PREREQUISITE_OF),
        ]
        candidate = _relation("r3", "kp3", "kp1", RelationType.PREREQUISITE_OF)
        cycle = detect_prerequisite_cycle(candidate, accepted)
        assert cycle is not None

    def test_non_prerequisite_relation_ignored_for_cycle(self):
        # CONTAINS edges do not participate in prerequisite DAG
        accepted = [
            _relation("r1", "course1", "chap1", RelationType.CONTAINS),
        ]
        candidate = _relation("r2", "chap1", "course1", RelationType.PREREQUISITE_OF)
        # kp nodes don't exist but cycle detection only looks at prereq edges;
        # no prereq edges => no cycle
        cycle = detect_prerequisite_cycle(candidate, accepted)
        assert cycle is None

    def test_non_prerequisite_candidate_returns_none(self):
        accepted = [
            _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF),
        ]
        candidate = _relation("r2", "kp2", "kp1", RelationType.RELATED_TO)
        cycle = detect_prerequisite_cycle(candidate, accepted)
        assert cycle is None


# ---------------------------------------------------------------------------
# Full validation + review status suggestion
# ---------------------------------------------------------------------------


class TestValidateRelationFull:
    def test_valid_prerequisite_no_cycle(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        result = validate_relation_full(rel, src, tgt, accepted_relations=[])
        assert result.ok
        assert suggest_review_status(result) == ReviewStatus.PROPOSED

    def test_prerequisite_cycle_is_soft_violation(self):
        src = _node("kp2", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp1", NodeType.KNOWLEDGE_POINT)
        accepted = [_relation("r0", "kp1", "kp2", RelationType.PREREQUISITE_OF)]
        rel = _relation("r1", "kp2", "kp1", RelationType.PREREQUISITE_OF)
        result = validate_relation_full(rel, src, tgt, accepted_relations=accepted)
        assert not result.ok
        assert result.has_soft_violation
        assert not result.has_hard_violation
        assert suggest_review_status(result) == ReviewStatus.NEEDS_REVIEW

    def test_hard_violation_short_circuits_cycle_check(self):
        # Self-loop is hard; should not even reach cycle detection
        node = _node("kp1", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "kp1", "kp1", RelationType.PREREQUISITE_OF)
        result = validate_relation_full(
            rel, node, node, accepted_relations=[]
        )
        assert result.has_hard_violation
        assert suggest_review_status(result) == ReviewStatus.REJECTED

    def test_duplicate_is_soft_violation(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        existing = [_relation("r0", "kp1", "kp2", RelationType.PREREQUISITE_OF)]
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        result = validate_relation_full(
            rel, src, tgt, existing_relations=existing, accepted_relations=[]
        )
        assert result.has_soft_violation
        assert suggest_review_status(result) == ReviewStatus.NEEDS_REVIEW

    def test_type_matrix_hard_violation_rejected(self):
        src = _node("p1", NodeType.PAGE)
        tgt = _node("kp1", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "p1", "kp1", RelationType.PREREQUISITE_OF)
        result = validate_relation_full(rel, src, tgt)
        assert result.has_hard_violation
        assert suggest_review_status(result) == ReviewStatus.REJECTED


# ---------------------------------------------------------------------------
# Isolation advisory
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_isolated_accepted_node_found(self):
        nodes = {
            "kp1": _node("kp1", NodeType.KNOWLEDGE_POINT),
            "kp2": _node("kp2", NodeType.KNOWLEDGE_POINT),
            "orphan": _node("orphan", NodeType.KNOWLEDGE_POINT),
        }
        nodes["kp1"].status = ReviewStatus.ACCEPTED
        nodes["kp2"].status = ReviewStatus.ACCEPTED
        nodes["orphan"].status = ReviewStatus.ACCEPTED
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        rel.status = ReviewStatus.ACCEPTED
        isolated = find_isolated_accepted_nodes(nodes, [rel])
        assert "orphan" in isolated
        assert "kp1" not in isolated
        assert "kp2" not in isolated

    def test_no_isolated_when_all_connected(self):
        nodes = {
            "kp1": _node("kp1", NodeType.KNOWLEDGE_POINT),
            "kp2": _node("kp2", NodeType.KNOWLEDGE_POINT),
        }
        nodes["kp1"].status = ReviewStatus.ACCEPTED
        nodes["kp2"].status = ReviewStatus.ACCEPTED
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        rel.status = ReviewStatus.ACCEPTED
        isolated = find_isolated_accepted_nodes(nodes, [rel])
        assert isolated == []

    def test_proposed_relations_do_not_connect(self):
        nodes = {
            "kp1": _node("kp1", NodeType.KNOWLEDGE_POINT),
            "kp2": _node("kp2", NodeType.KNOWLEDGE_POINT),
        }
        nodes["kp1"].status = ReviewStatus.ACCEPTED
        nodes["kp2"].status = ReviewStatus.ACCEPTED
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        rel.status = ReviewStatus.PROPOSED  # not accepted -> does not connect
        isolated = find_isolated_accepted_nodes(nodes, [rel])
        assert set(isolated) == {"kp1", "kp2"}


# ---------------------------------------------------------------------------
# Unknown relation type
# ---------------------------------------------------------------------------


class TestUnknownRelationType:
    def test_unknown_type_rejected(self):
        src = _node("kp1", NodeType.KNOWLEDGE_POINT)
        tgt = _node("kp2", NodeType.KNOWLEDGE_POINT)
        rel = _relation("r1", "kp1", "kp2", RelationType.PREREQUISITE_OF)
        # Simulate unknown type by monkeypatching relation_type to a non-matrix value
        # We use a string that is not in the enum; validate via a fake enum member
        class FakeType:
            value = "fake_relation"
        rel.relation_type = FakeType()  # type: ignore
        result = validate_relation(rel, src, tgt)
        assert not result.ok
        assert any(
            v.reason == ValidationReason.UNKNOWN_RELATION_TYPE
            for v in result.violations
        )
