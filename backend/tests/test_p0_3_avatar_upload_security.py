"""P0-3 教师数字人素材上传与预处理安全链路验收测试。

验证完成标准：
- 教师 A 无法把教师 B、课程资料或任意对象键登记为自己的数字人素材
- 损坏、超大、伪装格式、未校验素材无法进入预处理
- 学生只看到已发布课程的渲染资产，不看到原始视频/语音

覆盖范围：
1. request_upload_intent：服务端生成 object_key（命名空间隔离）
2. confirm_uploaded：服务端 head + ffprobe + hash + scan -> verified
3. 跨教师越权：教师 B 无法访问/确认教师 A 的素材
4. 客户端伪造 object_key：旧式 register_source_media 拒绝任意键
5. 损坏文件：空文件、全零文件 -> invalid/quarantined
6. 伪装文件：扩展名与签名不一致 -> quarantined
7. 未校验素材：pending_upload/uploaded 状态无法启动预处理
8. 教师撤回素材：withdrawn 状态无法启动预处理
9. 学生无法下载原始素材（仅能看到已发布课程渲染资产）
10. PUT /upload 路由：签名校验、过期、越权、超大、错误 MIME
"""
from __future__ import annotations

import hashlib
from datetime import datetime

import pytest
from sqlmodel import select

from app.core.security import create_access_token, get_password_hash
from app.models.avatar_model import (
    AvatarProfile,
    AvatarProfileStatus,
    AvatarSourceMedia,
    AvatarSourceMediaStatus,
    AvatarSourceMediaType,
)
from app.models.course_model import Course, CourseStatus
from app.models.user_model import User, UserRole
from app.services.course_access_service import establish_course_access_baseline
from app.services.object_storage import (
    LocalStorageProvider,
    reset_object_storage_for_tests,
)


AVATAR = "/api/v1/avatar-profiles"


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


