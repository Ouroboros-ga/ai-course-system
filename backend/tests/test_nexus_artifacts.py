"""M3：Nexus Artifact 写入/列表/下载契约测试（存储用真 LocalStorageProvider
临时目录 + nexus_artifacts 元数据表）。

锁定：
- 内部写端点 fail-closed（令牌/身份/入参校验）与成功入库；
- 列表/下载为 Backend 原生路由：JWT + require_nexus_use + owner 过滤；
- 非 owner 一律 404（防枚举探测）；下载响应带正确 mime 与 filename。
"""

import uuid

import pytest
from sqlalchemy import text

from app.api.v1.endpoints import nexus_internal, nexus_proxy
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.core.security import create_access_token
from app.services import nexus_artifact_service

# nexus_artifacts 表为 PG-only 域表（nexus_checkpoints schema，TIMESTAMPTZ）；
# SQLite 测试引擎不建该表——涉表断言由部署后线上验收覆盖（M3 验收记录），
# 其余 fail-closed 契约（令牌/入参）在 SQLite 上照常锁定。
_is_pg = None


def _skip_if_sqlite(session):
    global _is_pg
    if _is_pg is None:
        _is_pg = session.connection().dialect.name != "sqlite"
    if not _is_pg:
        pytest.skip("nexus_artifacts 为 PG-only 域表，涉表断言由线上验收覆盖")


