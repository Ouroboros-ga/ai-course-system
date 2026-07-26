"""阶段7 资源库 API 端到端测试。

覆盖路线图 §10 验收与 PageDesign前端API契约规划.md §3.9：
- 资源创建/列表/详情/更新；跨用户隔离
- 资源引用登记与列表
- 软删除返回下游影响；恢复；purge 彻底删除
- 回收站 scope 仅返回已删除资源
- 标签更新
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.resource_model import (
    RecycleBinEntry,
    ResourceItem,
    ResourceReference,
    ResourceTag,
)
from app.models.user_model import User, UserRole


RESOURCES = "/api/v1/resources"


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


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_resource_via_api(
    client, token: str, *, name: str = "实验讲义.pdf",
    course_id: int | None = None, tags: list[str] | None = None,
    object_key: str = "obj/key1", content_hash: str = "hash1",
) -> dict:
    payload = {
        "name": name,
        "description": "实验讲义",
        "resource_type": "document",
        "mime_type": "application/pdf",
        "file_size": 1024,
        "object_key": object_key,
        "content_hash": content_hash,
        "tags": tags or [],
    }
    if course_id is not None:
        payload["course_id"] = course_id
    resp = client.post(
        f"{RESOURCES}/files",
        json=payload,
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


# ---------------------------------------------------------------------------
# 资源 CRUD
# ---------------------------------------------------------------------------


class TestResourceCrud:
    """资源创建/读取/更新"""

    def test_create_resource_with_first_version_and_tags(self, client, session):
        u = _user(session, "res_owner1")
        data = _create_resource_via_api(
            client, _token(u),
            tags=["数学", "讲义"],
        )
        assert data["resource_id"].startswith("res_")
        assert data["owner_user_id"] == u.id
        assert data["scope"] == "user"
        assert data["current_version_id"]  # 首版本已激活
        # 标签写入
        tags = session.exec(
            select(ResourceTag).where(ResourceTag.resource_id == data["resource_id"])
        ).all()
        assert {t.tag for t in tags} == {"数学", "讲义"}

    def test_list_mine_scope(self, client, session):
        u1 = _user(session, "res_mine1")
        u2 = _user(session, "res_mine2")
        r1 = _create_resource_via_api(client, _token(u1), name="r1")
        r2 = _create_resource_via_api(client, _token(u2), name="r2")

        resp = client.get(
            f"{RESOURCES}/files?scope=mine",
            headers=_auth(_token(u1)),
        )
        body = resp.json()
        ids = [item["resource_id"] for item in body["data"]["items"]]
        assert r1["resource_id"] in ids
        assert r2["resource_id"] not in ids  # 跨用户隔离

    def test_get_resource_detail(self, client, session):
        u = _user(session, "res_detail1")
        r = _create_resource_via_api(client, _token(u), name="detail.pdf")

        resp = client.get(
            f"{RESOURCES}/files/{r['resource_id']}",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["name"] == "detail.pdf"

    def test_other_user_cannot_access_private_resource(self, client, session):
        u1 = _user(session, "res_priv1")
        u2 = _user(session, "res_priv2")
        r = _create_resource_via_api(client, _token(u1), name="secret.pdf")

        resp = client.get(
            f"{RESOURCES}/files/{r['resource_id']}",
            headers=_auth(_token(u2)),
        )
        body = resp.json()
        assert body["code"] != 200  # 拒绝访问

    def test_update_resource_metadata_and_tags(self, client, session):
        u = _user(session, "res_upd1")
        r = _create_resource_via_api(client, _token(u), name="old.pdf", tags=["old"])

        resp = client.patch(
            f"{RESOURCES}/files/{r['resource_id']}",
            json={"name": "new.pdf", "description": "updated", "tags": ["new", "tag"]},
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["name"] == "new.pdf"
        assert body["data"]["description"] == "updated"
        # 标签已替换
        tags = session.exec(
            select(ResourceTag).where(ResourceTag.resource_id == r["resource_id"])
        ).all()
        assert {t.tag for t in tags} == {"new", "tag"}


# ---------------------------------------------------------------------------
# 资源引用
# ---------------------------------------------------------------------------


class TestResourceReference:
    """资源引用登记"""

    def test_add_and_list_references(self, client, session):
        u = _user(session, "res_ref1")
        r = _create_resource_via_api(client, _token(u))

        # 登记引用
        resp_add = client.post(
            f"{RESOURCES}/files/{r['resource_id']}/references",
            json={
                "target_type": "course",
                "target_course_id": 1,
                "reference_note": "课程讲义",
            },
            headers=_auth(_token(u)),
        )
        body = resp_add.json()
        assert body["code"] == 201
        assert body["data"]["target_type"] == "course"

        # 列出引用
        resp_list = client.get(
            f"{RESOURCES}/files/{r['resource_id']}/references",
            headers=_auth(_token(u)),
        )
        body = resp_list.json()
        assert body["code"] == 200
        assert body["data"]["total"] == 1

    def test_reject_invalid_reference_type(self, client, session):
        u = _user(session, "res_ref2")
        r = _create_resource_via_api(client, _token(u))

        resp = client.post(
            f"{RESOURCES}/files/{r['resource_id']}/references",
            json={"target_type": "invalid_type"},
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] != 201


# ---------------------------------------------------------------------------
# 软删除/恢复/purge
# ---------------------------------------------------------------------------


class TestResourceDelete:
    """软删除/恢复/彻底删除"""

    def test_soft_delete_returns_affected_references(self, client, session):
        u = _user(session, "res_del1")
        r = _create_resource_via_api(client, _token(u))
        # 登记两个引用
        client.post(
            f"{RESOURCES}/files/{r['resource_id']}/references",
            json={"target_type": "course", "target_course_id": 1},
            headers=_auth(_token(u)),
        )
        client.post(
            f"{RESOURCES}/files/{r['resource_id']}/references",
            json={"target_type": "node", "target_node_id": 100},
            headers=_auth(_token(u)),
        )

        # 软删除
        resp = client.delete(
            f"{RESOURCES}/files/{r['resource_id']}",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["affected_count"] == 2
        assert len(body["data"]["affected_references"]) == 2
        assert body["data"]["entry_id"]  # 回收站条目 ID

        # 资源已软删除
        item = session.exec(
            select(ResourceItem).where(ResourceItem.resource_id == r["resource_id"])
        ).first()
        assert item.is_deleted is True

    def test_soft_delete_then_restore(self, client, session):
        u = _user(session, "res_restore1")
        r = _create_resource_via_api(client, _token(u))

        client.delete(
            f"{RESOURCES}/files/{r['resource_id']}",
            headers=_auth(_token(u)),
        )
        # 恢复
        resp = client.post(
            f"{RESOURCES}/files/{r['resource_id']}/restore",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["is_deleted"] is False

    def test_purge_fully_deletes_resource(self, client, session):
        u = _user(session, "res_purge1")
        r = _create_resource_via_api(client, _token(u))

        client.delete(
            f"{RESOURCES}/files/{r['resource_id']}",
            headers=_auth(_token(u)),
        )
        resp = client.delete(
            f"{RESOURCES}/files/{r['resource_id']}/purge",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] == 200
        # 资源已物理删除
        item = session.exec(
            select(ResourceItem).where(ResourceItem.resource_id == r["resource_id"])
        ).first()
        assert item is None

    def test_trash_scope_only_returns_deleted(self, client, session):
        u = _user(session, "res_trash1")
        r_active = _create_resource_via_api(client, _token(u), name="active.pdf")
        r_deleted = _create_resource_via_api(client, _token(u), name="deleted.pdf")
        client.delete(
            f"{RESOURCES}/files/{r_deleted['resource_id']}",
            headers=_auth(_token(u)),
        )

        resp = client.get(
            f"{RESOURCES}/files?scope=trash",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        ids = [item["resource_id"] for item in body["data"]["items"]]
        assert r_deleted["resource_id"] in ids
        assert r_active["resource_id"] not in ids

    def test_cannot_restore_purged_resource(self, client, session):
        u = _user(session, "res_purge_restore1")
        r = _create_resource_via_api(client, _token(u))
        client.delete(f"{RESOURCES}/files/{r['resource_id']}", headers=_auth(_token(u)))
        client.delete(f"{RESOURCES}/files/{r['resource_id']}/purge", headers=_auth(_token(u)))

        # 已 purge 的资源不可恢复
        resp = client.post(
            f"{RESOURCES}/files/{r['resource_id']}/restore",
            headers=_auth(_token(u)),
        )
        body = resp.json()
        assert body["code"] != 200
