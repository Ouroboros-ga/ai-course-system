"""Audited one-way transfer from a SQLite snapshot to PostgreSQL.

This tool is intentionally not an application-startup migration.  It is used
only during a scheduled cutover after the target PostgreSQL database has been
created with ``alembic upgrade head``.  It never accepts database URLs on the
command line and never prints them, so credentials remain in server-only
environment files.

Required environment variables for ``plan``, ``copy`` and ``verify``:

* ``AI_COURSE_SQLITE_SNAPSHOT_PATH``: immutable SQLite backup created by this
  tool's ``snapshot`` command;
* ``AI_COURSE_POSTGRES_TARGET_URL``: a PostgreSQL migration-role URL;
* ``AI_COURSE_MIGRATION_REPORT_DIR`` (optional): private report directory.

``copy`` is a single PostgreSQL transaction.  It requires an explicitly
enabled, temporary migration role because ``session_replication_role=replica``
is needed to import a legacy schema with cross-table references.  The script
performs table digests and foreign-key anti-join checks before that transaction
is committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    and_,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.engine import Connection, Engine

SCRIPT_ROOT = Path(__file__).resolve().parents[2]
SKIPPED_SOURCE_TABLES = {"alembic_version", "sqlite_sequence"}
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TRANSFER_NAME = "sqlite-to-postgresql"


class TransferError(RuntimeError):
    """A fail-closed transfer precondition or verification error."""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise TransferError(f"missing required environment variable: {name}")
    return value


def _validate_batch_id(batch_id: str) -> str:
    if not BATCH_ID_PATTERN.fullmatch(batch_id):
        raise TransferError("batch id must contain only letters, digits, '.', '_' or '-'")
    return batch_id


def _snapshot_path() -> Path:
    path = Path(_require_env("AI_COURSE_SQLITE_SNAPSHOT_PATH")).expanduser().resolve()
    if not path.is_file():
        raise TransferError("SQLite snapshot does not exist")
    return path


def _source_path_for_snapshot() -> Path:
    raw_path = os.environ.get("AI_COURSE_SQLITE_SOURCE_PATH", "").strip()
    if raw_path:
        path = Path(raw_path).expanduser().resolve()
    else:
        database_url = os.environ.get("AI_COURSE_DATABASE_URL", "").strip()
        if not database_url.startswith("sqlite:///"):
            raise TransferError(
                "set AI_COURSE_SQLITE_SOURCE_PATH or an sqlite AI_COURSE_DATABASE_URL before snapshot"
            )
        path = Path(database_url.removeprefix("sqlite:///")).expanduser().resolve()
    if not path.is_file():
        raise TransferError("SQLite source database does not exist")
    return path


def _target_url() -> str:
    url = _require_env("AI_COURSE_POSTGRES_TARGET_URL")
    if not url.startswith("postgresql"):
        raise TransferError("AI_COURSE_POSTGRES_TARGET_URL must be a PostgreSQL URL")
    return url


def _report_dir(batch_id: str) -> Path:
    configured = os.environ.get("AI_COURSE_MIGRATION_REPORT_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    else:
        root = _snapshot_path().parent / "migration-reports"
    result = root / batch_id
    result.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(result, 0o700)
    except OSError:
        pass
    return result


def _report_path(batch_id: str) -> Path:
    return _report_dir(batch_id) / "report.json"


def _snapshot_attestation_path(batch_id: str) -> Path:
    return _report_dir(batch_id) / "snapshot.json"


def _read_report(batch_id: str) -> dict[str, Any] | None:
    path = _report_path(batch_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(".json.tmp")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(str(temp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_report(batch_id: str, payload: dict[str, Any]) -> None:
    _write_private_json(_report_path(batch_id), payload)


def _attest_snapshot(batch_id: str, snapshot: Path, source_sha256: str, checks: dict[str, Any]) -> None:
    """Record that this exact file was produced by SQLite's Backup API.

    The attestation contains only the batch id, snapshot file name/checksum and
    integrity result.  It intentionally excludes the source path and all
    business data, but makes a hand-copied arbitrary SQLite file fail closed.
    """
    _write_private_json(
        _snapshot_attestation_path(batch_id),
        {
            "batch_id": batch_id,
            "method": "sqlite_backup_api",
            "snapshot_name": snapshot.name,
            "snapshot_sha256": source_sha256,
            "source_checks": checks,
        },
    )


def _validate_snapshot_attestation(
    batch_id: str,
    snapshot: Path,
    source_sha256: str,
    checks: dict[str, Any],
) -> None:
    path = _snapshot_attestation_path(batch_id)
    if not path.is_file():
        raise TransferError("SQLite snapshot is missing its Backup API attestation")
    try:
        attestation = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TransferError("SQLite snapshot attestation is unreadable") from exc
    expected_path = path.parent / str(attestation.get("snapshot_name") or "")
    if snapshot != expected_path.resolve():
        raise TransferError("SQLite snapshot path does not match its batch attestation")
    if attestation.get("batch_id") != batch_id or attestation.get("method") != "sqlite_backup_api":
        raise TransferError("SQLite snapshot attestation has an invalid method or batch id")
    if attestation.get("snapshot_sha256") != source_sha256:
        raise TransferError("SQLite snapshot checksum does not match its Backup API attestation")
    if attestation.get("source_checks") != checks:
        raise TransferError("SQLite snapshot integrity result does not match its attestation")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_snapshot_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    """Open a source/snapshot without any possibility of SQLite writes."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _sqlite_snapshot_checks(path: Path) -> dict[str, Any]:
    connection = _open_sqlite_read_only(path)
    try:
        integrity_rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]
        foreign_key_rows = list(connection.execute("PRAGMA foreign_key_check"))
    finally:
        connection.close()
    if integrity_rows != ["ok"]:
        raise TransferError("SQLite integrity_check failed")
    if foreign_key_rows:
        raise TransferError(f"SQLite foreign_key_check found {len(foreign_key_rows)} violation(s)")
    return {"integrity_check": "ok", "foreign_key_violation_count": 0}


