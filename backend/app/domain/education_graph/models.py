"""Education graph domain models.

These are NOT ORM models -- they are pure domain dataclasses that P1-09
will map to persistence.  They only reference P1-01 DocumentIR stable IDs
and P1-03 Evidence contracts (both frozen at G2).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.education_graph.enums import (
    EducationalUnitType,
    NodeType,
    ONTOLOGY_VERSION,
    RelationType,
    ReviewStatus,
)

# ---------------------------------------------------------------------------
# Stable ID types (opaque string newtypes)
# ---------------------------------------------------------------------------
# These are strings with a prefix convention (e.g. "edu_u_001", "n_001").
# In production they will be UUIDv5 deterministic IDs.
# For the in-memory fake we use short human-readable strings.

EducationalUnitId = str
NodeId = str
RelationId = str
SnapshotId = str


# ---------------------------------------------------------------------------
# EducationalUnit
# ---------------------------------------------------------------------------


@dataclass
class EducationalUnit:
    """A deterministic structural unit in the educational hierarchy.

    Only references DocumentIR stable IDs.  Hierarchy changes are
    version-tracked (``version`` field).
    """

    unit_id: EducationalUnitId
    unit_type: EducationalUnitType
    title: str

    # Hierarchy
    parent_id: Optional[EducationalUnitId] = None
    ordinal: Optional[int] = None

    # DocumentIR references (stable IDs only)
    doc_id: Optional[str] = None  # DocumentIR document_id
    block_ids: List[str] = field(default_factory=list)  # DocumentIR block_ids

    # Versioning
    version: int = 1
    ontology_version: str = ONTOLOGY_VERSION

    # Metadata
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# GraphNode
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A node in the education knowledge graph.

    ``node_id`` is stable across runs (deterministic from content).
    ``status`` follows the ReviewStatus state machine.
    An accepted node MUST have at least one GraphEvidence reference.
    """

    node_id: NodeId
    unit_id: EducationalUnitId
    node_type: NodeType
    label: str  # Primary display name (canonical name)

    # Canonicalization and aliases
    canonical_key: str = ""  # Normalized unique key for dedup
    aliases: List[str] = field(default_factory=list)

    # Properties (type-specific, schema-constrained)
    properties: Dict[str, Any] = field(default_factory=dict)

    # Lifecycle
    status: ReviewStatus = ReviewStatus.PROPOSED
    confidence: float = 0.0  # 0.0-1.0, only meaningful for PROPOSED/NEEDS_REVIEW

    # Evidence references (accepted nodes MUST have at least one)
    evidence_ids: List[str] = field(default_factory=list)

    # Metadata
    ontology_version: str = ONTOLOGY_VERSION
    created_by_run: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.canonical_key:
            # Default canonical key from label (normalized)
            self.canonical_key = self.label.lower().strip().replace(" ", "_")


# ---------------------------------------------------------------------------
# GraphRelation
# ---------------------------------------------------------------------------


@dataclass
class GraphRelation:
    """A directed or undirected edge between two GraphNodes.

    ``relation_id`` is stable across runs.
    ``source_id`` and ``target_id`` MUST reference existing GraphNode IDs.
    Type matrix constraints are enforced at validation time.
    """

    relation_id: RelationId
    source_id: NodeId
    target_id: NodeId
    relation_type: RelationType

    # Direction
    directed: bool = True  # Default True for most relation types

    # Properties
    properties: Dict[str, Any] = field(default_factory=dict)

    # Lifecycle
    status: ReviewStatus = ReviewStatus.PROPOSED
    confidence: float = 0.0

    # Evidence references
    evidence_ids: List[str] = field(default_factory=list)

    # Metadata
    ontology_version: str = ONTOLOGY_VERSION
    created_by_run: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # Undirected relation types
        if self.relation_type in (
            RelationType.CONTRASTS_WITH,
            RelationType.RELATED_TO,
        ):
            self.directed = False


# ---------------------------------------------------------------------------
# GraphSnapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphSnapshot:
    """An immutable snapshot of the graph at a point in time.

    Only ACCEPTED nodes/edges are included.
    The active pointer can be rolled back to a previous snapshot.
    Content is frozen after creation (frozen=True).
    """

    snapshot_id: SnapshotId
    ontology_version: str = ONTOLOGY_VERSION

    # Immutable content
    nodes: Dict[NodeId, GraphNode] = field(default_factory=dict)
    relations: Dict[RelationId, GraphRelation] = field(default_factory=dict)

    # Metadata
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ReviewDecision (teacher review record)
# ---------------------------------------------------------------------------


@dataclass
class ReviewDecision:
    """A teacher review decision on a proposed node or edge.

    Every ACCEPTED node/edge must have at least one ReviewDecision
    that resolves to valid Evidence.
    """

    # Target (required - no defaults)
    target_id: str  # NodeId or RelationId
    target_type: str  # "node" or "relation"

    # Decision (required - no defaults)
    decision: ReviewStatus  # ACCEPTED or REJECTED
    reviewer: str

    # Optional fields
    decision_id: str = field(default_factory=lambda: f"rd_{uuid.uuid4().hex[:12]}")
    review_comment: str = ""
    evidence_bundle_id: Optional[str] = None

    # Audit
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


# Type matrix: allowed (source_type, relation_type, target_type) tuples.
# This is a simplified version -- a full matrix would enumerate all combos.
# Here we define broad rules that validation checks enforce.

STRUCTURAL_NODE_TYPES = {
    NodeType.COURSE,
    NodeType.CHAPTER,
    NodeType.SECTION,
    NodeType.PAGE,
    NodeType.SOURCE_BLOCK,
}

SEMANTIC_NODE_TYPES = {
    NodeType.KNOWLEDGE_POINT,
    NodeType.CONCEPT,
    NodeType.DEFINITION,
    NodeType.FORMULA,
    NodeType.THEOREM,
    NodeType.METHOD,
    NodeType.SKILL,
    NodeType.EXAMPLE,
    NodeType.EXERCISE,
    NodeType.MISCONCEPTION,
    NodeType.LEARNING_OBJECTIVE,
}

ALL_NODE_TYPES = STRUCTURAL_NODE_TYPES | SEMANTIC_NODE_TYPES
