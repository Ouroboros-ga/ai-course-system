"""Comprehensive tests for Education Graph domain model and GraphStore.

Test categories:
1. EducationalUnit CRUD
2. GraphNode CRUD
3. GraphRelation CRUD
4. Review decisions (accept/reject with evidence)
5. GraphSnapshot lifecycle
6. Error handling (missing entities, duplicates, constraint violations)
7. Edge cases (empty store, evidence retrieval)
"""
import pytest
from datetime import datetime

from app.domain.education_graph.models import (
    EducationalUnit,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    EducationalUnitId,
    NodeId,
    RelationId,
    SnapshotId,
)
from app.domain.education_graph.enums import (
    EducationalUnitType,
    NodeType,
    RelationType,
    ReviewStatus,
)
from app.platform.graph.fakes import InMemoryGraphStore


class TestEducationalUnit:
    """EducationalUnit CRUD operations."""

    def test_create_unit(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Test Course",
            version=1,
        )
        created = store.create_unit(unit)
        assert created.unit_id == EducationalUnitId("u-001")
        assert created.title == "Test Course"
        assert created.unit_type == EducationalUnitType.COURSE
        assert created.version == 1
        assert created.ontology_version == "edu-graph/1.0"

    def test_get_unit(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Test Course",
            version=1,
        )
        store.create_unit(unit)
        retrieved = store.get_unit(EducationalUnitId("u-001"))
        assert retrieved is not None
        assert retrieved.unit_id == EducationalUnitId("u-001")
        assert retrieved.title == "Test Course"

    def test_get_unit_not_found(self, store: InMemoryGraphStore):
        assert store.get_unit(EducationalUnitId("nonexistent")) is None

    def test_update_unit(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Test Course",
            version=1,
        )
        store.create_unit(unit)
        unit.title = "Updated Course"
        unit.version = 2
        updated = store.update_unit(unit)
        assert updated.title == "Updated Course"
        assert updated.version == 2

    def test_update_unit_not_found(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-999"),
            unit_type=EducationalUnitType.COURSE,
            title="Ghost",
            version=1,
        )
        with pytest.raises(KeyError):
            store.update_unit(unit)

    def test_delete_unit(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Test Course",
            version=1,
        )
        store.create_unit(unit)
        store.delete_unit(EducationalUnitId("u-001"))
        assert store.get_unit(EducationalUnitId("u-001")) is None

    def test_delete_unit_not_found(self, store: InMemoryGraphStore):
        with pytest.raises(KeyError):
            store.delete_unit(EducationalUnitId("nonexistent"))

    def test_create_unit_duplicate_id(self, store: InMemoryGraphStore):
        unit = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Original",
            version=1,
        )
        store.create_unit(unit)
        duplicate = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.CHAPTER,
            title="Duplicate",
            version=1,
        )
        with pytest.raises(ValueError):
            store.create_unit(duplicate)

    def test_create_chapter_unit(self, store: InMemoryGraphStore):
        course = EducationalUnit(
            unit_id=EducationalUnitId("u-001"),
            unit_type=EducationalUnitType.COURSE,
            title="Math 101",
            version=1,
        )
        store.create_unit(course)
        chapter = EducationalUnit(
            unit_id=EducationalUnitId("u-002"),
            unit_type=EducationalUnitType.CHAPTER,
            title="Algebra",
            parent_id=EducationalUnitId("u-001"),
            ordinal=1,
            version=1,
        )
        created = store.create_unit(chapter)
        assert created.parent_id == EducationalUnitId("u-001")
        assert created.ordinal == 1


