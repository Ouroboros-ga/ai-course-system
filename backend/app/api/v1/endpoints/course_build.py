"""阶段3 统一任务中心与教师课程建设工作流 API 路由。

路由前缀：
- /api/v1/facade/course/{course_id}/build            建设聚合读模型
- /api/v1/course-build/course/{course_id}/materials   源材料管理
- /api/v1/course-build/course/{course_id}/steps/{step_name}  单步状态
- /api/v1/course-build/course/{course_id}/steps/{step_name}/lock  锁定
- /api/v1/course-build/course/{course_id}/validate    质量门禁
- /api/v1/course-build/course/{course_id}/releases    发布管理

所有课程接口使用 Course Access v1 校验权限（course.edit / course.publish）。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import unified_response
from app.core.security import get_current_user
from app.models.course_build_model import (
    BuildStepName,
    BuildStepStatus,
    MaterialStatus,
)
from app.models.database import get_session
from app.services.course_access_service import require_course_permission
from app.services.course_build_service import (
    course_build_service,
    course_release_service,
    quality_gate_service,
    source_material_service,
)


course_build_router = APIRouter()


# ---------------------------------------------------------------------------
# 源材料
# ---------------------------------------------------------------------------


class MaterialCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    material_type: str = Field(default="document")
    source_kind: str = Field(default="upload")
    file_path: str = Field(default="")
    file_hash: str = Field(default="")
    file_size: int = Field(default=0, ge=0)
    mime_type: str = Field(default="")


class MaterialVersionAddRequest(BaseModel):
    file_path: str = Field(default="")
    file_hash: str = Field(default="")
    file_size: int = Field(default=0, ge=0)
    mime_type: str = Field(default="")


class MaterialParseStatusRequest(BaseModel):
    version_id: str
    status: MaterialStatus
    parse_task_id: Optional[str] = None
    parse_output_ref: Optional[str] = None
    parse_error: Optional[str] = None


class MaterialCorpusSelectionRequest(BaseModel):
    include_in_course_corpus: bool


@course_build_router.get("/course/{course_id}/materials")
async def list_materials(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的所有源材料。"""
    require_course_permission(session, current_user, course_id, "course.view")
    items = source_material_service.list_materials(session, course_id=course_id)
    return unified_response(
        code=200,
        message="获取源材料列表成功",
        data={
            "course_id": course_id,
            "items": [_serialize_material(m) for m in items],
            "total": len(items),
        },
    )


