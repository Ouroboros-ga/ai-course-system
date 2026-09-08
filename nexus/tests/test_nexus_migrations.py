"""Nexus 域显式迁移（任务书 T2／P2 §9.7：显式、可重入、带回退说明，不写启动时DDL）。

契约：
- 迁移文件按版本序应用；已应用的不重复执行；已应用文件内容漂移即拒绝；
- 逐文件事务，失败回滚；
- dry-run / --status 不改库；
- **源码守卫**：`nexus/src/nexus/` 下不得出现建表/改列 DDL（只允许注释提及）。
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEXUS_SRC = REPO_ROOT / "nexus" / "src" / "nexus"
MIGRATIONS_DIR = REPO_ROOT / "nexus" / "migrations"


@pytest.fixture()
def mig_dir():
    """系统临时目录（本机 pytest tmp 根目录无权限，不用 tmp_path）。"""
    path = Path(tempfile.mkdtemp(prefix="nexus-mig-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _load_runner():
    """importlib 加载 scripts/apply_nexus_migrations.py（scripts 非包）。"""
    path = REPO_ROOT / "nexus" / "scripts" / "apply_nexus_migrations.py"
    spec = importlib.util.spec_from_file_location("apply_nexus_migrations", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        self.conn.executed.append((str(sql), params))
        if "SELECT version, checksum" in str(sql):
            self._rows = list(self.conn.applied_rows)
        return None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, applied_rows=()):
        self.executed: list[tuple] = []
        self.applied_rows = list(applied_rows)
        self.commits = 0
        self.rollbacks = 0
        self.fail_on: str | None = None

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_plan_orders_and_skips_applied(mig_dir):
    runner = _load_runner()
    (mig_dir / "0002_b.sql").write_text("SELECT 2;", encoding="utf-8")
    (mig_dir / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    files = runner.discover(mig_dir)
    assert [v for v, _ in files] == ["0001_a", "0002_b"]
    assert runner.plan({"0001_a": runner.checksum("SELECT 1;")}, files) == ["0002_b"]


def test_checksum_drift_rejected(mig_dir):
    runner = _load_runner()
    (mig_dir / "0001_a.sql").write_text("SELECT changed;", encoding="utf-8")
    files = runner.discover(mig_dir)
    with pytest.raises(runner.MigrationError) as exc:
        runner.plan({"0001_a": runner.checksum("SELECT original;")}, files)
    assert exc.value.code == "CHECKSUM_DRIFT"


def test_run_applies_pending_and_records_ledger(mig_dir):
    runner = _load_runner()
    (mig_dir / "0001_a.sql").write_text(
        "CREATE TABLE IF NOT EXISTS {schema}.t1 (id INT);", encoding="utf-8")
    (mig_dir / "0002_b.sql").write_text(
        "ALTER TABLE {schema}.t1 ADD COLUMN IF NOT EXISTS n INT;", encoding="utf-8")
    conn = _FakeConn()
    result = runner.run(conn, "nexus_checkpoints", mig_dir)
    assert result["applied"] == ["0001_a", "0002_b"]
    assert result["pending"] == ["0001_a", "0002_b"]
    sqls = [sql for sql, _ in conn.executed]
    assert any("CREATE TABLE IF NOT EXISTS nexus_checkpoints.t1" in s for s in sqls)
    assert any("ALTER TABLE nexus_checkpoints.t1" in s for s in sqls)
    assert sum("INSERT INTO nexus_checkpoints.nexus_schema_migrations" in s
               for s in sqls) == 2
    assert conn.commits == 2, "逐文件提交"
    assert "{schema}" not in " ".join(sqls), "占位符必须被替换"


def test_run_skips_applied_versions(mig_dir):
    runner = _load_runner()
    (mig_dir / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    (mig_dir / "0002_b.sql").write_text("SELECT 2;", encoding="utf-8")
    conn = _FakeConn(applied_rows=[("0001_a", runner.checksum("SELECT 1;"))])
    result = runner.run(conn, "s", mig_dir)
    assert result["applied"] == ["0002_b"]
    assert result["skipped"] == ["0001_a"]
    assert not any("SELECT 1;" == sql for sql, _ in conn.executed)


def test_run_dry_run_does_not_write(mig_dir):
    runner = _load_runner()
    (mig_dir / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = _FakeConn()
    result = runner.run(conn, "s", mig_dir, dry_run=True)
    assert result["pending"] == ["0001_a"] and result["applied"] == []
    assert conn.commits == 0
    assert not any("SELECT 1;" == sql for sql, _ in conn.executed)


def test_run_failure_rolls_back(mig_dir):
    runner = _load_runner()
    (mig_dir / "0001_a.sql").write_text("SELECT 1;", encoding="utf-8")
    conn = _FakeConn()

    class _BoomCursor(_FakeCursor):
        def execute(self, sql, params=None):
            if "SELECT 1;" == str(sql):
                raise RuntimeError("boom")
            return super().execute(sql, params)

    conn.cursor = lambda: _BoomCursor(conn)
    with pytest.raises(runner.MigrationError) as exc:
        runner.run(conn, "s", mig_dir)
    assert exc.value.code == "MIGRATION_FAILED"
    assert conn.rollbacks == 1


def test_baseline_covers_all_expected_tables():
    """基线必须覆盖 persistence.NEXUS_TABLES，且全部语句幂等。"""
    sys.path.insert(0, str(REPO_ROOT / "nexus" / "src"))
    from nexus.persistence import NEXUS_TABLES

    text = (MIGRATIONS_DIR / "0001_nexus_baseline.sql").read_text(encoding="utf-8")
    for table in NEXUS_TABLES:
        assert f"nexus_checkpoints" not in text or True  # 占位符形式，下面查表名
        assert f".{table} (" in text or f".{table}\n" in text, f"基线缺表 {table}"
    statements = [s.strip() for s in text.split(";") if s.strip()
                  and not s.strip().startswith("--")]
    assert statements, "基线不应为空"
    for statement in statements:
        head = statement.lstrip().upper()
        if head.startswith("--"):
            continue
        assert "IF NOT EXISTS" in head, f"非幂等语句：{statement[:80]}"


def test_no_startup_ddl_in_nexus_sources():
    """源码守卫：Nexus 运行时不得再出现建表/改列 DDL（注释除外）。"""
    offenders: list[str] = []
    for path in NEXUS_SRC.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            upper = stripped.upper()
            if any(token in upper for token in (
                    "CREATE TABLE", "ADD COLUMN", "CREATE SCHEMA")):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert not offenders, f"启动时 DDL 残留：{offenders}"
