"""
访问控制运维 CLI：预检、备份、恢复、回滚 backfill 演练。

批次0上线底座要求：跑 access_control_preflight，补齐迁移、回滚、备份恢复演练。

用法（在 backend 目录）：
    uv run python -m app.scripts.access_control_ops preflight
    uv run python -m app.scripts.access_control_ops backup
    uv run python -m app.scripts.access_control_ops restore <backup_file>
    uv run python -m app.scripts.access_control_ops rollback-backfill
    uv run python -m app.scripts.access_control_ops drill   # 完整备份->预检->回滚->恢复演练

注意：
- 备份/恢复仅支持 SQLite 文件级复制（与当前迁移器一致）。
- rollback-backfill 是部署回滚伴侣，不是运行时恢复机制；应用必须先回滚到
  仍理解 legacy 权限的代码版本后再执行（AGENTS.md §5.3.4）。
- 不要在生产服务流量进行中执行恢复。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone

from app.common.db_migrator import (
    ACCESS_CONTROL_MIGRATION_BATCH,
    access_control_preflight,
    rollback_access_control_backfill,
)
from app.models.database import DATABASE_DIR, DATABASE_URL


def _resolve_db_path() -> str:
    if not DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError("当前数据库非 SQLite，备份/恢复仅支持 SQLite 文件")
    return DATABASE_URL.removeprefix("sqlite:///")


def _print_preflight(report: dict) -> int:
    ok = report.get("ok", False)
    print(f"[preflight] ok={ok}")
    counts = report.get("counts", {})
    if counts:
        for k, v in counts.items():
            print(f"             {k} = {v}")
    for issue in report.get("issues", []):
        print(f"             issue: {issue}")
    return 0 if ok else 1


def cmd_preflight(args: argparse.Namespace) -> int:
    path = args.database or _resolve_db_path()
    report = access_control_preflight(path)
    return _print_preflight(report)


def cmd_backup(args: argparse.Namespace) -> int:
    src = args.database or _resolve_db_path()
    if not os.path.exists(src):
        print(f"[backup] 数据库文件不存在: {src}")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest_dir = args.dest_dir or os.path.join(DATABASE_DIR, "backups")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"smart_class_{stamp}.db")
    # 使用 SQLite 在线备份 API 保证一致性；退回到文件复制
    copied = _sqlite_safe_copy(src, dest)
    if copied:
        print(f"[backup] ok -> {dest}")
        return 0
    print(f"[backup] FAILED")
    return 1


def _sqlite_safe_copy(src: str, dest: str) -> bool:
    """优先用 SQLite backup API 做热备份；失败则文件复制。"""
    try:
        import sqlite3

        src_conn = sqlite3.connect(src)
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
            return True
        finally:
            dest_conn.close()
            src_conn.close()
    except Exception:
        # 回退到直接复制（要求此时没有写入连接）
        try:
            shutil.copy2(src, dest)
            return True
        except Exception:
            return False


def cmd_restore(args: argparse.Namespace) -> int:
    src = args.backup_file
    if not os.path.exists(src):
        print(f"[restore] 备份文件不存在: {src}")
        return 1
    dest = args.database or _resolve_db_path()
    if not args.force and os.path.exists(dest):
        print(f"[restore] 目标已存在: {dest}（使用 --force 覆盖）")
        return 1
    shutil.copy2(src, dest)
    print(f"[restore] ok -> {dest} (from {src})")
    # 恢复后立即预检，确认数据完整性
    report = access_control_preflight(dest)
    return _print_preflight(report)


def cmd_rollback_backfill(args: argparse.Namespace) -> int:
    path = args.database or _resolve_db_path()
    deleted = rollback_access_control_backfill(path)
    print(f"[rollback-backfill] batch={ACCESS_CONTROL_MIGRATION_BATCH}")
    for table, count in deleted.items():
        print(f"                    {table}: {count} rows deleted")
    return 0


def cmd_drill(args: argparse.Namespace) -> int:
    """完整演练：备份 -> 预检 -> 回滚 backfill -> 预检 -> 恢复 -> 预检。"""
    print("=== 备份恢复演练开始 ===")
    path = args.database or _resolve_db_path()
    if not os.path.exists(path):
        print(f"[drill] 数据库不存在: {path}，演练跳过（新库无需迁移）")
        return 0

    # 1. 备份
    backup_ns = argparse.Namespace(database=path, dest_dir=args.dest_dir)
    rc = cmd_backup(backup_ns)
    if rc != 0:
        return rc

    # 找到刚创建的备份
    dest_dir = args.dest_dir or os.path.join(DATABASE_DIR, "backups")
    backups = sorted(
        (os.path.join(dest_dir, f) for f in os.listdir(dest_dir) if f.endswith(".db")),
        key=os.path.getmtime,
    )
    if not backups:
        print("[drill] 备份文件未找到，演练中止")
        return 1
    latest = backups[-1]
    print(f"[drill] 使用备份: {latest}")

    # 2. 预检（备份前状态）
    print("--- 预检（当前）---")
    cmd_preflight(argparse.Namespace(database=path))

    # 3. 回滚 backfill（模拟部署回滚）
    print("--- 回滚 backfill（演练）---")
    cmd_rollback_backfill(argparse.Namespace(database=path))

    # 4. 预检（回滚后）
    print("--- 预检（回滚后）---")
    cmd_preflight(argparse.Namespace(database=path))

    # 5. 恢复
    print("--- 恢复（演练）---")
    cmd_restore(argparse.Namespace(backup_file=latest, database=path, force=True))

    # 6. 预检（恢复后）
    print("--- 预检（恢复后）---")
    rc = cmd_preflight(argparse.Namespace(database=path))
    print("=== 备份恢复演练结束 ===")
    return rc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="访问控制运维 CLI")
    parser.add_argument(
        "--database",
        default=None,
        help="目标 SQLite 数据库路径（默认使用配置的 DATABASE_URL）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_pre = sub.add_parser("preflight", help="运行 access_control_preflight")
    p_pre.set_defaults(func=cmd_preflight)

    p_bak = sub.add_parser("backup", help="备份数据库")
    p_bak.add_argument("--dest-dir", default=None, help="备份目录")
    p_bak.set_defaults(func=cmd_backup)

    p_rest = sub.add_parser("restore", help="从备份恢复数据库")
    p_rest.add_argument("backup_file", help="备份文件路径")
    p_rest.add_argument("--force", action="store_true", help="覆盖已存在的目标")
    p_rest.set_defaults(func=cmd_restore)

    p_rb = sub.add_parser("rollback-backfill", help="回滚 access-control-v1 backfill")
    p_rb.set_defaults(func=cmd_rollback_backfill)

    p_drill = sub.add_parser("drill", help="完整备份->预检->回滚->恢复演练")
    p_drill.add_argument("--dest-dir", default=None, help="备份目录")
    p_drill.set_defaults(func=cmd_drill)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
