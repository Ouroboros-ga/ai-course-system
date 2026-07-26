"""P1-5: S3/MinIO-compatible object-storage contract tests.

No test uses a cloud account; ``InMemoryS3Client`` exercises the same client
calls used by the real boto3 implementation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.services.object_storage import (
    LocalStorageProvider,
    ObjectStorageConfigurationError,
    get_object_storage,
    migrate_object_keys,
    reset_object_storage_for_tests,
)
from app.services.s3_object_storage import S3ObjectStorageProvider


class _NotFound(Exception):
    def __init__(self):
        self.response = {"Error": {"Code": "NoSuchKey"}}


class InMemoryS3Client:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata):
        self.items[Key] = {
            "data": bytes(Body), "content_type": ContentType,
            "metadata": dict(Metadata), "modified": datetime.now(timezone.utc),
        }

    def get_object(self, *, Bucket, Key):
        if Key not in self.items:
            raise _NotFound()
        return {"Body": BytesIO(self.items[Key]["data"])}

    def head_object(self, *, Bucket, Key):
        if Key not in self.items:
            raise _NotFound()
        item = self.items[Key]
        return {
            "ContentLength": len(item["data"]), "ContentType": item["content_type"],
            "Metadata": item["metadata"], "LastModified": item["modified"],
        }

    def delete_object(self, *, Bucket, Key):
        self.items.pop(Key, None)

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        return f"https://minio.example/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"

    def generate_presigned_post(self, *, Bucket, Key, Conditions, ExpiresIn):
        return {"url": f"https://minio.example/{Bucket}", "fields": {"key": Key, "policy": "fake"}}

    def get_paginator(self, name):
        client = self

        class Paginator:
            def paginate(self, *, Bucket, Prefix):
                yield {"Contents": [{"Key": key} for key in sorted(client.items) if key.startswith(Prefix)]}
        return Paginator()


@pytest.fixture
def fake_s3():
    return S3ObjectStorageProvider(bucket="course-assets", endpoint_url="http://minio", client=InMemoryS3Client())


def test_s3_provider_crud_presign_and_prefix_listing(fake_s3):
    digest = fake_s3.put("courses/1/audio/intro.mp3", b"audio", mime_type="audio/mpeg")
    assert fake_s3.get("courses/1/audio/intro.mp3") == b"audio"
    assert fake_s3.head("courses/1/audio/intro.mp3")["content_sha256"] == digest
    assert fake_s3.list_keys("courses/1/") == ["courses/1/audio/intro.mp3"]
    assert "intro.mp3" in fake_s3.sign_read_url("courses/1/audio/intro.mp3")
    intent = fake_s3.sign_upload_intent("avatars/7/source/video.mp4", max_size_bytes=123)
    assert intent["method"] == "POST"
    assert intent["max_size_bytes"] == 123
    assert fake_s3.delete("courses/1/audio/intro.mp3") is True
    assert fake_s3.exists("courses/1/audio/intro.mp3") is False


def test_migration_is_resumable_and_rejects_target_hash_conflict(tmp_path, fake_s3):
    source = LocalStorageProvider(str(tmp_path / "local"), sign_key="test")
    source.put("courses/1/a.txt", b"same")
    first = migrate_object_keys(source, fake_s3, ["courses/1/a.txt"])
    assert first["migrated_count"] == 1
    second = migrate_object_keys(source, fake_s3, ["courses/1/a.txt"])
    assert second["skipped_count"] == 1
    fake_s3.put("courses/1/a.txt", b"different")
    conflict = migrate_object_keys(source, fake_s3, ["courses/1/a.txt"])
    assert conflict["failed_count"] == 1
    assert source.exists("courses/1/a.txt")


def test_remote_configuration_fails_closed_without_demo_fallback(monkeypatch):
    from app.core.config import settings
    reset_object_storage_for_tests()
    monkeypatch.setattr(settings, "OBJECT_STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_ENDPOINT", "")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_BUCKET", "")
    monkeypatch.setattr(settings, "OBJECT_STORAGE_ALLOW_DEMO_LOCAL_FALLBACK", False)
    with pytest.raises(ObjectStorageConfigurationError):
        get_object_storage()
    reset_object_storage_for_tests()
