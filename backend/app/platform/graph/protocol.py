"""GraphStore abstract protocol for the education knowledge graph.

This is a sync ABC (not async) because the in-memory fake is sync.
P1-09 may add async wrappers for the actual DB implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

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


class GraphStore(ABC):
    """Abstract graph store interface.

    Implementations: InMemoryGraphStore (testing), JSON store, SQL/ORM (P1-09).
    """

    # ---- EducationalUnit CRUD ----

    @abstractmethod
    def create_unit(self, unit: EducationalUnit) -> EducationalUnit:
        """Create a new educational unit. Raises if unit_id already exists."""
        ...

    @abstractmethod
    def get_unit(self, unit_id: EducationalUnitId) -> Optional[EducationalUnit]:
        """Get a unit by ID, or None."""
        ...

    @abstractmethod
    def update_unit(self, unit: EducationalUnit) -> EducationalUnit:
        """Update an existing unit. Raises if not found."""
        ...

    @abstractmethod
    def delete_unit(self, unit_id: EducationalUnitId) -> None:
        """Delete a unit. Raises if not found."""
        ...

    # ---- Node CRUD ----

    @abstractmethod
    def create_node(self, node: GraphNode) -> GraphNode:
        """Create a new graph node. Raises if node_id already exists."""
        ...

    @abstractmethod
    def get_node(self, node_id: NodeId) -> Optional[GraphNode]:
        """Get a node by ID, or None."""
        ...

    @abstractmethod
    def get_nodes_by_ids(self, node_ids: set[NodeId]) -> Dict[NodeId, GraphNode]:
        """Get multiple nodes by IDs. Missing IDs are omitted from the result."""
        ...

    @abstractmethod
    def update_node(self, node: GraphNode) -> GraphNode:
        """Update an existing node. Raises if not found."""
        ...

    @abstractmethod
    def delete_node(self, node_id: NodeId) -> None:
        """Delete a node. Raises if not found. Fails if relations reference it."""
        ...

    # ---- Relation CRUD ----

    @abstractmethod
    def create_relation(self, relation: GraphRelation) -> GraphRelation:
        """Create a new relation. Raises if relation_id or endpoints invalid."""
        ...

    @abstractmethod
    def get_relation(self, relation_id: RelationId) -> Optional[GraphRelation]:
        """Get a relation by ID, or None."""
        ...

    @abstractmethod
    def update_relation(self, relation: GraphRelation) -> GraphRelation:
        """Update an existing relation. Raises if not found."""
        ...

    @abstractmethod
    def delete_relation(self, relation_id: RelationId) -> None:
        """Delete a relation. Raises if not found."""
        ...

    @abstractmethod
    def get_relations_from_node(
        self, node_id: NodeId
    ) -> List[GraphRelation]:
        """Get all relations where node_id is source or target."""
        ...

    # ---- Review decisions ----

    @abstractmethod
    def accept_node(
        self,
        node_id: NodeId,
        evidence_bundle: EvidenceBundle,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphNode:
        """Accept a node with evidence. Raises if node not found or already accepted."""
        ...

    @abstractmethod
    def reject_node(
        self,
        node_id: NodeId,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphNode:
        """Reject a node. Raises if not found."""
        ...

    @abstractmethod
    def accept_relation(
        self,
        relation_id: RelationId,
        evidence_bundle: EvidenceBundle,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphRelation:
        """Accept a relation with evidence."""
        ...

    @abstractmethod
    def reject_relation(
        self,
        relation_id: RelationId,
        reviewer: str,
        review_comment: str = "",
    ) -> GraphRelation:
        """Reject a relation."""
        ...

    # ---- Evidence ----

    @abstractmethod
    def get_evidence(self, evidence_id: str) -> Optional[EvidenceBundle]:
        """Get a single evidence bundle by ID."""
        ...

    @abstractmethod
    def get_evidence_bundle(
        self, evidence_ids: set[str]
    ) -> Dict[str, EvidenceBundle]:
        """Get multiple evidence bundles by IDs."""
        ...

    # ---- Snapshot ----

    @abstractmethod
    def create_snapshot(self, label: str = "") -> GraphSnapshot:
        """Create an immutable snapshot from current ACCEPTED nodes/relations."""
        ...

    @abstractmethod
    def get_snapshot(
        self, snapshot_id: SnapshotId
    ) -> Optional[GraphSnapshot]:
        """Get a snapshot by ID, or None."""
        ...

    @abstractmethod
    def get_active_snapshot(self) -> Optional[GraphSnapshot]:
        """Get the currently active snapshot, or None."""
        ...

    @abstractmethod
    def activate_snapshot(self, snapshot_id: SnapshotId) -> None:
        """Set the active pointer to a snapshot. Raises if not found."""
        ...

    @abstractmethod
    def list_snapshots(self) -> List[GraphSnapshot]:
        """List all snapshots in creation order."""
        ...
