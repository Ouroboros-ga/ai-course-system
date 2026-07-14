"""Graph validation: ontology type-matrix, structural, and prerequisite-cycle checks.

This module implements the deterministic validation layer required by the
P1-05 charter: validation of types, loops, direction, isolation, and
prerequisites.  It is a pure function layer over ``GraphRelation`` /
``GraphNode`` data - it does NOT mutate state and does NOT call external
services.  Callers (the GraphStore) decide how to act on a
``ValidationResult``: a hard-constraint violation rejects the candidate,
a prerequisite cycle moves the edge to ``needs_review`` (per R2D0 §3:
"PREREQUISITE_OF 必须无环；发现环时边进入 needs_review，不能自动删掉高价值证据").

Reference: docs/refactor/document_kg_v2/R2D0教育知识图谱本体与构建算法.md §3 (关系约束)
and §4.6 (关系验证), §4.7 (先修环检测).

Ontology version: edu-graph/1.0.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from .enums import NodeType, RelationType
from .models import GraphNode, GraphRelation, NodeId, RelationId


# =========================================================================
# Type matrix (from R2D0 ontology §3)
# =========================================================================
#
# Each entry: RelationType -> (
#     frozenset[NodeType] allowed source types,
#     frozenset[NodeType] allowed target types,
#     bool directed,
# )
#
# Self-loops are forbidden for ALL relation types (column "自环 = 否" in
# the ontology table), so self-loop is enforced uniformly rather than
# encoded per-type.
# =========================================================================

_TYPE_MATRIX: Dict[RelationType, Tuple[frozenset, frozenset, bool]] = {
    RelationType.CONTAINS: (
        frozenset({NodeType.COURSE, NodeType.CHAPTER, NodeType.SECTION}),
        frozenset({NodeType.CHAPTER, NodeType.SECTION, NodeType.KNOWLEDGE_POINT, NodeType.LEARNING_OBJECTIVE}),
        True,
    ),
    RelationType.PART_OF: (
        frozenset({NodeType.CHAPTER, NodeType.SECTION, NodeType.KNOWLEDGE_POINT}),
        frozenset({NodeType.COURSE, NodeType.CHAPTER, NodeType.SECTION}),
        True,
    ),
    RelationType.DEFINES: (
        frozenset({NodeType.DEFINITION, NodeType.SOURCE_BLOCK}),
        frozenset({NodeType.CONCEPT, NodeType.KNOWLEDGE_POINT}),
        True,
    ),
    RelationType.EXPLAINS: (
        frozenset({NodeType.SECTION, NodeType.EXAMPLE, NodeType.SOURCE_BLOCK}),
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.FORMULA, NodeType.METHOD}),
        True,
    ),
    RelationType.PREREQUISITE_OF: (
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.SKILL}),
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.SKILL}),
        True,
    ),
    RelationType.DERIVES_FROM: (
        frozenset({NodeType.FORMULA, NodeType.THEOREM, NodeType.METHOD}),
        frozenset({NodeType.FORMULA, NodeType.THEOREM, NodeType.CONCEPT}),
        True,
    ),
    RelationType.USES: (
        frozenset({NodeType.METHOD, NodeType.EXAMPLE, NodeType.EXERCISE, NodeType.SKILL}),
        frozenset({NodeType.CONCEPT, NodeType.KNOWLEDGE_POINT, NodeType.METHOD}),
        True,
    ),
    RelationType.USES_FORMULA: (
        frozenset({NodeType.METHOD, NodeType.EXAMPLE, NodeType.EXERCISE, NodeType.THEOREM}),
        frozenset({NodeType.FORMULA}),
        True,
    ),
    RelationType.HAS_EXAMPLE: (
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.METHOD}),
        frozenset({NodeType.EXAMPLE}),
        True,
    ),
    RelationType.TESTS: (
        frozenset({NodeType.EXERCISE}),
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.SKILL, NodeType.METHOD}),
        True,
    ),
    RelationType.CONTRASTS_WITH: (
        # undirected; "同类兼容类型" - allowed between any semantic node types
        frozenset({NodeType.CONCEPT, NodeType.METHOD, NodeType.MISCONCEPTION}),
        frozenset({NodeType.CONCEPT, NodeType.METHOD, NodeType.MISCONCEPTION}),
        False,
    ),
    RelationType.CAUSES: (
        frozenset({NodeType.CONCEPT, NodeType.KNOWLEDGE_POINT, NodeType.MISCONCEPTION}),
        frozenset({NodeType.CONCEPT, NodeType.KNOWLEDGE_POINT}),
        True,
    ),
    RelationType.RELATED_TO: (
        # undirected; "同类" - same-type semantic nodes
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.METHOD}),
        frozenset({NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.METHOD}),
        False,
    ),
    RelationType.SUPPORTED_BY: (
        frozenset({
            NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT, NodeType.DEFINITION,
            NodeType.FORMULA, NodeType.THEOREM, NodeType.METHOD, NodeType.SKILL,
            NodeType.EXAMPLE, NodeType.EXERCISE, NodeType.MISCONCEPTION,
            NodeType.LEARNING_OBJECTIVE,
        }),
        frozenset({NodeType.SOURCE_BLOCK}),
        True,
    ),
    RelationType.APPEARS_ON: (
        frozenset({
            NodeType.SOURCE_BLOCK, NodeType.KNOWLEDGE_POINT, NodeType.CONCEPT,
            NodeType.DEFINITION, NodeType.FORMULA, NodeType.THEOREM,
            NodeType.METHOD, NodeType.EXAMPLE, NodeType.EXERCISE,
        }),
        frozenset({NodeType.PAGE}),
        True,
    ),
}


# =========================================================================
# Reason codes (stable, per P1-00 contract stability rules)
# =========================================================================


class ValidationReason(str, Enum):
    """Stable reason codes for graph validation violations."""

    SELF_LOOP = "self_loop"
    """source_id == target_id; forbidden for all relation types."""

    TYPE_MATRIX_VIOLATION_SOURCE = "type_matrix_violation_source"
    """source node type not allowed for this relation type."""

    TYPE_MATRIX_VIOLATION_TARGET = "type_matrix_violation_target"
    """target node type not allowed for this relation type."""

    DUPLICATE_EDGE = "duplicate_edge"
    """An equivalent edge already exists (same endpoints + type + direction)."""

    PREREQUISITE_CYCLE = "prerequisite_cycle"
    """Accepting this PREREQUISITE_OF edge would create a cycle (non-DAG)."""

    UNKNOWN_RELATION_TYPE = "unknown_relation_type"
    """Relation type not present in the type matrix."""


# Hard-constraint violations: candidate must be REJECTED.
_HARD_VIOLATIONS = frozenset({
    ValidationReason.SELF_LOOP,
    ValidationReason.TYPE_MATRIX_VIOLATION_SOURCE,
    ValidationReason.TYPE_MATRIX_VIOLATION_TARGET,
    ValidationReason.UNKNOWN_RELATION_TYPE,
})

# Soft-constraint violations: candidate moves to NEEDS_REVIEW (not auto-delete).
_SOFT_VIOLATIONS = frozenset({
    ValidationReason.DUPLICATE_EDGE,
    ValidationReason.PREREQUISITE_CYCLE,
})


# =========================================================================
# Validation result
# =========================================================================


@dataclass(frozen=True)
class Violation:
    """A single validation violation."""

    reason: ValidationReason
    detail: str
    relation_id: Optional[RelationId] = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating a graph relation against the ontology.

    ``ok`` is True when there are no violations.  Callers map violations
    to review status:
    - hard violation (self-loop, type-matrix, unknown type) -> REJECT
    - soft violation (duplicate, prerequisite cycle) -> NEEDS_REVIEW
    - no violation -> can ACCEPT (still requires evidence, enforced separately)
    """

    ok: bool
    violations: List[Violation] = field(default_factory=list)

    @property
    def has_hard_violation(self) -> bool:
        return any(v.reason in _HARD_VIOLATIONS for v in self.violations)

    @property
    def has_soft_violation(self) -> bool:
        return any(v.reason in _SOFT_VIOLATIONS for v in self.violations)

    @staticmethod
    def ok_result() -> "ValidationResult":
        return ValidationResult(ok=True, violations=[])

    @staticmethod
    def fail(violations: List[Violation]) -> "ValidationResult":
        return ValidationResult(ok=False, violations=violations)


