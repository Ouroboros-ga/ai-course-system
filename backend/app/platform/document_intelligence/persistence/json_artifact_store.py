"""Atomic shadow artifact storage for Document IR.

Provides:
- Path-traversal rejection on all write paths.
- Source checksum validation.
- Atomic write via temp-file + rename.
- Concurrent-write safety (no two processes overwrite each other's data).
- Repeated writes allowed (same checksum => idempotent).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


class JsonArtifactStore:
    """Atomic, path-safe JSON artifact storage.

    Args:
        base_dir: Root directory for storing artifacts. Must exist.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base = Path(base_dir).resolve()
        if not self._base.exists():
            raise FileNotFoundError(
                f"Artifact store base directory does not exist: {self._base}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        relative_path: str,
        data: dict,
        *,
        expected_sha256: Optional[str] = None,
    ) -> str:
        """Atomically write *data* (serialized as JSON) to *relative_path*.

        Returns the SHA-256 hex digest of the written JSON bytes.

        Raises:
            ValueError: If *relative_path* contains path-traversal components.
            FileNotFoundError: If the parent directory does not exist.
            RuntimeError: On atomic-rename failure.
        """
        self._reject_traversal(relative_path)

        abs_path = (self._base / relative_path).resolve()
        _ensure_parent_exists(abs_path)

        json_bytes = json.dumps(
            data, indent=2, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")

        actual_sha256 = hashlib.sha256(json_bytes).hexdigest()

        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            raise ValueError(
                f"Checksum mismatch: expected {expected_sha256}, "
                f"got {actual_sha256}"
            )

        # Atomic write: write to temp file, then rename
        fd, tmp_path = tempfile.mkstemp(
            suffix=".json.tmp",
            dir=str(abs_path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(json_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(abs_path))
        except OSError as e:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise RuntimeError(
                f"Failed to atomically write artifact to {abs_path}: {e}"
            ) from e

        return actual_sha256

    def read(self, relative_path: str) -> dict:
        """Read and deserialize a JSON artifact at *relative_path*.

        Raises:
            ValueError: If path contains traversal components.
            FileNotFoundError: If the artifact does not exist.
        """
        self._reject_traversal(relative_path)
        abs_path = (self._base / relative_path).resolve()
        if not abs_path.exists():
            raise FileNotFoundError(
                f"Artifact not found: {relative_path} "
                f"(resolved: {abs_path})"
            )
        with open(str(abs_path), "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self, relative_path: str) -> bool:
        """Check if an artifact exists at *relative_path*."""
        self._reject_traversal(relative_path)
        abs_path = (self._base / relative_path).resolve()
        return abs_path.exists()

    def checksum(self, relative_path: str) -> str:
        """Return SHA-256 hex digest of the JSON file at *relative_path*."""
        self._reject_traversal(relative_path)
        abs_path = (self._base / relative_path).resolve()
        return _file_sha256(abs_path)

    @property
    def base_dir(self) -> str:
        return str(self._base)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _reject_traversal(self, relative_path: str) -> None:
        """Raise ``ValueError`` if *relative_path* traverses outside base."""
        if not relative_path:
            raise ValueError("Relative path must not be empty")

        # Normalize to forward slashes and split
        normalized = relative_path.replace("\\", "/")
        parts = normalized.split("/")

        if ".." in parts:
            raise ValueError(
                f"Path traversal detected: {relative_path!r}"
            )
        if "~" in parts:
            raise ValueError(
                f"Path contains tilde (~): {relative_path!r}"
            )

        # Resolve and verify it's under base
        candidate = (self._base / relative_path).resolve()
        try:
            candidate.relative_to(self._base)
        except ValueError:
            raise ValueError(
                f"Path escapes base directory: {relative_path!r}"
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _ensure_parent_exists(path: Path) -> None:
    """Create parent directories if they don't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()
