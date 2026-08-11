"""PostgreSQL-only verification for the audited SQLite transfer command.

These tests are deliberately opt-in because they need an isolated PostgreSQL
database whose user can create/drop a schema and temporarily set
``session_replication_role``.  They never use the application's SQLite file or
any configured deployment database.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from argparse import Namespace
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.scripts import sqlite_to_postgres as transfer
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UnicodeText,
    create_engine,
    func,
    select,
    text,
)
from sqlalchemy import Enum as SAEnum


def test_snapshot_records_backup_api_attestation(tmp_path, monkeypatch):
    """A raw source becomes transferable only through the Backup API command."""
    source_path = tmp_path / "source.sqlite"
    with sqlite3.connect(source_path) as connection:
        connection.execute("CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO probe(value) VALUES ('中文')")

    batch_id = "snapshot-attestation"
    report_root = tmp_path / "reports"
    monkeypatch.setenv("AI_COURSE_SQLITE_SOURCE_PATH", str(source_path))
    monkeypatch.setenv("AI_COURSE_MIGRATION_REPORT_DIR", str(report_root))
    assert transfer.cmd_snapshot(Namespace(batch_id=batch_id, replace=False)) == 0

    snapshot_path = report_root / batch_id / "source.sqlite"
    checksum = transfer._sha256_file(snapshot_path)
    checks = transfer._sqlite_snapshot_checks(snapshot_path)
    transfer._validate_snapshot_attestation(batch_id, snapshot_path, checksum, checks)
    attestation = json.loads((report_root / batch_id / "snapshot.json").read_text(encoding="utf-8"))
    assert attestation["method"] == "sqlite_backup_api"
    assert "source_path" not in attestation


def _postgres_url_or_skip() -> str:
    url = os.environ.get("AI_COURSE_TEST_POSTGRES_URL", "")
    if not url:
        pytest.skip("AI_COURSE_TEST_POSTGRES_URL is required")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - a test dependency is unavailable
        pytest.skip(f"PostgreSQL test database unavailable: {type(exc).__name__}")
    finally:
        engine.dispose()
    return url


def _alembic_config(database_url: str) -> Config:
    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _run_alembic(database_url: str, operation: str, revision: str) -> None:
    old_url = os.environ.get("AI_COURSE_DATABASE_URL")
    os.environ["AI_COURSE_DATABASE_URL"] = database_url
    try:
        getattr(command, operation)(_alembic_config(database_url), revision)
    finally:
        if old_url is None:
            os.environ.pop("AI_COURSE_DATABASE_URL", None)
        else:
            os.environ["AI_COURSE_DATABASE_URL"] = old_url


def _upgrade_to_head(database_url: str) -> None:
    _run_alembic(database_url, "upgrade", "head")


def test_revision_0047_sqlite_downgrade_upgrade_is_reentrant(tmp_path):
    """The lease-index repair upgrades, downgrades and upgrades on SQLite."""
    database_path = tmp_path / "0047-roundtrip.sqlite"
    database_url = f"sqlite:///{database_path.as_posix()}"
    _upgrade_to_head(database_url)
    _run_alembic(database_url, "downgrade", "0046")
    _run_alembic(database_url, "upgrade", "0047")
    _run_alembic(database_url, "upgrade", "0047")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            index_sql = connection.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = 'uq_course_draft_build_active_course'"
                )
            ).scalar_one()
        assert "WHERE status IN ('queued', 'running')" in index_sql
    finally:
        engine.dispose()


def _reset_postgres_public_schema(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.execute(text("GRANT ALL ON SCHEMA public TO PUBLIC"))
    finally:
        engine.dispose()


def test_empty_schema_transfer_plan_copy_and_verify(tmp_path, monkeypatch):
    """A real empty PostgreSQL reaches 0047 and accepts a complete dry copy."""
    postgres_url = _postgres_url_or_skip()
    _reset_postgres_public_schema(postgres_url)
    _upgrade_to_head(postgres_url)

    source_path = tmp_path / "source.sqlite"
    source_url = f"sqlite:///{source_path.as_posix()}"
    _upgrade_to_head(source_url)

    batch_id = "test-empty-0047"
    report_root = tmp_path / "reports"
    monkeypatch.setenv("AI_COURSE_SQLITE_SOURCE_PATH", str(source_path))
    monkeypatch.setenv("AI_COURSE_MIGRATION_REPORT_DIR", str(report_root))
    assert transfer.cmd_snapshot(Namespace(batch_id=batch_id, replace=False)) == 0

    snapshot_path = report_root / batch_id / "source.sqlite"
    monkeypatch.setenv("AI_COURSE_SQLITE_SNAPSHOT_PATH", str(snapshot_path))
    monkeypatch.setenv("AI_COURSE_POSTGRES_TARGET_URL", postgres_url)
    assert transfer.cmd_plan(Namespace(batch_id=batch_id)) == 0
    assert transfer.cmd_copy(Namespace(batch_id=batch_id, allow_replica_role=True)) == 0
    assert transfer.cmd_verify(Namespace(batch_id=batch_id)) == 0

    report = json.loads((report_root / batch_id / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "verified"
    assert report["source_summaries"] == report["target_summaries"]
    assert all(count == 0 for count in report["foreign_key_violations"].values())


def test_copy_normalizes_legacy_types_and_rolls_back_invalid_enum(tmp_path):
    """Probe bool/JSON/enum/time/binary/Unicode/NULL plus cyclic FK copying."""
    postgres_url = _postgres_url_or_skip()
    suffix = uuid.uuid4().hex[:12]
    data_name = f"sqlite_transfer_probe_{suffix}"
    left_name = f"sqlite_transfer_left_{suffix}"
    right_name = f"sqlite_transfer_right_{suffix}"
    bad_name = f"sqlite_transfer_bad_{suffix}"
    enum_name = f"sqlite_transfer_state_{suffix}"

    source_path = tmp_path / "probe.sqlite"
    source_engine = create_engine(f"sqlite:///{source_path.as_posix()}")
    target_engine = create_engine(postgres_url, pool_pre_ping=True)
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_data = Table(
        data_name,
        source_metadata,
        *[
            # SQLite uses integer/text storage for these historical values.
            Column("id", Integer, primary_key=True),
            Column("enabled", Integer, nullable=False),
            Column("payload", Text, nullable=True),
            Column("state", Text, nullable=False),
            Column("occurred_at", Text, nullable=True),
            Column("binary_payload", LargeBinary, nullable=True),
            Column("note", Text, nullable=True),
        ],
    )
    source_left = Table(
        left_name,
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "right_id",
            Integer,
            ForeignKey(f"{right_name}.id", name=f"fk_{left_name}_right"),
            nullable=True,
        ),
    )
    source_right = Table(
        right_name,
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "left_id",
            Integer,
            ForeignKey(f"{left_name}.id", name=f"fk_{right_name}_left"),
            nullable=True,
        ),
    )
    source_bad = Table(
        bad_name,
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("state", Text, nullable=False),
    )

    state_enum = SAEnum("queued", "running", name=enum_name)
    target_data = Table(
        data_name,
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column("enabled", Boolean, nullable=False),
        Column("payload", JSON, nullable=True),
        Column("state", state_enum, nullable=False),
        Column("occurred_at", DateTime(timezone=True), nullable=True),
        Column("binary_payload", LargeBinary, nullable=True),
        Column("note", UnicodeText, nullable=True),
    )
    target_left = Table(
        left_name,
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "right_id",
            Integer,
            ForeignKey(f"{right_name}.id", name=f"fk_{left_name}_right"),
            nullable=True,
        ),
    )
    target_right = Table(
        right_name,
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "left_id",
            Integer,
            ForeignKey(f"{left_name}.id", name=f"fk_{right_name}_left"),
            nullable=True,
        ),
    )
    target_bad = Table(
        bad_name,
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column("state", state_enum, nullable=False),
    )

    source_metadata.create_all(source_engine)
    target_metadata.create_all(target_engine)
    try:
        with source_engine.begin() as connection:
            connection.execute(
                source_data.insert(),
                [
                    {
                        "id": 7,
                        "enabled": 1,
                        "payload": '{"topic":"中文","n":null}',
                        "state": "queued",
                        "occurred_at": "2026-08-11T09:30:00",
                        "binary_payload": b"\\x00binary",
                        "note": "Unicode: 汽车工程",
                    },
                    {
                        "id": 8,
                        "enabled": 0,
                        "payload": None,
                        "state": "running",
                        "occurred_at": None,
                        "binary_payload": None,
                        "note": None,
                    },
                ],
            )
            connection.execute(source_left.insert().values(id=1, right_id=1))
            connection.execute(source_right.insert().values(id=1, left_id=1))
            connection.execute(source_bad.insert().values(id=1, state="not-a-real-state"))

        source_tables = {
            data_name: source_data,
            left_name: source_left,
            right_name: source_right,
            bad_name: source_bad,
        }
        target_tables = {
            data_name: target_data,
            left_name: target_left,
            right_name: target_right,
            bad_name: target_bad,
        }
        with source_engine.connect() as source_connection, target_engine.begin() as target_connection:
            target_connection.execute(text("SET LOCAL session_replication_role = replica"))
            transfer._copy_table(source_connection, target_connection, source_data, target_data)
            transfer._copy_table(source_connection, target_connection, source_left, target_left)
            transfer._copy_table(source_connection, target_connection, source_right, target_right)
            source_summary = transfer._all_summaries(
                source_connection,
                [data_name, left_name, right_name],
                source_tables,
                target_tables,
                "test-batch",
            )
            target_summary = transfer._all_summaries(
                target_connection,
                [data_name, left_name, right_name],
                target_tables,
                target_tables,
                "test-batch",
            )
            assert source_summary == target_summary
            assert all(value == 0 for value in transfer._foreign_key_violations(target_connection, target_tables).values())

        # Keep pytest.raises outside the transaction context so the exception
        # reaches ``begin`` and causes a real rollback before it is asserted.
        with source_engine.connect() as source_connection, pytest.raises(transfer.TransferError):  # noqa: SIM117
            with target_engine.begin() as target_connection:
                transfer._copy_table(source_connection, target_connection, source_data, target_data)
                transfer._copy_table(source_connection, target_connection, source_bad, target_bad)
        with target_engine.connect() as connection:
            assert connection.execute(select(func.count()).select_from(target_bad)).scalar_one() == 0
            assert connection.execute(select(func.count()).select_from(target_data)).scalar_one() == 2
    finally:
        target_metadata.drop_all(target_engine)
        source_metadata.drop_all(source_engine)
        target_engine.dispose()
        source_engine.dispose()
