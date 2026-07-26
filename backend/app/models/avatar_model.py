"""阶段8 教师数字人资产中心模型

实现「教师建立数字人预设 → 课程绑定 → 学生端播放」的资产链。

设计要点：
- `AvatarProfile`：教师拥有的逻辑数字人预设，按 `owner_user_id` 严格隔离。
  不绑定具体引擎字段，只持有 `provider_key/provider_version/current_asset_package_id`。
- `AvatarSourceMedia`：原始上传文件登记，仅存 `object_key`，不入 Git、不暴露绝对路径。
- `AvatarPreparationJob`：异步预处理任务，通过 `task_id` 关联统一任务中心。
- `AvatarAssetPackage`：引擎可消费的产物包，含 manifest、哈希、支持的渲染模式。
- `CourseAvatarBinding`：把教师预设绑定到课程媒体版本，首版严格限制"只能绑定自己"。

核心安全约束：
- 教师只能管理自己的预设；学生只能读取已发布课程的渲染资产
- 原始视频/语音样本不能直接给学生下载
- 删除预设不立即删除历史版本，标记撤回并走媒体版本回滚
- 上传语音样本不自动做声音克隆，首版讯飞 TTS 用平台标准音色
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class AvatarProfileStatus(str, Enum):
    """数字人预设状态机"""
    DRAFT = "draft"            # 教师刚创建，尚未上传素材
    UPLOADED = "uploaded"      # 已上传素材，待预处理
    PROCESSING = "processing"  # 预处理中
    READY = "ready"            # 预处理完成，可用于课程绑定
    FAILED = "failed"          # 预处理失败
    DISABLED = "disabled"      # 教师主动停用
    QUARANTINED = "quarantined"  # 素材被隔离（恶意文件/校验失败），需教师重新上传
    DELETED = "deleted"        # 软删除


class AvatarSourceMediaType(str, Enum):
    """数字人原始素材类型"""
    PORTRAIT_VIDEO = "portrait_video"   # 形象视频（必填）
    VOICE_SAMPLE = "voice_sample"        # 语音样本（可选，首版不克隆）


class AvatarSourceMediaStatus(str, Enum):
    """原始素材上传与校验状态机（P0-3 安全链路）

    状态流转：
        pending_upload -> uploaded -> verified -> (quarantined | withdrawn)
                              |             |
                              +--> invalid  +--> expired

    - pending_upload: 已签发上传意图，客户端尚未上传完成
    - uploaded: 客户端已 PUT，等待服务端确认对象存在 + 探测 + 扫描
    - verified: 服务端已完成 head/ffprobe/hash/scan，可进入预处理
    - invalid: 校验失败（MIME/大小/格式/损坏）；可重新上传
    - quarantined: 病毒扫描阳性或安全风险；保留取证，禁止预处理
    - withdrawn: 教师主动撤回或预设被停用后撤销，不再可用
    - expired: 超过保留期，由回收策略处理
    """
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    VERIFIED = "verified"
    INVALID = "invalid"
    QUARANTINED = "quarantined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"

    # 兼容旧值：register_source_media 历史写入 "validated"
    @classmethod
    def _legacy_aliases(cls) -> dict[str, "AvatarSourceMediaStatus"]:
        return {"validated": cls.VERIFIED, "pending": cls.PENDING_UPLOAD}


class AvatarPreparationJobStatus(str, Enum):
    """预处理任务状态（与 TaskRecord 状态同步镜像）"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEGRADED = "degraded"      # 降级成功（如真实 Provider 不可用回退 Fake）


class AvatarAssetPackageStatus(str, Enum):
    """资产包状态"""
    BUILDING = "building"
    READY = "ready"
    INVALID = "invalid"        # 校验失败
    STALE = "stale"            # 依赖资产失效


class CourseAvatarBindingStatus(str, Enum):
    """课程数字人绑定状态"""
    DRAFT = "draft"            # 教师选定但未随版本发布
    PUBLISHED = "published"    # 已随 MediaRelease 发布，学生可见
    WITHDRAWN = "withdrawn"    # 教师主动撤回
    STALE = "stale"            # AvatarProfile 失效或资产包过期


