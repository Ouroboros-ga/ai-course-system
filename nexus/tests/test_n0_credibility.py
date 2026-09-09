"""N0 可信度收尾回归：P1-A/B/C ＋ R1/R2/R3/H2（审查合成复现转常驻测试）。

全部离线合成：内存审批/提案存储、MockTransport/替身 I/O、脚本化假模型；
零真实 Worker/付费 LLM。验收映射见 ABCD 审查 §1 与 H1/R1a 质量审查。
"""

from __future__ import annotations

import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

import nexus.main as main_module
from nexus import approvals, proposals
from nexus.config import get_settings
from nexus.main import app
from nexus.paper_evidence import get_registry
from nexus.request_scope import (
    reset_execution_scope,
    reset_scope,
    set_execution_scope,
    set_scope,
)
import nexus.tools.paper_research as pr
import nexus.tools.reproduction as repro_module
from nexus.tools.reproduction import REPRO_PRESETS


@pytest.fixture(autouse=True)
def _clean():
    proposals.clear_memory_store()
    approvals.clear_memory_store()
    yield
    proposals.clear_memory_store()
    approvals.clear_memory_store()
    main_module._active_threads.clear()
    main_module._request_registry.clear()
    main_module._registry_order.clear()
    get_registry()._entries.clear()
    get_registry()._order.clear()


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NEXUS_API_KEY", "")
    get_settings.cache_clear()
    original_agents = main_module._agents
    yield main_module
    main_module._agents = original_agents
    get_settings.cache_clear()


def _install(agent) -> None:
    main_module._agents = {
        ("research", "deepseek-chat"): agent,
        ("general", "deepseek-chat"): agent,
    }
    main_module._pg_saver = None


def _scope(user="7", session="s1"):
    a = set_scope(user, None)
    b = set_execution_scope(session, None)
    return a, b


def _unscope(tokens):
    reset_scope(tokens[0])
    reset_execution_scope(tokens[1])


