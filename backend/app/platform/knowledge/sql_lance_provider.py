"""Production CourseKnowledgeReadPort backed by SQL metadata and LanceDB."""
from __future__ import annotations

from sqlmodel import select

from app.domain.knowledge_bundle import (
    ActiveKnowledgeBundle,
    KnowledgeGraphView,
    KnowledgeNodeView,
    KnowledgeSearchItem,
    KnowledgeSearchResult,
)
from app.models.database import session_factory
from app.models.document_parse_model import (
    CitationStatus,
    EvidenceCitation,
    EvidenceRenderAsset,
)
from app.models.graph_production_model import CourseKnowledgeNode, GraphSnapshotRecord
from app.models.knowledge_bundle_model import CourseKnowledgeBundle, CourseVectorIndex
from app.platform.knowledge.embedding import embedding_provider_from_settings
from app.platform.knowledge.lancedb_provider import LanceDbCourseVectorProvider
from app.services.knowledge_bundle_service import knowledge_bundle_service


class SqlLanceCourseKnowledgeProvider:
    """Fail-closed read adapter for the single active Bundle."""

    def __init__(
        self,
        *,
        vector_provider=None,
        allow_legacy_graph_fallback: bool = False,
    ) -> None:
        self._vector_provider = vector_provider
        self._allow_legacy_graph_fallback = allow_legacy_graph_fallback

    def get_active_bundle(self, course_id: int) -> ActiveKnowledgeBundle | None:
        with session_factory() as session:
            bundle = knowledge_bundle_service.get_active_bundle(session, course_id)
            if bundle:
                return _bundle_view(bundle)
            if self._allow_legacy_graph_fallback:
                snapshot = _legacy_active_snapshot(session, course_id)
                if snapshot:
                    return _legacy_bundle_view(snapshot)
            return None

    def get_graph(self, course_id: int) -> KnowledgeGraphView | None:
        with session_factory() as session:
            bundle = knowledge_bundle_service.get_active_bundle(session, course_id)
            if bundle is None:
                if not self._allow_legacy_graph_fallback:
                    return None
                snapshot = _legacy_active_snapshot(session, course_id)
                if snapshot is None:
                    return None
                return KnowledgeGraphView(
                    bundle=_legacy_bundle_view(snapshot),
                    nodes=tuple(snapshot.nodes or []),
                    relations=tuple(snapshot.relations or []),
                )
            snapshot = session.exec(select(GraphSnapshotRecord).where(
                GraphSnapshotRecord.course_id == course_id,
                GraphSnapshotRecord.snapshot_id == bundle.graph_snapshot_id,
            )).first()
            if snapshot is None:
                return None
            return KnowledgeGraphView(
                bundle=_bundle_view(bundle),
                nodes=tuple(snapshot.nodes or []),
                relations=tuple(snapshot.relations or []),
            )

    def get_node(self, course_id: int, node_key: str) -> KnowledgeNodeView | None:
        graph = self.get_graph(course_id)
        if graph is None:
            return None
        payload = next(
            (node for node in graph.nodes if str(node.get("id")) == node_key),
            None,
        )
        if payload is None:
            return None
        prerequisites = self._neighbors(graph, node_key, incoming=True)
        successors = self._neighbors(graph, node_key, incoming=False)
        identity_id = int(payload.get("identity_id") or 0)
        if identity_id <= 0:
            return None
        citation_ids = tuple(str(item) for item in payload.get("citation_ids") or [])
        return KnowledgeNodeView(
            node_key=node_key,
            knowledge_node_id=identity_id,
            title=str(payload.get("title") or payload.get("label") or ""),
            entity_type=str(payload.get("type") or payload.get("kind") or "concept"),
            description=str(payload.get("description") or ""),
            prerequisites=prerequisites,
            successors=successors,
            evidence_ids=tuple(str(item) for item in payload.get("evidence_ids") or []),
            citation_ids=citation_ids,
            metadata={
                "bundle_id": graph.bundle.bundle_id,
                "graph_snapshot_id": graph.bundle.graph_snapshot_id,
            },
        )

    def get_prerequisites(self, course_id: int, node_key: str) -> tuple[str, ...]:
        graph = self.get_graph(course_id)
        return self._neighbors(graph, node_key, incoming=True) if graph else ()

    def get_successors(self, course_id: int, node_key: str) -> tuple[str, ...]:
        graph = self.get_graph(course_id)
        return self._neighbors(graph, node_key, incoming=False) if graph else ()

    def search_evidence(
        self,
        course_id: int,
        query: str,
        *,
        top_k: int = 6,
        node_keys: tuple[str, ...] = (),
    ) -> KnowledgeSearchResult | None:
        with session_factory() as session:
            bundle = knowledge_bundle_service.get_active_bundle(session, course_id)
            if bundle is None or not bundle.vector_index_id:
                return None
            vector_index = session.exec(select(CourseVectorIndex).where(
                CourseVectorIndex.course_id == course_id,
                CourseVectorIndex.vector_index_id == bundle.vector_index_id,
            )).first()
            if vector_index is None:
                return None
            identities = {
                node.node_key: int(node.id)
                for node in session.exec(select(CourseKnowledgeNode).where(
                    CourseKnowledgeNode.course_id == course_id,
                )).all()
            }
        provider = self._vector_provider or LanceDbCourseVectorProvider(
            embedding_provider=embedding_provider_from_settings()
        )
        rows = provider.search(
            course_id=course_id,
            bundle_id=bundle.bundle_id,
            query=query,
            top_k=top_k,
            node_keys=node_keys,
        )
        items = tuple(KnowledgeSearchItem(
            node_key=(str(row.get("node_key")) or None),
            knowledge_node_id=(
                int(row.get("knowledge_node_id"))
                if int(row.get("knowledge_node_id") or 0) > 0
                else identities.get(str(row.get("node_key") or ""))
            ),
            content=str(row.get("text") or ""),
            score=float(row.get("score") or 0.0),
            retrieval_sources=tuple(row.get("retrieval_sources") or []),
            evidence_ids=tuple(str(item) for item in row.get("evidence_ids") or []),
            citation_ids=tuple(str(item) for item in row.get("citation_ids") or []),
            document_id=str(row.get("document_id") or "") or None,
            page_number=int(row.get("page_number") or 0) or None,
        ) for row in rows)
        return KnowledgeSearchResult(
            bundle=_bundle_view(bundle),
            query=query,
            items=items,
        )

    def get_citations(
        self,
        course_id: int,
        *,
        node_key: str | None = None,
        citation_ids: tuple[str, ...] = (),
    ) -> tuple[dict, ...]:
        with session_factory() as session:
            bundle = knowledge_bundle_service.get_active_bundle(session, course_id)
            if bundle is None:
                return ()
            allowed_ids = set(citation_ids)
            if node_key:
                snapshot = session.exec(select(GraphSnapshotRecord).where(
                    GraphSnapshotRecord.course_id == course_id,
                    GraphSnapshotRecord.snapshot_id == bundle.graph_snapshot_id,
                )).first()
                node = next((
                    item for item in (snapshot.nodes if snapshot else [])
                    if str(item.get("id")) == node_key
                ), None)
                if node is None:
                    return ()
                allowed_ids.update(str(item) for item in node.get("citation_ids") or [])
            if not allowed_ids:
                return ()
            rows = session.exec(select(EvidenceCitation).where(
                EvidenceCitation.course_id == course_id,
                EvidenceCitation.citation_id.in_(sorted(allowed_ids)),
                EvidenceCitation.student_visible == True,  # noqa: E712
                EvidenceCitation.status.in_([CitationStatus.EXACT, CitationStatus.APPROXIMATE]),
            )).all()
            result: list[dict] = []
            for row in rows:
                asset = session.exec(select(EvidenceRenderAsset).where(
                    EvidenceRenderAsset.course_id == course_id,
                    EvidenceRenderAsset.citation_id == row.citation_id,
                )).first()
                if asset is None:
                    asset = session.exec(select(EvidenceRenderAsset).where(
                        EvidenceRenderAsset.course_id == course_id,
                        EvidenceRenderAsset.document_id == row.document_id,
                        EvidenceRenderAsset.run_id == row.run_id,
                        EvidenceRenderAsset.page_number == row.page_number,
                        EvidenceRenderAsset.asset_type == "page_image",
                    )).first()
                result.append({
                    "citation_id": row.citation_id,
                    "evidence_id": row.evidence_id,
                    "document_id": row.document_id,
                    "source_file": row.source_file,
                    "source_type": row.source_type,
                    "page_number": row.page_number,
                    "bbox": row.bbox,
                    "text_snippet": row.text_snippet,
                    "status": row.status.value,
                    "bundle_id": bundle.bundle_id,
                    "render_url": (
                        f"/api/v1/graph/course/{course_id}/"
                        f"evidence-renders/{asset.asset_id}/content"
                        if asset is not None else None
                    ),
                })
            return tuple(result)

    @staticmethod
    def _neighbors(
        graph: KnowledgeGraphView,
        node_key: str,
        *,
        incoming: bool,
    ) -> tuple[str, ...]:
        values: set[str] = set()
        for relation in graph.relations:
            relation_type = str(
                relation.get("type") or relation.get("relation_type") or ""
            ).casefold()
            if relation_type not in {
                "prerequisite_of", "prerequisite", "requires",
            }:
                continue
            source = str(relation.get("source") or "")
            target = str(relation.get("target") or "")
            if incoming and target == node_key:
                values.add(source)
            elif not incoming and source == node_key:
                values.add(target)
        return tuple(sorted(values))


def _bundle_view(bundle: CourseKnowledgeBundle) -> ActiveKnowledgeBundle:
    return ActiveKnowledgeBundle(
        bundle_id=bundle.bundle_id,
        course_id=bundle.course_id,
        version=bundle.version,
        graph_snapshot_id=bundle.graph_snapshot_id,
        retrieval_snapshot_id=bundle.retrieval_snapshot_id,
        vector_index_id=str(bundle.vector_index_id or ""),
    )


def _legacy_active_snapshot(
    session,
    course_id: int,
) -> GraphSnapshotRecord | None:
    """Transitional read used only by recommendation during Bundle migration."""
    return session.exec(select(GraphSnapshotRecord).where(
        GraphSnapshotRecord.course_id == course_id,
        GraphSnapshotRecord.is_active == True,  # noqa: E712
    ).order_by(GraphSnapshotRecord.version.desc())).first()


def _legacy_bundle_view(snapshot: GraphSnapshotRecord) -> ActiveKnowledgeBundle:
    return ActiveKnowledgeBundle(
        bundle_id="",
        course_id=snapshot.course_id,
        version=snapshot.version,
        graph_snapshot_id=snapshot.snapshot_id,
        retrieval_snapshot_id="",
        vector_index_id="",
    )