class DigitalHumanProviderKey(str, Enum):
    """数字人 Provider 标识（首版只支持 fake，后续接入真实 Provider）"""
    FAKE = "fake"                  # 假 Provider，用于端到端测试
    DH_LIVE_MINI = "dh_live_mini"  # DH_live_mini（M4 接入）
    LITE_AVATAR = "lite_avatar"    # LiteAvatar（备用）
    DUIL_AVATAR = "duil_avatar"    # 现有 Duix.Avatar (GPU)


# ---------------------------------------------------------------------------
# 教师数字人预设
# ---------------------------------------------------------------------------


class AvatarProfile(SQLModel, table=True):
    """教师数字人预设

    - 按 `owner_user_id` 严格隔离，教师只能管理自己的预设
    - 不绑定具体引擎字段，仅持有 provider_key/provider_version
    - `current_asset_package_id` 指向最新可用资产包，可随 Provider 替换更新
    - 软删除：status=deleted，不立即清除历史绑定
    """

    __tablename__ = "avatar_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    avatar_id: str = Field(
        default_factory=lambda: "avp_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    owner_user_id: int = Field(foreign_key="users.id", index=True)
    display_name: str = Field(default="", max_length=100, description="教师可读名称")

    status: AvatarProfileStatus = Field(
        default=AvatarProfileStatus.DRAFT, index=True,
    )

    provider_key: str = Field(
        default=DigitalHumanProviderKey.FAKE.value,
        index=True,
        description="当前预设使用的数字人 Provider",
    )
    provider_version: str = Field(default="", description="Provider 自报版本")
    current_asset_package_id: Optional[str] = Field(
        default=None, index=True,
        description="当前激活的 AvatarAssetPackage.asset_package_id",
    )

    # 教师授权确认（必须勾选本人形象与授权）
    consent_text: str = Field(default="", description="授权确认文本快照")
    consented_at: Optional[datetime] = Field(default=None)
    # P0-3：显式记录教师本人形象授权确认与撤销时间，区别于 deleted_at（软删除）
    teacher_authorization_confirmed_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None, description="教师主动撤销授权时间")

    # 渲染偏好
    default_render_mode: str = Field(default="browser_realtime")
    supported_quality_profiles: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="如 ['auto', 'low_resource']",
    )

    notes: str = Field(default="", description="教师备注")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: Optional[datetime] = Field(default=None)