def _make_request_response(monkeypatch, calls: dict):
    """拦截 Runtime 出站 Backend 内部 HTTP，捕获 POST 体（沿用 test_proposals 模式）。"""
    real_client = httpx.AsyncClient

    class _Resp:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def factory(**kwargs):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                calls["url"] = url
                calls["body"] = json
                return _Resp({"code": 200, "data": {"run_id": "run-x"}})

            async def get(self, url, headers=None, params=None):
                return _Resp({"code": 200, "data": {}})

        return _Client()

    monkeypatch.setattr(repro_module.httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------------
# P1-A：核销冻结快照；核销后修改锁拒绝；登记/提交只消费冻结体
# ---------------------------------------------------------------------------


async def test_consume_locks_proposal_and_linkage_uses_frozen_snapshot(monkeypatch):
    tokens = _scope()
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    get_settings.cache_clear()
    calls: dict = {}
    try:
        row = proposals.create_proposal(
            user_id="7", session_id="s1", preset=REPRO_PRESETS["nanogpt"],
            parameters={"max_iters": 100})
        req = proposals.request_approval_for_proposal(
            row["proposal_id"], user_id="7", expected_version=1)
        apv = req["approval"]["approval_id"]
        approvals.decide_approval(apv, "7", "approved")

        captured: dict = {}

        async def fake_submit(effective):
            captured["steps"] = list(effective["steps"])
            # 核销后、提交返回前的修改：必须被锁拒绝（旧批准自然失效语义保留）。
            with pytest.raises(proposals.ProposalError) as exc:
                proposals.patch_proposal(
                    row["proposal_id"], user_id="7", expected_version=1,
                    parameters={"max_iters": 2000})
            assert exc.value.code == "PROPOSAL_LOCKED"
            return {"status": "submitted", "job": {"job_id": "job-frozen"}}

        monkeypatch.setattr(repro_module, "_submit_to_worker", fake_submit)

        async def fake_ownership(job_id, preset, user_id=None):
            return True

        monkeypatch.setattr(repro_module, "_record_job_ownership", fake_ownership)
        _make_request_response(monkeypatch, calls)

        result = await repro_module.execute_approved_reproduction(
            approval_id=apv, user_id="7", session_id="s1", preset_id="nanogpt")
        assert result["status"] == "submitted"
        # 提交载荷用冻结步骤（v1 max_iters=100，非现行值）。
        assert "--max_iters=100" in captured["steps"][3]
        snap = calls["body"]["config_snapshot"]
        assert snap["proposal_version"] == 1
        assert snap["parameters"]["max_iters"] == 100
        assert "--max_iters=100" in snap["steps"][3]
        assert "--lr_decay_iters=101" in snap["steps"][3]
        assert snap["metric_policy"]["basis"] == "exploratory"
        # 执行成功后提案 approved→executed（后续修改须走新提案）。
        assert proposals.get_proposal(row["proposal_id"])["status"] == "executed"
    finally:
        _unscope(tokens)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# P1-B：linkage 不可读 ≠ 无 linkage；前者无比较结论且不回写
# ---------------------------------------------------------------------------

_JOB_PASS_LIKE = {
    "job_id": "job-metric", "preset_id": "nanogpt", "status": "succeeded",
    "requested_license": "MIT",
    "license_checks": {"github_spdx": "MIT", "local_spdx": "MIT", "local_evidence": "LICENSE",
                       "effective": "MIT", "allowed": True, "reason": ""},
    "seed_used": True,
    "steps_result": [
        {"command": "python train.py ...", "exit_code": 0, "timed_out": False,
         "duration_s": 10, "log_tail": "step 500: train loss 2.1, val loss 1.91"},
    ],
}


def _fake_artifact(monkeypatch, written: list):
    import nexus.artifact_client as artifact_client

    async def fake_write(*, artifact_type, title, content, user_id, run_id=""):
        written.append((artifact_type, title, run_id))
        return {"status": "success",
                "artifact": {"artifact_id": f"art-{len(written)}",
                             "artifact_type": artifact_type, "title": title,
                             "size_bytes": len(content)}}

    monkeypatch.setattr(artifact_client, "write_artifact_via_backend", fake_write)


async def test_report_linkage_unreadable_is_incomplete_without_writeback(monkeypatch, fake_env):
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    async def fake_job(job_id):
        return dict(_JOB_PASS_LIKE)

    async def fake_linkage(job_id, user_id):
        return None, "unavailable"

    writebacks: list = []

    async def fake_writeback(job_id, verdict, summary):
        writebacks.append((job_id, verdict))

    monkeypatch.setattr(main_module, "_fetch_repro_job", fake_job)
    monkeypatch.setattr(main_module, "_fetch_run_linkage", fake_linkage)
    monkeypatch.setattr(main_module, "_writeback_metric_verdict", fake_writeback)
    written: list = []
    _fake_artifact(monkeypatch, written)

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/repro/jobs/job-metric/report",
            headers={"X-Nexus-User-Id": "7"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "INCOMPLETE", body
    assert "不可读" in body.get("metric_note", ""), body
    assert body["comparison"] == []
    assert writebacks == [], "不可读配置不得回写任何判定"
    assert len(written) == 2, "报告产物照常生成"


async def test_report_linkage_missing_keeps_legacy_verdict(monkeypatch, fake_env):
    """明确无 linkage（老直批作业）→ legacy verified 判定保持不变。"""
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)

    async def fake_job(job_id):
        return dict(_JOB_PASS_LIKE)

    async def fake_linkage(job_id, user_id):
        return None, "not_found"

    writebacks: list = []

    async def fake_writeback(job_id, verdict, summary):
        writebacks.append((job_id, verdict))

    monkeypatch.setattr(main_module, "_fetch_repro_job", fake_job)
    monkeypatch.setattr(main_module, "_fetch_run_linkage", fake_linkage)
    monkeypatch.setattr(main_module, "_writeback_metric_verdict", fake_writeback)
    written: list = []
    _fake_artifact(monkeypatch, written)

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/repro/jobs/job-metric/report",
            headers={"X-Nexus-User-Id": "7"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["verdict"] == "PASS"
    assert writebacks == [("job-metric", "PASS")]


# ---------------------------------------------------------------------------
# P1-C：同步聊天异常释放锁；失败请求可重试，不永久 409
# ---------------------------------------------------------------------------


class _Boom(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "nexus-boom"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("synthetic model failure")


class _Ok(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "nexus-ok"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="好的"))])


