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

import hashlib
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.core.exceptions import (
    unified_response,
)
from app.core.security import get_current_user
from app.models.database import get_session
from app.models.media_release_model import (
    MediaBuildBatch,
    MediaBuildBatchStatus,
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaReleaseStatus,
    MediaReleaseItem,
    PlaybackMode,
)
from app.models.access_control_model import PlatformPermission
from app.services.course_access_service import require_course_permission, require_platform_permission
from app.services.task_service import task_service
from app.services.media_release_service import (
    ensure_release_tts_assets_registered,
    media_generation_job_service,
    media_playback_service,
    media_release_service,
    tts_execution_service,
)
from app.models.course_outline_model import TeachingScriptNode
from app.services.tts_provider import TtsProviderConfigurationError
from app.services.stage8_provider_runtime import get_stage8_tts_provider, resolve_stage8_tts_runtime
from app.services.platform_media_preset_service import list_public_presets, sign_avatar_package_for_release
from app.services.media_batch_service import (
    build_media_plan,
    confirm_media_batch,
    enqueue_batch_cue,
    freeze_playlist,
    project_tts_result_to_batch_item,
    refresh_batch_status,
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
    """TTS 任务执行请求（真实 Provider 交由 Media Worker 异步执行）"""
    script_text: str = Field(min_length=1, max_length=200_000)
    voice_id: str = Field(default="default", max_length=100)
    resource_version: str = Field(default="v1", max_length=20)
    provider_key: str = Field(default="", max_length=50)
    max_retries: Optional[int] = Field(None, ge=1, le=10, description="最大重试次数，默认从配置读取")


class MediaBatchPlanRequest(BaseModel):
    node_ids: list[int] = Field(default_factory=list, max_length=20)
    provider_key: str = Field(default="", max_length=50)
    provider_version: str = Field(default="", max_length=50)
    voice_id: str = Field(default="default", max_length=100)
    voice_preset_id: str = Field(default="", max_length=100)
    voice_preset_version: str = Field(default="", max_length=40)
    avatar_preset_id: str = Field(default="", max_length=100)
    avatar_preset_version: str = Field(default="", max_length=40)


class MediaBatchConfirmRequest(MediaBatchPlanRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    paid_tts_confirmed: bool = Field(default=False)


class MediaPlaylistFreezeRequest(BaseModel):
    batch_id: Optional[str] = Field(default=None, max_length=128)


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


class AvatarCuesBuildRequest(BaseModel):
    """Freeze one successful TTS job into release-scoped P2 cue assets."""
    tts_job_id: str = Field(min_length=1, max_length=100)
    outline_node_id: Optional[str] = Field(None, max_length=100)
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=100)


class PptManifestBuildRequest(BaseModel):
    """Build the release-scoped PPT image manifest from the course source deck."""
    force: bool = Field(default=False, description="仅允许对当前草稿重新生成")


class SwitchPlaybackModeRequest(BaseModel):
    """播放模式切换请求（M3/M5）"""
    playback_mode: str = Field(pattern="^(auto|low_resource|compatibility)$")


# ---------------------------------------------------------------------------
# 媒体生成任务
# ---------------------------------------------------------------------------


@media_release_router.get("/course/{course_id}/platform-presets")
async def get_platform_media_presets(
    course_id: int,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return safe platform preset choices for the course media builder."""
    require_course_permission(session, current_user, course_id, "course.media.generate")
    runtime = resolve_stage8_tts_runtime()
    data = list_public_presets(session, active_tts_provider_key=runtime.provider_key)
    session.commit()
    return unified_response(code=200, message="平台音色与数字人角色已加载", data={
        **data,
        "effective_provider": runtime.effective_provider,
    })


@media_release_router.post("/course/{course_id}/batch/plan")
async def plan_media_batch(course_id: int, payload: MediaBatchPlanRequest,
                           session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.media.generate")
    plan = build_media_plan(
        session, course_id=course_id, node_ids=payload.node_ids,
        provider_key=payload.provider_key, provider_version=payload.provider_version, voice_id=payload.voice_id,
        voice_preset_id=payload.voice_preset_id, voice_preset_version=payload.voice_preset_version,
        avatar_preset_id=payload.avatar_preset_id, avatar_preset_version=payload.avatar_preset_version,
    )
    return unified_response(code=200, message="媒体批量计划已生成", data=plan)


@media_release_router.post("/course/{course_id}/batch/confirm")
async def confirm_media_batch_endpoint(course_id: int, payload: MediaBatchConfirmRequest,
                                       session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.media.generate")
    runtime = resolve_stage8_tts_runtime()
    if runtime.requires_confirmation and not payload.paid_tts_confirmed:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("批量 TTS 必须先明确确认可能产生 Provider 费用")
    plan = build_media_plan(
        session, course_id=course_id, node_ids=payload.node_ids,
        provider_key=payload.provider_key, provider_version=payload.provider_version, voice_id=payload.voice_id,
        voice_preset_id=payload.voice_preset_id, voice_preset_version=payload.voice_preset_version,
        avatar_preset_id=payload.avatar_preset_id, avatar_preset_version=payload.avatar_preset_version,
    )
    try:
        provider = get_stage8_tts_provider(plan["provider_key"])
    except TtsProviderConfigurationError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("Stage 8 TTS Provider 未正确配置，未创建或派发任务")
    if provider.requires_async_worker:
        from app.platform.tasks.worker import local_task_worker
        if not local_task_worker.has_handler("media.tts"):
            from app.core.exceptions import reject_dependency_unavailable
            reject_dependency_unavailable("media.tts Worker 未注册，未创建批量任务或发起任何 TTS 调用")
    batch, release, jobs = confirm_media_batch(session, course_id=course_id, created_by=int(current_user["user_id"]),
                                               plan=plan, idempotency_key=payload.idempotency_key, label=payload.label)
    voice_resource_version = str(plan.get("voice_resource_version") or "v1")
    for job in jobs:
        # Preserve safe preset identities on every durable job.  The raw
        # provider speaker remains server configuration and is never present.
        job.input_payload = {
            **(job.input_payload or {}),
            "voice_preset_id": release.voice_preset_id,
            "voice_preset_version": release.voice_preset_version,
            "voice_resource_version": voice_resource_version,
            "avatar_preset_id": release.avatar_preset_id,
            "avatar_preset_version": release.avatar_preset_version,
        }
        session.add(job)
    # Confirmation is the only batch operation allowed to dispatch TTS.  Fake
    # providers execute inline for local demos; paid providers go through the
    # existing media.tts worker path and never run on the request event loop.
    from app.models.course_outline_model import TeachingScriptNode
    from app.models.database import session_factory
    from app.platform.tasks.worker import local_task_worker
    pending_dispatches: list[tuple[str, dict]] = []

    def schedule_cue(source_job: MediaGenerationJob) -> None:
        """Create the non-billable Cue task after a batch TTS result.

        The Cue job is persisted together with the batch before its worker is
        submitted.  This keeps a fast local worker from racing the transaction
        that created the job, while ensuring Fake-provider batch results use
        exactly the same item/Cue projection as paid worker results.
        """
        cue_job, cue_task_id = enqueue_batch_cue(
            session,
            course_id=course_id,
            release_id=release.release_id,
            source_tts_job=source_job,
            created_by=int(current_user["user_id"]),
        )
        if cue_job.status != MediaGenerationStatus.PENDING:
            return
        if not local_task_worker.has_handler("media.timeline_publish"):
            from app.services.media_batch_service import project_cue_result_to_batch_item
            project_cue_result_to_batch_item(
                session,
                course_id=course_id,
                release_id=release.release_id,
                source_tts_job=source_job,
                error_code="DEPENDENCY_UNAVAILABLE",
                error_message_safe="Cue Worker 未注册，未冻结字幕与数字人时间轴",
            )
            return
        pending_dispatches.append((cue_task_id, {
            **(cue_job.input_payload or {}),
            "job_id": cue_job.job_id,
        }))

    for job in jobs:
        node = session.get(TeachingScriptNode, job.node_id) if job.node_id else None
        if node is None:
            continue
        if job.status == MediaGenerationStatus.SUCCEEDED:
            project_tts_result_to_batch_item(session, job=job)
            schedule_cue(job)
            continue
        provider = get_stage8_tts_provider(job.provider_key or None)
        if provider.requires_async_worker:
            prepared, worker_payload = tts_execution_service.prepare_tts_job_for_dispatch(
                session, course_id=course_id, job_id=job.job_id, script_text=node.content,
                voice_id="default", resource_version=voice_resource_version, provider_key=job.provider_key, max_retries=1,
            )
            pending_dispatches.append((prepared.task_id or "", worker_payload))
        else:
            completed = tts_execution_service.execute_tts_job(
                session, course_id=course_id, job_id=job.job_id, script_text=node.content,
                voice_id="default", resource_version=voice_resource_version, provider_key=job.provider_key, max_retries=1,
            )
            project_tts_result_to_batch_item(session, job=completed)
            if completed.status == MediaGenerationStatus.SUCCEEDED:
                schedule_cue(completed)
    refresh_batch_status(session, course_id=course_id, release_id=release.release_id)
    session.commit()
    for task_id, worker_payload in pending_dispatches:
        local_task_worker.submit(session_factory, task_id, worker_payload)
    return unified_response(code=202, message="批量媒体任务已确认", data={
        "batch_id": batch.batch_id, "release_id": release.release_id, "estimate": batch.estimate,
        "jobs": [_serialize_job(job) for job in jobs], "status": batch.status.value,
    })


@media_release_router.get("/course/{course_id}/batch/{batch_id}")
async def get_media_batch(course_id: int, batch_id: str, session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.media.generate")
    batch = session.exec(select(MediaBuildBatch).where(MediaBuildBatch.course_id == course_id, MediaBuildBatch.batch_id == batch_id)).first()
    if not batch:
        from app.core.exceptions import reject_resource_not_found
        reject_resource_not_found("批量媒体批次不存在")
    refresh_batch_status(session, course_id=course_id, release_id=batch.release_id or "")
    session.commit()
    items = list(session.exec(select(MediaReleaseItem).where(MediaReleaseItem.release_id == batch.release_id).order_by(MediaReleaseItem.order_index)).all())
    jobs = list(session.exec(select(MediaGenerationJob).where(MediaGenerationJob.media_release_id == batch.release_id).order_by(MediaGenerationJob.created_at.desc())).all())
    return unified_response(code=200, message="批量媒体状态获取成功", data={
        "batch_id": batch.batch_id, "release_id": batch.release_id, "status": batch.status.value,
        "estimate": batch.estimate,
        "voice_preset_id": batch.voice_preset_id,
        "voice_preset_version": batch.voice_preset_version,
        "avatar_preset_id": batch.avatar_preset_id,
        "avatar_preset_version": batch.avatar_preset_version,
        "items": [_serialize_release_item(item) for item in items],
        "jobs": [_serialize_job(job) for job in jobs],
    })


@media_release_router.get("/course/{course_id}/releases/{release_id}/items/{item_id}/preview")
async def preview_draft_release_item(
    course_id: int,
    release_id: str,
    item_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Sign a completed batch item only for the authorised construction UI.

    This intentionally has no student-readable equivalent: draft audio may be
    listened to by a course builder but cannot leak into the learner playback
    route until the complete playlist has been frozen and published.
    """
    require_course_permission(session, current_user, course_id, "course.media.generate")
    release = media_release_service.get_release(session, course_id=course_id, release_id=release_id)
    if release.status != MediaReleaseStatus.DRAFT:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("仅媒体草稿可试听批量知识点")
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
        MediaReleaseItem.item_id == item_id,
    )).first()
    if item is None:
        from app.core.exceptions import reject_resource_not_found
        reject_resource_not_found("批量媒体条目不存在")
    if not item.audio_object_key:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("该知识点的音频尚未生成完成")
    from app.services.object_storage import get_object_storage
    # Local drafts created before the audio ledger was introduced remain
    # immutable, but they still need a course-scoped MediaAsset record for the
    # guarded content route.  This does not call a Provider or modify bytes.
    repaired_assets = ensure_release_tts_assets_registered(
        session, course_id=course_id, release_id=release_id,
    )
    if repaired_assets:
        session.commit()
    storage = get_object_storage()
    if not storage.exists(item.audio_object_key):
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("草稿音频对象不可用")
    scope = {
        "course_id": course_id,
        "purpose": "media_draft_preview",
        "release_id": release_id,
        "item_id": item_id,
    }
    return unified_response(code=200, message="草稿媒体试听地址已签发", data={
        "release_id": release_id,
        "item_id": item.item_id,
        "node_id": item.node_id,
        "status": item.status,
        "duration_ms": item.duration_ms,
        "audio_url": storage.sign_read_url(item.audio_object_key, scope=scope),
        "subtitle_manifest_url": storage.sign_read_url(
            item.subtitle_manifest_object_key,
            scope={**scope, "purpose": "media_draft_preview_subtitle"},
        ) if item.subtitle_manifest_object_key else None,
        "avatar_cues_url": storage.sign_read_url(
            item.avatar_cues_object_key,
            scope={**scope, "purpose": "media_draft_preview_avatar_cues"},
        ) if item.avatar_cues_object_key else None,
    })


