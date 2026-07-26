"""阶段8 媒体生成与发布 API

挂在 `/api/v1/media` 前缀下，与现有 media_timeline.py 共用前缀。
实现 §3.11 中的 3 个 planned 端点：
- POST /media/course/{id}/generation-jobs
- GET  /media/course/{id}/releases
- POST /media/course/{id}/releases/{release_id}/activate

并补齐：
- GET  /media/course/{id}/releases/current
- GET  /media/course/{id}/releases/{release_id}
- POST /media/course/{id}/releases/{release_id}/withdraw
- POST /media/course/{id}/releases/{release_id}/rollback
- GET  /media/course/{id}/playback
- GET  /media/course/{id}/generation-jobs
- GET  /media/course/{id}/generation-jobs/{job_id}
- POST /media/course/{id}/generation-jobs/{job_id}/execute  (M1 同步执行 Fake)

权限：
- 读（timeline/releases/playback）：course.content.read
- 写（generation-jobs 创建/执行）：course.media.generate
- 发布激活/撤回/回滚：course.publish
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import (
    unified_response,
)
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.media_release_model import (
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaReleaseStatus,
    PlaybackMode,
)
from app.services.course_access_service import require_course_permission
from app.services.media_release_service import (
    media_generation_job_service,
    media_playback_service,
    media_release_service,
    tts_execution_service,
)


media_release_router = APIRouter(tags=["阶段8 媒体生成与发布"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class GenerationJobCreateRequest(BaseModel):
    """媒体生成任务创建请求"""
    job_type: str = Field(description="tts|subtitle|avatar_preprocess|dh_render|video_package|timeline_publish")
    node_id: Optional[int] = Field(None, ge=1)
    provider_key: str = Field(default="")
    provider_version: str = Field(default="")
    input_summary: str = Field(default="", max_length=500)
    input_payload: dict = Field(default_factory=dict)
    idempotency_key: str = Field(default="", max_length=100)
    avatar_id: Optional[str] = Field(None, max_length=100)
    media_release_id: Optional[str] = Field(None, max_length=100)


class TtsJobExecuteRequest(BaseModel):
    """TTS 任务执行请求（M1 阶段同步执行 Fake）"""
    script_text: str = Field(min_length=1, max_length=200_000)
    voice_id: str = Field(default="default", max_length=100)
    resource_version: str = Field(default="v1", max_length=20)
    provider_key: str = Field(default="", max_length=50)


class ReleaseCreateRequest(BaseModel):
    """媒体发布版本创建请求"""
    label: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)
    audio_object_key: Optional[str] = Field(None, max_length=500)
    subtitle_manifest_object_key: Optional[str] = Field(None, max_length=500)
    ppt_manifest_object_key: Optional[str] = Field(None, max_length=500)
    avatar_binding_id: Optional[str] = Field(None, max_length=100)
    digital_human_manifest_object_key: Optional[str] = Field(None, max_length=500)
    default_playback_mode: str = Field(default="auto", pattern="^(auto|low_resource|compatibility)$")
    capability_profile_id: Optional[str] = Field(None, max_length=100)


class FreezeCuesRequest(BaseModel):
    """冻结时间轴 Cue 到发布版本"""
    cue_ids: list[int] = Field(default_factory=list, description="MediaTimelineCue.id 列表；为空则冻结全部")


# ---------------------------------------------------------------------------
# 媒体生成任务
# ---------------------------------------------------------------------------


@media_release_router.post("/course/{course_id}/generation-jobs")
async def create_generation_job(
    course_id: int,
    payload: GenerationJobCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建媒体生成任务（返回 202 + task_id）

    与 §3.11 planned `POST /media/course/{id}/generation-jobs` 对齐。
    实际任务状态由 /api/v1/tasks/{task_id} 追踪。
    """
    context = require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    user_id = int(current_user["user_id"])

    try:
        job_type = MediaGenerationJobType(payload.job_type)
    except ValueError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(
            f"不支持的 job_type: {payload.job_type}",
            details={"allowed": [t.value for t in MediaGenerationJobType]},
        )

    # 计算输入哈希
    import hashlib
    import json
    input_hash = hashlib.sha256(
        json.dumps(payload.input_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course_id,
        job_type=job_type,
        created_by=user_id,
        provider_key=payload.provider_key,
        provider_version=payload.provider_version,
        node_id=payload.node_id,
        input_summary=payload.input_summary,
        input_payload=payload.input_payload,
        input_hash=input_hash,
        idempotency_key=payload.idempotency_key,
        avatar_id=payload.avatar_id,
        media_release_id=payload.media_release_id,
    )
    session.commit()
    return unified_response(
        code=202, message="媒体生成任务已创建",
        data={
            "job_id": job.job_id,
            "task_id": task_id,
            "status": job.status.value,
            "job_type": job.job_type.value,
            "idempotency_key": job.idempotency_key,
        },
    )


@media_release_router.get("/course/{course_id}/generation-jobs")
async def list_generation_jobs(
    course_id: int,
    job_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    node_id: Optional[int] = Query(None, ge=1),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的媒体生成任务"""
    require_course_permission(session, current_user, course_id, "course.content.read")
    jt = None
    if job_type:
        try:
            jt = MediaGenerationJobType(job_type)
        except ValueError:
            pass
    st = None
    if status:
        try:
            st = MediaGenerationStatus(status)
        except ValueError:
            pass

    jobs = media_generation_job_service.list_jobs(
        session, course_id=course_id, job_type=jt, status=st, node_id=node_id,
    )
    return unified_response(
        code=200, message="获取媒体任务列表成功",
        data={"items": [_serialize_job(j) for j in jobs], "total": len(jobs)},
    )


@media_release_router.get("/course/{course_id}/generation-jobs/{job_id}")
async def get_generation_job(
    course_id: int,
    job_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取媒体生成任务详情"""
    require_course_permission(session, current_user, course_id, "course.content.read")
    job = media_generation_job_service.get_job(session, course_id=course_id, job_id=job_id)
    return unified_response(
        code=200, message="获取媒体任务详情成功",
        data=_serialize_job(job),
    )


@media_release_router.post("/course/{course_id}/generation-jobs/{job_id}/execute-tts")
async def execute_tts_job(
    course_id: int,
    job_id: str,
    payload: TtsJobExecuteRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """同步执行 TTS 任务（M1 阶段使用 Fake Provider）

    M2 接入真实讯飞后将改为异步 worker，本端点仅用于端到端测试。
    """
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    job = media_generation_job_service.get_job(session, course_id=course_id, job_id=job_id)
    if job.job_type != MediaGenerationJobType.TTS:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(f"任务类型 {job.job_type.value} 不是 tts，无法执行 TTS")

    updated = tts_execution_service.execute_tts_job(
        session,
        course_id=course_id,
        job_id=job_id,
        script_text=payload.script_text,
        voice_id=payload.voice_id,
        resource_version=payload.resource_version,
        provider_key=payload.provider_key or None,
    )
    session.commit()
    return unified_response(
        code=200, message="TTS 任务执行完成",
        data=_serialize_job(updated),
    )


# ---------------------------------------------------------------------------
# 媒体发布版本
# ---------------------------------------------------------------------------


@media_release_router.post("/course/{course_id}/releases")
async def create_release(
    course_id: int,
    payload: ReleaseCreateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """创建媒体发布版本（草稿）"""
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    user_id = int(current_user["user_id"])

    try:
        mode = PlaybackMode(payload.default_playback_mode)
    except ValueError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(f"不支持的播放模式: {payload.default_playback_mode}")

    release = media_release_service.create_release(
        session,
        course_id=course_id,
        created_by=user_id,
        label=payload.label,
        notes=payload.notes,
        audio_object_key=payload.audio_object_key,
        subtitle_manifest_object_key=payload.subtitle_manifest_object_key,
        ppt_manifest_object_key=payload.ppt_manifest_object_key,
        avatar_binding_id=payload.avatar_binding_id,
        digital_human_manifest_object_key=payload.digital_human_manifest_object_key,
        default_playback_mode=mode,
        capability_profile_id=payload.capability_profile_id,
    )
    session.commit()
    return unified_response(
        code=201, message="媒体发布版本已创建",
        data=_serialize_release(release),
    )


@media_release_router.get("/course/{course_id}/releases")
async def list_releases(
    course_id: int,
    status: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """列出课程的媒体发布版本"""
    require_course_permission(session, current_user, course_id, "course.content.read")
    st = None
    if status:
        try:
            st = MediaReleaseStatus(status)
        except ValueError:
            pass
    releases = media_release_service.list_releases(
        session, course_id=course_id, status=st,
    )
    return unified_response(
        code=200, message="获取媒体版本列表成功",
        data={"items": [_serialize_release(r) for r in releases], "total": len(releases)},
    )


@media_release_router.get("/course/{course_id}/releases/current")
async def get_current_release(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取课程当前激活的媒体版本"""
    require_course_permission(session, current_user, course_id, "course.content.read")
    release = media_release_service.get_current_release(session, course_id=course_id)
    if release is None:
        return unified_response(
            code=200, message="课程尚未发布任何媒体版本",
            data={"available": False, "reason": "no_active_release"},
        )
    return unified_response(
        code=200, message="获取当前媒体版本成功",
        data=_serialize_release(release),
    )


@media_release_router.get("/course/{course_id}/releases/{release_id}")
async def get_release(
    course_id: int,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取指定媒体发布版本详情（含 cue 快照）"""
    require_course_permission(session, current_user, course_id, "course.content.read")
    release = media_release_service.get_release(
        session, course_id=course_id, release_id=release_id,
    )
    cues = media_release_service.list_release_cues(
        session, course_id=course_id, release_id=release_id,
    )
    data = _serialize_release(release)
    data["cues"] = [_serialize_release_cue(c) for c in cues]
    return unified_response(
        code=200, message="获取媒体版本详情成功",
        data=data,
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/freeze-cues")
async def freeze_cues(
    course_id: int,
    release_id: str,
    payload: FreezeCuesRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """将编辑中的 MediaTimelineCue 冻结为发布版本快照"""
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    from app.models.media_timeline_model import MediaTimelineCue
    if payload.cue_ids:
        cues = list(session.exec(
            select(MediaTimelineCue).where(
                MediaTimelineCue.course_id == course_id,
                MediaTimelineCue.id.in_(payload.cue_ids),
                MediaTimelineCue.is_active == True,  # noqa: E712
            ).order_by(MediaTimelineCue.node_id, MediaTimelineCue.cue_index)
        ).all())
    else:
        cues = list(session.exec(
            select(MediaTimelineCue).where(
                MediaTimelineCue.course_id == course_id,
                MediaTimelineCue.is_active == True,  # noqa: E712
            ).order_by(MediaTimelineCue.node_id, MediaTimelineCue.cue_index)
        ).all())

    frozen = media_release_service.freeze_cues_from_timeline(
        session, course_id=course_id, release_id=release_id, cues=cues,
    )
    session.commit()
    return unified_response(
        code=200, message=f"已冻结 {len(frozen)} 条 Cue",
        data={
            "release_id": release_id,
            "frozen_count": len(frozen),
            "timeline_content_hash": media_release_service.get_release(
                session, course_id=course_id, release_id=release_id,
            ).timeline_content_hash,
        },
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/activate")
async def activate_release(
    course_id: int,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """激活指定媒体版本（旧 active 标记 superseded）

    与 §3.11 planned `POST /media/course/{id}/releases/{id}/activate` 对齐。
    """
    require_course_permission(
        session, current_user, course_id, "course.publish",
    )
    release = media_release_service.activate_release(
        session, course_id=course_id, release_id=release_id,
    )
    session.commit()
    return unified_response(
        code=200, message="媒体版本已激活",
        data=_serialize_release(release),
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/withdraw")
async def withdraw_release(
    course_id: int,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """撤回媒体版本（学生端不再可见，但保留历史）"""
    require_course_permission(
        session, current_user, course_id, "course.publish",
    )
    release = media_release_service.withdraw_release(
        session, course_id=course_id, release_id=release_id,
    )
    session.commit()
    return unified_response(
        code=200, message="媒体版本已撤回",
        data=_serialize_release(release),
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/rollback")
async def rollback_release(
    course_id: int,
    release_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """回滚到历史媒体版本（将该版本重新激活）"""
    require_course_permission(
        session, current_user, course_id, "course.rollback",
    )
    release = media_release_service.rollback_to_release(
        session, course_id=course_id, release_id=release_id,
    )
    session.commit()
    return unified_response(
        code=200, message="已回滚到指定媒体版本",
        data=_serialize_release(release),
    )


# ---------------------------------------------------------------------------
# 学生端统一播放清单
# ---------------------------------------------------------------------------


@media_release_router.get("/course/{course_id}/playback")
async def get_playback(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """获取学生端统一播放清单

    返回音频 + 字幕 + PPT 时间轴 + 数字人 manifest + 三档模式配置。
    数字人未绑定时返回兼容模式（音频+字幕+PPT+讲稿）。
    """
    require_course_permission(session, current_user, course_id, "course.content.read")
    playback = media_playback_service.get_current_playback(session, course_id=course_id)
    return unified_response(
        code=200, message="获取播放清单成功",
        data=playback,
    )


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _serialize_job(job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "task_id": job.task_id,
        "course_id": job.course_id,
        "node_id": job.node_id,
        "job_type": job.job_type.value,
        "status": job.status.value,
        "provider_key": job.provider_key,
        "provider_version": job.provider_version,
        "input_hash": job.input_hash,
        "idempotency_key": job.idempotency_key,
        "input_summary": job.input_summary,
        "output_object_key": job.output_object_key,
        "output_metadata": job.output_metadata,
        "error_code": job.error_code,
        "error_message_safe": job.error_message_safe,
        "avatar_id": job.avatar_id,
        "media_release_id": job.media_release_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _serialize_release(release) -> dict[str, Any]:
    return {
        "release_id": release.release_id,
        "course_id": release.course_id,
        "version_number": release.version_number,
        "label": release.label,
        "status": release.status.value,
        "timeline_content_hash": release.timeline_content_hash,
        "audio_object_key": release.audio_object_key,
        "subtitle_manifest_object_key": release.subtitle_manifest_object_key,
        "ppt_manifest_object_key": release.ppt_manifest_object_key,
        "avatar_binding_id": release.avatar_binding_id,
        "digital_human_manifest_object_key": release.digital_human_manifest_object_key,
        "default_playback_mode": release.default_playback_mode.value,
        "capability_profile_id": release.capability_profile_id,
        "notes": release.notes,
        "created_at": release.created_at.isoformat() if release.created_at else None,
        "activated_at": release.activated_at.isoformat() if release.activated_at else None,
        "superseded_at": release.superseded_at.isoformat() if release.superseded_at else None,
        "withdrawn_at": release.withdrawn_at.isoformat() if release.withdrawn_at else None,
    }


def _serialize_release_cue(cue) -> dict[str, Any]:
    return {
        "release_cue_id": cue.release_cue_id,
        "release_id": cue.release_id,
        "course_id": cue.course_id,
        "node_id": cue.node_id,
        "cue_index": cue.cue_index,
        "start_time": cue.start_time,
        "end_time": cue.end_time,
        "cue_type": cue.cue_type,
        "ppt_page": cue.ppt_page,
        "subtitle_text": cue.subtitle_text,
        "script_reference": cue.script_reference,
        "audio_object_key": cue.audio_object_key,
        "video_object_key": cue.video_object_key,
    }