# =========================================================================
# Validation functions
# =========================================================================


def _edge_signature(relation: GraphRelation) -> Tuple:
    """Canonical signature for duplicate-edge detection.

    For directed relations, (source, target, type) distinguishes A->B from B->A.
    For undirected relations, endpoints are sorted so A-B == B-A.
    """
    if relation.directed:
        return (relation.source_id, relation.target_id, relation.relation_type)
    endpoints = tuple(sorted([str(relation.source_id), str(relation.target_id)]))
    return (endpoints[0], endpoints[1], relation.relation_type)


def validate_relation(
    relation: GraphRelation,
    source_node: GraphNode,
    target_node: GraphNode,
    existing_relations: Optional[List[GraphRelation]] = None,
) -> ValidationResult:
    """Validate a single relation against the ontology type matrix.

    Checks (in order):
    1. Self-loop: source_id == target_id (forbidden for all types).
    2. Unknown relation type (not in type matrix).
    3. Type matrix: source/target node types allowed for this relation type.
    4. Duplicate edge: same canonical signature already exists.

    Prerequisite-cycle detection is NOT done here (it requires the full
    accepted-edge set); use ``detect_prerequisite_cycle`` before accepting
    a PREREQUISITE_OF edge.

    Parameters
    ----------
    relation : GraphRelation
        The candidate relation.
    source_node, target_node : GraphNode
        The resolved endpoint nodes (caller must ensure they exist).
    existing_relations : list, optional
        Existing relations to check for duplicates (typically the
        accepted + proposed set in the store).

    Returns
    -------
    ValidationResult
    """
    violations: List[Violation] = []

    # 1. Self-loop (forbidden for all relation types)
    if relation.source_id == relation.target_id:
        violations.append(Violation(
            reason=ValidationReason.SELF_LOOP,
            detail=f"Self-loop forbidden: source and target are both {relation.source_id}",
            relation_id=relation.relation_id,
        ))
        # Self-loop is a hard violation; type-matrix is moot. Return early.
        return ValidationResult.fail(violations)

    # 2. Unknown relation type
    if relation.relation_type not in _TYPE_MATRIX:
        violations.append(Violation(
            reason=ValidationReason.UNKNOWN_RELATION_TYPE,
            detail=f"Relation type {relation.relation_type} not in ontology type matrix",
            relation_id=relation.relation_id,
        ))
        return ValidationResult.fail(violations)

    allowed_sources, allowed_targets, expected_directed = _TYPE_MATRIX[relation.relation_type]

    # 3a. Type matrix - source
    if source_node.node_type not in allowed_sources:
        violations.append(Violation(
            reason=ValidationReason.TYPE_MATRIX_VIOLATION_SOURCE,
            detail=(
                f"Source node type {source_node.node_type} not allowed for "
                f"{relation.relation_type}; allowed sources: "
                f"{sorted(t.value for t in allowed_sources)}"
            ),
            relation_id=relation.relation_id,
        ))

    # 3b. Type matrix - target
    if target_node.node_type not in allowed_targets:
        violations.append(Violation(
            reason=ValidationReason.TYPE_MATRIX_VIOLATION_TARGET,
            detail=(
                f"Target node type {target_node.node_type} not allowed for "
                f"{relation.relation_type}; allowed targets: "
                f"{sorted(t.value for t in allowed_targets)}"
            ),
            relation_id=relation.relation_id,
        ))

    # 4. Duplicate edge
    if existing_relations:
        new_sig = _edge_signature(relation)
        for existing in existing_relations:
            if existing.relation_id == relation.relation_id:
                continue  # self (update case)
            if _edge_signature(existing) == new_sig:
                violations.append(Violation(
                    reason=ValidationReason.DUPLICATE_EDGE,
                    detail=(
                        f"Duplicate edge: equivalent to existing relation "
                        f"{existing.relation_id}"
                    ),
                    relation_id=relation.relation_id,
                ))
                break

    if violations:
        return ValidationResult.fail(violations)
    return ValidationResult.ok_result()


