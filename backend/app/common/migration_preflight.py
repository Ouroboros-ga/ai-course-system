"""迁移预检：无副作用的只读检查函数。

职责：
- 在执行 alembic upgrade 前检查旧库是否具备升级条件。
- 输出结构化 JSON 报告，供 migration_ops CLI 与部署脚本消费。
- 不执行任何结构变更或数据修改。

原 db_migrator.py 中的 DDL/DML 逻辑已迁移至 alembic revision：
- 0001_legacy_schema_baseline：完整建表
- 0002_access_control_v1_backfill：Course Access 历史数据回填
- 0003_agent_log_redaction_backfill：Agent 日志脱敏（不可逆）

本模块使用 SQLAlchemy Core 而非 sqlite3，以同时支持 SQLite 与 PostgreSQL。
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy import create_engine, inspect, text

from app.models.database import DATABASE_URL

ACCESS_CONTROL_MIGRATION_BATCH = "access-control-v1"
AGENT_LOG_MIGRATION_BATCH = "agent-log-minimization-v1"


def _build_connect_args(url: str) -> dict:
    """按数据库类型构建连接参数。"""
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _resolve_database_url(database_url: str | None = None) -> str:
    """解析数据库 URL。

    优先级：
    1. 显式传入的 database_url 参数（测试/部署脚本可覆盖）
    2. AI_COURSE_DATABASE_URL 环境变量（部署时动态切换库）
    3. app.models.database.DATABASE_URL（模块导入时的快照，兼容旧行为）

    动态读取环境变量是为了让 migration_ops CLI 在不同数据库间切换时，
    不必重新加载本模块即可生效。
    """
    if database_url:
        return database_url
    return os.environ.get("AI_COURSE_DATABASE_URL") or DATABASE_URL


def _table_exists(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _table_columns(inspector, table_name: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table_name)}


def access_control_preflight(database_url: str | None = None) -> dict[str, Any]:
    """验证 legacy 权限来源是否可安全回填。

    检查内容：
    - users/courses/student_enrollments 表是否存在且具备必需列。
    - 是否存在孤儿课程（teacher_id 指向不存在或非活跃用户）。
    - 是否存在孤儿 enrollment（指向不存在或非活跃的用户/课程）。

    返回结构：
        {"ok": bool, "issues": list[str], "counts": dict}
    """
    url = _resolve_database_url(database_url)
    if not os.path.exists(url.replace("sqlite:///", "")) and url.startswith("sqlite"):
        return {"ok": True, "issues": [], "counts": {}}

    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        inspector = inspect(engine)
        required = {
            "users": {"id", "is_active", "role"},
            "courses": {"id", "teacher_id"},
            "student_enrollments": {"course_id", "student_id", "is_active"},
        }
        issues: list[str] = []
        for table_name, columns in required.items():
            if not _table_exists(inspector, table_name):
                issues.append(f"{table_name} table missing")
                continue
            existing = _table_columns(inspector, table_name)
            missing = columns - existing
            if missing:
                issues.append(f"{table_name} missing columns: {', '.join(sorted(missing))}")
        if issues:
            return {"ok": False, "issues": issues, "counts": {}}

        with engine.connect() as conn:
            orphan_owners = conn.execute(
                text("""
                    SELECT COUNT(*) FROM courses c
                    LEFT JOIN users u ON u.id = c.teacher_id
                    WHERE c.teacher_id IS NULL OR u.id IS NULL OR u.is_active = 0
                """)
            ).scalar() or 0
            orphan_enrolments = conn.execute(
                text("""
                    SELECT COUNT(*) FROM student_enrollments e
                    LEFT JOIN courses c ON c.id = e.course_id
                    LEFT JOIN users u ON u.id = e.student_id
                    WHERE e.is_active = 1 AND (c.id IS NULL OR u.id IS NULL OR u.is_active = 0)
                """)
            ).scalar() or 0
            counts = {
                "orphan_course_owners": int(orphan_owners),
                "orphan_active_enrolments": int(orphan_enrolments),
            }
            if orphan_owners:
                issues.append(f"{orphan_owners} course owner records refer to missing or inactive users")
            if orphan_enrolments:
                issues.append(f"{orphan_enrolments} active enrollment records refer to missing/inactive users or courses")
            return {"ok": not issues, "issues": issues, "counts": counts}
    finally:
        engine.dispose()


def agent_log_redaction_preflight(database_url: str | None = None) -> dict[str, Any]:
    """报告 Agent 日志脱敏前置条件。

    检查内容：
    - agent_learning_events / agent_trace_records 表是否存在且具备必需列。
    - 统计待脱敏行数。

    返回结构：
        {"ok": bool, "issues": list[str], "counts": dict}
    """
    url = _resolve_database_url(database_url)
    if not os.path.exists(url.replace("sqlite:///", "")) and url.startswith("sqlite"):
        return {"ok": True, "issues": [], "counts": {}}

    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        inspector = inspect(engine)
        counts: dict[str, int] = {}
        issues: list[str] = []
        for table_name in ("agent_learning_events", "agent_trace_records"):
            if not _table_exists(inspector, table_name):
                counts[table_name] = 0
                continue
            required = {"id", "student_id", "course_id", "trace_id"}
            missing = required - _table_columns(inspector, table_name)
            if missing:
                issues.append(f"{table_name} missing columns: {', '.join(sorted(missing))}")
                continue
            with engine.connect() as conn:
                counts[table_name] = int(
                    conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0
                )
        return {"ok": not issues, "issues": issues, "counts": counts}
    finally:
        engine.dispose()


def legacy_schema_preflight(database_url: str | None = None) -> dict[str, Any]:
    """检查旧库 schema 是否符合 legacy baseline（0001）。

    用于判断是否可对旧库执行 `alembic stamp 0001` 后 upgrade head。

    返回结构：
        {"ok": bool, "issues": list[str], "table_count": int}
    """
    url = _resolve_database_url(database_url)
    if not os.path.exists(url.replace("sqlite:///", "")) and url.startswith("sqlite"):
        return {"ok": True, "issues": [], "table_count": 0}

    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        # baseline 必需的核心表（抽样检查，不要求全部）
        core_tables = {
            "users", "courses", "student_enrollments",
            "course_memberships", "course_capabilities",
        }
        missing = core_tables - tables
        issues = [f"missing core table: {t}" for t in sorted(missing)]
        return {
            "ok": not issues,
            "issues": issues,
            "table_count": len(tables),
        }
    finally:
        engine.dispose()


def migration_readiness_report(database_url: str | None = None) -> dict[str, Any]:
    """聚合所有预检结果，输出完整迁移就绪报告。

    返回结构：
        {
            "ok": bool,
            "target_revision": "0003",
            "blocking_issues": list[dict],
            "warnings": list[str],
            "backup_required": bool,
            "preflights": {
                "access_control": {...},
                "agent_log": {...},
                "legacy_schema": {...},
            },
        }
    """
    ac = access_control_preflight(database_url)
    al = agent_log_redaction_preflight(database_url)
    ls = legacy_schema_preflight(database_url)

    blocking: list[dict] = []
    warnings: list[str] = []

    if not ac["ok"]:
        blocking.extend({"code": "ACCESS_CONTROL", "detail": i} for i in ac["issues"])
    if not al["ok"]:
        blocking.extend({"code": "AGENT_LOG", "detail": i} for i in al["issues"])
    if not ls["ok"]:
        blocking.extend({"code": "LEGACY_SCHEMA", "detail": i} for i in ls["issues"])

    # agent log 脱敏不可逆，必须备份
    if al["counts"] and sum(al["counts"].values()) > 0:
        warnings.append("agent_log_redaction is irreversible; backup required before upgrade")
        backup_required = True
    else:
        backup_required = len(blocking) > 0

    return {
        "ok": len(blocking) == 0,
        "target_revision": "0004",
        "blocking_issues": blocking,
        "warnings": warnings,
        "backup_required": backup_required,
        "preflights": {
            "access_control": ac,
            "agent_log": al,
            "legacy_schema": ls,
        },
    }
