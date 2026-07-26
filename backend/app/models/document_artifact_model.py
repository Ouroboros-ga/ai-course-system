from __future__ import annotations

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from typing import Optional
from datetime import datetime

from app.core.time_utils import utcnow_naive


class DocumentArtifact(SQLModel, table=True):
    """文档产物持久化表：替代进程内 document_cache 字典，重启不丢失"""

    __tablename__ = "document_artifacts"

    id: Optional[int] = Field(default=None, primary_key=True)
    document_id: str = Field(unique=True, index=True, description="上传时生成的文档ID")
    course_id: int = Field(foreign_key="courses.id", index=True)
    file_name: str = Field(description="原始文件名")
    mime_type: str = Field(default="")
    parse_info: dict = Field(default={}, sa_column=Column(JSON), description="解析状态信息")
    created_at: datetime = Field(default_factory=utcnow_naive)
