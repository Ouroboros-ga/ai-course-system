"""NX-LB1/LB2 后端回归：运行元数据＋提案代理。

- LB1：显式迁移（旧表补列/回填/播种，可重入）、会话内稳定序号（含并发
  唯一）、重命名乐观锁、分页稳定、display_title、presets 代理、列表新形状、
  终态免问 Worker、有界并发截止；
- LB2：提案代理透传（创建/详情/修改/批复）、PATCH 非法字段 422（Backend 先拦）。
全离线：Worker/Runtime 一律 MockTransport，不出网。
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.api.v1.endpoints import nexus_proxy
from app.core.security import create_access_token
from app.models.access_control_model import PlatformPermission, PlatformPermissionAssignment
from app.services import nexus_run_service

RUNTIME_URL = "http://127.0.0.1:8300"
SERVICE_TOKEN = "test-nexus-service-token"
UID = "lb-user-1"
SID = "lb-session-1"


@contextmanager
def mock_runtime(handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    with patch.object(nexus_proxy.httpx, "AsyncClient", factory):
        yield


@pytest.fixture
def runtime_configured(monkeypatch):
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_URL", RUNTIME_URL)
    monkeypatch.setattr(nexus_proxy.settings, "NEXUS_RUNTIME_API_KEY", SERVICE_TOKEN)


def _token_for(user) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


@pytest.fixture
def nexus_student_token(session, student_user):
    session.add(PlatformPermissionAssignment(
        user_id=student_user.id,
        permission=PlatformPermission.NEXUS_USE,
    ))
    session.commit()
    return _token_for(student_user)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _record(session, run_id, user=UID, session_id=SID, **kw):
    args = {"run_id": run_id, "user_id": user, "session_id": session_id,
            "preset_id": "nanogpt", "job_id": f"job-{run_id}", "status": "submitted"}
    args.update(kw)
    return nexus_run_service.record_run(session, **args)


# 各测试使用独立 (user, session) 命名空间：测试库文件在会话内持久，
# 序号计数器按命名空间隔离，互不干扰。


# ---------------------------------------------------------------------------
# LB1：显式迁移
# ---------------------------------------------------------------------------


def test_migrate_old_table_backfills_numbers_and_seeds_counters(session):
    """旧表（12 列）→ 迁移补列 → 旧行回填序号 → counters 播种；可重入。"""
    MU, MS = "lb-mig-user", "lb-mig"
    nexus_run_service._table_ready = False
    table = nexus_run_service._table(session)
    session.connection().execute(text(f"DROP TABLE IF EXISTS {table}"))
    session.connection().execute(text(
        f"CREATE TABLE {table} (run_id VARCHAR(64) PRIMARY KEY,"
        " user_id TEXT NOT NULL DEFAULT '', session_id TEXT NOT NULL DEFAULT '',"
        " tool TEXT NOT NULL DEFAULT '', preset_id TEXT NOT NULL DEFAULT '',"
        " plan_hash TEXT NOT NULL DEFAULT '', approval_id TEXT NOT NULL DEFAULT '',"
        " job_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'submitted',"
        " detail TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL DEFAULT 0,"
        " updated_at REAL NOT NULL DEFAULT 0)"))
    for i, rid in enumerate(("old-a", "old-b")):
        session.connection().execute(
            text(f"INSERT INTO {table} (run_id, user_id, session_id, created_at, updated_at)"
                 " VALUES (:r, :u, :s, :t, :t)"),
            {"r": rid, "u": MU, "s": MS, "t": 1000.0 + i})
    session.commit()
    try:
        result = nexus_run_service.migrate_nexus_runs(session)
        assert len(result["added_columns"]) == 9
        assert result["backfilled"] == 2
        assert result["counters_seeded"] == 1
        rows = {r["run_id"]: r for r in nexus_run_service.list_session_runs(
            session, user_id=MU, session_id=MS)}
        assert rows["old-a"]["run_number"] == 1
        assert rows["old-b"]["run_number"] == 2
        assert rows["old-a"]["version"] == 1
        # 可重入：第二次无新增、无回填。
        again = nexus_run_service.migrate_nexus_runs(session)
        assert again == {"added_columns": [], "backfilled": 0, "counters_seeded": 0}
        # 新行继续序号（播种生效）。
        third = _record(session, "lb-new-1", user=MU, session_id=MS)
        assert third["run_number"] == 3
    finally:
        nexus_run_service._table_ready = False
        nexus_run_service.ensure_table(session)


def test_run_numbers_stable_per_session_and_idempotent(session):
    nexus_run_service.ensure_table(session)
    first = _record(session, "lb-n1", user="lb-num-user", session_id="lb-num-a")
    second = _record(session, "lb-n2", user="lb-num-user", session_id="lb-num-a")
    other = _record(session, "lb-n3", user="lb-num-user", session_id="lb-num-b")
    assert (first["run_number"], second["run_number"], other["run_number"]) == (1, 2, 1)
    # 同 run_id 重登不烧号。
    again = _record(session, "lb-n1", user="lb-num-user", session_id="lb-num-a",
                    status="running")
    assert again["run_number"] == 1
    assert again["status"] == "running"


def test_run_numbers_unique_under_concurrency(test_engine):
    """10 线程同会话并发登记：序号两两不同（counters 原子递增）。"""
    nexus_run_service.ensure_table(Session(test_engine))
    errors: list = []
    numbers: list = []
    lock = threading.Lock()

    def _worker(i: int):
        try:
            with Session(test_engine) as session:
                row = _record(session, f"lb-c-{i}", user="lb-conc-user",
                              session_id="lb-conc")
                with lock:
                    numbers.append(row["run_number"])
        except Exception as error:  # noqa: BLE001
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert sorted(numbers) == list(range(1, 11))


# ---------------------------------------------------------------------------
# LB1：命名、展示、分页
# ---------------------------------------------------------------------------


def test_rename_optimistic_lock_and_default_restore(session):
    nexus_run_service.ensure_table(session)
    row = _record(session, "lb-r1", user="lb-ren-user", session_id="lb-ren",
                  preset_display_name="nanoGPT")
    assert row["display_title"] == "nanoGPT #1"
    renamed = nexus_run_service.rename_run(
        session, user_id="lb-ren-user", run_id="lb-r1",
        title="  第一次全量  ", expected_version=1)
    assert renamed is not None and renamed["title"] == "第一次全量"
    assert renamed["version"] == 2
    assert renamed["display_title"] == "第一次全量"
    # 陈旧版本 → 冲突（返回当前版本，不泄露他人数据）。
    with pytest.raises(nexus_run_service._VersionConflict) as exc:
        nexus_run_service.rename_run(
            session, user_id="lb-ren-user", run_id="lb-r1",
            title="x", expected_version=1)
    assert exc.value.current_version == 2
    # None 恢复默认名。
    restored = nexus_run_service.rename_run(
        session, user_id="lb-ren-user", run_id="lb-r1",
        title=None, expected_version=2)
    assert restored is not None and restored["title"] == ""
    assert restored["display_title"] == "nanoGPT #1"
    # 非 owner 不可见。
    assert nexus_run_service.rename_run(
        session, user_id="someone-else", run_id="lb-r1",
        title="x", expected_version=3) is None


def test_list_pagination_stable_and_total(session):
    nexus_run_service.ensure_table(session)
    for i in range(5):
        _record(session, f"lb-p-{i}", user="lb-page-user", session_id="lb-page")
    page1 = nexus_run_service.list_session_runs_page(
        session, user_id="lb-page-user", session_id="lb-page", limit=2)
    assert page1["total"] == 5
    assert [r["run_id"] for r in page1["items"]] == ["lb-p-4", "lb-p-3"]
    assert page1["next_cursor"]
    page2 = nexus_run_service.list_session_runs_page(
        session, user_id="lb-page-user", session_id="lb-page", limit=2,
        cursor=page1["next_cursor"])
    assert [r["run_id"] for r in page2["items"]] == ["lb-p-2", "lb-p-1"]
    page3 = nexus_run_service.list_session_runs_page(
        session, user_id="lb-page-user", session_id="lb-page", limit=2,
        cursor=page2["next_cursor"])
    assert [r["run_id"] for r in page3["items"]] == ["lb-p-0"]
    assert page3["next_cursor"] == ""
    # 非法 cursor 不炸，退回第一页。
    fallback = nexus_run_service.list_session_runs_page(
        session, user_id="lb-page-user", session_id="lb-page", limit=2, cursor="bogus")
    assert len(fallback["items"]) == 2


def test_run_detail_and_list_shape_via_http(
    client, session, nexus_student_token, student_user, runtime_configured
):
    """列表/详情新字段齐全；终态行不问 Worker（handler 必炸即失败）。"""
    uid = str(student_user.id)

    async def _must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("终态行不得触发 Worker 读取")

    terminal = nexus_run_service.record_run(
        session, run_id="lb-http-1", user_id=uid, session_id="lb-http",
        preset_id="nanogpt", job_id="job-lb-1", status="succeeded",
        preset_display_name="nanoGPT", proposal_id="pp-1", proposal_version=2,
        config_snapshot={"metric_policy": {"basis": "verified"}})
    assert terminal["display_title"] == "nanoGPT #1"
    with mock_runtime(_must_not_call):
        listing = client.get("/api/v1/nexus/runs?session_id=lb-http",
                             headers=_auth(nexus_student_token))
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] == 1
        item = body["items"][0]
        for key in ("display_title", "title", "run_number", "version",
                    "parent_run_id", "proposal_id", "proposal_version",
                    "config_snapshot", "status_source", "observed_at", "stale"):
            assert key in item, key
        assert item["status_source"] == "snapshot" and item["stale"] is False
        assert body["next_cursor"] == ""
        assert item["config_status"] == "frozen"
        detail = client.get("/api/v1/nexus/runs/lb-http-1",
                            headers=_auth(nexus_student_token))
        assert detail.status_code == 200
        assert detail.json()["config_snapshot"]["metric_policy"]["basis"] == "verified"


def test_config_status_marks_unknown_history(client, session, nexus_student_token):
    """无快照＋无 preset 的历史行标记 unavailable，不倒灌当前预设。"""
    from app.services import nexus_run_service

    nexus_run_service.ensure_table(session)
    # 直接插一行"远古"行（无快照、无 preset）：走 record_run 的最小字段。
    row = nexus_run_service.record_run(
        session, run_id="lb-ancient", user_id="lb-ancient-user", session_id="lb-ancient",
        preset_id="", job_id="job-ancient", status="succeeded")
    assert row["config_snapshot"] == {}
    from app.api.v1.endpoints.nexus_proxy import _merge_run_live

    assert _merge_run_live(row, None)["config_status"] == "unavailable"
    legacy = dict(row, preset_id="nanogpt")
    assert _merge_run_live(legacy, None)["config_status"] == "preset-defaults"


def test_rename_endpoint_statuses(client, session, nexus_student_token, student_user):
    uid = str(student_user.id)
    nexus_run_service.record_run(
        session, run_id="lb-ren-1", user_id=uid, session_id="lb-ren",
        preset_id="nanogpt", job_id="job-ren-1")
    ok = client.patch("/api/v1/nexus/runs/lb-ren-1",
                      json={"title": "命名实验", "expected_version": 1},
                      headers=_auth(nexus_student_token))
    assert ok.status_code == 200
    assert ok.json()["display_title"] == "命名实验"
    conflict = client.patch("/api/v1/nexus/runs/lb-ren-1",
                            json={"title": "再命名", "expected_version": 1},
                            headers=_auth(nexus_student_token))
    assert conflict.status_code == 409
    assert conflict.json()["data"]["error_code"] == "RUN_VERSION_CONFLICT"
    missing = client.patch("/api/v1/nexus/runs/lb-nope",
                           json={"title": "x", "expected_version": 1},
                           headers=_auth(nexus_student_token))
    assert missing.status_code == 404
    illegal = client.patch("/api/v1/nexus/runs/lb-ren-1",
                           json={"title": "x", "expected_version": 2, "status": "succeeded"},
                           headers=_auth(nexus_student_token))
    assert illegal.status_code == 422


def test_presets_proxy_returns_runtime_projection(
    client, nexus_student_token, student_user, runtime_configured
):
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["user"] = request.headers.get("X-Nexus-User-Id")
        return httpx.Response(200, json={"presets": [{
            "preset_id": "nanogpt", "display_name": "nanoGPT",
            "parameters": {"schema": {}, "defaults": {}}}]})
    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/repro/presets",
                              headers=_auth(nexus_student_token))
    assert response.status_code == 200
    assert seen["path"] == "/api/v1/nexus/repro/presets"
    assert seen["user"] == str(student_user.id)
    assert response.json()["presets"][0]["display_name"] == "nanoGPT"


# ---------------------------------------------------------------------------
# LB2：提案代理（透传＋本地 422）
# ---------------------------------------------------------------------------


def test_proposal_proxies_passthrough(
    client, nexus_student_token, student_user, runtime_configured
):
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method_path"] = f"{request.method} {request.url.path}"
        seen["user"] = request.headers.get("X-Nexus-User-Id")
        body = json.loads(request.content or b"{}")
        seen["body"] = body
        return httpx.Response(200, json={"proposal": {"proposal_id": "pp-9", "version": 1}})

    with mock_runtime(handler):
        created = client.post(
            "/api/v1/nexus/repro/proposals",
            json={"preset_id": "nanogpt", "session_id": "s9"},
            headers=_auth(nexus_student_token))
        assert created.status_code == 200
        assert seen["method_path"] == "POST /api/v1/nexus/repro/proposals"
        assert seen["user"] == str(student_user.id)
        detail = client.get("/api/v1/nexus/repro/proposals/pp-9",
                            headers=_auth(nexus_student_token))
        assert detail.status_code == 200
        assert seen["method_path"] == "GET /api/v1/nexus/repro/proposals/pp-9"
        patched = client.patch(
            "/api/v1/nexus/repro/proposals/pp-9",
            json={"expected_version": 1, "parameters": {"max_iters": 500}},
            headers=_auth(nexus_student_token))
        assert patched.status_code == 200
        assert seen["body"]["parameters"] == {"max_iters": 500}
        req = client.post(
            "/api/v1/nexus/repro/proposals/pp-9/request-approval",
            json={"expected_version": 1},
            headers=_auth(nexus_student_token))
        assert req.status_code == 200
        assert seen["method_path"].endswith("/request-approval")


def test_proposal_patch_rejects_undeclared_fields_offline(
    client, nexus_student_token, runtime_configured
):
    """非法字段由 Backend pydantic 先拦（422），不触达 Runtime。"""

    async def _must_not_call(request: httpx.Request) -> httpx.Response:
        raise AssertionError("非法字段不得透传上游")

    with mock_runtime(_must_not_call):
        response = client.patch(
            "/api/v1/nexus/repro/proposals/pp-9",
            json={"expected_version": 1, "steps": ["rm -rf /"]},
            headers=_auth(nexus_student_token))
    assert response.status_code == 422


def test_approvals_list_proxies_query(
    client, nexus_student_token, student_user, runtime_configured
):
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params)
        return httpx.Response(200, json={"items": []})

    with mock_runtime(handler):
        response = client.get("/api/v1/nexus/approvals?session_id=s9&status=pending",
                              headers=_auth(nexus_student_token))
    assert response.status_code == 200
    assert seen["query"] == {"session_id": "s9", "status": "pending"}
    assert response.json() == {"items": []}
