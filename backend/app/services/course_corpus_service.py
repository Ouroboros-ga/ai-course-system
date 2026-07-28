"""Course-level orchestration for parsed materials.

Material parsing produces immutable document facts.  This service is the
boundary that turns the current *set* of successfully parsed material versions
into a course corpus and a separately traceable course-draft build task.
"""
from __future__ import annotations

import hashlib
import json
from typing import Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.course_build_model import (
    CorpusSnapshotStatus,
    CourseCorpusSnapshot,
    CourseDraftBuildStatus,
    CourseDraftBuildTask,
    CourseRetrievalSnapshot,
    MaterialStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_outline_model import CourseOutlineVersion, TeachingScriptVersion
from app.models.document_parse_model import DocumentParseRun, ParseRunStatus
from app.services.task_service import TaskCreateRequest, task_service


class CourseCorpusService:
    def create_ready_snapshot(
        self, session: Session, *, course_id: int, owner_user_id: int,
    ) -> Optional[CourseCorpusSnapshot]:
        """Freeze all current material versions only when every one parsed.

        Returning ``None`` is normal while other material tasks are still in
        flight.  A failed material never silently enters a course corpus.
        """
        versions = list(session.exec(select(SourceMaterialVersion).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.is_current == True,  # noqa: E712
        )).all())
        if not versions or any(v.parse_status != MaterialStatus.PARSED for v in versions):
            return None

        run_ids: list[str] = []
        for version in versions:
            run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_version_id == version.version_id,
                DocumentParseRun.status.in_([ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS]),
            ).order_by(DocumentParseRun.finished_at.desc())).first()
            if run is None:
                return None
            run_ids.append(run.run_id)

        version_ids = sorted(v.version_id for v in versions)
        run_ids = sorted(run_ids)
        content_hash = hashlib.sha256(json.dumps(
            {"versions": version_ids, "runs": run_ids}, sort_keys=True,
        ).encode("utf-8")).hexdigest()
        existing = session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.content_hash == content_hash,
            CourseCorpusSnapshot.status == CorpusSnapshotStatus.READY,
        )).first()
        if existing:
            return existing

        for old in session.exec(select(CourseCorpusSnapshot).where(
            CourseCorpusSnapshot.course_id == course_id,
            CourseCorpusSnapshot.status == CorpusSnapshotStatus.READY,
        )).all():
            old.status = CorpusSnapshotStatus.SUPERSEDED
            session.add(old)

        snapshot = CourseCorpusSnapshot(
            course_id=course_id,
            status=CorpusSnapshotStatus.READY,
            material_version_ids=version_ids,
            parse_run_ids=run_ids,
            content_hash=content_hash,
            created_by=owner_user_id,
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    def ensure_retrieval_snapshot(
        self, session: Session, *, corpus: CourseCorpusSnapshot,
    ) -> CourseRetrievalSnapshot:
        existing = session.exec(select(CourseRetrievalSnapshot).where(
            CourseRetrievalSnapshot.course_id == corpus.course_id,
            CourseRetrievalSnapshot.corpus_snapshot_id == corpus.corpus_snapshot_id,
        )).first()
        if existing:
            return existing
        retrieval = CourseRetrievalSnapshot(
            course_id=corpus.course_id,
            corpus_snapshot_id=corpus.corpus_snapshot_id,
            material_version_ids=list(corpus.material_version_ids or []),
            status="ready",
        )
        session.add(retrieval)
        session.flush()
        return retrieval

    def create_build_task(
        self, session: Session, *, corpus: CourseCorpusSnapshot, owner_user_id: int,
        trigger: str = "auto_after_materials_ready",
    ) -> tuple[CourseDraftBuildTask, str]:
        existing = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == corpus.course_id,
            CourseDraftBuildTask.corpus_snapshot_id == corpus.corpus_snapshot_id,
            CourseDraftBuildTask.status.in_([CourseDraftBuildStatus.QUEUED, CourseDraftBuildStatus.RUNNING]),
        )).first()
        if existing and existing.task_id:
            return existing, existing.task_id

        latest_outline = session.exec(select(CourseOutlineVersion).where(
            CourseOutlineVersion.course_id == corpus.course_id,
        ).order_by(CourseOutlineVersion.version.desc())).first()
        latest_script = session.exec(select(TeachingScriptVersion).where(
            TeachingScriptVersion.course_id == corpus.course_id,
        ).order_by(TeachingScriptVersion.version.desc())).first()
        mode = "initial" if latest_outline is None else "proposal"
        task_view = task_service.create_task(session, TaskCreateRequest(
            task_type="course_draft_build",
            owner_user_id=owner_user_id,
            course_id=corpus.course_id,
            input_summary="汇总已解析课程材料，生成课程建设草稿",
            input_payload={"course_id": corpus.course_id, "corpus_snapshot_id": corpus.corpus_snapshot_id},
            resource_links=[
                {"resource_kind": "course", "resource_id": str(corpus.course_id), "relation": "input"},
                {"resource_kind": "course_corpus_snapshot", "resource_id": corpus.corpus_snapshot_id, "relation": "input"},
            ],
        ))
        build = CourseDraftBuildTask(
            course_id=corpus.course_id,
            corpus_snapshot_id=corpus.corpus_snapshot_id,
            task_id=task_view.task_id,
            owner_user_id=owner_user_id,
            trigger=trigger,
            generation_mode=mode,
            base_outline_version_id=latest_outline.outline_version_id if latest_outline else None,
            base_script_version_id=latest_script.script_version_id if latest_script else None,
        )
        session.add(build)
        session.flush()
        return build, task_view.task_id

    def current_material_type_by_version(self, session: Session, *, course_id: int) -> dict[str, str]:
        rows = session.exec(select(SourceMaterialVersion, SourceMaterial).join(
            SourceMaterial, SourceMaterial.material_id == SourceMaterialVersion.material_id,
        ).where(SourceMaterialVersion.course_id == course_id)).all()
        return {version.version_id: material.material_type for version, material in rows}


course_corpus_service = CourseCorpusService()
