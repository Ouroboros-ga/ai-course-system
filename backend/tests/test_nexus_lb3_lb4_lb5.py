"""NX-LB3/LB4/LB5 后端回归：运行上下文投影、取消授权、备注、产物关联。

- LB3：chat 的 context.run_ref → 服务端白名单投影（归属/会话/step 校验、
  有界日志 ≤40 行 ≤8000 字符、服务端脱敏、客户端执行事实不透传）；
- LB4：取消授权签发（登录态一次性）+ 内部取消（无授权→confirmation_required，
  终态→already_terminal，Worker 语义复用取消代理）；
- LB5：追加式运行备注（幂等/owner/agent 标记）+ run 详情已授权产物引用；
- 回归：签名键 time/enc 随 body 不再 422（前端 request.js 契约），
  未声明字段仍 422。
全离线：Worker/Runtime 一律 MockTransport，不出网。
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from app.api.v1.endpoints import nexus_internal, nexus_proxy
from app.services import nexus_run_service

from tests.test_nexus_lb1_lb2 import (
    _auth,
    _record,
    mock_runtime,
    nexus_student_token,  # noqa: F401
    runtime_configured,   # noqa: F401
)

UID = "lb3-user-1"
SID = "lb3-session-1"
WORKER_URL = "http://127.0.0.1:8410"
WORKER_TOKEN = "worker-token-1"

RUNTIME_URL = "http://127.0.0.1:8300"
SERVICE_TOKEN = "test-nexus-service-token"


@pytest.fixture
def worker_configured(monkeypatch):
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_URL", WORKER_URL)
    monkeypatch.setattr(nexus_proxy.settings, "REPRO_WORKER_TOKEN", WORKER_TOKEN)


@pytest.fixture
def internal_token(monkeypatch):
    monkeypatch.setattr(nexus_internal.settings, "NEXUS_INTERNAL_TOKEN", "internal-tok")
    return {"Authorization": "Bearer internal-tok"}


def _long_log(line_count=60):
    return "\n".join(f"iter {i}: loss {1 + i / 100:.4f}" for i in range(line_count))


def _live_job(job_id="job-lb3-1", status="running", log=None, steps=None):
    return {
        "job_id": job_id, "status": status, "preset_id": "nanogpt",
        "steps_result": steps if steps is not None else [
            {"command": "python train.py --max_iters=100", "exit_code": 0,
             "timed_out": False, "duration_s": 1.0,
             "log_tail": log if log is not None else "iter 99: loss 2.70"}],
        "stage_events": [{"seq": 1, "stage": "setup", "status": "done",
                          "note": None, "time": 1}],
        "current_step": 0,
    }


def _combined_mock(runtime_handler, worker_handler):
    """单补丁双路调度（Runtime:8300 / Worker:8410）：避免双重 patch 同一属性。

    两个上游都经 nexus_proxy.httpx.AsyncClient；按 URL 端口分流。
    """
    real_client = httpx.AsyncClient

    async def router(request: httpx.Request) -> httpx.Response:
        if request.url.port == 8410:
            return await worker_handler(request)
        return await runtime_handler(request)

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(router)
        return real_client(**kwargs)

    return patch.object(nexus_proxy.httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------------
# LB3：chat run_ref → 服务端白名单投影
# ---------------------------------------------------------------------------


def test_chat_run_ref_injects_server_context(
    client, session, nexus_student_token, student_user, runtime_configured,
    worker_configured
):
    """run_ref 被替换为服务端投影；客户端自带 run_context 被丢弃。"""
    uid = str(student_user.id)
    _record(session, "lb3-r1", user=uid, session_id=SID, job_id="job-lb3-1")
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"session_id": SID, "message": "ok"})

    async def worker_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_live_job())

    with _combined_mock(handler, worker_handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "为什么卡住了", "session_id": SID, "mode": "research",
                  "context": {"run_ref": {"run_id": "lb3-r1"},
                              "run_context": {"fake": "client-data"}}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 200
    ctx = captured["body"]["context"]
    assert "run_ref" not in ctx and "fake" not in ctx
    run_context = ctx["run_context"]
    assert run_context["run_id"] == "lb3-r1"
    assert run_context["status"] == "running"
    assert run_context["status_source"] == "live"
    assert run_context["steps"][0]["exit_code"] == 0
    assert "log" in run_context["steps"][0]


def test_chat_run_ref_rejects_cross_user_session_and_bad_step(
    client, session, nexus_student_token, student_user, runtime_configured,
    worker_configured
):
    uid = str(student_user.id)
    _record(session, "lb3-r2", user=uid, session_id=SID, job_id="job-x")
    other = _record(session, "lb3-r3", user="someone-else", session_id=SID,
                    job_id="job-y")
    assert other["run_id"] == "lb3-r3"

    async def worker_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_live_job(steps=[]))

    async def passthrough(request: httpx.Request) -> httpx.Response:
        raise AssertionError("校验失败不得触达 Runtime")

    with _combined_mock(passthrough, worker_handler):
        cross_user = client.post(
            "/api/v1/nexus/chat",
            json={"message": "m", "session_id": SID,
                  "context": {"run_ref": {"run_id": "lb3-other"}}},
            headers=_auth(nexus_student_token))
        assert cross_user.status_code == 404

        cross_session = client.post(
            "/api/v1/nexus/chat",
            json={"message": "m", "session_id": "another-session",
                  "context": {"run_ref": {"run_id": "lb3-r2"}}},
            headers=_auth(nexus_student_token))
        assert cross_session.status_code == 403
        assert cross_session.json()["message"] == "RUN_SESSION_MISMATCH"

        bad_step = client.post(
            "/api/v1/nexus/chat",
            json={"message": "m", "session_id": SID,
                  "context": {"run_ref": {"run_id": "lb3-r2", "step_id": 99}}},
            headers=_auth(nexus_student_token))
        assert bad_step.status_code == 422


def test_run_context_bounded_and_sanitized_log(
    client, session, nexus_student_token, student_user, runtime_configured,
    worker_configured
):
    """有界日志：≤40 行 ≤8000 字符 + truncated 标记 + 服务端脱敏。"""
    uid = str(student_user.id)
    _record(session, "lb3-r4", user=uid, session_id=SID, job_id="job-lb3-4")
    captured: dict = {}

    async def worker_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_live_job(log=(
            "password=super-secret-123\n" + _long_log(60))))

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": "ok"})

    with _combined_mock(handler, worker_handler):
        response = client.post(
            "/api/v1/nexus/chat",
            json={"message": "m", "session_id": SID,
                  "context": {"run_ref": {"run_id": "lb3-r4"}}},
            headers=_auth(nexus_student_token))
    assert response.status_code == 200
    log = captured["body"]["context"]["run_context"]["steps"][0]["log"]
    assert log["lines"] <= nexus_proxy._RUN_CTX_LOG_LINES
    assert log["total_lines"] == 61
    assert log["truncated"] is True
    assert "super-secret-123" not in log["text"]
    assert "iter 59" in log["text"], "应保留最近的行"


def test_run_context_log_bounds_direct():
    """_bounded_log_tail 单元：行数/字符双界 + 截断标记 + 脱敏。"""
    tail = nexus_proxy._bounded_log_tail("password=super-secret-123\n" + _long_log(60))
    assert tail["lines"] <= nexus_proxy._RUN_CTX_LOG_LINES
    assert tail["total_lines"] == 61
    assert tail["truncated"] is True
    assert "super-secret-123" not in tail["text"]
    assert "iter 59" in tail["text"], "应保留最近的行"
    short = nexus_proxy._bounded_log_tail("iter 0: ok")
    assert short == {"text": "iter 0: ok", "lines": 1, "total_lines": 1,
                     "truncated": False}


# ---------------------------------------------------------------------------
# LB4：取消授权 + 内部取消
# ---------------------------------------------------------------------------


def test_cancel_grant_endpoints_and_internal_flow(
    client, session, nexus_student_token, student_user, worker_configured
):
    uid = str(student_user.id)
    _record(session, "lb4-r1", user=uid, session_id=SID, job_id="job-lb4-1")
    internal_headers = {
        "Authorization": "Bearer internal-tok",
        "X-Nexus-User-Id": uid,
        "X-Nexus-Session-Id": SID,
    }
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = "internal-tok"

    # 无授权 → confirmation_required（一次性授权必须由用户签发）。
    no_grant = client.post(
        "/api/v1/nexus-internal/runs/lb4-r1/cancel", headers=internal_headers)
    assert no_grant.status_code == 200
    assert no_grant.json()["data"]["status"] == "confirmation_required"
    assert no_grant.json()["data"]["code"] == "CANCEL_CONFIRMATION_REQUIRED"

    # 用户确认 → 签发一次性授权。
    grant = client.post("/api/v1/nexus/runs/lb4-r1/cancel-grant",
                        json={"session_id": SID},
                        headers=_auth(nexus_student_token))
    assert grant.status_code == 200
    assert grant.json()["action"] == "cancel_run"
    assert grant.json()["consumed"] is False

    async def _must_not_reach_runtime(request: httpx.Request) -> httpx.Response:
        raise AssertionError("内部取消不得经过 Runtime 透传")

    async def worker_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/jobs/job-lb4-1/cancel")
        return httpx.Response(200, json={"job_id": "job-lb4-1",
                                         "status": "cancelling"})

    with _combined_mock(_must_not_reach_runtime, worker_handler):
        cancelled = client.post(
            "/api/v1/nexus-internal/runs/lb4-r1/cancel", headers=internal_headers)
    assert cancelled.status_code == 200
    body = cancelled.json()["data"]
    assert body["status"] == "cancelling" and body["job_id"] == "job-lb4-1"

    # 授权一次性：第二次需要重新确认。
    again = client.post(
        "/api/v1/nexus-internal/runs/lb4-r1/cancel", headers=internal_headers)
    assert again.json()["data"]["status"] == "confirmation_required"


def test_internal_cancel_terminal_run_needs_no_grant(
    client, session, nexus_student_token, student_user
):
    uid = str(student_user.id)
    _record(session, "lb4-r2", user=uid, session_id=SID, job_id="job-lb4-2",
            status="succeeded")
    headers = {"Authorization": "Bearer internal-tok",
               "X-Nexus-User-Id": uid, "X-Nexus-Session-Id": SID}
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = "internal-tok"
    response = client.post("/api/v1/nexus-internal/runs/lb4-r2/cancel",
                           headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["already_terminal"] is True
    assert data["status"] == "succeeded"


def test_internal_run_endpoints_reject_cross_session_and_bad_token(
    client, session, nexus_student_token, student_user
):
    uid = str(student_user.id)
    _record(session, "lb4-r3", user=uid, session_id=SID, job_id="job-lb4-3")
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = "internal-tok"
    owner = {"Authorization": "Bearer internal-tok",
             "X-Nexus-User-Id": uid, "X-Nexus-Session-Id": "other-session"}
    cross = client.get("/api/v1/nexus-internal/runs/lb4-r3/status", headers=owner)
    assert cross.status_code == 403
    bad_token = {"Authorization": "Bearer wrong", "X-Nexus-User-Id": uid,
                 "X-Nexus-Session-Id": SID}
    unauthorized = client.get("/api/v1/nexus-internal/runs/lb4-r3/status",
                              headers=bad_token)
    assert unauthorized.status_code == 401


# ---------------------------------------------------------------------------
# LB5：运行备注
# ---------------------------------------------------------------------------


def test_run_notes_append_idempotent_and_isolated(
    client, session, nexus_student_token, student_user
):
    uid = str(student_user.id)
    _record(session, "lb5-r1", user=uid, session_id=SID, job_id="job-lb5-1")

    first = client.post("/api/v1/nexus/runs/lb5-r1/notes",
                        json={"content": "注意到 loss 收敛", "request_id": "req-1"},
                        headers=_auth(nexus_student_token))
    assert first.status_code == 200
    note = first.json()
    assert note["author_kind"] == "user"
    assert note["deduped"] is False

    dup = client.post("/api/v1/nexus/runs/lb5-r1/notes",
                      json={"content": "注意到 loss 收敛", "request_id": "req-1"},
                      headers=_auth(nexus_student_token))
    assert dup.status_code == 200
    assert dup.json()["deduped"] is True
    assert dup.json()["note_id"] == note["note_id"]

    too_long = client.post("/api/v1/nexus/runs/lb5-r1/notes",
                           json={"content": "x" * 4001},
                           headers=_auth(nexus_student_token))
    assert too_long.status_code == 422

    unknown = client.post("/api/v1/nexus/runs/lb5-nope/notes",
                          json={"content": "x"},
                          headers=_auth(nexus_student_token))
    assert unknown.status_code == 404

    listing = client.get("/api/v1/nexus/runs/lb5-r1/notes",
                         headers=_auth(nexus_student_token))
    assert listing.status_code == 200
    assert [n["note_id"] for n in listing.json()["items"]] == [note["note_id"]]

    # 他人不可见也不可写。
    other = _record(session, "lb5-r2", user="another-user", session_id=SID,
                    job_id="job-lb5-2")
    assert other["run_id"] == "lb5-r2"
    foreign = client.get("/api/v1/nexus/runs/lb5-r2/notes",
                         headers=_auth(nexus_student_token))
    assert foreign.status_code == 200
    assert foreign.json()["items"] == []


def test_agent_notes_marked_agent_via_internal(
    client, session, nexus_student_token, student_user
):
    uid = str(student_user.id)
    _record(session, "lb5-r3", user=uid, session_id=SID, job_id="job-lb5-3")
    nexus_internal.settings.NEXUS_INTERNAL_TOKEN = "internal-tok"
    headers = {"Authorization": "Bearer internal-tok",
               "X-Nexus-User-Id": uid, "X-Nexus-Session-Id": SID}
    response = client.post("/api/v1/nexus-internal/runs/lb5-r3/notes",
                           json={"content": "建议增大 batch_size"},
                           headers=headers)
    assert response.status_code == 200
    note = response.json()["data"]
    assert note["author_kind"] == "agent"
    listing = client.get("/api/v1/nexus/runs/lb5-r3/notes",
                         headers=_auth(nexus_student_token))
    assert listing.json()["items"][0]["author_kind"] == "agent"


# ---------------------------------------------------------------------------
# LB5：run 详情的已授权产物引用
# ---------------------------------------------------------------------------


def test_run_detail_lists_authorized_artifacts(
    client, session, nexus_student_token, student_user, monkeypatch
):
    from app.services import nexus_artifact_service

    uid = str(student_user.id)
    _record(session, "lb5-r4", user=uid, session_id=SID, job_id="job-lb5-4")

    class _FakeStorage:
        def put(self, key, data, mime_type=None):
            return "sha-" + str(len(data))

    monkeypatch.setattr(
        "app.services.object_storage.get_object_storage", lambda: _FakeStorage())
    nexus_artifact_service._table_ready = False
    try:
        created = nexus_artifact_service.create_artifact(
            session, user_id=uid, artifact_type="markdown",
            title="复现报告 · nanogpt", content="# 报告", run_id="lb5-r4")
        # 不带 run_id 的产物不出现在该 run 的引用里。
        nexus_artifact_service.create_artifact(
            session, user_id=uid, artifact_type="markdown",
            title="无关产物", content="# 其他", run_id="")
        detail = client.get("/api/v1/nexus/runs/lb5-r4",
                            headers=_auth(nexus_student_token))
        assert detail.status_code == 200
        artifacts = detail.json()["artifacts"]
        assert [a["artifact_id"] for a in artifacts] == [created["artifact_id"]]
        assert artifacts[0]["download_path"] == (
            f"/api/v1/nexus/artifacts/{created['artifact_id']}/download")
    finally:
        nexus_artifact_service._table_ready = False


# ---------------------------------------------------------------------------
# 回归：签名键随 body 不再 422；未声明字段仍 422
# ---------------------------------------------------------------------------


def test_rename_and_proposal_patch_tolerate_signature_keys(
    client, session, nexus_student_token, student_user
):
    uid = str(student_user.id)
    _record(session, "lb5-r5", user=uid, session_id=SID, job_id="job-lb5-5")
    ok = client.patch(
        "/api/v1/nexus/runs/lb5-r5",
        json={"title": "命名", "expected_version": 1,
              "time": "2026-09-08 10:00:00", "enc": "ABC"},
        headers=_auth(nexus_student_token))
    assert ok.status_code == 200, "签名键不得触发 422"
    illegal = client.patch(
        "/api/v1/nexus/runs/lb5-r5",
        json={"title": "再命名", "expected_version": 2, "status": "succeeded",
              "time": "2026-09-08 10:00:00", "enc": "ABC"},
        headers=_auth(nexus_student_token))
    assert illegal.status_code == 422