def _head_revision() -> str:
    """Resolve the single Alembic head without importing app configuration."""
    versions_dir = SCRIPT_ROOT / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for path in versions_dir.glob("*.py"):
        content = path.read_text(encoding="utf-8")
        revision_match = re.search(
            r'^revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']',
            content,
            re.MULTILINE,
        )
        down_match = re.search(
            r'^down_revision(?:\s*:\s*[^=]+)?\s*=\s*(None|["\']([^"\']+)["\'])',
            content,
            re.MULTILINE,
        )
        if revision_match:
            revisions[revision_match.group(1)] = (
                down_match.group(2) if down_match and down_match.group(2) else None
            )
    parents = {revision for revision in revisions.values() if revision}
    heads = sorted(revision for revision in revisions if revision not in parents)
    if len(heads) != 1:
        raise TransferError("Alembic history must have exactly one head")
    return heads[0]


def _application_table_names(inspector) -> list[str]:
    return sorted(name for name in inspector.get_table_names() if name not in SKIPPED_SOURCE_TABLES)


def _schema_fingerprint(inspector, table_names: Iterable[str]) -> str:
    definition: list[dict[str, Any]] = []
    for table_name in sorted(table_names):
        columns = [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": bool(column.get("nullable", False)),
                "default": str(column.get("default") or ""),
            }
            for column in inspector.get_columns(table_name)
        ]
        foreign_keys = [
            {
                "columns": list(item.get("constrained_columns") or []),
                "target": item.get("referred_table") or "",
                "target_columns": list(item.get("referred_columns") or []),
            }
            for item in inspector.get_foreign_keys(table_name)
        ]
        definition.append(
            {
                "table": table_name,
                "columns": columns,
                "primary_key": list(inspector.get_pk_constraint(table_name).get("constrained_columns") or []),
                "foreign_keys": sorted(foreign_keys, key=lambda item: json.dumps(item, sort_keys=True)),
            }
        )
    raw = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_tables(engine: Engine, table_names: Iterable[str]) -> dict[str, Table]:
    metadata = MetaData()
    metadata.reflect(bind=engine, only=list(table_names), resolve_fks=True)
    missing = sorted(set(table_names) - set(metadata.tables))
    if missing:
        raise TransferError(f"could not reflect {len(missing)} table(s)")
    return {name: metadata.tables[name] for name in table_names}


