"""阶段8 教师数字人资产中心 API

挂在 `/api/v1/avatar-profiles` 与 `/api/v1/courses/{id}/media/avatar-binding` 前缀下。

实现「教师数字人资产中心」规划 §5 接口：

教师个人中心：
- POST   /avatar-profiles
- GET    /avatar-profiles/me
- GET    /avatar-profiles/{avatar_id}
- POST   /avatar-profiles/{avatar_id}/source-media
- POST   /avatar-profiles/{avatar_id}/prepare
- GET    /avatar-profiles/{avatar_id}/preparation-jobs
- GET    /avatar-preparation-jobs/{job_id}
- POST   /avatar-profiles/{avatar_id}/prepare/execute  (M1 同步执行 Fake)
- POST   /avatar-profiles/{avatar_id}/disable
- DELETE /avatar-profiles/{avatar_id}

课程媒体配置：
- GET    /courses/{course_id}/available-avatar-profiles
- PUT    /courses/{course_id}/media/avatar-binding
- GET    /courses/{course_id}/media/avatar-binding
- POST   /courses/{course_id}/media/avatar-binding/{binding_id}/publish
- POST   /courses/{course_id}/media/avatar-binding/{binding_id}/withdraw

权限：
- 教师只能管理 owner_user_id 是自己的 AvatarProfile
- 课程绑定需 course.media.generate 或 course.publish
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.exceptions import (
    reject_validation_failed,
    unified_response,
)
from app.core.security import get_current_user
from app.models.avatar_model import (
    AvatarSourceMediaType,
    CourseAvatarBindingStatus,
    DigitalHumanProviderKey,
)
from app.models.database import get_session
from app.services.avatar_service import (
    asset_package_service,
    course_avatar_binding_service,
    preparation_service,
    profile_service,
    source_media_service,
)
from app.services.course_access_service import require_course_permission


avatar_router = APIRouter(tags=["阶段8 教师数字人资产中心"])
course_avatar_router = APIRouter(tags=["阶段8 课程数字人绑定"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class AvatarProfileCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    provider_key: str = Field(default=DigitalHumanProviderKey.FAKE.value, max_length=50)
    notes: str = Field(default="", max_length=2000)
    consent_text: str = Field(min_length=10, max_length=2000,
                              description="必须包含本人形象与授权确认文本")


class SourceMediaRegisterRequest(BaseModel):
    media_type: str = Field(pattern="^(portrait_video|voice_sample)$")
    object_key: str = Field(min_length=3, max_length=500)
    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)
    duration_ms: Optional[int] = Field(None, ge=0)
    content_sha256: str = Field(default="", max_length=64)


class SourceMediaUploadIntentRequest(BaseModel):
    """P0-3 受控上传意图请求。

    客户端只提交 media_type / mime_type / size_bytes 预校验信息，
    不提交 object_key；object_key 由服务端生成。
    """
    media_type: str = Field(pattern="^(portrait_video|voice_sample)$")
    mime_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)


class SourceMediaConfirmRequest(BaseModel):
    """P0-3 服务端确认请求。

    客户端上传完成后调用此接口，服务端将独立完成 head/ffprobe/hash/scan。
    """
    source_media_id: str = Field(min_length=3, max_length=100)


class PrepareRequest(BaseModel):
    provider_key: str = Field(default="", max_length=50)
    idempotency_key: str = Field(default="", max_length=100)


class CourseAvatarBindingRequest(BaseModel):
    avatar_id: str = Field(min_length=3, max_length=100)
    notes: str = Field(default="", max_length=2000)


class CourseAvatarBindingPublishRequest(BaseModel):
    media_release_id: str = Field(min_length=3, max_length=100)


# ---------------------------------------------------------------------------
# 教师个人中心：数字人预设
# ---------------------------------------------------------------------------


@avatar_router.post("/avatar-profiles")
async def create_avatar_profile(
    payload: AvatarProfileCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建数字人预设草稿"""
    user_id = int(current_user["user_id"])
    profile = profile_service.create_profile(
        session,
        owner_user_id=user_id,
        display_name=payload.display_name,
        provider_key=payload.provider_key,
        notes=payload.notes,
        consent_text=payload.consent_text,
    )
    session.commit()
    return unified_response(
        code=201, message="数字人预设已创建",
        data=_serialize_profile(profile),
    )


