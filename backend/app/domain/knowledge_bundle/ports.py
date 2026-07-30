"""Read-only contracts shared by students, recommendation, and teaching agents.

The public boundary deliberately exposes stable ``kn_*`` identities and an
active bundle version.  GraphRAG run identifiers and storage paths never cross
this boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ActiveKnowledgeBundle:
    bundle_id: str
    course_id: int
    version: int
    graph_snapshot_id: str
    retrieval_snapshot_id: str
    vector_index_id: str


@dataclass(frozen=True)
class KnowledgeNodeView:
    node_key: str
    knowledge_node_id: int
    title: str
    entity_type: str
    description: str = ""
    prerequisites: tuple[str, ...] = ()
    successors: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeGraphView:
    bundle: ActiveKnowledgeBundle
    nodes: tuple[dict, ...]
    relations: tuple[dict, ...]


@dataclass(frozen=True)
class KnowledgeSearchItem:
    node_key: str | None
    knowledge_node_id: int | None
    content: str
    score: float
    retrieval_sources: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    document_id: str | None = None
    page_number: int | None = None


@dataclass(frozen=True)
class KnowledgeSearchResult:
    bundle: ActiveKnowledgeBundle
    query: str
    items: tuple[KnowledgeSearchItem, ...]


class CourseKnowledgeReadPort(Protocol):
    """The only supported learner-facing course knowledge read surface."""

    def get_active_bundle(self, course_id: int) -> ActiveKnowledgeBundle | None:
        ...

    def get_graph(self, course_id: int) -> KnowledgeGraphView | None:
        ...

    def get_node(self, course_id: int, node_key: str) -> KnowledgeNodeView | None:
        ...

    def get_prerequisites(self, course_id: int, node_key: str) -> tuple[str, ...]:
        ...

    def get_successors(self, course_id: int, node_key: str) -> tuple[str, ...]:
        ...

    def search_evidence(
        self,
        course_id: int,
        query: str,
        *,
        top_k: int = 6,
        node_keys: tuple[str, ...] = (),
    ) -> KnowledgeSearchResult | None:
        ...

    def get_citations(
        self,
        course_id: int,
        *,
        node_key: str | None = None,
        citation_ids: tuple[str, ...] = (),
    ) -> tuple[dict, ...]:
        ...
