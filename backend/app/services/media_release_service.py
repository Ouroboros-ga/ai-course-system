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
from app.models.media_timeline_model import MediaTimelineCue
from app.services.digital_human_provider import (
    DigitalHumanPlaybackRequest,
    get_digital_human_provider,
)
from app.services.object_storage import get_object_storage
from app.services.task_service import TaskCreateRequest, task_service
from app.services.tts_provider import (
    TtsSynthesisRequest,
    get_tts_provider,
)


logger = logging.getLogger(__name__)


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
        """将编辑中的 MediaTimelineCue 冻结为发布版本快照 MediaReleaseCue"""
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        # 计算内容哈希
        hash_payload = json.dumps([
            {
                "node_id": c.node_id,
                "cue_index": c.cue_index,
                "start_time": c.start_time,
                "end_time": c.end_time,
                "cue_type": c.cue_type.value if hasattr(c.cue_type, "value") else str(c.cue_type),
                "ppt_page": c.ppt_page,
                "subtitle_text": c.subtitle_text,
                "audio_object_key": c.audio_object_key,
                "video_object_key": c.video_object_key,
            }
            for c in cues
        ], ensure_ascii=False, sort_keys=True)
        release.timeline_content_hash = hashlib.sha256(
            hash_payload.encode("utf-8")
        ).hexdigest()
        session.add(release)

        # 删除该 release 已有的 cue 快照（支持重做）
        existing = session.exec(
            select(MediaReleaseCue).where(MediaReleaseCue.release_id == release_id)
        ).all()
        for old in existing:
            session.delete(old)

        new_cues: list[MediaReleaseCue] = []
        for c in cues:
            rc = MediaReleaseCue(
                release_id=release_id,
                course_id=course_id,
                node_id=c.node_id,
                cue_index=c.cue_index,
                start_time=c.start_time,
                end_time=c.end_time,
                cue_type=c.cue_type.value if hasattr(c.cue_type, "value") else str(c.cue_type),
                ppt_page=c.ppt_page,
                subtitle_text=c.subtitle_text,
                script_reference=c.script_reference,
                audio_object_key=c.audio_object_key,
                video_object_key=c.video_object_key,
                cue_metadata=c.cue_metadata or {},
            )
            session.add(rc)
            new_cues.append(rc)
        session.flush()
        return new_cues

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

        # 字幕与 PPT 时间轴
        subtitle_segments = []
        ppt_timeline = []
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
                    "ppt_page": cue.ppt_page,
                    "start_ms": int(cue.start_time * 1000),
                })

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
            "digital_human_manifest": digital_human_manifest,
            "default_playback_mode": release.default_playback_mode.value,
            "fallback_mode": "compatibility" if digital_human_manifest is None else release.default_playback_mode.value,
            "timeline_content_hash": release.timeline_content_hash,
        }

    def _estimate_total_duration_ms(self, cues: list[MediaReleaseCue]) -> int:
        if not cues:
            return 0
        max_end = max(c.end_time for c in cues)
        return int(max_end * 1000)


# ---------------------------------------------------------------------------
# TTS 合成执行器（同步执行 Fake；M2 接讯飞时改为异步 worker）
# ---------------------------------------------------------------------------


