"""Regression coverage for the documented legacy media-release orphan rows."""
from __future__ import annotations

import sqlite3

import pytest

from app.scripts import sqlite_to_postgres as transfer


def _create_media_release_fixture(path, *, legacy_orphan: bool) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE script_nodes (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE media_release_items ("
            "id INTEGER PRIMARY KEY, "
            "node_id INTEGER NOT NULL REFERENCES script_nodes(id)"
            ")"
        )
        connection.execute("INSERT INTO script_nodes(id) VALUES (1)")
        connection.execute("INSERT INTO media_release_items(id, node_id) VALUES (1, 1)")
        if legacy_orphan:
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("INSERT INTO media_release_items(id, node_id) VALUES (2, 999)")


def test_snapshot_checks_preserve_documented_legacy_media_release_orphans(tmp_path):
    """The known stale media reference is counted, not silently discarded."""
    source = tmp_path / "legacy-media.sqlite"
    _create_media_release_fixture(source, legacy_orphan=True)

    checks = transfer._sqlite_snapshot_checks(source)

    assert checks["integrity_check"] == "ok"
    assert checks["foreign_key_violation_count"] == 1
    assert checks["foreign_key_violations"] == {"media_release_items:node_id": 1}


def test_snapshot_checks_reject_unexpected_legacy_foreign_key_orphans(tmp_path):
    """Only the explicitly documented legacy relation may contain old orphans."""
    source = tmp_path / "unexpected-legacy.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        connection.execute(
            "CREATE TABLE children (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parents(id))"
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("INSERT INTO children(id, parent_id) VALUES (1, 999)")

    with pytest.raises(transfer.TransferError, match="unexpected foreign-key violation"):
        transfer._sqlite_snapshot_checks(source)


def test_foreign_key_verification_requires_legacy_orphan_counts_to_match_source():
    """A transfer cannot add, remove, or move tolerated historical orphans."""
    expected = {"media_release_items:node_id": 14}

    transfer._assert_foreign_key_violation_parity(expected, expected)

    with pytest.raises(transfer.TransferError, match="foreign-key verification mismatch"):
        transfer._assert_foreign_key_violation_parity(expected, {"media_release_items:node_id": 13})