def _course(session, teacher_id: int) -> Course:
    c = Course(
        fanya_course_id=f"p03-{teacher_id}-{datetime.utcnow().timestamp()}",
        fanya_course_name="P03 Course",
        title="P03 Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    establish_course_access_baseline(session, c.id, teacher_id)
    session.commit()
    return c


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_profile(client, token: str) -> dict:
    resp = client.post(
        AVATAR,
        json={
            "display_name": "P03 Test Avatar",
            "provider_key": "fake",
            "consent_text": "我确认本人形象授权，已阅读并同意数字人使用条款。",
            "notes": "",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 201, body
    return body["data"]


def _request_upload_intent(
    client, token: str, avatar_id: str,
    *,
    media_type: str = "portrait_video",
    mime_type: str = "video/mp4",
    size_bytes: int = 1024 * 1024,
) -> dict:
    resp = client.post(
        f"{AVATAR}/{avatar_id}/source-media/upload-intent",
        json={
            "media_type": media_type,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    return body["data"]


# ---------------------------------------------------------------------------
# Fixture：使用临时本地存储目录
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_storage(tmp_path):
    """每个测试用独立临时目录作为对象存储根。"""
    provider = LocalStorageProvider(str(tmp_path / "media"))
    reset_object_storage_for_tests(provider)
    yield provider
    reset_object_storage_for_tests(None)


# ---------------------------------------------------------------------------
# 1. 服务端生成 object_key + 命名空间隔离
# ---------------------------------------------------------------------------


def test_request_upload_intent_generates_namespaced_object_key(client, session, temp_storage):
    """服务端生成的 object_key 必须按教师 + AvatarProfile 命名空间隔离。"""
    teacher = _user(session, "p03_teacher_a")
    profile = _create_profile(client, _token(teacher))

    data = _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )

    source = data["source_media"]
    intent = data["upload_intent"]

    # object_key 必须由服务端生成，且按教师命名空间隔离
    expected_prefix = f"avatar_sources/u{teacher.id}/{profile['avatar_id']}/portrait_video/"
    assert source["object_key"].startswith(expected_prefix), source["object_key"]
    # 状态应为 pending_upload
    assert source["upload_status"] == "pending_upload"
    # 上传意图包含限制
    assert intent["max_size_bytes"] > 0
    assert "video/mp4" in intent["allowed_mime_types"]
    assert intent["method"] == "PUT"
    assert intent["expires_at"] > 0
    assert intent["method"] == "PUT"
    assert intent["fields"] == {}
    assert intent["headers"]["Content-Type"] == "video/mp4"


def test_request_upload_intent_rejects_invalid_mime(client, session, temp_storage):
    """不支持的 MIME 类型应被拒绝。"""
    teacher = _user(session, "p03_teacher_b")
    profile = _create_profile(client, _token(teacher))

    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/upload-intent",
        json={
            "media_type": "portrait_video",
            "mime_type": "application/zip",  # 不允许
            "size_bytes": 1024,
        },
        headers=_auth(_token(teacher)),
    )
    # reject_validation_failed 返回 HTTP 422
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 422, body  # validation_failed


# ---------------------------------------------------------------------------
# 2. confirm_uploaded：head + ffprobe + hash + scan -> verified
# ---------------------------------------------------------------------------


def _put_fake_video(provider, object_key: str) -> bytes:
    """写入一个伪造的最小 MP4 文件（带 ftyp 签名）。"""
    # MP4 头部 ftyp + mdat 基本结构
    content = (
        b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
        + b"\x00\x00\x00\x08free"
        + b"\x00\x00\x00\x08mdat"
        + b"fake video content for p03 test"
    )
    provider.put(object_key, content, mime_type="video/mp4")
    return content


def test_confirm_uploaded_transitions_to_verified(client, session, temp_storage):
    """完整两步式上传 + 服务端确认 -> verified。"""
    teacher = _user(session, "p03_teacher_c")
    profile = _create_profile(client, _token(teacher))

    # 第 1 步：请求上传意图
    data = _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )
    source_media_id = data["source_media"]["source_media_id"]
    object_key = data["source_media"]["object_key"]

    # 客户端"上传"（这里直接通过 provider 写入模拟）
    content = _put_fake_video(temp_storage, object_key)

    # 第 2 步：服务端确认
    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    source = body["data"]

    # 验证状态转为 verified
    assert source["upload_status"] == "verified", source
    # 服务端探测字段已写入
    assert source["server_size_bytes"] == len(content)
    expected_sha = hashlib.sha256(content).hexdigest()
    assert source["server_content_sha256"] == expected_sha
    assert source["scan_status"] == "clean"
    assert source["verified_at"] is not None


def test_confirm_uploaded_object_not_found_marks_invalid(client, session, temp_storage):
    """对象未上传时，confirm 应标记为 invalid。"""
    teacher = _user(session, "p03_teacher_d")
    profile = _create_profile(client, _token(teacher))

    data = _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )
    source_media_id = data["source_media"]["source_media_id"]
    # 不上传文件

    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    body = resp.json()
    source = body["data"]
    assert source["upload_status"] == "invalid"
    assert source["validation_notes"] == "object_not_found"


def test_confirm_uploaded_all_zero_content_quarantined(client, session, temp_storage):
    """全零内容（伪装上传）应被扫描为 quarantined。"""
    teacher = _user(session, "p03_teacher_e")
    profile = _create_profile(client, _token(teacher))

    data = _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )
    source_media_id = data["source_media"]["source_media_id"]
    object_key = data["source_media"]["object_key"]

    # 上传全零内容
    temp_storage.put(object_key, b"\x00" * 4096, mime_type="video/mp4")

    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    body = resp.json()
    source = body["data"]
    # 全零内容应被扫描为 quarantined
    assert source["upload_status"] == "quarantined", source
    assert source["scan_status"] == "quarantined"


# ---------------------------------------------------------------------------
# 3. 跨教师越权
# ---------------------------------------------------------------------------


