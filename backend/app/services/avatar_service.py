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
from app.core.time_utils import utcnow_naive
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
            consented_at=utcnow_naive(),
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
        profile.updated_at = utcnow_naive()
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
        profile.deleted_at = utcnow_naive()
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
        profile.updated_at = utcnow_naive()
        session.add(profile)
        session.flush()
        return profile


# ---------------------------------------------------------------------------
# 原始素材服务
# ---------------------------------------------------------------------------


class AvatarSourceMediaService:
    """数字人原始素材服务（P0-3 安全链路）

    两步式受控上传：
    1. request_upload_intent：服务端生成 object_key（按教师+预设命名空间隔离），
       签发短时、限大小、限 MIME 的上传意图，状态=pending_upload。
    2. confirm_uploaded：服务端 head 对象 -> ffprobe 探测 -> 计算 hash ->
       病毒扫描 stub -> 全部通过则状态=verified，否则 invalid/quarantined。

    安全约束：
    - object_key 只能由服务端生成，禁止客户端提交任意键
    - 服务端探测的 mime/duration/hash/size 才可信，客户端自报仅作预校验
    - 预处理入口只接受 verified 素材
    """

    PORTRAIT_VIDEO_ALLOWED_MIMES = {
        "video/mp4", "video/webm", "video/quicktime", "video/x-msvideo",
    }
    VOICE_SAMPLE_ALLOWED_MIMES = {
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/webm",
    }

    # 服务端生成的 object_key 前缀，按教师和 AvatarProfile 命名空间隔离
    OBJECT_KEY_PREFIX = "avatar_sources"

    def request_upload_intent(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        media_type: AvatarSourceMediaType,
        client_mime_type: str,
        client_size_bytes: int,
    ) -> tuple[AvatarSourceMedia, dict]:
        """第 1 步：服务端生成 object_key + 签发上传意图。

        返回 (source_media_record, upload_intent_dict)。
        upload_intent_dict 包含：object_key, upload_url, method, headers,
        expires_at, max_size_bytes, allowed_mime_types。

        - 不接受客户端提交 object_key，杜绝越权登记他人对象键。
        - client_mime_type / client_size_bytes 仅作预校验，真实值以服务端探测为准。
        """
        # 校验所有者
        profile = profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        # 预校验 MIME
        self._validate_mime(media_type, client_mime_type)
        # 预校验大小
        self._validate_size(media_type, client_size_bytes)

        # 服务端生成 object_key：avatar_sources/u{user_id}/{avatar_id}/{media_type}/{uuid}.{ext}
        ext = self._extension_for_mime(media_type, client_mime_type)
        object_key = (
            f"{self.OBJECT_KEY_PREFIX}/u{owner_user_id}/{avatar_id}/"
            f"{media_type.value}/{uuid.uuid4().hex}{ext}"
        )

        source = AvatarSourceMedia(
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            media_type=media_type,
            object_key=object_key,
            mime_type=client_mime_type,  # 客户端自报，待服务端探测覆盖
            size_bytes=client_size_bytes,
            upload_status=AvatarSourceMediaStatus.PENDING_UPLOAD,
        )
        session.add(source)
        session.flush()

        # 签发上传意图：限大小、限 MIME、短时
        from app.core.config import settings
        max_bytes = self._max_bytes_for(media_type)
        expires_in = 900  # 15 分钟
        intent = {
            "object_key": object_key,
            "source_media_id": source.source_media_id,
            "upload_url": "/api/v1/media/avatar-sources/upload",
            "method": "PUT",
            "headers": {"Content-Type": client_mime_type},
            "expires_at": int(datetime.now(timezone.utc).timestamp()) + expires_in,
            "max_size_bytes": max_bytes,
            "allowed_mime_types": sorted(self._allowed_mimes_for(media_type)),
            "signature_subject": f"avatar_source:{source.source_media_id}",
        }
        # 记录到 profile（保持 profile 状态可观察）
        if profile.status == AvatarProfileStatus.DRAFT:
            profile.status = AvatarProfileStatus.UPLOADED
        return source, intent

    def confirm_uploaded(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        source_media_id: str,
    ) -> AvatarSourceMedia:
        """第 2 步：服务端确认对象存在 + 探测 + 哈希 + 扫描，状态转为 verified。

        P0-3 安全链路核心：
        1. 校验 source_media 属于该教师（防止越权）
        2. 调用 object_storage.head() 确认对象真实存在
        3. 调用 _probe_media() 重新探测真实 mime/duration（ffprobe 或同类）
        4. 服务端重新读取对象流计算 content_sha256（不信任客户端）
        5. 调用 _scan_for_threats() 病毒/恶意文件扫描
        6. 全部通过 -> verified；任一失败 -> invalid/quarantined
        """
        source = self._get_owned_source(
            session,
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            source_media_id=source_media_id,
        )
        # 状态机校验：仅 pending_upload 或 uploaded 可重新确认
        if source.upload_status not in (
            AvatarSourceMediaStatus.PENDING_UPLOAD,
            AvatarSourceMediaStatus.UPLOADED,
            AvatarSourceMediaStatus.INVALID,
        ):
            reject_state_conflict(
                f"素材当前状态 {source.upload_status.value} 不允许重新确认",
                details={"source_media_id": source_media_id, "current_status": source.upload_status.value},
            )

        storage = get_object_storage()
        notes_parts: list[str] = []

        # 1. 确认对象存在
        if not storage.exists(source.object_key):
            source.upload_status = AvatarSourceMediaStatus.INVALID
            source.validation_notes = "object_not_found"
            session.add(source)
            session.flush()
            return source

        head_info = storage.head(source.object_key)
        source.server_size_bytes = int(head_info.get("size_bytes") or 0)
        if source.server_size_bytes == 0:
            source.upload_status = AvatarSourceMediaStatus.INVALID
            source.validation_notes = "empty_object"
            session.add(source)
            session.flush()
            return source

        # 2. 服务端重新读取对象流计算 content_sha256（不信任客户端）
        try:
            content = storage.get(source.object_key)
            server_sha = hashlib.sha256(content).hexdigest()
            source.server_content_sha256 = server_sha
        except Exception as exc:
            source.upload_status = AvatarSourceMediaStatus.INVALID
            source.validation_notes = f"hash_compute_failed: {type(exc).__name__}"
            session.add(source)
            session.flush()
            return source

        # 3. ffprobe/同类探测真实媒体信息
        try:
            probe = _probe_media(source.object_key, content, source.media_type)
            source.server_mime_type = probe.get("mime_type", "")
            source.server_duration_ms = probe.get("duration_ms")
            if probe.get("note"):
                notes_parts.append(probe["note"])
        except Exception as exc:
            source.upload_status = AvatarSourceMediaStatus.INVALID
            source.validation_notes = f"probe_failed: {type(exc).__name__}: {exc}"[:500]
            session.add(source)
            session.flush()
            return source

        # 4. 校验服务端探测到的 MIME 与大小
        try:
            self._validate_server_mime(source.media_type, source.server_mime_type)
            self._validate_server_size(source.media_type, source.server_size_bytes)
        except Exception as exc:
            source.upload_status = AvatarSourceMediaStatus.INVALID
            source.validation_notes = f"server_validation_failed: {exc}"[:500]
            session.add(source)
            session.flush()
            return source

        # 5. 病毒/恶意文件扫描（首版 stub，可接入 ClamAV）
        scan_result = _scan_for_threats(source.object_key, content)
        source.scan_status = scan_result.get("status", "not_scanned")
        if scan_result.get("note"):
            notes_parts.append(scan_result["note"])
        if scan_result.get("status") == "quarantined":
            source.upload_status = AvatarSourceMediaStatus.QUARANTINED
            source.validation_notes = "; ".join(notes_parts) or "scan_quarantined"
            session.add(source)
            session.flush()
            return source

        # 6. 全部通过 -> verified
        source.upload_status = AvatarSourceMediaStatus.VERIFIED
        source.verified_at = utcnow_naive()
        source.validated_at = source.verified_at
        source.validation_notes = "; ".join(notes_parts) if notes_parts else "ok"
        session.add(source)
        session.flush()
        return source

    def withdraw_source_media(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        source_media_id: str,
    ) -> AvatarSourceMedia:
        """教师主动撤回素材（状态转为 withdrawn）。"""
        source = self._get_owned_source(
            session,
            avatar_id=avatar_id,
            owner_user_id=owner_user_id,
            source_media_id=source_media_id,
        )
        if source.upload_status == AvatarSourceMediaStatus.WITHDRAWN:
            return source
        source.upload_status = AvatarSourceMediaStatus.WITHDRAWN
        session.add(source)
        session.flush()
        return source

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
        """[已废弃] 旧式直接登记素材接口。

        P0-3 后请改用 request_upload_intent + confirm_uploaded 两步式流程。
        本方法保留仅为兼容旧测试，新代码不应使用。

        安全注意：本方法不再信任客户端 object_key，会校验其前缀必须由本服务生成
        （即必须以 avatar_sources/u{owner_user_id}/{avatar_id}/ 开头）。
        """
        # 校验所有者
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        # 校验 MIME
        self._validate_mime(media_type, mime_type)
        # 校验大小
        self._validate_size(media_type, size_bytes)
        # P0-3：校验 object_key 必须由本服务生成（命名空间隔离）
        expected_prefix = (
            f"{self.OBJECT_KEY_PREFIX}/u{owner_user_id}/{avatar_id}/"
        )
        if not object_key.startswith(expected_prefix):
            reject_validation_failed(
                "object_key 必须由服务端 request_upload_intent 生成，"
                "禁止提交任意对象键",
                details={
                    "expected_prefix": expected_prefix,
                    "object_key": object_key,
                },
            )

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

    def _get_owned_source(
        self,
        session: Session,
        *,
        avatar_id: str,
        owner_user_id: int,
        source_media_id: str,
    ) -> AvatarSourceMedia:
        """获取指定 source_media 并校验归属，防止越权。"""
        profile_service.get_profile(
            session, avatar_id=avatar_id, owner_user_id=owner_user_id,
        )
        source = session.exec(
            select(AvatarSourceMedia).where(
                AvatarSourceMedia.source_media_id == source_media_id,
                AvatarSourceMedia.avatar_id == avatar_id,
                AvatarSourceMedia.owner_user_id == owner_user_id,
            )
        ).first()
        if source is None:
            reject_resource_not_found(
                "AvatarSourceMedia",
                f"source_media_id={source_media_id} 不存在或不属于该教师",
            )
        return source

    def _allowed_mimes_for(
        self, media_type: AvatarSourceMediaType,
    ) -> set[str]:
        return (
            self.PORTRAIT_VIDEO_ALLOWED_MIMES
            if media_type == AvatarSourceMediaType.PORTRAIT_VIDEO
            else self.VOICE_SAMPLE_ALLOWED_MIMES
        )

    def _max_bytes_for(
        self, media_type: AvatarSourceMediaType,
    ) -> int:
        from app.core.config import settings
        if media_type == AvatarSourceMediaType.PORTRAIT_VIDEO:
            return int(settings.AVATAR_PORTRAIT_VIDEO_MAX_MB) * 1024 * 1024
        return int(settings.AVATAR_VOICE_SAMPLE_MAX_MB) * 1024 * 1024

    def _extension_for_mime(
        self, media_type: AvatarSourceMediaType, mime_type: str,
    ) -> str:
        """根据 MIME 推断文件扩展名。"""
        ext_map = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "video/quicktime": ".mov",
            "video/x-msvideo": ".avi",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/webm": ".weba",
        }
        return ext_map.get(mime_type.lower(), ".bin")

    def _validate_server_mime(
        self, media_type: AvatarSourceMediaType, server_mime_type: str,
    ) -> None:
        """服务端探测到的 MIME 校验（更严格，不允许 octet-stream）。"""
        if not server_mime_type:
            reject_validation_failed(
                "服务端未能探测到 MIME 类型，文件可能已损坏",
                details={"server_mime_type": server_mime_type},
            )
        allowed = self._allowed_mimes_for(media_type)
        if server_mime_type.lower() not in allowed:
            reject_validation_failed(
                f"服务端探测到的 MIME 类型不被允许: {server_mime_type}",
                details={"allowed": sorted(allowed), "server_mime_type": server_mime_type},
            )

    def _validate_server_size(
        self, media_type: AvatarSourceMediaType, server_size_bytes: int,
    ) -> None:
        """服务端探测到的大小校验。"""
        from app.core.config import settings
        if media_type == AvatarSourceMediaType.PORTRAIT_VIDEO:
            max_mb = settings.AVATAR_PORTRAIT_VIDEO_MAX_MB
        else:
            max_mb = settings.AVATAR_VOICE_SAMPLE_MAX_MB
        if server_size_bytes > max_mb * 1024 * 1024:
            reject_validation_failed(
                f"服务端探测到文件超过最大限制 {max_mb}MB",
                details={"server_size_bytes": server_size_bytes, "max_mb": max_mb},
            )

    def _validate_mime(
        self, media_type: AvatarSourceMediaType, mime_type: str,
    ) -> None:
        allowed = self._allowed_mimes_for(media_type)
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
# 媒体探测与扫描（P0-3 安全链路）
# ---------------------------------------------------------------------------


