"""db_migrator.py — 已废弃，保留为兼容层。

DDL/DML 迁移逻辑已迁移至 Alembic revision：
- 0001_legacy_schema_baseline：完整建表（原 create_all + MIGRATIONS 字典）
- 0002_access_control_v1_backfill：Course Access 历史数据回填
- 0003_agent_log_redaction_backfill：Agent 日志脱敏（不可逆）

本模块仅保留预检函数与 rollback 工具，委托至 migration_preflight.py。
新代码应直接使用 migration_preflight 与 migration_ops CLI。

废弃路径：
- run_migrations()：不再执行任何操作，仅记录警告。
- MIGRATIONS 字典：已移除，由 alembic revision 替代。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import create_engine, inspect, text

from app.models.database import DATABASE_URL

logger = logging.getLogger(__name__)

# 保留常量以兼容现有引用
ACCESS_CONTROL_MIGRATION_BATCH = "access-control-v1"
AGENT_LOG_MIGRATION_BATCH = "agent-log-minimization-v1"


def _resolve_database_url(database_path: str | None = None) -> str:
    """动态解析数据库 URL。

    优先级：
    1. 显式传入的 database_path（转换为 sqlite:/// URL）
    2. AI_COURSE_DATABASE_URL 环境变量（部署时动态切换库）
    3. app.models.database.DATABASE_URL（模块导入时的快照）

    动态读取环境变量是为了让 migration_ops CLI 在不同数据库间切换时，
    不必重新加载本模块即可生效。
    """
    if database_path:
        return f"sqlite:///{database_path}"
    return os.environ.get("AI_COURSE_DATABASE_URL") or DATABASE_URL


# 预检函数委托至 migration_preflight
from app.common.migration_preflight import (  # noqa: E402, F401
    access_control_preflight as _ac_preflight_impl,
    agent_log_redaction_preflight as _al_preflight_impl,
)


def access_control_preflight(database_path: str | None = None) -> dict[str, Any]:
    """兼容包装：委托至 migration_preflight。

    旧接口接受 database_path（SQLite 文件路径），新接口接受 database_url。
    """
    return _ac_preflight_impl(_resolve_database_url(database_path))


def agent_log_preflight(database_path: str | None = None) -> dict[str, Any]:
    """兼容包装：委托至 migration_preflight。"""
    return _al_preflight_impl(_resolve_database_url(database_path))


def rollback_access_control_backfill(database_path: str | None = None) -> dict[str, int]:
    """删除 access-control-v1 批次创建的记录。

    部署运维命令，不由应用启动调用。
    """
    url = _resolve_database_url(database_path)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    try:
        deleted: dict[str, int] = {}
        with engine.begin() as conn:
            for table_name in (
                "platform_permission_assignments",
                "course_memberships",
                "course_capabilities",
            ):
                result = conn.execute(
                    text(f"DELETE FROM {table_name} WHERE migration_batch_id = :batch_id"),
                    {"batch_id": ACCESS_CONTROL_MIGRATION_BATCH},
                )
                deleted[table_name] = result.rowcount or 0
        return deleted
    finally:
        engine.dispose()


def rollback_agent_log_minimization(database_path: str | None = None) -> dict[str, int]:
    """删除 agent-log-minimization-v1 批次的账本记录。

    警告：原始 raw payload 已永久脱敏，无法恢复。
    """
    url = _resolve_database_url(database_path)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    try:
        inspector = inspect(engine)
        if "agent_log_migration_records" not in inspector.get_table_names():
            return {"agent_log_migration_records": 0}
        with engine.begin() as conn:
            result = conn.execute(
                text("DELETE FROM agent_log_migration_records WHERE batch_id = :batch_id"),
                {"batch_id": AGENT_LOG_MIGRATION_BATCH},
            )
            return {"agent_log_migration_records": result.rowcount or 0}
    finally:
        engine.dispose()


def run_migrations():
    """已废弃：不再执行任何迁移操作。

    迁移由部署流程显式执行 `alembic upgrade head`。
    保留此函数仅为兼容旧测试引用，调用时记录警告。
    """
    logger.warning(
        "db_migrator.run_migrations() is deprecated and is a no-op. "
        "Use 'alembic upgrade head' in the deployment flow instead."
    )


# ============================================================================
# 以下内部函数保留仅为兼容旧测试引用，新代码不应使用。
# 实际迁移逻辑在 alembic/versions/0002 和 0003 中。
# ============================================================================

def _backfill_access_control(cursor) -> int:
    """已废弃：access_control 回填逻辑已迁移至 alembic revision 0002。"""
    raise NotImplementedError(
        "access_control backfill has been migrated to alembic revision 0002. "
        "Run 'alembic upgrade head' to apply it."
    )


def _minimize_agent_logs(cursor) -> tuple[int, int]:
    """已废弃：agent log 脱敏逻辑已迁移至 alembic revision 0003。"""
    raise NotImplementedError(
        "agent log redaction has been migrated to alembic revision 0003. "
        "Run 'alembic upgrade head' to apply it."
    )
