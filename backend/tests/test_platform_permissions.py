"""平台权限授权管理端点（``/api/v1/admin/platform/users/*/platform-permissions``）。

CodeNexus 转型决策 D10：Nexus AI 使用权走新增的 ``platform.nexus.use``，
由管理员显式授予/撤销，不随角色推断（AGENTS.md §4.1.6）。本套测试锁定：
1. 只有持有 ``platform.user.manage``/``platform.admin`` 的管理员能操作；
2. 授予 → 生效、撤销 → 失效、重复撤销 → 404、再授予 → 复用旧行（唯一约束）；
3. ``platform.admin`` 不能经此端点授予（只随角色同步），非法权限值 422。
"""
from __future__ import annotations

import uuid

import pytest

from app.core.security import create_access_token
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.models.platform_admin_model import PlatformAdminAuditEvent
from app.models.user_model import User, UserRole


@pytest.fixture
def manager(session):
    """持有 ``platform.user.manage`` 的管理员（角色本身不参与鉴权）。"""
    user = User(
        username=f"m4a_perm_mgr_{uuid.uuid4().hex[:8]}",
        real_name="Permission Manager",
        hashed_password="x",
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(PlatformPermissionAssignment(
        user_id=user.id,
        permission=PlatformPermission.USER_MANAGE,
    ))
    session.commit()
    return user


@pytest.fixture
def manager_token(manager):
    return create_access_token({
        "sub": str(manager.id),
        "username": manager.username,
        "role": manager.role.value,
        "school_id": manager.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


PERM_URL = "/api/v1/admin/users/{user_id}/platform-permissions"


def test_grant_lists_and_revokes_nexus_use(client, manager_token, student_user):
    url = PERM_URL.format(user_id=student_user.id)

    granted = client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token))
    assert granted.status_code == 200
    assert granted.json()["data"]["permission"] == "platform.nexus.use"
    assert granted.json()["data"]["revoked_at"] is None

    listed = client.get(url, headers=_auth(manager_token))
    assert listed.status_code == 200
    values = [item["permission"] for item in listed.json()["data"]["items"]]
    assert values == ["platform.nexus.use"]
    assert "platform.nexus.use" in listed.json()["data"]["grantable"]

    revoked = client.delete(f"{url}/platform.nexus.use", headers=_auth(manager_token))
    assert revoked.status_code == 200
    assert revoked.json()["data"]["revoked_at"] is not None

    listed_after = client.get(url, headers=_auth(manager_token))
    assert listed_after.json()["data"]["items"] == []

    again = client.delete(f"{url}/platform.nexus.use", headers=_auth(manager_token))
    assert again.status_code == 404


def test_regrant_after_revoke_reuses_existing_row(client, manager_token, student_user, session):
    """(user_id, permission) 有唯一约束：re-grant 必须复活软撤销行而非插入新行。"""
    url = PERM_URL.format(user_id=student_user.id)

    assert client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token)).status_code == 200
    assert client.delete(f"{url}/platform.nexus.use", headers=_auth(manager_token)).status_code == 200
    regrant = client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token))
    assert regrant.status_code == 200
    assert regrant.json()["data"]["revoked_at"] is None

    from sqlmodel import select
    rows = session.exec(
        select(PlatformPermissionAssignment).where(
            PlatformPermissionAssignment.user_id == student_user.id,
            PlatformPermissionAssignment.permission == PlatformPermission.NEXUS_USE,
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None


def test_grant_rejects_admin_and_invalid_values(client, manager_token, student_user):
    url = PERM_URL.format(user_id=student_user.id)

    admin_grant = client.post(url, json={"permission": "platform.admin"}, headers=_auth(manager_token))
    assert admin_grant.status_code == 422

    invalid = client.post(url, json={"permission": "platform.nonsense"}, headers=_auth(manager_token))
    assert invalid.status_code == 422


def test_endpoints_require_manager_permission(client, student_token, student_user):
    url = PERM_URL.format(user_id=student_user.id)
    assert client.get(url, headers=_auth(student_token)).status_code == 403
    assert client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(student_token)).status_code == 403


def test_grant_and_revoke_write_admin_audit(client, manager_token, student_user, session):
    from sqlmodel import select
    url = PERM_URL.format(user_id=student_user.id)

    client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token))
    client.delete(f"{url}/platform.nexus.use", headers=_auth(manager_token))

    actions = session.exec(
        select(PlatformAdminAuditEvent).where(
            PlatformAdminAuditEvent.action.in_(["platform_permission.grant", "platform_permission.revoke"]),
            PlatformAdminAuditEvent.target_id == str(student_user.id),
        )
    ).all()
    assert {event.action for event in actions} == {"platform_permission.grant", "platform_permission.revoke"}


