from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time_utils import utcnow_aware


class PlatformIntegrationConfig(SQLModel, table=True):
    """Encrypted, versioned configuration for server-side integrations."""

    __tablename__ = "platform_integration_configs"
    __table_args__ = (UniqueConstraint("integration_key", name="uq_platform_integration_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    integration_key: str = Field(index=True, max_length=32)
    provider: str = Field(default="", max_length=64)
    base_url: str = Field(default="", max_length=500)
    model_name: str = Field(default="", max_length=200)
    encrypted_api_key: str = Field(default="")
    api_key_last4: str = Field(default="", max_length=4)
    extra_config: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False, default=dict))
    enabled: bool = Field(default=False)
    version: int = Field(default=1)
    health_status: str = Field(default="unknown", max_length=32)
    health_message: str = Field(default="", max_length=500)
    last_checked_at: Optional[datetime] = Field(default=None)
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow_aware)
    updated_at: datetime = Field(default_factory=utcnow_aware)


class PlatformAdminAuditEvent(SQLModel, table=True):
    __tablename__ = "platform_admin_audit_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor_user_id: int = Field(index=True, foreign_key="users.id")
    action: str = Field(index=True, max_length=64)
    target_type: str = Field(default="", max_length=64)
    target_id: str = Field(default="", max_length=128)
    audit_metadata: dict = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON, nullable=False, default=dict),
    )
    created_at: datetime = Field(default_factory=utcnow_aware, index=True)
