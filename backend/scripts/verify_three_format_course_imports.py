"""Import three representative courseware files and export auditable parse artifacts.

This is a local-demo verification utility.  It uses the same material, task,
parse-run, and worker services as ``/api/v1/document/course-imports`` rather
than writing DocumentIR or retrieval rows directly.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlmodel import select

from app.models.course_build_model import MaterialStatus
from app.models.course_model import Course, CourseStatus
from app.models.database import session_factory
from app.models.document_parse_model import (
    DocumentIRVersion,
    DocumentParseRun,
    EvidenceAnchor,
    EvidenceSpan,
    EvidenceSpanStatus,
    GraphCandidateBatch,
    RetrievalChunk,
    RetrievalIndexSnapshot,
)
from app.models.course_outline_model import CoursePptMapping
from app.platform.retrieval.providers.canonical_document_ir import CanonicalDocumentIRRetriever
from app.platform.retrieval.schemas import RetrievalScope
from app.models.task_model import TaskRecord
from app.platform.tasks.handlers import register_all_handlers
from app.platform.tasks.worker import local_task_worker
from app.services.course_access_service import establish_course_access_baseline
from app.services.course_build_service import source_material_service
from app.services.document_parse_service import document_parse_service
from app.services.object_storage import get_object_storage
from app.services.task_service import TaskCreateRequest, task_service


SOURCE_ROOT = Path(
    r"D:\A School Work\服务外包\a12基于泛雅平台的AI互动智课生成与实时问答\课件下载-3月3日"
)
OWNER_USER_ID = 6  # Existing local-demo teacher account (TTT).
# A fresh label creates isolated demo courses and artifacts for each audit run.
RUN_LABEL = os.getenv("DOCUMENT_PARSE_VERIFICATION_RUN_LABEL", "three-format-parse-20260728")
OUTPUT_DIR = ROOT / "docs" / "phase1" / "parse-verification" / RUN_LABEL

SOURCES = (
    ("ppt", SOURCE_ROOT / "材料力学智慧课程（15期 2025春夏）-课件20260303" / "M01绪论.ppt"),
    ("pdf", SOURCE_ROOT / "制冷原理与设备、建筑冷热源-课件20260303" / "第01章 绪论，制冷、制冷方法、应用、热点.pdf"),
    ("pptx", SOURCE_ROOT / "汽车构造 2025-课件20260303" / "01总论.pptx"),
)


def _write_json(name: str, payload: Any) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def _to_markdown(ir: dict[str, Any], *, metadata: dict[str, Any]) -> str:
    lines = [
        "# Canonical DocumentIR verification export",
        "",
        f"- Source: `{metadata['source_file_name']}`",
        f"- Course ID: `{metadata['course_id']}`",
        f"- Parse run ID: `{metadata['run_id']}`",
        f"- IR version ID: `{metadata['ir_version_id']}`",
        f"- Canonical object: `{metadata['object_key']}`",
        "",
        "## Extracted blocks",
        "",
    ]
    for block in ir.get("blocks", []):
        text = (block.get("text") or "").strip()
        if not text:
            continue
        kind = block.get("block_type", "paragraph")
        page = block.get("page_or_slide", 0)
        if kind == "heading":
            lines.extend([f"## {text}", ""])
        else:
            lines.extend([f"<!-- {kind}, page/slide {page}, id {block.get('block_id', '')} -->", text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _create_and_parse(kind: str, source_path: Path, *, retry_failed: bool = False) -> dict[str, Any]:
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_bytes = source_path.read_bytes()
    sha256 = hashlib.sha256(source_bytes).hexdigest()
    suffix = source_path.suffix.lower()
    import_tag = hashlib.sha256(f"{RUN_LABEL}:{kind}:{sha256}".encode()).hexdigest()[:12]
    object_key = f"course-source/manual-verification/{RUN_LABEL}/{kind}-{import_tag}/source{suffix}"
    mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"

    with session_factory() as session:
        existing_courses = list(session.exec(select(Course).where(
            Course.fanya_course_id == f"local_verify_{import_tag}",
        ).order_by(Course.id.desc())).all())
        for existing_course in existing_courses:
            existing_run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == existing_course.id,
            ).order_by(DocumentParseRun.created_at.desc())).first()
            if existing_run is None:
                continue
            existing_task = session.exec(select(TaskRecord).where(
                TaskRecord.task_id == existing_run.task_id,
            )).first()
            existing_version = None
            if existing_run.document_ir_version_id:
                existing_version = session.exec(select(DocumentIRVersion).where(
                    DocumentIRVersion.ir_version_id == existing_run.document_ir_version_id,
                )).first()
            if existing_run.status.value in {"succeeded", "partial_success"} or (
                existing_run.status.value == "failed" and not retry_failed
            ):
                return {
                    "format": kind, "source_file_name": source_path.name, "source_path": str(source_path),
                    "source_sha256": sha256, "source_size_bytes": len(source_bytes),
                    "course_id": existing_course.id, "material_id": existing_run.material_id,
                    "material_version_id": existing_run.material_version_id, "task_id": existing_run.task_id,
                    "task_status": existing_task.status if existing_task else "", "task_error_code": existing_task.error_code if existing_task else "",
                    "task_error_message": existing_task.error_message if existing_task else "", "run_id": existing_run.run_id,
                    "run_status": existing_run.status.value, "run_error_code": existing_run.error_code,
                    "run_error_message": existing_run.error_message, "block_count": existing_run.block_count,
                    "evidence_span_count": existing_run.evidence_span_count, "graph_candidate_count": existing_run.graph_candidate_count,
                    "ir_version_id": existing_version.ir_version_id if existing_version else None,
                    "object_key": existing_version.object_key if existing_version else None,
                    "parse_outcome": existing_version.parse_outcome if existing_version else None,
                    "quality_verdict": existing_version.quality_verdict if existing_version else None,
                    "needs_review": existing_version.needs_review if existing_version else None,
                }

    storage = get_object_storage()
    storage.put(object_key, source_bytes, mime_type=mime_type)

    with session_factory() as session:
        course = Course(
            fanya_course_id=f"local_verify_{import_tag}",
            fanya_course_name=f"{RUN_LABEL}-{kind}",
            title=f"解析验证 {kind.upper()} - {source_path.stem}",
            description="本地三格式课件解析验证；未发布。",
            teacher_id=OWNER_USER_ID,
            status=CourseStatus.DRAFT,
            is_ai_generated=False,
            source_file_name=source_path.name,
            source_file_path=object_key,
            source_mimetype=mime_type,
            total_pages=0,
        )
        session.add(course)
        session.flush()
        establish_course_access_baseline(session, course.id, OWNER_USER_ID)
        material, version = source_material_service.create_material(
            session,
            course_id=course.id,
            name=source_path.name,
            material_type="slide" if suffix in {".ppt", ".pptx"} else "document",
            source_kind="upload",
            file_path=object_key,
            file_hash=sha256,
            file_size=len(source_bytes),
            mime_type=mime_type,
            created_by=OWNER_USER_ID,
        )
        task = task_service.create_task(session, TaskCreateRequest(
            task_type="document_parse",
            owner_user_id=OWNER_USER_ID,
            course_id=course.id,
            input_summary=f"{RUN_LABEL}: parse {source_path.name}",
            input_payload={
                "course_id": course.id,
                "material_id": material.material_id,
                "material_version_id": version.version_id,
                "pipeline": "full",
                "stale_strategy": "mark_stale",
                "initiated_by": OWNER_USER_ID,
            },
            resource_links=[
                {"resource_kind": "course", "resource_id": str(course.id), "relation": "input"},
                {"resource_kind": "source_material", "resource_id": material.material_id, "relation": "input"},
                {"resource_kind": "source_material_version", "resource_id": version.version_id, "relation": "input"},
            ],
        ))
        run = document_parse_service.create_run(
            session,
            course_id=course.id,
            material_id=material.material_id,
            material_version_id=version.version_id,
            task_id=task.task_id,
            initiated_by=OWNER_USER_ID,
        )
        version.parse_task_id = task.task_id
        version.parse_status = MaterialStatus.PARSING
        session.add(version)
        session.commit()
        payload = {
            "course_id": course.id,
            "run_id": run.run_id,
            "material_id": material.material_id,
            "material_version_id": version.version_id,
            "pipeline": "full",
            "stale_strategy": "mark_stale",
            "initiated_by": OWNER_USER_ID,
        }

    asyncio.run(local_task_worker.run_inline(session_factory, task.task_id, payload))

    with session_factory() as session:
        task_row = session.exec(select(TaskRecord).where(TaskRecord.task_id == task.task_id)).one()
        run_row = session.exec(select(DocumentParseRun).where(DocumentParseRun.run_id == run.run_id)).one()
        version = None
        if run_row.document_ir_version_id:
            version = session.exec(select(DocumentIRVersion).where(
                DocumentIRVersion.ir_version_id == run_row.document_ir_version_id
            )).one()
        return {
            "format": kind,
            "source_file_name": source_path.name,
            "source_path": str(source_path),
            "source_sha256": sha256,
            "source_size_bytes": len(source_bytes),
            "course_id": course.id,
            "material_id": material.material_id,
            "material_version_id": run_row.material_version_id,
            "task_id": task.task_id,
            "task_status": task_row.status,
            "task_error_code": task_row.error_code,
            "task_error_message": task_row.error_message,
            "run_id": run_row.run_id,
            "run_status": run_row.status.value,
            "run_error_code": run_row.error_code,
            "run_error_message": run_row.error_message,
            "block_count": run_row.block_count,
            "evidence_span_count": run_row.evidence_span_count,
            "graph_candidate_count": run_row.graph_candidate_count,
            "ir_version_id": version.ir_version_id if version else None,
            "object_key": version.object_key if version else None,
            "parse_outcome": version.parse_outcome if version else None,
            "quality_verdict": version.quality_verdict if version else None,
            "needs_review": version.needs_review if version else None,
        }


def _export_success_artifacts(result: dict[str, Any]) -> None:
    if not result["ir_version_id"]:
        (OUTPUT_DIR / f"{result['format']}-parse-failure.md").write_text(
            "# Parse verification failure\n\n"
            f"- Source: `{result['source_file_name']}`\n"
            f"- Course ID: `{result['course_id']}`\n"
            f"- Parse run ID: `{result['run_id']}`\n"
            f"- Status: `{result['run_status']}`\n"
            f"- Error code: `{result['run_error_code']}`\n"
            f"- Error: {result['run_error_message']}\n\n"
            "No Canonical DocumentIR, retrieval index, or graph-candidate input was created for this failed run.\n",
            encoding="utf-8",
        )
        return
    storage = get_object_storage()
    raw = storage.get(result["object_key"])
    document_ir = json.loads(raw.decode("utf-8"))
    stem = result["format"]
    md_path = OUTPUT_DIR / f"{stem}-document-ir.md"
    md_path.write_text(_to_markdown(document_ir, metadata=result), encoding="utf-8")

    with session_factory() as session:
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == result["course_id"],
            RetrievalChunk.ir_version_id == result["ir_version_id"],
        )).all())
        snapshots = list(session.exec(select(RetrievalIndexSnapshot).where(
            RetrievalIndexSnapshot.course_id == result["course_id"],
            RetrievalIndexSnapshot.ir_version_id == result["ir_version_id"],
        )).all())
        anchors = list(session.exec(select(EvidenceAnchor).where(
            EvidenceAnchor.course_id == result["course_id"],
            EvidenceAnchor.ir_version_id == result["ir_version_id"],
        ).order_by(EvidenceAnchor.id)).all())
        batches = list(session.exec(select(GraphCandidateBatch).where(
            GraphCandidateBatch.course_id == result["course_id"],
            GraphCandidateBatch.parse_run_id == result["run_id"],
        )).all())

    # This is a pre-review diagnostic over candidate chunks, not the formal
    # RAG endpoint. Formal RAG only searches chunks made active when a teacher
    # confirms their evidence anchor.
    query = ""
    hit_items: list[dict[str, Any]] = []
    if chunks:
        query = chunks[0].text.strip()[: min(16, len(chunks[0].text.strip()))]
        if query:
            for chunk in chunks:
                score = chunk.text.lower().count(query.lower())
                if score:
                    hit_items.append({
                        "chunk_id": chunk.chunk_id,
                        "score": score,
                        "text": chunk.text,
                        "document_id": chunk.document_id,
                        "unit_id": chunk.unit_id,
                        "block_ids": chunk.block_ids,
                        "anchor_ids": chunk.anchor_ids,
                    })
            hit_items.sort(key=lambda item: (-item["score"], item["chunk_id"]))
    _write_json(f"{stem}-rag-retrieval.json", {
        "course_id": result["course_id"],
        "run_id": result["run_id"],
        "ir_version_id": result["ir_version_id"],
        "active_index_snapshots": [{
            "snapshot_id": item.snapshot_id,
            "status": item.status,
            "chunk_count": item.chunk_count,
        } for item in snapshots],
        "mode": "candidate_diagnostic_not_formal_rag",
        "formal_rag_precondition": "Confirm the linked EvidenceSpan so its RetrievalChunk becomes active.",
        "request": {"query": query, "top_k": 5},
        "candidate_diagnostic_response": {"items": hit_items[:5], "total": min(5, len(hit_items))},
    })
    _write_json(f"{stem}-knowledge-graph-input.json", {
        "course_id": result["course_id"],
        "parse_run_id": result["run_id"],
        "canonical_ir_version_id": result["ir_version_id"],
        "graph_candidate_batches": [{
            "batch_id": batch.batch_id,
            "status": batch.status.value,
            "node_candidate_count": batch.node_candidate_count,
            "relation_candidate_count": batch.relation_candidate_count,
            "needs_review_count": batch.needs_review_count,
            "model_version": batch.model_version,
            "node_candidates": batch.node_candidates,
            "relation_candidates": batch.relation_candidates,
        } for batch in batches],
        "candidate_input_evidence_anchors": [{
            "anchor_id": anchor.anchor_id,
            "block_id": anchor.block_id,
            "page_or_slide": anchor.page_or_slide,
            "text": anchor.text,
            "content_hash": anchor.content_hash,
        } for anchor in anchors[:20]],
        "note": "These are the canonical evidence-closed inputs and candidate-batch metadata. They are not a published knowledge graph.",
    })


def _confirm_and_verify_formal_retrieval(result: dict[str, Any]) -> None:
    """Record one human-reviewed anchor-to-RAG trace for a successful run.

    This is deliberately opt-in because confirming evidence changes a
    course-scoped record from candidate to active.  It verifies the formal
    retriever, unlike the candidate diagnostic export above.
    """
    if not result["ir_version_id"]:
        return
    with session_factory() as session:
        spans = list(session.exec(select(EvidenceSpan).where(
            EvidenceSpan.course_id == result["course_id"],
            EvidenceSpan.run_id == result["run_id"],
            EvidenceSpan.status.in_((EvidenceSpanStatus.CANDIDATE, EvidenceSpanStatus.CONFIRMED)),
        ).order_by(EvidenceSpan.id)).all())
        chunks = list(session.exec(select(RetrievalChunk).where(
            RetrievalChunk.course_id == result["course_id"],
            RetrievalChunk.ir_version_id == result["ir_version_id"],
            RetrievalChunk.status.in_(("candidate", "active")),
        ).order_by(RetrievalChunk.id)).all())
        selected_span = next((span for span in spans if span.text_snippet.strip()), None)
        selected_chunk = next((chunk for chunk in chunks if selected_span and selected_span.block_id in (
            chunk.block_ids or []
        )), None)
        if selected_span is None or selected_chunk is None:
            _write_json(f"{result['format']}-formal-rag-after-evidence-review.json", {
                "status": "not_executed",
                "reason": "No candidate EvidenceSpan/RetrievalChunk pair could be selected.",
            })
            return
        reviewed_evidence = {
            "span_id": selected_span.span_id,
            "text": selected_span.text_snippet,
            "page_or_slide": selected_span.page_number,
            "linked_chunk_id": selected_chunk.chunk_id,
            "linked_anchor_ids": list(selected_chunk.anchor_ids or []),
        }
        if selected_span.status == EvidenceSpanStatus.CANDIDATE:
            document_parse_service.confirm_evidence_span(
                session,
                course_id=result["course_id"],
                span_id=selected_span.span_id,
                confirmed_by=OWNER_USER_ID,
                source_file=result["source_file_name"],
                source_type=result["format"],
            )
            session.commit()
        query = (selected_chunk.text or selected_span.text_snippet).strip()[:80]

    hits = CanonicalDocumentIRRetriever.retrieve(
        query,
        scope=RetrievalScope(scope_type="course", scope_id=str(result["course_id"])),
        top_k=5,
    )
    with session_factory() as session:
        mapping_count = session.exec(select(CoursePptMapping).where(
            CoursePptMapping.course_id == result["course_id"],
            CoursePptMapping.material_version_id == result["material_version_id"],
        )).all()
    _write_json(f"{result['format']}-formal-rag-after-evidence-review.json", {
        "status": "executed",
        "mode": "formal_teacher_confirmed_canonical_rag",
        "reviewed_evidence": reviewed_evidence,
        "request": {"query": query, "top_k": 5},
        "response": {
            "items": [{
                "chunk_id": hit.chunk_id,
                "text": hit.content,
                "score": hit.retrieval_score,
                "block_ids": hit.metadata.get("block_ids", []),
                "anchor_ids": hit.metadata.get("anchor_ids", []),
            } for hit in hits],
            "total": len(hits),
            "reviewed_anchor_returned": any(
                set(reviewed_evidence["linked_anchor_ids"]) & set(hit.metadata.get("anchor_ids", []))
                for hit in hits
            ),
        },
        "course_ppt_mapping_count": len(mapping_count),
    })


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    register_all_handlers()
    results = []
    for kind, source_path in SOURCES:
        result = _create_and_parse(kind, source_path, retry_failed=kind in {"pdf", "pptx"})
        results.append(result)
        _export_success_artifacts(result)
        if os.getenv("DOCUMENT_PARSE_VERIFICATION_CONFIRM_SAMPLE") == "1":
            _confirm_and_verify_formal_retrieval(result)
    _write_json("run-summary.json", {"run_label": RUN_LABEL, "results": results})
    print(json.dumps({"output_dir": str(OUTPUT_DIR), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
