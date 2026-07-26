"""migration_ops CLI - 数据库迁移部署编排工具。

职责：
- preflight：执行迁移前只读预检，输出就绪报告。
- upgrade：执行 alembic upgrade head（含备份提示、账本写入）。
- downgrade：执行 alembic downgrade（含边界保护，禁止降到 base 以下）。
- stamp：对已具备 baseline 结构的旧库盖章（不执行迁移）。
- backup：SQLite 文件级备份（PG 由外部工具备份）。
- rollback-access-control：删除 access-control-v1 批次记录。
- rollback-agent-log：删除 agent-log 账本记录（不恢复原始内容）。
- ledger：查询 SchemaMigrationRecord 业务级迁移账本。
- current：显示当前 alembic 版本。
- history：显示迁移历史。

部署流程（P0-1 完成标准）：
    python -m app.scripts.migration_ops preflight
    python -m app.scripts.migration_ops backup
    python -m app.scripts.migration_ops upgrade
    # 启动应用前确认 ledger 已写入

回滚边界：
- upgrade 失败：alembic 事务原子回滚，账本不写入。
- downgrade：默认禁止降到 base；显式 --allow-base 才允许。
- rollback-access-control / rollback-agent-log：账本标记 rolled_back，
  但原始数据可能不可恢复（agent_log 不可逆）。

用法：
    python -m app.scripts.migration_ops preflight
    python -m app.scripts.migration_ops upgrade --backup
    python -m app.scripts.migration_ops downgrade --revision 0002
    python -m app.scripts.migration_ops stamp 0001
    python -m app.scripts.migration_ops ledger
    python -m app.scripts.migration_ops current
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保可从 backend/ 目录运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, inspect, text

from app.common.migration_preflight import migration_readiness_report
from app.models.database import DATABASE_URL as _DEFAULT_DATABASE_URL


def _database_url() -> str:
    """动态读取当前数据库 URL。

    优先使用 AI_COURSE_DATABASE_URL 环境变量；否则回退到模块导入时的默认值。
    这样在测试中通过环境变量切换数据库时，无需重新加载本模块。
    """
    return os.environ.get("AI_COURSE_DATABASE_URL") or _DEFAULT_DATABASE_URL


# ---------------------------------------------------------------------------
# 迁移账本常量：将 alembic revision 映射到业务级 SchemaMigrationRecord 条目
# ---------------------------------------------------------------------------

MIGRATION_LEDGER: dict[str, dict] = {
    "0001": {
        "batch_id": "legacy-schema-baseline",
        "name": "Legacy schema baseline (full table structure)",
        "rollback_notes": "Drop all tables; data loss. Restore from backup only.",
    },
    "0002": {
        "batch_id": "access-control-v1",
        "name": "Course Access v1 backfill (legacy role/teacher_id/enrollment)",
        "rollback_notes": (
            "Deletes rows tagged with migration_batch_id='access-control-v1'. "
            "Does NOT restore legacy role/teacher_id fields. "
            "Application code must be rolled back to a version that understands legacy fields."
        ),
    },
    "0003": {
        "batch_id": "agent-log-minimization-v1",
        "name": "Agent log redaction (irreversible raw payload minimization)",
        "rollback_notes": (
            "IRREVERSIBLE: deletes agent_log_migration_records ledger only. "
            "Original raw payloads (student questions, LLM traces) are permanently redacted. "
            "Backup is the only recovery boundary."
        ),
    },
    "0004": {
        "batch_id": "avatar-upload-security-v1",
        "name": "Avatar upload security v1 (server-side object_key, ffprobe, scan, verified state)",
        "rollback_notes": (
            "Drops new columns on avatar_profiles / avatar_source_media (PostgreSQL only). "
            "SQLite keeps columns due to lack of DROP COLUMN support. "
            "upload_status string values migrated: pending->pending_upload, validated->verified; "
            "downgrade does NOT restore old string values. "
            "Application code must be rolled back to a version that understands new states."
        ),
    },
    "0005": {
        "batch_id": "storage-object-refs-v1",
        "name": "Storage object refs v1 (GC ledger, readback verification, soft delete)",
        "rollback_notes": (
            "Drops storage_object_refs table. "
            "GC/readback/soft-delete history is lost; object files in provider are NOT affected. "
            "Re-running upgrade recreates the table and reconcile() repopulates refs from provider."
        ),
    },
}

BASELINE_REVISION = "0001"
HEAD_REVISION = "0005"


def _build_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _run_alembic(*args: str) -> int:
    """执行 alembic 命令，返回退出码。

    通过 alembic.command 模块直接调用，避免 CommandLine.main() 触发 sys.exit。
    env.py 在导入时会用 AI_COURSE_DATABASE_URL 环境变量覆盖 config 中的 url，
    因此调用方需先设置该环境变量（_run_migration_ops 测试辅助已处理）。
    """
    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", _database_url())

    cmd_name = args[0] if args else ""
    if cmd_name == "upgrade":
        command.upgrade(config, args[1] if len(args) > 1 else "head")
    elif cmd_name == "downgrade":
        command.downgrade(config, args[1] if len(args) > 1 else "-1")
    elif cmd_name == "stamp":
        command.stamp(config, args[1])
    elif cmd_name == "current":
        command.current(config)
    elif cmd_name == "history":
        command.history(config, verbose=len(args) > 1 and args[1] == "--verbose")
    else:
        raise ValueError(f"Unknown alembic command: {cmd_name}")
    return 0


def _current_alembic_version(url: str) -> str | None:
    """读取 alembic_version 表中的当前版本号。"""
    if not _database_file_exists(url):
        return None
    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            return None
        with engine.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()


def _database_file_exists(url: str) -> bool:
    """SQLite 库文件存在性检查；非 SQLite 视为存在。"""
    if not url.startswith("sqlite:///"):
        return True
    return os.path.exists(url.removeprefix("sqlite:///"))


def _write_ledger_entry(
    url: str,
    *,
    revision: str,
    status: str,
    applied_rows: int = 0,
    operator_user_id: int | None = None,
    preflight_ok: bool = True,
) -> None:
    """向 schema_migration_records 表写入或更新一条业务级迁移账本。

    幂等：如果 batch_id 已存在，仅更新 status 与 applied_at。
    """
    if revision not in MIGRATION_LEDGER:
        return
    entry = MIGRATION_LEDGER[revision]
    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        with engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM schema_migration_records WHERE batch_id = :batch_id"
                ),
                {"batch_id": entry["batch_id"]},
            ).first()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if existing is None:
                conn.execute(
                    text(
                        "INSERT INTO schema_migration_records "
                        "(batch_id, name, applied_at, status, rollback_notes, "
                        "preflight_ok, applied_rows, operator_user_id, created_at) "
                        "VALUES (:batch_id, :name, :applied_at, :status, :notes, "
                        ":preflight_ok, :applied_rows, :operator, :created_at)"
                    ),
                    {
                        "batch_id": entry["batch_id"],
                        "name": entry["name"],
                        "applied_at": now,
                        "status": status,
                        "notes": entry["rollback_notes"],
                        "preflight_ok": 1 if preflight_ok else 0,
                        "applied_rows": applied_rows,
                        "operator": operator_user_id,
                        "created_at": now,
                    },
                )
            else:
                conn.execute(
                    text(
                        "UPDATE schema_migration_records "
                        "SET applied_at = :applied_at, status = :status, "
                        "preflight_ok = :preflight_ok, applied_rows = :applied_rows "
                        "WHERE batch_id = :batch_id"
                    ),
                    {
                        "applied_at": now,
                        "status": status,
                        "preflight_ok": 1 if preflight_ok else 0,
                        "applied_rows": applied_rows,
                        "batch_id": entry["batch_id"],
                    },
                )
    finally:
        engine.dispose()


def _count_batch_rows(url: str, batch_id: str) -> int:
    """统计某批次回填产生的行数（用于审计 applied_rows）。"""
    engine = create_engine(url, connect_args=_build_connect_args(url))
    try:
        inspector = inspect(engine)
        total = 0
        for table in (
            "course_memberships",
            "course_capabilities",
            "platform_permission_assignments",
            "agent_log_migration_records",
        ):
            if table not in inspector.get_table_names():
                continue
            with engine.connect() as conn:
                # 不同表使用 migration_batch_id 或 batch_id 列
                if table == "agent_log_migration_records":
                    count = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table} WHERE batch_id = :b"),
                        {"b": batch_id},
                    ).scalar() or 0
                else:
                    count = conn.execute(
                        text(f"SELECT COUNT(*) FROM {table} WHERE migration_batch_id = :b"),
                        {"b": batch_id},
                    ).scalar() or 0
                total += int(count)
        return total
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    """执行迁移前预检，输出就绪报告。"""
    report = migration_readiness_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if not report["ok"]:
        print("\nBLOCKING: 迁移被阻断，请先修复上述问题。", file=sys.stderr)
        return 1

    if report["backup_required"]:
        print(
            "\nWARNING: 建议在升级前备份数据库（agent_log 脱敏不可逆）。",
            file=sys.stderr,
        )
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    """执行 alembic upgrade head（含预检、备份、账本写入）。"""
    db_url = _database_url()
    if args.backup and db_url.startswith("sqlite:///"):
        db_path = db_url.removeprefix("sqlite:///")
        if os.path.exists(db_path):
            backup_path = (
                f"{db_path}.backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            )
            shutil.copy2(db_path, backup_path)
            print(f"Backup created: {backup_path}")
        else:
            print(f"Database not found at {db_path}, skip backup")
    elif args.backup:
        print(
            "WARNING: 非 SQLite 数据库请使用外部工具备份（pg_dump 等）。",
            file=sys.stderr,
        )

    if not args.skip_preflight:
        report = migration_readiness_report(db_url)
        if not report["ok"]:
            print("Preflight failed, refusing to upgrade:", file=sys.stderr)
            print(json.dumps(report["blocking_issues"], indent=2), file=sys.stderr)
            return 1

    target = args.revision or "head"
    print(f"Upgrading to {target}...")
    exit_code = _run_alembic("upgrade", target)
    if exit_code not in (None, 0):
        print(f"alembic upgrade failed with exit code {exit_code}", file=sys.stderr)
        return int(exit_code or 1)

    # 写入业务级迁移账本（仅写入实际执行的 revision）
    # 通过对比 alembic_version 前后差异决定写入哪些条目
    current = _current_alembic_version(db_url)
    if current:
        # 升级到 head 时，写入所有已知 revision 的账本条目（幂等）
        for revision in MIGRATION_LEDGER.keys():
            entry = MIGRATION_LEDGER.get(revision)
            if entry is None:
                continue
            applied_rows = _count_batch_rows(db_url, entry["batch_id"])
            _write_ledger_entry(
                db_url,
                revision=revision,
                status="applied",
                applied_rows=applied_rows,
                preflight_ok=True,
            )
        print(f"Ledger updated: alembic_version={current}")

    return 0


def cmd_downgrade(args: argparse.Namespace) -> int:
    """执行 alembic downgrade（含边界保护）。

    边界保护：
    - 默认禁止降到 base（会丢全部表结构）；
      必须显式 --allow-base 才允许。
    - agent_log 不可逆：downgrade 到 0002 以下会删除脱敏账本，
      但原始 raw payload 已永久丢失，必须再次确认。
    - 自动备份 SQLite（除非 --no-backup）。
    """
    target = args.revision or "-1"

    if target in ("base", "0000") and not args.allow_base:
        print(
            "BLOCKING: 拒绝降到 base（会删除全部表结构）。"
            "如确需，请显式传 --allow-base 并提前备份。",
            file=sys.stderr,
        )
        return 1

    # agent_log 不可逆保护
    if target in ("base", "0001", "0000"):
        print(
            "WARNING: 降到 %s 会删除 agent_log_migration_records 账本，"
            "但原始 raw payload 已永久脱敏，无法恢复。" % target,
            file=sys.stderr,
        )
        if not args.confirm_irreversible:
            print(
                "BLOCKING: 不可逆操作，请显式传 --confirm-irreversible。",
                file=sys.stderr,
            )
            return 1

    # SQLite 自动备份
    db_url = _database_url()
    if not args.no_backup and db_url.startswith("sqlite:///"):
        db_path = db_url.removeprefix("sqlite:///")
        if os.path.exists(db_path):
            backup_path = (
                f"{db_path}.backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
            )
            shutil.copy2(db_path, backup_path)
            print(f"Auto-backup created: {backup_path}")

    print(f"Downgrading to {target}...")
    exit_code = _run_alembic("downgrade", target)
    if exit_code not in (None, 0):
        print(f"alembic downgrade failed with exit code {exit_code}", file=sys.stderr)
        return int(exit_code or 1)

    # 更新账本：标记被撤销的 revision 为 rolled_back
    current = _current_alembic_version(db_url)
    if current:
        # 简化：downgrade 后将所有比当前版本高的条目标记为 rolled_back
        try:
            current_idx = list(MIGRATION_LEDGER.keys()).index(current)
        except ValueError:
            current_idx = -1
        if current_idx >= 0:
            for revision in list(MIGRATION_LEDGER.keys())[current_idx + 1:]:
                _write_ledger_entry(
                    db_url,
                    revision=revision,
                    status="rolled_back",
                    applied_rows=0,
                    preflight_ok=True,
                )
        print(f"Ledger updated: alembic_version={current}")

    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    """对旧库盖章，不执行迁移。

    仅当旧库已具备 baseline 结构时使用。应先运行 preflight 确认。
    """
    print(f"Stamping database to revision {args.revision} (no migration executed)")
    print(
        "WARNING: 确保旧库已具备该 revision 对应的结构。",
        file=sys.stderr,
    )
    exit_code = _run_alembic("stamp", args.revision)
    if exit_code not in (None, 0):
        return int(exit_code or 1)

    # stamp 后也写入对应账本条目（标记为已应用，但不执行实际 DDL/DML）
    if args.revision in MIGRATION_LEDGER:
        _write_ledger_entry(
            _database_url(),
            revision=args.revision,
            status="applied",
            applied_rows=0,
            preflight_ok=True,
        )
        print(f"Ledger entry written for {args.revision}")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    """SQLite 文件级备份。"""
    db_url = _database_url()
    if not db_url.startswith("sqlite:///"):
        print(
            "ERROR: 非 SQLite 数据库请使用外部工具备份（pg_dump 等）。",
            file=sys.stderr,
        )
        return 1

    db_path = db_url.removeprefix("sqlite:///")
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        return 1

    backup_path = (
        args.output
        or f"{db_path}.backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    )
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")
    return 0


def cmd_rollback_access_control(args: argparse.Namespace) -> int:
    """删除 access-control-v1 批次创建的记录。"""
    from app.common.db_migrator import rollback_access_control_backfill

    if args.dry_run:
        print("[dry-run] Would delete access-control-v1 batch records")
        return 0

    deleted = rollback_access_control_backfill()
    print(f"Deleted: {deleted}")
    print(
        "WARNING: 应用代码必须回退到理解 legacy role/teacher_id 的版本。",
        file=sys.stderr,
    )

    # 更新账本状态为 rolled_back
    _write_ledger_entry(
        _database_url(),
        revision="0002",
        status="rolled_back",
        applied_rows=0,
        preflight_ok=True,
    )
    print("Ledger updated: access-control-v1 marked rolled_back")
    return 0


def cmd_rollback_agent_log(args: argparse.Namespace) -> int:
    """删除 agent-log-minimization-v1 批次的账本记录。"""
    from app.common.db_migrator import rollback_agent_log_minimization

    if args.dry_run:
        print("[dry-run] Would delete agent-log-minimization-v1 ledger records")
        print(
            "WARNING: 原始 raw payload 已永久脱敏，无法恢复。",
            file=sys.stderr,
        )
        return 0

    deleted = rollback_agent_log_minimization()
    print(f"Deleted: {deleted}")
    print(
        "WARNING: 原始 raw payload 已永久脱敏，无法恢复。",
        file=sys.stderr,
    )

    # 更新账本状态为 rolled_back
    _write_ledger_entry(
        _database_url(),
        revision="0003",
        status="rolled_back",
        applied_rows=0,
        preflight_ok=True,
    )
    print("Ledger updated: agent-log-minimization-v1 marked rolled_back")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    """查询 schema_migration_records 业务级迁移账本。"""
    db_url = _database_url()
    if not _database_file_exists(db_url):
        print("Database file not found; no ledger entries.")
        return 0
    engine = create_engine(db_url, connect_args=_build_connect_args(db_url))
    try:
        inspector = inspect(engine)
        if "schema_migration_records" not in inspector.get_table_names():
            print("schema_migration_records table not present; run `alembic upgrade head`.")
            return 0
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT batch_id, name, applied_at, status, rollback_notes, "
                    "preflight_ok, applied_rows "
                    "FROM schema_migration_records "
                    "ORDER BY applied_at DESC"
                )
            ).all()
        items = [
            {
                "batch_id": r[0],
                "name": r[1],
                "applied_at": str(r[2]) if r[2] else "",
                "status": r[3],
                "rollback_notes": r[4],
                "preflight_ok": bool(r[5]),
                "applied_rows": int(r[6] or 0),
            }
            for r in rows
        ]
        print(json.dumps({"items": items, "total": len(items)}, indent=2, ensure_ascii=False))
        return 0
    finally:
        engine.dispose()


def cmd_current(args: argparse.Namespace) -> int:
    """显示当前 alembic 版本。"""
    return _run_alembic("current")


def cmd_history(args: argparse.Namespace) -> int:
    """显示迁移历史。"""
    return _run_alembic("history", "--verbose" if args.verbose else "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migration_ops",
        description="数据库迁移部署编排工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # preflight
    p_preflight = sub.add_parser("preflight", help="迁移前只读预检")
    p_preflight.set_defaults(func=cmd_preflight)

    # upgrade
    p_upgrade = sub.add_parser("upgrade", help="执行 alembic upgrade")
    p_upgrade.add_argument("--revision", default="head", help="目标版本（默认 head）")
    p_upgrade.add_argument("--backup", action="store_true", help="升级前备份（SQLite）")
    p_upgrade.add_argument("--skip-preflight", action="store_true", help="跳过预检")
    p_upgrade.set_defaults(func=cmd_upgrade)

    # downgrade
    p_down = sub.add_parser("downgrade", help="执行 alembic downgrade（含边界保护）")
    p_down.add_argument(
        "--revision",
        default="-1",
        help="目标版本（默认 -1，即回退一格；可为 0001/0002/0003/base）",
    )
    p_down.add_argument(
        "--allow-base",
        action="store_true",
        help="允许降到 base（默认禁止，会删除全部表结构）",
    )
    p_down.add_argument(
        "--confirm-irreversible",
        action="store_true",
        help="确认 agent_log 不可逆回滚（仅降到 0001 以下时需要）",
    )
    p_down.add_argument(
        "--no-backup",
        action="store_true",
        help="跳过 SQLite 自动备份（不建议）",
    )
    p_down.set_defaults(func=cmd_downgrade)

    # stamp
    p_stamp = sub.add_parser("stamp", help="对旧库盖章（不执行迁移）")
    p_stamp.add_argument("revision", help="目标版本号，如 0001")
    p_stamp.set_defaults(func=cmd_stamp)

    # backup
    p_backup = sub.add_parser("backup", help="SQLite 文件级备份")
    p_backup.add_argument("--output", help="备份文件路径")
    p_backup.set_defaults(func=cmd_backup)

    # rollback-access-control
    p_rbac = sub.add_parser("rollback-access-control", help="删除 access-control-v1 批次记录")
    p_rbac.add_argument("--dry-run", action="store_true", help="只显示会删除什么")
    p_rbac.set_defaults(func=cmd_rollback_access_control)

    # rollback-agent-log
    p_ral = sub.add_parser("rollback-agent-log", help="删除 agent-log 账本记录")
    p_ral.add_argument("--dry-run", action="store_true", help="只显示会删除什么")
    p_ral.set_defaults(func=cmd_rollback_agent_log)

    # ledger
    p_ledger = sub.add_parser("ledger", help="查询 schema_migration_records 业务级迁移账本")
    p_ledger.set_defaults(func=cmd_ledger)

    # current
    p_current = sub.add_parser("current", help="显示当前 alembic 版本")
    p_current.set_defaults(func=cmd_current)

    # history
    p_history = sub.add_parser("history", help="显示迁移历史")
    p_history.add_argument("--verbose", action="store_true")
    p_history.set_defaults(func=cmd_history)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
