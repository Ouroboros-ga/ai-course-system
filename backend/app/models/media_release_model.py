"""阶段8 媒体生成与发布模型

实现「讲稿 → TTS → 字幕/PPT 时间轴 → MediaRelease → 学生端播放」闭环的核心持久化模型。

设计要点：
- `MediaGenerationJob`：TTS/字幕/头像预处理/视频渲染等异步任务登记。
  与统一任务中心 `TaskRecord` 通过 `task_id` 一一对应，不重复实现任务状态机；
  每个任务携带 `provider_key/provider_version`、`input_hash`、`idempotency_key`。
- `MediaGenerationAttempt`：每次重试/降级的明细记录，便于审计与质量分析。
  失败原因保留 `error_code/error_message_safe`，禁止把 503/超时伪装成成功。
- `MediaRelease`：某课程对学生可见的不可变媒体版本，包含 PPT/字幕/音频/数字人 manifest
  的内容哈希与时间轴版本；支持回滚，旧版本标记 `stale` 而非静默删除。
- `MediaReleaseCue`：发布版本冻结的时间轴 Cue 快照（独立于编辑中的 `MediaTimelineCue`）。
- `PlaybackCapabilityProfile`：自动/低资源/兼容三档播放模式配置与实测结果。

所有媒体产物只通过 `object_key` 引用，绝不写入本地绝对路径。
所有读取继续经过 Course Access v1，按 `course_id` 严格隔离。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class MediaGenerationJobType(str, Enum):
    """媒体生成任务类型

    与 platform/tasks TaskType 区分：本枚举仅描述媒体领域子类型，
    实际任务状态机仍由 task_service.TaskRecord 承载。
    """
    TTS = "tts"                              # 讲稿 TTS 合成
    SUBTITLE = "subtitle"                     # 字幕分段
    AVATAR_PREPROCESS = "avatar_preprocess"   # 数字人资产预处理（教师资产中心）
    DH_RENDER = "dh_render"                   # 数字人渲染
    VIDEO_PACKAGE = "video_package"           # 封装视频合成
    TIMELINE_PUBLISH = "timeline_publish"     # 时间轴发布


class MediaGenerationStatus(str, Enum):
    """媒体生成任务状态（与 TaskRecord 状态同步镜像，便于直接查询）"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL_SUCCESS = "partial_success"
    DEGRADED = "degraded"     # 降级成功（如真实 Provider 不可用回退 Fake）


class MediaReleaseStatus(str, Enum):
    """媒体发布版本状态"""
    DRAFT = "draft"           # 教师编辑中，尚未激活
    ACTIVE = "active"         # 当前学生可见
    SUPERSEDED = "superseded"  # 被新版本替换
    WITHDRAWN = "withdrawn"   # 教师主动撤回
    STALE = "stale"           # 因依赖资产失效被标记


class MediaBuildBatchStatus(str, Enum):
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlaybackMode(str, Enum):
    """播放模式三档"""
    AUTO = "auto"                 # 自动模式：默认，能力探测后启用数字人
    LOW_RESOURCE = "low_resource"  # 低资源模式：降画质/降帧率
    COMPATIBILITY = "compatibility"  # 兼容模式：仅音频+字幕+PPT+讲稿


# ---------------------------------------------------------------------------
# 媒体生成任务
# ---------------------------------------------------------------------------


