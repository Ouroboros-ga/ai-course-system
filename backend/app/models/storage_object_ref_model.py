"""G5 对象存储引用登记表（GC 与回读校验的唯一真实来源）

设计要点：
- `StorageObjectRef` 记录每个 `object_key` 在 Provider 中的存在状态与引用来源。
- GC 决策只依据此表：`soft_deleted_at` 早于保留期且 `last_verify_status != "missing"`
  的对象可被回收。
- 回读校验只填入 `last_verified_at`/`last_verify_status`，不修改对象本身。
- 引用来源用 `referenced_by`（逗号分隔的来源表名）登记，便于审计；不强求外部
  代码每次写入对象时都调用登记接口，reconcile 流程会扫描全量 DB 引用补齐。
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, SQLModel


class StorageVerifyStatus(str, Enum):
    """回读校验状态"""

    OK = "ok"                    # SHA256 与 refs 表一致
    MISSING = "missing"          # Provider 中已不存在
    HASH_MISMATCH = "hash_mismatch"  # SHA256 不一致
    NOT_VERIFIED = "not_verified"


class StorageObjectRef(SQLModel, table=True):
    """对象存储引用登记

    一行 = 一个 object_key 的当前状态。GC、迁移、回读校验都以此表为账本。
    """

    __tablename__ = "storage_object_refs"

    id: Optional[int] = Field(default=None, primary_key=True)
    object_key: str = Field(unique=True, index=True, description="抽象存储键")
    content_sha256: str = Field(default="", index=True, description="登记时的 SHA256")
    size_bytes: int = Field(default=0, description="登记时的大小")
    mime_type: str = Field(default="", description="登记时的 MIME 类型")
    source_backend: str = Field(default="", description="登记时的存储后端 local/s3/minio/oss")
    referenced_by: str = Field(
        default="",
        description="引用来源表名（逗号分隔），例如 source_material_versions,media_assets",
    )
    soft_deleted_at: Optional[datetime] = Field(
        default=None,
        index=True,
        description="标记为软删除的时间；非空且超过保留期才会被 GC 真正删除",
    )
    soft_delete_reason: str = Field(default="", description="软删除原因")
    last_verified_at: Optional[datetime] = Field(default=None, description="最近一次回读校验时间")
    last_verify_status: str = Field(
        default=StorageVerifyStatus.NOT_VERIFIED.value,
        index=True,
        description="ok/missing/hash_mismatch/not_verified",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
