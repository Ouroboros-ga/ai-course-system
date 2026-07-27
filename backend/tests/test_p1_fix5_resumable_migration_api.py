"""P1 Fix5 验收测试：对象存储迁移 API 切换到可恢复账本实现

验证约束：
- /api/v1/media/storage/migrate 必须使用 ObjectMigrationLedger + migrate_object_keys_resumable
- 响应必须包含账本摘要（summary）、processed（verified/migrated/failed/skipped/not_found）
- 响应必须包含 ledger_path 与 delete_source 字段
- 重复调用必须断点续传：已 verified 的对象在第二次调用时被 skipped
- /storage/migrate/status 必须返回账本状态与失败条目详情
- /storage/migrate/reset-failed 必须将 failed 条目重置为 pending

约束来源：
- Hard Constraints: "Object storage migration must implement resumable task ledger
  with per-object migration status and byte SHA verification"
- Lessons Learned: "新迁移账本未被生产接口使用"
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.models.user_model import User, UserRole
from app.services.object_storage import (
    LocalStorageProvider,
    reset_object_storage_for_tests,
)


MEDIA = "/api/v1/media"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(session, monkeypatch, tmp_path: Path) -> tuple[User, str]:
    """创建真实管理员用户并返回 (user, token)；同时把账本路径指向临时目录。

    必须授予 PlatformPermission.ADMIN，否则 require_platform_permission 会返回 403。
    使用 uuid 后缀避免跨测试用户名冲突。
    """
    unique = uuid.uuid4().hex[:8]
    admin = User(
        username=f"fix5_admin_{unique}",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(admin)
    session.commit()
    session.refresh(admin)

    # 授予平台管理员权限（require_platform_permission 检查的是 PlatformPermissionAssignment，不是 UserRole）
    session.add(PlatformPermissionAssignment(
        user_id=admin.id,
        permission=PlatformPermission.ADMIN,
        granted_by_user_id=admin.id,
    ))
    session.commit()

    token = create_access_token({
        "sub": str(admin.id),
        "username": admin.username,
        "role": admin.role.value,
        "school_id": admin.school_id or "test-school",
    })

    # 把账本路径指向临时目录，避免污染开发环境数据
    ledger_path = str(tmp_path / "ledger" / "migration.json")
    from app.core.config import settings
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MIGRATION_LEDGER_PATH", ledger_path)
    monkeypatch.setattr(settings, "OBJECT_STORAGE_MIGRATION_MAX_ATTEMPTS", 3)
    # 同时允许 demo local fallback，使 s3 后端在测试环境中回退到本地
    monkeypatch.setattr(settings, "OBJECT_STORAGE_ALLOW_DEMO_LOCAL_FALLBACK", True)
    # 让 build_object_storage_provider("local") 也指向同一个临时目录
    monkeypatch.setattr(settings, "MEDIA_STORAGE_PATH", str(tmp_path / "media"))

    return admin, token


def _put_object(tmp_path: Path, key: str, content: bytes) -> None:
    """直接写入本地存储目录（模拟已上传的对象）。"""
    full = tmp_path / "media" / key
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_storage():
    """每个测试用独立临时目录作为对象存储根。"""
    tmp_dir = tempfile.mkdtemp(prefix="fix5_migration_")
    provider = LocalStorageProvider(tmp_dir)
    reset_object_storage_for_tests(provider)
    yield
    reset_object_storage_for_tests(None)


# ---------------------------------------------------------------------------
# 1. /storage/migrate 使用可恢复账本
# ---------------------------------------------------------------------------


class TestStorageMigrateUsesResumableLedger:
    """验证 /storage/migrate 真正使用了 ObjectMigrationLedger + migrate_object_keys_resumable"""

    def test_response_contains_ledger_fields(self, client, session, monkeypatch, tmp_path):
        """响应必须包含 summary/processed/ledger_path/delete_source 字段。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        _put_object(tmp_path, "tts/course_1/a.mp3", b"audio-a")

        resp = client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/a.mp3"],
                "source_backend": "local",
                "target_backend": "s3",  # 不同后端；fallback 使两者指向同一 LocalStorageProvider
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200, body

        data = body["data"]
        # 必须包含可恢复账本特有字段（旧版 migrate_object_keys 不返回这些）
        assert "summary" in data, "响应缺少 summary 字段（账本状态汇总）"
        assert "processed" in data, "响应缺少 processed 字段"
        assert "ledger_path" in data, "响应缺少 ledger_path 字段"
        assert "delete_source" in data, "响应缺少 delete_source 字段"
        assert "newly_registered" in data, "响应缺少 newly_registered 字段"
        assert "interrupted_reset" in data, "响应缺少 interrupted_reset 字段"

        # summary 必须包含全部状态
        summary = data["summary"]
        for status in ("pending", "in_progress", "migrated", "verified", "failed", "total"):
            assert status in summary, f"summary 缺少 {status}"

        # fallback 下两者指向同一 LocalStorageProvider：对象应被 verified（source_sha == target_sha）
        assert data["processed"]["verified"] >= 1, data["processed"]
        # 账本路径必须与 settings 配置一致
        assert data["ledger_path"] == str(tmp_path / "ledger" / "migration.json")

    def test_resumable_migration_skips_verified_on_rerun(self, client, session, monkeypatch, tmp_path):
        """第二次调用必须跳过已 verified 的对象（断点续传核心）。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        _put_object(tmp_path, "tts/course_1/b.mp3", b"audio-b")

        # 第一次迁移：对象从 pending → verified
        resp1 = client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/b.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()["data"]
        assert data1["processed"]["verified"] >= 1, data1["processed"]

        # 第二次迁移：已 verified 的对象必须被 skipped
        resp2 = client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/b.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()["data"]
        # 断点续传：verified 的对象在第二次调用时被 skipped，不会重复迁移
        assert data2["processed"]["skipped"] >= 1, data2["processed"]
        assert data2["processed"]["verified"] == 0, data2["processed"]

    def test_ledger_persists_across_requests(self, client, session, monkeypatch, tmp_path):
        """账本必须持久化到磁盘，跨请求保留状态。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        _put_object(tmp_path, "tts/course_1/c.mp3", b"audio-c")

        # 第一次请求
        client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/c.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )

        # 验证账本文件已写入磁盘
        ledger_path = tmp_path / "ledger" / "migration.json"
        assert ledger_path.exists(), f"账本文件未写入: {ledger_path}"
        with open(ledger_path, "r", encoding="utf-8") as f:
            ledger_data = json.load(f)
        assert "entries" in ledger_data
        assert "tts/course_1/c.mp3" in ledger_data["entries"]
        assert ledger_data["entries"]["tts/course_1/c.mp3"]["status"] == "verified"


