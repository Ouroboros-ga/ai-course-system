"""Persist canonical DocumentIR then create query-oriented relational projections."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from app.models.document_parse_model import (
    DocumentBlock,
    DocumentIRVersion,
    EvidenceAnchor,
    EvidenceSpan,
    RetrievalIndexSnapshot,
    RetrievalChunk,
)
from app.platform.document_intelligence.document_ir.models import block_to_dict
from app.platform.document_intelligence.document_ir.serialization import serialize_document_ir
from app.services.object_storage import get_object_storage


@dataclass(frozen=True)
class StoredDocumentIR:
    ir_version_id: str
    object_key: str
    content_hash: str


class DocumentIRProjector:
    """Store first, then atomically materialize database read projections."""

    def persist_and_project(
        self,
        session: Session,
        *,
        course_id: int,
        material_version_id: str | None,
        run_id: str,
        previous_run_id: str | None,
        document_ir: Any,
        quality_decision: Any,
        provider_versions: dict[str, str],
        parse_outcome: str,
        parser_profile: str = "standard",
        cache_key: str = "",
        cache_source: DocumentIRVersion | None = None,
    ) -> tuple[StoredDocumentIR, int, int]:
        raw = serialize_document_ir(document_ir, indent=2)
        content_hash = cache_source.content_hash if cache_source else hashlib.sha256(raw.encode("utf-8")).hexdigest()
        previous = self._previous_version(session, previous_run_id)
        version = DocumentIRVersion(
            course_id=course_id,
            material_version_id=material_version_id,
            run_id=run_id,
            document_id=document_ir.document_id,
            artifact_id=cache_source.artifact_id if cache_source else document_ir.source_artifact.artifact_id,
            source_sha256=cache_source.source_sha256 if cache_source else document_ir.source_artifact.sha256,
            schema_version=cache_source.schema_version if cache_source else document_ir.schema_version,
            parser_profile=parser_profile,
            cache_key=cache_key,
            content_hash=content_hash,
            parser_versions=cache_source.parser_versions if cache_source else provider_versions,
            quality=cache_source.quality if cache_source else (document_ir.quality.to_dict() if document_ir.quality else {}),
            quality_verdict=cache_source.quality_verdict if cache_source else quality_decision.verdict.value,
            parse_outcome=cache_source.parse_outcome if cache_source else parse_outcome,
            needs_review=cache_source.needs_review if cache_source else quality_decision.needs_review,
            warning_count=cache_source.warning_count if cache_source else len(document_ir.warnings),
            prev_ir_version_id=previous.ir_version_id if previous else None,
        )
        session.add(version)
        session.flush()
        object_key = cache_source.object_key if cache_source else f"document-ir/course{course_id}/{document_ir.document_id}/{version.ir_version_id}.json"
        storage = get_object_storage()
        if cache_source is not None:
            if not storage.exists(object_key):
                raise RuntimeError(f"Cached Canonical DocumentIR object missing: {object_key}")
        else:
            payload = raw.encode("utf-8")
            if storage.exists(object_key):
                if storage.get(object_key) != payload:
                    raise RuntimeError(f"Immutable Canonical DocumentIR key collision: {object_key}")
            else:
                storage.put(object_key, payload, mime_type="application/json")
        version.object_key = object_key
        session.add(version)

        block_count = 0
        anchor_count = 0
        unit_by_block = {
            block_id: unit.unit_id
            for unit in document_ir.units
            for block_id in unit.block_ids
        }
        for order_index, block in enumerate(document_ir.blocks):
            payload = block_to_dict(block)
            text = getattr(block, "text", None) or ""
            db_block = DocumentBlock(
                block_id=block.block_id,
                course_id=course_id,
                run_id=run_id,
                document_id=document_ir.document_id,
                unit_id=unit_by_block.get(block.block_id),
                document_ir_version_id=version.ir_version_id,
                page_number=int(block.page_or_slide or 0),
                page_or_slide=int(block.page_or_slide or 0),
                block_type=self._block_type(block.block_type),
                text=text,
                bbox=payload.get("bbox"),
                char_start=0,
                char_end=len(text),
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
                order_index=order_index,
                material_version_id=material_version_id,
                source_kind=self._source_kind(payload),
                confidence=float(getattr(block, "confidence", None) or 1.0),
                provider_version="|".join(f"{name}={value}" for name, value in sorted(provider_versions.items())),
                heading_level=getattr(block, "heading_level", None),
                semantic_role=self._semantic_role(block),
                style_hints=getattr(block, "style_hints", {}) or {},
                parent_block_id=getattr(block, "parent_id", None),
                reading_order=int(getattr(block, "reading_order", None) or order_index),
                visual_description=getattr(block, "visual_description", None),
            )
            session.add(db_block)
            session.flush()
            block_count += 1
            if text.strip():
                anchor = EvidenceAnchor(
                    course_id=course_id,
                    ir_version_id=version.ir_version_id,
                    run_id=run_id,
                    document_id=document_ir.document_id,
                    unit_id=unit_by_block.get(block.block_id),
                    block_id=block.block_id,
                    page_or_slide=block.page_or_slide,
                    char_start=0,
                    char_end=len(text),
                    text=text,
                    content_hash=db_block.content_hash,
                    bbox=payload.get("bbox"),
                    provenance=(payload.get("provenance") or [None])[0],
                )
                session.add(anchor)
                session.flush()
                session.add(EvidenceSpan(
                    course_id=course_id,
                    run_id=run_id,
                    ir_version_id=version.ir_version_id,
                    block_id=block.block_id,
                    document_id=document_ir.document_id,
                    page_number=int(block.page_or_slide or 0),
                    text_snippet=text,
                    bbox=payload.get("bbox"),
                    char_start=0,
                    char_end=len(text),
                    content_hash=db_block.content_hash,
                ))
                self._chunk(session, course_id, version, document_ir.document_id, unit_by_block.get(block.block_id), block.block_id, anchor.anchor_id, text, db_block.content_hash)
                anchor_count += 1
        self._create_index_snapshot(
            session,
            course_id=course_id,
            version=version,
            document_id=document_ir.document_id,
        )
        return StoredDocumentIR(version.ir_version_id, object_key, content_hash), block_count, anchor_count

    @staticmethod
    def _previous_version(session: Session, previous_run_id: str | None) -> DocumentIRVersion | None:
        if not previous_run_id:
            return None
        return session.exec(select(DocumentIRVersion).where(DocumentIRVersion.run_id == previous_run_id)).first()

    @staticmethod
    def _block_type(value: str) -> str:
        return {"paragraph": "text", "heading": "title", "table": "table_cell", "image": "figure_caption"}.get(value, "text")

    @staticmethod
    def _source_kind(payload: dict) -> str:
        providers = [str(item.get("provider", "")) for item in payload.get("provenance", [])]
        return "ocr" if any("ocr" in name.lower() for name in providers) else "native"

    @staticmethod
    def _semantic_role(block: Any) -> str:
        if block.block_type == "heading":
            # 顶层（第X章/9.4 等）→ section_title；更深小标题（9.4.1 / 1、/ （1））→ knowledge_title，
            # 使知识点来自真实标题而非每个正文段（修复 textbox 型教学 PPT 映射）。
            level = getattr(block, "heading_level", None) or 0
            return "section_title" if level <= 1 else "knowledge_title"
        return "explanation"

    @staticmethod
    def _chunk(session: Session, course_id: int, version: DocumentIRVersion, document_id: str, unit_id: str | None, block_id: str, anchor_id: str, text: str, content_hash: str) -> None:
        chunk_id = "rch_" + hashlib.sha256(f"{version.ir_version_id}:{block_id}:0:{len(text)}".encode("utf-8")).hexdigest()[:32]
        session.add(RetrievalChunk(
            chunk_id=chunk_id,
            course_id=course_id,
            ir_version_id=version.ir_version_id,
            document_id=document_id,
            unit_id=unit_id,
            block_ids=[block_id],
            anchor_ids=[anchor_id],
            text=text,
            content_hash=content_hash,
        ))

    @staticmethod
    def _create_index_snapshot(
        session: Session,
        *,
        course_id: int,
        version: DocumentIRVersion,
        document_id: str,
    ) -> None:
        """Build a candidate snapshot after all deterministic chunks exist."""
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == course_id,
            RetrievalChunk.ir_version_id == version.ir_version_id,
        )).all())
        digest = hashlib.sha256(
            "\n".join(sorted(chunk.content_hash for chunk in chunks)).encode("utf-8")
        ).hexdigest()
        session.add(RetrievalIndexSnapshot(
            course_id=course_id,
            ir_version_id=version.ir_version_id,
            document_id=document_id,
            chunk_count=len(chunks),
            content_hash=digest,
        ))