def _graph_with(model):
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=model, tools=[], system_prompt="t",
        middleware=[], checkpointer=InMemorySaver(),
    )


async def test_sync_chat_exception_releases_lock_and_allows_retry(fake_env):
    _install(_graph_with(_Boom()))
    thread = None
    # raise_app_exceptions=False：服务端 500 以响应返回，不断言传输层抛错。
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport,
                           base_url="http://test") as client:
        first = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "hi", "session_id": "p1c", "mode": "research",
                  "client_request_id": "boom-1"},
            headers={"X-Nexus-User-Id": "7"},
        )
        assert first.status_code == 500
        from nexus.persistence import thread_for

        thread = thread_for("p1c", "7")
        assert thread not in main_module._active_threads, "异常必须释放写者"
        # 失败请求不毒化注册表：同键可重新执行（不是永久 409，也不是空回放）。
        _install(_graph_with(_Ok()))
        retry = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "hi", "session_id": "p1c", "mode": "research",
                  "client_request_id": "boom-1"},
            headers={"X-Nexus-User-Id": "7"},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["message"] == "好的"
        assert "deduped" not in retry.json()
        # 不同键更不受影响。
        fresh = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "hi", "session_id": "p1c", "mode": "research",
                  "client_request_id": "boom-2"},
            headers={"X-Nexus-User-Id": "7"},
        )
        assert fresh.status_code == 200


# ---------------------------------------------------------------------------
# R1：正文引用编号必须映射到已解析证据
# ---------------------------------------------------------------------------


def _research_tokens(user="42", session="sess-r1", aids=("att01",)):
    a = set_scope(user, None)
    b = set_execution_scope(session, None)
    return a, b


def _register_evidence(eid, aid="att01", locator="p2"):
    get_registry().register("42", "sess-r1", [{
        "evidence_id": eid, "attachment_id": aid, "source_title": "方法A.pdf",
        "source_kind": "upload_label", "locator": locator,
        "excerpt": "方法A在数据集X上达到SOTA。", "coverage": "fulltext_excerpt",
        "is_supplementary": True,
    }])


async def test_report_rejects_unmapped_citation_numbers(monkeypatch):
    tokens = _research_tokens()
    get_registry()._entries.clear()
    _register_evidence("ev-ok1")

    import nexus.artifact_client as artifact_client

    async def must_not_write(**kwargs):
        raise AssertionError("非法引用不得触达产物写入")

    monkeypatch.setattr(artifact_client, "write_artifact_via_backend", must_not_write)
    try:
        bad = await pr.write_research_report.coroutine(
            title="t", question="q", body_markdown="结论 [999]。",
            cited_evidence_ids=["ev-ok1"],
        )
        assert bad["status"] == "rejected"
        assert bad["code"] == "CITATION_NUMBER_INVALID"
        assert "999" in bad["detail"]
        empty = await pr.write_research_report.coroutine(
            title="t", question="q", body_markdown="纯文字，没有任何引用标记。",
            cited_evidence_ids=["ev-ok1"],
        )
        assert empty["status"] == "rejected"
        assert empty["code"] == "CITATION_BODY_MISSING"
    finally:
        reset_scope(tokens[0])
        reset_execution_scope(tokens[1])


# ---------------------------------------------------------------------------
# R2：报告写入前重验附件可用性（撤销/过期/改绑后旧证据不可用）
# ---------------------------------------------------------------------------


async def test_report_rechecks_attachment_availability(monkeypatch):
    tokens = _research_tokens()
    get_registry()._entries.clear()
    _register_evidence("ev-gone", aid="att-gone")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://backend.test")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    get_settings.cache_clear()

    import httpx as _httpx

    real_client = _httpx.AsyncClient

    def factory(**kwargs):
        async def responder(request):
            return _httpx.Response(404, json={"detail": "ATTACHMENT_NOT_FOUND"})

        kwargs["transport"] = _httpx.MockTransport(responder)
        return real_client(**kwargs)

    monkeypatch.setattr(pr.httpx, "AsyncClient", factory)

    import nexus.artifact_client as artifact_client

    async def must_not_write(**kwargs):
        raise AssertionError("撤销证据不得触达产物写入")

    monkeypatch.setattr(artifact_client, "write_artifact_via_backend", must_not_write)
    try:
        result = await pr.write_research_report.coroutine(
            title="t", question="q", body_markdown="结论 [1]。",
            cited_evidence_ids=["ev-gone"],
        )
        assert result["status"] == "rejected"
        assert result["code"] == "EVIDENCE_SOURCE_REVOKED"
        assert "att-gone" in result["detail"]
    finally:
        reset_scope(tokens[0])
        reset_execution_scope(tokens[1])
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# R3：问题参与证据选择＋块级截断如实标记
# ---------------------------------------------------------------------------


