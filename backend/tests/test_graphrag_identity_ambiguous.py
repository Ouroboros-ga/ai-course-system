"""Unit tests: graphrag identity reconcile ambiguity degrades instead of failing."""
from app.models.graph_production_model import (
    CourseKnowledgeNode,
    CourseKnowledgeNodeStatus,
)
from app.services.graphrag_identity_service import (
    GraphRagIdentityService,
    IdentityAmbiguousError,
)


def _node(node_key: str, title: str, anchors: set[str], kind: str = "concept") -> CourseKnowledgeNode:
    return CourseKnowledgeNode(
        course_id=1,
        node_key=node_key,
        title=title,
        kind=kind,
        status=CourseKnowledgeNodeStatus.PUBLISHED,
        source_anchor_ids=sorted(anchors),
        extra_data={},
    )


def test_match_ambiguous_deferred_instead_of_raise() -> None:
    """Two nodes with close scores must degrade, not raise IDENTITY_AMBIGUOUS."""
    nodes = [
        _node("kn_a", "数据结构", {"anc_1", "anc_2", "anc_3"}),
        _node("kn_b", "数据结构", {"anc_1", "anc_2", "anc_4"}),
    ]
    node, method, score = GraphRagIdentityService._match(
        nodes,
        title="数据结构",
        entity_type="concept",
        anchor_ids={"anc_1", "anc_2"},
    )
    assert node is None
    assert method == "ambiguous_deferred"
    assert score == 0.0
    # The error class is retained for compatibility but never raised by _match
    assert IdentityAmbiguousError is not None


def test_match_single_candidate_still_resolves() -> None:
    """A single strong candidate must still match normally."""
    nodes = [
        _node("kn_a", "数据结构", {"anc_1", "anc_2", "anc_3"}),
    ]
    node, method, score = GraphRagIdentityService._match(
        nodes,
        title="数据结构",
        entity_type="concept",
        anchor_ids={"anc_1", "anc_2"},
    )
    assert node is not None
    assert node.node_key == "kn_a"
    assert method == "exact_title_anchor"
    assert score > 0.9