# =========================================================================
# Prerequisite cycle detection (DAG enforcement for PREREQUISITE_OF)
# =========================================================================


def detect_prerequisite_cycle(
    candidate_relation: GraphRelation,
    accepted_relations: List[GraphRelation],
) -> Optional[List[NodeId]]:
    """Detect whether accepting a PREREQUISITE_OF edge creates a cycle.

    Builds a directed graph from existing accepted PREREQUISITE_OF edges
    plus the candidate edge, then runs a DFS cycle detection.  Returns
    the cycle path (list of node IDs) if a cycle is found, else None.

    Only PREREQUISITE_OF edges participate (per R2D0 §3: "PREREQUISITE_OF
    必须无环").  Other relation types do not form the prerequisite DAG.

    Parameters
    ----------
    candidate_relation : GraphRelation
        The PREREQUISITE_OF edge being considered for acceptance.
    accepted_relations : list
        Already-accepted relations (only PREREQUISITE_OF ones are used).

    Returns
    -------
    list of NodeId or None
        The cycle path if a cycle would be created, else None.
    """
    if candidate_relation.relation_type != RelationType.PREREQUISITE_OF:
        return None

    # Build adjacency: source -> set of targets, from accepted prereq edges
    adj: Dict[NodeId, Set[NodeId]] = defaultdict(set)
    for rel in accepted_relations:
        if rel.relation_type == RelationType.PREREQUISITE_OF:
            adj[rel.source_id].add(rel.target_id)
    # Add candidate edge
    adj[candidate_relation.source_id].add(candidate_relation.target_id)

    # DFS cycle detection (white/gray/black coloring)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[NodeId, int] = defaultdict(lambda: WHITE)
    parent: Dict[NodeId, Optional[NodeId]] = {}

    def _dfs(start: NodeId) -> Optional[List[NodeId]]:
        stack: List[Tuple[NodeId, int]] = [(start, 0)]
        color[start] = GRAY
        path: List[NodeId] = [start]
        while stack:
            node, idx = stack[-1]
            neighbors = sorted(adj.get(node, []), key=str)
            if idx < len(neighbors):
                stack[-1] = (node, idx + 1)
                nxt = neighbors[idx]
                if color[nxt] == GRAY:
                    # Found cycle: extract from path
                    cycle_start = path.index(nxt)
                    return path[cycle_start:] + [nxt]
                elif color[nxt] == WHITE:
                    color[nxt] = GRAY
                    parent[nxt] = node
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = BLACK
                stack.pop()
                if path:
                    path.pop()
        return None

    # Run DFS from candidate source (cycle must involve the new edge)
    cycle = _dfs(candidate_relation.source_id)
    return cycle


