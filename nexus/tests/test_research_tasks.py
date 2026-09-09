"""F7 持续研究：Brief/任务/预算/补读/子任务/交付核对（平台护栏）。

行为契约（计划 §12）：
- Brief 保留分析维度与交付格式；解析/读过/理解三分，不把上传当读懂；
- 补读按块偏移分页，只返新证据，覆盖范围机械判定；
- 证据持久化来源版本＋内容 hash＋locator＋覆盖＋权限（PG 缺席即跳过，
  不阻断内存链路）；
- 受限 researcher 只读工具面；交办一次一个；预算/取消/终态即停；
- 交付看清单不看 Todo 全勾；实验是分支（仅自主 run 可关联）。
"""

import pytest

from nexus import research_state as state_module


@pytest.fixture(autouse=True)
def _clean():
    state_module.clear_memory_store()
    yield
    state_module.clear_memory_store()


def test_parse_dimensions_and_namespace():
    assert state_module.parse_dimensions("方法比较, 数据集 、 指标；   ") == [
        "方法比较", "数据集", "指标"]
    assert state_module.parse_dimensions("") == []
    assert state_module.task_namespace("rst-abc") == "rstask-rst-abc"


def test_create_task_brief_and_derived_questions():
    task = state_module.create_task(
        owner="u-f7", session_id="s-f7", objective="比较两篇论文的方法",
        dimensions="方法比较, 数据集", delivery_format="比较表＋综述")
    assert task["task_id"].startswith("rst-")
    assert task["brief"]["dimensions"] == ["方法比较", "数据集"]
    assert task["brief"]["delivery_format"] == "比较表＋综述"
    assert len(task["questions"]) == 2
    assert task["status"] == "open"
    assert task["namespace"] == f"rstask-{task['task_id']}"
    assert task["budget"] == {"max_rounds": 8, "max_subtasks": 8,
                              "max_evidence_calls": 24}


def test_create_task_rejects_empty_objective():
    with pytest.raises(state_module.ResearchError) as exc:
        state_module.create_task(owner="u-f7", session_id="s-f7", objective="  ")
    assert exc.value.code == "TASK_OBJECTIVE_EMPTY"


def test_budget_check_and_consume():
    task = state_module.create_task(
        owner="u-f7", session_id="s-f7", objective="x",
        budget={"max_rounds": 1, "max_subtasks": 1, "max_evidence_calls": 1})
    assert state_module.check_budget(task) == ""
    task = state_module.consume_budget(task["task_id"], "u-f7", "rounds")
    assert task["used"]["rounds"] == 1
    assert task["status"] == "running"
    assert state_module.check_budget(task) == "budget_exhausted:rounds"
    with pytest.raises(state_module.ResearchError) as exc:
        state_module.consume_budget(task["task_id"], "u-f7", "rounds")
    assert exc.value.code == "RESEARCH_BUDGET_EXHAUSTED"


def test_assign_next_question_atomic():
    task = state_module.create_task(
        owner="u-f7", session_id="s-f7", objective="x", dimensions="甲,乙",
        budget={"max_rounds": 1, "max_subtasks": 1, "max_evidence_calls": 5})
    first = state_module.assign_next_question(task["task_id"], "u-f7")
    assert first.get("stopped") is None
    assert first["question"]["id"] == "q1"
    assert first["task"]["used"] == {"rounds": 1, "subtasks": 1, "evidence_calls": 0}
    # 配额已满：第二次交办即停（不透支）。
    second = state_module.assign_next_question(task["task_id"], "u-f7")
    assert second["stopped"] == "budget_exhausted"
    assert second["task"]["status"] == "partial"


def test_assign_no_pending_and_cancel():
    task = state_module.create_task(owner="u-f7", session_id="s-f7", objective="x")
    assigned = state_module.assign_next_question(task["task_id"], "u-f7")
    assert assigned.get("stopped") is None
    # 该任务仅 1 个子问题且已交办 → 无待办。
    again = state_module.assign_next_question(task["task_id"], "u-f7")
    assert again["stopped"] == "no_pending"
    cancelled = state_module.request_cancel(task["task_id"], "u-f7")
    assert cancelled["status"] == "cancelled"
    third = state_module.assign_next_question(task["task_id"], "u-f7")
    assert third["stopped"] == "terminal"


