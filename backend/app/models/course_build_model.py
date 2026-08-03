"""阶段3 统一任务中心与教师课程建设工作流 持久化模型。

承载路线图 §6：
- 七步建设状态：资料(materials)→结构(structure)→讲稿(scripts)→页映射(page_mappings)→媒体(media)→校验(validate)→发布(release)
- 每步记录输入、产物、失败原因、重试和下游影响
- 教师锁定的映射/讲稿不被 AI 重跑覆盖（locked_by 字段）
- 发布前质量门禁可阻断；发布后学生只读不可变 release
- 回滚产生新激活版本而非破坏历史

所有表按 course_id 严格隔离；release 一旦 published 不可变。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, JSON, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 课程建设草稿与步骤
# ---------------------------------------------------------------------------


class BuildStepName(str, Enum):
    """七步建设步骤

    顺序：materials → structure → scripts → page_mappings → media → validate → release
    每步有 status 与 quality_gate 状态。
    """
    MATERIALS = "materials"
    STRUCTURE = "structure"
    SCRIPTS = "scripts"
    PAGE_MAPPINGS = "page_mappings"
    MEDIA = "media"
    VALIDATE = "validate"
    RELEASE = "release"


class BuildStepStatus(str, Enum):
    """单步状态"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"          # 上游失败导致阻塞
    READY_FOR_REVIEW = "ready_for_review"
    APPROVED = "approved"
    FAILED = "failed"
    LOCKED = "locked"            # 教师锁定，AI 重跑不可覆盖