def _target_preflight(source_engine: Engine, target_engine: Engine) -> tuple[list[str], str]:
    source_inspector = inspect(source_engine)
    target_inspector = inspect(target_engine)
    source_tables = _application_table_names(source_inspector)
    target_tables = _application_table_names(target_inspector)
    missing = sorted(set(source_tables) - set(target_tables))
    if missing:
        raise TransferError(f"PostgreSQL schema is missing {len(missing)} source table(s)")
    unexpected = sorted(set(target_tables) - set(source_tables))
    if unexpected:
        raise TransferError(f"PostgreSQL schema has {len(unexpected)} unexpected application table(s)")

    with target_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != _head_revision():
        raise TransferError("PostgreSQL target is not at this codebase's Alembic head")

    target_table_map = _load_tables(target_engine, target_tables)
    with target_engine.connect() as connection:
        nonempty = [
            table_name
            for table_name, table in target_table_map.items()
            if connection.execute(select(func.count()).select_from(table)).scalar_one() > 0
        ]
    if nonempty:
        raise TransferError("PostgreSQL target must be empty before copy")
    return source_tables, _schema_fingerprint(target_inspector, target_tables)


def _coerce_datetime(value: Any, column_type: DateTime) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise TransferError("could not parse a legacy datetime value") from exc
    if not isinstance(value, datetime):
        raise TransferError("datetime column contains a non-datetime value")
    if column_type.timezone:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _coerce_value(value: Any, target_column) -> Any:
    if value is None:
        return None
    column_type = target_column.type
    if isinstance(column_type, JSON):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise TransferError(f"invalid JSON in {target_column.table.name}.{target_column.name}") from exc
        return value
    if isinstance(column_type, Boolean):
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in {"0", "1", "true", "false"}:
            return value.strip().lower() in {"1", "true"}
        raise TransferError(f"invalid boolean in {target_column.table.name}.{target_column.name}")
    if isinstance(column_type, DateTime):
        return _coerce_datetime(value, column_type)
    if isinstance(column_type, SAEnum):
        candidate = value.value if hasattr(value, "value") else str(value)
        allowed = set(column_type.enums or [])
        if allowed and candidate not in allowed:
            raise TransferError(f"invalid enum value in {target_column.table.name}.{target_column.name}")
        return candidate
    if isinstance(column_type, LargeBinary) and isinstance(value, memoryview):
        return value.tobytes()
    return value


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TransferError("non-finite floating point values cannot be verified safely")
        return {"float": repr(value)}
    if isinstance(value, Decimal):
        return {"decimal": format(value, "f")}
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return {"datetime": value.isoformat(timespec="microseconds")}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, time):
        return {"time": value.isoformat(timespec="microseconds")}
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        return {"binary_sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    if isinstance(value, UUID):
        return {"uuid": str(value)}
    if hasattr(value, "value"):
        return _canonical_value(value.value)
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    return {"repr": str(value)}


def _ordered_select(table: Table):
    statement = select(table)
    primary_key_columns = list(table.primary_key.columns)
    if primary_key_columns:
        statement = statement.order_by(*primary_key_columns)
    else:
        statement = statement.order_by(*table.columns)
    return statement


def _ensure_equal_columns(source_table: Table, target_table: Table) -> None:
    source_columns = set(source_table.c.keys())
    target_columns = set(target_table.c.keys())
    if source_columns != target_columns:
        raise TransferError(f"column set differs for table {target_table.name}")


def _table_summary(
    connection: Connection,
    table: Table,
    *,
    target_table: Table,
    transfer_batch_id: str,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    null_counts = {column.name: 0 for column in target_table.columns}
    primary_keys = [column.name for column in target_table.primary_key.columns]
    first_primary_key: list[Any] | None = None
    last_primary_key: list[Any] | None = None
    statement = _ordered_select(table)
    if table.name == "schema_migration_records" and "batch_id" in table.c:
        statement = statement.where(table.c.batch_id != transfer_batch_id)
    rows = connection.execute(statement).mappings()
    for row in rows:
        # Both source and target values are normalized through the target
        # column contract.  This deliberately collapses SQLite integer booleans,
        # textual JSON and legacy datetimes onto PostgreSQL's representation
        # before computing an equality digest.
        normalized = {
            column.name: _coerce_value(row[column.name], column)
            for column in target_table.columns
        }
        for column_name, value in normalized.items():
            if value is None:
                null_counts[column_name] += 1
        canonical_row = {name: _canonical_value(value) for name, value in normalized.items()}
        digest.update(json.dumps(canonical_row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        if primary_keys:
            primary_key = [canonical_row[column_name] for column_name in primary_keys]
            if first_primary_key is None:
                first_primary_key = primary_key
            last_primary_key = primary_key
        count += 1
    return {
        "row_count": count,
        "null_counts": null_counts,
        "primary_key_first": first_primary_key,
        "primary_key_last": last_primary_key,
        "sha256": digest.hexdigest(),
    }


def _all_summaries(
    connection: Connection,
    table_names: Iterable[str],
    tables: dict[str, Table],
    target_tables: dict[str, Table],
    transfer_batch_id: str,
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for table_name in table_names:
        source_table = tables[table_name]
        target_table = target_tables[table_name]
        _ensure_equal_columns(source_table, target_table)
        summaries[table_name] = _table_summary(
            connection,
            source_table,
            target_table=target_table,
            transfer_batch_id=transfer_batch_id,
        )
    return summaries


def _copy_table(
    source_connection: Connection,
    target_connection: Connection,
    source_table: Table,
    target_table: Table,
    *,
    batch_size: int = 1000,
) -> int:
    _ensure_equal_columns(source_table, target_table)
    copied = 0
    batch: list[dict[str, Any]] = []
    for row in source_connection.execute(_ordered_select(source_table)).mappings():
        batch.append(
            {
                column.name: _coerce_value(row[column.name], column)
                for column in target_table.columns
            }
        )
        if len(batch) >= batch_size:
            target_connection.execute(target_table.insert(), batch)
            copied += len(batch)
            batch.clear()
    if batch:
        target_connection.execute(target_table.insert(), batch)
        copied += len(batch)
    return copied


def _reset_sequences(connection: Connection, table_names: Iterable[str], tables: dict[str, Table]) -> None:
    """Advance PostgreSQL serial/identity sequences after explicit PK inserts."""
    for table_name in table_names:
        table = tables[table_name]
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1 or not isinstance(primary_keys[0].type, Integer):
            continue
        primary_key = primary_keys[0]
        sequence_name = connection.execute(
            text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
            {"table_name": table_name, "column_name": primary_key.name},
        ).scalar_one_or_none()
        if not sequence_name:
            continue
        maximum = connection.execute(select(func.max(table.c[primary_key.name]))).scalar_one()
        if maximum is None:
            connection.execute(
                text("SELECT setval(CAST(:sequence_name AS regclass), 1, false)"),
                {"sequence_name": sequence_name},
            )
        else:
            connection.execute(
                text("SELECT setval(CAST(:sequence_name AS regclass), :value, true)"),
                {"sequence_name": sequence_name, "value": int(maximum)},
            )


def _foreign_key_violations(connection: Connection, tables: dict[str, Table]) -> dict[str, int]:
    violations: dict[str, int] = {}
    for table_name, child_table in tables.items():
        for foreign_key in child_table.foreign_key_constraints:
            parent_table = foreign_key.referred_table
            if parent_table is None or parent_table.name not in tables:
                continue
            parent_table = tables[parent_table.name]
            pairs = [
                (child_column.name, parent_column.name)
                for child_column, parent_column in zip(
                    foreign_key.columns,
                    foreign_key.referred_columns,
                    strict=True,
                )
            ]
            if not pairs:
                continue
            join_condition = and_(*[
                child_table.c[child_name] == parent_table.c[parent_name]
                for child_name, parent_name in pairs
            ])
            child_present = and_(*[child_table.c[child_name].is_not(None) for child_name, _ in pairs])
            parent_missing = parent_table.c[pairs[0][1]].is_(None)
            count = connection.execute(
                select(func.count())
                .select_from(child_table.outerjoin(parent_table, join_condition))
                .where(child_present, parent_missing)
            ).scalar_one()
            key = f"{table_name}:{','.join(name for name, _ in pairs)}"
            violations[key] = int(count)
    return violations


def _assert_matching_summaries(source: dict[str, Any], target: dict[str, Any]) -> None:
    if source.keys() != target.keys():
        raise TransferError("source and target table sets differ during verification")
    mismatched = [name for name in source if source[name] != target[name]]
    if mismatched:
        raise TransferError(f"row summary mismatch in {len(mismatched)} table(s)")


def _ledger_record(connection: Connection, table: Table, batch_id: str, copied_rows: int, source_sha256: str) -> None:
    now = datetime.now(UTC)
    connection.execute(
        table.insert().values(
            batch_id=batch_id,
            name=TRANSFER_NAME,
            applied_at=now,
            status="applied",
            rollback_notes=f"SQLite snapshot sha256={source_sha256}; rollback is environment switch before traffic resumes.",
            preflight_ok=True,
            applied_rows=copied_rows,
            operator_user_id=None,
            created_at=now,
        )
    )


def _new_report(batch_id: str, snapshot: Path, source_sha256: str, target_schema_sha256: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "transfer": TRANSFER_NAME,
        "source_snapshot_name": snapshot.name,
        "source_sha256": source_sha256,
        "target_schema_sha256": target_schema_sha256,
        "target_alembic_revision": _head_revision(),
        "status": "planned",
    }


def _validate_existing_batch(report: dict[str, Any] | None, *, source_sha256: str, target_schema_sha256: str) -> None:
    if report is None:
        return
    if report.get("source_sha256") != source_sha256:
        raise TransferError("batch id is already associated with another SQLite snapshot")
    if report.get("target_schema_sha256") != target_schema_sha256:
        raise TransferError("batch id is already associated with another PostgreSQL schema")


def cmd_snapshot(args: argparse.Namespace) -> int:
    batch_id = _validate_batch_id(args.batch_id)
    source_path = _source_path_for_snapshot()
    report_root = _report_dir(batch_id)
    destination = report_root / "source.sqlite"
    if _read_report(batch_id) is not None:
        raise TransferError("a planned or completed report already exists for this batch")
    if destination.exists() and not args.replace:
        raise TransferError("snapshot already exists for batch; pass --replace only before plan/copy")

    source = _open_sqlite_read_only(source_path)
    destination_connection = sqlite3.connect(destination)
    try:
        source.backup(destination_connection)
    finally:
        destination_connection.close()
        source.close()
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    checks = _sqlite_snapshot_checks(destination)
    _attest_snapshot(batch_id, destination, _sha256_file(destination), checks)
    print(json.dumps({"batch_id": batch_id, "snapshot": destination.name, **checks}, ensure_ascii=False))
    return 0


def _engines_for_transfer() -> tuple[Path, Engine, Engine]:
    snapshot = _snapshot_path()
    return (
        snapshot,
        create_engine(_sqlite_snapshot_url(snapshot), connect_args={"check_same_thread": False}),
        create_engine(_target_url(), pool_pre_ping=True),
    )


def cmd_plan(args: argparse.Namespace) -> int:
    batch_id = _validate_batch_id(args.batch_id)
    snapshot, source_engine, target_engine = _engines_for_transfer()
    try:
        source_sha256 = _sha256_file(snapshot)
        source_checks = _sqlite_snapshot_checks(snapshot)
        _validate_snapshot_attestation(batch_id, snapshot, source_sha256, source_checks)
        source_tables, target_schema_sha256 = _target_preflight(source_engine, target_engine)
        report = _new_report(batch_id, snapshot, source_sha256, target_schema_sha256)
        _validate_existing_batch(_read_report(batch_id), source_sha256=source_sha256, target_schema_sha256=target_schema_sha256)
        source_table_map = _load_tables(source_engine, source_tables)
        target_table_map = _load_tables(target_engine, source_tables)
        with source_engine.connect() as connection:
            report["source_summaries"] = _all_summaries(
                connection,
                source_tables,
                source_table_map,
                target_table_map,
                batch_id,
            )
        report["source_checks"] = source_checks
        report["source_table_count"] = len(source_tables)
        report["status"] = "planned"
        _write_report(batch_id, report)
        print(json.dumps({"batch_id": batch_id, "status": "planned", "table_count": len(source_tables)}, ensure_ascii=False))
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def cmd_copy(args: argparse.Namespace) -> int:
    if not args.allow_replica_role:
        raise TransferError("copy requires --allow-replica-role and a temporary PostgreSQL migration role")
    batch_id = _validate_batch_id(args.batch_id)
    snapshot, source_engine, target_engine = _engines_for_transfer()
    try:
        source_sha256 = _sha256_file(snapshot)
        source_checks = _sqlite_snapshot_checks(snapshot)
        _validate_snapshot_attestation(batch_id, snapshot, source_sha256, source_checks)
        source_tables, target_schema_sha256 = _target_preflight(source_engine, target_engine)
        previous_report = _read_report(batch_id)
        _validate_existing_batch(previous_report, source_sha256=source_sha256, target_schema_sha256=target_schema_sha256)
        report = _new_report(batch_id, snapshot, source_sha256, target_schema_sha256)
        source_table_map = _load_tables(source_engine, source_tables)
        target_table_map = _load_tables(target_engine, source_tables)
        with source_engine.connect() as source_connection:
            source_summaries = _all_summaries(
                source_connection,
                source_tables,
                source_table_map,
                target_table_map,
                batch_id,
            )
            copied_rows = 0
            with target_engine.begin() as target_connection:
                # Requires SUPERUSER.  The scope is this single transaction and
                # all foreign-key anti-joins below must pass before commit.
                target_connection.execute(text("SET LOCAL session_replication_role = replica"))
                for table_name in source_tables:
                    copied_rows += _copy_table(
                        source_connection,
                        target_connection,
                        source_table_map[table_name],
                        target_table_map[table_name],
                    )
                _reset_sequences(target_connection, source_tables, target_table_map)
                target_summaries = _all_summaries(
                    target_connection,
                    source_tables,
                    target_table_map,
                    target_table_map,
                    batch_id,
                )
                _assert_matching_summaries(source_summaries, target_summaries)
                foreign_key_violations = _foreign_key_violations(target_connection, target_table_map)
                failing_foreign_keys = {key: value for key, value in foreign_key_violations.items() if value}
                if failing_foreign_keys:
                    raise TransferError(f"foreign-key verification failed for {len(failing_foreign_keys)} relation(s)")
                _ledger_record(
                    target_connection,
                    target_table_map["schema_migration_records"],
                    batch_id,
                    copied_rows,
                    source_sha256,
                )
        report.update(
            {
                "source_checks": source_checks,
                "source_table_count": len(source_tables),
                "source_summaries": source_summaries,
                "target_summaries": target_summaries,
                "foreign_key_violations": foreign_key_violations,
                "copied_rows": copied_rows,
                "status": "copied",
            }
        )
        _write_report(batch_id, report)
        print(json.dumps({"batch_id": batch_id, "status": "copied", "copied_rows": copied_rows}, ensure_ascii=False))
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def cmd_verify(args: argparse.Namespace) -> int:
    batch_id = _validate_batch_id(args.batch_id)
    snapshot, source_engine, target_engine = _engines_for_transfer()
    try:
        source_sha256 = _sha256_file(snapshot)
        source_checks = _sqlite_snapshot_checks(snapshot)
        _validate_snapshot_attestation(batch_id, snapshot, source_sha256, source_checks)
        source_tables, target_schema_sha256 = _target_preflight_for_verify(source_engine, target_engine)
        report = _read_report(batch_id)
        _validate_existing_batch(report, source_sha256=source_sha256, target_schema_sha256=target_schema_sha256)
        if report is None or report.get("status") not in {"copied", "verified"}:
            raise TransferError("verify requires a successfully copied batch report")
        source_table_map = _load_tables(source_engine, source_tables)
        target_table_map = _load_tables(target_engine, source_tables)
        with source_engine.connect() as source_connection, target_engine.connect() as target_connection:
            source_summaries = _all_summaries(
                source_connection,
                source_tables,
                source_table_map,
                target_table_map,
                batch_id,
            )
            target_summaries = _all_summaries(
                target_connection,
                source_tables,
                target_table_map,
                target_table_map,
                batch_id,
            )
            _assert_matching_summaries(source_summaries, target_summaries)
            foreign_key_violations = _foreign_key_violations(target_connection, target_table_map)
        failing_foreign_keys = {key: value for key, value in foreign_key_violations.items() if value}
        if failing_foreign_keys:
            raise TransferError(f"foreign-key verification failed for {len(failing_foreign_keys)} relation(s)")
        report.update(
            {
                "source_checks": source_checks,
                "source_summaries": source_summaries,
                "target_summaries": target_summaries,
                "foreign_key_violations": foreign_key_violations,
                "status": "verified",
            }
        )
        _write_report(batch_id, report)
        print(json.dumps({"batch_id": batch_id, "status": "verified", "table_count": len(source_tables)}, ensure_ascii=False))
        return 0
    finally:
        source_engine.dispose()
        target_engine.dispose()


def _target_preflight_for_verify(source_engine: Engine, target_engine: Engine) -> tuple[list[str], str]:
    source_inspector = inspect(source_engine)
    target_inspector = inspect(target_engine)
    source_tables = _application_table_names(source_inspector)
    target_tables = _application_table_names(target_inspector)
    missing = sorted(set(source_tables) - set(target_tables))
    if missing:
        raise TransferError(f"PostgreSQL schema is missing {len(missing)} source table(s)")
    unexpected = sorted(set(target_tables) - set(source_tables))
    if unexpected:
        raise TransferError(f"PostgreSQL schema has {len(unexpected)} unexpected application table(s)")
    with target_engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != _head_revision():
        raise TransferError("PostgreSQL target is not at this codebase's Alembic head")
    return source_tables, _schema_fingerprint(target_inspector, target_tables)


def _redact_error(message: str) -> str:
    # Keep a short diagnostic without ever persisting a URL that may contain a
    # password.  SQLAlchemy errors can include the connection string.
    return re.sub(r"postgresql(?:\+[a-z0-9_]+)?://[^\s@]+@", "postgresql://[REDACTED]@", message)[:300]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audited SQLite to PostgreSQL transfer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("snapshot", cmd_snapshot), ("plan", cmd_plan), ("copy", cmd_copy), ("verify", cmd_verify)):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--batch-id", required=True)
        if name == "snapshot":
            subparser.add_argument("--replace", action="store_true")
        if name == "copy":
            subparser.add_argument("--allow-replica-role", action="store_true")
        subparser.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except TransferError as exc:
        print(f"TRANSFER_FAILED: {_redact_error(str(exc))}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001  # pragma: no cover - process safety net
        print(f"TRANSFER_FAILED: {_redact_error(type(exc).__name__ + ': ' + str(exc))}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