class TestGraphNode:
    """GraphNode CRUD operations."""

    def test_create_node(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Binary Tree",
            properties={"domain": "computer_science"},
        )
        created = store.create_node(node)
        assert created.node_id == NodeId("n-001")
        assert created.status == ReviewStatus.PROPOSED
        assert created.canonical_key == "binary_tree"
        assert created.ontology_version == "edu-graph/1.0"

    def test_get_node(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Binary Tree",
        )
        store.create_node(node)
        retrieved = store.get_node(NodeId("n-001"))
        assert retrieved is not None
        assert retrieved.label == "Binary Tree"

    def test_get_node_not_found(self, store: InMemoryGraphStore):
        assert store.get_node(NodeId("nonexistent")) is None

    def test_get_nodes_by_ids(self, store: InMemoryGraphStore):
        n1 = GraphNode(node_id=NodeId("n-001"), unit_id=EducationalUnitId("u-001"), node_type=NodeType.CONCEPT, label="A")
        n2 = GraphNode(node_id=NodeId("n-002"), unit_id=EducationalUnitId("u-001"), node_type=NodeType.DEFINITION, label="B")
        n3 = GraphNode(node_id=NodeId("n-003"), unit_id=EducationalUnitId("u-001"), node_type=NodeType.FORMULA, label="C")
        store.create_node(n1)
        store.create_node(n2)
        store.create_node(n3)

        result = store.get_nodes_by_ids({NodeId("n-001"), NodeId("n-003"), NodeId("n-999")})
        assert len(result) == 2
        assert NodeId("n-001") in result
        assert NodeId("n-003") in result
        assert NodeId("n-999") not in result

    def test_update_node(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Original Label",
        )
        store.create_node(node)
        node.label = "Updated Label"
        node.confidence = 0.95
        updated = store.update_node(node)
        assert updated.label == "Updated Label"
        assert updated.confidence == 0.95

    def test_update_node_not_found(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-999"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Ghost",
        )
        with pytest.raises(KeyError):
            store.update_node(node)

    def test_delete_node(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Delete Me",
        )
        store.create_node(node)
        store.delete_node(NodeId("n-001"))
        assert store.get_node(NodeId("n-001")) is None

    def test_delete_node_not_found(self, store: InMemoryGraphStore):
        with pytest.raises(KeyError):
            store.delete_node(NodeId("nonexistent"))

    def test_create_node_duplicate_id(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Original",
        )
        store.create_node(node)
        duplicate = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.DEFINITION,
            label="Duplicate",
        )
        with pytest.raises(ValueError):
            store.create_node(duplicate)

    def test_canonical_key_auto_generated(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Binary Search Tree",
        )
        assert node.canonical_key == "binary_search_tree"

    def test_canonical_key_explicit(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="BST",
            canonical_key="binary_search_tree",
        )
        assert node.canonical_key == "binary_search_tree"

    def test_node_aliases(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Binary Tree",
            aliases=["BT", "B-tree (incorrect)", "二叉树"],
        )
        store.create_node(node)
        retrieved = store.get_node(NodeId("n-001"))
        assert retrieved is not None
        assert len(retrieved.aliases) == 3
        assert "BT" in retrieved.aliases


