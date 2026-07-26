"""统一任务中心领域模型（阶段0）。

承载 OCR、解析、图谱构建、导入、媒体生成、实验运行、外部同步等长任务。
设计要点：
- 公开 task_id (UUID)，不暴露自增主键；
- 任务必须绑定 owner_user_id 与可选 course_id，跨课程隔离；
- 状态机：pending → running → succeeded | failed | cancelled | partial_success；
- task_events 记录状态流转与进度，前端可轮询/SSE；
- task_resource_links 记录任务关联的资源（课程、文档、节点等），删除资源时可定位影响；
- idempotency_keys 支持客户端重试，相同 key + user 在窗口期内返回同一任务；
- schema_migration_records 为后续版本化迁移机制做底座（替代散落的 ALTER 脚本）。

这些表只承载任务调度元数据，不保存原始学习内容、认知证据或学生作答；
任何 LLM/OCR/Agent 输出仍是候选或带来源的辅助结果，不绕过教师审核。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_naive


# ---------------------------------------------------------------------------
# schema_migration_records：版本化迁移底座
# ---------------------------------------------------------------------------


class SchemaMigrationRecord(SQLModel, table=True):
    """受版本控制的数据库迁移记录。

    替代散落在 db_migrator.py 中的 ALTER 脚本，提供预检/回滚/审计的统一账本。
    每次迁移必须记录 batch_id、applied_at、status、回滚说明与依赖外部条件。
    """

    __tablename__ = "schema_migration_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True, max_length=128, description="唯一迁移批次标识")
    name: str = Field(max_length=256, description="人类可读的迁移名称")
    applied_at: datetime = Field(default_factory=utcnow_naive, index=True)
    status: str = Field(default="applied", max_length=32, description="applied|rolled_back|failed")
    rollback_notes: str = Field(default="", description="回滚边界与说明")
    preflight_ok: bool = Field(default=True, description="预检是否通过")
    applied_rows: int = Field(default=0, description="影响的行数（用于审计）")
    operator_user_id: Optional[int] = Field(default=None, description="执行迁移的操作员")
    created_at: datetime = Field(default_factory=utcnow_naive)


# ---------------------------------------------------------------------------
# tasks：任务主体
# ---------------------------------------------------------------------------


class TaskRecord(SQLModel, table=True):
    """统一长任务记录。"""

    __tablename__ = "tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, max_length=64, description="公开 UUID")
    task_type: str = Field(index=True, max_length=64, description="document_parse|graph_ingest|media_gen|...")
    status: str = Field(default="pending", index=True, max_length=32,
                        description="pending|running|succeeded|failed|cancelled|partial_success")
    stage: str = Field(default="", max_length=64, description="当前阶段标签，如 ocr/parse/index")
    progress: int = Field(default=0, description="0-100 整数百分比")
    owner_user_id: int = Field(index=True, description="创建者用户 ID")
    course_id: Optional[int] = Field(default=None, index=True, description="课程隔离键")
    node_id: Optional[int] = Field(default=None, description="关联知识点节点")
    input_summary: str = Field(default="", description="输入摘要，不含原始大对象")
    input_payload: str = Field(default="{}", description="JSON: 结构化输入参数")
    result_ref: str = Field(default="", description="结果引用，如 object_key/URL/记录 ID")
    result_data: str = Field(default="{}", description="JSON: 结构化结果摘要")
    error_code: str = Field(default="", max_length=64)
    error_message: str = Field(default="")
    retryable: bool = Field(default=True)
    acknowledged: bool = Field(default=False, description="用户是否已确认已读/已处理")
    acknowledged_at: Optional[datetime] = Field(default=None)
    parent_task_id: Optional[str] = Field(default=None, index=True, description="父任务 UUID（子任务编排）")
    idempotency_key: Optional[str] = Field(default=None, index=True, description="客户端幂等键")
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)
    updated_at: datetime = Field(default_factory=utcnow_naive, index=True)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)


# ---------------------------------------------------------------------------
# task_events：任务事件流
# ---------------------------------------------------------------------------


class TaskEventRecord(SQLModel, table=True):
    """任务事件序列，用于 /tasks/{id}/events 轮询或 SSE。"""

    __tablename__ = "task_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, max_length=64, description="关联 TaskRecord.task_id")
    event_type: str = Field(max_length=64,
                            description="created|started|progress|succeeded|failed|cancelled|retried|acknowledged")
    stage: str = Field(default="", max_length=64)
    progress: Optional[int] = Field(default=None)
    message: str = Field(default="")
    error_code: str = Field(default="", max_length=64)
    event_data: str = Field(default="{}", description="JSON: 结构化事件负载")
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)


# ---------------------------------------------------------------------------
# task_resource_links：任务关联资源
# ---------------------------------------------------------------------------


class TaskResourceLinkRecord(SQLModel, table=True):
    """任务关联的资源清单。

    删除资源时通过此表定位受影响任务；软删除资源时仍保留链接以便恢复。
    """

    __tablename__ = "task_resource_links"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, max_length=64)
    resource_kind: str = Field(max_length=64,
                               description="course|document|node|question|experiment|media|release|...")
    resource_id: str = Field(max_length=128, description="资源标识（UUID 或稳定 ID）")
    relation: str = Field(default="input", max_length=32,
                          description="input|output|affected|reference")
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)


# ---------------------------------------------------------------------------
# idempotency_keys：幂等键
# ---------------------------------------------------------------------------


class IdempotencyKeyRecord(SQLModel, table=True):
    """客户端幂等键，避免重复创建任务。

    相同 (user_id, idempotency_key) 在窗口期内返回同一 task_id；
    过期后允许复用，但保留历史记录以便审计。
    """

    __tablename__ = "idempotency_keys"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    idempotency_key: str = Field(index=True, max_length=128)
    task_id: str = Field(index=True, max_length=64, description="关联 TaskRecord.task_id")
    request_payload_hash: str = Field(default="", max_length=128, description="请求体哈希，校验一致性")
    expires_at: datetime = Field(index=True, description="幂等窗口过期时间")
    created_at: datetime = Field(default_factory=utcnow_naive)