def _probe_media(
    object_key: str, content: bytes, media_type: AvatarSourceMediaType,
) -> dict:
    """服务端探测真实媒体信息。

    优先使用 ffprobe；若 ffprobe 不可用，回退到扩展名推断（标注 note）。

    返回 {mime_type, duration_ms, note}。
    """
    from app.services.object_storage import mime_type_for
    note = ""
    mime = mime_type_for(object_key)
    duration_ms: Optional[int] = None

    # 尝试调用 ffprobe（如果可用）
    try:
        probe_result = _ffprobe_probe(content)
        if probe_result:
            mime = probe_result.get("mime_type", mime)
            duration_ms = probe_result.get("duration_ms")
    except FileNotFoundError:
        note = "ffprobe_not_available;fallback_to_extension"
    except Exception as exc:  # noqa: BLE001
        note = f"ffprobe_failed:{type(exc).__name__}"

    return {"mime_type": mime, "duration_ms": duration_ms, "note": note}


def _ffprobe_probe(content: bytes) -> Optional[dict]:
    """调用 ffprobe 探测真实媒体信息。

    通过临时文件写入 content，调用 ffprobe 解析 JSON 输出。
    ffprobe 不可用时抛 FileNotFoundError。
    """
    import json as _json
    import shutil as _shutil
    import subprocess as _subprocess
    import tempfile as _tempfile

    ffprobe = _shutil.which("ffprobe")
    if not ffprobe:
        raise FileNotFoundError("ffprobe not installed")

    with _tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = _subprocess.run(
            [
                ffprobe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return None
        data = _json.loads(result.stdout or "{}")
        fmt = data.get("format", {})
        duration_seconds = float(fmt.get("duration") or 0)
        duration_ms = int(duration_seconds * 1000) if duration_seconds > 0 else None

        # 从第一个 stream 推断 MIME
        streams = data.get("streams") or []
        mime_type = ""
        if streams:
            codec_type = streams[0].get("codec_type", "")
            if codec_type == "video":
                mime_type = "video/mp4"
            elif codec_type == "audio":
                mime_type = "audio/mpeg"

        return {"mime_type": mime_type, "duration_ms": duration_ms}
    finally:
        try:
            import os as _os
            _os.unlink(tmp_path)
        except OSError:
            pass


def _scan_for_threats(object_key: str, content: bytes) -> dict:
    """病毒/恶意文件扫描 stub。

    首版不接入真实杀毒引擎，仅做基本 sanity check：
    - 文件大小 > 0
    - 内容非全零（防止伪装上传）
    - 文件签名与扩展名一致（防止伪装）

    生产部署应替换为 ClamAV 或同类引擎调用。
    返回 {status: "clean"|"quarantined", note: str}。
    """
    if not content:
        return {"status": "quarantined", "note": "empty_content"}

    # 全零内容检测（伪装上传）
    if all(b == 0 for b in content[:min(len(content), 4096)]):
        return {
            "status": "quarantined",
            "note": "all_zero_content_suspected_disguise",
        }

    # 文件签名 sanity check
    from app.services.object_storage import mime_type_for
    expected_mime = mime_type_for(object_key)
    signature_mime = _detect_signature_mime(content)
    if signature_mime and expected_mime and signature_mime != expected_mime:
        # 仅当签名明确指向不同类型时报警
        if (signature_mime.startswith("video/") and expected_mime.startswith("audio/")) or \
           (signature_mime.startswith("audio/") and expected_mime.startswith("video/")):
            return {
                "status": "quarantined",
                "note": f"signature_mismatch:expected={expected_mime},actual={signature_mime}",
            }

    return {"status": "clean", "note": "stub_scan_passed"}


def _detect_signature_mime(content: bytes) -> str:
    """通过文件头魔数检测真实 MIME 类型。"""
    if len(content) < 12:
        return ""
    # MP4: .... ftyp
    if content[4:8] == b"ftyp":
        return "video/mp4"
    # WebM: 1A 45 DF A3
    if content[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    # MP3: ID3 or FF FB
    if content[:3] == b"ID3" or (content[0] == 0xFF and (content[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    # WAV: RIFF....WAVE
    if content[:4] == b"RIFF" and content[8:12] == b"WAVE":
        return "audio/wav"
    return ""


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

        # 状态机校验：disabled/quarantined 不允许启动新预处理
        # draft/uploaded/failed/ready 均可（ready/failed 用于重预处理或重试）
        if profile.status in (AvatarProfileStatus.DISABLED, AvatarProfileStatus.QUARANTINED):
            reject_state_conflict(
                f"预设当前状态 {profile.status.value} 不能启动预处理，请先恢复启用或重新上传素材",
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

        # P0-3.6 安全校验：所有依赖素材必须处于 VERIFIED 状态
        # pending_upload/uploaded/invalid/quarantined/withdrawn/expired 均拒绝
        unverified_sources = [
            s for s in ([portrait] + ([voice] if voice else []))
            if s.upload_status != AvatarSourceMediaStatus.VERIFIED
        ]
        if unverified_sources:
            bad = [
                {
                    "source_media_id": s.source_media_id,
                    "media_type": s.media_type.value,
                    "upload_status": s.upload_status.value,
                }
                for s in unverified_sources
            ]
            reject_state_conflict(
                "存在未通过服务端校验的素材，无法启动预处理；请先调用 confirm 端点完成校验",
                details={"unverified_sources": bad},
            )

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
        profile.updated_at = utcnow_naive()
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
        job.started_at = utcnow_naive()
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
            job.finished_at = utcnow_naive()
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
            finished_at=utcnow_naive(),
        )
        session.add(asset_package)
        session.flush()

        # 更新 profile 与 job
        profile.status = AvatarProfileStatus.READY
        profile.current_asset_package_id = asset_package.asset_package_id
        profile.provider_key = result.provider_key
        profile.provider_version = result.provider_version
        profile.updated_at = utcnow_naive()
        session.add(profile)

        job.status = AvatarPreparationJobStatus.SUCCEEDED
        job.result_asset_package_id = asset_package.asset_package_id
        job.finished_at = utcnow_naive()
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
        binding.published_at = utcnow_naive()
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
        binding.withdrawn_at = utcnow_naive()
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