async def test_question_ranking_surfaces_late_blocks(monkeypatch):
    tokens = _research_tokens()
    get_registry()._entries.clear()
    get_registry()._order.clear()
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://backend.test")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    get_settings.cache_clear()

    import httpx as _httpx

    blocks = [
        {"text": "本文介绍背景与动机。", "locator": "p1"},
        {"text": "相关工作综述。", "locator": "p2"},
        {"text": "核心结果：METHOD_RESULT_Z=42，详见实验表。", "locator": "p9"},
    ]
    payload = {"attachment_id": "att01", "filename": "论文.pdf", "kind": "pdf",
               "status": "ready", "blocks": blocks, "truncated": False,
               "total_blocks": 3}
    real_client = _httpx.AsyncClient

    def factory(**kwargs):
        async def responder(request):
            return _httpx.Response(
                200, json={"code": 200, "message": "ok", "data": payload})

        kwargs["transport"] = _httpx.MockTransport(responder)
        return real_client(**kwargs)

    monkeypatch.setattr(pr.httpx, "AsyncClient", factory)
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="METHOD_RESULT_Z 是多少", attachment_ids=["att01"])
    finally:
        reset_scope(tokens[0])
        reset_execution_scope(tokens[1])
        get_settings.cache_clear()
    assert result["status"] == "success", result
    excerpts = " ".join(e["excerpt"] for e in result["evidences"])
    assert "METHOD_RESULT_Z=42" in excerpts, "问题相关块必须被选中，不只取前部"
    assert result["evidences"][0]["locator"] == "p9", "相关块排在前面"


async def test_evidence_marks_block_truncation(monkeypatch):
    tokens = _research_tokens()
    get_registry()._entries.clear()
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_URL", "http://backend.test")
    monkeypatch.setenv("NEXUS_BACKEND_INTERNAL_TOKEN", "tok")
    get_settings.cache_clear()

    import httpx as _httpx

    long_text = "y" * 2000
    payload = {"attachment_id": "att01", "filename": "论文.pdf", "kind": "pdf",
               "status": "ready",
               "blocks": [{"text": long_text, "locator": "p4"},
                          {"text": "短块。", "locator": "p5"}],
               "truncated": False, "total_blocks": 2}
    real_client = _httpx.AsyncClient

    def factory(**kwargs):
        async def responder(request):
            return _httpx.Response(
                200, json={"code": 200, "message": "ok", "data": payload})

        kwargs["transport"] = _httpx.MockTransport(responder)
        return real_client(**kwargs)

    monkeypatch.setattr(pr.httpx, "AsyncClient", factory)
    try:
        result = await pr.collect_paper_evidence.coroutine(
            question="q", attachment_ids=["att01"])
    finally:
        reset_scope(tokens[0])
        reset_execution_scope(tokens[1])
        get_settings.cache_clear()
    assert result["status"] == "success", result
    by_locator = {e["locator"]: e for e in result["evidences"]}
    assert by_locator["p4"]["truncated"] is True, "超长块截断必须标记"
    assert by_locator["p5"]["truncated"] is False


# ---------------------------------------------------------------------------
# H2：checkpoint 读取失败是明确错误，不是"无计划"
# ---------------------------------------------------------------------------


async def test_plan_read_failure_is_explicit_error(fake_env):
    class _NoState:
        async def aget_state(self, config):  # noqa: ANN001, ANN003
            raise RuntimeError("checkpoint unavailable")

    _install(_NoState())
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        response = await client.get(
            "/api/v1/nexus/plan/s-h2", headers={"X-Nexus-User-Id": "7"})
    assert response.status_code == 503, response.text
    assert "CHECKPOINT_READ_FAILED" in response.text
