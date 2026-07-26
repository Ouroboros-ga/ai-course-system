"""P0-1 数据库迁移机制验收测试。

覆盖三个场景：
1. 空库 alembic upgrade head 建表（SQLite）
2. 旧 SQLite fixture stamp + upgrade head 演练
3. PostgreSQL 迁移冒烟测试（需 PG 可用，否则跳过）

验证目标（来自 P0-1 完成标准）：
- 任意历史版本数据库 → 按迁移链升级 → 当前应用启动 → 数据和权限记录仍可读
- SQLite 与 PostgreSQL 都能从空库执行到 head
- 旧 SQLite fixture 可经 preflight、stamp、upgrade 演练
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text


def _alembic_config(db_url: str):
    """构建指向指定 DB 的 alembic Config。"""
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    # 设置绝对路径，避免从其他目录运行时找不到 versions/
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", db_url)
    return config


def _run_alembic(db_url: str, *args: str) -> None:
    """执行 alembic 命令。

    通过环境变量 AI_COURSE_DATABASE_URL 传递数据库 URL，
    因为 env.py 在导入时会用该环境变量覆盖 config 中的 sqlalchemy.url。
    """
    from alembic import command

    config = _alembic_config(db_url)
    old_url = os.environ.get("AI_COURSE_DATABASE_URL")
    os.environ["AI_COURSE_DATABASE_URL"] = db_url
    try:
        method = getattr(command, args[0])
        method(config, *args[1:])
    finally:
        if old_url is not None:
            os.environ["AI_COURSE_DATABASE_URL"] = old_url
        else:
            os.environ.pop("AI_COURSE_DATABASE_URL", None)


# ==================== 场景1：空库 upgrade head（SQLite）====================


def test_empty_sqlite_upgrade_head_creates_all_tables(tmp_path):
    """空 SQLite 库 alembic upgrade head 应创建所有表。"""
    db_path = tmp_path / "empty.db"
    db_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "upgrade", "head")

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        # 验证核心表存在
        core_tables = {
            "users", "courses", "course_memberships", "course_capabilities",
            "platform_permission_assignments", "agent_learning_events",
            "agent_trace_records", "alembic_version",
        }
        assert core_tables.issubset(tables), f"缺少核心表: {core_tables - tables}"

        # 验证 alembic_version 表指向 head
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0004", f"alembic_version 应为 0004，实际 {version}"
    finally:
        engine.dispose()


# ==================== 场景2：旧 SQLite fixture stamp + upgrade 演练 ====================


def test_legacy_sqlite_stamp_and_upgrade(tmp_path):
    """旧 SQLite 库（已具备 baseline 结构）通过 stamp + upgrade head 升级。

    模拟场景：已部署的旧库通过 create_all 建表，现在要接入 alembic。
    流程：preflight → stamp 0001 → upgrade head
    """
    from app.common.migration_preflight import migration_readiness_report
    from app.models import database  # 确保模型已导入
    from sqlmodel import SQLModel

    db_path = tmp_path / "legacy.db"
    db_url = f"sqlite:///{db_path}"

    # 1. 用 create_all 模拟旧库（已具备 baseline 结构）
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    engine.dispose()

    # 2. preflight 检查
    report = migration_readiness_report(db_url)
    assert report["ok"], f"preflight 应通过: {report['blocking_issues']}"

    # 3. stamp 0001（标记旧库已具备 baseline 结构）
    _run_alembic(db_url, "stamp", "0001")

    # 4. upgrade head（执行 0002 + 0003 数据迁移）
    _run_alembic(db_url, "upgrade", "head")

    # 5. 验证 alembic_version 指向 head
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0004"

            # 6. 验证数据迁移生效（0002 access_control backfill）
            # 旧库无 legacy role/teacher_id 数据，所以回填不应产生记录
            # 但表结构应存在且可查询
            membership_count = conn.execute(
                text("SELECT COUNT(*) FROM course_memberships")
            ).scalar()
            assert membership_count == 0  # 无 legacy 数据，回填无记录

            # 7. 验证数据迁移生效（0003 agent log redaction）
            # 旧库无 raw payload，脱敏处理 0 行，但仍写入账本记录（标记批次已执行）
            log_count = conn.execute(
                text("SELECT COUNT(*) FROM agent_log_migration_records")
            ).scalar()
            assert log_count == 1  # 账本记录存在，标记批次已执行
            ledger = conn.execute(text(
                "SELECT redacted_event_rows, redacted_trace_rows "
                "FROM agent_log_migration_records WHERE batch_id = 'agent-log-minimization-v1'"
            )).one()
            assert ledger[0] == 0  # 0 行 event 被脱敏
            assert ledger[1] == 0  # 0 行 trace 被脱敏
    finally:
        engine.dispose()


def test_legacy_sqlite_with_data_stamp_and_upgrade(tmp_path):
    """旧 SQLite 库（含 legacy 权限数据）通过 stamp + upgrade 升级。

    模拟场景：已部署的旧库有 users.role/courses.teacher_id/student_enrollments 数据。
    流程：stamp 0001 → upgrade head → 验证 access_control backfill 生成记录
    """
    from app.models import database  # noqa: F401
    from sqlmodel import SQLModel

    db_path = tmp_path / "legacy_with_data.db"
    db_url = f"sqlite:///{db_path}"

    # 1. 用 create_all 建库
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    # 2. 插入 legacy 权限数据（补全所有 NOT NULL 字段）
    with engine.begin() as conn:
        # 插入 teacher 用户
        conn.execute(text(
            "INSERT INTO users (username, hashed_password, role, is_active, is_fanya_verified, created_at) "
            "VALUES ('legacy_teacher', 'hash', 'teacher', 1, 0, CURRENT_TIMESTAMP)"
        ))
        teacher_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        # 插入 student 用户
        conn.execute(text(
            "INSERT INTO users (username, hashed_password, role, is_active, is_fanya_verified, created_at) "
            "VALUES ('legacy_student', 'hash', 'student', 1, 0, CURRENT_TIMESTAMP)"
        ))
        student_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        # 插入课程（teacher_id 指向 teacher，补全所有 NOT NULL 字段）
        conn.execute(text(
            "INSERT INTO courses (fanya_course_id, fanya_course_name, title, teacher_id, status, "
            "is_ai_generated, total_duration, total_nodes, total_pages, created_at, updated_at) "
            "VALUES ('legacy-1', 'Legacy', 'Legacy Course', :tid, 'published', "
            "0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"tid": teacher_id})
        course_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()

        # 插入 enrollment（补全所有 NOT NULL 字段）
        conn.execute(text(
            "INSERT INTO student_enrollments (student_id, course_id, is_active, overall_progress, "
            "enrolled_at, total_nodes_completed, total_nodes_count, avg_understanding_score, "
            "avg_understanding_level, total_study_minutes) "
            "VALUES (:sid, :cid, 1, 0.0, CURRENT_TIMESTAMP, 0, 0, 0.0, 'UNKNOWN', 0)"
        ), {"sid": student_id, "cid": course_id})
    engine.dispose()

    # 3. stamp 0001 + upgrade head
    _run_alembic(db_url, "stamp", "0001")
    _run_alembic(db_url, "upgrade", "head")

    # 4. 验证 access_control backfill 生成了记录
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            # 应生成 1 条 owner membership（teacher -> course）
            owner_count = conn.execute(text(
                "SELECT COUNT(*) FROM course_memberships "
                "WHERE role = 'owner' AND migration_batch_id = 'access-control-v1'"
            )).scalar()
            assert owner_count == 1, f"应有 1 条 owner membership，实际 {owner_count}"

            # 应生成 1 条 student membership
            student_count = conn.execute(text(
                "SELECT COUNT(*) FROM course_memberships "
                "WHERE role = 'student' AND migration_batch_id = 'access-control-v1'"
            )).scalar()
            assert student_count == 1, f"应有 1 条 student membership，实际 {student_count}"

            # 应生成 1 条 platform.course.create permission（teacher）
            perm_count = conn.execute(text(
                "SELECT COUNT(*) FROM platform_permission_assignments "
                "WHERE permission = 'platform.course.create' "
                "AND migration_batch_id = 'access-control-v1'"
            )).scalar()
            assert perm_count == 1, f"应有 1 条 platform.course.create permission，实际 {perm_count}"

            # 应生成 1 条 course_capability
            cap_count = conn.execute(text(
                "SELECT COUNT(*) FROM course_capabilities "
                "WHERE migration_batch_id = 'access-control-v1'"
            )).scalar()
            assert cap_count == 1, f"应有 1 条 course_capability，实际 {cap_count}"
    finally:
        engine.dispose()


# ==================== 场景3：PostgreSQL 迁移冒烟测试 ====================


def _postgres_available() -> bool:
    """检查 PostgreSQL 测试数据库是否可用。"""
    pg_url = os.environ.get("AI_COURSE_TEST_POSTGRES_URL", "")
    if not pg_url:
        return False
    try:
        engine = create_engine(pg_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _postgres_available(),
    reason="需设置 AI_COURSE_TEST_POSTGRES_URL 且 PostgreSQL 可用",
)
def test_postgres_empty_upgrade_head():
    """PostgreSQL 空库 alembic upgrade head 冒烟测试。

    需设置环境变量 AI_COURSE_TEST_POSTGRES_URL=postgresql://user:pass@host:port/dbname
    """
    pg_url = os.environ["AI_COURSE_TEST_POSTGRES_URL"]

    # 清空测试库（仅用于测试，生产禁止）
    engine = create_engine(pg_url)
    with engine.begin() as conn:
        # 删除所有表（包括 alembic_version）
        conn.execute(text(
            "DROP TABLE IF EXISTS alembic_version CASCADE"
        ))
        # 获取所有表并删除
        inspector = inspect(engine)
        for table_name in inspector.get_table_names():
            conn.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
    engine.dispose()

    # 执行 alembic upgrade head
    _run_alembic(pg_url, "upgrade", "head")

    # 验证
    engine = create_engine(pg_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        core_tables = {
            "users", "courses", "course_memberships", "alembic_version",
        }
        assert core_tables.issubset(tables), f"PG 缺少核心表: {core_tables - tables}"

        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0004"
    finally:
        engine.dispose()


# ==================== 迁移链完整性测试 ====================


def test_migration_chain_downgrade_and_upgrade_roundtrip(tmp_path):
    """迁移链 downgrade + upgrade 往返测试。

    验证：upgrade head → downgrade 0001 → upgrade head 不丢失数据结构。
    """
    db_path = tmp_path / "roundtrip.db"
    db_url = f"sqlite:///{db_path}"

    # 1. 初始 upgrade head
    _run_alembic(db_url, "upgrade", "head")

    # 2. downgrade 到 0001（撤销 0002 + 0003 数据迁移）
    _run_alembic(db_url, "downgrade", "0001")

    # 3. 验证 0002/0003 的数据被回滚
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            # access_control backfill 记录应被删除
            membership_count = conn.execute(text(
                "SELECT COUNT(*) FROM course_memberships "
                "WHERE migration_batch_id = 'access-control-v1'"
            )).scalar()
            assert membership_count == 0

            # agent log 账本应被删除
            log_count = conn.execute(text(
                "SELECT COUNT(*) FROM agent_log_migration_records"
            )).scalar()
            assert log_count == 0

            # alembic_version 应为 0001
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0001"
    finally:
        engine.dispose()

    # 4. 再次 upgrade head
    _run_alembic(db_url, "upgrade", "head")

    # 5. 验证结构完整
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0004"
    finally:
        engine.dispose()


# ==================== 场景4：migration_ops CLI 边界保护与账本写入 ====================


def _run_migration_ops(db_url: str, *args: str) -> int:
    """直接调用 migration_ops 模块函数，避免子进程开销。

    通过临时设置 AI_COURSE_DATABASE_URL 环境变量让 CLI 指向目标库。
    migration_ops 内部使用 _database_url() 动态读取环境变量，无需 reload。
    """
    from app.scripts import migration_ops

    old_url = os.environ.get("AI_COURSE_DATABASE_URL")
    os.environ["AI_COURSE_DATABASE_URL"] = db_url
    try:
        return migration_ops.main(list(args))
    finally:
        if old_url is not None:
            os.environ["AI_COURSE_DATABASE_URL"] = old_url
        else:
            os.environ.pop("AI_COURSE_DATABASE_URL", None)


def test_migration_ops_upgrade_writes_ledger(tmp_path):
    """upgrade head 后 schema_migration_records 应包含 0001/0002/0003/0004 四条账本。"""
    db_path = tmp_path / "ledger.db"
    db_url = f"sqlite:///{db_path}"

    rc = _run_migration_ops(db_url, "upgrade", "--skip-preflight")
    assert rc == 0

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0004"

            rows = conn.execute(
                text(
                    "SELECT batch_id, status FROM schema_migration_records ORDER BY batch_id"
                )
            ).all()
            batch_ids = {r[0] for r in rows}
            assert "legacy-schema-baseline" in batch_ids
            assert "access-control-v1" in batch_ids
            assert "agent-log-minimization-v1" in batch_ids
            assert "avatar-upload-security-v1" in batch_ids
            for r in rows:
                assert r[1] == "applied"
    finally:
        engine.dispose()


def test_migration_ops_ledger_command_outputs_entries(tmp_path):
    """ledger 命令应输出 schema_migration_records 中的条目。"""
    import io
    import contextlib

    db_path = tmp_path / "ledger_query.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _run_migration_ops(db_url, "ledger")
    assert rc == 0
    body = out.getvalue()
    assert "schema_migration_records" not in body or "items" in body
    assert "legacy-schema-baseline" in body
    assert "access-control-v1" in body
    assert "agent-log-minimization-v1" in body
    assert "avatar-upload-security-v1" in body


def test_migration_ops_downgrade_refuses_base_by_default(tmp_path):
    """默认禁止降到 base，必须显式 --allow-base。"""
    db_path = tmp_path / "downgrade_base.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")

    rc = _run_migration_ops(
        db_url, "downgrade", "--revision", "base", "--no-backup"
    )
    assert rc == 1, "应拒绝降到 base"


def test_migration_ops_downgrade_to_0001_requires_confirm_irreversible(tmp_path):
    """降到 0001 触发 agent_log 不可逆保护，需 --confirm-irreversible。"""
    db_path = tmp_path / "downgrade_0001.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")

    rc = _run_migration_ops(
        db_url, "downgrade", "--revision", "0001", "--no-backup"
    )
    assert rc == 1, "应要求 --confirm-irreversible"


def test_migration_ops_downgrade_to_0002_marks_ledger_rolled_back(tmp_path):
    """downgrade 到 0002 后，agent_log 账本应被标记 rolled_back。"""
    db_path = tmp_path / "downgrade_0002.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")
    _run_migration_ops(
        db_url, "downgrade", "--revision", "0002", "--no-backup"
    )

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == "0002"

            status = conn.execute(
                text(
                    "SELECT status FROM schema_migration_records "
                    "WHERE batch_id = 'agent-log-minimization-v1'"
                )
            ).scalar()
            assert status == "rolled_back"
    finally:
        engine.dispose()


def test_migration_ops_rollback_access_control_updates_ledger(tmp_path):
    """rollback-access-control 命令应将 0002 账本标记为 rolled_back。"""
    db_path = tmp_path / "rollback_ac.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")

    rc = _run_migration_ops(db_url, "rollback-access-control")
    assert rc == 0

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            status = conn.execute(
                text(
                    "SELECT status FROM schema_migration_records "
                    "WHERE batch_id = 'access-control-v1'"
                )
            ).scalar()
            assert status == "rolled_back"
    finally:
        engine.dispose()


def test_migration_ops_preflight_blocks_when_legacy_orphan_exists(tmp_path):
    """preflight 应在存在孤儿课程时阻断 upgrade。"""
    from sqlmodel import SQLModel

    db_path = tmp_path / "orphan.db"
    db_url = f"sqlite:///{db_path}"

    # 用 create_all 模拟旧库结构
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        # 插入一条 teacher_id 指向不存在用户的孤儿课程
        conn.execute(text(
            "INSERT INTO courses (fanya_course_id, fanya_course_name, title, teacher_id, status, "
            "is_ai_generated, total_duration, total_nodes, total_pages, created_at, updated_at) "
            "VALUES ('orphan-1', 'Orphan', 'Orphan Course', 9999, 'published', "
            "0, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    engine.dispose()

    # 预检应阻断
    rc = _run_migration_ops(db_url, "preflight")
    assert rc == 1


def test_migration_ledger_idempotent_on_repeated_upgrade(tmp_path):
    """重复执行 upgrade head，账本条目应保持唯一（不产生重复行）。"""
    db_path = tmp_path / "idempotent.db"
    db_url = f"sqlite:///{db_path}"

    _run_migration_ops(db_url, "upgrade", "--skip-preflight")
    _run_migration_ops(db_url, "upgrade", "--skip-preflight")

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM schema_migration_records")
            ).scalar()
            assert count == 4, f"应只有 4 条账本，实际 {count}"
    finally:
        engine.dispose()