class CourseBuildDraft(SQLModel, table=True):
    """课程建设草稿

    每个课程有一个活跃草稿；发布后草稿可清空或保留为下次迭代的起点。
    """

    __tablename__ = "course_build_drafts"

    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: str = Field(
        default_factory=lambda: f"cbd_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 当前活跃步骤
    current_step: BuildStepName = Field(default=BuildStepName.MATERIALS, index=True)
    overall_status: str = Field(default="not_started", description="not_started/in_progress/blocked/ready_for_release/released")

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class CourseBuildStep(SQLModel, table=True):
    """课程建设单步记录

    每步记录输入摘要、产物引用、失败原因、重试次数、教师锁定状态。
    教师锁定后 AI 重跑不可覆盖（locked_by 非空时跳过）。
    """

    __tablename__ = "course_build_steps"
    __table_args__ = (
        UniqueConstraint("course_id", "step_name", name="uq_course_build_step"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    step_id: str = Field(
        default_factory=lambda: "cbs_" + uuid.uuid4().hex,
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    draft_id: Optional[str] = Field(default=None, index=True)

    step_name: BuildStepName = Field(index=True)
    status: BuildStepStatus = Field(default=BuildStepStatus.NOT_STARTED, index=True)

    # 输入与产物
    input_summary: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_ref: str = Field(default="", description="产物引用（如 task_id / artifact_id）")
    output_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON), description="产物快照")

    # 失败与重试
    error_code: str = Field(default="")
    error_message: str = Field(default="")
    retry_count: int = Field(default=0)

    # 教师锁定
    locked_by: Optional[int] = Field(default=None, foreign_key="users.id")
    locked_at: Optional[datetime] = Field(default=None)
    lock_reason: str = Field(default="")

    # 质量门禁
    quality_gate_passed: bool = Field(default=False)
    quality_gate_details: dict = Field(default_factory=dict, sa_column=Column(JSON))

    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 源材料与版本
# ---------------------------------------------------------------------------


class MaterialStatus(str, Enum):
    """源材料状态"""
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    SUPERSEDED = "superseded"    # 被新版本替代


class SourceMaterial(SQLModel, table=True):
    """课程建设源材料

    教师上传的课件、文档、视频等原始材料。
    每个材料可有多个版本；解析基于版本执行。
    """

    __tablename__ = "source_materials"

    id: Optional[int] = Field(default=None, primary_key=True)
    material_id: str = Field(
        default_factory=lambda: f"sm_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 材料信息
    name: str = Field(default="", description="材料名称")
    material_type: str = Field(default="document", description="document|slide|video|audio|other")
    material_role: str = Field(default="reference", description="primary_courseware|textbook|syllabus|experiment_guide|exercise_bank|reference")
    include_in_course_corpus: bool = Field(
        default=True,
        description="教师是否把当前材料纳入下一次课程语料快照；失败材料须重试或显式排除",
    )
    source_kind: str = Field(default="upload", description="upload|fanya_sync|reference")

    # 当前版本
    current_version_id: Optional[str] = Field(default=None, description="当前活跃版本 ID")

    # 状态
    status: MaterialStatus = Field(default=MaterialStatus.UPLOADED, index=True)

    # 归属
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class SourceMaterialVersion(SQLModel, table=True):
    """源材料版本

    每次重新上传或解析生成新版本；旧版本标记为 superseded。
    解析任务基于版本执行，确保重解析不会静默指向错误内容。
    """

    __tablename__ = "source_material_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    version_id: str = Field(
        default_factory=lambda: f"smv_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    material_id: str = Field(index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 版本内容
    version: int = Field(default=1)
    file_path: str = Field(default="", description="对象存储路径 object_key")
    file_hash: str = Field(default="", index=True, description="内容哈希")
    file_size: int = Field(default=0)
    mime_type: str = Field(default="")

    # 解析任务
    parse_task_id: Optional[str] = Field(default=None, index=True, description="解析任务 task_id")
    parse_status: MaterialStatus = Field(default=MaterialStatus.UPLOADED, index=True)
    parse_output_ref: str = Field(default="", description="解析产物引用")
    parse_error: str = Field(default="")

    is_current: bool = Field(default=True, index=True)

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 课程级材料/检索快照与编排任务
# ---------------------------------------------------------------------------


class CorpusSnapshotStatus(str, Enum):
    """A frozen set of material versions selected for course construction."""

    BUILDING = "building"
    READY = "ready"
    SUPERSEDED = "superseded"


class CourseCorpusSnapshot(SQLModel, table=True):
    """Immutable course-level view of the material versions used to build a draft.

    A parse run is a fact about one material.  This snapshot is the only
    allowed input to a course-wide outline, script, graph, or release.
    """

    __tablename__ = "course_corpus_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    corpus_snapshot_id: str = Field(
        default_factory=lambda: f"ccs_{uuid.uuid4().hex}", unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    status: CorpusSnapshotStatus = Field(default=CorpusSnapshotStatus.BUILDING, index=True)
    material_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    parse_run_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    document_ir_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    warnings: list = Field(default_factory=list, sa_column=Column(JSON))
    content_hash: str = Field(default="", index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseCorpusItem(SQLModel, table=True):
    """One material-version decision inside an immutable corpus snapshot.

    The denormalized ID lists on :class:`CourseCorpusSnapshot` remain useful
    for old readers, while this table captures the teacher-facing semantics
    (role, priority, inclusion and parse-quality warning) that the course
    builder must preserve.
    """

    __tablename__ = "course_corpus_items"
    __table_args__ = (
        UniqueConstraint("corpus_snapshot_id", "material_version_id", name="uq_corpus_item_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    corpus_snapshot_id: str = Field(index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    material_id: str = Field(index=True)
    material_version_id: str = Field(index=True)
    material_role: str = Field(default="reference", index=True)
    priority: int = Field(default=100)
    document_ir_version_id: str = Field(index=True)
    parse_run_id: str = Field(index=True)
    included: bool = Field(default=True, index=True)
    quality_warning: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseRetrievalSnapshot(SQLModel, table=True):
    """The course-scoped retrieval corpus selection.

    The table deliberately stores a *set* of material versions.  It prevents
    a later material index from replacing the course's earlier material index.
    Retrieval engines may change, but consumers keep this stable snapshot ID.
    """

    __tablename__ = "course_retrieval_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    retrieval_snapshot_id: str = Field(
        default_factory=lambda: f"crs_{uuid.uuid4().hex}", unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    corpus_snapshot_id: str = Field(index=True)
    material_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    document_ir_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    # A candidate corpus is useful to the teacher-side builder, but it is not
    # an entitlement to expose every parsed block to learners.  A ``release``
    # snapshot contains the exact reviewed chunks/anchors that were frozen at
    # publication time and is the only kind a student reader may use.
    snapshot_kind: str = Field(default="candidate", index=True, description="candidate|release")
    retrieval_chunk_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    evidence_anchor_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(default="ready", index=True, description="building|ready|superseded")
    provider_policy_version: str = Field(default="canonical-retrieval/1")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseDraftBuildStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CourseDraftBuildTask(SQLModel, table=True):
    """Course-wide construction orchestration, separate from material parsing."""

    __tablename__ = "course_draft_build_tasks"
    __table_args__ = (
        # Database-level guard for the course build lease.  Status transitions
        # release the lease when a task reaches a terminal state.
        Index(
            "uq_course_draft_build_active_course",
            "course_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    build_task_id: str = Field(
        default_factory=lambda: f"cdbt_{uuid.uuid4().hex}", unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    corpus_snapshot_id: str = Field(index=True)
    task_id: Optional[str] = Field(default=None, index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    status: CourseDraftBuildStatus = Field(default=CourseDraftBuildStatus.QUEUED, index=True)
    trigger: str = Field(default="auto_after_materials_ready")
    generation_mode: str = Field(default="initial", description="initial|proposal")
    base_outline_version_id: Optional[str] = Field(default=None, index=True)
    base_script_version_id: Optional[str] = Field(default=None, index=True)
    result_outline_version_id: Optional[str] = Field(default=None, index=True)
    result_script_version_id: Optional[str] = Field(default=None, index=True)
    result_retrieval_snapshot_id: Optional[str] = Field(default=None, index=True)
    error_code: str = Field(default="")
    error_message: str = Field(default="")
    not_before_at: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)


class CourseDraftBuildCheckpoint(SQLModel, table=True):
    """Durable, non-teacher-visible output from one completed build stage.

    Checkpoints make a long build inspectable and restartable without exposing
    a half-formed outline or script version to the teacher-facing workspace.
    The final outline/script rows are still committed only after every stage
    has passed validation.
    """

    __tablename__ = "course_draft_build_checkpoints"
    __table_args__ = (
        UniqueConstraint("build_task_id", "stage", name="uq_course_build_checkpoint_stage"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    checkpoint_id: str = Field(
        default_factory=lambda: f"cdbc_{uuid.uuid4().hex}", unique=True, index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    build_task_id: str = Field(index=True)
    corpus_snapshot_id: str = Field(index=True)
    stage: str = Field(index=True, max_length=64)
    progress: int = Field(default=0)
    status: str = Field(default="completed", max_length=32)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 质量门禁运行
# ---------------------------------------------------------------------------


class GateSeverity(str, Enum):
    """发布前检查问题严重级别。"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"          # 教师确认后可发布
    BLOCKER = "blocker"      # 不可绕过


class CourseQualityGateRun(SQLModel, table=True):
    """课程发布前检查记录。

    ``blocker`` 必须先处理；``error`` 和 ``warning`` 可由具备发布权限的
    教师明确确认后用于正式发布。每次检查均保留完整结果与确认记录。
    """

    __tablename__ = "course_quality_gate_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    gate_run_id: str = Field(
        default_factory=lambda: f"qgr_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    draft_id: Optional[str] = Field(default=None, index=True)

    # 检查结果
    checks: list = Field(default_factory=list, sa_column=Column(JSON), description="检查项列表")
    passed: bool = Field(default=False, index=True)
    blocker_count: int = Field(default=0)
    error_count: int = Field(default=0)
    warning_count: int = Field(default=0)

    # Kept for API/database compatibility with the earlier warning-only
    # confirmation flow. New callers should use teacher_confirmation_*.
    warning_override_confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    warning_override_reason: str = Field(default="")
    warning_override_at: Optional[datetime] = Field(default=None)

    # An explicit teacher acknowledgement is required for any non-blocking
    # problem (ERROR or WARNING) before this exact check result can publish.
    teacher_confirmation_confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    teacher_confirmation_reason: str = Field(default="")
    teacher_confirmation_at: Optional[datetime] = Field(default=None)

    # 关联发布
    target_release_id: Optional[str] = Field(default=None, description="目标发布 ID")

    initiated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    completed_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# 课程发布
# ---------------------------------------------------------------------------


class ReleaseStatus(str, Enum):
    """发布状态"""
    DRAFT = "draft"              # 准备中
    PUBLISHED = "published"      # 已发布，学生可读，不可变
    SUPERSEDED = "superseded"    # 被新发布替代
    ROLLED_BACK = "rolled_back"  # 被回滚（仍保留历史）


class CourseRelease(SQLModel, table=True):
    """课程发布记录

    发布的是一组一致的结构、讲稿、映射、Evidence、图谱和媒体版本。
    一旦 published 不可变；回滚产生新激活版本而非破坏历史。
    学生只读 published 状态的 release。
    """

    __tablename__ = "course_releases"

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(
        default_factory=lambda: f"cr_{uuid.uuid4().hex}",
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)

    # 版本
    version: int = Field(default=1, description="发布版本号")
    prev_release_id: Optional[str] = Field(default=None, description="前一版本 release_id")

    # 状态
    status: ReleaseStatus = Field(default=ReleaseStatus.DRAFT, index=True)
    is_active: bool = Field(default=False, index=True, description="是否为当前活跃发布")

    # 发布内容引用
    structure_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    scripts_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    page_mappings_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    media_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    graph_snapshot_ref: Optional[str] = Field(default=None, description="关联 GraphSnapshot ID")
    evidence_refs: list = Field(default_factory=list, sa_column=Column(JSON))

    # Frozen source selections. Student readers must resolve these IDs from
    # the active release, never from whichever material happened to parse last.
    material_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    document_ir_run_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    document_ir_version_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    corpus_snapshot_id: Optional[str] = Field(default=None, index=True)
    retrieval_snapshot_id: Optional[str] = Field(default=None, index=True)
    # Optional compatibility reference only.  The independent knowledge
    # bundle head, not CourseRelease, is authoritative for learner graph/RAG.
    knowledge_bundle_id: Optional[str] = Field(default=None, index=True)
    outline_version_id: Optional[str] = Field(default=None, index=True)
    script_version_id: Optional[str] = Field(default=None, index=True)

    # 发布前检查
    quality_gate_run_id: Optional[str] = Field(default=None)
    quality_gate_passed: bool = Field(default=False)
    publication_check_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    publication_issues: list = Field(default_factory=list, sa_column=Column(JSON))
    teacher_confirmation_confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    teacher_confirmation_reason: str = Field(default="")
    teacher_confirmation_at: Optional[datetime] = Field(default=None)

    # 元数据
    label: str = Field(default="")
    release_notes: str = Field(default="")
    content_hash: str = Field(default="", description="发布内容哈希，用于完整性校验")

    published_by: Optional[int] = Field(default=None, foreign_key="users.id")
    published_at: Optional[datetime] = Field(default=None)

    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)


class CourseReleaseArtifact(SQLModel, table=True):
    """课程发布产物关联

    记录每个发布包含的具体产物（材料版本、讲稿版本、映射版本等）。
    用于发布后追溯具体产物版本。
    """

    __tablename__ = "course_release_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    release_id: str = Field(index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)

    artifact_type: str = Field(default="", description="material|script|page_mapping|media|graph")
    artifact_id: str = Field(default="", description="产物 ID")
    artifact_version: int = Field(default=1)
    artifact_ref: str = Field(default="", description="产物引用路径")

    created_at: datetime = Field(default_factory=utcnow_aware)
