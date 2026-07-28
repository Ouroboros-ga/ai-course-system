"""SourceArtifact — stable source identity.

Stable ID must depend only on source bytes, schema version, and normalization
rules.  Timestamps, status, errors, retries, run IDs, parser-run IDs, and
storage paths must never participate in the stable artifact ID.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class SourceArtifact:
    """Immutable representation of a source file.

    ``artifact_id`` is a deterministic UUIDv5 derived from (sha256, normalization
    version), NOT from runtime metadata.

    Fields:
        artifact_id:    Stable deterministic identifier.
        sha256:         SHA-256 hex digest of the source bytes.
        filename:       Original filename (metadata only, not in ID).
        mime:           MIME type.
        size_bytes:     File size in bytes.
        created_at:     Creation timestamp (runtime metadata; NOT in ID).
        uri:            Optional storage URI (not in ID).
        normalization_version: Version of normalization rules used for ID.
    """

    artifact_id: str
    sha256: str
    filename: str
    mime: str
    size_bytes: int
    created_at: Optional[datetime] = None
    uri: Optional[str] = None
    normalization_version: str = "1"
    # Runtime-only parser input.  It is deliberately not serialized and does
    # not participate in the stable artifact ID; providers prefer it so a
    # LibreOffice-converted PDF never needs a fake object-storage key.
    data: Optional[bytes] = field(default=None, repr=False, compare=False)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        filename: str,
        mime: str,
        *,
        normalization_version: str = "1",
        uri: Optional[str] = None,
    ) -> "SourceArtifact":
        """Build a SourceArtifact from raw source bytes.

        The ``artifact_id`` is a deterministic UUID v5 derived from
        ``sha256 + normalization_version``, ensuring the same bytes + version
        always produce the same ID.
        """
        sha256 = hashlib.sha256(data).hexdigest()
        artifact_id = _compute_artifact_id(sha256, normalization_version)
        return cls(
            artifact_id=artifact_id,
            sha256=sha256,
            filename=filename,
            mime=mime,
            size_bytes=len(data),
            created_at=datetime.now(timezone.utc),
            uri=uri,
            normalization_version=normalization_version,
            data=data,
        )

    def to_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "filename": self.filename,
            "mime": self.mime,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "uri": self.uri,
            "normalization_version": self.normalization_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceArtifact":
        raw = d.get("created_at")
        created = datetime.fromisoformat(raw) if raw else None
        return cls(
            artifact_id=d["artifact_id"],
            sha256=d["sha256"],
            filename=d["filename"],
            mime=d["mime"],
            size_bytes=d["size_bytes"],
            created_at=created,
            uri=d.get("uri"),
            normalization_version=d.get("normalization_version", "1"),
            data=None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTIFACT_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _compute_artifact_id(sha256: str, normalization_version: str) -> str:
    """Deterministic UUIDv5 from sha256 + normalization version."""
    raw = f"{sha256}:nv{normalization_version}"
    return f"art_{uuid.uuid5(_ARTIFACT_NAMESPACE, raw).hex}"


def _check_sha256(data: bytes, expected: str) -> bool:
    return hashlib.sha256(data).hexdigest() == expected


# ---------------------------------------------------------------------------
# Path traversal guard
# ---------------------------------------------------------------------------

def reject_path_traversal(path: str) -> None:
    """Raise ``ValueError`` if *path* contains path-traversal components."""
    normalized = os.path.normpath(path)
    # Reject if any component is '..' or if the path escapes the intended base
    parts = normalized.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(
            f"Path traversal detected: {path!r}"
        )
    # Also reject absolute-looking paths on Windows (drive letter)
    if len(path) >= 2 and path[1] == ":":
        raise ValueError(
            f"Absolute path with drive letter rejected: {path!r}"
        )
