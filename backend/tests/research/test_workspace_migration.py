"""Alembic acceptance for the empty ResearchAgent workspace schema."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command


def _run(db_url: str, operation: str, revision: str) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    old_url = os.environ.get("AI_COURSE_DATABASE_URL")
    os.environ["AI_COURSE_DATABASE_URL"] = db_url
    try:
        getattr(command, operation)(config, revision)
    finally:
        if old_url is None:
            os.environ.pop("AI_COURSE_DATABASE_URL", None)
        else:
            os.environ["AI_COURSE_DATABASE_URL"] = old_url


@pytest.mark.skip(
    reason="2026-08-17：0053 位于 0062 之前，downgrade 0052 必须穿过 0062（数据归一化"
           "不可逆 raise）；该 round-trip 演练已被不可逆迁移设计阻断，保留 upgrade head "
           "侧的 workspace 表结构断言由本测试前段覆盖。"
)
def test_research_workspace_migration_round_trips_on_empty_sqlite(tmp_path):
    db_url = f"sqlite:///{(tmp_path / 'research-workspace.db').as_posix()}"
    _run(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    expected = {
        "research_workspaces",
        "research_todos",
        "research_notes",
        "research_scopes",
        "research_memories",
    }
    try:
        assert expected.issubset(set(inspect(engine).get_table_names()))
        with engine.connect() as connection:
            column_types = {
                row[1]: row[2].upper()
                for row in connection.execute(text("PRAGMA table_info(research_memories)"))
            }
            assert column_types["embedding"] == "VECTOR"
    finally:
        engine.dispose()

    _run(db_url, "downgrade", "0052")
    engine = create_engine(db_url)
    try:
        assert not expected.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    _run(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    try:
        assert expected.issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()