class AvatarSourceMedia(SQLModel, table=True):
    """数字人原始素材登记

    - 仅存 object_key，不暴露绝对路径
    - 语音样本首版不用于声音克隆
    - 保留期到期后由回收策略处理
    """

    __tablename__ = "avatar_source_media"

    id: Optional[int] = Field(default=None, primary_key=True)
    source_media_id: str = Field(
        default_factory=lambda: "asm_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    avatar_id: str = Field(index=True, description="关联 AvatarProfile.avatar_id")
    owner_user_id: int = Field(foreign_key="users.id", index=True)

    media_type: AvatarSourceMediaType = Field(index=True)
    object_key: str = Field(index=True, description="抽象存储键，禁止暴露本地路径")

    content_sha256: str = Field(default="", index=True, description="内容哈希，用于去重")
    mime_type: str = Field(default="")
    duration_ms: Optional[int] = Field(default=None)
    size_bytes: int = Field(default=0)

    upload_status: AvatarSourceMediaStatus = Field(
        default=AvatarSourceMediaStatus.PENDING_UPLOAD, index=True,
    )
    retention_policy: str = Field(default="standard", description="保留策略标识")

    validation_notes: str = Field(default="", description="校验结果备注")
    # P0-3：服务端探测结果（ffprobe/scan/hash）
    server_mime_type: str = Field(default="", description="服务端探测到的真实 MIME")
    server_duration_ms: Optional[int] = Field(default=None, description="服务端探测到的时长")
    server_size_bytes: int = Field(default=0, description="服务端 head 拿到的字节数")
    server_content_sha256: str = Field(
        default="", index=True, description="服务端重算的内容哈希（不信任客户端）",
    )
    scan_status: str = Field(
        default="not_scanned",
        description="病毒/恶意文件扫描状态：not_scanned|clean|quarantined",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validated_at: Optional[datetime] = Field(default=None, description="通过校验的时间")
    verified_at: Optional[datetime] = Field(default=None, description="服务端 head+ffprobe+scan 完成时间")


class AvatarPreparationJob(SQLModel, table=True):
    """数字人资产预处理任务

    - 通过 `task_id` 关联统一任务中心，不重复实现状态机
    - 每次重试/降级生成一条新记录（也可关联 MediaGenerationAttempt）
    - 失败时保留原始 error_code，禁止伪装成功
    """

    __tablename__ = "avatar_preparation_jobs"
    __table_args__ = (
        UniqueConstraint("avatar_id", "input_hash", name="uq_avatar_prep_input"),
        UniqueConstraint("avatar_id", "idempotency_key", name="uq_avatar_prep_idempotency"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(
        default_factory=lambda: "apj_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    task_id: Optional[str] = Field(
        default=None, index=True,
        description="关联 task_service.TaskRecord.task_id",
    )
    avatar_id: str = Field(index=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)

    provider_key: str = Field(default=DigitalHumanProviderKey.FAKE.value, index=True)
    provider_version: str = Field(default="")

    status: AvatarPreparationJobStatus = Field(
        default=AvatarPreparationJobStatus.PENDING, index=True,
    )

    idempotency_key: str = Field(default="", index=True, description="客户端重试去重键")
    input_hash: str = Field(default="", index=True, description="输入素材哈希")
    input_summary: str = Field(default="")
    input_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    result_asset_package_id: Optional[str] = Field(
        default=None, index=True,
        description="成功后生成的 AvatarAssetPackage.asset_package_id",
    )

    error_code: str = Field(default="")
    error_message_safe: str = Field(default="")
    attempt_count: int = Field(default=0)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)

    job_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))


class AvatarAssetPackage(SQLModel, table=True):
    """数字人资产包

    - 引擎可消费的产物（如 DH_live 的 .pth 模型 + manifest）
    - 通过 `manifest_object_key` 指向资产清单
    - 替换引擎时新建资产包，旧包标记 stale
    """

    __tablename__ = "avatar_asset_packages"

    id: Optional[int] = Field(default=None, primary_key=True)
    asset_package_id: str = Field(
        default_factory=lambda: "aap_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    avatar_id: str = Field(index=True)
    owner_user_id: int = Field(foreign_key="users.id", index=True)

    provider_key: str = Field(index=True)
    provider_version: str = Field(default="")

    object_prefix: str = Field(
        default="",
        description="资产在对象存储中的前缀(如 avatars/u_5/aap_xxx/)",
    )
    manifest_object_key: str = Field(default="", description="manifest.json 的 object_key")
    asset_sha256: str = Field(default="", index=True)
    estimated_download_bytes: int = Field(default=0)

    supported_render_modes: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="如 ['browser_realtime']",
    )
    quality_profiles: list = Field(
        default_factory=list, sa_column=Column(JSON),
        description="如 ['auto', 'low_resource', 'compatibility']",
    )

    status: AvatarAssetPackageStatus = Field(
        default=AvatarAssetPackageStatus.BUILDING, index=True,
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# 课程绑定
# ---------------------------------------------------------------------------


class CourseAvatarBinding(SQLModel, table=True):
    """课程数字人绑定

    - 把教师预设绑定到课程的 MediaRelease
    - 首版严格限制：教师只能绑定 owner_user_id 是自己的 AvatarProfile
    - 状态机：draft → published → withdrawn | stale
    - 撤回后学生端走兼容模式，不影响已发布的历史版本
    """

    __tablename__ = "course_avatar_bindings"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "media_release_id",
            name="uq_course_release_avatar_binding",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    binding_id: str = Field(
        default_factory=lambda: "cab_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    avatar_id: str = Field(index=True, description="关联 AvatarProfile.avatar_id")
    bound_by_user_id: int = Field(foreign_key="users.id", index=True)

    media_release_id: Optional[str] = Field(
        default=None, index=True,
        description="随该 MediaRelease 发布；未发布时为空",
    )

    status: CourseAvatarBindingStatus = Field(
        default=CourseAvatarBindingStatus.DRAFT, index=True,
    )

    # 绑定时锁定 Provider 与资产包版本，避免后续替换影响学生端
    locked_provider_key: str = Field(default="")
    locked_provider_version: str = Field(default="")
    locked_asset_package_id: Optional[str] = Field(default=None)

    notes: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = Field(default=None)
    withdrawn_at: Optional[datetime] = Field(default=None)

    binding_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