def validate_relation_full(
    relation: GraphRelation,
    source_node: GraphNode,
    target_node: GraphNode,
    existing_relations: Optional[List[GraphRelation]] = None,
    accepted_relations: Optional[List[GraphRelation]] = None,
) -> ValidationResult:
    """Full validation: type-matrix + structural + prerequisite-cycle.

    Convenience wrapper combining ``validate_relation`` and
    ``detect_prerequisite_cycle``.  A prerequisite cycle is a soft
    violation (NEEDS_REVIEW), not a rejection.
    """
    result = validate_relation(relation, source_node, target_node, existing_relations)
    if result.has_hard_violation:
        return result  # hard violation short-circuits

    violations = list(result.violations)
    if relation.relation_type == RelationType.PREREQUISITE_OF and accepted_relations is not None:
        cycle = detect_prerequisite_cycle(relation, accepted_relations)
        if cycle is not None:
            violations.append(Violation(
                reason=ValidationReason.PREREQUISITE_CYCLE,
                detail=(
                    f"Accepting this PREREQUISITE_OF edge creates a cycle: "
                    f"{' -> '.join(str(n) for n in cycle)}"
                ),
                relation_id=relation.relation_id,
            ))

    if violations:
        return ValidationResult.fail(violations)
    return ValidationResult.ok_result()


def suggest_review_status(result: ValidationResult) -> "ReviewStatus":
    """Map a ValidationResult to the recommended ReviewStatus.

    - hard violation -> REJECTED
    - soft violation only -> NEEDS_REVIEW
    - no violation -> PROPOSED (can proceed to ACCEPT once evidence provided)
    """
    from .enums import ReviewStatus
    if result.has_hard_violation:
        return ReviewStatus.REJECTED
    if result.has_soft_violation:
        return ReviewStatus.NEEDS_REVIEW
    return ReviewStatus.PROPOSED


# =========================================================================
# Isolation check (soft advisory)
# =========================================================================


def find_isolated_accepted_nodes(
    nodes: Dict[NodeId, GraphNode],
    relations: List[GraphRelation],
) -> List[NodeId]:
    """Return IDs of ACCEPTED nodes that have no ACCEPTED relation.

    This is an advisory isolation check (not a hard constraint): an
    accepted node with no accepted edges is structurally orphaned and
    may indicate incomplete extraction.  Per the charter this is a
    "validation of isolation" - surfaced for review, not auto-rejected.
    """
    from .enums import ReviewStatus
    connected: Set[NodeId] = set()
    for rel in relations:
        if rel.status == ReviewStatus.ACCEPTED:
            connected.add(rel.source_id)
            connected.add(rel.target_id)
    return [
        nid for nid, node in nodes.items()
        if node.status == ReviewStatus.ACCEPTED and nid not in connected
    ]