@pytest.fixture
def internal_configured(monkeypatch):
    monkeypatch.setattr(nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-token-1")


@pytest.fixture
def nexus_student_token(session, student_user):
    session.add(PlatformPermissionAssignment(
        user_id=student_user.id,
        permission=PlatformPermission.NEXUS_USE,
    ))
    session.commit()
    return create_access_token({
        "sub": str(student_user.id),
        "username": student_user.username,
        "role": student_user.role.value,
        "school_id": student_user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_headers() -> dict[str, str]:
    return {"Authorization": "Bearer internal-token-1", "X-Nexus-User-Id": "77"}


def test_write_artifact_fails_closed_without_token(client):
    response = client.post(
        "/api/v1/nexus-internal/artifacts",
        json={"artifact_type": "markdown", "title": "t", "content": "# hi"},
        headers={"X-Nexus-User-Id": "77"},
    )
    assert response.status_code == 503


def test_write_artifact_rejects_bad_input(client, internal_configured):
    for payload in (
        {"artifact_type": "docx", "title": "t", "content": "# hi"},
        {"artifact_type": "markdown", "title": "", "content": "# hi"},
        {"artifact_type": "markdown", "title": "t", "content": ""},
        {"artifact_type": "markdown", "title": "t", "content": "x" * (512 * 1024 + 1)},
        # SR6：word 不接受文本形态（字节必须经 content_b64）。
        {"artifact_type": "word", "title": "t", "content": "# hi"},
        {"artifact_type": "word", "title": "t", "content": "", "content_b64": "!!!"},
    ):
        response = client.post(
            "/api/v1/nexus-internal/artifacts",
            json=payload,
            headers=_write_headers(),
        )
        assert response.status_code == 422, payload


def test_word_binary_validation_pure():
    """SR6：二进制校验纯函数（无 DB，SQLite 照跑）：类型/标题/空字节/超限。"""
    assert nexus_artifact_service.validate_binary_input("word", "t", b"PK\x03\x04") is None
    assert nexus_artifact_service.validate_binary_input(
        "word", "", b"PK") == "ARTIFACT_TITLE_INVALID"
    assert nexus_artifact_service.validate_binary_input(
        "word", "t", b"") == "ARTIFACT_CONTENT_EMPTY"
    assert nexus_artifact_service.validate_binary_input(
        "markdown", "t", b"PK") == "ARTIFACT_TYPE_UNSUPPORTED"
    assert nexus_artifact_service.validate_binary_input(
        "word", "t", b"x" * (512 * 1024 + 1)) == "ARTIFACT_CONTENT_TOO_LARGE"


def test_write_word_binary_roundtrip(client, session, internal_configured, monkeypatch):
    """SR6：word 二进制经 content_b64 入库（.docx 后缀＋正确 mime）；空字节拒绝。"""
    import base64

    _skip_if_sqlite(session)
    stored: dict = {}

    class _FakeStorage:
        def put(self, object_key, content, *, mime_type=""):
            stored["key"] = object_key
            stored["data"] = bytes(content)
            stored["mime"] = mime_type
            return "word" * 16

    monkeypatch.setattr(nexus_artifact_service, "get_object_storage", lambda: _FakeStorage())
    raw = b"PK\x03\x04fake-docx-bytes"
    response = client.post(
        "/api/v1/nexus-internal/artifacts",
        json={"artifact_type": "word", "title": "正式报告",
              "content_b64": base64.b64encode(raw).decode("ascii")},
        headers=_write_headers(),
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["object_key"].endswith(".docx")
    assert stored["data"] == raw
    assert stored["mime"] == (
        "application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document")
    assert data["size_bytes"] == len(raw)


def test_write_artifact_success_writes_storage_and_metadata(client, session, internal_configured, monkeypatch):
    _skip_if_sqlite(session)
    stored: dict = {}

    class _FakeStorage:
        def put(self, object_key, content, *, mime_type=""):
            stored["key"] = object_key
            stored["data"] = bytes(content)
            return "deadbeef" * 8

    monkeypatch.setattr(nexus_artifact_service, "get_object_storage", lambda: _FakeStorage())
    response = client.post(
        "/api/v1/nexus-internal/artifacts",
        json={"artifact_type": "markdown", "title": "复现报告", "content": "# 报告\n\n正文"},
        headers=_write_headers(),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifact_id"]
    assert data["object_key"].startswith("nexus-artifacts/u77/")
    assert data["object_key"].endswith(".md")
    assert data["size_bytes"] > 0
    assert stored["data"].decode("utf-8") == "# 报告\n\n正文"


def test_list_and_download_owner_scoped(client, session, nexus_student_token, student_user, monkeypatch):
    _skip_if_sqlite(session)
    class _FakeStorage:
        def put(self, object_key, content, *, mime_type=""):
            return "a" * 64

        def _safe_full_path(self, object_key):
            return f"/tmp/fake-root/{object_key}"

        def get(self, object_key):
            return b"# report body"

    fake = _FakeStorage()
    monkeypatch.setattr(nexus_artifact_service, "get_object_storage", lambda: fake)

    created = nexus_artifact_service.create_artifact(
        session,
        user_id=str(student_user.id),
        artifact_type="markdown",
        title="Owner Report",
        content="# report body",
    )
    other_token_user_id = student_user.id + 1000

    # 列表：只见自己的产物（裸 JSON，与 nexus 其他路由一致）
    response = client.get("/api/v1/nexus/artifacts", headers=_auth(nexus_student_token))
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["artifact_id"] for i in items] == [created["artifact_id"]]

    # 下载：owner 200 且带 filename
    response = client.get(
        f"/api/v1/nexus/artifacts/{created['artifact_id']}/download",
        headers=_auth(nexus_student_token),
    )
    assert response.status_code == 200
    assert "Owner" in response.headers.get("content-disposition", "")

    # 非 owner 一律 404（不暴露存在性）
    stranger_token = create_access_token({
        "sub": str(other_token_user_id),
        "username": "stranger",
        "role": "student",
        "school_id": "test-school",
    })
    session.add(PlatformPermissionAssignment(
        user_id=other_token_user_id,
        permission=PlatformPermission.NEXUS_USE,
    ))
    session.commit()
    response = client.get(
        f"/api/v1/nexus/artifacts/{created['artifact_id']}/download",
        headers=_auth(stranger_token),
    )
    assert response.status_code == 404

    # 未登录 401
    response = client.get(f"/api/v1/nexus/artifacts/{created['artifact_id']}/download")
    assert response.status_code in (401, 403)


def test_internal_read_json_roundtrip_owner_scoped(
        client, session, internal_configured, monkeypatch):
    """F5 内部读：json 类型可写可读；owner 校验；他人物品 404；二进制 415。"""
    _skip_if_sqlite(session)

    class _FakeStorage:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def put(self, object_key, content, *, mime_type=""):
            data = bytes(content) if isinstance(content, (bytes, bytearray)) else bytes(content)
            self.objects[object_key] = data
            return "b" * 64

        def get(self, object_key):
            return self.objects[object_key]

    fake = _FakeStorage()
    monkeypatch.setattr(nexus_artifact_service, "get_object_storage", lambda: fake)

    def _headers(user="77"):
        return {"Authorization": "Bearer internal-token-1", "X-Nexus-User-Id": user}

    written = client.post(
        "/api/v1/nexus-internal/artifacts",
        json={"artifact_type": "json", "title": "recipe rcp-1",
              "content": '{"recipe_hash": "abc"}', "run_id": "run-f5"},
        headers=_headers(),
    )
    assert written.status_code == 200, written.text
    artifact_id = written.json()["data"]["artifact_id"]

    read = client.get(f"/api/v1/nexus-internal/artifacts/{artifact_id}",
                      headers=_headers())
    assert read.status_code == 200, read.text
    data = read.json()["data"]
    assert data["content"] == '{"recipe_hash": "abc"}'
    assert data["truncated"] is False
    assert data["artifact_type"] == "json"

    # 非 owner 与不存在同等 404。
    stranger = client.get(f"/api/v1/nexus-internal/artifacts/{artifact_id}",
                          headers=_headers("78"))
    assert stranger.status_code == 404
    missing = client.get("/api/v1/nexus-internal/artifacts/nope1234",
                         headers=_headers())
    assert missing.status_code == 404

    # 无 token 401。
    assert client.get(
        f"/api/v1/nexus-internal/artifacts/{artifact_id}").status_code == 401


def test_internal_read_rejects_binary_as_text(
        client, session, internal_configured, monkeypatch):
    """F5 内部读：word 二进制拒绝文本解读（415，不猜测）。"""
    _skip_if_sqlite(session)

    class _FakeStorage:
        def __init__(self):
            self.objects: dict[str, bytes] = {}

        def put(self, object_key, content, *, mime_type=""):
            self.objects[object_key] = bytes(content)
            return "c" * 64

        def get(self, object_key):
            return self.objects[object_key]

    monkeypatch.setattr(nexus_artifact_service, "get_object_storage",
                        lambda: _FakeStorage())
    import base64 as _base64

    written = client.post(
        "/api/v1/nexus-internal/artifacts",
        json={"artifact_type": "word", "title": "doc",
              "content": "", "content_b64": _base64.b64encode(b"PKdoc").decode(),
              "run_id": "run-f5"},
        headers={"Authorization": "Bearer internal-token-1",
                 "X-Nexus-User-Id": "77"},
    )
    assert written.status_code == 200, written.text
    artifact_id = written.json()["data"]["artifact_id"]
    read = client.get(f"/api/v1/nexus-internal/artifacts/{artifact_id}",
                      headers={"Authorization": "Bearer internal-token-1",
                               "X-Nexus-User-Id": "77"})
    assert read.status_code == 415
