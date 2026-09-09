"""Nexus 域显式迁移（任务书 T2／P2 §9.7：显式、可重入、带回退说明，不写启动时DDL）。

用法（在 nexus 项目内，PG 环境）：

    NEXUS_POSTGRES_DSN=postgresql://... NEXUS_POSTGRES_SCHEMA=nexus_checkpoints \
        python scripts/apply_nexus_migrations.py            # 应用未执行的迁移
        python scripts/apply_nexus_migrations.py --status   # 只报告，不改库
        python scripts/apply_nexus_migrations.py --dry-run  # 打印将执行的文件

- 迁移文件：``nexus/migrations/NNNN_*.sql``，按文件名序执行；文件内用 ``{schema}``
  占位 schema（由本脚本替换）；多语句一次执行，逐文件事务。
- ledger：``{schema}.nexus_schema_migrations(version, checksum, applied_at)``；
  已应用文件的校验和漂移即拒绝（禁止修改历史迁移）。
- 退出码：0=成功/无待应用；2=迁移或校验失败；3=未配置 NEXUS_POSTGRES_DSN。

发布链路：``deploy/scripts/smartcarb-release.sh`` 在同步 nexus 代码后、重启
nexus-runtime 之前调用本脚本；失败即中止发布（旧代码仍在服务）。
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

LEDGER_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};
CREATE TABLE IF NOT EXISTS {schema}.nexus_schema_migrations (
    version TEXT PRIMARY KEY,
    checksum TEXT NOT NULL DEFAULT '',
    applied_at DOUBLE PRECISION NOT NULL DEFAULT 0
);
"""


class MigrationError(Exception):
    """迁移域失败：携带机器可读 code。"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def discover(migrations_dir: Path) -> list[tuple[str, Path]]:
    """按文件名序返回 (version, path)；忽略非 .sql 与目录。"""
    files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
    return [(p.stem, p) for p in files]


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan(applied: dict[str, str], files: list[tuple[str, Path]]) -> list[str]:
    """待应用版本（文件序）。已应用但校验和漂移 → MigrationError（禁止改历史迁移）。"""
    pending: list[str] = []
    for version, path in files:
        digest = checksum(path.read_text(encoding="utf-8"))
        if version in applied:
            recorded = applied.get(version) or ""
            if recorded and recorded != digest:
                raise MigrationError(
                    "CHECKSUM_DRIFT",
                    f"{version} 内容与已应用记录不一致（历史迁移不可修改；"
                    "如需变更请新增编号文件）",
                )
            continue
        pending.append(version)
    return pending


def read_applied(cursor: Any, schema: str) -> dict[str, str]:
    cursor.execute(LEDGER_DDL.format(schema=schema))
    cursor.execute(
        f"SELECT version, checksum FROM {schema}.nexus_schema_migrations")
    return {str(row[0]): str(row[1] or "") for row in cursor.fetchall()}


def run(conn: Any, schema: str, migrations_dir: Path, *,
        dry_run: bool = False) -> dict[str, Any]:
    """应用未执行的迁移；返回 {"applied", "pending", "skipped", "dry_run"}。

    conn 为 psycopg 连接（测试可注入伪连接：cursor()/commit()/rollback()）。
    """
    files = discover(migrations_dir)
    with contextlib.closing(conn.cursor()) as cur:
        applied = read_applied(cur, schema)
    pending = plan(applied, files)
    applied_now: list[str] = []
    if not dry_run:
        for version, path in files:
            if version not in pending:
                continue
            sql = path.read_text(encoding="utf-8").replace("{schema}", schema)
            digest = checksum(path.read_text(encoding="utf-8"))
            try:
                with contextlib.closing(conn.cursor()) as cur:
                    cur.execute(sql)
                    cur.execute(
                        f"INSERT INTO {schema}.nexus_schema_migrations "
                        "(version, checksum, applied_at) VALUES (%s, %s, %s)",
                        (version, digest, time.time()),
                    )
                conn.commit()
            except Exception as error:  # noqa: BLE001 - 逐文件事务，失败即回滚
                conn.rollback()
                raise MigrationError(
                    "MIGRATION_FAILED",
                    f"{version} 执行失败（{type(error).__name__}）：{str(error)[:200]}",
                ) from error
            applied_now.append(version)
    return {
        "applied": applied_now,
        "pending": pending,
        "skipped": [v for v, _ in files if v in applied],
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nexus 域显式迁移")
    parser.add_argument("--dir", default=str(DEFAULT_MIGRATIONS_DIR),
                        help="迁移目录（默认 nexus/migrations）")
    parser.add_argument("--status", action="store_true",
                        help="只报告已应用/待应用，不改库")
    parser.add_argument("--dry-run", action="store_true",
                        help="打印将执行的迁移，不改库")
    args = parser.parse_args(argv)

    dsn = (os.environ.get("NEXUS_POSTGRES_DSN") or "").strip()
    schema = (os.environ.get("NEXUS_POSTGRES_SCHEMA") or "nexus_checkpoints").strip()
    if not dsn:
        print("错误: 未配置 NEXUS_POSTGRES_DSN（Nexus 域迁移需直连其 PG）",
              file=sys.stderr)
        return 3
    try:
        import psycopg

        with psycopg.connect(dsn) as conn:
            result = run(conn, schema, Path(args.dir),
                         dry_run=args.status or args.dry_run)
    except MigrationError as error:
        print(f"错误: {error.code}: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - 连接/未知失败如实报错
        print(f"错误: 迁移失败（{type(error).__name__}）：{str(error)[:200]}",
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