def test_submit_finding_validates_evidence():
    from nexus import paper_evidence as evidence_module

    task = state_module.create_task(owner="u-f7", session_id="s-f7", objective="x")
    evidence = {"evidence_id": "ev-test0001", "attachment_id": "att-1",
                "source_title": "t", "locator": "p.2", "excerpt": "abc" * 10,
                "coverage": "fulltext_excerpt", "is_supplementary": True}
    evidence_module.get_registry().register("u-f7", "s-f7", [evidence])
    try:
        done = state_module.submit_finding(
            task_id=task["task_id"], owner="u-f7", question_id="q1",
            summary="方法 A 优于 B", evidence_ids=["ev-test0001"],
            gaps=["缺数据集版本"], conflicts=[])
        assert done["evidence_ids"] == ["ev-test0001"]
        assert done["gaps"] == ["缺数据集版本"]
        assert done["questions"][0]["status"] == "done"
        with pytest.raises(state_module.ResearchError) as exc:
            state_module.submit_finding(
                task_id=task["task_id"], owner="u-f7", question_id="q1",
                summary="伪造", evidence_ids=["ev-nope"])
        assert exc.value.code == "EVIDENCE_ID_INVALID"
        with pytest.raises(state_module.ResearchError) as exc2:
            state_module.submit_finding(
                task_id=task["task_id"], owner="attacker", question_id="q1",
                summary="越权", evidence_ids=[])
        assert exc2.value.code == "TASK_FORBIDDEN"
    finally:
        evidence_module.get_registry()._entries.pop("ev-test0001", None)
        evidence_module.get_registry()._order[:] = [
            eid for eid in evidence_module.get_registry()._order
            if eid != "ev-test0001"]


def test_link_experiment_only_autonomous():
    from nexus import experiment_runs as runs_module

    runs_module.clear_memory_store()
    try:
        task = state_module.create_task(owner="u-f7", session_id="s-f7", objective="x")
        run = runs_module.create_or_get_run(
            run_id="run-f7-link", owner="u-f7", session_id="s-f7",
            proposal_id="pp-1", proposal_version=1,
            scope_hash="h" * 16, approval_id="run-f7-link")
        linked = state_module.link_experiment(task["task_id"], "u-f7", run["run_id"])
        assert linked["experiment_run_ids"] == ["run-f7-link"]
        with pytest.raises(state_module.ResearchError) as exc:
            state_module.link_experiment(task["task_id"], "u-f7", "nope")
        assert exc.value.code == "RUN_NOT_FOUND"
    finally:
        runs_module.clear_memory_store()


def test_delivery_checklist_gates_completion():
    task = state_module.create_task(
        owner="u-f7", session_id="s-f7", objective="做实验比较 x",
        delivery_format="含实验的综述")
    items = {item["item"]: item for item in state_module.delivery_checklist(task)}
    assert items["has_evidence"]["met"] is False
    assert items["experiment_linked"]["met"] is False
    assert "experiment_linked" in items, "Brief 要求实验才检查关联"


def test_reading_offset_and_states():
    from nexus import research_reading as reading_module

    blocks = [{"text": f"块{i} 内容足够长 abcdefghij", "locator": f"p.{i}"}
              for i in range(5)]

    async def _fetch(_aid):
        return blocks, sum(len(block["text"]) for block in blocks), False

    import asyncio as _asyncio

    first = _asyncio.run(reading_module.read_more_blocks(
        attachment_id="att-1", offset=0, limit=2, fetch_blocks=_fetch))
    assert len(first["evidences"]) == 2
    assert first["next_offset"] == 2
    assert first["has_more"] is True
    assert first["reading_state"]["read_blocks"] == 2
    known = [evidence["evidence_id"] for evidence in first["evidences"]]
    second = _asyncio.run(reading_module.read_more_blocks(
        attachment_id="att-1", offset=0, limit=2, known_evidence_ids=known,
        fetch_blocks=_fetch))
    assert second["evidences"] == [], "已知 id 去重"
    tail = _asyncio.run(reading_module.read_more_blocks(
        attachment_id="att-1", offset=4, limit=6, fetch_blocks=_fetch))
    assert tail["has_more"] is False
    state = reading_module.describe_reading_state(
        attachment_total_chars=100, blocks_total=5, blocks_read=5)
    assert state["coverage"] == "abstract_only"
    assert "≠" in state["note"]


async def test_loop_tools_end_to_end():
    from nexus import paper_evidence as evidence_module
    from nexus.request_scope import (
        reset_execution_scope,
        reset_scope,
        set_execution_scope,
        set_scope,
    )
    from nexus import research_loop as loop_module

    state_module.clear_memory_store()
    tokens = set_scope("u-f7", None) + set_execution_scope("s-f7", None)
    try:
        planned = await loop_module.plan_research_task.ainvoke({
            "objective": "比较 A 与 B", "dimensions": "方法, 数据",
            "delivery_format": "综述"})
        assert planned["status"] == "success"
        task_id = planned["task"]["task_id"]
        assert len(planned["task"]["questions"]) == 2
        first = await loop_module.advance_research_task.ainvoke(
            {"task_id": task_id})
        assert first["status"] == "success"
        assert first["assignment"]["question_id"] == "q1"
        assert first["assignment"]["namespace"].startswith("rstask-")
        evidence = {"evidence_id": "ev-loop0001", "attachment_id": "att-1",
                    "source_title": "t", "locator": "p.1",
                    "excerpt": "xyz" * 10, "coverage": "fulltext_excerpt",
                    "is_supplementary": True}
        evidence_module.get_registry().register("u-f7", "s-f7", [evidence])
        try:
            submitted = await loop_module.submit_research_result.ainvoke({
                "task_id": task_id, "question_id": "q1",
                "summary": "A 更优", "evidence_ids": ["ev-loop0001"],
                "gaps": [], "conflicts": ["B 的数据口径疑似不一致"]})
            assert submitted["status"] == "success"
            assert submitted["task"]["conflicts"] == ["B 的数据口径疑似不一致"]
            # 交付核对：报告未登记＋q2 未做 → 未达项返回，不强制关闭。
            completed = await loop_module.complete_research_task.ainvoke(
                {"task_id": task_id})
            assert completed["status"] == "need_more_work"
            assert any(item["item"] == "synthesis_report"
                       for item in completed["unmet"])
            # 缺口保留下关闭 → partial。
            partial = await loop_module.complete_research_task.ainvoke(
                {"task_id": task_id, "close_as_partial": True})
            assert partial["closed"] == "partial"
            assert partial["task"]["status"] == "partial"
        finally:
            evidence_module.get_registry()._entries.pop("ev-loop0001", None)
            evidence_module.get_registry()._order[:] = [
                eid for eid in evidence_module.get_registry()._order
                if eid != "ev-loop0001"]
    finally:
        reset_scope(tokens[:2])
        reset_execution_scope(tokens[2:])
        state_module.clear_memory_store()


