"""阶段4 课程材料解析、Evidence、Citation 与图谱候选 持久化模型

将"上传材料 → 异步解析 → DocumentIR 块 → Evidence 片段 → 学生可读 Citation → 图谱候选批次"
固化为可重放、可审计、可降级的流水线。

设计要点：
- `DocumentParseRun` 记录单次解析任务（绑定 TaskRecord.task_id），承载 stale 策略与影响范围。
- `DocumentBlock` 是 DocumentIR 的最小可引用块（页码、bbox、文本段）。
- `EvidenceSpan` 是从块中抽取的细粒度证据片段，可与 `CourseEvidenceRecord`（教师确认态）共存：
  教师确认后才升级为正式 `CourseEvidenceRecord`，未确认前仅为候选。
- `EvidenceCitation` 是面向学生端"原文引用"的稳定 ViewModel 持久化，支持 stale/orphaned 状态。
- `EvidenceRenderAsset` 缓存页面图/区域图，避免每次请求重新渲染。
- `GraphCandidateBatch` 跟踪一次 AI 图谱候选生成批次（节点/关系候选），与教师审核流关联。
- `GraphReleaseLink` 将已发布 GraphSnapshot 与课程 release 绑定，支持 release 回滚时图谱联动。

所有表按 course_id 严格隔离，绝不跨课程暴露。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, ForeignKeyConstraint, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


# ---------------------------------------------------------------------------
# 解析运行
# ---------------------------------------------------------------------------


class ParseRunStatus(str, Enum):
    """解析运行状态机：pending → running → succeeded/failed/cancelled/partial_success"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # 后端重启扫尾：遗留 running 的解析运行标记为 interrupted，
    # 与 TaskRecord.status 一致；可重新解析，不是业务终态成功。
    INTERRUPTED = "interrupted"
    PARTIAL_SUCCESS = "partial_success"


class StaleStrategy(str, Enum):
    """重解析时旧 Evidence/Citation 的处理策略"""
    MARK_STALE = "mark_stale"          # 标记 stale，仍可追溯历史
    ORPHAN = "orphan"                  # 标记 orphaned，仅保留历史
    DELETE = "delete"                  # 物理删除（需更高权限，默认不使用）


class ParsePipeline(str, Enum):
    """解析流水线类型"""
    OCR_ONLY = "ocr_only"              # 仅 OCR
    DOCLING = "docling"                # Docling DocumentIR
    FULL = "full"                      # OCR + DocumentIR + Evidence + 图谱候选


class DocumentParseRun(SQLModel, table=True):
    """课程材料版本的单次解析运行

    - 一个 source_material_version 可有多次解析运行（重解析场景）
    - 重解析时旧运行不会删除，新运行引用 prev_run_id 形成链
    - 旧 Evidence 按 stale_strategy 处理
    """

    __tablename__ = "document_parse_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(default_factory=lambda: "dpr_" + __import__("uuid").uuid4().hex,
                        unique=True, index=True, description="公开运行ID")
    course_id: int = Field(foreign_key="courses.id", index=True)
    material_id: str = Field(index=True, description="关联 SourceMaterial.material_id")
    material_version_id: Optional[str] = Field(default=None, index=True,
                                               description="关联 SourceMaterialVersion.version_id")
    document_id: Optional[str] = Field(default=None, index=True,
                                       description="关联 DocumentArtifact.document_id")
    document_ir_version_id: Optional[str] = Field(
        default=None,
        index=True,
        description="本次运行产出的 Canonical DocumentIRVersion；失败运行为空",
    )
    task_id: Optional[str] = Field(default=None, index=True,
                                   description="关联 TaskRecord.task_id")
    prev_run_id: Optional[str] = Field(default=None, description="重解析时的上一运行ID")
    pipeline: ParsePipeline = Field(default=ParsePipeline.FULL, index=True)
    status: ParseRunStatus = Field(default=ParseRunStatus.PENDING, index=True)
    stale_strategy: StaleStrategy = Field(default=StaleStrategy.MARK_STALE)
    affected_evidence_count: int = Field(default=0, description="本次运行影响的旧证据数")
    reparse_applied: bool = Field(
        default=False,
        index=True,
        description="重解析替换是否已由教师确认并应用；首次解析恒为 false",
    )
    parse_profile: str = Field(
        default="standard",
        max_length=40,
        index=True,
        description="standard|high_quality_ocr; immutable parse configuration label",
    )
    reparse_scope: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="Explicit page/slide scope and agent request reference",
    )
    block_count: int = Field(default=0)
    evidence_span_count: int = Field(default=0)
    graph_candidate_count: int = Field(default=0)
    error_code: str = Field(default="")
    error_message: str = Field(default="")
    initiated_by: int = Field(foreign_key="users.id")
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 文档块（DocumentIR 最小可引用单元）
# ---------------------------------------------------------------------------


