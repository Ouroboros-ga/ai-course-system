"""Shared durable upload path for course source materials."""
from __future__ import annotations

import hashlib
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlmodel import Session, select

from app.models.course_build_model import MaterialStatus, SourceMaterialVersion
from app.models.document_parse_model import ParsePipeline, StaleStrategy
from app.services.course_build_service import source_material_service
from app.services.document_parse_service import document_parse_service
from app.services.object_storage import get_object_storage
from app.services.task_service import TaskCreateRequest, task_service


logger = logging.getLogger(__name__)

COURSE_MATERIAL_MAX_BYTES = 50 * 1024 * 1024
ALLOWED_SOURCE_SUFFIXES = {".ppt", ".pptx", ".pdf", ".doc", ".docx"}


def validate_source_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SOURCE_SUFFIXES:
        raise ValueError("仅支持 PPT、PPTX、PDF、DOC、DOCX 课程文件")
    return suffix


def _suggest_material_role(suffix: str) -> str:
    if suffix in {".ppt", ".pptx"}:
        return "primary_courseware"
    if suffix == ".pdf":
        return "textbook"
    return "reference"


class CourseMaterialUploadService:
    async def upload_material(
        self,
        *,
        file: UploadFile,
        session: Session,
        course_id: int,
        user_id: int,
        material_role: Optional[str] = None,
    ) -> dict:
        original_name = (file.filename or "untitled").strip()
        suffix = validate_source_name(original_name)
        total = 0
        digest = hashlib.sha256()
        object_key = ""

        with tempfile.SpooledTemporaryFile(max_size=2 * 1024 * 1024, mode="w+b") as staged:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > COURSE_MATERIAL_MAX_BYTES:
                    raise ValueError("文件大小超过限制（最大 50MB）")
                digest.update(chunk)
                staged.write(chunk)
            if total == 0:
                raise ValueError("不能上传空文件")

            source_hash = digest.hexdigest()
            existing = session.exec(select(SourceMaterialVersion).where(
                SourceMaterialVersion.file_hash == source_hash,
            ).order_by(SourceMaterialVersion.created_at.desc())).first()
            object_reused = bool(existing and existing.file_path and get_object_storage().exists(existing.file_path))
            object_key = existing.file_path if object_reused else f"course-source/u{user_id}/{uuid.uuid4().hex}/source{suffix}"
            staged.seek(0)
            try:
                get_object_storage().put(
                    object_key,
                    staged,
                    mime_type=file.content_type or "application/octet-stream",
                )
            except Exception as exc:
                logger.exception("Failed to persist course source material")
                raise RuntimeError("课程源文件暂时无法保存，请稍后重试") from exc

        try:
            material, version = source_material_service.create_material(
                session,
                course_id=course_id,
                name=original_name,
                material_type="slide" if suffix in {".ppt", ".pptx"} else "document",
                material_role=(material_role or _suggest_material_role(suffix)).strip(),
                source_kind="upload",
                file_path=object_key,
                file_hash=source_hash,
                file_size=total,
                mime_type=file.content_type or "application/octet-stream",
                created_by=user_id,
            )
            task_view = task_service.create_task(session, TaskCreateRequest(
                task_type="document_parse",
                owner_user_id=user_id,
                course_id=course_id,
                input_summary=f"解析课程 {course_id} 的材料 {original_name}",
                input_payload={
                    "course_id": course_id,
                    "material_id": material.material_id,
                    "material_version_id": version.version_id,
                    "pipeline": ParsePipeline.FULL.value,
                    "stale_strategy": StaleStrategy.MARK_STALE.value,
                    "initiated_by": user_id,
                },
                resource_links=[
                    {"resource_kind": "course", "resource_id": str(course_id), "relation": "input"},
                    {"resource_kind": "source_material", "resource_id": material.material_id, "relation": "input"},
                    {"resource_kind": "source_material_version", "resource_id": version.version_id, "relation": "input"},
                ],
            ))
            run = document_parse_service.create_run(
                session,
                course_id=course_id,
                material_id=material.material_id,
                material_version_id=version.version_id,
                task_id=task_view.task_id,
                pipeline=ParsePipeline.FULL,
                stale_strategy=StaleStrategy.MARK_STALE,
                initiated_by=user_id,
            )
            version.parse_task_id = task_view.task_id
            # The durable task has only been submitted here.  It remains in
            # the teacher-visible queue until the worker actually starts it.
            version.parse_status = MaterialStatus.UPLOADED
            session.add(version)
            session.commit()
        except Exception:
            session.rollback()
            if not object_reused:
                try:
                    get_object_storage().delete(object_key)
                except Exception:
                    logger.warning("Could not clean orphaned course source object %s", object_key, exc_info=True)
            raise

        self._submit_parse_task(course_id, run.run_id, material.material_id, version.version_id, user_id, task_view.task_id)
        return {
            "material_id": material.material_id,
            "material_version_id": version.version_id,
            "run_id": run.run_id,
            "task_id": task_view.task_id,
            "task_status": task_view.status,
            "parse_status": version.parse_status.value,
            "name": original_name,
            "material_role": material.material_role,
            "source_object_reused": object_reused,
        }

    @staticmethod
    def _submit_parse_task(course_id: int, run_id: str, material_id: str, version_id: str, user_id: int, task_id: str) -> None:
        try:
            from app.models.database import session_factory
            from app.platform.tasks.worker import local_task_worker
            from app.platform.tasks.document_parse_queue import document_parse_queue
            if local_task_worker.has_handler("document_parse"):
                document_parse_queue.submit(session_factory, local_task_worker, task_id)
            else:
                logger.error("document_parse handler unavailable for task %s", task_id)
        except Exception:
            # The task is committed and retryable even if local fire-and-forget
            # dispatch is unavailable.
            logger.exception("Could not submit course material task %s", task_id)


course_material_upload_service = CourseMaterialUploadService()