def test_unknown_user_returns_404(client, manager_token):
    url = PERM_URL.format(user_id=999999)
    assert client.get(url, headers=_auth(manager_token)).status_code == 404
    assert client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token)).status_code == 404


# ---------------------------------------------------------------------------
# 默认授权语义（D10 修订：platform.nexus.use 默认授予所有用户，可按用户撤销）
# ---------------------------------------------------------------------------


def test_register_grants_nexus_use_by_default(client):
    username = f"nexus_reg_{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/user/register", json={"username": username, "password": "password123"}
    )

    assert response.status_code == 200
    perms = response.json()["data"]["userInfo"]["platform_permissions"]
    assert "platform.nexus.use" in perms


def test_login_grants_nexus_use_for_legacy_user(client, student_user):
    """存量用户（改动前创建、无授权行）登录时补授默认权限。"""
    assert student_user.username
    response = client.post(
        "/api/v1/user/login",
        json={"username": student_user.username, "password": "test-password"},
    )

    assert response.status_code == 200
    perms = response.json()["data"]["userInfo"]["platform_permissions"]
    assert "platform.nexus.use" in perms


def test_revoked_nexus_use_not_resurrected_by_login(client, manager_token, student_user):
    """管理员显式撤销后，登录/同步流程不得复活默认授权。"""
    url = PERM_URL.format(user_id=student_user.id)
    assert client.post(url, json={"permission": "platform.nexus.use"}, headers=_auth(manager_token)).status_code == 200
    assert client.delete(f"{url}/platform.nexus.use", headers=_auth(manager_token)).status_code == 200

    response = client.post(
        "/api/v1/user/login",
        json={"username": student_user.username, "password": "test-password"},
    )

    assert response.status_code == 200
    perms = response.json()["data"]["userInfo"]["platform_permissions"]
    assert "platform.nexus.use" not in perms


def test_migration_0068_backfill_grants_all_users_and_respects_revocations(tmp_path):
    """0068 回填：所有无授权行用户默认获得 NEXUS_USE；已撤销行保持撤销。"""
    from sqlalchemy import create_engine, text
    from sqlmodel import Session

    from test_alembic_migration import _run_alembic

    db_path = tmp_path / "mig_nexus_default_grant.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    _run_alembic(db_url, "upgrade", "0067")

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    from app.models.user_model import User

    with Session(engine) as db_session:
        db_session.add(User(username="nexus_mig_a", hashed_password="x"))
        db_session.add(User(username="nexus_mig_b", hashed_password="x"))
        db_session.add(User(username="nexus_mig_revoked", hashed_password="x"))
        db_session.commit()

    with engine.begin() as conn:
        row = conn.execute(text(
            "SELECT id FROM users WHERE username = 'nexus_mig_revoked'"
        )).one()
        conn.execute(text(
            "INSERT INTO platform_permission_assignments "
            "(user_id, permission, granted_at, revoked_at) "
            "VALUES (:uid, 'NEXUS_USE', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"uid": row.id})
    engine.dispose()

    _run_alembic(db_url, "upgrade", "0068")

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        grants = dict(conn.execute(text(
            "SELECT u.username, COUNT(p.id) FROM users u "
            "LEFT JOIN platform_permission_assignments p "
            "ON p.user_id = u.id AND p.permission = 'NEXUS_USE' "
            "GROUP BY u.username"
        )).all())
    engine.dispose()

    # 两个无行用户被回填；已有撤销行的用户保持 1 行且仍处于撤销态。
    assert grants["nexus_mig_a"] == 1
    assert grants["nexus_mig_b"] == 1
    assert grants["nexus_mig_revoked"] == 1
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    with engine.connect() as conn:
        revoked = conn.execute(text(
            "SELECT revoked_at FROM platform_permission_assignments p "
            "JOIN users u ON u.id = p.user_id "
            "WHERE u.username = 'nexus_mig_revoked' AND p.permission = 'NEXUS_USE'"
        )).scalar_one()
    engine.dispose()
    assert revoked is not None
