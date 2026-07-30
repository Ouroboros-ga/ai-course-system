"""Durable task handlers for GraphRAG and immutable Bundle indexing."""
from __future__ import annotations

import asyncio

from sqlmodel import select

from app.models.knowledge_bundle_model import (
    CourseKnowledgeBundle,
    CourseVectorIndex,
    GraphRagRun,
    GraphRagRunStatus,
    KnowledgeBundleStatus,
    VectorIndexStatus,
)
from app.platform.tasks.worker import TaskExecutionError, TaskHandlerContext
from app.services.knowledge_bundle_service import KnowledgeBundleError, knowledge_bundle_service


async def knowledge_graphrag_build_handler(ctx: TaskHandlerContext) -> None:
    run_id = str((ctx.input_payload or {}).get("run_id") or "")
    course_id = int((ctx.input_payload or {}).get("course_id") or 0)
    if not run_id or not course_id:
        raise TaskExecutionError("VALIDATION_FAILED", "缺少 run_id/course_id", retryable=False)
    with ctx.session_factory() as session:
        run = session.exec(select(GraphRagRun).where(
            GraphRagRun.course_id == course_id,
            GraphRagRun.run_id == run_id,
        )).first()
        if run is not None and run.status == GraphRagRunStatus.FAILED:
            run.status = GraphRagRunStatus.QUEUED
            run.error_code = ""
            run.error_message = ""
            session.add(run)
            session.commit()
        ctx.service.mark_running(session, ctx.task_id, stage="export_document_ir")

    def progress(percent: int, stage: str) -> None:
        with ctx.session_factory() as progress_session:
            ctx.service.mark_progress(
                progress_session,
                ctx.task_id,
                progress=percent,
                stage=stage,
                message=stage,
            )

    def execute():
        with ctx.session_factory() as session:
            return knowledge_bundle_service.execute_graphrag_run(
                session, run_id=run_id, progress=progress
            )

    try:
        run = await asyncio.to_thread(execute)
    except Exception as exc:
        with ctx.session_factory() as failure_session:
            record = failure_session.exec(select(GraphRagRun).where(
                GraphRagRun.course_id == course_id,
                GraphRagRun.run_id == run_id,
            )).first()
            if record is not None:
                record.status = GraphRagRunStatus.FAILED
                record.error_code = getattr(exc, "code", "GRAPHRAG_BUILD_FAILED")
                record.error_message = f"{type(exc).__name__}: {exc}"[:1000]
                failure_session.add(record)
                failure_session.commit()
        code = getattr(exc, "code", "GRAPHRAG_BUILD_FAILED")
        raise TaskExecutionError(
            code,
            str(exc),
            retryable=code not in {
                "GRAPHRAG_NOT_CONFIGURED",
                "LLM_BUDGET_EXCEEDED",
                "GRAPH_OUTPUT_INVALID",
                "EVIDENCE_CLOSURE_FAILED",
                "IDENTITY_AMBIGUOUS",
            } and not isinstance(exc, KnowledgeBundleError),
        ) from exc
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=run.run_id,
            result_data={
                "run_id": run.run_id,
                "status": run.status.value,
                "entity_count": run.entity_count,
                "relationship_count": run.relationship_count,
            },
        )


async def knowledge_vector_index_handler(ctx: TaskHandlerContext) -> None:
    payload = ctx.input_payload or {}
    course_id = int(payload.get("course_id") or 0)
    bundle_id = str(payload.get("bundle_id") or "")
    vector_index_id = str(payload.get("vector_index_id") or "")
    actor_user_id = int(payload.get("actor_user_id") or 0) or None
    if not course_id or not bundle_id or not vector_index_id:
        raise TaskExecutionError(
            "VALIDATION_FAILED", "缺少 course_id/bundle_id/vector_index_id", retryable=False
        )
    with ctx.session_factory() as session:
        ctx.service.mark_running(session, ctx.task_id, stage="vectorize_text_units")

    def progress(percent: int, stage: str) -> None:
        with ctx.session_factory() as progress_session:
            ctx.service.mark_progress(
                progress_session,
                ctx.task_id,
                progress=percent,
                stage=stage,
                message=stage,
            )

    def execute():
        with ctx.session_factory() as session:
            return knowledge_bundle_service.build_vector_index(
                session,
                course_id=course_id,
                bundle_id=bundle_id,
                vector_index_id=vector_index_id,
                actor_user_id=actor_user_id,
                progress=progress,
            )

    try:
        bundle = await asyncio.to_thread(execute)
    except Exception as exc:
        with ctx.session_factory() as failure_session:
            vector = failure_session.exec(select(CourseVectorIndex).where(
                CourseVectorIndex.course_id == course_id,
                CourseVectorIndex.vector_index_id == vector_index_id,
            )).first()
            bundle_record = failure_session.exec(select(CourseKnowledgeBundle).where(
                CourseKnowledgeBundle.course_id == course_id,
                CourseKnowledgeBundle.bundle_id == bundle_id,
            )).first()
            if vector is not None:
                vector.status = VectorIndexStatus.FAILED
                vector.error_code = getattr(exc, "code", "VECTOR_BUILD_FAILED")
                vector.error_message = f"{type(exc).__name__}: {exc}"[:1000]
                failure_session.add(vector)
            if bundle_record is not None:
                bundle_record.status = KnowledgeBundleStatus.FAILED
                failure_session.add(bundle_record)
            failure_session.commit()
        code = getattr(exc, "code", "VECTOR_BUILD_FAILED")
        raise TaskExecutionError(
            code,
            str(exc),
            retryable=code not in {
                "GRAPHRAG_NOT_CONFIGURED",
                "VECTOR_DIMENSION_MISMATCH",
                "VECTOR_ROW_INVALID",
                "VECTOR_INPUT_EMPTY",
            },
        ) from exc
    with ctx.session_factory() as session:
        ctx.service.mark_succeeded(
            session,
            ctx.task_id,
            result_ref=bundle.bundle_id,
            result_data=knowledge_bundle_service.serialize_bundle(bundle),
        )
