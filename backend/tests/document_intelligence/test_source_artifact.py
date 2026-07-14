"""Tests for SourceArtifact: stable IDs, checksum, path traversal."""

import hashlib

import pytest

from app.platform.document_intelligence.source_artifact import (
    SourceArtifact,
    reject_path_traversal,
)


class TestSourceArtifact:
    def test_from_bytes_produces_deterministic_id(self) -> None:
        data = b"hello world"
        a1 = SourceArtifact.from_bytes(data, "hello.txt", "text/plain")
        a2 = SourceArtifact.from_bytes(data, "hello.txt", "text/plain")
        assert a1.artifact_id == a2.artifact_id
        assert a1.sha256 == a2.sha256
        assert a1.sha256 == hashlib.sha256(data).hexdigest()

    def test_different_bytes_different_id(self) -> None:
        a1 = SourceArtifact.from_bytes(b"data1", "a.txt", "text/plain")
        a2 = SourceArtifact.from_bytes(b"data2", "a.txt", "text/plain")
        assert a1.artifact_id != a2.artifact_id

    def test_id_does_not_depend_on_filename(self) -> None:
        data = b"same content"
        a1 = SourceArtifact.from_bytes(data, "foo.txt", "text/plain")
        a2 = SourceArtifact.from_bytes(data, "bar.txt", "text/plain")
        assert a1.artifact_id == a2.artifact_id

    def test_id_does_not_depend_on_mime(self) -> None:
        data = b"same content"
        a1 = SourceArtifact.from_bytes(data, "f.txt", "text/plain")
        a2 = SourceArtifact.from_bytes(data, "f.txt", "application/pdf")
        assert a1.artifact_id == a2.artifact_id

    def test_id_changes_with_normalization_version(self) -> None:
        data = b"same content"
        a1 = SourceArtifact.from_bytes(data, "f.txt", "text/plain", normalization_version="1")
        a2 = SourceArtifact.from_bytes(data, "f.txt", "text/plain", normalization_version="2")
        assert a1.artifact_id != a2.artifact_id

    def test_size_bytes(self) -> None:
        data = b"1234567890"
        a = SourceArtifact.from_bytes(data, "f.txt", "text/plain")
        assert a.size_bytes == 10

    def test_created_at_set(self) -> None:
        a = SourceArtifact.from_bytes(b"x", "f.txt", "text/plain")
        assert a.created_at is not None

    def test_uri_optional(self) -> None:
        a = SourceArtifact.from_bytes(b"x", "f.txt", "text/plain")
        assert a.uri is None
        a2 = SourceArtifact.from_bytes(b"x", "f.txt", "text/plain", uri="artifacts/foo.txt")
        assert a2.uri == "artifacts/foo.txt"

    def test_round_trip_dict(self) -> None:
        a = SourceArtifact.from_bytes(b"test data", "test.bin", "application/octet-stream")
        d = a.to_dict()
        restored = SourceArtifact.from_dict(d)
        assert restored == a
        assert restored.artifact_id == a.artifact_id
        assert restored.sha256 == a.sha256


class TestRejectPathTraversal:
    def test_simple_path_ok(self) -> None:
        reject_path_traversal("runs/abc/ir.json")  # should not raise

    def test_dot_dot_rejected(self) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            reject_path_traversal("../../etc/passwd")

    def test_windows_dot_dot(self) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            reject_path_traversal("..\\..\\windows\\system32")

    def test_absolute_drive_letter_rejected(self) -> None:
        with pytest.raises(ValueError, match="Absolute path"):
            reject_path_traversal("C:\\windows\\system32")

    def test_nested_ok(self) -> None:
        reject_path_traversal("a/b/c/d.json")  # should not raise
