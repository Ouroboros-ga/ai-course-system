"""T5 provider 分派回归：autonomous runs 走 Runtime console/cancel 分支。

- linkage 允许 job_id 为空（无 Worker 作业）；恢复查询/备注/取消的归属
  依据照常；
- 列表/详情合并 Runtime console（attempt 投影＋reconciling 语义），
  Runtime 失联回落快照且 stale，不伪造终态；
- 用户取消直达 Runtime（回收确认后 cancelled；失联 503 不伪装）；
- Agent 取消仍走一次性授权（grant），核销后按 provider 分派；
- preset 路径不受影响（job 维度照旧）。
全离线：Runtime/Worker 一律 MockTransport，不出网。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import httpx

from app.api.v1.endpoints import nexus_internal, nexus_proxy
from app.core.security import create_access_token
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.services import nexus_run_service

RUNTIME_URL = "http://127.0.0.1:8300"
SERVICE_TOKEN = "test-nexus-service-token"
INTERNAL_TOKEN = "internal-tok"
UID = "t5-user-1"
SID = "t5-session-1"


@contextmanager
def mock_runtime(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    with patch.object(nexus_proxy.httpx, "AsyncClient", factory):
        yield


def _token_for(user) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _grant_fixture(monkeypatch, session, student_user):
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_URL", RUNTIME_URL)
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_API_KEY", SERVICE_TOKEN)
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = INTERNAL_TOKEN
    session.add(PlatformPermissionAssignment(
        user_id=student_user.id,
        permission=PlatformPermission.NEXUS_USE,
    ))
    session.commit()
    return _token_for(student_user)


def _record_auto(session, run_id, user=UID, session_id=SID, **kw):
    args = {"run_id": run_id, "user_id": user, "session_id": session_id,
            "tool": "autonomous_experiment", "preset_id": "", "job_id": "",
            "status": "running", "proposal_id": "pp_t5",
            "config_snapshot": {"kind": "autonomous_experiment"},
            "preset_display_name": "自主实验"}
    args.update(kw)
    return nexus_run_service.record_run(session, **args)


def _console_snapshot(run_id, status="running", console_status="running"):
    return {"snapshot": {
        "run_id": run_id, "status": status, "console_status": console_status,
        "attempt_no": 2,
        "attempts": [
            {"attempt_no": 1, "operation_id": f"{run_id}-op-0001",
             "command_summary": "pip install -r requirements.txt",
             "duration_s": 12.0, "log_tail": "ok", "exit_code": 0,
             "result": "succeeded"},
            {"attempt_no": 2, "operation_id": f"{run_id}-op-0002",
             "command_summary": "python train.py", "duration_s": None,
             "log_tail": "Epoch 1/10", "exit_code": None, "result": "running"},
        ],
        "active_operation": f"{run_id}-op-0002", "detail": "",
    }}


def test_autonomous_linkage_accepts_empty_job_id(client, session, monkeypatch):
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = INTERNAL_TOKEN
    try:
        response = client.post(
            "/api/v1/nexus-internal/repro-runs",
            json={"run_id": "apv_t5_link", "session_id": SID,
                  "tool": "autonomous_experiment", "job_id": "",
                  "status": "running", "proposal_id": "pp_t5",
                  "config_snapshot": {"kind": "autonomous_experiment"}},
            headers={"Authorization": f"Bearer {INTERNAL_TOKEN}",
                     "X-Nexus-User-Id": "99"},
        )
    finally:
        nexus_internal.settings.NEXUS_INTERNAL_TOKEN = ""
    assert response.status_code == 200
    row = nexus_run_service.get_owned_run(session, user_id="99", run_id="apv_t5_link")
    assert row is not None and row["tool"] == "autonomous_experiment"
    assert row["job_id"] == ""


def test_runs_list_merges_runtime_console(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_list", user=uid, session_id=SID)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/console")
        assert request.headers.get("X-Nexus-User-Id") == uid
        return httpx.Response(200, json=_console_snapshot("apv_t5_list"))

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/runs?session_id=" + SID,
                              headers=_auth(token))
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["provider"] == "autonomous"
    assert item["live"]["status"] == "running"
    assert item["stale"] is False
    assert len(item["attempts"]) == 2
    assert item["attempts"][1]["command_summary"] == "python train.py"


def test_runs_list_runtime_down_falls_back_snapshot(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_down", user=uid, session_id=SID)

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/runs?session_id=" + SID,
                              headers=_auth(token))
    assert response.status_code == 200
    item = response.json()["items"][0]
    # 回落登记快照且标 stale；不伪造终态。
    assert item["stale"] is True
    assert item["status"] == "running"


def test_run_detail_autonomous_has_attempts(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_detail", user=uid, session_id=SID)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_console_snapshot("apv_t5_detail"))

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/runs/apv_t5_detail", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "autonomous"
    assert body["live"]["status"] == "running"
    assert body["artifacts"] == []


def test_user_cancel_autonomous_calls_runtime(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_cancel", user=uid, session_id=SID)
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen[request.method + request.url.path] = True
        return httpx.Response(200, json={"run_id": "apv_t5_cancel",
                                         "status": "cancelled",
                                         "already_terminal": False})

    with mock_runtime(handler):
        response = client.post("/api/v1/nexus/runs/apv_t5_cancel/cancel",
                               json={"session_id": SID}, headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert "POST/api/v1/nexus/repro/runs/apv_t5_cancel/cancel" in seen
    row = nexus_run_service.get_owned_run(session, user_id=uid, run_id="apv_t5_cancel")
    assert row["status"] == "cancelled"


def test_user_cancel_runtime_down_is_503_not_fake(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_cdown", user=uid, session_id=SID)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "CONTROL_UNAVAILABLE"})

    with mock_runtime(handler):
        response = client.post("/api/v1/nexus/runs/apv_t5_cdown/cancel",
                               json={"session_id": SID}, headers=_auth(token))
    assert response.status_code == 503
    row = nexus_run_service.get_owned_run(session, user_id=uid, run_id="apv_t5_cdown")
    assert row["status"] == "running"


def test_internal_cancel_grant_flow_autonomous(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_grant", user=uid, session_id=SID)
    internal = {"Authorization": f"Bearer {INTERNAL_TOKEN}",
                "X-Nexus-User-Id": uid, "X-Nexus-Session-Id": SID}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json={"run_id": "apv_t5_grant",
                                             "status": "cancelled",
                                             "already_terminal": False})
        return httpx.Response(200, json=_console_snapshot("apv_t5_grant"))

    with mock_runtime(handler):
        # 无授权 → confirmation_required（零取消）。
        first = client.post("/api/v1/nexus-internal/runs/apv_t5_grant/cancel",
                            headers=internal)
        assert first.json()["data"]["status"] == "confirmation_required"
        # 用户签发一次性授权 → 核销后经 Runtime 取消。
        grant = client.post("/api/v1/nexus/runs/apv_t5_grant/cancel-grant",
                            json={"session_id": SID}, headers=_auth(token))
        assert grant.status_code == 200
        second = client.post("/api/v1/nexus-internal/runs/apv_t5_grant/cancel",
                             headers=internal)
        assert second.json()["data"]["status"] == "cancelled"
    row = nexus_run_service.get_owned_run(session, user_id=uid, run_id="apv_t5_grant")
    assert row["status"] == "cancelled"


def test_notes_on_autonomous_run(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_note", user=uid, session_id=SID)
    created = client.post("/api/v1/nexus/runs/apv_t5_note/notes",
                          json={"content": "用户备注", "request_id": "n1"},
                          headers=_auth(token))
    assert created.status_code == 200
    agent = client.post("/api/v1/nexus-internal/runs/apv_t5_note/notes",
                        json={"content": "智能体解释", "request_id": "n2"},
                        headers={"Authorization": f"Bearer {INTERNAL_TOKEN}",
                                 "X-Nexus-User-Id": uid,
                                 "X-Nexus-Session-Id": SID})
    assert agent.status_code == 200
    listed = client.get("/api/v1/nexus/runs/apv_t5_note/notes", headers=_auth(token))
    kinds = [n["author_kind"] for n in listed.json()["items"]]
    assert kinds == ["user", "agent"]


def test_cross_user_run_invisible(client, session, student_user, monkeypatch):
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_cross", user=uid, session_id=SID)

    async def _must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("他人 run 不得触达 Runtime")

    other = None
    # 无归属用户：服务层直验不可见（路由层 404/空列表语义由既有用例覆盖）。
    assert nexus_run_service.get_owned_run(session, user_id="stranger",
                                           run_id="apv_t5_cross") is None
    assert other is None
    with mock_runtime(_must_not_call):
        listing = client.get("/api/v1/nexus/runs?session_id=other-session",
                             headers=_auth(token))
    assert listing.status_code == 200
    assert listing.json()["items"] == []


def test_internal_status_projects_attempts(client, session, student_user, monkeypatch):
    _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t5_ctx", user=uid, session_id=SID)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_console_snapshot("apv_t5_ctx"))

    with mock_runtime(handler):
        response = client.get(
            "/api/v1/nexus-internal/runs/apv_t5_ctx/status",
            headers={"Authorization": f"Bearer {INTERNAL_TOKEN}",
                     "X-Nexus-User-Id": uid, "X-Nexus-Session-Id": SID},
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "autonomous"
    assert data["status"] == "running"
    assert len(data["steps"]) == 2
    assert data["steps"][1]["command"] == "python train.py"
    assert data["steps"][1]["exit_code"] is None


def test_run_report_proxy_passthrough(client, session, student_user, monkeypatch):
    """T6：报告生成代理——归属先行，本人透传 Runtime；他人 404 不上行。"""
    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_t6_rep", user=uid, session_id=SID,
                 status="succeeded")
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = True
        return httpx.Response(200, json={
            "run_id": "apv_t6_rep", "content_version": "experiment-report/1",
            "execution_succeeded": True, "metric_verdict": "not_evaluated",
            "comparison": [], "clean_verification": "not_run",
            "artifacts": [{"artifact_id": "art-1"}]})

    with mock_runtime(handler):
        ok_response = client.post("/api/v1/nexus/runs/apv_t6_rep/report",
                                  headers=_auth(token))
        assert ok_response.status_code == 200
        assert ok_response.json()["metric_verdict"] == "not_evaluated"
        assert "/api/v1/nexus/repro/runs/apv_t6_rep/report" in seen
        # 他人 run：404 且不上行（seen 不再增长）。
        missing = client.post("/api/v1/nexus/runs/apv_nope/report",
                              headers=_auth(token))
        assert missing.status_code == 404
        assert len(seen) == 1


def test_clean_verify_forwards_declared_mode_only(client, session, student_user, monkeypatch):
    """SR6 回归：clean-verify 只透传声明字段（签名键不进 Runtime forbid 模型）。

    未知模式 400（不上行）；未声明字段 422；ask＋签名键透传上游 body 恰为
    {"research_execution_mode": "ask"}（线上 E2E 实证：透传 time/enc 会被
    Runtime extra=forbid 以 422 拒绝）。
    """
    import json as _json

    token = _grant_fixture(monkeypatch, session, student_user)
    uid = str(student_user.id)
    _record_auto(session, "apv_sr6_cv", user=uid, session_id=SID,
                 status="succeeded")
    # 未知模式 → 400（门在代理层）。
    bad = client.post("/api/v1/nexus/runs/apv_sr6_cv/clean-verify",
                      json={"research_execution_mode": "turbo"},
                      headers=_auth(token))
    assert bad.status_code == 400
    # 未声明字段 → 422（签名键 time/enc 除外）。
    junk = client.post("/api/v1/nexus/runs/apv_sr6_cv/clean-verify",
                       json={"research_execution_mode": "auto", "owner": "x"},
                       headers=_auth(token))
    assert junk.status_code == 422
    # ask＋签名键 → 上游 body 恰为声明字段（透传成功与否由 Runtime 决定）。
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = _json.loads(request.content.decode() or "{}")
        return httpx.Response(403, json={"detail": "CLEAN_EXECUTION_DISABLED"})

    with mock_runtime(handler):
        ask = client.post(
            "/api/v1/nexus/runs/apv_sr6_cv/clean-verify",
            json={"research_execution_mode": "ask",
                  "time": "2026-09-09 00:00:00", "enc": "ABCDEF"},
            headers=_auth(token))
    assert ask.status_code == 403
    assert seen["body"] == {"research_execution_mode": "ask"}