@media_release_router.get("/course/{course_id}/releases/{release_id}/items/{item_id}/preview-playback")
async def preview_draft_release_item_playback(
    course_id: int,
    release_id: str,
    item_id: str,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Return a builder-only playback surface for one completed draft item.

    The response intentionally uses the same audio/PPT/subtitle/Cue fields as
    the learner-facing adapter, but it is available only to a media builder
    and only while the MediaRelease remains a draft.  This lets the build
    page reuse the production player components without exposing a partial
    playlist to students.
    """
    require_course_permission(session, current_user, course_id, "course.media.generate")
    release = media_release_service.get_release(session, course_id=course_id, release_id=release_id)
    if release.status != MediaReleaseStatus.DRAFT:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("仅媒体草稿可预览批量知识点")
    item = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
        MediaReleaseItem.item_id == item_id,
    )).first()
    if item is None:
        from app.core.exceptions import reject_resource_not_found
        reject_resource_not_found("批量媒体条目不存在")
    if not item.audio_object_key:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("该知识点的音频尚未生成完成")
    from app.services.object_storage import get_object_storage
    repaired_assets = ensure_release_tts_assets_registered(
        session, course_id=course_id, release_id=release_id,
    )
    if repaired_assets:
        session.commit()
    storage = get_object_storage()
    if not storage.exists(item.audio_object_key):
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("草稿音频对象不可用")
    scope = {
        "course_id": course_id,
        "purpose": "media_draft_playback_preview",
        "release_id": release_id,
        "item_id": item_id,
    }
    subtitle_segments: list[dict[str, Any]] = []
    if item.subtitle_manifest_object_key and storage.exists(item.subtitle_manifest_object_key):
        try:
            subtitle_segments = list(json.loads(storage.get(item.subtitle_manifest_object_key).decode("utf-8")).get("segments") or [])
        except Exception:
            subtitle_segments = []
    ppt_timeline: list[dict[str, Any]] = []
    for mapping in (item.ppt_mapping_snapshot or {}).get("mappings") or []:
        refs = [int(page) for page in (mapping.get("page_refs") or []) if str(page).isdigit()]
        if not refs:
            refs = list(range(int(mapping.get("page_start") or 1), int(mapping.get("page_end") or 1) + 1))
        for index, page in enumerate(refs):
            ppt_timeline.append({
                "ppt_page": page,
                "material_version_id": mapping.get("material_version_id"),
                "start_ms": int(item.duration_ms * index / max(len(refs), 1)),
            })
    _, avatar_manifest_url, avatar_asset_urls = sign_avatar_package_for_release(
        session,
        course_id=course_id,
        release_id=release_id,
        preset_id=release.avatar_preset_id,
        preset_version=release.avatar_preset_version,
    )
    return unified_response(code=200, message="草稿统一播放器预览数据已签发", data={
        "schema": "draft-media-preview/v1",
        "release_id": release_id,
        "item_id": item.item_id,
        "node_id": item.node_id,
        "audio_url": storage.sign_read_url(item.audio_object_key, scope=scope),
        "duration_ms": item.duration_ms,
        "subtitle_manifest_url": storage.sign_read_url(
            item.subtitle_manifest_object_key,
            scope={**scope, "purpose": "media_draft_playback_preview_subtitle"},
        ) if item.subtitle_manifest_object_key else None,
        "subtitle_segments": subtitle_segments,
        "avatar_cues_url": storage.sign_read_url(
            item.avatar_cues_object_key,
            scope={**scope, "purpose": "media_draft_playback_preview_avatar_cues"},
        ) if item.avatar_cues_object_key else None,
        "ppt_manifest_url": storage.sign_read_url(
            release.ppt_manifest_object_key,
            scope={**scope, "purpose": "media_draft_playback_preview_ppt"},
        ) if release.ppt_manifest_object_key and storage.exists(release.ppt_manifest_object_key) else None,
        "ppt_timeline": ppt_timeline,
        "avatar_preset_id": release.avatar_preset_id,
        "avatar_preset_version": release.avatar_preset_version,
        "avatar_manifest_url": avatar_manifest_url,
        "avatar_asset_urls": avatar_asset_urls,
    })


@media_release_router.post("/course/{course_id}/releases/{release_id}/audio-playlist")
async def freeze_audio_playlist(course_id: int, release_id: str, payload: MediaPlaylistFreezeRequest,
                                session: Session = Depends(get_session), current_user: dict = Depends(get_current_user)):
    require_course_permission(session, current_user, course_id, "course.media.generate")
    if payload.batch_id:
        batch = session.exec(select(MediaBuildBatch).where(
            MediaBuildBatch.course_id == course_id,
            MediaBuildBatch.batch_id == payload.batch_id,
            MediaBuildBatch.release_id == release_id,
        )).first()
        if batch is None:
            from app.core.exceptions import reject_validation_failed
            reject_validation_failed("批量媒体批次与待冻结的媒体版本不匹配")
    result = freeze_playlist(session, course_id=course_id, release_id=release_id)
    session.commit()
    return unified_response(code=200, message="audio-playlist/v1 已冻结", data=result)


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

    # ``node_id`` is the database FK consumed by MediaReleaseCue, rather than
    # the public ``tsn_*`` editor identifier.  Validate an optional binding
    # when the course has formal teaching-script rows.  Legacy timeline-only
    # courses do not carry this table yet and retain their existing media
    # migration path.
    if payload.node_id is not None:
        script_node = session.exec(select(TeachingScriptNode).where(
            TeachingScriptNode.id == payload.node_id,
            TeachingScriptNode.course_id == course_id,
        )).first()
        has_formal_scripts = session.exec(select(TeachingScriptNode.id).where(
            TeachingScriptNode.course_id == course_id,
        )).first() is not None
        if script_node is None and has_formal_scripts:
            from app.core.exceptions import reject_validation_failed
            reject_validation_failed("媒体任务绑定的讲稿节点不存在或不属于当前课程")

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
    """执行或派发 TTS 任务。

    Fake/Mock 可为离线回归同步执行；真实付费 Provider 返回 202 并交由
    ``media.tts`` Worker 消费，避免在 FastAPI 请求路径持有长连接。
    """
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    job = media_generation_job_service.get_job(session, course_id=course_id, job_id=job_id)
    if job.job_type != MediaGenerationJobType.TTS:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(f"任务类型 {job.job_type.value} 不是 tts，无法执行 TTS")

    selected_provider_key = payload.provider_key or job.provider_key or None
    try:
        provider = get_stage8_tts_provider(selected_provider_key)
    except TtsProviderConfigurationError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("所选 TTS Provider 未注册，任务未调用任何外部服务")

    if provider.requires_async_worker:
        from app.models.database import session_factory
        from app.platform.tasks.worker import local_task_worker
        if not local_task_worker.has_handler("media.tts"):
            from app.core.exceptions import reject_dependency_unavailable
            reject_dependency_unavailable("media.tts Worker 未注册，未发起任何 TTS 调用")
        prepared, worker_payload = tts_execution_service.prepare_tts_job_for_dispatch(
            session,
            course_id=course_id,
            job_id=job_id,
            script_text=payload.script_text,
            voice_id=payload.voice_id,
            resource_version=payload.resource_version,
            provider_key=selected_provider_key,
            max_retries=payload.max_retries,
        )
        session.commit()
        local_task_worker.submit(session_factory, prepared.task_id or "", worker_payload)
        return unified_response(
            code=202, message="豆包 TTS 任务已提交至 Media Worker",
            data={**_serialize_job(prepared), "async": True},
        )

    # Fake/Mock compatibility path: no paid provider is contacted here.  This
    # remains useful for offline demos and automated regression tests.
    updated = tts_execution_service.execute_tts_job(
        session,
        course_id=course_id,
        job_id=job_id,
        script_text=payload.script_text,
        voice_id=payload.voice_id,
        resource_version=payload.resource_version,
        provider_key=payload.provider_key or None,
        max_retries=payload.max_retries,
    )
    session.commit()
    return unified_response(
        code=200, message="TTS 任务执行完成",
        data=_serialize_job(updated),
    )


@media_release_router.post("/course/{course_id}/generation-jobs/{job_id}/retry")
async def retry_tts_job(
    course_id: int,
    job_id: str,
    payload: TtsJobExecuteRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """人工重跑失败的 TTS 任务

    - 仅 failed 状态任务可重跑
    - 重置状态后重新执行，支持指定 max_retries
    """
    require_course_permission(
        session, current_user, course_id, "course.media.generate",
    )
    job = media_generation_job_service.get_job(session, course_id=course_id, job_id=job_id)
    if job.job_type != MediaGenerationJobType.TTS:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(f"任务类型 {job.job_type.value} 不是 tts，无法重跑")

    selected_provider_key = payload.provider_key or job.provider_key or None
    try:
        provider = get_stage8_tts_provider(selected_provider_key)
    except TtsProviderConfigurationError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("所选 TTS Provider 未注册，任务未调用任何外部服务")

    if provider.requires_async_worker:
        from app.models.database import session_factory
        from app.platform.tasks.worker import local_task_worker
        if not local_task_worker.has_handler("media.tts"):
            from app.core.exceptions import reject_dependency_unavailable
            reject_dependency_unavailable("media.tts Worker 未注册，未发起任何 TTS 调用")
        prepared, worker_payload = tts_execution_service.prepare_tts_job_for_dispatch(
            session,
            course_id=course_id,
            job_id=job_id,
            script_text=payload.script_text,
            voice_id=payload.voice_id,
            resource_version=payload.resource_version,
            provider_key=selected_provider_key,
            max_retries=payload.max_retries,
            retry=True,
        )
        session.commit()
        local_task_worker.submit(session_factory, prepared.task_id or "", worker_payload)
        return unified_response(
            code=202, message="豆包 TTS 重跑任务已提交至 Media Worker",
            data={**_serialize_job(prepared), "async": True},
        )

    updated = tts_execution_service.retry_job(
        session,
        course_id=course_id,
        job_id=job_id,
        script_text=payload.script_text,
        voice_id=payload.voice_id,
        resource_version=payload.resource_version,
        provider_key=payload.provider_key or None,
        max_retries=payload.max_retries,
    )
    session.commit()
    return unified_response(
        code=200, message="TTS 任务重跑完成",
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
    items = list(session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
    ).order_by(MediaReleaseItem.order_index)).all())
    data = _serialize_release(release)
    data["cues"] = [_serialize_release_cue(c) for c in cues]
    data["items"] = [_serialize_release_item(item) for item in items]
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


@media_release_router.post("/course/{course_id}/releases/{release_id}/avatar-cues")
async def build_avatar_cues(
    course_id: int,
    release_id: str,
    payload: AvatarCuesBuildRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Submit the non-billable P2 Cue Worker for a completed TTS job.

    The endpoint never calls a speech Provider.  It only reads an existing
    TTS object, normalizes its persisted timing metadata, and writes immutable
    ``subtitle-manifest/v1`` / ``avatar-cues/v1`` assets for the draft release.
    """
    require_course_permission(session, current_user, course_id, "course.media.generate")
    release = media_release_service.get_release(
        session, course_id=course_id, release_id=release_id,
    )
    if release.status != MediaReleaseStatus.DRAFT:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("仅从未激活的媒体草稿可生成数字人时间轴")
    source_job = media_generation_job_service.get_job(
        session, course_id=course_id, job_id=payload.tts_job_id,
    )
    if source_job.job_type != MediaGenerationJobType.TTS or source_job.status != MediaGenerationStatus.SUCCEEDED:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("请先完成指定 TTS 任务，再生成数字人时间轴")
    if source_job.node_id is None:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("TTS 任务未绑定讲稿节点，无法形成可导航的播放 Cue")

    worker_payload = {
        "course_id": course_id,
        "release_id": release_id,
        "source_tts_job_id": source_job.job_id,
        "outline_node_id": payload.outline_node_id,
    }
    input_hash = hashlib.sha256(
        json.dumps(worker_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    idempotency_key = payload.idempotency_key or f"cue:{release_id}:{source_job.job_id}"
    existing = session.exec(select(MediaGenerationJob).where(
        MediaGenerationJob.course_id == course_id,
        MediaGenerationJob.idempotency_key == idempotency_key,
    )).first()
    if existing is not None:
        if existing.status == MediaGenerationStatus.FAILED:
            from app.core.exceptions import reject_state_conflict
            reject_state_conflict(
                "此前的 Cue Worker 已失败；请使用新的幂等键重新提交",
                details={"cue_job_id": existing.job_id, "error_code": existing.error_code},
            )
        return unified_response(
            code=202,
            message="相同 Cue Worker 已存在",
            data={**_serialize_job(existing), "async": existing.status == MediaGenerationStatus.RUNNING},
        )
    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course_id,
        job_type=MediaGenerationJobType.TIMELINE_PUBLISH,
        created_by=int(current_user["user_id"]),
        provider_key="avatar-cues",
        provider_version="v1",
        node_id=source_job.node_id,
        input_summary="冻结 TTS 字幕与数字人时间轴",
        input_payload=worker_payload,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
        media_release_id=release_id,
    )
    from app.models.database import session_factory
    from app.platform.tasks.worker import local_task_worker
    if not local_task_worker.has_handler("media.timeline_publish"):
        from app.core.exceptions import reject_dependency_unavailable
        reject_dependency_unavailable("Cue Worker 未注册，未修改发布版本")
    worker_payload = {**worker_payload, "job_id": job.job_id}
    session.commit()
    local_task_worker.submit(session_factory, task_id, worker_payload)
    return unified_response(
        code=202,
        message="Cue Worker 已提交，未调用任何 TTS Provider",
        data={**_serialize_job(job), "async": True},
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/ppt-manifest")
async def enqueue_ppt_manifest_build(
    course_id: int,
    release_id: str,
    payload: PptManifestBuildRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Queue a cache-first PPT manifest build and return immediately.

    The worker reuses source-slide images produced by the mapping pipeline.
    It renders only missing PPTX pages and writes safe page counters to the
    media job so the authoring page can poll progress without holding an HTTP
    request open.
    """
    access = require_course_permission(session, current_user, course_id, "course.media.generate")
    release = media_release_service.get_release(session, course_id=course_id, release_id=release_id)
    if release.status not in (MediaReleaseStatus.DRAFT, MediaReleaseStatus.WITHDRAWN):
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("Only draft or withdrawn media releases can build a PPT manifest")
    if release.ppt_manifest_object_key and not payload.force:
        return unified_response(
            code=200,
            message="PPT manifest already exists",
            data={
                "release_id": release_id,
                "ppt_manifest_object_key": release.ppt_manifest_object_key,
                "async": False,
            },
        )

    from app.models.database import session_factory
    from app.models.task_model import TaskRecord
    from app.platform.tasks.worker import local_task_worker
    from app.services.ppt_manifest_service import ppt_manifest_input_fingerprint

    if not local_task_worker.has_handler("media.ppt_manifest"):
        from app.core.exceptions import reject_dependency_unavailable
        reject_dependency_unavailable("PPT manifest worker is not registered; release was not changed")

    input_hash = ppt_manifest_input_fingerprint(session, course_id=course_id)
    force_suffix = "normal"
    if payload.force:
        # A force request rebuilds the release-scoped manifest binding, never
        # bypasses the source-page cache.  Include the prior binding only to
        # allow a later explicit rebuild after a successful task.
        force_suffix = hashlib.sha256((release.ppt_manifest_object_key or "none").encode("utf-8")).hexdigest()[:12]
    idempotency_key = f"ppt-manifest:{release_id}:{input_hash[:32]}:{force_suffix}"
    existing = session.exec(select(MediaGenerationJob).where(
        MediaGenerationJob.course_id == course_id,
        MediaGenerationJob.idempotency_key == idempotency_key,
    )).first()
    if existing is not None:
        worker_payload = {
            "course_id": course_id,
            "release_id": release_id,
            "job_id": existing.job_id,
        }
        if existing.status in (MediaGenerationStatus.PENDING, MediaGenerationStatus.RUNNING):
            return unified_response(
                code=202,
                message="PPT manifest worker is already queued",
                data={**_serialize_job(existing), "async": True},
            )
        if existing.status in (MediaGenerationStatus.FAILED, MediaGenerationStatus.CANCELLED):
            if not existing.task_id:
                from app.core.exceptions import reject_state_conflict
                reject_state_conflict("The failed PPT manifest job has no task record and cannot be retried")
            task_service.retry(
                session,
                existing.task_id,
                operator_user_id=int(access.user_id),
            )
            existing.status = MediaGenerationStatus.PENDING
            existing.error_code = ""
            existing.error_message_safe = ""
            existing.finished_at = None
            existing.output_metadata = {}
            existing.input_payload = worker_payload
            session.add(existing)
            session.commit()
            local_task_worker.submit(session_factory, existing.task_id, worker_payload)
            return unified_response(
                code=202,
                message="PPT manifest worker retried",
                data={**_serialize_job(existing), "async": True},
            )
        return unified_response(
            code=200,
            message="PPT manifest worker has already completed",
            data={**_serialize_job(existing), "async": False},
        )

    task_payload = {
        "course_id": course_id,
        "release_id": release_id,
        "source_fingerprint": input_hash[:16],
    }
    job, task_id = media_generation_job_service.create_job(
        session,
        course_id=course_id,
        job_type=MediaGenerationJobType.PPT_MANIFEST,
        created_by=int(access.user_id),
        provider_key="ppt-source-cache",
        provider_version="ppt-manifest/v1",
        input_summary="PPT manifest: reuse cached pages and render only missing pages",
        input_payload=task_payload,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
        media_release_id=release_id,
    )
    worker_payload = {**task_payload, "job_id": job.job_id}
    job.input_payload = worker_payload
    task_record = session.exec(select(TaskRecord).where(TaskRecord.task_id == task_id)).first()
    if task_record is not None:
        task_record.input_payload = json.dumps(worker_payload, ensure_ascii=False, sort_keys=True)
        session.add(task_record)
    session.add(job)
    session.commit()
    local_task_worker.submit(session_factory, task_id, worker_payload)
    return unified_response(
        code=202,
        message="PPT manifest worker queued",
        data={**_serialize_job(job), "async": True},
    )


@media_release_router.post("/course/{course_id}/releases/{release_id}/ppt-manifest/sync", include_in_schema=False)
async def build_ppt_manifest(
    course_id: int,
    release_id: str,
    payload: PptManifestBuildRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Render and bind an immutable ``ppt-manifest/v1`` to a draft release."""
    from app.core.exceptions import reject_state_conflict
    reject_state_conflict(
        "Synchronous PPT manifest rendering was removed; use the background manifest endpoint",
        details={"error_code": "PPT_MANIFEST_ASYNC_REQUIRED"},
    )

    # Kept below temporarily as a source-level reference for the old endpoint
    # contract.  The early state conflict above makes this route non-operative.
    require_course_permission(session, current_user, course_id, "course.media.generate")
    release = media_release_service.get_release(session, course_id=course_id, release_id=release_id)
    if release.status not in (MediaReleaseStatus.DRAFT, MediaReleaseStatus.WITHDRAWN):
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict("仅草稿或撤回版本可生成 PPT manifest")
    if release.ppt_manifest_object_key and not payload.force:
        return unified_response(
            code=200,
            message="PPT manifest 已存在",
            data={"release_id": release_id, "ppt_manifest_object_key": release.ppt_manifest_object_key},
        )
    from app.services.ppt_manifest_service import PptManifestGenerationError, build_ppt_manifest
    try:
        manifest = build_ppt_manifest(session, course_id=course_id, release=release)
    except PptManifestGenerationError as exc:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict(
            "PPT manifest generation failed",
            details={"error_code": "PPT_MANIFEST_GENERATION_FAILED", "cause": str(exc)[:200]},
        )
    if manifest is None:
        return unified_response(
            code=409,
            message="当前课程没有可渲染的 PPT/PDF 源文件",
            data={"release_id": release_id, "reason": "ppt_source_unavailable"},
        )
    session.commit()
    return unified_response(
        code=200,
        message="ppt-manifest/v1 已生成",
        data={
            "release_id": release_id,
            "schema": manifest["schema"],
            "ppt_manifest_object_key": release.ppt_manifest_object_key,
            "source_sha256": manifest["source_sha256"],
            "page_count": len(manifest["pages"]),
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
    # Manifest rendering is a dedicated background job.  Activation only
    # verifies its immutable output so a click here can never start a second
    # LibreOffice conversion after the authoring request timed out.
    release_for_manifest = media_release_service.get_release(
        session, course_id=course_id, release_id=release_id,
    )
    from app.services.ppt_manifest_service import has_ppt_manifest_source
    if has_ppt_manifest_source(session, course_id=course_id) and not release_for_manifest.ppt_manifest_object_key:
        from app.core.exceptions import reject_state_conflict
        reject_state_conflict(
            "PPT manifest is still pending; wait for the background media job before activation",
            details={"error_code": "PPT_MANIFEST_PENDING"},
        )
    try:
        media_release_service.ensure_ppt_manifest(
            session, course_id=course_id, release_id=release_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        # A declared PPT/PDF source is part of the release contract. Do not
        # activate a release that would silently fall back to stale slides.
        from app.core.exceptions import reject_state_conflict
        logger = __import__("logging").getLogger(__name__)
        logger.exception("PPT manifest generation failed during activation")
        reject_state_conflict(
            "PPT manifest generation failed; release was not activated",
            details={
                "error_code": "PPT_MANIFEST_GENERATION_FAILED",
                "cause": str(exc)[:200],
            },
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
        "audio_playlist_object_key": release.audio_playlist_object_key,
        "audio_playlist_sha256": release.audio_playlist_sha256,
        "voice_preset_id": release.voice_preset_id,
        "voice_preset_version": release.voice_preset_version,
        "avatar_preset_id": release.avatar_preset_id,
        "avatar_preset_version": release.avatar_preset_version,
        "avatar_cues_object_key": release.avatar_cues_object_key,
        "avatar_binding_id": release.avatar_binding_id,
        "digital_human_manifest_object_key": release.digital_human_manifest_object_key,
        "default_playback_mode": release.default_playback_mode.value,
        "capability_profile_id": release.capability_profile_id,
        "notes": release.notes,
        "created_at": release.created_at.isoformat() if release.created_at else None,
        "activated_at": release.activated_at.isoformat() if release.activated_at else None,
        "superseded_at": release.superseded_at.isoformat() if release.superseded_at else None,
        "withdrawn_at": release.withdrawn_at.isoformat() if release.withdrawn_at else None,
        "release_metadata": release.release_metadata or {},
    }


def _serialize_release_item(item) -> dict[str, Any]:
    return {
        "item_id": item.item_id, "release_id": item.release_id, "course_id": item.course_id,
        "node_id": item.node_id, "outline_node_id": item.outline_node_id, "order_index": item.order_index,
        "script_hash": item.script_hash, "status": item.status, "audio_object_key": item.audio_object_key,
        "audio_sha256": item.audio_sha256, "duration_ms": item.duration_ms,
        "subtitle_manifest_object_key": item.subtitle_manifest_object_key,
        "avatar_cues_object_key": item.avatar_cues_object_key,
        "ppt_mapping_snapshot": item.ppt_mapping_snapshot, "tts_job_id": item.tts_job_id,
        "error_code": item.error_code, "error_message_safe": item.error_message_safe,
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
        "material_version_id": (cue.cue_metadata or {}).get("material_version_id"),
        "outline_node_id": (cue.cue_metadata or {}).get("outline_node_id"),
        "subtitle_text": cue.subtitle_text,
        "script_reference": cue.script_reference,
        "audio_object_key": cue.audio_object_key,
        "video_object_key": cue.video_object_key,
    }


# ---------------------------------------------------------------------------
# M3/M5 Provider 健康检查、开关与故障切换
# ---------------------------------------------------------------------------


@media_release_router.get("/providers/health")
async def get_providers_health(
    current_user: dict = Depends(get_current_user),
):
    """查询所有 Provider 健康状态（M3/M5）

    返回 TTS 和数字人 Provider 的健康检查结果与当前配置。
    不需要课程权限，仅限已登录用户。
    """
    from app.services.digital_human_provider import get_digital_human_provider
    from app.core.config import settings

    tts_runtime = resolve_stage8_tts_runtime()
    dh_provider = get_digital_human_provider()

    dh_health = dh_provider.health_check()

    return unified_response(
        code=200, message="Provider 健康状态查询成功",
        data={
            "tts": tts_runtime.as_public_dict(),
            "digital_human": {
                "provider_key": dh_provider.provider_key,
                "provider_version": dh_provider.provider_version,
                "healthy": dh_health.healthy,
                "status_message": dh_health.message,
                "configured_provider": getattr(settings, "STAGE8_DH_PROVIDER", "fake"),
                "fallback_on_failure": getattr(settings, "DH_PROVIDER_FALLBACK_ON_FAILURE", True),
            },
        },
    )


@media_release_router.post("/course/{course_id}/playback/switch-mode")
async def switch_playback_mode(
    course_id: int,
    payload: "SwitchPlaybackModeRequest",
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """学生端手动切换播放模式（M3/M5）

    - 学生可手动切换 auto/low_resource/compatibility
    - 仅影响当前学生的播放会话，不修改 MediaRelease.default_playback_mode
    - 数字人 Provider 故障时系统自动降级到 compatibility
    """
    require_course_permission(session, current_user, course_id, "course.content.read")

    try:
        mode = PlaybackMode(payload.playback_mode)
    except ValueError:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed(f"不支持的播放模式: {payload.playback_mode}")

    # 返回切换确认与兼容模式信息
    return unified_response(
        code=200, message="播放模式已切换",
        data={
            "course_id": course_id,
            "playback_mode": mode.value,
            "digital_human_enabled": mode != PlaybackMode.COMPATIBILITY,
            "fallback_supported": True,
            "message": (
                "已切换到兼容模式（音频+字幕+PPT+讲稿）" if mode == PlaybackMode.COMPATIBILITY
                else f"已切换到 {mode.value} 模式"
            ),
        },
    )


# ---------------------------------------------------------------------------
# M5 对象存储迁移
# ---------------------------------------------------------------------------


class StorageMigrateRequest(BaseModel):
    """对象存储迁移请求（M5）"""
    object_keys: list[str] = Field(default_factory=list, description="待迁移的 object_key 列表；为空则迁移全部")
    prefix: str = Field(default="", max_length=500, description="按前缀过滤；与 object_keys 互斥")
    delete_source: bool = Field(default=False, description="迁移成功后删除源文件")
    source_backend: str = Field(default="local", pattern="^(local|s3|minio|oss)$")
    target_backend: str = Field(default="s3", pattern="^(local|s3|minio|oss)$")


@media_release_router.post("/storage/migrate")
async def migrate_storage(
    payload: StorageMigrateRequest,
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """对象存储迁移（M5）

    将 object_key 从当前存储后端迁移到另一个后端。
    管理员操作，用于本地→OSS 迁移演练。

    约束来源: "Object storage migration must implement resumable task ledger
    with per-object migration status and byte SHA verification"

    实现要点:
    - 使用 ObjectMigrationLedger 持久化每个 object_key 的迁移状态
    - 逐对象 byte SHA 校验：source_sha256 与 target_sha256 必须一致才标记 verified
    - 重新调用本接口可断点续传：跳过 verified，重试 failed，续传 in_progress
    - 单对象失败不阻断整批；超过 max_attempts 标记 failed 不再自动重试
    """
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)

    from app.core.config import settings
    from app.services.object_storage import (
        ObjectMigrationLedger,
        build_object_storage_provider,
        list_object_keys_under_prefix,
        migrate_object_keys_resumable,
    )

    source = build_object_storage_provider(payload.source_backend)
    target = build_object_storage_provider(payload.target_backend)
    if payload.source_backend == payload.target_backend:
        from app.core.exceptions import reject_validation_failed
        reject_validation_failed("source_backend 与 target_backend 必须不同")

    keys = payload.object_keys
    if not keys and payload.prefix:
        keys = list_object_keys_under_prefix(source, payload.prefix)

    if not keys:
        return unified_response(
            code=200, message="无可迁移的 object_key",
            data={
                "migrated_count": 0,
                "failed_count": 0,
                "skipped_count": 0,
                "summary": {"pending": 0, "in_progress": 0, "migrated": 0, "verified": 0, "failed": 0, "total": 0},
            },
        )

    # 使用可恢复账本：每个 object_key 独立状态机 + byte SHA 校验
    ledger = ObjectMigrationLedger(settings.OBJECT_STORAGE_MIGRATION_LEDGER_PATH)
    report = migrate_object_keys_resumable(
        source,
        target,
        keys,
        ledger=ledger,
        delete_source=payload.delete_source,
        max_attempts=settings.OBJECT_STORAGE_MIGRATION_MAX_ATTEMPTS,
    )
    # 透出账本路径便于运维查看断点状态
    report["ledger_path"] = settings.OBJECT_STORAGE_MIGRATION_LEDGER_PATH
    report["delete_source"] = payload.delete_source
    return unified_response(
        code=200, message="对象存储迁移完成",
        data=report,
    )


@media_release_router.get("/storage/migrate/status")
async def get_storage_migrate_status(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """查询对象存储迁移账本状态（M5）

    管理员可查看每个 object_key 的迁移状态、SHA、attempts、last_error，
    用于断点续传前评估是否需要人工介入或重置 failed 条目。
    """
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)

    from app.core.config import settings
    from app.services.object_storage import ObjectMigrationLedger

    ledger = ObjectMigrationLedger(settings.OBJECT_STORAGE_MIGRATION_LEDGER_PATH)
    summary = ledger.summary()
    # 透出失败条目详情便于人工介入
    failed_entries = [
        {"object_key": k, "attempts": v.get("attempts", 0), "last_error": v.get("last_error", "")}
        for k, v in ledger._entries.items()
        if v.get("status") == "failed"
    ]
    return unified_response(
        code=200, message="对象存储迁移账本状态",
        data={
            "summary": summary,
            "ledger_path": settings.OBJECT_STORAGE_MIGRATION_LEDGER_PATH,
            "failed_entries": failed_entries,
        },
    )


@media_release_router.post("/storage/migrate/reset-failed")
async def reset_failed_migration_entries(
    session: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """重置 failed 状态的迁移条目为 pending，允许重新尝试（M5）

    人工介入后（如修复源对象、扩充配额、修正凭据）可调用此接口清空 failed
    状态，再次调用 /storage/migrate 时这些条目将重新进入迁移流程。
    """
    require_platform_permission(session, current_user, PlatformPermission.ADMIN)

    from app.core.config import settings
    from app.services.object_storage import ObjectMigrationLedger

    ledger = ObjectMigrationLedger(settings.OBJECT_STORAGE_MIGRATION_LEDGER_PATH)
    reset_count = 0
    for key, entry in list(ledger._entries.items()):
        if entry.get("status") == "failed":
            # 保留 attempts 历史以便审计；重置状态为 pending
            entry["status"] = "pending"
            entry["last_error"] = ""
            reset_count += 1
    if reset_count:
        ledger._save()
    return unified_response(
        code=200, message="已重置 failed 状态迁移条目",
        data={
            "reset_count": reset_count,
            "summary_after_reset": ledger.summary(),
        },
    )
