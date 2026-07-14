"""In-memory fake implementation of GraphStore for testing."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.domain.education_graph.enums import ReviewStatus
from app.domain.education_graph.models import (
    EducationalUnit,
    EducationalUnitId,
    GraphNode,
    GraphRelation,
    GraphSnapshot,
    NodeId,
    RelationId,
    SnapshotId,
)
from app.platform.evidence.contracts import EvidenceBundle
from app.platform.graph.protocol import GraphStore


class InMemoryGraphStore(GraphStore):
    """In-memory implementation backed by dicts.

    All data is lost when the instance is garbage-collected.
    Thread-safe only if external locks are used.
    """

    def __init__(self) -> None:
        self._units: Dict[EducationalUnitId, EducationalUnit] = {}
        self._nodes: Dict[NodeId, GraphNode] = {}
        self._relations: Dict[RelationId, GraphRelation] = {}
        self._evidence: Dict[str, EvidenceBundle] = {}
        self._snapshots: Dict[SnapshotId, GraphSnapshot] = {}
        self._active_snapshot_id: Optional[SnapshotId] = None

    # ---- EducationalUnit CRUD ----

    def create_unit(self, unit: EducationalUnit) -> EducationalUnit:
        if unit.unit_id in self._units:
            raise ValueError(f"Unit {unit.unit_id} already exists")
        self._units[unit.unit_id] = unit
        return unit

    def get_unit(self, unit_id: EducationalUnitId) -> Optional[EducationalUnit]:
        return self._units.get(unit_id)

    def update_unit(self, unit: EducationalUnit) -> EducationalUnit:
        if unit.unit_id not in self._units:
            raise KeyError(f"Unit {unit.unit_id} not found")
        self._units[unit.unit_id] = unit
        return unit

    def delete_unit(self, unit_id: EducationalUnitId) -> None:
        if unit_id not in self._units:
            raise KeyError(f"Unit {unit_id} not found")
        del self._units[unit_id]

    # ---- Node CRUD ----

    def create_node(self, node: GraphNode) -> GraphNode:
        if node.node_id in self._nodes:
            raise ValueError(f"Node {node.node_id} already exists")
        self._nodes[node.node_id] = node
        return node

    def get_node(self, node_id: NodeId) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def get_nodes_by_ids(self, node_ids: set[NodeId]) -> Dict[NodeId, GraphNode]:
        return {nid: self._nodes[nid] for nid in node_ids if nid in self._nodes}

    def update_node(self, node: GraphNode) -> GraphNode:
        if node.node_id not in self._nodes:
            raise KeyError(f"Node {node.node_id} not found")
        self._nodes[node.node_id] = node
        return node

    def delete_node(self, node_id: NodeId) -> None:
        if node_id not in self._nodes:
            raise KeyError(f"Node {node_id} not found")
        # Check for relations referencing this node
        for rel in self._relations.values():
            if rel.source_id == node_id or rel.target_id == node_id:
                raise ValueError(
                    f"Cannot delete node {node_id}: referenced by relation {rel.relation_id}"
                )
        del self._nodes[node_id]

    # ---- Relation CRUD ----

    def create_relation(self, relation: GraphRelation) -> GraphRelation:
        if relation.relation_id in self._relations:
            raise ValueError(f"Relation {relation.relation_id} already exists")
        if relation.source_id not in self._nodes:
            raise KeyError(f"Source node {relation.source_id} not found")
        if relation.target_id not in self._nodes:
            raise KeyError(f"Target node {relation.target_id} not found")
        self._relations[relation.relation_id] = relation
        return relation

    def get_relation(self, relation_id: RelationId) -> Optional[GraphRelation]:
        return self._relations.get(relation_id)

    def update_relation(self, relation: GraphRelation) -> GraphRelation:
        if relation.relation_id not in self._relations:
            raise KeyError(f"Relation {relation.relation_id} not found")
        self._relations[relation.relation_id] = relation
        return relation

    def delete_relation(self, relation_id: RelationId) -> None:
        if relation_id not in self._relations:
            raise KeyError(f"Relation {relation_id} not found")
        del self._relations[relation_id]

    def get_relations_from_node(
        self, node_id: NodeId
    ) -> List[GraphRelation]:
        return [
            rel
            for rel in self._relations.values()
            if rel.source_id == node_id or rel.target_id == node_id
        ]

    # ---- Review decisions ----

    def accept_node(
        self,
        node_id: NodeId,
        evidence_bundle: EvidenceBundle,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphNode:
        node = self._get_node_or_raise(node_id)
        node.status = ReviewStatus.ACCEPTED
        # Record evidence reference
        if evidence_bundle.bundle_id not in node.evidence_ids:
            node.evidence_ids.append(evidence_bundle.bundle_id)
        self._evidence[evidence_bundle.bundle_id] = evidence_bundle
        return node

    def reject_node(
        self,
        node_id: NodeId,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphNode:
        node = self._get_node_or_raise(node_id)
        node.status = ReviewStatus.REJECTED
        return node

    def accept_relation(
        self,
        relation_id: RelationId,
        evidence_bundle: EvidenceBundle,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphRelation:
        relation = self._get_relation_or_raise(relation_id)
        relation.status = ReviewStatus.ACCEPTED
        if evidence_bundle.bundle_id not in relation.evidence_ids:
            relation.evidence_ids.append(evidence_bundle.bundle_id)
        self._evidence[evidence_bundle.bundle_id] = evidence_bundle
        return relation

    def reject_relation(
        self,
        relation_id: RelationId,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphRelation:
        relation = self._get_relation_or_raise(relation_id)
        relation.status = ReviewStatus.REJECTED
        return relation

    # ---- Evidence ----

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceBundle]:
        return self._evidence.get(evidence_id)

    def get_evidence_bundle(
        self, evidence_ids: set[str]
    ) -> Dict[str, EvidenceBundle]:
        return {
            eid: self._evidence[eid]
            for eid in evidence_ids
            if eid in self._evidence
        }

    # ---- Snapshot ----

    def create_snapshot(self, label: str = "") -> GraphSnapshot:
        snapshot_id = SnapshotId(f"snap_{uuid.uuid4().hex[:12]}")
        # Collect only ACCEPTED nodes and relations
        accepted_nodes = {
            nid: node
            for nid, node in self._nodes.items()
            if node.status == ReviewStatus.ACCEPTED
        }
        accepted_relations = {
            rid: rel
            for rid, rel in self._relations.items()
            if rel.status == ReviewStatus.ACCEPTED
        }
        snapshot = GraphSnapshot(
            snapshot_id=snapshot_id,
            nodes=accepted_nodes,
            relations=accepted_relations,
            label=label,
        )
        self._snapshots[snapshot_id] = snapshot
        return snapshot

    def get_snapshot(
        self, snapshot_id: SnapshotId
    ) -> Optional[GraphSnapshot]:
        return self._snapshots.get(snapshot_id)

    def get_active_snapshot(self) -> Optional[GraphSnapshot]:
        if self._active_snapshot_id is None:
            return None
        return self._snapshots.get(self._active_snapshot_id)

    def activate_snapshot(self, snapshot_id: SnapshotId) -> None:
        if snapshot_id not in self._snapshots:
            raise KeyError(f"Snapshot {snapshot_id} not found")
        self._active_snapshot_id = snapshot_id

    def list_snapshots(self) -> List[GraphSnapshot]:
        return list(self._snapshots.values())

    # ---- Helpers ----

    def _get_node_or_raise(self, node_id: NodeId) -> GraphNode:
        node = self._nodes.get(node_id)
        if node is None:
            raise KeyError(f"Node {node_id} not found")
        return node

    def _get_relation_or_raise(self, relation_id: RelationId) -> GraphRelation:
        relation = self._relations.get(relation_id)
        if relation is None:
            raise KeyError(f"Relation {relation_id} not found")
        return relation
