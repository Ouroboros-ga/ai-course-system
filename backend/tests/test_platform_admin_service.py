from app.core.security import get_password_hash, verify_password
from app.models.user_model import User, UserRole
from app.services.platform_admin_service import (
    decrypt_secret,
    encrypt_secret,
    list_users,
    reset_password,
    update_user,
)
from app.core.security import create_access_token
from datetime import timedelta


def _user(username: str, role: UserRole = UserRole.USER) -> User:
    return User(username=username, hashed_password=get_password_hash("old-password"), role=role)


def test_platform_secret_is_encrypted_round_trip():
    ciphertext = encrypt_secret("local-test-provider-key")
    assert ciphertext != "local-test-provider-key"
    assert decrypt_secret(ciphertext) == "local-test-provider-key"


def test_admin_user_filter_update_and_password_reset(session):
    admin = _user("platform-admin", UserRole.ADMIN)
    learner = _user("learner-alice")
    learner.real_name = "Alice"
    session.add(admin)
    session.add(learner)
    session.commit()
    session.refresh(admin)
    session.refresh(learner)

    result = list_users(session, query="Alice", role="user")
    assert result["total"] == 1
    assert result["items"][0]["id"] == learner.id
    assert result["items"][0]["role"] == "user"

    updated = update_user(session, admin.id, learner.id, {"nickname": "Alice New", "role": "admin", "is_active": True})
    assert updated["nickname"] == "Alice New"
    assert updated["role"] == "admin"

    before = learner.auth_version
    reset_password(session, admin.id, learner.id, "new-secure-password")
    session.refresh(learner)
    assert learner.auth_version == before + 1
    assert verify_password("new-secure-password", learner.hashed_password)


def test_profile_update_keeps_login_name_and_requires_current_password(client, session):
    user = _user("profile-user")
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token({"sub": str(user.id), "username": user.username, "role": "user", "auth_version": user.auth_version}, timedelta(minutes=30))
    headers = {"Authorization": f"Bearer {token}"}

    rejected = client.patch("/api/v1/user/me/profile", headers=headers, json={"new_password": "new-password"})
    assert rejected.status_code == 200
    assert rejected.json()["code"] == 401

    updated = client.patch("/api/v1/user/me/profile", headers=headers, json={"nickname": "展示名称", "current_password": "old-password", "new_password": "new-password"})
    assert updated.status_code == 200
    payload = updated.json()["data"]
    assert payload["userInfo"]["id"] == str(user.id)
    assert payload["userInfo"]["username"] == "profile-user"
    assert payload["userInfo"]["nickname"] == "展示名称"
    session.refresh(user)
    assert user.username == "profile-user"
    assert user.real_name == "展示名称"
    assert verify_password("new-password", user.hashed_password)
