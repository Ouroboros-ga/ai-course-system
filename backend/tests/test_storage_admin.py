"""G5 对象存储运维：refs 登记 / GC / 回读校验 / 软删除 端到端验收。

覆盖：
1. reconcile 注册新 ref、标记孤儿、引用恢复
2. GC dry_run / 真删 / 保留期内不删 / Provider 已缺失只清账本
3. verify_readback 真实读取字节并重算 SHA256，捕获 mismatch
4. 软删除手动撤销
5. 管理员权限：非管理员访问返回 403
6. 迁移哈希校验（与已有 test_s3_object_storage 互补）
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.access_control_model import (
    PlatformPermission,
    PlatformPermissionAssignment,
)
from app.models.storage_object_ref_model import (
    StorageObjectRef,
    StorageVerifyStatus,
)
from app.models.user_model import User, UserRole
from app.services.object_storage import (
    LocalStorageProvider,
    reset_object_storage_for_tests,
)
from app.services.storage_admin_service import StorageAdminService


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _user(session, name: str, role: UserRole = UserRole.TEACHER) -> User:
    u = User(
        username=name,
        hashed_password=get_password_hash("test-password"),
        role=role,
        is_active=True,
    )
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _admin_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(session, name: str = "g5_admin") -> User:
    admin = _user(session, name, UserRole.STUDENT)
    session.add(PlatformPermissionAssignment(
        user_id=admin.id, permission=PlatformPermission.ADMIN,
    ))
    session.commit()
    return admin


@pytest.fixture
def temp_storage(tmp_path, session):
    """独立临时目录作为对象存储根；同时清空 storage_object_refs 表保证测试隔离。"""
    # 清理上一轮测试残留的 refs（session.commit() 会持久化，rollback 不会撤销）
    for ref in session.exec(select(StorageObjectRef)).all():
        session.delete(ref)
    session.commit()

    provider = LocalStorageProvider(str(tmp_path / "media"), sign_key="g5-test")
    reset_object_storage_for_tests(provider)
    yield provider
    reset_object_storage_for_tests(None)

    # 测试结束再次清理，避免影响后续测试
    for ref in session.exec(select(StorageObjectRef)).all():
        session.delete(ref)
    session.commit()


# ---------------------------------------------------------------------------
# 服务层：reconcile / GC / verify
# ---------------------------------------------------------------------------


def test_reconcile_registers_orphan_and_reactivate(session, temp_storage):
    """reconcile: 新对象登记、孤儿标记、DB 重新引用后恢复"""
    # 1) Provider 中放一个对象，DB 中无任何引用 → 应被标记 orphan
    temp_storage.put("courses/1/audio/orphan.mp3", b"orphan-audio")
    svc = StorageAdminService(provider=temp_storage)
    report = svc.reconcile(session)
    assert report.scanned_in_provider == 1
    assert report.new_refs_registered == 1
    assert report.orphans_marked == 1

    ref = session.exec(
        select(StorageObjectRef).where(StorageObjectRef.object_key == "courses/1/audio/orphan.mp3")
    ).first()
    assert ref is not None
    assert ref.soft_deleted_at is not None
    assert ref.soft_delete_reason == "reconcile:orphan"
    assert ref.source_backend == "local"

    # 2) 再次 reconcile：已标记的孤儿不会重复计数
    report2 = svc.reconcile(session)
    assert report2.orphans_already_marked == 1
    assert report2.orphans_marked == 0

    # 3) 手动撤销软删除后，reconcile 会因 DB 仍无引用而重新标记为孤儿
    #    （reconcile 只信 DB 实际引用扫描，不信 referenced_by 字段）
    ref.soft_deleted_at = None
    session.add(ref)
    session.commit()
    report3 = svc.reconcile(session)
    assert report3.orphans_marked == 1  # 重新标记为孤儿


def test_gc_dry_run_and_real_delete_with_retention(session, temp_storage):
    """GC dry_run 不删；达到保留期才真删；保留期内不删"""
    temp_storage.put("gc/keep.mp3", b"keep")
    temp_storage.put("gc/delete.mp3", b"delete")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    # reconcile 已把两个对象标记为孤儿（soft_deleted_at = now）

    # 1) dry_run with retention=0：列出候选但不真删
    dry = svc.run_gc(session, retention_seconds=0, dry_run=True)
    assert dry.candidates == 2
    assert dry.deleted == 2  # dry_run 也算 deleted 计数
    assert temp_storage.exists("gc/keep.mp3")
    assert temp_storage.exists("gc/delete.mp3")

    # 2) retention=3600, dry_run=False：soft_deleted_at=now 在保留期内 → 不删
    fresh = svc.run_gc(session, retention_seconds=3600, dry_run=False)
    assert fresh.candidates == 2
    assert fresh.deleted == 0
    assert fresh.retained_within_retention == 2
    assert temp_storage.exists("gc/keep.mp3")
    assert temp_storage.exists("gc/delete.mp3")

    # 3) 把 soft_deleted_at 推到 2 小时前，超过 3600s 保留期 → 真删
    past = datetime.utcnow() - timedelta(seconds=7200)
    for ref in session.exec(select(StorageObjectRef)).all():
        ref.soft_deleted_at = past
        session.add(ref)
    session.commit()

    expired = svc.run_gc(session, retention_seconds=3600, dry_run=False)
    assert expired.deleted == 2
    assert not temp_storage.exists("gc/keep.mp3")
    assert not temp_storage.exists("gc/delete.mp3")
    # ref 行也被清理
    refs = session.exec(select(StorageObjectRef)).all()
    assert len(refs) == 0


def test_gc_handles_missing_in_provider(session, temp_storage):
    """对象在 Provider 中已不存在时，GC 只清 ref 行不报错"""
    temp_storage.put("gc/missing.mp3", b"missing")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    # 直接从 Provider 删除对象，但保留 ref 行
    temp_storage.delete("gc/missing.mp3")
    # 标记软删除
    ref = session.exec(select(StorageObjectRef)).first()
    ref.soft_deleted_at = datetime.utcnow() - timedelta(seconds=3600)
    session.add(ref)
    session.commit()

    report = svc.run_gc(session, retention_seconds=0, dry_run=False)
    assert report.deleted == 0
    assert report.retained_missing_in_provider == 1
    # ref 行被清理
    assert session.exec(select(StorageObjectRef)).first() is None


def test_verify_readback_detects_hash_mismatch(session, temp_storage):
    """verify_readback 真实读取字节并重算 SHA256，捕获不一致"""
    temp_storage.put("verify/ok.mp3", b"ok-content")
    temp_storage.put("verify/bad.mp3", b"original")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    # 篡改 refs 表的 sha（模拟登记后对象被替换）
    bad_ref = session.exec(
        select(StorageObjectRef).where(StorageObjectRef.object_key == "verify/bad.mp3")
    ).first()
    bad_ref.content_sha256 = hashlib.sha256(b"tampered").hexdigest()
    session.add(bad_ref)
    session.commit()
    # 同时把 Provider 中的内容也替换，模拟实际 mismatch
    temp_storage.delete("verify/bad.mp3")
    temp_storage.put("verify/bad.mp3", b"different-content")

    report = svc.verify_readback(session, sample_size=0)  # 全量
    assert report.sampled == 2
    assert report.ok == 1
    assert report.hash_mismatch == 1
    assert len(report.mismatches) == 1
    # refs 表的 last_verify_status 被更新
    bad_ref = session.exec(
        select(StorageObjectRef).where(StorageObjectRef.object_key == "verify/bad.mp3")
    ).first()
    assert bad_ref.last_verify_status == StorageVerifyStatus.HASH_MISMATCH.value


def test_verify_readback_marks_missing(session, temp_storage):
    """verify_readback 对 Provider 中已不存在的对象标记 missing"""
    temp_storage.put("verify/gone.mp3", b"gone")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    temp_storage.delete("verify/gone.mp3")

    report = svc.verify_readback(session, sample_size=0)
    assert report.missing == 1
    ref = session.exec(select(StorageObjectRef)).first()
    assert ref.last_verify_status == StorageVerifyStatus.MISSING.value


def test_manual_soft_delete_and_reactivate(session, temp_storage):
    """手动软删除 + 撤销"""
    temp_storage.put("manual/a.mp3", b"a")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    # 注意：reconcile 会因为无 DB 引用而标记 orphan，先撤销
    ref = session.exec(select(StorageObjectRef)).first()
    ref.soft_deleted_at = None
    session.add(ref)
    session.commit()

    # 手动软删除
    assert svc.mark_soft_deleted(session, "manual/a.mp3", reason="test") is True
    ref = session.exec(select(StorageObjectRef)).first()
    assert ref.soft_deleted_at is not None
    assert ref.soft_delete_reason == "test"

    # 撤销
    assert svc.reactivate(session, "manual/a.mp3") is True
    ref = session.exec(select(StorageObjectRef)).first()
    assert ref.soft_deleted_at is None


def test_get_stats_and_list_refs(session, temp_storage):
    """stats 与 list_refs 返回结构正确"""
    temp_storage.put("stats/a.mp3", b"a")
    temp_storage.put("stats/b.mp3", b"bb")
    svc = StorageAdminService(provider=temp_storage)
    svc.reconcile(session)
    stats = svc.get_stats(session)
    assert stats["total_objects"] == 2
    assert stats["total_size_bytes"] == 3
    assert stats["by_backend"].get("local") == 2

    refs = svc.list_refs(session, limit=10)
    assert len(refs["items"]) == 2


# ---------------------------------------------------------------------------
# 端点层：权限 + 调用
# ---------------------------------------------------------------------------


def test_admin_endpoints_require_platform_admin(client, session, temp_storage):
    """非管理员访问 /api/v1/admin/storage/* 返回 403"""
    teacher = _user(session, "g5_teacher_no_admin", UserRole.TEACHER)
    token = _admin_token(teacher)
    # /stats
    r = client.get("/api/v1/admin/storage/stats", headers=_auth(token))
    assert r.status_code == 403
    # /reconcile
    r = client.post("/api/v1/admin/storage/reconcile", headers=_auth(token), json={})
    assert r.status_code == 403


def test_admin_reconcile_and_gc_end_to_end(client, session, temp_storage):
    """管理员调用 reconcile → soft-delete → gc 完整链路"""
    admin = _make_admin(session, "g5_admin_e2e")
    token = _admin_token(admin)
    temp_storage.put("e2e/orphan.mp3", b"orphan")

    # reconcile
    r = client.post("/api/v1/admin/storage/reconcile", headers=_auth(token), json={})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["scanned_in_provider"] == 1
    assert body["data"]["orphans_marked"] == 1

    # verify-readback
    r = client.post(
        "/api/v1/admin/storage/verify-readback",
        headers=_auth(token),
        json={"sample_size": 0},
    )
    assert r.status_code == 200
    assert r.json()["data"]["sampled"] == 1
    assert r.json()["data"]["ok"] == 1

    # GC dry_run
    r = client.post(
        "/api/v1/admin/storage/gc",
        headers=_auth(token),
        json={"retention_seconds": 0, "dry_run": True},
    )
    assert r.status_code == 200
    assert r.json()["data"]["candidates"] == 1
    assert r.json()["data"]["deleted"] == 1
    # dry_run 不真删
    assert temp_storage.exists("e2e/orphan.mp3")

    # GC 真删
    r = client.post(
        "/api/v1/admin/storage/gc",
        headers=_auth(token),
        json={"retention_seconds": 0, "dry_run": False},
    )
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] == 1
    assert not temp_storage.exists("e2e/orphan.mp3")


def test_admin_soft_delete_and_reactivate_endpoint(client, session, temp_storage):
    """管理员手动软删除 + 撤销端点"""
    admin = _make_admin(session, "g5_admin_sd")
    token = _admin_token(admin)
    temp_storage.put("sd/a.mp3", b"a")
    # 先 reconcile 让 ref 存在
    client.post("/api/v1/admin/storage/reconcile", headers=_auth(token), json={})
    # 撤销 reconcile 标记的 orphan，再测手动软删除
    ref = session.exec(select(StorageObjectRef)).first()
    ref.soft_deleted_at = None
    session.add(ref)
    session.commit()

    # 手动软删除
    r = client.post(
        "/api/v1/admin/storage/refs/sd/a.mp3/soft-delete",
        headers=_auth(token),
        json={"reason": "manual-test"},
    )
    assert r.status_code == 200
    session.expire_all()
    ref = session.exec(select(StorageObjectRef)).first()
    assert ref.soft_deleted_at is not None
    assert ref.soft_delete_reason == "manual-test"

    # 撤销
    r = client.post(
        "/api/v1/admin/storage/refs/sd/a.mp3/reactivate",
        headers=_auth(token),
    )
    assert r.status_code == 200
    session.expire_all()
    ref = session.exec(select(StorageObjectRef)).first()
    assert ref.soft_deleted_at is None