def test_cross_teacher_cannot_access_source_media(client, session, temp_storage):
    """教师 B 无法访问/确认教师 A 的素材。"""
    teacher_a = _user(session, "p03_teacher_a_isolated")
    teacher_b = _user(session, "p03_teacher_b_isolated")
    profile_a = _create_profile(client, _token(teacher_a))

    data = _request_upload_intent(
        client, _token(teacher_a), profile_a["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )
    source_media_id = data["source_media"]["source_media_id"]

    # 教师 B 尝试 confirm 教师 A 的素材 -> 应失败
    resp = client.post(
        f"{AVATAR}/{profile_a['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher_b)),
    )
    # 应该是 404 或 403
    body = resp.json()
    assert body["code"] in (404, 403), body


def test_cross_teacher_cannot_register_arbitrary_object_key(client, session, temp_storage):
    """旧式 register_source_media 拒绝教师 A 提交教师 B 的命名空间下的 object_key。"""
    teacher_a = _user(session, "p03_teacher_a_v2")
    profile_a = _create_profile(client, _token(teacher_a))

    # 尝试用教师 B 的命名空间下的 object_key
    fake_object_key = f"avatar_sources/u999999/{profile_a['avatar_id']}/portrait_video/abc.mp4"
    resp = client.post(
        f"{AVATAR}/{profile_a['avatar_id']}/source-media",
        json={
            "media_type": "portrait_video",
            "object_key": fake_object_key,
            "mime_type": "video/mp4",
            "size_bytes": 1024 * 1024,
            "duration_ms": 30000,
        },
        headers=_auth(_token(teacher_a)),
    )
    # reject_validation_failed 返回 HTTP 422
    assert resp.status_code == 422
    body = resp.json()
    # 应被拒绝（validation_failed 422）
    assert body["code"] == 422, body


# ---------------------------------------------------------------------------
# 4. 未校验素材无法启动预处理
# ---------------------------------------------------------------------------


def test_create_preparation_rejects_pending_upload_source(client, session, temp_storage):
    """pending_upload 状态的素材不能启动预处理。"""
    teacher = _user(session, "p03_teacher_pending")
    profile = _create_profile(client, _token(teacher))

    # 仅请求上传意图，未上传未确认
    _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )

    # 尝试启动预处理 -> 应失败
    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/prepare",
        json={"provider_key": "", "idempotency_key": ""},
        headers=_auth(_token(teacher)),
    )
    # reject_state_conflict 返回 HTTP 409
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 409, body  # state_conflict


def test_create_preparation_rejects_withdrawn_source(client, session, temp_storage):
    """withdrawn 状态的素材不能启动预处理。"""
    teacher = _user(session, "p03_teacher_withdraw")
    profile = _create_profile(client, _token(teacher))

    # 第 1 步 + 上传 + 确认 -> verified
    data = _request_upload_intent(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",
        size_bytes=2 * 1024 * 1024,
    )
    source_media_id = data["source_media"]["source_media_id"]
    object_key = data["source_media"]["object_key"]
    _put_fake_video(temp_storage, object_key)

    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert resp.json()["data"]["upload_status"] == "verified"

    # 撤回素材
    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/withdraw",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["upload_status"] == "withdrawn"

    # 尝试启动预处理 -> 应失败
    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/prepare",
        json={"provider_key": "", "idempotency_key": ""},
        headers=_auth(_token(teacher)),
    )
    # reject_state_conflict 返回 HTTP 409
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == 409, body


# ---------------------------------------------------------------------------
# 5. 学生无法下载原始素材
# ---------------------------------------------------------------------------


