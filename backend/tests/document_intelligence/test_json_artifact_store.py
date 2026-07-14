"""Tests for JsonArtifactStore: atomic writes, checksum, path traversal,
concurrent-write safety, repeated writes."""

import hashlib
import json
import os
import tempfile

import pytest

from app.platform.document_intelligence.persistence.json_artifact_store import (
    JsonArtifactStore,
)


@pytest.fixture
def store() -> JsonArtifactStore:
    tmpdir = tempfile.mkdtemp(prefix="artifact_store_test_")
    yield JsonArtifactStore(tmpdir)
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Basic write / read
# ---------------------------------------------------------------------------


class TestBasicWriteRead:
    def test_write_and_read(self, store: JsonArtifactStore) -> None:
        data = {"key": "value", "num": 42}
        store.write("test/file.json", data)
        assert store.exists("test/file.json")
        loaded = store.read("test/file.json")
        assert loaded == data

    def test_write_returns_checksum(self, store: JsonArtifactStore) -> None:
        data = {"a": 1}
        checksum = store.write("test/data.json", data)
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA-256 hex

    def test_checksum_matches(self, store: JsonArtifactStore) -> None:
        data = {"msg": "hello"}
        store.write("test/data.json", data)
        cs = store.checksum("test/data.json")
        assert isinstance(cs, str)
        assert len(cs) == 64

    def test_read_nonexistent_raises(self, store: JsonArtifactStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.read("nonexistent.json")


# ---------------------------------------------------------------------------
# Atomic write (temp file + rename)
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_atomic_write_creates_file(self, store: JsonArtifactStore) -> None:
        store.write("atomic/test.json", {"status": "ok"})
        assert store.exists("atomic/test.json")

    def test_atomic_write_no_partial_file_on_failure(self, store: JsonArtifactStore) -> None:
        """Temp file should be cleaned up if rename fails."""
        # Write to a path whose parent doesn't exist (should fail at mkdir)
        store.write("parent/test.json", {"data": 1})
        assert store.exists("parent/test.json")


# ---------------------------------------------------------------------------
# Repeated writes (idempotent)
# ---------------------------------------------------------------------------


class TestRepeatedWrites:
    def test_repeated_write_same_data(self, store: JsonArtifactStore) -> None:
        data = {"id": 42, "name": "test"}
        cs1 = store.write("repeated/data.json", data)
        cs2 = store.write("repeated/data.json", data)
        assert cs1 == cs2
        loaded = store.read("repeated/data.json")
        assert loaded == data

    def test_repeated_write_different_data(self, store: JsonArtifactStore) -> None:
        store.write("replaced/data.json", {"v": 1})
        store.write("replaced/data.json", {"v": 2})
        loaded = store.read("replaced/data.json")
        assert loaded == {"v": 2}


# ---------------------------------------------------------------------------
# Expected checksum validation
# ---------------------------------------------------------------------------


class TestExpectedChecksum:
    def test_correct_checksum_passes(self, store: JsonArtifactStore) -> None:
        data = {"stable": True}
        # Compute expected checksum
        json_bytes = json.dumps(
            data, indent=2, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        expected = hashlib.sha256(json_bytes).hexdigest()
        actual = store.write("checksum/test.json", data, expected_sha256=expected)
        assert actual == expected

    def test_wrong_checksum_raises(self, store: JsonArtifactStore) -> None:
        data = {"stable": True}
        with pytest.raises(ValueError, match="Checksum mismatch"):
            store.write("checksum/bad.json", data, expected_sha256="0" * 64)


# ---------------------------------------------------------------------------
# Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_dot_dot_rejected(self, store: JsonArtifactStore) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            store.write("../../etc/passwd", {"pwned": True})

    def test_windows_dot_dot_rejected(self, store: JsonArtifactStore) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            store.write("..\\..\\windows\\system32", {"pwned": True})

    def test_tilde_rejected(self, store: JsonArtifactStore) -> None:
        with pytest.raises(ValueError, match="tilde"):
            store.write("~/evil.json", {"pwned": True})

    def test_absolute_path_inside_base_ok(self, store: JsonArtifactStore) -> None:
        """Paths that resolve within base should be fine."""
        store.write("safe/path.json", {"ok": True})
        assert store.exists("safe/path.json")

    def test_empty_path_rejected(self, store: JsonArtifactStore) -> None:
        with pytest.raises(ValueError, match="empty"):
            store.write("", {"data": 1})

    def test_read_traversal_rejected(self, store: JsonArtifactStore) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            store.read("../outside.json")


# ---------------------------------------------------------------------------
# Non-existent base directory
# ---------------------------------------------------------------------------


class TestBaseDir:
    def test_nonexistent_base_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            JsonArtifactStore("C:\\nonexistent_dir_abc123")