class MediaGenerationJob(SQLModel, table=True):
    """媒体生成任务登记

    - 通过 `task_id` 关联统一任务中心 `TaskRecord`，不重复实现状态机
    - `idempotency_key` 用于客户端重试去重
    - `input_hash` 用于缓存命中判断（相同输入可直接复用历史产物）
    - 失败时 `error_code/error_message_safe` 必须保留原始失败原因
    """

    __tablename__ = "media_generation_jobs"
    __table_args__ = (
        UniqueConstraint("course_id", "idempotency_key", name="uq_media_job_idempotency"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(
        default_factory=lambda: "mgj_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    task_id: Optional[str] = Field(
        default=None, index=True,
        description="关联 task_service.TaskRecord.task_id",
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="关联 script_nodes.id")

    job_type: MediaGenerationJobType = Field(index=True)
    status: MediaGenerationStatus = Field(
        default=MediaGenerationStatus.PENDING, index=True,
    )

    # Provider 信息（可替换引擎的关键）
    provider_key: str = Field(default="", index=True, description="如 xfyun_tts/dh_live_mini/fake")
    provider_version: str = Field(default="", description="Provider 自报版本")

    # 输入指纹与幂等
    input_hash: str = Field(default="", index=True, description="输入参数 SHA256，用于缓存命中")
    idempotency_key: str = Field(default="", index=True)
    input_summary: str = Field(default="", description="人类可读输入摘要")
    input_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # 输出（成功后写入）
    output_object_key: Optional[str] = Field(default=None, index=True, description="产物 object_key")
    output_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # 失败信息（必须保留原始原因，禁止伪装成功）
    error_code: str = Field(default="")
    error_message_safe: str = Field(default="", description="可向前端展示的安全错误消息")

    # 关联资产
    avatar_id: Optional[str] = Field(default=None, index=True, description="若涉及数字人，关联 AvatarProfile")
    media_release_id: Optional[str] = Field(default=None, index=True, description="触发该任务的发布版本")

    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)
    finished_at: Optional[datetime] = Field(default=None)


class MediaGenerationAttempt(SQLModel, table=True):
    """媒体生成任务单次尝试

    每次重试/降级都生成一条 Attempt 记录，包含耗时、Provider 版本、失败原因。
    用于审计、质量分析与 Provider 替换演练。
    """

    __tablename__ = "media_generation_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    attempt_id: str = Field(
        default_factory=lambda: "mga_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    job_id: str = Field(index=True, description="关联 MediaGenerationJob.job_id")
    course_id: int = Field(foreign_key="courses.id", index=True)

    attempt_number: int = Field(default=1, description="第几次尝试(从1开始)")
    provider_key: str = Field(default="")
    provider_version: str = Field(default="")

    started_at: datetime = Field(default_factory=utcnow_aware)
    finished_at: Optional[datetime] = Field(default=None)
    duration_ms: Optional[int] = Field(default=None, description="本次尝试耗时")

    status: MediaGenerationStatus = Field(default=MediaGenerationStatus.RUNNING)
    error_code: str = Field(default="")
    error_message_safe: str = Field(default="")
    degraded_from_provider: Optional[str] = Field(
        default=None, description="若发生降级，记录原始 Provider",
    )

    attempt_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))


# ---------------------------------------------------------------------------
# 媒体发布版本
# ---------------------------------------------------------------------------


class MediaRelease(SQLModel, table=True):
    """媒体发布版本（不可变）

    - 每次发布形成不可变版本，修改讲稿或头像必须新建版本
    - 学生端通过 `GET /api/v1/media/course/{id}/releases/current` 获取当前激活版本
    - 旧版本被替换时标记 `superseded`，不能静默指向新文件
    - 依赖资产失效时标记 `stale`，并触发教师重新发布提示
    """

    __tablename__ = "media_releases"

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(
        default_factory=lambda: "mrel_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    version_number: int = Field(default=1, ge=1, description="课程内单调递增")
    label: str = Field(default="", max_length=200, description="教师可读版本标签")

    status: MediaReleaseStatus = Field(
        default=MediaReleaseStatus.DRAFT, index=True,
    )

    # 内容指纹（不可变）
    timeline_content_hash: str = Field(
        default="", index=True,
        description="时间轴 Cue 内容 SHA256，用于版本比对",
    )
    audio_object_key: Optional[str] = Field(default=None, index=True)
    subtitle_manifest_object_key: Optional[str] = Field(default=None)
    ppt_manifest_object_key: Optional[str] = Field(default=None)
    audio_playlist_object_key: Optional[str] = Field(default=None, index=True)
    audio_playlist_sha256: str = Field(default="", index=True)
    avatar_preset_id: Optional[str] = Field(default=None, max_length=100)

    # P2: 与音频 SHA 绑定的厂商无关数字人时间轴。它不同于形象资产包 manifest：
    # 前者描述本次讲解何时说话/可用何种 viseme，后者描述浏览器可加载的形象资源。
    avatar_cues_object_key: Optional[str] = Field(default=None)

    # 数字人 manifest（可选，未绑定时为空，学生端走兼容模式）
    avatar_binding_id: Optional[str] = Field(
        default=None, index=True,
        description="关联 CourseAvatarBinding.binding_id",
    )
    digital_human_manifest_object_key: Optional[str] = Field(default=None)

    # 播放配置
    default_playback_mode: PlaybackMode = Field(default=PlaybackMode.AUTO)
    capability_profile_id: Optional[str] = Field(
        default=None, description="关联 PlaybackCapabilityProfile.profile_id",
    )

    # 元数据
    notes: str = Field(default="", description="教师备注")
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    activated_at: Optional[datetime] = Field(default=None)
    superseded_at: Optional[datetime] = Field(default=None)
    withdrawn_at: Optional[datetime] = Field(default=None)

    release_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))