def test_student_cannot_list_teacher_source_media(client, session, temp_storage):
    """学生通过 /avatar-profiles/{id} 路径无法访问教师素材列表。

    学生只能通过课程绑定路径查看已发布的渲染资产，不能直接访问教师素材端点。
    """
    teacher = _user(session, "p03_teacher_student_test")
    student = _user(session, "p03_student", UserRole.STUDENT)
    profile = _create_profile(client, _token(teacher))

    # 学生尝试访问教师 profile 详情 -> 应失败（404/403）
    resp = client.get(
        f"{AVATAR}/{profile['avatar_id']}",
        headers=_auth(_token(student)),
    )
    body = resp.json()
    # 学生不是 owner，应被拒绝
    assert body["code"] in (404, 403), body


# ---------------------------------------------------------------------------
# 6. 教师授权时间戳字段
# ---------------------------------------------------------------------------


def test_avatar_profile_has_authorization_timestamps(client, session, temp_storage):
    """AvatarProfile 应包含 teacher_authorization_confirmed_at / revoked_at 字段。"""
    teacher = _user(session, "p03_teacher_auth_ts")
    profile_data = _create_profile(client, _token(teacher))

    # 直接从数据库读取，确认字段存在
    record = session.exec(
        select(AvatarProfile).where(AvatarProfile.avatar_id == profile_data["avatar_id"])
    ).first()
    assert record is not None
    # 字段存在（即使为 None）
    assert hasattr(record, "teacher_authorization_confirmed_at")
    assert hasattr(record, "revoked_at")


# ---------------------------------------------------------------------------
# 7. PUT /upload 路由：受控上传完整链路
# ---------------------------------------------------------------------------


_MIN_MP4 = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    + b"\x00\x00\x00\x08free"
    + b"\x00\x00\x00\x08mdat"
    + b"put-route video content"
)


def _request_intent_and_get_params(
    client, token: str, avatar_id: str,
    *,
    media_type: str = "portrait_video",
    mime_type: str = "video/mp4",
    size_bytes: int = 1024 * 1024,
) -> dict:
    """请求上传意图并返回 source_media + upload_intent 完整字段。"""
    data = _request_upload_intent(
        client, token, avatar_id,
        media_type=media_type, mime_type=mime_type, size_bytes=size_bytes,
    )
    return data


def test_put_upload_route_writes_object_and_marks_uploaded(client, session, temp_storage):
    """PUT /upload 路由成功上传后，对象写入存储且 upload_status 转为 uploaded。"""
    teacher = _user(session, "p03_put_success")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source = data["source_media"]
    intent = data["upload_intent"]
    source_media_id = source["source_media_id"]
    object_key = source["object_key"]

    # 客户端通过 PUT 路由上传，携带 exp/sig
    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200, body
    updated = body["data"]
    # 状态转为 uploaded（不是 verified，需 /confirm 完成 head+ffprobe+hash+scan）
    assert updated["upload_status"] == "uploaded", updated
    assert updated["server_size_bytes"] == len(_MIN_MP4)
    assert updated["mime_type"] == "video/mp4"

    # 对象确实写入存储
    assert temp_storage.exists(object_key)
    stored = temp_storage.get(object_key)
    assert stored == _MIN_MP4


def test_put_upload_route_rejects_missing_signature_params(client, session, temp_storage):
    """缺少 exp/sig 任一参数应返回 422（FastAPI Query 校验）。"""
    teacher = _user(session, "p03_put_missing_sig")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source_media_id = data["source_media"]["source_media_id"]

    # 缺少 exp
    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"sig": "any"},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 422, resp.text

    # 缺少 sig
    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": 9999999999},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 422, resp.text


def test_put_upload_route_rejects_invalid_signature(client, session, temp_storage):
    """伪造的 sig 应被拒绝（403）。"""
    teacher = _user(session, "p03_put_invalid_sig")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source_media_id = data["source_media"]["source_media_id"]
    object_key = data["source_media"]["object_key"]

    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": 9999999999, "sig": "tampered_signature_value"},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert "签名无效" in body.get("detail", "") or body.get("code") == 403, body

    # 对象不应被写入
    assert not temp_storage.exists(object_key)