class TestGraphRelation:
    """GraphRelation CRUD operations."""

    def test_create_relation(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        created = store.create_relation(rel)
        assert created.relation_id == RelationId("r-001")
        assert created.status == ReviewStatus.PROPOSED
        assert created.directed is True

    def test_create_undirected_relation(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.RELATED_TO,
        )
        created = store.create_relation(rel)
        assert created.directed is False

    def test_get_relation(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        store.create_relation(rel)
        retrieved = store.get_relation(RelationId("r-001"))
        assert retrieved is not None
        assert retrieved.source_id == NodeId("n-001")
        assert retrieved.target_id == NodeId("n-002")

    def test_get_relation_not_found(self, store: InMemoryGraphStore):
        assert store.get_relation(RelationId("nonexistent")) is None

    def test_delete_relation(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        store.create_relation(rel)
        store.delete_relation(RelationId("r-001"))
        assert store.get_relation(RelationId("r-001")) is None

    def test_delete_relation_not_found(self, store: InMemoryGraphStore):
        with pytest.raises(KeyError):
            store.delete_relation(RelationId("nonexistent"))

    def test_create_relation_missing_source(self, store: InMemoryGraphStore):
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        with pytest.raises(KeyError):
            store.create_relation(rel)

    def test_get_relations_from_node(self, store: InMemoryGraphStore):
        # Create three nodes
        for nid in ["n-001", "n-002", "n-003"]:
            store.create_node(GraphNode(
                node_id=NodeId(nid),
                unit_id=EducationalUnitId("u-001"),
                node_type=NodeType.CONCEPT,
                label=f"Node {nid}",
            ))
        # Create relations: n001 -> n002, n001 -> n003
        store.create_relation(GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        ))
        store.create_relation(GraphRelation(
            relation_id=RelationId("r-002"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-003"),
            relation_type=RelationType.RELATED_TO,
        ))
        relations = store.get_relations_from_node(NodeId("n-001"))
        assert len(relations) == 2
        assert len(store.get_relations_from_node(NodeId("n-002"))) == 1  # n-002 is target of r-001
        assert len(store.get_relations_from_node(NodeId("n-003"))) == 1  # n-003 is target of r-002

    def test_delete_node_with_relations_fails(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        store.create_relation(GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        ))
        with pytest.raises(ValueError):
            store.delete_node(NodeId("n-001"))

    def _create_two_nodes(self, store):
        store.create_node(GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Concept A",
        ))
        store.create_node(GraphNode(
            node_id=NodeId("n-002"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Concept B",
        ))


class TestReviewDecisions:
    """Teacher review decisions: accept/reject with evidence."""

    def test_accept_node_with_evidence(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Test Concept",
        )
        store.create_node(node)

        evidence = self._make_evidence("ev-001")
        accepted = store.accept_node(
            node_id=NodeId("n-001"),
            evidence_bundle=evidence,
            reviewer="teacher-01",
            review_comment="Correct concept",
        )
        assert accepted.status == ReviewStatus.ACCEPTED
        assert "ev-001" in accepted.evidence_ids

    def test_reject_node(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Wrong Concept",
        )
        store.create_node(node)

        rejected = store.reject_node(
            node_id=NodeId("n-001"),
            reviewer="teacher-01",
            review_comment="Incorrect definition",
        )
        assert rejected.status == ReviewStatus.REJECTED

    def test_accept_relation_with_evidence(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        store.create_relation(rel)

        evidence = self._make_evidence("ev-002")
        accepted = store.accept_relation(
            relation_id=RelationId("r-001"),
            evidence_bundle=evidence,
            reviewer="teacher-01",
        )
        assert accepted.status == ReviewStatus.ACCEPTED
        assert "ev-002" in accepted.evidence_ids

    def test_reject_relation(self, store: InMemoryGraphStore):
        self._create_two_nodes(store)
        rel = GraphRelation(
            relation_id=RelationId("r-001"),
            source_id=NodeId("n-001"),
            target_id=NodeId("n-002"),
            relation_type=RelationType.PREREQUISITE_OF,
        )
        store.create_relation(rel)

        rejected = store.reject_relation(
            relation_id=RelationId("r-001"),
            reviewer="teacher-01",
            review_comment="Not a prerequisite",
        )
        assert rejected.status == ReviewStatus.REJECTED

    def test_accept_nonexistent_node(self, store: InMemoryGraphStore):
        evidence = self._make_evidence("ev-001")
        with pytest.raises(KeyError):
            store.accept_node(
                node_id=NodeId("n-999"),
                evidence_bundle=evidence,
                reviewer="teacher-01",
            )

    def test_evidence_retrievable_after_accept(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Test",
        )
        store.create_node(node)
        evidence = self._make_evidence("ev-001")
        store.accept_node(
            node_id=NodeId("n-001"),
            evidence_bundle=evidence,
            reviewer="teacher-01",
        )
        retrieved = store.get_evidence("ev-001")
        assert retrieved is not None
        assert retrieved.bundle_id == "ev-001"

    def _create_two_nodes(self, store):
        store.create_node(GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Concept A",
        ))
        store.create_node(GraphNode(
            node_id=NodeId("n-002"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Concept B",
        ))

    def _make_evidence(self, bundle_id: str):
        from app.platform.evidence.contracts import EvidenceBundle, EvidenceSpan
        return EvidenceBundle(
            bundle_id=bundle_id,
            items=[
                EvidenceSpan(
                    artifact_id="art_001",
                    document_id="doc_001",
                    unit_id="unit_001",
                    block_id="blk_001",
                    text_snippet="Sample evidence text",
                )
            ],
        )


class TestGraphSnapshot:
    """GraphSnapshot lifecycle: create, activate, get active, list."""

    def test_create_snapshot_empty(self, store: InMemoryGraphStore):
        snap = store.create_snapshot(label="empty-snap")
        assert snap.snapshot_id is not None
        assert snap.label == "empty-snap"
        assert len(snap.nodes) == 0
        assert len(snap.relations) == 0

    def test_create_snapshot_with_accepted_content(self, store: InMemoryGraphStore):
        self._setup_accepted_graph(store)

        snap = store.create_snapshot(label="snap-1")
        assert len(snap.nodes) == 2
        assert len(snap.relations) == 1
        assert NodeId("n-001") in snap.nodes
        assert NodeId("n-002") in snap.nodes
        assert RelationId("r-001") in snap.relations

    def test_snapshot_excludes_proposed_content(self, store: InMemoryGraphStore):
        # Create accepted node
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Accepted Concept",
        )
        store.create_node(node)
        evidence = self._make_evidence("ev-001")
        store.accept_node(
            node_id=NodeId("n-001"),
            evidence_bundle=evidence,
            reviewer="teacher-01",
        )
        # Create proposed node (no accept)
        proposed = GraphNode(
            node_id=NodeId("n-002"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Proposed Concept",
        )
        store.create_node(proposed)

        snap = store.create_snapshot(label="snap-1")
        assert NodeId("n-001") in snap.nodes
        assert NodeId("n-002") not in snap.nodes

    def test_activate_snapshot(self, store: InMemoryGraphStore):
        snap = store.create_snapshot(label="snap-1")
        store.activate_snapshot(snap.snapshot_id)
        active = store.get_active_snapshot()
        assert active is not None
        assert active.snapshot_id == snap.snapshot_id
        assert active.label == snap.label

    def test_activate_nonexistent_snapshot(self, store: InMemoryGraphStore):
        with pytest.raises(KeyError):
            store.activate_snapshot(SnapshotId("nonexistent"))

    def test_get_active_snapshot_returns_none_when_none_active(
        self, store: InMemoryGraphStore
    ):
        assert store.get_active_snapshot() is None

    def test_list_snapshots(self, store: InMemoryGraphStore):
        snap1 = store.create_snapshot(label="snap-1")
        snap2 = store.create_snapshot(label="snap-2")
        snapshots = store.list_snapshots()
        assert len(snapshots) == 2
        ids = {s.snapshot_id for s in snapshots}
        assert snap1.snapshot_id in ids
        assert snap2.snapshot_id in ids

    def test_snapshot_immutable_after_create(self, store: InMemoryGraphStore):
        snap = store.create_snapshot(label="snap-1")
        with pytest.raises(Exception):
            snap.nodes = {}  # frozen=True prevents attribute reassignment

    def test_rollback_via_activate_previous(self, store: InMemoryGraphStore):
        """Simulate rollback by activating a previous snapshot."""
        snap1 = store.create_snapshot(label="v1")
        store.activate_snapshot(snap1.snapshot_id)
        snap2 = store.create_snapshot(label="v2")
        store.activate_snapshot(snap2.snapshot_id)
        # Rollback to v1
        store.activate_snapshot(snap1.snapshot_id)
        active = store.get_active_snapshot()
        assert active is not None
        assert active.snapshot_id == snap1.snapshot_id

    def test_get_snapshot_by_id(self, store: InMemoryGraphStore):
        snap = store.create_snapshot(label="snap-1")
        retrieved = store.get_snapshot(snap.snapshot_id)
        assert retrieved is not None
        assert retrieved.snapshot_id == snap.snapshot_id

    def test_get_snapshot_not_found(self, store: InMemoryGraphStore):
        assert store.get_snapshot(SnapshotId("nonexistent")) is None

    def _setup_accepted_graph(self, store):
        n1 = GraphNode(node_id=NodeId("n-001"), unit_id=EducationalUnitId("u-001"),
                        node_type=NodeType.CONCEPT, label="Accepted A")
        n2 = GraphNode(node_id=NodeId("n-002"), unit_id=EducationalUnitId("u-001"),
                        node_type=NodeType.CONCEPT, label="Accepted B")
        store.create_node(n1)
        store.create_node(n2)

        evidence = self._make_evidence("ev-001")
        store.accept_node(NodeId("n-001"), evidence, "teacher-01")
        store.accept_node(NodeId("n-002"), evidence, "teacher-01")

        rel = GraphRelation(relation_id=RelationId("r-001"),
                            source_id=NodeId("n-001"),
                            target_id=NodeId("n-002"),
                            relation_type=RelationType.PREREQUISITE_OF)
        store.create_relation(rel)
        store.accept_relation(RelationId("r-001"), evidence, "teacher-01")

    def _make_evidence(self, bundle_id: str):
        from app.platform.evidence.contracts import EvidenceBundle, EvidenceSpan
        return EvidenceBundle(
            bundle_id=bundle_id,
            items=[
                EvidenceSpan(
                    artifact_id="art_001",
                    document_id="doc_001",
                    unit_id="unit_001",
                    block_id="blk_001",
                    text_snippet="Sample evidence text",
                )
            ],
        )


class TestEvidenceRetrieval:
    """Evidence bundle storage and retrieval."""

    def test_get_evidence_bundle(self, store: InMemoryGraphStore):
        node = GraphNode(
            node_id=NodeId("n-001"),
            unit_id=EducationalUnitId("u-001"),
            node_type=NodeType.CONCEPT,
            label="Test",
        )
        store.create_node(node)

        ev1 = self._make_evidence("ev-001")
        ev2 = self._make_evidence("ev-002")
        store.accept_node(NodeId("n-001"), ev1, "teacher-01")

        # Store another evidence directly via accept
        n2 = GraphNode(node_id=NodeId("n-002"), unit_id=EducationalUnitId("u-001"),
                        node_type=NodeType.CONCEPT, label="Test 2")
        store.create_node(n2)
        store.accept_node(NodeId("n-002"), ev2, "teacher-01")

        result = store.get_evidence_bundle({"ev-001", "ev-002", "ev-999"})
        assert len(result) == 2
        assert "ev-001" in result
        assert "ev-002" in result
        assert "ev-999" not in result

    def test_get_nonexistent_evidence(self, store: InMemoryGraphStore):
        assert store.get_evidence("nonexistent") is None

    def _make_evidence(self, bundle_id: str):
        from app.platform.evidence.contracts import EvidenceBundle, EvidenceSpan
        return EvidenceBundle(
            bundle_id=bundle_id,
            items=[
                EvidenceSpan(
                    artifact_id="art_001",
                    document_id="doc_001",
                    unit_id="unit_001",
                    block_id="blk_001",
                    text_snippet="Sample evidence text",
                )
            ],
        )
