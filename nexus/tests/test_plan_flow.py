"""NX-H1 计划流集成验证：fake 模型驱动真实 graph/tool loop（离线集成）。

明确边界：本套件是 fake 模型驱动的离线集成验证（write_todos → checkpoint
→ 事件 → snapshot → 恢复读取），**不是**真实 LLM 的计划质量验收。
全程零真实 LLM/网络调用。
"""

import json

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from nexus.config import get_settings
from nexus.main import app
import nexus.main as main_module

TODOS_V1 = [
    {"content": "读取论文证据", "status": "in_progress"},
    {"content": "比较方法", "status": "pending"},
    {"content": "写报告", "status": "pending"},
]
TODOS_V2 = [
    {"content": "读取论文证据", "status": "completed"},
    {"content": "比较方法", "status": "in_progress"},
    {"content": "写报告", "status": "pending"},
]


class _Fake(BaseChatModel):
    """脚本化假模型：按序回放 AIMessage。

    不用 GenericFakeChatModel——其流式实现按内容切块会丢 tool_calls，导致
    流式路径（messages+updates 双模式）根本不触发工具节点。本假模型的
    ``_astream`` 原样产出整条消息（content + tool_calls），流式与非流式
    行为一致。
    """

    _responses: list[AIMessage] = PrivateAttr(default_factory=list)
    _cursor: int = PrivateAttr(default=0)

    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__()
        self._responses = list(responses)

    @property
    def _llm_type(self) -> str:
        return "nexus-scripted-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        message = self._responses[self._cursor] if self._cursor < len(self._responses) else AIMessage(content="ok")
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        result = self._generate(messages, stop, run_manager, **kwargs)
        message = result.generations[0].message
        # 必须产出 ChatGenerationChunk（裸 AIMessageChunk 会破坏基类
        # astream→agenerate 回退路径的 chunk 累积契约）。
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content=message.content,
                tool_calls=list(message.tool_calls or []),
                id=message.id or "fake-chunk",
            )
        )


def _agent_with(responses: list[AIMessage]):
    from deepagents import create_deep_agent
    from langchain.agents.middleware import TodoListMiddleware

    return create_deep_agent(
        model=_Fake(responses),
        tools=[],
        system_prompt="test",
        middleware=[TodoListMiddleware()],
        checkpointer=InMemorySaver(),
    )


def _todo_turn(todos: list[dict], reply: str = "计划已更新。") -> list[AIMessage]:
    return [
        # content 非空：messages 流模式按内容切块，空 content 会让
        # GenericFakeChatModel 流式路径抛 "No generations found in stream"。
        AIMessage(
            content="先建立计划。",
            tool_calls=[{"name": "write_todos", "args": {"todos": todos}, "id": "call-todo"}],
        ),
        AIMessage(content=reply),
    ]


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch):
    """注入 InMemory agent 容器并清空计划 revision 计数器。"""
    monkeypatch.setenv("NEXUS_API_KEY", "")
    get_settings.cache_clear()
    original_agents = main_module._agents
    original_revisions = dict(main_module._plan_revisions)
    main_module._plan_revisions = {}
    yield main_module
    main_module._agents = original_agents
    main_module._plan_revisions = original_revisions
    get_settings.cache_clear()


def _install(agent) -> None:
    main_module._agents = {
        ("research", "deepseek-chat"): agent,
        ("general", "deepseek-chat"): agent,
    }
    main_module._pg_saver = None


async def test_chat_response_carries_monotonic_plan(fake_env):
    """同步响应携带计划快照；revision 随 write_todos 单调递增。"""
    _install(_agent_with(_todo_turn(TODOS_V1) + _todo_turn(TODOS_V2)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "开始研究", "session_id": "plan-1"},
            headers={"X-Nexus-User-Id": "42"},
        )
        second = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "继续", "session_id": "plan-1"},
            headers={"X-Nexus-User-Id": "42"},
        )
    assert first.status_code == 200 and second.status_code == 200
    plan1 = first.json()["plan"]
    plan2 = second.json()["plan"]
    assert plan1 is not None and plan2 is not None
    assert plan1["revision"] == 1 and plan2["revision"] == 2
    assert plan1["plan_id"] == plan2["plan_id"]
    assert plan1["source"] == "agent_plan"
    assert [i["status"] for i in plan1["items"]] == ["in_progress", "pending", "pending"]
    assert [i["status"] for i in plan2["items"]] == ["completed", "in_progress", "pending"]
    # 条目 id 跨 revision 稳定（计划修改可替换项，不改 id）。
    assert [i["id"] for i in plan1["items"]] == [i["id"] for i in plan2["items"]]


async def test_stream_emits_plan_event_from_state_update(fake_env):
    """SSE 流中 plan 事件来自真实 state update（非自然语言解析）。"""
    _install(_agent_with(_todo_turn(TODOS_V1)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream(
            "POST",
            "/api/v1/nexus/chat/stream",
            json={"message": "开始研究", "session_id": "plan-sse"},
            headers={"X-Nexus-User-Id": "42"},
        ) as response:
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
    assert response.status_code == 200
    events = []
    for block in body.split("\n\n"):
        if block.startswith("event: plan\n"):
            data = block.split("data: ", 1)[1]
            events.append(json.loads(data))
    assert len(events) == 1
    snapshot = events[0]
    assert snapshot["plan_id"].startswith("plan-")
    assert [i["content"] for i in snapshot["items"]] == [t["content"] for t in TODOS_V1]
    # 计划之外原协议继续有效：token/tool_call/tool_result/done 仍在流中。
    assert "event: tool_call" in body and "event: done" in body
    assert '"name": "write_todos"' in body.replace("'write_todos'", '"write_todos"') or "write_todos" in body


async def test_plan_restore_readonly_and_user_isolation(fake_env):
    """恢复读取返回 checkpoint 真值（pending 保持 pending，不自动勾选）；
    不同用户同 session_id 互不可见；恢复不触发任何执行。"""
    _install(_agent_with(_todo_turn(TODOS_V1)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        chat = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "开始研究", "session_id": "plan-restore"},
            headers={"X-Nexus-User-Id": "42"},
        )
        assert chat.status_code == 200
        owner_view = await client.get(
            "/api/v1/nexus/plan/plan-restore", headers={"X-Nexus-User-Id": "42"}
        )
        other_view = await client.get(
            "/api/v1/nexus/plan/plan-restore", headers={"X-Nexus-User-Id": "99"}
        )
    assert owner_view.status_code == 200 and other_view.status_code == 200
    owner_plan = owner_view.json()["plan"]
    assert owner_plan is not None
    assert [i["status"] for i in owner_plan["items"]].count("pending") == 2, (
        "恢复读取不得把未完成项改成完成"
    )
    assert other_view.json()["plan"] is None, "跨用户不得读到他人计划"


async def test_simple_chat_has_no_plan(fake_env):
    """简单回复（未调 write_todos）→ 无计划快照（不伪造空计划）。"""
    _install(_agent_with([AIMessage(content="你好！")]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/nexus/chat",
            json={"message": "你好", "session_id": "plan-none"},
            headers={"X-Nexus-User-Id": "42"},
        )
    assert response.status_code == 200
    assert response.json()["plan"] is None


async def test_plan_revision_counter_monotonic(fake_env):
    """进程内计数器单调递增（含恢复读取也会推进基线，不回退）。"""
    assert main_module._next_plan_revision("t") == 1
    assert main_module._next_plan_revision("t") == 2
    assert main_module._next_plan_revision("other") == 1
    assert main_module._next_plan_revision("t") == 3