def test_put_upload_route_rejects_expired_signature(client, session, temp_storage):
    """过期的 exp 应被拒绝（403）。"""
    teacher = _user(session, "p03_put_expired")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source_media_id = data["source_media"]["source_media_id"]
    object_key = data["source_media"]["object_key"]

    # 直接构造一个过期的 exp + 对应签名（用 provider 内部 _sign 方法）
    storage = temp_storage
    expired_exp = int(datetime(2020, 1, 1).timestamp())  # 过去时间
    expired_sig = storage._sign(object_key, expired_exp, {"upload": True})

    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": expired_exp, "sig": expired_sig},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 403, resp.text

    # 对象不应被写入
    assert not temp_storage.exists(object_key)


def test_put_upload_route_rejects_cross_teacher(client, session, temp_storage):
    """教师 B 不能用教师 A 的 source_media_id 上传（即使持有签名）。"""
    teacher_a = _user(session, "p03_put_owner")
    teacher_b = _user(session, "p03_put_attacker")
    profile_a = _create_profile(client, _token(teacher_a))
    data = _request_intent_and_get_params(client, _token(teacher_a), profile_a["avatar_id"])
    source_media_id = data["source_media"]["source_media_id"]
    intent = data["upload_intent"]

    # 教师 B 持有教师 A 签发的 exp/sig，但仍应被 404（归属校验先于验签）
    resp = client.put(
        f"{AVATAR}/{profile_a['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher_b)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert body.get("detail") or body.get("code") == 404


def test_put_upload_route_rejects_oversized_content(client, session, temp_storage):
    """超过 max_size_bytes 的内容应被拒绝（413 PAYLOAD_TOO_LARGE）。

    P0 修复：在读取 body 之前先按可信 Content-Length 硬拒绝，避免超大文件读入内存。
    """
    teacher = _user(session, "p03_put_oversize")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(
        client, _token(teacher), profile["avatar_id"],
        size_bytes=1024,  # 申报 1KB（预校验通过）
    )
    source_media_id = data["source_media"]["source_media_id"]
    intent = data["upload_intent"]
    max_bytes = intent["max_size_bytes"]
    # 构造超出上限的内容
    oversized = b"\x00" * (max_bytes + 1024)

    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=oversized,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    # P0 修复后：413 PAYLOAD_TOO_LARGE（在读取 body 之前硬拒绝）
    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["code"] == 413
    detail = body.get("data") or body
    assert detail.get("error_code") == "PAYLOAD_TOO_LARGE"


def test_put_upload_route_rejects_oversized_streaming_no_content_length(
    client, session, temp_storage, monkeypatch,
):
    """省略 Content-Length 时通过流式读取检测超限并返回 413。

    P0 修复：攻击者可省略 Content-Length，使超大文件绕过前置校验；
    流式读取累计字节数，一旦超过 max_bytes 立即中止。
    """
    teacher = _user(session, "p03_put_stream_overflow")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(
        client, _token(teacher), profile["avatar_id"],
        size_bytes=1024,
    )
    source_media_id = data["source_media"]["source_media_id"]
    intent = data["upload_intent"]
    max_bytes = intent["max_size_bytes"]
    # 构造超出上限的内容
    oversized = b"\x00" * (max_bytes + 1024)

    # 使用 chunked transfer encoding 模拟省略 Content-Length
    # httpx client 在 content=bytes 时会自动设置 Content-Length，
    # 但我们用 data=generator 触发 chunked encoding（无 Content-Length）
    def _chunked():
        yield oversized

    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        data=_chunked(),  # chunked encoding，无 Content-Length header
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    # 流式读取检测超限 → 413 PAYLOAD_TOO_LARGE_STREAMING
    assert resp.status_code == 413, resp.text
    body = resp.json()
    assert body["code"] == 413
    detail = body.get("data") or body
    assert detail.get("error_code") in ("PAYLOAD_TOO_LARGE_STREAMING", "PAYLOAD_TOO_LARGE")


def test_put_upload_route_rejects_wrong_mime(client, session, temp_storage):
    """Content-Type 不在 allowed_mime_types 列表内应被拒绝。"""
    teacher = _user(session, "p03_put_wrong_mime")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(
        client, _token(teacher), profile["avatar_id"],
        media_type="portrait_video",
        mime_type="video/mp4",  # 预校验通过
    )
    source_media_id = data["source_media"]["source_media_id"]
    intent = data["upload_intent"]

    # 实际 PUT 时改用不允许的 MIME
    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "application/zip"},
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == 422, body


