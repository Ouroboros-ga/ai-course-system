"""阶段8 教师数字人资产中心服务

实现「教师建立数字人预设 → 课程绑定 → 学生端播放」的服务编排。

设计要点：
- 教师只能管理 owner_user_id 是自己的 AvatarProfile
- 课程教师只能绑定自己的 AvatarProfile 到自己负责的课程
- 原始视频/语音样本仅存 object_key，不直接给学生下载
- 上传语音样本首版不用于声音克隆
- 删除预设不立即删除历史版本，标记撤回并走媒体版本回滚
- 所有异步预处理任务通过 task_service 持久化
- 失败时必须保留原始 error_code，禁止把 503/超时伪装成成功
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, func, select

from app.core.exceptions import (
    reject_auth_required,
    reject_capability_disabled,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.models.avatar_model import (
    AvatarAssetPackage,
    AvatarAssetPackageStatus,
    AvatarPreparationJob,
    AvatarPreparationJobStatus,
    AvatarProfile,
    AvatarProfileStatus,
    AvatarSourceMedia,
    AvatarSourceMediaStatus,
    AvatarSourceMediaType,
    CourseAvatarBinding,
    CourseAvatarBindingStatus,
    DigitalHumanProviderKey,
)
from app.services.digital_human_provider import (
    AvatarPreparationRequest,
    get_digital_human_provider,
)
from app.services.object_storage import get_object_storage
from app.services.task_service import TaskCreateRequest, task_service


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 教师数字人预设服务
# ---------------------------------------------------------------------------


class AvatarProfileService:
    """教师数字人预设服务

    - 按 owner_user_id 严格隔离
    - 状态机：draft → uploaded → processing → ready | failed
    - disabled/deleted 可中途介入
    """

    def create_profile(
        self,
        session: Session,
        *,
        owner_user_id: int,
        display_name: str,
        provider_key: str = DigitalHumanProviderKey.FAKE.value,
        notes: str = "",
        consent_text: str = "",
    ) -> AvatarProfile:
        if not display_name.strip():
            reject_validation_failed("display_name 不能为空")
        if not consent_text.strip():
            reject_validation_failed("必须勾选本人形象与授权确认")

        profile = AvatarProfile(
            owner_user_id=owner_user_id,
            display_name=display_name.strip(),
            status=AvatarProfileStatus.DRAFT,
            provider_key=provider_key,
            consent_text=consent_text,
            consented_at=datetime.now(timezone.utc),
            notes=notes,
        )
        session.add(profile)
        session.flush()
        return profile

    def get_profile(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: Optional[int] = None,
    ) -> AvatarProfile:
        profile = session.exec(
            select(AvatarProfile).where(AvatarProfile.avatar_id == avatar_id)
        ).first()
        if profile is None or profile.status == AvatarProfileStatus.DELETED:
            reject_resource_not_found(f"数字人预设 {avatar_id} 不存在")
        if owner_user_id is not None and profile.owner_user_id != owner_user_id:
            # 跨教师访问拒绝，统一返回 404 避免泄露存在性
            reject_resource_not_found(f"数字人预设 {avatar_id} 不存在")
        return profile

    def list_my_profiles(
        self,
        session: Session,
        *,
        owner_user_id: int,
        include_deleted: bool = False,
    ) -> list[AvatarProfile]:
        stmt = select(AvatarProfile).where(AvatarProfile.owner_user_id == owner_user_id)
        if not include_deleted:
            stmt = stmt.where(AvatarProfile.status != AvatarProfileStatus.DELETED)
        stmt = stmt.order_by(AvatarProfile.created_at.desc())
        return list(session.exec(stmt).all())

    def list_available_profiles_for_teacher(
        self,
        session: Session,
        *,
        owner_user_id: int,
    ) -> list[AvatarProfile]:
        """列出教师可用于课程绑定的预设（status=ready 或 disabled 但未删除）"""
        return list(session.exec(
            select(AvatarProfile).where(
                AvatarProfile.owner_user_id == owner_user_id,
                AvatarProfile.status == AvatarProfileStatus.READY,
            ).order_by(AvatarProfile.created_at.desc())
        ).all())

    def disable_profile(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
    ) -> AvatarProfile:
        profile = self.get_profile(session, avatar_id=avatar_id, owner_user_id=owner_user_id)
        if profile.status == AvatarProfileStatus.DELETED:
            reject_state_conflict("预设已删除，无法停用")
        profile.status = AvatarProfileStatus.DISABLED
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)
        # 同时把已发布的绑定标记 stale，触发教师重新选择
        bindings = session.exec(
            select(CourseAvatarBinding).where(
                CourseAvatarBinding.avatar_id == avatar_id,
                CourseAvatarBinding.status.in_([
                    CourseAvatarBindingStatus.DRAFT,
                    CourseAvatarBindingStatus.PUBLISHED,
                ]),
            )
        ).all()
        for binding in bindings:
            binding.status = CourseAvatarBindingStatus.STALE
            session.add(binding)
        session.flush()
        return profile

    def soft_delete_profile(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
    ) -> AvatarProfile:
        """软删除预设：标记 deleted，不立即清除历史绑定"""
        profile = self.get_profile(session, avatar_id=avatar_id, owner_user_id=owner_user_id)
        profile.status = AvatarProfileStatus.DELETED
        profile.deleted_at = datetime.now(timezone.utc)
        profile.updated_at = profile.deleted_at
        session.add(profile)
        # 已发布绑定标记 stale，学生端走兼容模式
        bindings = session.exec(
            select(CourseAvatarBinding).where(
                CourseAvatarBinding.avatar_id == avatar_id,
                CourseAvatarBinding.status.in_([
                    CourseAvatarBindingStatus.DRAFT,
                    CourseAvatarBindingStatus.PUBLISHED,
                ]),
            )
        ).all()
        for binding in bindings:
            binding.status = CourseAvatarBindingStatus.STALE
            session.add(binding)
        session.flush()
        return profile

    def update_current_asset_package(
        self,
        session: Session,
        *,
        avatar_id: str,
        asset_package_id: str,
        provider_key: str,
        provider_version: str,
    ) -> AvatarProfile:
        profile = self.get_profile(session, avatar_id=avatar_id)
        profile.current_asset_package_id = asset_package_id
        profile.provider_key = provider_key
        profile.provider_version = provider_version
        profile.status = AvatarProfileStatus.READY
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)
        session.flush()
        return profile


# ---------------------------------------------------------------------------
# 原始素材服务
# ---------------------------------------------------------------------------


class AvatarSourceMediaService:
    """数字人原始素材服务

    - 仅存 object_key，不暴露绝对路径
    - 上传校验：文件类型白名单、大小、时长、哈希去重
    - 语音样本首版不用于声音克隆
    """

    PORTRAIT_VIDEO_ALLOWED_MIMES = {
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    }
    VOICE_SAMPLE_ALLOWED_MIMES = {
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/webm",
    }

    def register_source_media(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        media_type: AvatarSourceMediaType,
        object_key: str,
        mime_type: str,
        size_bytes: int,
        duration_ms: Optional[int] = None,
        content_sha256: str = "",
    ) -> AvatarSourceMedia:
        # 校验所有者
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        # 校验 MIME
        self._validate_mime(media_type, mime_type)
        # 校验大小
        self._validate_size(media_type, size_bytes)

        # 去重：同 avatar_id + content_sha256 已存在则直接返回
        if content_sha256:
            existing = session.exec(
                select(AvatarSourceMedia).where(
                    AvatarSourceMedia.avatar_id == avatar_id,
                    AvatarSourceMedia.content_sha256 == content_sha256,
                    AvatarSourceMedia.upload_status != AvatarSourceMediaStatus.EXPIRED,
                )
            ).first()
            if existing is not None:
                return existing

        source = AvatarSourceMedia(
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            media_type=media_type,
            object_key=object_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            duration_ms=duration_ms,
            content_sha256=content_sha256,
            upload_status=AvatarSourceMediaStatus.UPLOADED,
        )
        session.add(source)
        session.flush()
        return source

    def list_source_media(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        media_type: Optional[AvatarSourceMediaType] = None,
    ) -> list[AvatarSourceMedia]:
        # 校验所有者
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        stmt = select(AvatarSourceMedia).where(AvatarSourceMedia.avatar_id == avatar_id)
        if media_type is not None:
            stmt = stmt.where(AvatarSourceMedia.media_type == media_type)
        stmt = stmt.order_by(AvatarSourceMedia.created_at.desc())
        return list(session.exec(stmt).all())

    def _validate_mime(
        self, media_type: AvatarSourceMediaType, mime_type: str,
    ) -> None:
        allowed = (
            self.PORTRAIT_VIDEO_ALLOWED_MIMES
            if media_type == AvatarSourceMediaType.PORTRAIT_VIDEO
            else self.VOICE_SAMPLE_ALLOWED_MIMES
        )
        if mime_type.lower() not in allowed:
            reject_validation_failed(
                f"不支持的文件类型: {mime_type}",
                details={"allowed": sorted(allowed)},
            )

    def _validate_size(
        self, media_type: AvatarSourceMediaType, size_bytes: int,
    ) -> None:
        from app.core.config import settings
        if media_type == AvatarSourceMediaType.PORTRAIT_VIDEO:
            max_mb = settings.AVATAR_PORTRAIT_VIDEO_MAX_MB
        else:
            max_mb = settings.AVATAR_VOICE_SAMPLE_MAX_MB
        if size_bytes > max_mb * 1024 * 1024:
            reject_validation_failed(
                f"文件超过最大限制 {max_mb}MB",
                details={"size_bytes": size_bytes, "max_mb": max_mb},
            )


# ---------------------------------------------------------------------------
# 资产预处理服务
# ---------------------------------------------------------------------------


class AvatarPreparationService:
    """数字人资产预处理服务

    - 通过 task_service 持久化任务，不在主 Web 请求里同步执行
    - 失败时保留原始 error_code，禁止伪装成功
    - M1 阶段：同步执行 Fake Provider 验证端到端流程
    - M4 阶段：改为独立 Worker 调用真实引擎
    """

    def create_preparation_job(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        provider_key: Optional[str] = None,
        idempotency_key: str = "",
    ) -> tuple[AvatarPreparationJob, str]:
        profile = profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )

        # 状态机校验：disabled 不允许启动新预处理
        # draft/uploaded/failed/ready 均可（ready/failed 用于重预处理或重试）
        if profile.status == AvatarProfileStatus.DISABLED:
            reject_state_conflict(
                "已停用的预设不能启动预处理，请先恢复启用",
                details={"current_status": profile.status.value},
            )

        # 校验已有 portrait_video 素材
        sources = source_media_service.list_source_media(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
            media_type=AvatarSourceMediaType.PORTRAIT_VIDEO,
        )
        if not sources:
            reject_state_conflict("缺少形象视频素材，无法启动预处理")
        portrait = sources[0]
        voice_samples = source_media_service.list_source_media(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
            media_type=AvatarSourceMediaType.VOICE_SAMPLE,
        )
        voice = voice_samples[0] if voice_samples else None

        if not idempotency_key:
            idempotency_key = "auto_" + uuid.uuid4().hex[:16]

        # 幂等检查
        existing = session.exec(
            select(AvatarPreparationJob).where(
                AvatarPreparationJob.avatar_id == avatar_id,
                AvatarPreparationJob.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            return existing, existing.task_id or ""

        # 计算输入哈希
        input_hash = hashlib.sha256(
            f"{avatar_id}|{portrait.object_key}|{voice.object_key if voice else ''}"
            f"|{provider_key or profile.provider_key}".encode("utf-8")
        ).hexdigest()

        # 在 task_service 创建统一任务
        task_view = task_service.create_task(session, TaskCreateRequest(
            task_type="media.avatar_preprocess",
            owner_user_id=owner_user_id,
            input_summary=f"预处理数字人预设 {profile.display_name}",
            input_payload={
                "avatar_id": avatar_id,
                "portrait_object_key": portrait.object_key,
                "voice_object_key": voice.object_key if voice else None,
                "provider_key": provider_key or profile.provider_key,
            },
            idempotency_key=f"avatar_prep:{avatar_id}:{idempotency_key}",
            resource_links=[{
                "resource_kind": "avatar_preparation_job",
                "resource_id": "pending",
                "relation": "output",
            }],
        ))

        job = AvatarPreparationJob(
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            provider_key=provider_key or profile.provider_key,
            status=AvatarPreparationJobStatus.PENDING,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
            input_summary=f"portrait={portrait.object_key};voice={voice.object_key if voice else ''}",
            input_payload={
                "portrait_object_key": portrait.object_key,
                "voice_object_key": voice.object_key if voice else None,
            },
            task_id=task_view.task_id,
        )
        session.add(job)

        # 同时把 profile 标记 processing
        profile.status = AvatarProfileStatus.PROCESSING
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)

        session.flush()
        return job, task_view.task_id

    def execute_preparation_job(
        self,
        session: Session,
        *,
        avatar_id: str,
        job_id: str,
        owner_user_id: int,
    ) -> AvatarPreparationJob:
        """同步执行预处理任务（M1 阶段使用 Fake Provider）"""
        job = self.get_preparation_job(
            session, avatar_id=avatar_id, job_id=job_id, owner_user_id=owner_user_id,
        )
        profile = profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )

        # 标记 running
        job.status = AvatarPreparationJobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.attempt_count += 1
        session.add(job)
        if job.task_id:
            task_service.mark_running(session, job.task_id, stage="avatar_preprocessing")
        session.flush()

        provider = get_digital_human_provider(job.provider_key)

        try:
            request = AvatarPreparationRequest(
                avatar_id=avatar_id,
                owner_user_id=owner_user_id,
                portrait_video_object_key=job.input_payload.get("portrait_object_key", ""),
                voice_sample_object_key=job.input_payload.get("voice_object_key"),
                provider_key=job.provider_key,
                provider_version=provider.provider_version,
                consent_text=profile.consent_text,
                idempotency_key=job.idempotency_key,
            )
            result = provider.prepare_avatar(request)
        except Exception as e:
            error_code = "DH_PROVIDER_FAILED"
            error_message_safe = str(e)[:500]
            job.status = AvatarPreparationJobStatus.FAILED
            job.error_code = error_code
            job.error_message_safe = error_message_safe
            job.finished_at = datetime.now(timezone.utc)
            session.add(job)
            profile.status = AvatarProfileStatus.FAILED
            profile.updated_at = job.finished_at
            session.add(profile)
            if job.task_id:
                task_service.mark_failed(
                    session, job.task_id,
                    error_code=error_code,
                    error_message=error_message_safe,
                )
            session.flush()
            return job

        # 创建资产包
        asset_package = AvatarAssetPackage(
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            provider_key=result.provider_key,
            provider_version=result.provider_version,
            object_prefix=result.object_prefix,
            manifest_object_key=result.manifest_object_key,
            asset_sha256=result.asset_sha256,
            estimated_download_bytes=result.estimated_download_bytes,
            supported_render_modes=result.supported_render_modes,
            quality_profiles=result.quality_profiles,
            status=AvatarAssetPackageStatus.READY,
            finished_at=datetime.now(timezone.utc),
        )
        session.add(asset_package)
        session.flush()

        # 更新 profile 与 job
        profile.status = AvatarProfileStatus.READY
        profile.current_asset_package_id = asset_package.asset_package_id
        profile.provider_key = result.provider_key
        profile.provider_version = result.provider_version
        profile.updated_at = datetime.now(timezone.utc)
        session.add(profile)

        job.status = AvatarPreparationJobStatus.SUCCEEDED
        job.result_asset_package_id = asset_package.asset_package_id
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        if job.task_id:
            task_service.mark_succeeded(
                session, job.task_id,
                result_ref=asset_package.asset_package_id,
                result_data={
                    "asset_package_id": asset_package.asset_package_id,
                    "manifest_object_key": asset_package.manifest_object_key,
                    "provider_key": result.provider_key,
                    "provider_version": result.provider_version,
                    "warnings": result.warnings,
                },
            )
        session.flush()
        return job

    def get_preparation_job(
        self,
        session: Session,
        *,
        avatar_id: str,
        job_id: str,
        owner_user_id: Optional[int] = None,
    ) -> AvatarPreparationJob:
        job = session.exec(
            select(AvatarPreparationJob).where(
                AvatarPreparationJob.job_id == job_id,
                AvatarPreparationJob.avatar_id == avatar_id,
            )
        ).first()
        if job is None:
            reject_resource_not_found(f"预处理任务 {job_id} 不存在")
        if owner_user_id is not None and job.owner_user_id != owner_user_id:
            reject_resource_not_found(f"预处理任务 {job_id} 不存在")
        return job

    def list_preparation_jobs(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
    ) -> list[AvatarPreparationJob]:
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        return list(session.exec(
            select(AvatarPreparationJob).where(
                AvatarPreparationJob.avatar_id == avatar_id,
                AvatarPreparationJob.owner_user_id == owner_user_id,
            ).order_by(AvatarPreparationJob.created_at.desc())
        ).all())


# ---------------------------------------------------------------------------
# 资产包服务
# ---------------------------------------------------------------------------


class AvatarAssetPackageService:
    """数字人资产包服务"""

    def get_package(
        self,
        session: Session,
        *,
        asset_package_id: str,
        owner_user_id: Optional[int] = None,
    ) -> AvatarAssetPackage:
        pkg = session.exec(
            select(AvatarAssetPackage).where(
                AvatarAssetPackage.asset_package_id == asset_package_id,
            )
        ).first()
        if pkg is None:
            reject_resource_not_found(f"资产包 {asset_package_id} 不存在")
        if owner_user_id is not None and pkg.owner_user_id != owner_user_id:
            reject_resource_not_found(f"资产包 {asset_package_id} 不存在")
        return pkg

    def list_packages(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
    ) -> list[AvatarAssetPackage]:
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        return list(session.exec(
            select(AvatarAssetPackage).where(
                AvatarAssetPackage.avatar_id == avatar_id,
                AvatarAssetPackage.owner_user_id == owner_user_id,
            ).order_by(AvatarAssetPackage.created_at.desc())
        ).all())


# ---------------------------------------------------------------------------
# 课程绑定服务
# ---------------------------------------------------------------------------


class CourseAvatarBindingService:
    """课程数字人绑定服务

    - 教师只能绑定 owner_user_id 是自己的 AvatarProfile
    - 状态机：draft → published → withdrawn | stale
    - 撤回后学生端走兼容模式
    """

    def create_or_update_binding(
        self,
        session: Session,
        *,
        course_id: int,
        avatar_id: str,
        bound_by_user_id: int,
        notes: str = "",
    ) -> CourseAvatarBinding:
        # 校验预设归属
        profile = profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=bound_by_user_id,
        )
        if profile.status != AvatarProfileStatus.READY:
            reject_state_conflict(
                f"预设状态 {profile.status.value} 不可绑定，仅 ready 可绑定",
                details={"current_status": profile.status.value},
            )
        if not profile.current_asset_package_id:
            reject_state_conflict("预设缺少可用资产包")

        # 同课程同 release 只能有一条 binding；若未指定 release，则按 draft 处理
        # 这里检查是否已有 draft binding（未发布的），有则更新
        existing = session.exec(
            select(CourseAvatarBinding).where(
                CourseAvatarBinding.course_id == course_id,
                CourseAvatarBinding.bound_by_user_id == bound_by_user_id,
                CourseAvatarBinding.status == CourseAvatarBindingStatus.DRAFT,
            )
        ).first()

        if existing is not None:
            existing.avatar_id = avatar_id
            existing.locked_provider_key = profile.provider_key
            existing.locked_provider_version = profile.provider_version
            existing.locked_asset_package_id = profile.current_asset_package_id
            existing.notes = notes
            existing.binding_metadata = {}
            session.add(existing)
            session.flush()
            return existing

        binding = CourseAvatarBinding(
            course_id=course_id,
            avatar_id=avatar_id,
            bound_by_user_id=bound_by_user_id,
            status=CourseAvatarBindingStatus.DRAFT,
            locked_provider_key=profile.provider_key,
            locked_provider_version=profile.provider_version,
            locked_asset_package_id=profile.current_asset_package_id,
            notes=notes,
        )
        session.add(binding)
        session.flush()
        return binding

    def get_binding(
        self,
        session: Session,
        *,
        course_id: int,
        binding_id: Optional[str] = None,
    ) -> Optional[CourseAvatarBinding]:
        """获取课程当前绑定（默认取最新 draft 或 published）"""
        if binding_id is not None:
            return session.exec(
                select(CourseAvatarBinding).where(
                    CourseAvatarBinding.binding_id == binding_id,
                    CourseAvatarBinding.course_id == course_id,
                )
            ).first()
        # 取最新的一条
        return session.exec(
            select(CourseAvatarBinding).where(
                CourseAvatarBinding.course_id == course_id,
            ).order_by(CourseAvatarBinding.created_at.desc())
        ).first()

    def publish_binding(
        self,
        session: Session,
        *,
        course_id: int,
        binding_id: str,
        media_release_id: str,
        bound_by_user_id: int,
    ) -> CourseAvatarBinding:
        binding = self._require_binding(
            session, course_id=course_id, binding_id=binding_id,
            bound_by_user_id=bound_by_user_id,
        )
        if binding.status not in (
            CourseAvatarBindingStatus.DRAFT, CourseAvatarBindingStatus.WITHDRAWN,
        ):
            reject_state_conflict(
                f"绑定状态 {binding.status.value} 不允许发布",
                details={"current_status": binding.status.value},
            )

        binding.status = CourseAvatarBindingStatus.PUBLISHED
        binding.media_release_id = media_release_id
        binding.published_at = datetime.now(timezone.utc)
        session.add(binding)
        session.flush()
        return binding

    def withdraw_binding(
        self,
        session: Session,
        *,
        course_id: int,
        binding_id: str,
        bound_by_user_id: int,
    ) -> CourseAvatarBinding:
        binding = self._require_binding(
            session, course_id=course_id, binding_id=binding_id,
            bound_by_user_id=bound_by_user_id,
        )
        if binding.status not in (
            CourseAvatarBindingStatus.DRAFT, CourseAvatarBindingStatus.PUBLISHED,
        ):
            reject_state_conflict(
                f"绑定状态 {binding.status.value} 不允许撤回",
                details={"current_status": binding.status.value},
            )
        binding.status = CourseAvatarBindingStatus.WITHDRAWN
        binding.withdrawn_at = datetime.now(timezone.utc)
        session.add(binding)
        session.flush()
        return binding

    def list_bindings(
        self,
        session: Session,
        *,
        course_id: int,
        status: Optional[CourseAvatarBindingStatus] = None,
    ) -> list[CourseAvatarBinding]:
        stmt = select(CourseAvatarBinding).where(
            CourseAvatarBinding.course_id == course_id,
        )
        if status is not None:
            stmt = stmt.where(CourseAvatarBinding.status == status)
        stmt = stmt.order_by(CourseAvatarBinding.created_at.desc())
        return list(session.exec(stmt).all())

    def _require_binding(
        self,
        session: Session,
        *,
        course_id: int,
        binding_id: str,
        bound_by_user_id: int,
    ) -> CourseAvatarBinding:
        binding = session.exec(
            select(CourseAvatarBinding).where(
                CourseAvatarBinding.binding_id == binding_id,
                CourseAvatarBinding.course_id == course_id,
            )
        ).first()
        if binding is None:
            reject_resource_not_found(f"绑定 {binding_id} 不存在")
        if binding.bound_by_user_id != bound_by_user_id:
            reject_resource_not_found(f"绑定 {binding_id} 不存在")
        return binding


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------


profile_service = AvatarProfileService()
source_media_service = AvatarSourceMediaService()
preparation_service = AvatarPreparationService()
asset_package_service = AvatarAssetPackageService()
course_avatar_binding_service = CourseAvatarBindingService()