@course_build_router.post("/course/{course_id}/materials")
async def create_material(
    course_id: int,
    payload: MaterialCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.edit")
    return unified_response(
        code=410,
        message="材料登记入口已下线；请通过统一文件上传入口创建解析任务",
        data={"error_code": "UNIFIED_SOURCE_UPLOAD_REQUIRED", "upload_endpoint": f"/api/v1/document/course/{course_id}/source-materials"},
    )
    """创建源材料 + 首版本。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    material, version = source_material_service.create_material(
        session,
        course_id=course_id,
        name=payload.name,
        material_type=payload.material_type,
        source_kind=payload.source_kind,
        file_path=payload.file_path,
        file_hash=payload.file_hash,
        file_size=payload.file_size,
        mime_type=payload.mime_type,
        created_by=context.user_id,
    )
    session.commit()
    return unified_response(
        code=201,
        message="源材料已创建",
        data={
            "material": _serialize_material(material),
            "version": _serialize_version(version),
        },
    )


@course_build_router.get("/course/{course_id}/materials/{material_id}/versions")
async def list_material_versions(
    course_id: int,
    material_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出材料的所有版本。"""
    require_course_permission(session, current_user, course_id, "course.view")
    versions = source_material_service.list_versions(
        session, course_id=course_id, material_id=material_id,
    )
    return unified_response(
        code=200,
        message="获取材料版本列表成功",
        data={
            "course_id": course_id,
            "material_id": material_id,
            "items": [_serialize_version(v) for v in versions],
            "total": len(versions),
        },
    )


@course_build_router.patch("/course/{course_id}/materials/{material_id}/corpus-selection")
async def set_material_corpus_selection(
    course_id: int,
    material_id: str,
    payload: MaterialCorpusSelectionRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Explicitly include/exclude a material from the next course corpus.

    This is the only permitted way for a failed parse to stop blocking an
    automatic course build; it remains visible in the material list.
    """
    context = require_course_permission(session, current_user, course_id, "course.edit")
    material = source_material_service.get_material(
        session, course_id=course_id, material_id=material_id,
    )
    material.include_in_course_corpus = payload.include_in_course_corpus
    session.add(material)
    from app.services.course_corpus_service import course_corpus_service
    course_corpus_service.invalidate_queued_builds(
        session, course_id=course_id, reason="课程材料纳入范围已由教师修改",
    )
    corpus = course_corpus_service.create_ready_snapshot(
        session, course_id=course_id, owner_user_id=context.user_id,
    )
    build = None
    build_task_id = None
    if corpus is not None:
        build, build_task_id = course_corpus_service.create_build_task(
            session, corpus=corpus, owner_user_id=context.user_id, trigger="teacher_material_selection",
        )
    session.commit()
    if build_task_id:
        try:
            from app.models.database import session_factory
            from app.platform.tasks.worker import local_task_worker
            local_task_worker.submit(session_factory, build_task_id, {
                "course_id": course_id,
                "corpus_snapshot_id": corpus.corpus_snapshot_id,
                "build_task_id": build.build_task_id,
            })
        except Exception:
            # Durable task remains queued and can be retried from task centre.
            pass
    return unified_response(code=200, message="课程语料纳入范围已更新", data={
        "material": _serialize_material(material),
        "corpus_snapshot_id": corpus.corpus_snapshot_id if corpus else None,
        "course_draft_build_task_id": build.build_task_id if build else None,
        "task_id": build_task_id,
    })
@course_build_router.post("/course/{course_id}/materials/{material_id}/versions")
async def add_material_version(
    course_id: int,
    material_id: str,
    payload: MaterialVersionAddRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.edit")
    return unified_response(
        code=410,
        message="材料版本必须由统一上传入口创建，不能手填对象路径",
        data={"error_code": "UNIFIED_SOURCE_UPLOAD_REQUIRED", "upload_endpoint": f"/api/v1/document/course/{course_id}/source-materials"},
    )
    """为材料添加新版本；旧版本标记为 superseded。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    version = source_material_service.add_version(
        session,
        course_id=course_id,
        material_id=material_id,
        file_path=payload.file_path,
        file_hash=payload.file_hash,
        file_size=payload.file_size,
        mime_type=payload.mime_type,
        created_by=context.user_id,
    )
    session.commit()
    return unified_response(code=201, message="材料新版本已添加", data=_serialize_version(version))


@course_build_router.post("/course/{course_id}/materials/{material_id}/parse")
async def trigger_material_parse(
    course_id: int,
    material_id: str,
    payload: MaterialParseStatusRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    require_course_permission(session, current_user, course_id, "course.edit")
    return unified_response(
        code=410,
        message="解析状态由统一任务中心维护，前端不得手工写入",
        data={"error_code": "TASK_OWNED_PARSE_STATUS"},
    )
    """触发材料解析（记录解析任务 ID 与状态）。

    实际解析由统一任务中心异步执行；本接口仅记录任务关联。
    """
    context = require_course_permission(session, current_user, course_id, "course.edit")
    version = source_material_service.mark_parse_status(
        session,
        course_id=course_id,
        material_id=material_id,
        version_id=payload.version_id,
        status=payload.status,
        parse_task_id=payload.parse_task_id,
        parse_output_ref=payload.parse_output_ref,
        parse_error=payload.parse_error,
    )
    session.commit()
    return unified_response(code=200, message="材料解析状态已更新", data=_serialize_version(version))


def _serialize_material(m) -> dict:
    return {
        "material_id": m.material_id,
        "course_id": m.course_id,
        "name": m.name,
        "material_type": m.material_type,
        "material_role": m.material_role,
        "include_in_course_corpus": m.include_in_course_corpus,
        "source_kind": m.source_kind,
        "current_version_id": m.current_version_id,
        "status": m.status.value,
        "created_by": m.created_by,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


def _serialize_version(v) -> dict:
    return {
        "version_id": v.version_id,
        "material_id": v.material_id,
        "course_id": v.course_id,
        "version": v.version,
        "file_path": v.file_path,
        "file_hash": v.file_hash,
        "file_size": v.file_size,
        "mime_type": v.mime_type,
        "parse_task_id": v.parse_task_id,
        "parse_status": v.parse_status.value,
        "parse_output_ref": v.parse_output_ref,
        "parse_error": v.parse_error,
        "is_current": v.is_current,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


# ---------------------------------------------------------------------------
# 建设步骤
# ---------------------------------------------------------------------------


class StepUpdateRequest(BaseModel):
    target_status: Optional[str] = Field(default=None, description="目标状态")
    output_ref: Optional[str] = None
    output_snapshot: Optional[dict] = None
    input_summary: Optional[dict] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    bypass_lock: bool = Field(default=False, description="教师强制覆盖锁定（需更高权限）")


class StepLockRequest(BaseModel):
    lock_reason: str = Field(default="", max_length=500)


@course_build_router.get("/course/{course_id}/steps/{step_name}")
async def get_step(
    course_id: int,
    step_name: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取单步状态。"""
    require_course_permission(session, current_user, course_id, "course.view")
    step = course_build_service.get_step(
        session,
        course_id=course_id,
        step_name=BuildStepName(step_name),
    )
    return unified_response(code=200, message="获取建设步骤成功", data=course_build_service._serialize_step(step))


@course_build_router.put("/course/{course_id}/steps/{step_name}")
async def update_step(
    course_id: int,
    step_name: str,
    payload: StepUpdateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """更新单步状态与产物。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    target_status = BuildStepStatus(payload.target_status) if payload.target_status else None
    step = course_build_service.update_step(
        session,
        course_id=course_id,
        step_name=BuildStepName(step_name),
        target_status=target_status,
        output_ref=payload.output_ref,
        output_snapshot=payload.output_snapshot,
        input_summary=payload.input_summary,
        error_code=payload.error_code,
        error_message=payload.error_message,
        actor_user_id=context.user_id,
        bypass_lock=payload.bypass_lock,
    )
    session.commit()
    return unified_response(code=200, message="建设步骤已更新", data=course_build_service._serialize_step(step))


@course_build_router.post("/course/{course_id}/steps/{step_name}/lock")
async def lock_step(
    course_id: int,
    step_name: str,
    payload: StepLockRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师锁定步骤：AI 重跑不可覆盖。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    step = course_build_service.lock_step(
        session,
        course_id=course_id,
        step_name=BuildStepName(step_name),
        locked_by=context.user_id,
        lock_reason=payload.lock_reason,
    )
    session.commit()
    return unified_response(code=200, message="步骤已锁定", data=course_build_service._serialize_step(step))


@course_build_router.post("/course/{course_id}/steps/{step_name}/unlock")
async def unlock_step(
    course_id: int,
    step_name: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """教师解锁步骤。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    step = course_build_service.unlock_step(
        session,
        course_id=course_id,
        step_name=BuildStepName(step_name),
        actor_user_id=context.user_id,
    )
    session.commit()
    return unified_response(code=200, message="步骤已解锁", data=course_build_service._serialize_step(step))


# ---------------------------------------------------------------------------
# 质量门禁
# ---------------------------------------------------------------------------


@course_build_router.post("/course/{course_id}/validate")
async def run_validation(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """运行质量门禁检查。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    run = quality_gate_service.run_checks(
        session,
        course_id=course_id,
        initiated_by=context.user_id,
    )
    session.commit()
    return unified_response(
        code=200,
        message="质量门禁已运行",
        data={
            "gate_run_id": run.gate_run_id,
            "passed": run.passed,
            "blocker_count": run.blocker_count,
            "error_count": run.error_count,
            "warning_count": run.warning_count,
            "checks": run.checks,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        },
    )


@course_build_router.get("/course/{course_id}/validate/{gate_run_id}")
async def get_validation_run(
    course_id: int,
    gate_run_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取质量门禁运行详情。"""
    require_course_permission(session, current_user, course_id, "course.view")
    run = quality_gate_service.get_run(
        session, course_id=course_id, gate_run_id=gate_run_id,
    )
    return unified_response(
        code=200,
        message="获取质量门禁运行详情成功",
        data={
            "gate_run_id": run.gate_run_id,
            "passed": run.passed,
            "blocker_count": run.blocker_count,
            "error_count": run.error_count,
            "warning_count": run.warning_count,
            "checks": run.checks,
            "target_release_id": run.target_release_id,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
    )


# ---------------------------------------------------------------------------
# 发布管理
# ---------------------------------------------------------------------------


class ReleaseCreateRequest(BaseModel):
    label: str = Field(default="", max_length=100)
    release_notes: str = Field(default="", max_length=2000)


class ReleasePublishRequest(BaseModel):
    structure_snapshot: Optional[dict] = None
    scripts_snapshot: Optional[dict] = None
    page_mappings_snapshot: Optional[dict] = None
    media_snapshot: Optional[dict] = None
    graph_snapshot_ref: Optional[str] = None
    evidence_refs: Optional[list] = None
    run_quality_gate: bool = Field(default=True)


class ReleaseRollbackRequest(BaseModel):
    target_release_id: str


class ArtifactAddRequest(BaseModel):
    artifact_type: str
    artifact_id: str
    artifact_version: int = Field(default=1, ge=1)
    artifact_ref: str = Field(default="")


@course_build_router.get("/course/{course_id}/releases")
async def list_releases(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的所有发布版本。"""
    require_course_permission(session, current_user, course_id, "course.view")
    releases = course_release_service.list_releases(session, course_id=course_id)
    return unified_response(
        code=200,
        message="获取发布列表成功",
        data={
            "course_id": course_id,
            "items": [course_build_service._serialize_release(r) for r in releases],
            "total": len(releases),
        },
    )


@course_build_router.post("/course/{course_id}/releases")
async def create_release(
    course_id: int,
    payload: ReleaseCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建发布草稿。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    release = course_release_service.create_release_draft(
        session,
        course_id=course_id,
        label=payload.label,
        release_notes=payload.release_notes,
        created_by=context.user_id,
    )
    session.commit()
    return unified_response(code=201, message="发布草稿已创建", data=course_build_service._serialize_release(release))


@course_build_router.post("/course/{course_id}/releases/{release_id}/publish")
async def publish_release(
    course_id: int,
    release_id: str,
    payload: ReleasePublishRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布：质量门禁通过后，将 release 标记为 published + is_active。"""
    context = require_course_permission(session, current_user, course_id, "course.publish")
    release = course_release_service.publish_release(
        session,
        course_id=course_id,
        release_id=release_id,
        published_by=context.user_id,
        structure_snapshot=payload.structure_snapshot,
        scripts_snapshot=payload.scripts_snapshot,
        page_mappings_snapshot=payload.page_mappings_snapshot,
        media_snapshot=payload.media_snapshot,
        graph_snapshot_ref=payload.graph_snapshot_ref,
        evidence_refs=payload.evidence_refs,
        run_quality_gate=payload.run_quality_gate,
    )
    session.commit()
    return unified_response(code=200, message="发布已完成", data=course_build_service._serialize_release(release))


@course_build_router.post("/course/{course_id}/releases/rollback")
async def rollback_release(
    course_id: int,
    payload: ReleaseRollbackRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """回滚到指定发布版本（生成新激活版本，不破坏历史）。"""
    context = require_course_permission(session, current_user, course_id, "course.publish")
    release = course_release_service.rollback_to_release(
        session,
        course_id=course_id,
        target_release_id=payload.target_release_id,
        actor_user_id=context.user_id,
    )
    session.commit()
    return unified_response(code=200, message="已回滚到目标发布", data=course_build_service._serialize_release(release))


@course_build_router.get("/course/{course_id}/releases/{release_id}/artifacts")
async def list_release_artifacts(
    course_id: int,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出发布关联的产物。"""
    require_course_permission(session, current_user, course_id, "course.view")
    artifacts = course_release_service.list_artifacts(
        session, course_id=course_id, release_id=release_id,
    )
    return unified_response(
        code=200,
        message="获取发布产物列表成功",
        data={
            "course_id": course_id,
            "release_id": release_id,
            "items": [
                {
                    "id": a.id,
                    "release_id": a.release_id,
                    "artifact_type": a.artifact_type,
                    "artifact_id": a.artifact_id,
                    "artifact_version": a.artifact_version,
                    "artifact_ref": a.artifact_ref,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in artifacts
            ],
            "total": len(artifacts),
        },
    )


@course_build_router.post("/course/{course_id}/releases/{release_id}/artifacts")
async def add_release_artifact(
    course_id: int,
    release_id: str,
    payload: ArtifactAddRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """为发布关联产物。"""
    context = require_course_permission(session, current_user, course_id, "course.edit")
    art = course_release_service.add_artifact(
        session,
        course_id=course_id,
        release_id=release_id,
        artifact_type=payload.artifact_type,
        artifact_id=payload.artifact_id,
        artifact_version=payload.artifact_version,
        artifact_ref=payload.artifact_ref,
    )
    session.commit()
    return unified_response(
        code=201,
        message="产物已关联到发布",
        data={
            "release_id": art.release_id,
            "artifact_type": art.artifact_type,
            "artifact_id": art.artifact_id,
            "artifact_version": art.artifact_version,
        },
    )
