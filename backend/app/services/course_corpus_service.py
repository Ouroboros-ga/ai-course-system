"""Course-level orchestration for parsed materials.

Material parsing produces immutable document facts.  This service is the
boundary that turns the current *set* of successfully parsed material versions
into a course corpus and a separately traceable course-draft build task.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlmodel import Session, select

from app.core.time_utils import utcnow_aware
from app.models.course_build_model import (
    CorpusSnapshotStatus,
    CourseCorpusItem,
    CourseCorpusSnapshot,
    CourseDraftBuildStatus,
    CourseDraftBuildTask,
    CourseRetrievalSnapshot,
    MaterialStatus,
    SourceMaterial,
    SourceMaterialVersion,
)
from app.models.course_outline_model import CourseOutlineVersion, TeachingScriptVersion
from app.models.document_parse_model import DocumentIRVersion, DocumentParseRun, ParseRunStatus
from app.services.task_service import TaskCreateRequest, task_service


logger = logging.getLogger(__name__)

DEFAULT_CORPUS_QUIET_WINDOW_SECONDS = 8

ROLE_PRIORITY = {
    "primary_courseware": 10,
    "syllabus": 20,
    "textbook": 30,
    "experiment_guide": 40,
    "exercise_bank": 50,
    "reference": 60,
}


class CourseCorpusService:
    def create_ready_snapshot(
        self, session: Session, *, course_id: int, owner_user_id: int,
    ) -> Optional[CourseCorpusSnapshot]:
        """Freeze all current material versions only when every one parsed.

        Returning ``None`` is normal while other material tasks are still in
        flight.  A failed material never silently enters a course corpus.
        """
        rows = list(session.exec(select(SourceMaterialVersion, SourceMaterial).join(
            SourceMaterial, SourceMaterial.material_id == SourceMaterialVersion.material_id,
        ).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.is_current == True,  # noqa: E712
        )).all())
        included_rows = [(version, material) for version, material in rows if material.include_in_course_corpus]
        if not included_rows:
            return None

        # Failed or still-running material is intentionally not silently
        # omitted. The teacher must retry it or explicitly exclude it first.
        allowed_statuses = {MaterialStatus.PARSED, MaterialStatus.NEEDS_REVIEW}
        if any(version.parse_status not in allowed_statuses for version, _ in included_rows):
            return None

        run_ids: list[str] = []
        ir_version_ids: list[str] = []
        item_specs: list[dict] = []
        warnings: list[str] = []
        for version, material in included_rows:
            run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_version_id == version.version_id,
                DocumentParseRun.status.in_([ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS]),
            ).order_by(DocumentParseRun.finished_at.desc())).first()
            if run is None:
                return None
            if not run.document_ir_version_id:
                return None
            ir_version = session.exec(select(DocumentIRVersion).where(
                DocumentIRVersion.ir_version_id == run.document_ir_version_id,
                DocumentIRVersion.course_id == course_id,
                DocumentIRVersion.material_version_id == version.version_id,
            )).first()
            if ir_version is None:
                return None
            run_ids.append(run.run_id)
            ir_version_ids.append(ir_version.ir_version_id)
            quality_warning = ""
            if run.status == ParseRunStatus.PARTIAL_SUCCESS or version.parse_status == MaterialStatus.NEEDS_REVIEW:
                quality_warning = f"{material.name}: 解析部分成功，构建结果需要教师检查"
                warnings.append(quality_warning)
            item_specs.append({
                "material_id": material.material_id,
                "material_version_id": version.version_id,
                "material_role": material.material_role,
                "priority": ROLE_PRIORITY.get(material.material_role, ROLE_PRIORITY["reference"]),
                "document_ir_version_id": ir_version.ir_version_id,
                "parse_run_id": run.run_id,
                "quality_warning": quality_warning,
            })

        version_ids = sorted(version.version_id for version, _ in included_rows)
        run_ids = sorted(run_ids)
        content_hash = hashlib.sha256(json.dumps(
            {"items": sorted(item_specs, key=lambda item: item["material_version_id"])}, sort_keys=True,
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
            document_ir_version_ids=sorted(ir_version_ids),
            warnings=warnings,
            content_hash=content_hash,
            created_by=owner_user_id,
        )
        session.add(snapshot)
        session.flush()
        for item_spec in item_specs:
            session.add(CourseCorpusItem(
                corpus_snapshot_id=snapshot.corpus_snapshot_id,
                course_id=course_id,
                included=True,
                **item_spec,
            ))
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
            document_ir_version_ids=list(corpus.document_ir_version_ids or []),
            status="ready",
        )
        session.add(retrieval)
        session.flush()
        return retrieval

    def create_build_task(
        self, session: Session, *, corpus: CourseCorpusSnapshot, owner_user_id: int,
        trigger: str = "auto_after_materials_ready",
        quiet_window_seconds: int = DEFAULT_CORPUS_QUIET_WINDOW_SECONDS,
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
        not_before_at = self._quiet_window_deadline(
            session, course_id=corpus.course_id, quiet_window_seconds=quiet_window_seconds,
        )
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
            not_before_at=not_before_at,
        )
        session.add(build)
        session.flush()
        return build, task_view.task_id

    def invalidate_queued_builds(self, session: Session, *, course_id: int, reason: str) -> None:
        """Cancel only builds that have not started when a material set changes."""
        builds = session.exec(select(CourseDraftBuildTask).where(
            CourseDraftBuildTask.course_id == course_id,
            CourseDraftBuildTask.status == CourseDraftBuildStatus.QUEUED,
        )).all()
        for build in builds:
            build.status = CourseDraftBuildStatus.CANCELLED
            build.error_code = "CORPUS_CHANGED"
            build.error_message = reason[:500]
            session.add(build)
            if build.task_id:
                try:
                    task_service.cancel(session, build.task_id, reason=reason)
                except ValueError:
                    # The handler validates freshness before generating; an
                    # already running task is therefore still safe.
                    logger.info("Course build task %s was no longer cancellable", build.task_id)

    def is_snapshot_current(self, session: Session, *, corpus: CourseCorpusSnapshot) -> bool:
        """Verify no included current material changed after this snapshot."""
        current = self.create_ready_snapshot(
            session, course_id=corpus.course_id, owner_user_id=corpus.created_by or 0,
        )
        return bool(current and current.corpus_snapshot_id == corpus.corpus_snapshot_id)

    @staticmethod
    def _quiet_window_deadline(
        session: Session, *, course_id: int, quiet_window_seconds: int,
    ) -> datetime:
        """Start the 5–10 second window at the last upload or parse completion."""
        latest_at = utcnow_aware()
        versions = session.exec(select(SourceMaterialVersion).where(
            SourceMaterialVersion.course_id == course_id,
            SourceMaterialVersion.is_current == True,  # noqa: E712
        )).all()
        for version in versions:
            version_created_at = _as_utc(version.created_at)
            if version_created_at and version_created_at > latest_at:
                latest_at = version_created_at
            run = session.exec(select(DocumentParseRun).where(
                DocumentParseRun.course_id == course_id,
                DocumentParseRun.material_version_id == version.version_id,
                DocumentParseRun.status.in_([ParseRunStatus.SUCCEEDED, ParseRunStatus.PARTIAL_SUCCESS]),
            ).order_by(DocumentParseRun.finished_at.desc())).first()
            run_finished_at = _as_utc(run.finished_at) if run else None
            if run_finished_at and run_finished_at > latest_at:
                latest_at = run_finished_at
        return latest_at + timedelta(seconds=max(0, quiet_window_seconds))

    def current_material_type_by_version(self, session: Session, *, course_id: int) -> dict[str, str]:
        rows = session.exec(select(SourceMaterialVersion, SourceMaterial).join(
            SourceMaterial, SourceMaterial.material_id == SourceMaterialVersion.material_id,
        ).where(SourceMaterialVersion.course_id == course_id)).all()
        return {version.version_id: material.material_type for version, material in rows}


course_corpus_service = CourseCorpusService()


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes even for timezone-aware columns."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
