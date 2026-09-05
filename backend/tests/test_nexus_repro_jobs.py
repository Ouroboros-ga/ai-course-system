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
    """已登记 job：发起人可查，返回裁剪记录（日志摘要 ≤300 字符）。"""
    _skip_if_sqlite(session)
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", "http://127.0.0.1:8400")
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", "wtok")
    job_id = "abc123def456"
    nexus_repro_job_service.record_job(
        session, job_id=job_id, user_id=str(student_user.id), preset_id="nanogpt"
    )

    seen: dict = {}

    def factory(**kwargs):
        def handler(request) -> Response:
            seen["path"] = request.url.path
            seen["auth"] = request.headers.get("Authorization")
            big_log = "x" * 2000
            return Response(200, json={
                "job_id": job_id,
                "status": "succeeded",
                "preset_id": "nanogpt",
                "license_checks": {"github_spdx": "MIT"},
                "steps_result": [{"command": "python train.py ...", "exit_code": 0, "timed_out": False, "duration_s": 170.9, "log_tail": big_log}],
                "artifacts": [],
            })
        import httpx as _httpx
        kwargs["transport"] = _httpx.MockTransport(handler)
        return _httpx.AsyncClient(**kwargs)

    monkeypatch.setattr(nexus_proxy.httpx, "AsyncClient", factory)
    response = client.get(f"/api/v1/nexus/repro/jobs/{job_id}", headers=_auth(nexus_student_token))
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == job_id
    assert len(body["steps_result"][0]["log_tail"]) <= 300
    assert seen["path"] == f"/jobs/{job_id}"
    assert seen["auth"] == "Bearer wtok"


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
