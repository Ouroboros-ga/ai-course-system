"""S3-compatible object storage provider for MinIO and cloud object storage.

The provider deliberately has no course-permission logic.  API services must
authorize before issuing a presigned URL; this module only stores bytes under a
stable ``object_key`` namespace.
"""
from __future__ import annotations

import hashlib
import io
import posixpath
from datetime import datetime, timezone
from typing import IO, Any, Optional

from app.services.object_storage import ObjectStorageProvider, mime_type_for


class S3ObjectStorageProvider(ObjectStorageProvider):
    """Real S3 API provider, compatible with MinIO and S3-compatible OSS.

    ``client`` is injectable so automated tests use a fake in-memory client
    rather than a real cloud account.
    """

    backend_name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str = "",
        region_name: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
        session_token: str = "",
        addressing_style: str = "path",
        presign_expires_seconds: int = 900,
        client: Any = None,
    ) -> None:
        if not bucket:
            raise ValueError("OBJECT_STORAGE_BUCKET is required for S3 storage")
        if client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:  # pragma: no cover - dependency lock guards this
                raise RuntimeError("boto3 is required for S3-compatible object storage") from exc
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                region_name=region_name or None,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
                aws_session_token=session_token or None,
                config=Config(s3={"addressing_style": addressing_style or "path"}),
            )
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self._client = client
        self._presign_expires_seconds = max(1, min(int(presign_expires_seconds), 7 * 24 * 3600))

    @classmethod
    def from_settings(cls, settings: Any) -> "S3ObjectStorageProvider":
        missing = [
            name for name in ("OBJECT_STORAGE_ENDPOINT", "OBJECT_STORAGE_BUCKET",
                              "OBJECT_STORAGE_ACCESS_KEY_ID", "OBJECT_STORAGE_SECRET_ACCESS_KEY")
            if not getattr(settings, name, "")
        ]
        if missing:
            raise ValueError("remote object storage configuration missing: " + ", ".join(missing))
        return cls(
            bucket=settings.OBJECT_STORAGE_BUCKET,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            region_name=settings.OBJECT_STORAGE_REGION,
            access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            session_token=settings.OBJECT_STORAGE_SESSION_TOKEN,
            addressing_style=settings.OBJECT_STORAGE_ADDRESSING_STYLE,
            presign_expires_seconds=settings.OBJECT_STORAGE_PRESIGN_EXPIRES_SECONDS,
        )

    @staticmethod
    def _validate_key(object_key: str) -> str:
        if not object_key or object_key.startswith(("/", "\\")):
            raise ValueError("object_key cannot be empty or absolute")
        normalized = posixpath.normpath(object_key.replace("\\", "/"))
        if normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError("object_key escapes its namespace")
        return normalized

    @staticmethod
    def _is_not_found(error: Exception) -> bool:
        response = getattr(error, "response", {}) or {}
        code = str((response.get("Error") or {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}

    def put(self, object_key: str, content: bytes | IO[bytes], *, mime_type: str = "") -> str:
        key = self._validate_key(object_key)
        data = bytes(content) if isinstance(content, (bytes, bytearray)) else content.read()
        digest = hashlib.sha256(data).hexdigest()
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime_type or mime_type_for(key),
            Metadata={"sha256": digest},
        )
        return digest

    def get(self, object_key: str) -> bytes:
        key = self._validate_key(object_key)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if self._is_not_found(exc):
                raise FileNotFoundError(f"object_key does not exist: {key}") from exc
            raise
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def head(self, object_key: str) -> dict:
        key = self._validate_key(object_key)
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if self._is_not_found(exc):
                raise FileNotFoundError(f"object_key does not exist: {key}") from exc
            raise
        modified = response.get("LastModified")
        if isinstance(modified, datetime) and modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        return {
            "size_bytes": int(response.get("ContentLength", 0)),
            "mime_type": response.get("ContentType") or mime_type_for(key),
            "content_sha256": (response.get("Metadata") or {}).get("sha256", ""),
            "last_modified": modified,
        }

    def delete(self, object_key: str) -> bool:
        key = self._validate_key(object_key)
        if not self.exists(key):
            return False
        self._client.delete_object(Bucket=self.bucket, Key=key)
        return True

    def exists(self, object_key: str) -> bool:
        try:
            self.head(object_key)
            return True
        except FileNotFoundError:
            return False

    def sign_read_url(
        self, object_key: str, *, expires_in: int = 3600, scope: Optional[dict] = None,
    ) -> str:
        del scope  # permissions are enforced before this Provider is called
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._validate_key(object_key)},
            ExpiresIn=max(1, min(int(expires_in), self._presign_expires_seconds)),
        )

    def sign_upload_intent(
        self, object_key: str, *, expires_in: int = 900, max_size_bytes: int = 0,
    ) -> dict:
        key = self._validate_key(object_key)
        max_bytes = max(1, max_size_bytes or 500 * 1024 * 1024)
        post = self._client.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Conditions=[["content-length-range", 1, max_bytes]],
            ExpiresIn=max(1, min(int(expires_in), self._presign_expires_seconds)),
        )
        return {
            "object_key": key,
            "upload_url": post["url"],
            "method": "POST",
            "headers": {},
            "fields": post["fields"],
            "expires_at": None,
            "max_size_bytes": max_bytes,
        }

    def list_keys(self, prefix: str = "") -> list[str]:
        prefix = self._validate_key(prefix) if prefix else ""
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)