class BlockType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    LIST_ITEM = "list_item"
    TABLE_CELL = "table_cell"
    FIGURE_CAPTION = "figure_caption"
    CODE = "code"


class DocumentBlock(SQLModel, table=True):
    """文档块：解析产物，可被 EvidenceSpan 引用

    块的内容哈希 `content_hash` 用于重解析时检测内容是否变化。
    """

    __tablename__ = "document_blocks"
    __table_args__ = (
        # A canonical source locator is stable across reparses.  The immutable
        # IR version supplies the scope that makes a projected row unique.
        UniqueConstraint("document_ir_version_id", "block_id", name="uq_document_blocks_ir_block"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    block_id: str = Field(default_factory=lambda: "blk_" + __import__("uuid").uuid4().hex,
                          index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    run_id: str = Field(foreign_key="document_parse_runs.run_id", index=True)
    document_id: Optional[str] = Field(default=None, index=True)
    unit_id: Optional[str] = Field(
        default=None,
        index=True,
        description="Canonical DocumentIR 的稳定 unit_id",
    )
    document_ir_version_id: Optional[str] = Field(
        default=None,
        index=True,
        description="首次投影该块的 DocumentIRVersion；历史版本以 DocumentIRVersion JSON 为准",
    )
    page_number: int = Field(default=0, index=True, description="1-based 页码")
    block_type: BlockType = Field(default=BlockType.TEXT, index=True)
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON),
                                 description="{x,y,w,h} 页面坐标，可选")
    text: str = Field(default="", description="块文本内容")
    char_start: int = Field(default=0, description="页内字符起始偏移")
    char_end: int = Field(default=0, description="页内字符结束偏移")
    content_hash: str = Field(default="", index=True, description="块内容哈希")
    order_index: int = Field(default=0, description="页内顺序")
    # Step 3 解析溯源：组合式解析（原生文本 + OCR）必须保留来源/坐标/置信度/版本/材料
    material_version_id: Optional[str] = Field(
        default=None, index=True,
        description="产出该块的 SourceMaterialVersion.version_id（解析溯源）",
    )
    page_or_slide: int = Field(
        default=0, index=True,
        description="通用页/幻灯片序号（PPTX=slide，PDF/image=page），与 page_number 对齐但语义更广",
    )
    source_kind: str = Field(
        default="", max_length=32, index=True,
        description="native|ocr|reconciled：块文本来源（原生解析或 OCR 补充或合并）",
    )
    confidence: float = Field(default=0.0, description="来源置信度 0..1（OCR 块）")
    provider_version: str = Field(
        default="", max_length=64,
        description="产出该块的 Provider 版本（如 paddleocr 2.7 / pdfplumber 0.11）",
    )
    heading_level: Optional[int] = Field(default=None, index=True)
    semantic_role: str = Field(default="", max_length=40, index=True)
    style_hints: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    parent_block_id: Optional[str] = Field(default=None, index=True)
    reading_order: int = Field(default=0)
    visual_description: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# Canonical DocumentIR version and downstream projections
# ---------------------------------------------------------------------------


class DocumentIRVersion(SQLModel, table=True):
    """Immutable, versioned canonical parse artifact for one parse run.

    The JSON in object storage is authoritative.  Relational rows such as
    ``DocumentBlock`` and ``EvidenceAnchor`` are query projections and never
    replace this artifact.  A source material version can therefore keep every
    historical parse without overwriting the raw source or a prior IR.
    """

    __tablename__ = "document_ir_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    ir_version_id: str = Field(
        default_factory=lambda: "dirv_" + __import__("uuid").uuid4().hex,
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    material_version_id: Optional[str] = Field(default=None, index=True)
    run_id: str = Field(foreign_key="document_parse_runs.run_id", unique=True, index=True)
    document_id: str = Field(index=True)
    artifact_id: str = Field(index=True)
    source_sha256: str = Field(default="", index=True)
    schema_version: str = Field(default="document-ir/1.0")
    object_key: str = Field(default="", description="Immutable canonical JSON object key")
    content_hash: str = Field(default="", index=True)
    parser_versions: dict = Field(default_factory=dict, sa_column=Column(JSON))
    quality: dict = Field(default_factory=dict, sa_column=Column(JSON))
    quality_verdict: str = Field(default="", index=True)
    parse_outcome: str = Field(
        default="",
        index=True,
        description="native_complete|native_with_ocr|partial_success|manual_review_required|unsupported_visual_structure",
    )
    needs_review: bool = Field(default=False, index=True)
    warning_count: int = Field(default=0)
    prev_ir_version_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


class EvidenceAnchor(SQLModel, table=True):
    """Stable source span projected from a canonical DocumentIR block.

    ``EvidenceSpan`` remains the teacher-review compatibility projection.  New
    retrieval and citation builders must use this anchor identity instead of a
    truncated, database-generated text snippet.
    """

    __tablename__ = "evidence_anchors"
    __table_args__ = (
        UniqueConstraint("ir_version_id", "block_id", "char_start", "char_end", name="uq_evidence_anchor_span"),
        ForeignKeyConstraint(
            ["ir_version_id", "block_id"],
            ["document_blocks.document_ir_version_id", "document_blocks.block_id"],
            name="fk_evidence_anchors_ir_block",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    anchor_id: str = Field(
        default_factory=lambda: "ea_" + __import__("uuid").uuid4().hex,
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    ir_version_id: str = Field(foreign_key="document_ir_versions.ir_version_id", index=True)
    run_id: str = Field(foreign_key="document_parse_runs.run_id", index=True)
    document_id: str = Field(index=True)
    unit_id: Optional[str] = Field(default=None, index=True)
    block_id: str = Field(index=True)
    page_or_slide: Optional[int] = Field(default=None, index=True)
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    text: str = Field(default="")
    content_hash: str = Field(default="", index=True)
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    provenance: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


class RetrievalChunk(SQLModel, table=True):
    """Deterministic, evidence-closed retrieval input derived from anchors."""

    __tablename__ = "retrieval_chunks"

    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: str = Field(unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    ir_version_id: str = Field(foreign_key="document_ir_versions.ir_version_id", index=True)
    document_id: str = Field(index=True)
    unit_id: Optional[str] = Field(default=None, index=True)
    block_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    anchor_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    text: str = Field(default="")
    content_hash: str = Field(default="", index=True)
    status: str = Field(default="draft", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


class RetrievalIndexSnapshot(SQLModel, table=True):
    """Versioned course retrieval index assembled from Canonical chunks.

    A parse creates a candidate snapshot.  Only one snapshot per course may
    be active, and a reparse switches it only through the explicit adopt
    operation.  The database retriever uses this row as its formal index
    boundary rather than treating every chunk projection as immediately live.
    """

    __tablename__ = "retrieval_index_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: str = Field(
        default_factory=lambda: "ris_" + __import__("uuid").uuid4().hex,
        unique=True,
        index=True,
    )
    course_id: int = Field(foreign_key="courses.id", index=True)
    ir_version_id: str = Field(
        foreign_key="document_ir_versions.ir_version_id", unique=True, index=True,
    )
    document_id: str = Field(index=True)
    status: str = Field(default="candidate", index=True, description="candidate|active|superseded")
    chunk_count: int = Field(default=0)
    content_hash: str = Field(default="", index=True)
    activated_at: Optional[datetime] = Field(default=None)
    superseded_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# Evidence 片段（候选态）
# ---------------------------------------------------------------------------


class EvidenceSpanStatus(str, Enum):
    """候选证据状态"""
    CANDIDATE = "candidate"        # AI 抽取，待教师确认
    CONFIRMED = "confirmed"        # 教师已确认（升级为 CourseEvidenceRecord）
    REJECTED = "rejected"          # 教师拒绝
    STALE = "stale"                # 课件重解析后标记
    ORPHANED = "orphaned"          # 课件删除后标记


class EvidenceSpan(SQLModel, table=True):
    """证据片段：从 DocumentBlock 中抽取的细粒度证据

    与 CourseEvidenceRecord 的关系：
    - EvidenceSpan 是候选态，AI 抽取；
    - 教师确认后，对应 EvidenceSpan.status=confirmed，并生成正式 CourseEvidenceRecord；
    - 学生端只能看到 confirmed 的证据（通过 EvidenceCitation 暴露）。
    """

    __tablename__ = "evidence_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ir_version_id", "block_id"],
            ["document_blocks.document_ir_version_id", "document_blocks.block_id"],
            name="fk_evidence_spans_ir_block",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    span_id: str = Field(default_factory=lambda: "es_" + __import__("uuid").uuid4().hex,
                         unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    run_id: str = Field(foreign_key="document_parse_runs.run_id", index=True)
    ir_version_id: Optional[str] = Field(
        default=None,
        foreign_key="document_ir_versions.ir_version_id",
        index=True,
        description="Canonical IR version that scopes block_id; null only for legacy projections",
    )
    block_id: str = Field(index=True)
    document_id: Optional[str] = Field(default=None, index=True)
    page_number: int = Field(default=0, index=True)
    text_snippet: str = Field(default="", description="证据文本片段")
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    content_hash: str = Field(default="", index=True)
    status: EvidenceSpanStatus = Field(default=EvidenceSpanStatus.CANDIDATE, index=True)
    confirmed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    confirmed_at: Optional[datetime] = Field(default=None)
    rejected_by: Optional[int] = Field(default=None, foreign_key="users.id")
    rejected_at: Optional[datetime] = Field(default=None)
    reject_reason: str = Field(default="")
    stale_reason: str = Field(default="")
    stale_at: Optional[datetime] = Field(default=None)
    linked_node_ids: list = Field(default_factory=list, sa_column=Column(JSON),
                                  description="关联的知识节点ID列表")
    linked_evidence_id: Optional[str] = Field(default=None, index=True,
                                              description="确认后关联的 CourseEvidenceRecord.evidence_id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 学生可读 Citation ViewModel
# ---------------------------------------------------------------------------


class CitationStatus(str, Enum):
    """学生端 Citation 状态"""
    EXACT = "exact"                # 精确引用
    APPROXIMATE = "approximate"    # 近似匹配
    SOURCE_UPDATED = "source_updated"  # 来源已更新
    SOURCE_INVALID = "source_invalid"  # 来源失效（orphaned）
    TEACHER_ONLY = "teacher_only"      # 仅教师可见


class EvidenceCitation(SQLModel, table=True):
    """学生端"原文引用"ViewModel 持久化

    学生端统一命名为"原文引用"，不显示内部术语 Evidence Viewer。
    状态严格区分：exact / approximate / source_updated / source_invalid / teacher_only。
    重解析/删除后历史引用返回 stale/orphaned，不静默指向新内容。
    """

    __tablename__ = "evidence_citations"

    id: Optional[int] = Field(default=None, primary_key=True)
    citation_id: str = Field(default_factory=lambda: "cit_" + __import__("uuid").uuid4().hex,
                             unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    evidence_id: Optional[str] = Field(default=None, index=True,
                                       description="关联 CourseEvidenceRecord.evidence_id")
    span_id: Optional[str] = Field(default=None, index=True,
                                   description="关联 EvidenceSpan.span_id")
    document_id: Optional[str] = Field(default=None, index=True)
    node_id: Optional[int] = Field(default=None, index=True, description="关联知识点")
    source_file: str = Field(default="", description="来源文件名")
    source_type: str = Field(default="document", description="ppt/textbook/handout/lesson_plan")
    page_number: int = Field(default=0, index=True)
    page_range: Optional[dict] = Field(default=None, sa_column=Column(JSON),
                                       description="{start,end} 跨页引用")
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    text_snippet: str = Field(default="")
    char_start: int = Field(default=0)
    char_end: int = Field(default=0)
    version: int = Field(default=1, description="引用版本")
    status: CitationStatus = Field(default=CitationStatus.EXACT, index=True)
    stale_reason: str = Field(default="")
    stale_at: Optional[datetime] = Field(default=None)
    student_visible: bool = Field(default=True, description="是否对学生可见")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 渲染资源（页面图/区域图缓存）
# ---------------------------------------------------------------------------


class RenderAssetType(str, Enum):
    PAGE_IMAGE = "page_image"
    REGION_IMAGE = "region_image"
    THUMBNAIL = "thumbnail"


class EvidenceRenderAsset(SQLModel, table=True):
    """Evidence 渲染资源缓存

    缓存页面图、区域图，避免每次请求重新渲染。
    通过 object_key 抽象本地/OSS 存储位置。
    """

    __tablename__ = "evidence_render_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    asset_id: str = Field(default_factory=lambda: "era_" + __import__("uuid").uuid4().hex,
                          unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    run_id: Optional[str] = Field(
        default=None, foreign_key="document_parse_runs.run_id", index=True,
        description="Canonical parse run that rendered this page; scopes assets when document_id is absent",
    )
    citation_id: Optional[str] = Field(default=None, foreign_key="evidence_citations.citation_id",
                                       index=True)
    document_id: Optional[str] = Field(default=None, index=True)
    page_number: int = Field(default=0, index=True)
    asset_type: RenderAssetType = Field(default=RenderAssetType.PAGE_IMAGE, index=True)
    object_key: str = Field(default="", description="本地/OSS 对象键")
    mime_type: str = Field(default="image/png")
    width: int = Field(default=0)
    height: int = Field(default=0)
    bbox: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    content_hash: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 图谱候选批次
# ---------------------------------------------------------------------------


class CandidateBatchStatus(str, Enum):
    """图谱候选批次状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL_SUCCESS = "partial_success"
    SUPERSEDED = "superseded"  # 被新批次替代


class GraphCandidateBatch(SQLModel, table=True):
    """图谱候选批次：一次 AI 图谱生成运行

    - 绑定 DocumentParseRun，由解析流水线触发
    - 产出节点/关系候选，进入教师审核流（已有 GraphNodeReview）
    - 教师审核通过后，候选升级为正式 GraphSnapshot
    - 新批次产生时旧批次标记为 superseded
    """

    __tablename__ = "graph_candidate_batches"

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(default_factory=lambda: "gcb_" + __import__("uuid").uuid4().hex,
                          unique=True, index=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    parse_run_id: Optional[str] = Field(default=None, foreign_key="document_parse_runs.run_id",
                                        index=True)
    task_id: Optional[str] = Field(default=None, index=True,
                                   description="关联 TaskRecord.task_id")
    prev_batch_id: Optional[str] = Field(default=None, description="上一批次")
    status: CandidateBatchStatus = Field(default=CandidateBatchStatus.PENDING, index=True)
    node_candidate_count: int = Field(default=0)
    relation_candidate_count: int = Field(default=0)
    accepted_count: int = Field(default=0)
    rejected_count: int = Field(default=0)
    needs_review_count: int = Field(default=0)
    node_candidates: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Teacher-reviewable concept candidates with source block and anchor references",
    )
    relation_candidates: list = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Teacher-reviewable typed relation candidates with source references",
    )
    snapshot_id: Optional[str] = Field(default=None, index=True,
                                       description="审核通过后生成的 GraphSnapshotRecord.snapshot_id")
    model_version: str = Field(default="graph-candidate-v1.0")
    error_code: str = Field(default="")
    error_message: str = Field(default="")
    initiated_by: int = Field(foreign_key="users.id")
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


# ---------------------------------------------------------------------------
# 图谱快照 ↔ 课程 release 关联
# ---------------------------------------------------------------------------


class GraphReleaseLink(SQLModel, table=True):
    """图谱快照与课程 release 的关联表

    - 一次课程发布（CourseRelease）绑定一个已发布 GraphSnapshot
    - release 回滚时，图谱同步回滚到对应快照（产生新激活快照而非破坏历史）
    - 保证图谱与课程内容版本一致
    """

    __tablename__ = "graph_release_links"
    __table_args__ = (
        UniqueConstraint("course_id", "release_id", name="uq_graph_release_link_per_course"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="courses.id", index=True)
    release_id: str = Field(index=True, description="关联 CourseRelease.release_id")
    snapshot_id: str = Field(index=True, description="关联 GraphSnapshotRecord.snapshot_id")
    linked_by: int = Field(foreign_key="users.id")
    linked_at: datetime = Field(default_factory=utcnow_aware)
    created_at: datetime = Field(default_factory=utcnow_aware)