async def test_loop_cancel_and_foreign_rejected():
    from nexus.request_scope import (
        reset_execution_scope,
        reset_scope,
        set_execution_scope,
        set_scope,
    )
    from nexus import research_loop as loop_module

    state_module.clear_memory_store()
    tokens = set_scope("u-f7", None) + set_execution_scope("s-f7", None)
    try:
        planned = await loop_module.plan_research_task.ainvoke(
            {"objective": "x"})
        task_id = planned["task"]["task_id"]
        cancelled = await loop_module.cancel_research_task.ainvoke(
            {"task_id": task_id})
        assert cancelled["task"]["status"] == "cancelled"
        stopped = await loop_module.advance_research_task.ainvoke(
            {"task_id": task_id})
        assert stopped["reason"] in ("cancelled", "terminal")
        foreign = await loop_module.get_research_task.ainvoke(
            {"task_id": task_id})
        assert foreign["status"] == "success"
    finally:
        reset_scope(tokens[:2])
        reset_execution_scope(tokens[2:])
        state_module.clear_memory_store()
    other = set_scope("attacker", None) + set_execution_scope("s-x", None)
    try:
        denied = await loop_module.get_research_task.ainvoke({"task_id": task_id})
        assert denied["status"] == "error"
        assert denied["code"] == "TASK_NOT_FOUND"
    finally:
        reset_scope(other[:2])
        reset_execution_scope(other[2:])
        state_module.clear_memory_store()


def test_researcher_is_read_only_and_wired():
    from nexus import agent as agent_module

    decl = agent_module.build_researcher_subagent()
    assert decl["name"] == "researcher"
    names = {tool.name for tool in (decl["tools"] or [])}
    assert names == set(agent_module.RESEARCHER_TOOL_NAMES)
    assert names.isdisjoint({"run_reproduction", "write_research_report",
                             "write_artifact", "create_reproduction_proposal",
                             "request_reproduction_approval", "execute", "task"})
    # 全局收敛不动：task 仍在 openai 键排除集中，research 独立键放行。
    assert "task" in agent_module.NEXUS_EXCLUDED_TOOLS
    from deepagents.profiles.harness.harness_profiles import _HARNESS_PROFILES

    agent_module._register_tool_surface_profile()
    assert "task" not in _HARNESS_PROFILES["nexus-research"].excluded_tools
    assert "execute" in _HARNESS_PROFILES["nexus-research"].excluded_tools


async def test_research_http_endpoints(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from nexus.main import app

    state_module.clear_memory_store()
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    user = {"X-Nexus-User-Id": "u-http"}
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as client:
        created = await client.post(
            "/api/v1/nexus/research-tasks",
            json={"objective": "比较 A 与 B", "dimensions": "方法"},
            headers=user)
        assert created.status_code == 200, created.text
        task_id = created.json()["task"]["task_id"]
        assert created.json()["task"]["namespace"].startswith("rstask-")
        listed = await client.get("/api/v1/nexus/research-tasks", headers=user)
        assert any(item["task_id"] == task_id
                   for item in listed.json()["tasks"])
        queried = await client.get(
            f"/api/v1/nexus/research-tasks/{task_id}", headers=user)
        assert queried.status_code == 200
        assert queried.json()["task"]["checklist"]
        cross = await client.get(
            f"/api/v1/nexus/research-tasks/{task_id}",
            headers={"X-Nexus-User-Id": "attacker"})
        assert cross.status_code == 404
        bad = await client.post("/api/v1/nexus/research-tasks",
                                json={"objective": "  "}, headers=user)
        assert bad.status_code == 400
        cancelled = await client.post(
            f"/api/v1/nexus/research-tasks/{task_id}/cancel", headers=user)
        assert cancelled.json()["task"]["status"] == "cancelled"
    state_module.clear_memory_store()
