"""批次4：TeachingAgent 可选工具端口契约测试。

覆盖：
1. WebResearchPort（CallableWebResearchPort）
   - 始终标记 is_supplementary=True
   - 始终标记 cannot_modify_mastery/recommendation/graph=True
   - callable 返回非 Mapping 时降级为 invalid_result_shape
   - 集成进 workflow 后未注入时节点跳过、注入时产出 web_research_results
2. CognitionPort（CallableCognitionPort）
   - get_state / get_recommendation 透传 callable 结果
   - 未注入时 workflow 节点跳过
   - 注入时 workflow 写入 cognitive_state / cognitive_recommendation
3. QuestionBankPort（CallableQuestionBankPort）
   - list_questions 透传 callable 结果
   - 未注入时 workflow 节点跳过
   - 注入时 workflow 写入 question_bank_items
4. fail-closed 原则：端口抛异常时 workflow 标记 degraded_services 且不中断

这些测试不连接数据库或网络；全部使用内存 fake。
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping

from app.platform.agents.contracts import TeachingTools
from app.platform.agents.runtime import TeachingAgentRuntime
from app.platform.agents.tools.cognition import CallableCognitionPort
from app.platform.agents.tools.fakes import (
    FakeEvents,
    FakeGraph,
    FakeLLM,
    FakeRecommendation,
    FakeRetrieval,
    FakeSandbox,
    FakeScope,
    FakeStudentModeling,
)
from app.platform.agents.tools.question_bank import CallableQuestionBankPort
from app.platform.agents.tools.web_research import CallableWebResearchPort


# ==================== WebResearchPort 契约测试 ====================


def _fake_llm_default() -> FakeLLM:
    return FakeLLM()


def _run(runtime: TeachingAgentRuntime, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "student_id": "s-1",
        "course_id": "c-1",
        "session_id": "session-1",
        "message": "为什么二分查找需要更新边界？",
    }
    payload.update(overrides)
    return asyncio.run(runtime.respond(**payload))


def test_web_research_port_always_marks_supplementary_contract():
    """WebResearch 返回必须始终标记 is_supplementary=True 和三个 cannot_modify 标记。

    即使底层 callable 返回的 dict 没有这些字段，port 也必须强制注入。
    """
    async def _research(**_: Any) -> Mapping[str, Any]:
        return {"results": [{"url": "https://example.com", "snippet": "x"}]}

    port = CallableWebResearchPort(_research)
    result = asyncio.run(port.research(course_id="c-1", query="测试"))
    assert result["is_supplementary"] is True
    assert result["cannot_modify_mastery"] is True
    assert result["cannot_modify_recommendation"] is True
    assert result["cannot_modify_graph"] is True
    # 原始字段保留
    assert result["results"][0]["url"] == "https://example.com"


def test_web_research_port_preserves_callable_marker_when_already_present():
    """callable 已经返回 supplementary 标记时仍由 port 强制覆盖（幂等）。"""
    async def _research(**_: Any) -> Mapping[str, Any]:
        return {
            "results": [],
            "is_supplementary": False,  # 故意错误，port 必须覆盖
            "cannot_modify_mastery": False,
        }

    port = CallableWebResearchPort(_research)
    result = asyncio.run(port.research(course_id="c-1", query="测试"))
    assert result["is_supplementary"] is True
    assert result["cannot_modify_mastery"] is True
    assert result["cannot_modify_recommendation"] is True
    assert result["cannot_modify_graph"] is True


def test_web_research_port_degrades_on_non_mapping_result():
    """callable 返回非 Mapping 时，port 返回 invalid_result_shape 占位结果。

    仍必须包含 supplementary 与 cannot_modify 标记，确保下游不会写入。
    """
    async def _research(**_: Any) -> Any:
        return ["not", "a", "mapping"]

    port = CallableWebResearchPort(_research)
    result = asyncio.run(port.research(course_id="c-1", query="测试"))
    assert result["status"] == "invalid_result_shape"
    assert result["results"] == []
    assert result["is_supplementary"] is True
    assert result["cannot_modify_mastery"] is True
    assert result["cannot_modify_recommendation"] is True
    assert result["cannot_modify_graph"] is True


def test_web_research_port_propagates_callable_exception_to_caller():
    """callable 抛异常时 port 不吞错（由 workflow 节点 fail-closed 处理）。"""
    async def _research(**_: Any) -> Mapping[str, Any]:
        raise RuntimeError("upstream down")

    port = CallableWebResearchPort(_research)
    raised = False
    try:
        asyncio.run(port.research(course_id="c-1", query="测试"))
    except RuntimeError:
        raised = True
    assert raised


def test_web_research_node_skipped_when_port_not_injected():
    """未注入 WebResearchPort 时，workflow 节点 skipped=True，不写入 web_research_results。"""
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        # web_research 不注入
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert state.get("web_research_results") is None
    # research_web 节点应出现在 trace 中且标记 skipped
    research_nodes = [t for t in state["trace"] if t.get("node") == "research_web"]
    assert len(research_nodes) == 1
    assert research_nodes[0].get("skipped") is True


def test_web_research_node_writes_results_when_port_injected():
    """注入 WebResearchPort 后，workflow 写入 web_research_results 并标记 available。"""
    async def _research(**_: Any) -> Mapping[str, Any]:
        return {"results": [{"url": "https://example.com/x", "snippet": "边界更新"}]}

    web_port = CallableWebResearchPort(_research)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        web_research=web_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert state.get("web_research_results") is not None
    assert state["web_research_results"]["is_supplementary"] is True
    assert state["web_research_results"]["results"][0]["url"] == "https://example.com/x"
    research_nodes = [t for t in state["trace"] if t.get("node") == "research_web"]
    assert len(research_nodes) == 1
    assert research_nodes[0].get("available") is True


def test_web_research_node_degrades_when_port_raises():
    """注入的 WebResearchPort 抛异常时，节点标记 degraded_services 且不中断流程。"""

    async def _research(**_: Any) -> Mapping[str, Any]:
        raise TimeoutError("upstream timeout")

    web_port = CallableWebResearchPort(_research)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        web_research=web_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    # 不中断：仍能产出 final_answer
    assert state.get("final_answer")
    # 标记降级
    assert "web_research" in state["degraded_services"]
    assert state.get("web_research_results") is None
    research_nodes = [t for t in state["trace"] if t.get("node") == "research_web"]
    assert len(research_nodes) == 1
    assert research_nodes[0].get("error") == "TimeoutError"


# ==================== CognitionPort 契约测试 ====================


def test_cognition_port_passes_through_state_and_recommendation():
    """CallableCognitionPort 透传 get_state / get_recommendation callable 的结果。"""
    async def _get_state(**kwargs: Any) -> Mapping[str, Any]:
        return {
            "student_id": kwargs["student_id"],
            "course_id": kwargs["course_id"],
            "node_id": kwargs.get("node_id"),
            "observed_performance_score": 0.4,
            "evidence_confidence": 0.8,
        }

    async def _get_recommendation(**kwargs: Any) -> Mapping[str, Any]:
        return {
            "recommendation_id": "rec-1",
            "recommendation_type": "practice_quiz",
            "priority": "high",
        }

    port = CallableCognitionPort(_get_state, _get_recommendation)
    state = asyncio.run(port.get_state(student_id="s-1", course_id="c-1", node_id="k-1"))
    rec = asyncio.run(port.get_recommendation(student_id="s-1", course_id="c-1", node_id="k-1"))
    assert state["observed_performance_score"] == 0.4
    assert state["node_id"] == "k-1"
    assert rec["recommendation_id"] == "rec-1"
    assert rec["priority"] == "high"


def test_cognition_port_returns_none_when_callable_returns_none():
    """callable 返回 None 时 port 透传 None（数据缺失不伪造）。"""
    async def _get_state(**_: Any) -> None:
        return None

    async def _get_recommendation(**_: Any) -> None:
        return None

    port = CallableCognitionPort(_get_state, _get_recommendation)
    assert asyncio.run(port.get_state(student_id="s-1", course_id="c-1")) is None
    assert asyncio.run(port.get_recommendation(student_id="s-1", course_id="c-1")) is None


def test_cognition_node_skipped_when_port_not_injected():
    """未注入 CognitionPort 时，workflow 节点 skipped=True。"""
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    nodes = [t for t in state["trace"] if t.get("node") == "load_cognitive_state"]
    assert len(nodes) == 1
    assert nodes[0].get("skipped") is True
    # 未写入认知字段
    assert state.get("cognitive_state") is None
    assert state.get("cognitive_recommendation") is None


def test_cognition_node_writes_state_when_port_injected():
    """注入 CognitionPort 后，workflow 写入 cognitive_state / cognitive_recommendation。"""
    async def _get_state(**_: Any) -> Mapping[str, Any]:
        return {"observed_performance_score": 0.3, "mastery_level": "low"}

    async def _get_recommendation(**_: Any) -> Mapping[str, Any]:
        return {"recommendation_id": "rec-x", "priority": "high"}

    cog_port = CallableCognitionPort(_get_state, _get_recommendation)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        cognition=cog_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert state.get("cognitive_state") is not None
    assert state["cognitive_state"]["observed_performance_score"] == 0.3
    assert state["cognitive_state"]["mastery_level"] == "low"
    assert state.get("cognitive_recommendation") is not None
    assert state["cognitive_recommendation"]["recommendation_id"] == "rec-x"
    nodes = [t for t in state["trace"] if t.get("node") == "load_cognitive_state"]
    assert len(nodes) == 1
    assert nodes[0].get("available") is True


def test_cognition_node_degrades_when_port_raises():
    """CognitionPort 抛异常时，节点标记 degraded_services，workflow 继续运行。"""

    async def _get_state(**_: Any) -> Mapping[str, Any]:
        raise RuntimeError("cognition down")

    async def _get_recommendation(**_: Any) -> Mapping[str, Any]:
        raise RuntimeError("cognition down")

    cog_port = CallableCognitionPort(_get_state, _get_recommendation)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        cognition=cog_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert "cognition" in state["degraded_services"]
    assert state.get("final_answer")
    nodes = [t for t in state["trace"] if t.get("node") == "load_cognitive_state"]
    assert len(nodes) == 1
    assert nodes[0].get("error") == "RuntimeError"


# ==================== QuestionBankPort 契约测试 ====================


def test_question_bank_port_passes_through_questions():
    """CallableQuestionBankPort 透传 list_questions callable 的结果。"""
    async def _list(**kwargs: Any) -> list[Mapping[str, Any]]:
        return [
            {"question_id": 1, "question_text": "Q1", "course_id": kwargs["course_id"]},
            {"question_id": 2, "question_text": "Q2", "course_id": kwargs["course_id"]},
        ]

    port = CallableQuestionBankPort(_list)
    items = asyncio.run(port.list_questions(course_id="c-1", limit=5))
    assert len(items) == 2
    assert items[0]["question_id"] == 1
    assert items[1]["question_text"] == "Q2"


def test_question_bank_port_returns_empty_list_when_callable_returns_empty():
    """callable 返回空列表时 port 透传空列表（不伪造题目）。"""
    async def _list(**_: Any) -> list[Mapping[str, Any]]:
        return []

    port = CallableQuestionBankPort(_list)
    items = asyncio.run(port.list_questions(course_id="c-1"))
    assert items == []


def test_question_bank_node_skipped_when_port_not_injected():
    """未注入 QuestionBankPort 时，workflow 节点 skipped=True。"""
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    nodes = [t for t in state["trace"] if t.get("node") == "load_question_bank"]
    assert len(nodes) == 1
    assert nodes[0].get("skipped") is True
    assert state.get("question_bank_items") in (None, [])


def test_question_bank_node_writes_items_when_port_injected():
    """注入 QuestionBankPort 后，workflow 写入 question_bank_items。"""
    async def _list(**_: Any) -> list[Mapping[str, Any]]:
        return [{"question_id": 42, "question_text": "什么是二分查找？"}]

    qb_port = CallableQuestionBankPort(_list)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        question_bank=qb_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert state.get("question_bank_items")
    assert state["question_bank_items"][0]["question_id"] == 42
    nodes = [t for t in state["trace"] if t.get("node") == "load_question_bank"]
    assert len(nodes) == 1
    assert nodes[0].get("count") == 1


def test_question_bank_node_degrades_when_port_raises():
    """QuestionBankPort 抛异常时，节点标记 degraded_services，workflow 继续运行。"""

    async def _list(**_: Any) -> list[Mapping[str, Any]]:
        raise RuntimeError("qb down")

    qb_port = CallableQuestionBankPort(_list)
    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        question_bank=qb_port,
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    assert "question_bank" in state["degraded_services"]
    assert state.get("question_bank_items") == []
    assert state.get("final_answer")
    nodes = [t for t in state["trace"] if t.get("node") == "load_question_bank"]
    assert len(nodes) == 1
    assert nodes[0].get("error") == "RuntimeError"


# ==================== 三端口同时注入的集成契约测试 ====================


def test_all_three_optional_ports_injected_together():
    """三个可选端口同时注入时，workflow 串行执行所有可选节点，不互相干扰。"""
    async def _research(**_: Any) -> Mapping[str, Any]:
        return {"results": [{"url": "https://x.example"}]}

    async def _get_state(**_: Any) -> Mapping[str, Any]:
        return {"observed_performance_score": 0.55}

    async def _get_rec(**_: Any) -> Mapping[str, Any]:
        return {"recommendation_id": "r-all"}

    async def _list(**_: Any) -> list[Mapping[str, Any]]:
        return [{"question_id": 7}]

    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        web_research=CallableWebResearchPort(_research),
        cognition=CallableCognitionPort(_get_state, _get_rec),
        question_bank=CallableQuestionBankPort(_list),
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    # 三个节点都产出结果
    assert state.get("web_research_results") is not None
    assert state["web_research_results"]["is_supplementary"] is True
    assert state.get("cognitive_state") is not None
    assert state["cognitive_state"]["observed_performance_score"] == 0.55
    assert state.get("cognitive_recommendation") is not None
    assert state["cognitive_recommendation"]["recommendation_id"] == "r-all"
    assert state.get("question_bank_items")
    assert state["question_bank_items"][0]["question_id"] == 7
    # 没有降级标记
    assert "web_research" not in state["degraded_services"]
    assert "cognition" not in state["degraded_services"]
    assert "question_bank" not in state["degraded_services"]
    # 最终答复仍正常
    assert state.get("final_answer")


def test_workflow_node_order_with_all_optional_ports_injected():
    """三个可选节点在 workflow 中的执行顺序应符合批次4设计：

    load_student_state -> load_cognitive_state -> load_graph_context
    -> load_question_bank -> retrieve_evidence -> research_web
    -> load_sandbox_context -> decide_teaching_action
    """
    async def _research(**_: Any) -> Mapping[str, Any]:
        return {"results": []}

    async def _get_state(**_: Any) -> Mapping[str, Any]:
        return {"observed_performance_score": 0.55}

    async def _get_rec(**_: Any) -> Mapping[str, Any]:
        return {"recommendation_id": "r"}

    async def _list(**_: Any) -> list[Mapping[str, Any]]:
        return []

    tools = TeachingTools(
        scope=FakeScope(),
        knowledge_graph=FakeGraph(),
        retrieval=FakeRetrieval(),
        student_modeling=FakeStudentModeling(),
        recommendation=FakeRecommendation(),
        sandbox=FakeSandbox(),
        learning_events=FakeEvents(),
        llm=_fake_llm_default(),
        web_research=CallableWebResearchPort(_research),
        cognition=CallableCognitionPort(_get_state, _get_rec),
        question_bank=CallableQuestionBankPort(_list),
    )
    runtime = TeachingAgentRuntime(tools)
    state = _run(runtime)
    node_names = [t.get("node") for t in state["trace"]]
    # 关键顺序断言
    assert node_names.index("load_student_state") < node_names.index("load_cognitive_state")
    assert node_names.index("load_cognitive_state") < node_names.index("load_graph_context")
    assert node_names.index("load_graph_context") < node_names.index("load_question_bank")
    assert node_names.index("load_question_bank") < node_names.index("retrieve_course_evidence")
    assert node_names.index("retrieve_course_evidence") < node_names.index("research_web")
    assert node_names.index("research_web") < node_names.index("load_sandbox_context")
    assert node_names.index("load_sandbox_context") < node_names.index("decide_teaching_action")