class TtsExecutionService:
    """TTS 合成执行器

    - M1 阶段：同步执行 Fake Provider，验证端到端流程
    - M2 阶段：实现重试、限额、人工重跑；真实讯飞仅人工验收
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

        # 脚本字节限制
        from app.core.config import settings
        max_script_bytes = getattr(settings, "TTS_MAX_SCRIPT_BYTES", 8000)
        if len(script_text.encode("utf-8")) > max_script_bytes:
            error_code = "TTS_SCRIPT_TOO_LONG"
            error_message_safe = (
                f"讲稿超过最大字节限制 {max_script_bytes}，当前 {len(script_text.encode('utf-8'))}"
            )
            job_service.record_attempt(
                session, course_id=course_id, job_id=job_id,
                attempt_number=self._next_attempt_number(session, job_id=job_id),
                provider_key="",
                provider_version="",
                status=MediaGenerationStatus.FAILED,
                error_code=error_code,
                error_message_safe=error_message_safe,
            )
            return job_service.mark_failed(
                session, course_id=course_id, job_id=job_id,
                error_code=error_code,
                error_message_safe=error_message_safe,
            )

        # 限额检查
        rate_limit_error = self._check_rate_limit(course_id)
        if rate_limit_error:
            job_service.record_attempt(
                session, course_id=course_id, job_id=job_id,
                attempt_number=self._next_attempt_number(session, job_id=job_id),
                provider_key="",
                provider_version="",
                status=MediaGenerationStatus.FAILED,
                error_code=rate_limit_error[0],
                error_message_safe=rate_limit_error[1],
            )
            return job_service.mark_failed(
                session, course_id=course_id, job_id=job_id,
                error_code=rate_limit_error[0],
                error_message_safe=rate_limit_error[1],
            )

        provider = get_tts_provider(provider_key or job.provider_key or None)
        max_attempts = max_retries if max_retries is not None else getattr(
            settings, "TTS_MAX_RETRY_ATTEMPTS", 3,
        )

        last_error_code = ""
        last_error_message = ""

        for attempt_idx in range(max_attempts):
            attempt_number = self._next_attempt_number(session, job_id=job_id)

            try:
                request = TtsSynthesisRequest(
                    script_text=script_text,
                    voice_id=voice_id,
                    course_id=course_id,
                    resource_version=resource_version,
                    idempotency_key=job.idempotency_key,
                )
                result = provider.synthesize(request)
            except Exception as e:
                # 保留原始失败原因
                last_error_code = "TTS_PROVIDER_FAILED"
                last_error_message = str(e)[:500]
                job_service.record_attempt(
                    session, course_id=course_id, job_id=job_id,
                    attempt_number=attempt_number,
                    provider_key=provider.provider_key,
                    provider_version=provider.provider_version,
                    status=MediaGenerationStatus.FAILED,
                    error_code=last_error_code,
                    error_message_safe=last_error_message,
                )
                # 还有重试机会则继续
                if attempt_idx < max_attempts - 1:
                    continue
                # 重试耗尽
                return job_service.mark_failed(
                    session, course_id=course_id, job_id=job_id,
                    error_code=last_error_code,
                    error_message_safe=(
                        f"{last_error_message}（已重试 {max_attempts} 次）"
                    ),
                )

            # 记录成功 attempt
            job_service.record_attempt(
                session, course_id=course_id, job_id=job_id,
                attempt_number=attempt_number,
                provider_key=result.provider_key,
                provider_version=result.provider_version,
                status=MediaGenerationStatus.SUCCEEDED,
                attempt_metadata={
                    "audio_object_key": result.audio_object_key,
                    "duration_ms": result.duration_ms,
                    "audio_sha256": result.audio_sha256,
                    "subtitle_segments": [
                        {
                            "text": s.text, "start_ms": s.start_ms, "end_ms": s.end_ms,
                            "sentence_index": s.sentence_index,
                        } for s in result.subtitle_segments
                    ],
                    "warnings": result.warnings,
                    "attempt_index": attempt_idx,
                },
            )

            return job_service.mark_succeeded(
                session, course_id=course_id, job_id=job_id,
                output_object_key=result.audio_object_key,
                output_metadata={
                    "audio_object_key": result.audio_object_key,
                    "duration_ms": result.duration_ms,
                    "audio_sha256": result.audio_sha256,
                    "subtitle_segments": [
                        {
                            "text": s.text, "start_ms": s.start_ms, "end_ms": s.end_ms,
                            "sentence_index": s.sentence_index,
                        } for s in result.subtitle_segments
                    ],
                    "warnings": result.warnings,
                    "provider_key": result.provider_key,
                    "provider_version": result.provider_version,
                    "attempts_used": attempt_idx + 1,
                },
            )

        # 理论上不会走到这里
        return job_service.mark_failed(
            session, course_id=course_id, job_id=job_id,
            error_code=last_error_code or "TTS_UNKNOWN_FAILURE",
            error_message_safe=last_error_message or "未知失败",
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
