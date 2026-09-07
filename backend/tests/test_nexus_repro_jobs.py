"""M4-B1/B3：复现作业归属与查询代理契约（fail-closed + 发起人鉴权）。

涉表断言（归属登记/查询）PG-only，SQLite 上跳过由线上验收覆盖——
与 nexus_artifacts 同策略。
"""

import pytest
from httpx import Response

from app.api.v1.endpoints import nexus_internal, nexus_proxy
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.core.security import create_access_token
from app.services import nexus_repro_job_service

AUTH = {"Authorization": "Bearer internal-token-1"}

_is_pg = None


def _skip_if_sqlite(session):
    global _is_pg
    if _is_pg is None:
        _is_pg = session.connection().dialect.name != "sqlite"
    if not _is_pg:
        pytest.skip("nexus_repro_jobs 为 PG-only 域表，涉表断言由线上验收覆盖")


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


def test_record_repro_job_fails_closed_without_token(client):
    response = client.post(
        "/api/v1/nexus-internal/repro-jobs",
        json={"job_id": "abc123def456"},
        headers={"X-Nexus-User-Id": "42"},
    )
    assert response.status_code == 503


def test_record_repro_job_requires_user_identity(client, internal_configured):
    response = client.post(
        "/api/v1/nexus-internal/repro-jobs",
        json={"job_id": "abc123def456"},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_job_status_requires_ownership_even_without_worker(
    client, session, nexus_student_token, internal_configured
):
    """归属表无记录（未登记）→ 404，先于 Worker 配置检查（防枚举优先）。"""
    _skip_if_sqlite(session)
    response = client.get(
        "/api/v1/nexus/repro/jobs/nonexistent0",
        headers=_auth(nexus_student_token),
    )
    assert response.status_code == 404


def test_job_status_proxies_trimmed_record(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    """已登记 job：发起人可查，返回裁剪记录（NX-E2：日志 ≤2000 字符＋控制符
    清洗＋stage_events/current_step/live_log_tail 透传）。"""
    _skip_if_sqlite(session)
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = "abc123def456"
    nexus_repro_job_service.record_job(
        session, job_id=job_id, user_id=str(student_user.id), preset_id="nanogpt"
    )

    seen: dict = {}
    dirty_log = "x" * 2000 + "\x1b[31mANSI\x07\x00"

    def factory(**kwargs):
        def handler(request) -> Response:
            seen["path"] = request.url.path
            seen["auth"] = request.headers.get("Authorization")
            return Response(200, json={
                "job_id": job_id,
                "status": "running",
                "preset_id": "nanogpt",
                "license_checks": {"github_spdx": "MIT"},
                "steps_result": [{"command": "python train.py ...", "exit_code": 0, "timed_out": False, "duration_s": 170.9, "log_tail": dirty_log}],
                "artifacts": [],
                "stage_events": [
                    {"seq": 1, "stage": "preparing", "status": "started", "time": 1.0},
                    {"seq": 2, "stage": "running", "status": "started", "time": 2.0},
                ],
                "current_step": 1,
                "live_log_tail": dirty_log,
            })
        import httpx as _httpx
        kwargs["transport"] = _httpx.MockTransport(handler)
        return _httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(nexus_proxy.httpx, "AsyncClient", factory)
    response = client.get(f"/api/v1/nexus/repro/jobs/{job_id}", headers=_auth(nexus_student_token))
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert len(body["steps_result"][0]["log_tail"]) <= 2000
    assert "\x1b" not in body["steps_result"][0]["log_tail"]
    assert "\x00" not in body["steps_result"][0]["log_tail"]
    assert body["current_step"] == 1
    assert [e["stage"] for e in body["stage_events"]] == ["preparing", "running"]
    assert len(body["live_log_tail"]) <= 2000
    assert seen["path"] == f"/jobs/{job_id}"
    assert seen["auth"] == "Bearer wtok"


def test_cancel_requires_ownership_before_worker(
    client, session, nexus_student_token, internal_configured
):
    """NX-E3：归属表无记录 → 404，先于 Worker 配置检查（防枚举优先）。"""
    _skip_if_sqlite(session)
    response = client.post(
        "/api/v1/nexus/repro/jobs/nonexistent0/cancel",
        headers=_auth(nexus_student_token),
    )
    assert response.status_code == 404


def test_cancel_proxies_with_auth_and_state(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    """NX-E3：发起人鉴权后转发 Worker cancel；cancelling/already_terminal 透传。"""
    _skip_if_sqlite(session)
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = "cancel11job1"
    nexus_repro_job_service.record_job(
        session, job_id=job_id, user_id=str(student_user.id), preset_id="nanogpt"
    )

    seen: dict = {}

    def factory(**kwargs):
        def handler(request) -> Response:
            seen["path"] = request.url.path
            seen["method"] = request.method
            seen["auth"] = request.headers.get("Authorization")
            return Response(200, json={"job_id": job_id, "status": "cancelling"})
        import httpx as _httpx
        kwargs["transport"] = _httpx.MockTransport(handler)
        return _httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(nexus_proxy.httpx, "AsyncClient", factory)
    response = client.post(f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token))
    assert response.status_code == 200
    body = response.json()
    assert body == {"job_id": job_id, "status": "cancelling", "already_terminal": False}
    assert seen["method"] == "POST"
    assert seen["path"] == f"/jobs/{job_id}/cancel"
    assert seen["auth"] == "Bearer wtok"


def test_cancel_forbids_non_owner(
    client, session, nexus_student_token, student_user, internal_configured
):
    _skip_if_sqlite(session)
    job_id = "owner99owner2"
    nexus_repro_job_service.record_job(session, job_id=job_id, user_id="999999")
    response = client.post(
        f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token)
    )
    assert response.status_code == 404


def test_cancel_fails_closed_without_worker(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    _skip_if_sqlite(session)
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "")
    job_id = "abc123def456"
    nexus_repro_job_service.record_job(
        session, job_id=job_id, user_id=str(student_user.id), preset_id="nanogpt"
    )
    response = client.post(
        f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token)
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "REPRO_WORKER_NOT_CONFIGURED"


def test_job_status_forbids_non_owner(
    client, session, nexus_student_token, student_user, internal_configured
):
    """他人 job（已登记给其他用户）→ 404（不暴露存在性）。"""
    _skip_if_sqlite(session)
    job_id = "owner99owner1"
    nexus_repro_job_service.record_job(session, job_id=job_id, user_id="999999")
    response = client.get(f"/api/v1/nexus/repro/jobs/{job_id}", headers=_auth(nexus_student_token))
    assert response.status_code == 404


def test_report_proxies_to_runtime_with_identity(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    """报告代理：发起人鉴权后透传 Runtime（身份头透传契约）。"""
    _skip_if_sqlite(session)
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_URL", "http://127.0.0.1:8300")
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_API_KEY", "test-nexus-service-token")
    job_id = "abc123def456"
    nexus_repro_job_service.record_job(session, job_id=job_id, user_id=str(student_user.id))

    seen: dict = {}
    from app.api.v1.endpoints import nexus_proxy as proxy_module

    def factory(**kwargs):
        def handler(request) -> Response:
            seen["path"] = request.url.path
            seen["user"] = request.headers.get("X-Nexus-User-Id")
            return Response(200, json={"verdict": "PASS", "artifacts": []})
        import httpx as _httpx
        kwargs["transport"] = _httpx.MockTransport(handler)
        return _httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", factory)
    response = client.post(f"/api/v1/nexus/repro/jobs/{job_id}/report", headers=_auth(nexus_student_token))
    assert response.status_code == 200
    assert seen["path"] == f"/api/v1/nexus/repro/jobs/{job_id}/report"
    assert seen["user"] == str(student_user.id)


def test_report_requires_ownership(client, session, nexus_student_token):
    _skip_if_sqlite(session)
    response = client.post(
        "/api/v1/nexus/repro/jobs/nonexistent0/report",
        headers=_auth(nexus_student_token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 边界修复批次（2026-09-07，审查 F1/F2）
# ---------------------------------------------------------------------------


def _owned_job(session, student_user, job_id: str) -> None:
    nexus_repro_job_service.record_job(
        session, job_id=job_id, user_id=str(student_user.id), preset_id="nanogpt"
    )


def _worker_factory(status_code: int, payload=None, raw: str = None):
    """返回替换 nexus_proxy.httpx.AsyncClient 的工厂：Worker 恒定回给定响应。

    注意必须在打补丁**前**捕获原始 AsyncClient——monkeypatch 的是全局
    httpx 模块属性，工厂体内再取 _httpx.AsyncClient 会命中工厂自身递归。
    """
    import httpx as _httpx

    original_client = _httpx.AsyncClient

    def factory(**kwargs):
        def handler(request) -> Response:
            if raw is not None:
                return Response(status_code, text=raw)
            return Response(status_code, json=payload if payload is not None else {})

        kwargs["transport"] = _httpx.MockTransport(handler)
        return original_client(**kwargs)

    return factory


@pytest.mark.parametrize("upstream_status", [401, 500, 502, 503])
def test_cancel_maps_worker_http_errors_to_502(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch,
    upstream_status,
):
    """F1：Worker 任何非成功 HTTP 响应一律 502 上抛，不得包装成"已接受取消"。"""
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = f"cancelerrjob{upstream_status:02d}"
    _owned_job(session, student_user, job_id)
    monkeypatch.setattr(nexus_proxy.httpx, "AsyncClient", _worker_factory(upstream_status, {"job_id": job_id}))
    response = client.post(
        f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token)
    )
    assert response.status_code == 502
    assert response.json()["message"] == "REPRO_CANCEL_UPSTREAM_ERROR"


def test_cancel_rejects_malformed_json_and_identity_or_status_anomalies(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    """F1：200 但畸形 JSON / job_id 不一致 / 状态缺失或未知 → 502，绝不默认 cancelling。"""
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = "canceloddjob01"
    _owned_job(session, student_user, job_id)

    cases = [
        (_worker_factory(200, raw="not-json{"), 502, "Worker 返回非 JSON"),
        (_worker_factory(200, {"job_id": "other-job-99", "status": "cancelling"}), 502, "REPRO_CANCEL_IDENTITY_MISMATCH"),
        (_worker_factory(200, {"job_id": job_id}), 502, "REPRO_CANCEL_UNKNOWN_STATUS"),
        (_worker_factory(200, {"job_id": job_id, "status": "weird-state"}), 502, "REPRO_CANCEL_UNKNOWN_STATUS"),
    ]
    for factory, want_status, want_detail in cases:
        monkeypatch.setattr(nexus_proxy.httpx, "AsyncClient", factory)
        response = client.post(
            f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token)
        )
        assert response.status_code == want_status, factory
        assert response.json()["message"] == want_detail, factory


def test_cancel_success_passthrough_terminal_status(
    client, session, nexus_student_token, student_user, internal_configured, monkeypatch
):
    """F1：Worker 成功响应（已知状态 + 身份一致）原样透传。"""
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = "cancelokjob001"
    _owned_job(session, student_user, job_id)
    monkeypatch.setattr(
        nexus_proxy.httpx, "AsyncClient",
        _worker_factory(200, {"job_id": job_id, "status": "cancelled", "already_terminal": True}),
    )
    response = client.post(
        f"/api/v1/nexus/repro/jobs/{job_id}/cancel", headers=_auth(nexus_student_token)
    )
    assert response.status_code == 200
    assert response.json() == {"job_id": job_id, "status": "cancelled", "already_terminal": True}


def test_sanitize_log_redacts_credentials_and_ansi():
    """F2：Bearer/Authorization/键值密钥/URL 用户信息/ANSI 在代理出口脱敏；
    普通训练指标不受损。"""
    dirty = (
        "step 1 ok, loss=0.1234, tokens: 99999\n"
        "Authorization: Basic dXNlcjpwYXNz\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456\n"
        "password=hunter2 api_key=abcd1234efgh5678\n"
        "clone https://user:secretpw@example.com/org/repo.git\n"
        "\x1b[32mtrain done\x1b[0m\n"
    )
    clean = nexus_proxy._sanitize_log(dirty)
    assert "dXNlcjpwYXNz" not in clean
    assert "eyJhbGciOiJIUzI1NiJ9" not in clean
    assert "hunter2" not in clean
    assert "abcd1234efgh5678" not in clean
    assert "secretpw" not in clean
    assert "\x1b" not in clean
    assert "loss=0.1234" in clean
    assert "tokens: 99999" in clean
    assert "train done" in clean
    assert "example.com/org/repo.git" in clean
