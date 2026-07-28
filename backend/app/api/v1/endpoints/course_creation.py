"""Course creation and source-material upload entry points.

These routes separate creating a course workspace from uploading its first
source file.  They intentionally reuse the document import service so a
material uploaded here has the same durable task and parse-run semantics as
the legacy import endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.course_creation_service import course_creation_service
from app.services.course_material_upload_service import course_material_upload_service


course_creation_router = APIRouter()
course_materials_router = APIRouter()


class CourseCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    subject: str = Field(default="", max_length=100)
    course_type: str = Field(default="", max_length=100)
    teaching_audience: str = Field(default="", max_length=200)
    language: str = Field(default="zh-CN", max_length=32)


@course_creation_router.post("")
async def create_course(
    payload: CourseCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Create an empty draft course and its Course Access v1 workspace."""
    try:
        result = course_creation_service.create_empty_course(
            session,
            owner_user_id=int(current_user["user_id"]),
            title=payload.title,
            description=payload.description,
            subject=payload.subject,
            course_type=payload.course_type,
            teaching_audience=payload.teaching_audience,
            language=payload.language,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail={"error_code": "VALIDATION_FAILED", "message": str(exc)}) from exc
    return unified_response(code=201, message="草稿课程已创建", data=result)


@course_materials_router.post("/{course_id}/materials")
async def upload_course_materials(
    course_id: int,
    files: list[UploadFile] = File(..., description="课程材料，可一次上传多份"),
    material_roles: Optional[list[str]] = Form(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Persist multiple independent source materials and enqueue parse tasks."""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    if material_roles is not None and len(material_roles) not in {0, len(files)}:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "VALIDATION_FAILED", "message": "材料角色数量必须与文件数量一致"},
        )
    items = []
    for index, file in enumerate(files):
        role = (material_roles or [])[index] if index < len(material_roles or []) else None
        try:
            items.append(await course_material_upload_service.upload_material(
                file=file,
                session=session,
                course_id=course_id,
                user_id=context.user_id,
                material_role=role,
            ))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"error_code": "VALIDATION_FAILED", "message": str(exc)}) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail={"error_code": "OBJECT_STORAGE_UNAVAILABLE", "message": str(exc)}) from exc
    return unified_response(
        code=202,
        message="课程材料已保存，正在排队解析",
        data={"course_id": course_id, "items": items, "total": len(items)},
    )