@avatar_router.get("/avatar-profiles/me")
async def list_my_avatar_profiles(
    include_deleted: bool = Query(False),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出当前教师的数字人预设"""
    user_id = int(current_user["user_id"])
    profiles = profile_service.list_my_profiles(
        session, owner_user_id=user_id, include_deleted=include_deleted,
    )
    return unified_response(
        code=200, message="获取数字人预设列表成功",
        data={"items": [_serialize_profile(p) for p in profiles], "total": len(profiles)},
    )


@avatar_router.get("/avatar-profiles/{avatar_id}")
async def get_avatar_profile(
    avatar_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取数字人预设详情"""
    user_id = int(current_user["user_id"])
    profile = profile_service.get_profile(
        session, avatar_id=avatar_id, owner_user_id=user_id,
    )
    return unified_response(
        code=200, message="获取数字人预设详情成功",
        data=_serialize_profile(profile),
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/source-media")
async def register_source_media(
    avatar_id: str,
    payload: SourceMediaRegisterRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """登记原始素材（仅记录 object_key，不接收文件流）

    文件上传由前端直接 PUT 到 `sign_upload_intent` 签发的地址，本接口只登记元数据。
    """
    user_id = int(current_user["user_id"])
    try:
        media_type = AvatarSourceMediaType(payload.media_type)
    except ValueError:
        reject_validation_failed(f"不支持的素材类型: {payload.media_type}")

    source = source_media_service.register_source_media(
        session,
        avatar_id=avatar_id,
        owner_user_id=user_id,
        media_type=media_type,
        object_key=payload.object_key,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        duration_ms=payload.duration_ms,
        content_sha256=payload.content_sha256,
    )
    session.commit()
    return unified_response(
        code=201, message="原始素材已登记",
        data=_serialize_source_media(source),
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/source-media/upload-intent")
async def request_source_media_upload_intent(
    avatar_id: str,
    payload: SourceMediaUploadIntentRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """P0-3 第 1 步：服务端生成 object_key + 签发受控上传意图。

    客户端不提交 object_key，由服务端按教师 + AvatarProfile 命名空间生成。
    返回的 upload_intent 包含短时、限大小、限 MIME 的上传约束。
    """
    user_id = int(current_user["user_id"])
    try:
        media_type = AvatarSourceMediaType(payload.media_type)
    except ValueError:
        reject_validation_failed(f"不支持的素材类型: {payload.media_type}")

    source, intent = source_media_service.request_upload_intent(
        session,
        avatar_id=avatar_id,
        owner_user_id=user_id,
        media_type=media_type,
        client_mime_type=payload.mime_type,
        client_size_bytes=payload.size_bytes,
    )
    session.commit()
    return unified_response(
        code=200, message="上传意图已签发",
        data={
            "source_media": _serialize_source_media(source),
            "upload_intent": intent,
        },
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/source-media/{source_media_id}/confirm")
async def confirm_source_media_uploaded(
    avatar_id: str,
    source_media_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """P0-3 第 2 步：服务端确认对象存在 + 探测 + 哈希 + 扫描。

    客户端上传完成后调用，服务端独立完成：
    1. head() 确认对象存在
    2. ffprobe 探测真实 mime/duration
    3. 重算 content_sha256
    4. 病毒/恶意文件扫描 stub
    全部通过 -> verified；任一失败 -> invalid/quarantined。
    """
    user_id = int(current_user["user_id"])
    source = source_media_service.confirm_uploaded(
        session,
        avatar_id=avatar_id,
        owner_user_id=user_id,
        source_media_id=source_media_id,
    )
    session.commit()
    return unified_response(
        code=200, message="素材校验完成",
        data=_serialize_source_media(source),
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/source-media/{source_media_id}/withdraw")
async def withdraw_source_media(
    avatar_id: str,
    source_media_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """P0-3：教师主动撤回素材（状态转为 withdrawn）。

    撤回后素材不再可用，预处理入口拒绝。
    """
    user_id = int(current_user["user_id"])
    source = source_media_service.withdraw_source_media(
        session,
        avatar_id=avatar_id,
        owner_user_id=user_id,
        source_media_id=source_media_id,
    )
    session.commit()
    return unified_response(
        code=200, message="素材已撤回",
        data=_serialize_source_media(source),
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/prepare")
async def create_preparation_job(
    avatar_id: str,
    payload: PrepareRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建数字人资产预处理任务（返回 202 + task_id）

    实际任务状态由 /api/v1/tasks/{task_id} 追踪。
    """
    user_id = int(current_user["user_id"])
    job, task_id = preparation_service.create_preparation_job(
        session,
        avatar_id=avatar_id,
        owner_user_id=user_id,
        provider_key=payload.provider_key or None,
        idempotency_key=payload.idempotency_key,
    )
    session.commit()
    return unified_response(
        code=202, message="数字人资产预处理任务已创建",
        data={
            "job_id": job.job_id,
            "task_id": task_id,
            "status": job.status.value,
            "avatar_id": job.avatar_id,
            "provider_key": job.provider_key,
        },
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/prepare/execute")
async def execute_preparation_job(
    avatar_id: str,
    payload: PrepareRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """同步执行预处理任务（M1 阶段使用 Fake Provider）

    M4 接入真实引擎后将改为独立 Worker，本端点仅用于端到端测试。
    """
    user_id = int(current_user["user_id"])
    # 若未指定 idempotency_key，则取最新 pending/failed 任务执行
    if payload.idempotency_key:
        jobs = preparation_service.list_preparation_jobs(
            session, avatar_id=avatar_id, owner_user_id=user_id,
        )
        job = next(
            (j for j in jobs if j.idempotency_key == payload.idempotency_key),
            None,
        )
        if job is None:
            reject_validation_failed(f"未找到 idempotency_key={payload.idempotency_key} 的任务")
    else:
        jobs = preparation_service.list_preparation_jobs(
            session, avatar_id=avatar_id, owner_user_id=user_id,
        )
        # 取最新创建的 pending 或 failed 任务
        pending_or_failed = [
            j for j in jobs
            if j.status.value in ("pending", "failed")
        ]
        if not pending_or_failed:
            reject_validation_failed("没有可执行的 pending 或 failed 任务")
        job = pending_or_failed[0]

    updated = preparation_service.execute_preparation_job(
        session,
        avatar_id=avatar_id,
        job_id=job.job_id,
        owner_user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200, message="预处理任务执行完成",
        data=_serialize_preparation_job(updated),
    )


@avatar_router.get("/avatar-profiles/{avatar_id}/preparation-jobs")
async def list_preparation_jobs(
    avatar_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出数字人预处理任务"""
    user_id = int(current_user["user_id"])
    jobs = preparation_service.list_preparation_jobs(
        session, avatar_id=avatar_id, owner_user_id=user_id,
    )
    return unified_response(
        code=200, message="获取预处理任务列表成功",
        data={"items": [_serialize_preparation_job(j) for j in jobs], "total": len(jobs)},
    )


@avatar_router.get("/avatar-preparation-jobs/{job_id}")
async def get_preparation_job(
    job_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取预处理任务详情"""
    user_id = int(current_user["user_id"])
    from sqlmodel import select
    from app.models.avatar_model import AvatarPreparationJob
    job = session.exec(
        select(AvatarPreparationJob).where(
            AvatarPreparationJob.job_id == job_id,
            AvatarPreparationJob.owner_user_id == user_id,
        )
    ).first()
    if job is None:
        from app.core.exceptions import reject_resource_not_found
        reject_resource_not_found(f"预处理任务 {job_id} 不存在")
    return unified_response(
        code=200, message="获取预处理任务详情成功",
        data=_serialize_preparation_job(job),
    )


@avatar_router.post("/avatar-profiles/{avatar_id}/disable")
async def disable_avatar_profile(
    avatar_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """停用数字人预设（已发布绑定标记 stale）"""
    user_id = int(current_user["user_id"])
    profile = profile_service.disable_profile(
        session, avatar_id=avatar_id, owner_user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200, message="数字人预设已停用",
        data=_serialize_profile(profile),
    )


@avatar_router.delete("/avatar-profiles/{avatar_id}")
async def delete_avatar_profile(
    avatar_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """软删除数字人预设（保留历史绑定，学生端走兼容模式）"""
    user_id = int(current_user["user_id"])
    profile = profile_service.soft_delete_profile(
        session, avatar_id=avatar_id, owner_user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200, message="数字人预设已删除",
        data=_serialize_profile(profile),
    )


# ---------------------------------------------------------------------------
# 课程数字人绑定
# ---------------------------------------------------------------------------


@course_avatar_router.get("/courses/{course_id}/available-avatar-profiles")
async def list_available_avatar_profiles(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出当前教师在该课程可绑定的数字人预设"""
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    user_id = int(current_user["user_id"])
    profiles = profile_service.list_available_profiles_for_teacher(
        session, owner_user_id=user_id,
    )
    return unified_response(
        code=200, message="获取可用数字人预设成功",
        data={"items": [_serialize_profile(p) for p in profiles], "total": len(profiles)},
    )


@course_avatar_router.put("/courses/{course_id}/media/avatar-binding")
async def put_avatar_binding(
    course_id: int,
    payload: CourseAvatarBindingRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建或更新课程数字人绑定（草稿态，需随 MediaRelease 发布）"""
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    user_id = int(current_user["user_id"])
    binding = course_avatar_binding_service.create_or_update_binding(
        session,
        course_id=course_id,
        avatar_id=payload.avatar_id,
        bound_by_user_id=user_id,
        notes=payload.notes,
    )
    session.commit()
    return unified_response(
        code=200, message="课程数字人绑定已保存",
        data=_serialize_binding(binding),
    )


@course_avatar_router.get("/courses/{course_id}/media/avatar-binding")
async def get_avatar_binding(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程当前数字人绑定"""
    require_course_permission(
        session, current_user, course_id, "course.content.read",
    )
    binding = course_avatar_binding_service.get_binding(session, course_id=course_id)
    if binding is None:
        return unified_response(
            code=200, message="课程未绑定数字人",
            data={"available": False},
        )
    return unified_response(
        code=200, message="获取课程数字人绑定成功",
        data=_serialize_binding(binding),
    )


@course_avatar_router.post("/courses/{course_id}/media/avatar-binding/{binding_id}/publish")
async def publish_avatar_binding(
    course_id: int,
    binding_id: str,
    payload: CourseAvatarBindingPublishRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """发布课程数字人绑定（需指定 MediaRelease ID）"""
    require_course_permission(
        session, current_user, course_id, "course.publish",
    )
    user_id = int(current_user["user_id"])
    binding = course_avatar_binding_service.publish_binding(
        session,
        course_id=course_id,
        binding_id=binding_id,
        media_release_id=payload.media_release_id,
        bound_by_user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200, message="课程数字人绑定已发布",
        data=_serialize_binding(binding),
    )


@course_avatar_router.post("/courses/{course_id}/media/avatar-binding/{binding_id}/withdraw")
async def withdraw_avatar_binding(
    course_id: int,
    binding_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """撤回课程数字人绑定（学生端走兼容模式）"""
    require_course_permission(
        session, current_user, course_id, "course.publish",
    )
    user_id = int(current_user["user_id"])
    binding = course_avatar_binding_service.withdraw_binding(
        session,
        course_id=course_id,
        binding_id=binding_id,
        bound_by_user_id=user_id,
    )
    session.commit()
    return unified_response(
        code=200, message="课程数字人绑定已撤回",
        data=_serialize_binding(binding),
    )


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize_profile(profile) -> dict[str, Any]:
    return {
        "avatar_id": profile.avatar_id,
        "owner_user_id": profile.owner_user_id,
        "display_name": profile.display_name,
        "status": profile.status.value,
        "provider_key": profile.provider_key,
        "provider_version": profile.provider_version,
        "current_asset_package_id": profile.current_asset_package_id,
        "consented_at": profile.consented_at.isoformat() if profile.consented_at else None,
        "default_render_mode": profile.default_render_mode,
        "supported_quality_profiles": profile.supported_quality_profiles,
        "notes": profile.notes,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
        "deleted_at": profile.deleted_at.isoformat() if profile.deleted_at else None,
    }


def _serialize_source_media(source) -> dict[str, Any]:
    return {
        "source_media_id": source.source_media_id,
        "avatar_id": source.avatar_id,
        "owner_user_id": source.owner_user_id,
        "media_type": source.media_type.value,
        "object_key": source.object_key,
        "mime_type": source.mime_type,
        "size_bytes": source.size_bytes,
        "duration_ms": source.duration_ms,
        "content_sha256": source.content_sha256,
        "upload_status": source.upload_status.value,
        "retention_policy": source.retention_policy,
        "validation_notes": source.validation_notes,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "validated_at": source.validated_at.isoformat() if source.validated_at else None,
        # P0-3 服务端探测字段
        "server_mime_type": getattr(source, "server_mime_type", "") or "",
        "server_duration_ms": getattr(source, "server_duration_ms", None),
        "server_size_bytes": getattr(source, "server_size_bytes", 0) or 0,
        "server_content_sha256": getattr(source, "server_content_sha256", "") or "",
        "scan_status": getattr(source, "scan_status", "not_scanned") or "not_scanned",
        "verified_at": (
            source.verified_at.isoformat()
            if getattr(source, "verified_at", None) else None
        ),
    }


def _serialize_preparation_job(job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "task_id": job.task_id,
        "avatar_id": job.avatar_id,
        "owner_user_id": job.owner_user_id,
        "provider_key": job.provider_key,
        "provider_version": job.provider_version,
        "status": job.status.value,
        "input_hash": job.input_hash,
        "input_summary": job.input_summary,
        "result_asset_package_id": job.result_asset_package_id,
        "error_code": job.error_code,
        "error_message_safe": job.error_message_safe,
        "attempt_count": job.attempt_count,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _serialize_binding(binding) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "course_id": binding.course_id,
        "avatar_id": binding.avatar_id,
        "bound_by_user_id": binding.bound_by_user_id,
        "media_release_id": binding.media_release_id,
        "status": binding.status.value,
        "locked_provider_key": binding.locked_provider_key,
        "locked_provider_version": binding.locked_provider_version,
        "locked_asset_package_id": binding.locked_asset_package_id,
        "notes": binding.notes,
        "created_at": binding.created_at.isoformat() if binding.created_at else None,
        "published_at": binding.published_at.isoformat() if binding.published_at else None,
        "withdrawn_at": binding.withdrawn_at.isoformat() if binding.withdrawn_at else None,
    }