class MediaBuildBatch(SQLModel, table=True):
    """一次教师明确确认的批量媒体建设批次。"""
    __tablename__ = "media_build_batches"
    __table_args__ = (UniqueConstraint("course_id", "idempotency_key", name="uq_media_batch_idempotency"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(default_factory=lambda: "mbatch_" + uuid.uuid4().hex, unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    release_id: Optional[str] = Field(default=None, index=True)
    created_by: int = Field(foreign_key="users.id")
    status: MediaBuildBatchStatus = Field(default=MediaBuildBatchStatus.PLANNED, index=True)
    idempotency_key: str = Field(default="", index=True)
    node_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    node_snapshot: list = Field(default_factory=list, sa_column=Column(JSON))
    estimate: dict = Field(default_factory=dict, sa_column=Column(JSON))
    voice_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    confirmed_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    error_code: str = Field(default="")
    error_message_safe: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class MediaReleaseItem(SQLModel, table=True):
    """课程级播放清单中的不可变知识点媒体条目。"""
    __tablename__ = "media_release_items"
    __table_args__ = (UniqueConstraint("release_id", "node_id", name="uq_media_release_item_node"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    item_id: str = Field(default_factory=lambda: "mrit_" + uuid.uuid4().hex, unique=True, index=True)
    release_id: str = Field(index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: int = Field(foreign_key="script_nodes.id", index=True)
    outline_node_id: Optional[str] = Field(default=None, index=True)
    order_index: int = Field(default=0, index=True)
    script_hash: str = Field(default="", index=True)
    status: str = Field(default="pending", index=True)
    audio_object_key: Optional[str] = Field(default=None)
    audio_sha256: str = Field(default="")
    duration_ms: int = Field(default=0)
    subtitle_manifest_object_key: Optional[str] = Field(default=None)
    avatar_cues_object_key: Optional[str] = Field(default=None)
    ppt_mapping_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    tts_job_id: Optional[str] = Field(default=None, index=True)
    error_code: str = Field(default="")
    error_message_safe: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class MediaReleaseCue(SQLModel, table=True):
    """发布版本冻结的时间轴 Cue 快照

    独立于编辑中的 MediaTimelineCue，确保学生端始终看到发布时的完整状态。
    Cue 内容不可变，仅随新版本发布新增。
    """

    __tablename__ = "media_release_cues"

    id: Optional[int] = Field(default=None, primary_key=True)
    release_cue_id: str = Field(
        default_factory=lambda: "mrc_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    release_id: str = Field(index=True, description="关联 MediaRelease.release_id")
    course_id: int = Field(foreign_key="courses.id", index=True)
    node_id: int = Field(foreign_key="script_nodes.id", index=True)

    cue_index: int = Field(description="在节点内的序号")
    start_time: float = Field(description="起始时间(秒，相对节点音频/视频)")
    end_time: float = Field(description="结束时间(秒)")

    cue_type: str = Field(default="narration", index=True)
    ppt_page: Optional[int] = Field(default=None)
    subtitle_text: str = Field(default="")
    script_reference: Optional[str] = Field(default=None)

    audio_object_key: Optional[str] = Field(default=None)
    video_object_key: Optional[str] = Field(default=None)

    cue_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))


# ---------------------------------------------------------------------------
# 播放能力配置
# ---------------------------------------------------------------------------


class PlaybackCapabilityProfile(SQLModel, table=True):
    """播放能力配置与实测结果

    描述自动/低资源/兼容三档模式的启用条件、推荐参数与历史实测数据。
    前端读取本表后做能力探测，决定初始化哪种模式。
    """

    __tablename__ = "playback_capability_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: str = Field(
        default_factory=lambda: "pcp_" + uuid.uuid4().hex,
        unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    name: str = Field(default="", max_length=100, description="配置名称")
    mode: PlaybackMode = Field(index=True)

    # 启用条件（前端探测后比对）
    min_browser_version: Optional[str] = Field(default=None, description="最低浏览器版本")
    requires_hw_accel: bool = Field(default=False, description="是否要求硬件加速")
    min_device_memory_gb: Optional[float] = Field(default=None, description="最低设备内存(GB)")

    # 推荐参数
    target_resolution: Optional[str] = Field(default=None, description="目标分辨率(如 720p)")
    target_fps: Optional[int] = Field(default=None, description="目标帧率")
    max_initial_load_ms: Optional[int] = Field(default=None, description="首屏最大加载时间")

    # 实测结果（设备样本累积）
    measured_avg_fps: Optional[float] = Field(default=None)
    measured_init_ms: Optional[int] = Field(default=None)
    measured_drop_rate: Optional[float] = Field(default=None, description="掉帧率 0..1")
    measurement_notes: str = Field(default="")

    is_active: bool = Field(default=True, index=True)
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)

    profile_metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