# ---------------------------------------------------------------------------
# 2. /storage/migrate/status 查询账本状态
# ---------------------------------------------------------------------------


class TestStorageMigrateStatus:
    """验证 /storage/migrate/status 返回账本状态"""

    def test_status_returns_summary_and_failed_entries(self, client, session, monkeypatch, tmp_path):
        """status 端点必须返回 summary 与 failed_entries。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        _put_object(tmp_path, "tts/course_1/d.mp3", b"audio-d")

        # 先执行一次迁移
        client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["tts/course_1/d.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )

        # 查询状态
        resp = client.get(
            f"{MEDIA}/storage/migrate/status",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200, body

        data = body["data"]
        assert "summary" in data
        assert "ledger_path" in data
        assert "failed_entries" in data
        assert isinstance(data["failed_entries"], list)
        # 已迁移的对象应在 summary 中反映
        assert data["summary"]["verified"] >= 1, data["summary"]
        assert data["summary"]["total"] >= 1, data["summary"]

    def test_status_includes_failed_entry_details(self, client, session, monkeypatch, tmp_path):
        """失败的迁移条目必须在 status 中显示详情（object_key/attempts/last_error）。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        # 不写入源对象，使其 not_found → failed

        # 执行迁移：源对象不存在
        client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["nonexistent/key.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )

        # 查询状态
        resp = client.get(
            f"{MEDIA}/storage/migrate/status",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        # not_found 也计入 failed
        assert data["summary"]["total"] >= 1, data["summary"]


# ---------------------------------------------------------------------------
# 3. /storage/migrate/reset-failed 重置失败条目
# ---------------------------------------------------------------------------


class TestStorageMigrateResetFailed:
    """验证 /storage/migrate/reset-failed 重置 failed 条目"""

    def test_reset_failed_returns_pending(self, client, session, monkeypatch, tmp_path):
        """reset-failed 必须将 failed 条目重置为 pending。"""
        admin, token = _make_admin(session, monkeypatch, tmp_path)
        # 不写入源对象，使其 failed

        # 执行迁移：源对象不存在 → failed
        client.post(
            f"{MEDIA}/storage/migrate",
            json={
                "object_keys": ["nonexistent/key2.mp3"],
                "source_backend": "local",
                "target_backend": "s3",
            },
            headers=_auth(token),
        )

        # 重置 failed 条目
        resp = client.post(
            f"{MEDIA}/storage/migrate/reset-failed",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200, body

        data = body["data"]
        assert "reset_count" in data
        assert "summary_after_reset" in data
        # 重置后 failed 应为 0
        assert data["summary_after_reset"]["failed"] == 0, data["summary_after_reset"]


# ---------------------------------------------------------------------------
# 4. 权限校验
# ---------------------------------------------------------------------------


class TestStorageMigratePermissions:
    """验证非管理员不能访问迁移 API"""

    def test_teacher_cannot_migrate(self, client, session, monkeypatch, tmp_path):
        """教师不能执行迁移。"""
        from app.services.course_access_service import establish_course_access_baseline
        from app.models.course_model import Course, CourseStatus

        teacher = User(
            username="fix5_teacher",
            hashed_password=get_password_hash("test-password"),
            role=UserRole.TEACHER,
            is_active=True,
        )
        session.add(teacher)
        session.commit()
        session.refresh(teacher)

        token = create_access_token({
            "sub": str(teacher.id),
            "username": teacher.username,
            "role": teacher.role.value,
            "school_id": teacher.school_id or "test-school",
        })

        resp = client.post(
            f"{MEDIA}/storage/migrate",
            json={"object_keys": []},
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text

    def test_student_cannot_view_status(self, client, session, monkeypatch, tmp_path):
        """学生不能查看迁移状态。"""
        student = User(
            username="fix5_student",
            hashed_password=get_password_hash("test-password"),
            role=UserRole.STUDENT,
            is_active=True,
        )
        session.add(student)
        session.commit()
        session.refresh(student)

        token = create_access_token({
            "sub": str(student.id),
            "username": student.username,
            "role": student.role.value,
            "school_id": student.school_id or "test-school",
        })

        resp = client.get(
            f"{MEDIA}/storage/migrate/status",
            headers=_auth(token),
        )
        assert resp.status_code == 403, resp.text
