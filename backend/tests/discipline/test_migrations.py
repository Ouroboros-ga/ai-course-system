"""DK1 迁移验收测试：一次性测试库上升/降级/再升级。

- 升级/降级/再升级按真实前一 migration schema 执行；
- 降级只删除本次新表（部署回滚优先关功能/回切版本保留数据）。
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from test_alembic_migration import _run_alembic

DISCIPLINE_TABLES = {
    "discipline_document_versions",
    "discipline_chunks",
    "discipline_concepts",
    "discipline_aliases",
    "discipline_mentions",
    "discipline_assertions",
    "discipline_supports",
    "discipline_builds",
    "discipline_work_items",
    "discipline_decisions",
    "discipline_releases",
    "discipline_release_items",
    "discipline_heads",
    "discipline_corpus_vectors",
    "discipline_corpus_index_members",
}


def _script() -> ScriptDirectory:
    backend_root = Path(__file__).resolve().parent.parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return ScriptDirectory.from_config(config)


def _tables(db_url: str) -> set[str]:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_discipline_migration_has_single_head():
    """唯一 head 是硬约束；不绑定具体版本名（新迁移不应改测试）。"""
    heads = list(_script().get_heads())
    assert len(heads) == 1, f"迁移链必须单 head：{heads}"
    assert heads[0].startswith("dk2026")


def test_discipline_migration_upgrade_downgrade_reupgrade(tmp_path):
    db_path = tmp_path / "discipline_dk1.db"
    db_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "upgrade", "head")
    assert DISCIPLINE_TABLES.issubset(_tables(db_url))

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")).scalar() == \
                list(_script().get_heads())[0]
    finally:
        engine.dispose()

    # 降级到前一版本：只删除本次新表
    _run_alembic(db_url, "downgrade", "0068")
    remaining = _tables(db_url)
    assert not (DISCIPLINE_TABLES & remaining)
    assert "users" in remaining
    assert "courses" in remaining

    # 再升级：新表恢复
    _run_alembic(db_url, "upgrade", "head")
    assert DISCIPLINE_TABLES.issubset(_tables(db_url))


def test_workitem_build_scoped_unique_roundtrip(tmp_path):
    """dk20260909v2：work_items 唯一键改 build 级，往返可逆。"""
    db_path = tmp_path / "discipline_dk2.db"
    db_url = f"sqlite:///{db_path}"

    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        names = {tuple(sorted(uq["column_names"]))
                 for uq in inspect(engine).get_unique_constraints(
                     "discipline_work_items")}
        assert ("build_id", "fingerprint", "stage") in names
    finally:
        engine.dispose()

    _run_alembic(db_url, "downgrade", "dk20260909v1")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        names = {tuple(sorted(uq["column_names"]))
                 for uq in inspect(engine).get_unique_constraints(
                     "discipline_work_items")}
        assert ("fingerprint", "stage") in names
    finally:
        engine.dispose()

    _run_alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    try:
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")).scalar() == \
                list(_script().get_heads())[0]
    finally:
        engine.dispose()
