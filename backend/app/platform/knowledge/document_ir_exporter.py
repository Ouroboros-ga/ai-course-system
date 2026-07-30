"""Export canonical DocumentIR projections into a reproducible GraphRAG corpus."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlmodel import Session, select

from app.models.document_parse_model import (
    EvidenceAnchor,
    EvidenceCitation,
    EvidenceSpan,
    RetrievalChunk,
)
from app.models.graph_production_model import CourseEvidenceRecord, EvidenceStatus


@dataclass(frozen=True)
class GraphRagInputDocument:
    source_key: str
    course_id: int
    retrieval_chunk_id: str
    document_id: str
    ir_version_id: str
    page_number: int | None
    title: str
    text: str
    content_hash: str
    anchor_ids: tuple[str, ...]
    evidence_span_ids: tuple[str, ...]
    formal_evidence_ids: tuple[str, ...]
    citation_ids: tuple[str, ...]
    initial_status: str


@dataclass(frozen=True)
class GraphRagInputManifest:
    schema_version: str
    course_id: int
    input_content_hash: str
    documents: tuple[GraphRagInputDocument, ...]

    @property
    def chunk_count(self) -> int:
        return len(self.documents)


class CanonicalDocumentIRExporter:
    """Canonical database exporter; it never reparses the uploaded file."""

    schema_version = "course-graphrag-input/1.0"

    def export(
        self,
        session: Session,
        *,
        course_id: int,
        output_dir: Path,
        chunk_ids: set[str] | None = None,
    ) -> GraphRagInputManifest:
        statement = select(RetrievalChunk).where(RetrievalChunk.course_id == course_id)
        if chunk_ids is not None:
            statement = statement.where(RetrievalChunk.chunk_id.in_(sorted(chunk_ids)))
        chunks = sorted(session.exec(statement).all(), key=lambda item: item.chunk_id)
        if not chunks:
            raise ValueError("GRAPH_INPUT_EMPTY")

        anchor_ids = {
            anchor_id
            for chunk in chunks
            for anchor_id in (chunk.anchor_ids or [])
            if anchor_id
        }
        anchors = list(session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == course_id,
            EvidenceAnchor.anchor_id.in_(sorted(anchor_ids)),
        )).all()) if anchor_ids else []
        anchor_by_id = {anchor.anchor_id: anchor for anchor in anchors}

        spans = list(session.exec(select(EvidenceSpan).where(
            EvidenceSpan.course_id == course_id,
        )).all())
        evidence = list(session.exec(select(CourseEvidenceRecord).where(
            CourseEvidenceRecord.course_id == course_id,
            CourseEvidenceRecord.status == EvidenceStatus.ACTIVE,
        )).all())
        citations = list(session.exec(select(EvidenceCitation).where(
            EvidenceCitation.course_id == course_id,
        )).all())

        spans_by_anchor: dict[str, set[str]] = {}
        for span in spans:
            for anchor in anchors:
                if (
                    span.ir_version_id == anchor.ir_version_id
                    and span.block_id == anchor.block_id
                    and span.char_start <= anchor.char_end
                    and span.char_end >= anchor.char_start
                ):
                    spans_by_anchor.setdefault(anchor.anchor_id, set()).add(span.span_id)

        evidence_by_anchor: dict[str, set[str]] = {}
        for record in evidence:
            for anchor_id in record.source_anchor_ids or []:
                evidence_by_anchor.setdefault(anchor_id, set()).add(record.evidence_id)

        citation_by_evidence: dict[str, set[str]] = {}
        for citation in citations:
            if citation.evidence_id and citation.student_visible:
                citation_by_evidence.setdefault(citation.evidence_id, set()).add(
                    citation.citation_id
                )

        documents: list[GraphRagInputDocument] = []
        for chunk in chunks:
            chunk_anchor_ids = tuple(
                anchor_id for anchor_id in (chunk.anchor_ids or []) if anchor_id in anchor_by_id
            )
            span_ids = sorted({
                span_id
                for anchor_id in chunk_anchor_ids
                for span_id in spans_by_anchor.get(anchor_id, set())
            })
            evidence_ids = sorted({
                evidence_id
                for anchor_id in chunk_anchor_ids
                for evidence_id in evidence_by_anchor.get(anchor_id, set())
            })
            citation_ids = sorted({
                citation_id
                for evidence_id in evidence_ids
                for citation_id in citation_by_evidence.get(evidence_id, set())
            })
            pages = [
                anchor_by_id[anchor_id].page_or_slide
                for anchor_id in chunk_anchor_ids
                if anchor_by_id[anchor_id].page_or_slide is not None
            ]
            documents.append(GraphRagInputDocument(
                source_key=f"rc_{chunk.chunk_id}",
                course_id=course_id,
                retrieval_chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                ir_version_id=chunk.ir_version_id,
                page_number=min(pages) if pages else None,
                title=f"rc:{chunk.chunk_id}",
                text=chunk.text,
                content_hash=chunk.content_hash,
                anchor_ids=chunk_anchor_ids,
                evidence_span_ids=tuple(span_ids),
                formal_evidence_ids=tuple(evidence_ids),
                citation_ids=tuple(citation_ids),
                initial_status=chunk.status,
            ))

        canonical_rows = [
            {
                **asdict(document),
                "anchor_ids": list(document.anchor_ids),
                "evidence_span_ids": list(document.evidence_span_ids),
                "formal_evidence_ids": list(document.formal_evidence_ids),
                "citation_ids": list(document.citation_ids),
            }
            for document in documents
        ]
        content_hash = hashlib.sha256(
            json.dumps(canonical_rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        manifest = GraphRagInputManifest(
            schema_version=self.schema_version,
            course_id=course_id,
            input_content_hash=content_hash,
            documents=tuple(documents),
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_payload = {
            "schema_version": manifest.schema_version,
            "course_id": manifest.course_id,
            "input_content_hash": manifest.input_content_hash,
            "chunk_count": manifest.chunk_count,
            "documents": canonical_rows,
        }
        (output_dir / "input_manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "documents.json").write_text(
            json.dumps(
                [{"id": item.source_key, "title": item.title, "text": item.text}
                 for item in documents],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return manifest


def load_graph_rag_input_manifest(path: str | Path) -> GraphRagInputManifest:
    """Load the canonical, key-free handoff format used by an isolated worker."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    documents = tuple(GraphRagInputDocument(
        source_key=str(item["source_key"]),
        course_id=int(item["course_id"]),
        retrieval_chunk_id=str(item["retrieval_chunk_id"]),
        document_id=str(item["document_id"]),
        ir_version_id=str(item["ir_version_id"]),
        page_number=(
            int(item["page_number"]) if item.get("page_number") is not None else None
        ),
        title=str(item["title"]),
        text=str(item["text"]),
        content_hash=str(item["content_hash"]),
        anchor_ids=tuple(str(value) for value in item.get("anchor_ids") or []),
        evidence_span_ids=tuple(
            str(value) for value in item.get("evidence_span_ids") or []
        ),
        formal_evidence_ids=tuple(
            str(value) for value in item.get("formal_evidence_ids") or []
        ),
        citation_ids=tuple(str(value) for value in item.get("citation_ids") or []),
        initial_status=str(item.get("initial_status") or "candidate"),
    ) for item in payload.get("documents") or [])
    manifest = GraphRagInputManifest(
        schema_version=str(payload["schema_version"]),
        course_id=int(payload["course_id"]),
        input_content_hash=str(payload["input_content_hash"]),
        documents=documents,
    )
    if int(payload.get("chunk_count") or 0) != manifest.chunk_count:
        raise ValueError("GRAPH_INPUT_MANIFEST_MISMATCH")
    return manifest