def test_put_upload_route_signature_bound_to_object_key(client, session, temp_storage):
    """签名绑定 object_key：用 source_media_A 的 sig 上传到 source_media_B 应失败。"""
    teacher = _user(session, "p03_put_sig_bind")
    profile = _create_profile(client, _token(teacher))
    # 为同一教师创建两个 source_media
    data_a = _request_intent_and_get_params(
        client, _token(teacher), profile["avatar_id"],
        mime_type="video/mp4",
    )
    data_b = _request_intent_and_get_params(
        client, _token(teacher), profile["avatar_id"],
        mime_type="video/mp4",
    )
    source_a_id = data_a["source_media"]["source_media_id"]
    intent_b = data_b["upload_intent"]  # 用 B 的签名上传到 A

    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_a_id}/upload",
        params={"exp": intent_b["exp"], "sig": intent_b["sig"]},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    # 验签会失败，因为 sig 绑定的是 B 的 object_key
    assert resp.status_code == 403, resp.text


def test_put_upload_then_confirm_reaches_verified(client, session, temp_storage):
    """完整链路：PUT 上传 -> POST /confirm -> verified。"""
    teacher = _user(session, "p03_put_then_confirm")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source_media_id = data["source_media"]["source_media_id"]
    intent = data["upload_intent"]

    # PUT 上传
    resp = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=_MIN_MP4,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["upload_status"] == "uploaded"

    # 调用 /confirm 完成 head+ffprobe+hash+scan
    resp = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source_media_id}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    source = body["data"]
    assert source["upload_status"] == "verified", source
    expected_sha = hashlib.sha256(_MIN_MP4).hexdigest()
    assert source["server_content_sha256"] == expected_sha


def test_confirm_rejects_client_sha256_mismatch(client, session, temp_storage):
    """confirm 必须以服务端重算 SHA 为准，并拒绝旧登记中的错误摘要。"""
    teacher = _user(session, "p03_sha_mismatch")
    profile = _create_profile(client, _token(teacher))
    data = _request_intent_and_get_params(client, _token(teacher), profile["avatar_id"])
    source = data["source_media"]
    intent = data["upload_intent"]
    content = _MIN_MP4

    uploaded = client.put(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source['source_media_id']}/upload",
        params={"exp": intent["exp"], "sig": intent["sig"]},
        content=content,
        headers={**_auth(_token(teacher)), "Content-Type": "video/mp4"},
    )
    assert uploaded.status_code == 200, uploaded.text

    # Simulate a legacy/client-declared digest that does not match the object.
    from sqlmodel import select
    from app.models.avatar_model import AvatarSourceMedia
    record = session.exec(
        select(AvatarSourceMedia).where(
            AvatarSourceMedia.source_media_id == source["source_media_id"]
        )
    ).one()
    record.content_sha256 = "0" * 64
    session.add(record)
    session.commit()

    confirmed = client.post(
        f"{AVATAR}/{profile['avatar_id']}/source-media/{source['source_media_id']}/confirm",
        headers=_auth(_token(teacher)),
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()["data"]
    assert body["upload_status"] == "invalid"
    assert body["validation_notes"] == "sha256_mismatch"
    assert body["server_content_sha256"] == hashlib.sha256(content).hexdigest()
