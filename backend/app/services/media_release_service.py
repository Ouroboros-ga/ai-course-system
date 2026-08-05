"""阶段8 媒体生成与发布服务

实现「讲稿 → TTS → 字幕/PPT 时间轴 → MediaRelease → 学生端播放」的服务编排。

设计要点：
- 所有异步任务通过 `task_service` 持久化，不在主 Web 请求里同步执行外部调用
- `MediaGenerationJobService` 创建/查询生成任务，对接 task_service.TaskRecord
- `MediaReleaseService` 负责发布版本管理：创建草稿 → 激活 → 回滚 → 撤回
- `MediaPlaybackService` 为学生端提供统一播放清单（音频+字幕+PPT+数字人 manifest）
- 失败时必须保留原始 error_code，禁止把 503/超时伪装成成功
- 所有读取继续经过 Course Access v1，按 course_id 严格隔离
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_capability_disabled,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_aware
from app.models.media_release_model import (
    MediaGenerationAttempt,
    MediaGenerationJob,
    MediaGenerationJobType,
    MediaGenerationStatus,
    MediaRelease,
    MediaReleaseCue,
    MediaReleaseStatus,
    PlaybackCapabilityProfile,
    PlaybackMode,
)
from app.models.media_timeline_model import MediaAsset, MediaTimelineCue, StorageBackend
from app.services.digital_human_provider import (
    DigitalHumanPlaybackRequest,
    get_digital_human_provider,
)
from app.services.object_storage import get_object_storage, mime_type_for
from app.services.task_service import TaskCreateRequest, task_service
from app.services.tts_provider import (
    TtsSynthesisRequest,
    TtsProviderConfigurationError,
    get_tts_provider,
)


logger = logging.getLogger(__name__)


class TtsAssetRegistrationError(RuntimeError):
    error_code = "TTS_ASSET_REGISTRATION_FAILED"
    safe_message = "TTS 音频已生成但无法登记为受课程权限保护的媒体资产"


def _register_tts_audio_asset(
    session: Session,
    *,
    course_id: int,
    object_key: str,
    duration_ms: int = 0,
    audio_sha256: str = "",
    provider_key: str = "",
    provider_version: str = "",
) -> None:
    """Keep the media ledger in sync before a TTS job becomes successful."""
    object_key = str(object_key or "")
    if not object_key:
        raise TtsAssetRegistrationError("TTS 音频缺少 object_key")
    existing = session.exec(select(MediaAsset).where(MediaAsset.object_key == object_key)).first()
    if existing is not None:
        if existing.course_id != course_id:
            raise TtsAssetRegistrationError("TTS 音频对象与课程归属不一致")
        return
    storage = get_object_storage()
    try:
        head = storage.head(object_key)
    except Exception as exc:
        raise TtsAssetRegistrationError("TTS 音频对象无法读取") from exc
    backend = StorageBackend.LOCAL if getattr(storage, "backend_name", "local") == "local" else StorageBackend.OSS
    session.add(MediaAsset(
        course_id=course_id,
        object_key=object_key,
        asset_type="audio",
        backend=backend,
        mime_type=mime_type_for(object_key),
        size_bytes=int(head.get("size_bytes") or 0),
        duration_seconds=max(0, int(duration_ms or 0)) / 1_000,
        content_hash=str(audio_sha256 or ""),
        resource_version=f"tts/{provider_key}/{provider_version}",
    ))
    session.flush()


def ensure_release_tts_assets_registered(
    session: Session,
    *,
    course_id: int,
    release_id: str,
) -> int:
    """Backfill ledger entries for immutable, previously-generated draft audio.

    Some local Demo batches were created before TTS audio began to be entered
    in ``media_assets``.  The signed content endpoint deliberately refuses
    unregistered object keys, so a builder could see a completed draft but
    receive a 404 when trying to listen.  This function only registers an
    existing object after checking its immutable key, course ownership and
    bytes; it never synthesizes, copies, or overwrites media.
    """
    from app.models.media_release_model import MediaReleaseItem

    storage = get_object_storage()
    repaired = 0
    items = session.exec(select(MediaReleaseItem).where(
        MediaReleaseItem.course_id == course_id,
        MediaReleaseItem.release_id == release_id,
    )).all()
    for item in items:
        object_key = str(item.audio_object_key or "")
        if not object_key or not storage.exists(object_key):
            continue
        existing = session.exec(select(MediaAsset).where(
            MediaAsset.object_key == object_key,
        )).first()
        if existing is not None:
            if existing.course_id != course_id:
                raise TtsAssetRegistrationError("TTS 音频对象与课程归属不一致")
            continue
        _register_tts_audio_asset(
            session,
            course_id=course_id,
            object_key=object_key,
            duration_ms=int(item.duration_ms or 0),
            audio_sha256=str(item.audio_sha256 or ""),
            provider_key="legacy_draft",
            provider_version="asset-ledger-backfill-v1",
        )
        repaired += 1
    return repaired


# ---------------------------------------------------------------------------
# 媒体生成任务服务
# ---------------------------------------------------------------------------


class MediaGenerationJobService:
    """媒体生成任务服务

    - 通过 task_service 持久化任务状态，本服务只维护媒体领域元数据
    - 支持幂等创建（idempotency_key + course_id 唯一）
    - 失败时保留原始 error_code 与 error_message_safe
    """

    def create_job(
        self,
        session: Session,
        *,
        course_id: int,
        job_type: MediaGenerationJobType,
        created_by: int,
        provider_key: str = "",
        provider_version: str = "",
        node_id: Optional[int] = None,
        input_summary: str = "",
        input_payload: Optional[dict] = None,
        input_hash: str = "",
        idempotency_key: str = "",
        avatar_id: Optional[str] = None,
        media_release_id: Optional[str] = None,
    ) -> tuple[MediaGenerationJob, str]:
        """创建媒体生成任务，返回 (job, task_id)

        task_id 由 task_service 分配；调用方随后调用 `execute_job` 执行实际工作。
        """
        if not idempotency_key:
            idempotency_key = "auto_" + uuid.uuid4().hex[:16]

        # 幂等检查：同 course_id + idempotency_key 已存在则直接返回
        existing = session.exec(
            select(MediaGenerationJob).where(
                MediaGenerationJob.course_id == course_id,
                MediaGenerationJob.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            return existing, existing.task_id or ""

        # 在 task_service 创建统一任务
        task_view = task_service.create_task(session, TaskCreateRequest(
            task_type=f"media.{job_type.value}",
            owner_user_id=created_by,
            course_id=course_id,
            node_id=node_id,
            input_summary=input_summary[:500],
            input_payload=input_payload or {},
            idempotency_key=f"media:{course_id}:{idempotency_key}",
            resource_links=[{
                "resource_kind": "media_generation_job",
                "resource_id": "pending",
                "relation": "output",
            }],
        ))

        job = MediaGenerationJob(
            course_id=course_id,
            node_id=node_id,
            job_type=job_type,
            status=MediaGenerationStatus.PENDING,
            provider_key=provider_key,
            provider_version=provider_version,
            input_hash=input_hash,
            idempotency_key=idempotency_key,
            input_summary=input_summary,
            input_payload=input_payload or {},
            task_id=task_view.task_id,
            avatar_id=avatar_id,
            media_release_id=media_release_id,
            created_by=created_by,
        )
        session.add(job)
        session.flush()
        return job, task_view.task_id

    def get_job(self, session: Session, *, course_id: int, job_id: str) -> MediaGenerationJob:
        job = session.exec(
            select(MediaGenerationJob).where(
                MediaGenerationJob.job_id == job_id,
                MediaGenerationJob.course_id == course_id,
            )
        ).first()
        if job is None:
            reject_resource_not_found(f"媒体任务 {job_id} 不存在")
        return job

    def get_job_by_task_id(
        self, session: Session, *, course_id: int, task_id: str,
    ) -> MediaGenerationJob:
        job = session.exec(
            select(MediaGenerationJob).where(
                MediaGenerationJob.task_id == task_id,
                MediaGenerationJob.course_id == course_id,
            )
        ).first()
        if job is None:
            reject_resource_not_found(f"任务 {task_id} 不属于课程 {course_id}")
        return job

    def list_jobs(
        self,
        session: Session,
        *,
        course_id: int,
        job_type: Optional[MediaGenerationJobType] = None,
        status: Optional[MediaGenerationStatus] = None,
        node_id: Optional[int] = None,
    ) -> list[MediaGenerationJob]:
        stmt = select(MediaGenerationJob).where(
            MediaGenerationJob.course_id == course_id,
        )
        if job_type is not None:
            stmt = stmt.where(MediaGenerationJob.job_type == job_type)
        if status is not None:
            stmt = stmt.where(MediaGenerationJob.status == status)
        if node_id is not None:
            stmt = stmt.where(MediaGenerationJob.node_id == node_id)
        stmt = stmt.order_by(MediaGenerationJob.created_at.desc())
        return list(session.exec(stmt).all())

    def mark_running(
        self, session: Session, *, course_id: int, job_id: str, stage: str = "",
    ) -> MediaGenerationJob:
        job = self.get_job(session, course_id=course_id, job_id=job_id)
        job.status = MediaGenerationStatus.RUNNING
        job.updated_at = utcnow_aware()
        session.add(job)
        if job.task_id:
            task_service.mark_running(session, job.task_id, stage=stage)
        session.flush()
        return job

    def mark_succeeded(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        output_object_key: str,
        output_metadata: Optional[dict] = None,
    ) -> MediaGenerationJob:
        job = self.get_job(session, course_id=course_id, job_id=job_id)
        job.status = MediaGenerationStatus.SUCCEEDED
        job.output_object_key = output_object_key
        job.output_metadata = output_metadata or {}
        job.error_code = ""
        job.error_message_safe = ""
        job.finished_at = utcnow_aware()
        job.updated_at = job.finished_at
        session.add(job)
        if job.task_id:
            task_service.mark_succeeded(
                session, job.task_id,
                result_ref=output_object_key,
                result_data=output_metadata or {},
            )
        session.flush()
        return job

    def mark_failed(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        error_code: str,
        error_message_safe: str,
        retryable: bool = True,
    ) -> MediaGenerationJob:
        job = self.get_job(session, course_id=course_id, job_id=job_id)
        job.status = MediaGenerationStatus.FAILED
        job.error_code = error_code
        job.error_message_safe = error_message_safe
        job.finished_at = utcnow_aware()
        job.updated_at = job.finished_at
        session.add(job)
        if job.task_id:
            task_service.mark_failed(
                session, job.task_id,
                error_code=error_code,
                error_message=error_message_safe,
                retryable=retryable,
            )
        session.flush()
        return job

    def record_attempt(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        attempt_number: int,
        provider_key: str,
        provider_version: str,
        status: MediaGenerationStatus,
        duration_ms: Optional[int] = None,
        error_code: str = "",
        error_message_safe: str = "",
        degraded_from_provider: Optional[str] = None,
        attempt_metadata: Optional[dict] = None,
    ) -> MediaGenerationAttempt:
        """记录单次尝试明细，用于审计与质量分析"""
        attempt = MediaGenerationAttempt(
            job_id=job_id,
            course_id=course_id,
            attempt_number=attempt_number,
            provider_key=provider_key,
            provider_version=provider_version,
            duration_ms=duration_ms,
            status=status,
            error_code=error_code,
            error_message_safe=error_message_safe,
            degraded_from_provider=degraded_from_provider,
            attempt_metadata=attempt_metadata or {},
            finished_at=utcnow_aware() if status != MediaGenerationStatus.RUNNING else None,
        )
        session.add(attempt)
        session.flush()
        return attempt


# ---------------------------------------------------------------------------
# 媒体发布服务
# ---------------------------------------------------------------------------


class MediaReleaseService:
    """媒体发布版本服务

    - 每次发布形成不可变版本，修改讲稿/头像必须新建版本
    - 状态机：draft → active → superseded；withdrawn/stale 可中途介入
    - 学生端通过 `get_current_release` 获取当前激活版本
    """

    def create_release(
        self,
        session: Session,
        *,
        course_id: int,
        created_by: int,
        label: str = "",
        notes: str = "",
        audio_object_key: Optional[str] = None,
        subtitle_manifest_object_key: Optional[str] = None,
        ppt_manifest_object_key: Optional[str] = None,
        avatar_binding_id: Optional[str] = None,
        digital_human_manifest_object_key: Optional[str] = None,
        default_playback_mode: PlaybackMode = PlaybackMode.AUTO,
        capability_profile_id: Optional[str] = None,
    ) -> MediaRelease:
        # 计算版本号
        max_version = session.exec(
            select(func.max(MediaRelease.version_number)).where(
                MediaRelease.course_id == course_id,
            )
        ).one() or 0
        version_number = int(max_version) + 1

        release = MediaRelease(
            course_id=course_id,
            version_number=version_number,
            label=label or f"v{version_number}",
            status=MediaReleaseStatus.DRAFT,
            audio_object_key=audio_object_key,
            subtitle_manifest_object_key=subtitle_manifest_object_key,
            ppt_manifest_object_key=ppt_manifest_object_key,
            avatar_binding_id=avatar_binding_id,
            digital_human_manifest_object_key=digital_human_manifest_object_key,
            default_playback_mode=default_playback_mode,
            capability_profile_id=capability_profile_id,
            notes=notes,
            created_by=created_by,
        )
        session.add(release)
        session.flush()
        return release

    def get_release(
        self, session: Session, *, course_id: int, release_id: str,
    ) -> MediaRelease:
        release = session.exec(
            select(MediaRelease).where(
                MediaRelease.release_id == release_id,
                MediaRelease.course_id == course_id,
            )
        ).first()
        if release is None:
            reject_resource_not_found(f"媒体版本 {release_id} 不存在")
        return release

    def list_releases(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[MediaReleaseStatus] = None,
    ) -> list[MediaRelease]:
        stmt = select(MediaRelease).where(MediaRelease.course_id == course_id)
        if status is not None:
            stmt = stmt.where(MediaRelease.status == status)
        stmt = stmt.order_by(MediaRelease.version_number.desc())
        return list(session.exec(stmt).all())

    def get_current_release(
        self, session: Session, *, course_id: int,
    ) -> Optional[MediaRelease]:
        """获取当前激活版本（学生端使用）"""
        return session.exec(
            select(MediaRelease).where(
                MediaRelease.course_id == course_id,
                MediaRelease.status == MediaReleaseStatus.ACTIVE,
            ).order_by(MediaRelease.version_number.desc())
        ).first()

    def activate_release(
        self, session: Session, *, course_id: int, release_id: str,
    ) -> MediaRelease:
        """激活指定版本：旧 active 标记 superseded"""
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        if release.status == MediaReleaseStatus.ACTIVE:
            return release  # 已激活，幂等返回
        if release.status not in (MediaReleaseStatus.DRAFT, MediaReleaseStatus.WITHDRAWN):
            reject_state_conflict(
                f"版本状态 {release.status.value} 不允许激活",
                details={"current_status": release.status.value},
            )

        self._validate_avatar_cues_binding(
            session, course_id=course_id, release=release,
        )

        # 旧 active 标记 superseded
        old_actives = session.exec(
            select(MediaRelease).where(
                MediaRelease.course_id == course_id,
                MediaRelease.status == MediaReleaseStatus.ACTIVE,
            )
        ).all()
        now = utcnow_aware()
        for old in old_actives:
            old.status = MediaReleaseStatus.SUPERSEDED
            old.superseded_at = now
            session.add(old)

        release.status = MediaReleaseStatus.ACTIVE
        release.activated_at = now
        session.add(release)
        session.flush()
        return release

    def ensure_ppt_manifest(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
    ) -> Optional[dict[str, Any]]:
        """Build the immutable PPT manifest once before a release is activated."""
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        if release.ppt_manifest_object_key:
            storage = get_object_storage()
            if not storage.exists(release.ppt_manifest_object_key):
                raise RuntimeError("bound PPT manifest object is unavailable")
            return None
        from app.services.ppt_manifest_service import build_ppt_manifest
        return build_ppt_manifest(session, course_id=course_id, release=release)

    def withdraw_release(
        self, session: Session, *, course_id: int, release_id: str,
    ) -> MediaRelease:
        """撤回版本：学生端不再可见，但保留历史"""
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        if release.status not in (MediaReleaseStatus.ACTIVE, MediaReleaseStatus.DRAFT):
            reject_state_conflict(
                f"版本状态 {release.status.value} 不允许撤回",
                details={"current_status": release.status.value},
            )
        release.status = MediaReleaseStatus.WITHDRAWN
        release.withdrawn_at = utcnow_aware()
        session.add(release)
        session.flush()
        return release

    def rollback_to_release(
        self, session: Session, *, course_id: int, release_id: str,
    ) -> MediaRelease:
        """回滚到历史版本：将该版本重新激活，其他 active 标记 superseded"""
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        # 允许从 superseded/withdrawn/stale 回滚
        if release.status == MediaReleaseStatus.ACTIVE:
            return release
        if release.status not in (
            MediaReleaseStatus.SUPERSEDED,
            MediaReleaseStatus.WITHDRAWN,
            MediaReleaseStatus.STALE,
        ):
            reject_state_conflict(
                f"版本状态 {release.status.value} 不允许回滚",
                details={"current_status": release.status.value},
            )

        # 旧 active 标记 superseded
        old_actives = session.exec(
            select(MediaRelease).where(
                MediaRelease.course_id == course_id,
                MediaRelease.status == MediaReleaseStatus.ACTIVE,
            )
        ).all()
        now = utcnow_aware()
        for old in old_actives:
            old.status = MediaReleaseStatus.SUPERSEDED
            old.superseded_at = now
            session.add(old)

        release.status = MediaReleaseStatus.ACTIVE
        release.activated_at = now
        release.withdrawn_at = None
        session.add(release)
        session.flush()
        return release

    def freeze_cues_from_timeline(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        cues: list[MediaTimelineCue],
    ) -> list[MediaReleaseCue]:
        """将编辑中的 MediaTimelineCue 冻结为发布版本快照 MediaReleaseCue.

        The legacy editor may still create ``MediaTimelineCue`` rows, but it
        must not be able to mutate an active learner release.  P2's Provider
        cue builder uses the same immutable replacement primitive below.
        """
        # Legacy editor cues can opt into the modern mapping snapshot through
        # cue metadata.  Expand all mapped pages (including multiple decks)
        # before freezing so old callers do not collapse same-numbered pages.
        enriched_rows = []
        from app.services.avatar_cue_service import _freeze_ppt_mapping_snapshot, _non_negative_int
        cues_by_node: dict[int, list[MediaTimelineCue]] = {}
        for item in cues:
            cues_by_node.setdefault(item.node_id, []).append(item)
        for cue in cues:
            metadata = dict(cue.cue_metadata or {})
            slides = []
            outline_node_id = metadata.get("outline_node_id")
            if outline_node_id:
                _, slides = _freeze_ppt_mapping_snapshot(
                    session, course_id=course_id, outline_node_id=str(outline_node_id),
                )
            if slides:
                node_cues = cues_by_node.get(cue.node_id, [cue])
                position = min(
                    (int(cue.cue_index) * len(slides)) // max(1, len(node_cues)),
                    len(slides) - 1,
                )
                selected = slides[position]
                metadata["material_version_id"] = selected.get("material_version_id")
                ppt_page = _non_negative_int(selected.get("page")) or None
            else:
                ppt_page = cue.ppt_page
            enriched_rows.append({
                "node_id": cue.node_id,
                "cue_index": cue.cue_index,
                "start_time": cue.start_time,
                "end_time": cue.end_time,
                "cue_type": cue.cue_type.value if hasattr(cue.cue_type, "value") else str(cue.cue_type),
                "ppt_page": ppt_page,
                "subtitle_text": cue.subtitle_text,
                "script_reference": cue.script_reference,
                "audio_object_key": cue.audio_object_key,
                "video_object_key": cue.video_object_key,
                "cue_metadata": metadata,
            })
        return self.freeze_cue_snapshot(
            session,
            course_id=course_id,
            release_id=release_id,
            cue_rows=enriched_rows,
        )

    def freeze_cue_snapshot(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        cue_rows: list[dict[str, Any]],
    ) -> list[MediaReleaseCue]:
        """Replace a *draft* release's full cue snapshot atomically.

        Input rows are already provider-neutral.  This is deliberately the
        only mutation path for ``MediaReleaseCue`` so the stored content hash
        covers all timing, audio references and mapping provenance.
        """
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        self._require_release_mutable(release, action="冻结 Cue")

        normalized = []
        for raw in cue_rows:
            node_id = raw.get("node_id")
            start_time = float(raw.get("start_time", 0))
            end_time = float(raw.get("end_time", 0))
            if not isinstance(node_id, int) or node_id < 1 or start_time < 0 or end_time <= start_time:
                reject_validation_failed("Cue 快照包含无效节点或时间范围")
            metadata = raw.get("cue_metadata") or {}
            if not isinstance(metadata, dict):
                reject_validation_failed("Cue 元数据必须为对象")
            normalized.append({
                "node_id": node_id,
                "cue_index": int(raw.get("cue_index", 0)),
                "start_time": start_time,
                "end_time": end_time,
                "cue_type": str(raw.get("cue_type") or "narration"),
                "ppt_page": raw.get("ppt_page"),
                "subtitle_text": str(raw.get("subtitle_text") or ""),
                "script_reference": raw.get("script_reference"),
                "audio_object_key": raw.get("audio_object_key"),
                "video_object_key": raw.get("video_object_key"),
                "cue_metadata": metadata,
            })
        normalized.sort(key=lambda item: (
            item["node_id"], item["cue_index"], item["start_time"], item["end_time"],
        ))
        try:
            hash_payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            reject_validation_failed("Cue 元数据必须可序列化")
            raise AssertionError("unreachable") from exc
        release.timeline_content_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()
        session.add(release)

        existing = session.exec(
            select(MediaReleaseCue).where(
                MediaReleaseCue.release_id == release_id,
                MediaReleaseCue.course_id == course_id,
            )
        ).all()
        for old in existing:
            session.delete(old)

        frozen: list[MediaReleaseCue] = []
        for row in normalized:
            cue = MediaReleaseCue(
                release_id=release_id,
                course_id=course_id,
                **row,
            )
            session.add(cue)
            frozen.append(cue)
        session.flush()
        return frozen

    @staticmethod
    def _require_release_mutable(release: MediaRelease, *, action: str) -> None:
        # A withdrawn release may be reactivated unchanged, but it may already
        # be referenced by an immutable CourseRelease.  Re-freezing it would
        # silently change historical learner media, so only never-activated
        # drafts are writable.
        if release.status != MediaReleaseStatus.DRAFT:
            reject_state_conflict(
                f"版本状态 {release.status.value} 不允许{action}",
                details={"current_status": release.status.value},
            )

    def _validate_avatar_cues_binding(
        self,
        session: Session,
        *,
        course_id: int,
        release: MediaRelease,
    ) -> None:
        """Fail closed only when P2 cue assets are declared on a release.

        Legacy audio-only releases remain compatible.  A release that claims a
        cue asset, however, must carry the same immutable audio binding and a
        frozen subtitle/Cue snapshot before learners can observe it.
        """
        playlist_mode = bool((release.release_metadata or {}).get("audio_playlist_mode"))
        if playlist_mode:
            if not release.audio_playlist_object_key or not release.audio_playlist_sha256:
                reject_state_conflict(
                    "课程级播放清单尚未冻结，发布未激活",
                    details={"error_code": "AUDIO_PLAYLIST_REQUIRED"},
                )
            from app.models.media_release_model import MediaReleaseItem

            items = list(session.exec(select(MediaReleaseItem).where(
                MediaReleaseItem.course_id == course_id,
                MediaReleaseItem.release_id == release.release_id,
            )).all())
            if not items or any(item.status != "ready" for item in items):
                reject_state_conflict(
                    "课程级播放清单存在未完成知识点，发布未激活",
                    details={"error_code": "AUDIO_PLAYLIST_ITEMS_REQUIRED"},
                )
            storage = get_object_storage()
            if not storage.exists(release.audio_playlist_object_key):
                reject_state_conflict(
                    "课程级播放清单对象不可用，发布未激活",
                    details={"error_code": "AUDIO_PLAYLIST_UNAVAILABLE"},
                )
            return

        if not release.avatar_cues_object_key:
            return
        from app.services.avatar_cue_service import AvatarCueBuildError, load_avatar_cue_manifest

        storage = get_object_storage()
        try:
            manifest = load_avatar_cue_manifest(storage, release.avatar_cues_object_key)
        except AvatarCueBuildError as exc:
            reject_state_conflict(
                "数字人时间轴资产不可用，发布未激活",
                details={"error_code": exc.error_code},
            )
        audio = manifest["audio"]
        expected_sha = str((release.release_metadata or {}).get("audio_sha256") or "")
        if audio.get("object_key") != release.audio_object_key or not expected_sha or audio.get("sha256") != expected_sha:
            reject_state_conflict(
                "数字人时间轴与发布音频不匹配，发布未激活",
                details={"error_code": "AVATAR_CUES_AUDIO_MISMATCH"},
            )
        if not self.list_release_cues(session, course_id=course_id, release_id=release.release_id):
            reject_state_conflict(
                "数字人时间轴缺少冻结字幕 Cue，发布未激活",
                details={"error_code": "RELEASE_CUES_REQUIRED"},
            )

    def list_release_cues(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        node_id: Optional[int] = None,
    ) -> list[MediaReleaseCue]:
        stmt = select(MediaReleaseCue).where(
            MediaReleaseCue.release_id == release_id,
            MediaReleaseCue.course_id == course_id,
        )
        if node_id is not None:
            stmt = stmt.where(MediaReleaseCue.node_id == node_id)
        stmt = stmt.order_by(MediaReleaseCue.node_id, MediaReleaseCue.cue_index)
        return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 媒体播放服务（学生端统一播放清单）
# ---------------------------------------------------------------------------


class MediaPlaybackService:
    """学生端统一播放清单服务

    返回音频 + 字幕 + PPT 时间轴 + 数字人 manifest + 三档模式配置。
    数字人 manifest 仅在已绑定且资产包可用时返回；否则走兼容模式。
    """

    def get_current_playback(
        self, session: Session, *, course_id: int,
    ) -> dict[str, Any]:
        # P4: when a course release exists, its media snapshot is authoritative.
        # A newer MediaRelease may be prepared for the next course version but
        # must not silently replace media in the current learner experience.
        from app.models.course_build_model import CourseRelease, ReleaseStatus
        course_release = session.exec(select(CourseRelease).where(
            CourseRelease.course_id == course_id,
            CourseRelease.is_active == True,  # noqa: E712
            CourseRelease.status == ReleaseStatus.PUBLISHED,
        )).first()
        if course_release is not None:
            media_release_id = (course_release.media_snapshot or {}).get("media_release_id")
            if not media_release_id:
                return {
                    "available": False,
                    "reason": "media_not_frozen",
                    "message": "当前课程发布版本未包含讲解媒体",
                    "fallback_mode": "compatibility",
                    "course_release_id": course_release.release_id,
                }
            release = session.exec(select(MediaRelease).where(
                MediaRelease.course_id == course_id,
                MediaRelease.release_id == media_release_id,
            )).first()
        else:
            # Compatibility only for legacy courses that predate CourseRelease.
            release = media_release_service.get_current_release(session, course_id=course_id)
        if release is None:
            return {
                "available": False,
                "reason": "no_active_release",
                "message": "本课程尚未发布任何讲解媒体版本",
                "fallback_mode": "compatibility",
            }

        if course_release is not None:
            frozen_playlist_hash = str((course_release.media_snapshot or {}).get("playlist_content_hash") or "")
            if frozen_playlist_hash and frozen_playlist_hash != str(release.audio_playlist_sha256 or ""):
                logger.error(
                    "Course release %s media playlist hash mismatch for course %s",
                    course_release.release_id, course_id,
                )
                return {
                    "available": False,
                    "reason": "media_snapshot_integrity_failed",
                    "message": "课程发布的媒体播放清单完整性校验失败",
                    "fallback_mode": "compatibility",
                    "course_release_id": course_release.release_id,
                }

        # 获取冻结 cue
        cues = media_release_service.list_release_cues(
            session, course_id=course_id, release_id=release.release_id,
        )

        # 签发音频 URL
        storage = get_object_storage()
        audio_url = ""
        if release.audio_object_key:
            audio_url = storage.sign_read_url(
                release.audio_object_key,
                scope={"course_id": course_id, "purpose": "lecture_playback"},
            )

        ppt_manifest = None
        if release.ppt_manifest_object_key:
            try:
                from app.services.ppt_manifest_service import load_manifest, sign_manifest_pages
                raw_manifest = load_manifest(storage, release.ppt_manifest_object_key)
                ppt_manifest = sign_manifest_pages(
                    raw_manifest,
                    storage,
                    course_id=course_id,
                    release_id=release.release_id,
                )
                ppt_manifest["manifest_url"] = storage.sign_read_url(
                    release.ppt_manifest_object_key,
                    scope={"course_id": course_id, "purpose": "ppt_manifest", "release_id": release.release_id},
                )
            except Exception as e:
                logger.warning("签发 PPT manifest 失败，降级为旧课件回退: %s", e)

        # 字幕与 PPT 时间轴
        subtitle_segments = []
        ppt_timeline = []
        playlist = None
        if release.audio_playlist_object_key:
            try:
                raw_playlist = json.loads(storage.get(release.audio_playlist_object_key).decode("utf-8"))
                if raw_playlist.get("schema") == "audio-playlist/v1":
                    playlist = {"schema": "audio-playlist/v1", "release_id": release.release_id,
                                "duration_ms": int(raw_playlist.get("duration_ms") or 0),
                                "content_sha256": release.audio_playlist_sha256, "items": []}
                    for raw_item in raw_playlist.get("items") or []:
                        item = dict(raw_item)
                        item_offset_ms = int(item.get("offset_ms") or 0)
                        item_duration_ms = int(item.get("duration_ms") or 0)
                        if item.get("audio_object_key"):
                            item["audio_url"] = storage.sign_read_url(item["audio_object_key"], scope={"course_id": course_id, "purpose": "lecture_playlist", "release_id": release.release_id})
                        if item.get("subtitle_manifest_object_key"):
                            item["subtitle_manifest_url"] = storage.sign_read_url(item["subtitle_manifest_object_key"], scope={"course_id": course_id, "purpose": "playlist_subtitle", "release_id": release.release_id})
                            try:
                                subtitle = json.loads(storage.get(item["subtitle_manifest_object_key"]).decode("utf-8"))
                                item["subtitle_segments"] = subtitle.get("segments") or []
                            except Exception:
                                item["subtitle_segments"] = []
                        if item.get("avatar_cues_object_key"):
                            item["avatar_cues_url"] = storage.sign_read_url(item["avatar_cues_object_key"], scope={"course_id": course_id, "purpose": "playlist_avatar_cues", "release_id": release.release_id})
                        mapping = (item.get("ppt_mapping_snapshot") or {}).get("mappings") or []
                        # ``audio-playlist/v1`` is a global course clock at
                        # the boundary.  Inside one node, map its frozen pages
                        # across the node duration so slides do not all
                        # collapse to the same start instant.
                        playback_pages = [
                            {"page": page, "material_version_id": row.get("material_version_id")}
                            for row in mapping
                            for page in (row.get("page_refs") or [row.get("page_start") or 1])
                        ]
                        item["ppt_timeline"] = [
                            {
                                "node_id": item.get("node_id"),
                                "ppt_page": page["page"],
                                "material_version_id": page["material_version_id"],
                                "start_ms": item_offset_ms + int(item_duration_ms * index / len(playback_pages)),
                                "end_ms": item_offset_ms + int(item_duration_ms * (index + 1) / len(playback_pages)),
                            }
                            for index, page in enumerate(playback_pages)
                        ]
                        for segment in item.get("subtitle_segments") or []:
                            segment["ppt_page"] = item["ppt_timeline"][0]["ppt_page"] if item["ppt_timeline"] else None
                            segment["material_version_id"] = item["ppt_timeline"][0]["material_version_id"] if item["ppt_timeline"] else None
                        playlist["items"].append(item)
            except Exception as exc:
                logger.warning("签发 audio-playlist/v1 失败，回退旧媒体字段: %s", exc)
        for cue in cues:
            subtitle_segments.append({
                "node_id": cue.node_id,
                "cue_index": cue.cue_index,
                "start_ms": int(cue.start_time * 1000),
                "end_ms": int(cue.end_time * 1000),
                "text": cue.subtitle_text,
                "script_reference": cue.script_reference,
            })
            if cue.ppt_page is not None:
                ppt_timeline.append({
                    "node_id": cue.node_id,
                    "outline_node_id": (cue.cue_metadata or {}).get("outline_node_id"),
                    "ppt_page": cue.ppt_page,
                    "material_version_id": (cue.cue_metadata or {}).get("material_version_id"),
                    "start_ms": int(cue.start_time * 1000),
                    "end_ms": int(cue.end_time * 1000),
                })
        # The persisted Cue snapshot is authoritative.  Sort by the audio
        # clock here so callers that use independent node audio still receive
        # a deterministic cross-deck sequence.
        ppt_timeline.sort(key=lambda item: (item["start_ms"], item["node_id"]))

        # 数字人 manifest（仅在绑定时）
        digital_human_manifest = None
        if release.digital_human_manifest_object_key:
            try:
                manifest_url = storage.sign_read_url(
                    release.digital_human_manifest_object_key,
                    scope={"course_id": course_id, "purpose": "dh_playback"},
                )
                digital_human_manifest = {
                    "manifest_url": manifest_url,
                    "render_mode": "browser_realtime",
                    "recommended_quality": release.default_playback_mode.value,
                    "fallback_supported": True,
                }
            except Exception as e:
                logger.warning("签发数字人 manifest 失败，降级为兼容模式: %s", e)
                digital_human_manifest = None

        # P2 timeline is exposed independently from the avatar package.  P3
        # may consume it when a renderer is available; all existing learners
        # safely ignore it and keep audio/PPT/subtitles as the primary path.
        avatar_cues = None
        if release.avatar_cues_object_key:
            try:
                from app.services.avatar_cue_service import load_avatar_cue_manifest

                cue_manifest = load_avatar_cue_manifest(storage, release.avatar_cues_object_key)
                audio_binding = cue_manifest["audio"]
                expected_sha = str((release.release_metadata or {}).get("audio_sha256") or "")
                if audio_binding.get("object_key") != release.audio_object_key or audio_binding.get("sha256") != expected_sha:
                    raise ValueError("avatar cue audio binding mismatch")
                avatar_cues = {
                    "schema": cue_manifest["schema"],
                    "manifest_url": storage.sign_read_url(
                        release.avatar_cues_object_key,
                        scope={"course_id": course_id, "purpose": "avatar_cues", "release_id": release.release_id},
                    ),
                    "timing_source": (cue_manifest.get("timing") or {}).get("source", ""),
                    "precision": (cue_manifest.get("timing") or {}).get("precision", ""),
                    "content_sha256": cue_manifest.get("content_sha256", ""),
                }
            except Exception as e:
                logger.warning("签发数字人 Cue manifest 失败，播放继续走兼容模式: %s", e)

        return {
            "available": True,
            "course_release_id": course_release.release_id if course_release else None,
            "release_id": release.release_id,
            "version_number": release.version_number,
            "label": release.label,
            "audio_url": audio_url,
            "duration_ms": self._estimate_total_duration_ms(cues),
            "subtitle_segments": subtitle_segments,
            "ppt_timeline": ppt_timeline,
            "ppt": ppt_manifest,
            "digital_human_manifest": digital_human_manifest,
            "avatar_cues": avatar_cues,
            "default_playback_mode": release.default_playback_mode.value,
            "fallback_mode": "compatibility" if digital_human_manifest is None else release.default_playback_mode.value,
            "timeline_content_hash": release.timeline_content_hash,
            "playlist": playlist,
        }

    def _estimate_total_duration_ms(self, cues: list[MediaReleaseCue]) -> int:
        if not cues:
            return 0
        max_end = max(c.end_time for c in cues)
        return int(max_end * 1000)


# ---------------------------------------------------------------------------
# TTS 合成执行器（Fake/Mock 可同步；真实 Provider 仅由异步 worker 调用）
# ---------------------------------------------------------------------------


class TtsExecutionService:
    """TTS 合成执行器

    - Fake/Mock Provider 保留同步执行，服务于离线演示与自动化测试
    - 真实付费 Provider 由 media.tts Worker 在独立线程/会话中调用
    - 失败时通过 mark_failed 保留原始 error_code，禁止伪装成功
    - 限额：基于内存滑动窗口，按 course_id 限制每分钟调用次数
    """

    # 内存滑动窗口限额：{course_id: [(timestamp, ...), ...]}
    _rate_limit_windows: dict[int, list[float]] = {}

    def execute_tts_job(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        script_text: str,
        voice_id: str = "default",
        resource_version: str = "v1",
        provider_key: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> MediaGenerationJob:
        """执行 TTS 合成任务，支持自动重试

        - max_retries: 自动重试次数（默认从配置读取 TTS_MAX_RETRY_ATTEMPTS）
        - 超过重试次数后标记 failed，保留最后一次错误
        - 限额超限时立即失败，错误码 TTS_RATE_LIMITED
        """
        job_service = media_generation_job_service
        job = job_service.mark_running(
            session, course_id=course_id, job_id=job_id, stage="tts_synthesizing",
        )

        from app.core.config import settings
        max_script_bytes = getattr(settings, "TTS_MAX_SCRIPT_BYTES", 8000)
        if len(script_text.encode("utf-8")) > max_script_bytes:
            return self._fail_job(
                session, course_id=course_id, job_id=job_id,
                error_code="TTS_SCRIPT_TOO_LONG",
                error_message_safe=(
                    f"讲稿超过最大字节限制 {max_script_bytes}，当前 {len(script_text.encode('utf-8'))}"
                ),
            )

        try:
            provider = get_tts_provider(provider_key or job.provider_key or None, strict=True)
        except TtsProviderConfigurationError:
            return self._fail_job(
                session, course_id=course_id, job_id=job_id,
                error_code="TTS_PROVIDER_UNSUPPORTED",
                error_message_safe="所选 TTS Provider 未注册，任务未调用任何外部服务",
            )

        request = TtsSynthesisRequest(
            script_text=script_text,
            voice_id=voice_id,
            course_id=course_id,
            resource_version=resource_version,
            idempotency_key=job.idempotency_key,
        )
        cache_key = provider.cache_key(request)
        job.provider_key = provider.provider_key
        job.provider_version = provider.provider_version
        job.input_hash = cache_key
        session.add(job)
        session.flush()

        cached = self._find_cached_success(
            session,
            course_id=course_id,
            job_id=job_id,
            cache_key=cache_key,
            provider_key=provider.provider_key,
            provider_version=provider.provider_version,
        )
        if cached is not None:
            metadata = dict(cached.output_metadata or {})
            metadata.update({
                "cache_hit": True,
                "cache_source_job_id": cached.job_id,
                "provider_key": provider.provider_key,
                "provider_version": provider.provider_version,
                "attempts_used": 0,
            })
            # Historic cache rows can predate MediaAsset bookkeeping.  Reuse
            # their immutable object without a second synthesis, then restore
            # the course-scoped ledger entry required by direct <audio> reads.
            try:
                _register_tts_audio_asset(
                    session,
                    course_id=course_id,
                    object_key=str(cached.output_object_key or ""),
                    duration_ms=int(metadata.get("duration_ms") or 0),
                    audio_sha256=str(metadata.get("audio_sha256") or ""),
                    provider_key=provider.provider_key,
                    provider_version=provider.provider_version,
                )
            except Exception as exc:
                return self._fail_job(
                    session,
                    course_id=course_id,
                    job_id=job_id,
                    error_code=getattr(exc, "error_code", "TTS_ASSET_REGISTRATION_FAILED"),
                    error_message_safe=str(getattr(exc, "safe_message", str(exc)))[:500],
                    provider_key=provider.provider_key,
                    provider_version=provider.provider_version,
                )
            job_service.record_attempt(
                session, course_id=course_id, job_id=job_id,
                attempt_number=self._next_attempt_number(session, job_id=job_id),
                provider_key=provider.provider_key,
                provider_version=provider.provider_version,
                status=MediaGenerationStatus.SUCCEEDED,
                duration_ms=0,
                attempt_metadata={"cache_hit": True, "cache_source_job_id": cached.job_id},
            )
            return job_service.mark_succeeded(
                session, course_id=course_id, job_id=job_id,
                output_object_key=cached.output_object_key or "",
                output_metadata=metadata,
            )

        rate_limit_error = self._check_rate_limit(course_id)
        if rate_limit_error:
            return self._fail_job(
                session, course_id=course_id, job_id=job_id,
                error_code=rate_limit_error[0], error_message_safe=rate_limit_error[1],
                provider_key=provider.provider_key, provider_version=provider.provider_version,
            )

        max_attempts = max_retries if max_retries is not None else getattr(
            settings, "TTS_MAX_RETRY_ATTEMPTS", 3,
        )
        last_error_code = ""
        last_error_message = ""
        for attempt_idx in range(max_attempts):
            attempt_number = self._next_attempt_number(session, job_id=job_id)
            started = time.monotonic()
            try:
                result = provider.synthesize(request)
                _register_tts_audio_asset(
                    session,
                    course_id=course_id,
                    object_key=result.audio_object_key,
                    duration_ms=result.duration_ms,
                    audio_sha256=result.audio_sha256,
                    provider_key=result.provider_key,
                    provider_version=result.provider_version,
                )
            except Exception as exc:
                last_error_code = getattr(exc, "error_code", "TTS_PROVIDER_FAILED")
                last_error_message = str(getattr(exc, "safe_message", str(exc)))[:500]
                job_service.record_attempt(
                    session, course_id=course_id, job_id=job_id,
                    attempt_number=attempt_number,
                    provider_key=provider.provider_key,
                    provider_version=provider.provider_version,
                    status=MediaGenerationStatus.FAILED,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_code=last_error_code,
                    error_message_safe=last_error_message,
                )
                if attempt_idx < max_attempts - 1 and getattr(exc, "retryable", True):
                    continue
                return job_service.mark_failed(
                    session, course_id=course_id, job_id=job_id,
                    error_code=last_error_code,
                    error_message_safe=f"{last_error_message}（已重试 {attempt_idx + 1} 次）",
                    retryable=getattr(exc, "retryable", True),
                )

            metadata = self._result_metadata(result, attempts_used=attempt_idx + 1)
            job_service.record_attempt(
                session, course_id=course_id, job_id=job_id,
                attempt_number=attempt_number,
                provider_key=result.provider_key,
                provider_version=result.provider_version,
                status=MediaGenerationStatus.SUCCEEDED,
                duration_ms=int((time.monotonic() - started) * 1000),
                attempt_metadata={**metadata, "attempt_index": attempt_idx, "cache_hit": False},
            )
            return job_service.mark_succeeded(
                session, course_id=course_id, job_id=job_id,
                output_object_key=result.audio_object_key,
                output_metadata=metadata,
            )

        return job_service.mark_failed(
            session, course_id=course_id, job_id=job_id,
            error_code=last_error_code or "TTS_UNKNOWN_FAILURE",
            error_message_safe=last_error_message or "未知失败",
        )

    def prepare_tts_job_for_dispatch(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        script_text: str,
        voice_id: str = "default",
        resource_version: str = "v1",
        provider_key: Optional[str] = None,
        max_retries: Optional[int] = None,
        retry: bool = False,
    ) -> tuple[MediaGenerationJob, dict[str, Any]]:
        """Persist a worker payload before a paid TTS task is submitted.

        The payload is stored on the job itself; credentials are resolved only
        by the Provider inside the worker.  The returned dict is safe to hand
        to ``LocalTaskWorker.submit`` and contains course script text only.
        """
        job = media_generation_job_service.get_job(session, course_id=course_id, job_id=job_id)
        if retry:
            if job.status != MediaGenerationStatus.FAILED:
                reject_state_conflict(f"仅 failed 任务可重跑，当前状态 {job.status.value}")
            job.status = MediaGenerationStatus.PENDING
            job.error_code = ""
            job.error_message_safe = ""
            job.finished_at = None
        elif job.status != MediaGenerationStatus.PENDING:
            reject_state_conflict(f"仅 pending 任务可派发，当前状态 {job.status.value}")

        provider = get_tts_provider(provider_key or job.provider_key or None, strict=True)
        request = TtsSynthesisRequest(
            script_text=script_text,
            voice_id=voice_id,
            course_id=course_id,
            resource_version=resource_version,
            idempotency_key=job.idempotency_key,
        )
        job.provider_key = provider.provider_key
        job.provider_version = provider.provider_version
        job.input_hash = provider.cache_key(request)
        job.input_payload = {
            **(job.input_payload or {}),
            "script_text": script_text,
            "voice_id": voice_id,
            "resource_version": resource_version,
            "provider_key": provider.provider_key,
            "max_retries": max_retries,
        }
        job.updated_at = utcnow_aware()
        session.add(job)
        session.flush()
        return job, {
            "course_id": course_id,
            "job_id": job.job_id,
            "script_text": script_text,
            "voice_id": voice_id,
            "resource_version": resource_version,
            "provider_key": provider.provider_key,
            "max_retries": max_retries,
        }

    def _find_cached_success(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        cache_key: str,
        provider_key: str,
        provider_version: str,
    ) -> Optional[MediaGenerationJob]:
        candidates = session.exec(
            select(MediaGenerationJob).where(
                MediaGenerationJob.course_id == course_id,
                MediaGenerationJob.job_type == MediaGenerationJobType.TTS,
                MediaGenerationJob.status == MediaGenerationStatus.SUCCEEDED,
                MediaGenerationJob.input_hash == cache_key,
                MediaGenerationJob.provider_key == provider_key,
                MediaGenerationJob.provider_version == provider_version,
                MediaGenerationJob.job_id != job_id,
            ).order_by(MediaGenerationJob.finished_at.desc())
        ).all()
        storage = get_object_storage()
        for candidate in candidates:
            if candidate.output_object_key and storage.exists(candidate.output_object_key):
                return candidate
        return None

    def _result_metadata(self, result: Any, *, attempts_used: int) -> dict[str, Any]:
        return {
            "audio_object_key": result.audio_object_key,
            "duration_ms": result.duration_ms,
            "audio_sha256": result.audio_sha256,
            "subtitle_segments": [
                {
                    "text": segment.text,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "sentence_index": segment.sentence_index,
                }
                for segment in result.subtitle_segments
            ],
            "timing_metadata": result.timing_metadata,
            "warnings": result.warnings,
            "provider_key": result.provider_key,
            "provider_version": result.provider_version,
            "attempts_used": attempts_used,
            "cache_hit": False,
        }

    def _fail_job(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        error_code: str,
        error_message_safe: str,
        provider_key: str = "",
        provider_version: str = "",
    ) -> MediaGenerationJob:
        job_service = media_generation_job_service
        job_service.record_attempt(
            session, course_id=course_id, job_id=job_id,
            attempt_number=self._next_attempt_number(session, job_id=job_id),
            provider_key=provider_key, provider_version=provider_version,
            status=MediaGenerationStatus.FAILED,
            error_code=error_code, error_message_safe=error_message_safe,
        )
        return job_service.mark_failed(
            session, course_id=course_id, job_id=job_id,
            error_code=error_code, error_message_safe=error_message_safe,
        )

    def retry_job(
        self,
        session: Session,
        *,
        course_id: int,
        job_id: str,
        script_text: str,
        voice_id: str = "default",
        resource_version: str = "v1",
        provider_key: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> MediaGenerationJob:
        """人工重跑：将 failed 任务重置为 pending 后重新执行

        - 仅允许 failed 状态的任务重跑
        - 重置 status 为 pending，清空 error 字段
        - 然后调用 execute_tts_job 重新执行
        """
        job_service = media_generation_job_service
        job = job_service.get_job(session, course_id=course_id, job_id=job_id)
        if job.status != MediaGenerationStatus.FAILED:
            reject_state_conflict(
                f"仅 failed 任务可重跑，当前状态 {job.status.value}"
            )
        # 重置状态
        job.status = MediaGenerationStatus.PENDING
        job.error_code = ""
        job.error_message_safe = ""
        job.updated_at = utcnow_aware()
        session.add(job)
        session.flush()
        return self.execute_tts_job(
            session, course_id=course_id, job_id=job_id,
            script_text=script_text, voice_id=voice_id,
            resource_version=resource_version,
            provider_key=provider_key, max_retries=max_retries,
        )

    def _check_rate_limit(self, course_id: int) -> Optional[tuple[str, str]]:
        """检查每分钟限额，超限返回 (error_code, error_message)"""
        from app.core.config import settings
        limit_per_minute = getattr(settings, "TTS_RATE_LIMIT_PER_MINUTE", 30)
        now = time.time()
        window = self._rate_limit_windows.setdefault(course_id, [])
        # 清理 60 秒外的记录
        cutoff = now - 60
        window[:] = [ts for ts in window if ts > cutoff]
        if len(window) >= limit_per_minute:
            return (
                "TTS_RATE_LIMITED",
                f"课程 {course_id} TTS 调用超过每分钟限额 {limit_per_minute}",
            )
        window.append(now)
        return None

    def _next_attempt_number(self, session: Session, *, job_id: str) -> int:
        max_attempt = session.exec(
            select(func.max(MediaGenerationAttempt.attempt_number)).where(
                MediaGenerationAttempt.job_id == job_id,
            )
        ).one() or 0
        return int(max_attempt) + 1

    @classmethod
    def reset_rate_limit_for_tests(cls) -> None:
        """测试辅助：清空限额窗口"""
        cls._rate_limit_windows.clear()


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


media_generation_job_service = MediaGenerationJobService()
media_release_service = MediaReleaseService()
media_playback_service = MediaPlaybackService()
tts_execution_service = TtsExecutionService()
