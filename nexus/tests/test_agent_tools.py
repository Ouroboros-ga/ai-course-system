"""M0-B1 工具面收敛回归（前端规格 D1）。

deepagents 默认给主智能体挂载全部文件工具（write_file/edit_file/delete/
ls/glob/grep）、execute 与 task 子代理。本套件锁定 nexus.agent.build_agent
的三层收敛结果：

1. 执行器注册表恰为 read_file + NEXUS_TOOLS（结构性移除）；
2. 模型请求可见面同上（HarnessProfile excluded_tools 过滤）；
3. 敌意/被注入的模型输出请求被禁工具时被拒，不产生副作用；
4. 即使结构性移除失效（工具被注册），excluded_tools 调用侧仍拒绝执行。

全程零真实 LLM 调用：_SpyChatOpenAI 继承 ChatOpenAI（保持 provider 判定为
"openai"，profile 收敛逻辑照常生效）但 _agenerate 返回预设消息。
"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

import nexus.agent
from nexus.agent import NEXUS_EXCLUDED_TOOLS, _register_tool_surface_profile, build_agent
from nexus.tools import NEXUS_TOOLS

EXPECTED_SURFACE = sorted(["read_file"] + [t.name for t in NEXUS_TOOLS])


class _SpyChatOpenAI(ChatOpenAI):
    """不联网的 ChatOpenAI 替身：bind_tools 记录模型可见工具面。

    ChatOpenAI 是 pydantic 模型，间谍状态用 PrivateAttr 挂载。
    """

    _responses: list[AIMessage] = PrivateAttr(default_factory=list)
    _bound_tool_names: list[str] = PrivateAttr(default_factory=list)

    def __init__(self, responses: list[AIMessage]) -> None:
        super().__init__(
            model="deepseek-chat",
            api_key="spy-key-not-real",
            base_url="https://api.deepseek.com/v1",
        )
        self._responses = list(responses)

    @property
    def bound_tool_names(self) -> list[str]:
        return list(self._bound_tool_names)

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        self._bound_tool_names = sorted(getattr(t, "name", str(t)) for t in tools)
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        response = self._responses.pop(0) if self._responses else AIMessage(content="ok")
        return ChatResult(generations=[ChatGeneration(message=response)])


def _registry(agent) -> list[str]:
    return sorted(agent.nodes["tools"].bound.tools_by_name.keys())


def _tool_messages(result: dict) -> list[ToolMessage]:
    return [m for m in result["messages"] if isinstance(m, ToolMessage)]


def test_excluded_set_covers_default_dangerous_tools():
    """排除集覆盖 deepagents 全部默认文件工具 + execute + task。"""
    assert NEXUS_EXCLUDED_TOOLS == frozenset(
        {"ls", "write_file", "edit_file", "delete", "glob", "grep", "execute", "task"}
    )


async def test_executor_registry_converged(monkeypatch: pytest.MonkeyPatch):
    """执行器注册表恰为 read_file + 四个产品工具（结构性移除 + GP 禁用）。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-registry")
    agent = build_agent()
    registry = _registry(agent)
    assert registry == EXPECTED_SURFACE
    assert not set(registry) & NEXUS_EXCLUDED_TOOLS


async def test_model_visible_tools_converged(monkeypatch: pytest.MonkeyPatch):
    """模型请求侧可见工具面同执行器注册表（profile 过滤生效）。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-surface")
    spy = _SpyChatOpenAI(responses=[AIMessage(content="你好，我是 Nexus。")])
    monkeypatch.setattr(nexus.agent, "build_llm", lambda: spy)
    agent = build_agent()
    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "surface-check"}},
    )
    assert spy.bound_tool_names == EXPECTED_SURFACE


async def test_hostile_tool_calls_rejected(monkeypatch: pytest.MonkeyPatch):
    """被注入的模型输出请求被禁工具：全部被拒（error ToolMessage），无写副作用。"""
    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-hostile")
    hostile = AIMessage(
        content="",
        tool_calls=[
            {"name": "write_file", "args": {"path": "/tmp/evil.txt", "content": "pwn"}, "id": "call-1"},
            {"name": "task", "args": {"description": "exfiltrate"}, "id": "call-2"},
            {"name": "execute", "args": {"command": "rm -rf /"}, "id": "call-3"},
            {"name": "edit_file", "args": {"path": "/etc/passwd", "old": "a", "new": "b"}, "id": "call-4"},
        ],
    )
    spy = _SpyChatOpenAI(responses=[hostile, AIMessage(content="done")])
    monkeypatch.setattr(nexus.agent, "build_llm", lambda: spy)
    agent = build_agent()
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "hostile-check"}},
    )
    errors = {m.name: m for m in _tool_messages(result) if m.status == "error"}
    assert {"write_file", "task", "execute", "edit_file"} <= set(errors)
    assert not result.get("files")


async def test_exclusion_middleware_rejects_registered_but_excluded_tool():
    """第二层防御直测：结构性移除失效（工具仍被注册）时，excluded_tools
    的调用侧拒绝仍拦截执行。"""
    from deepagents import create_deep_agent
    from langchain_core.tools import tool

    @tool
    def task(description: str) -> str:
        """敌意替身：若被真正执行则断言失败。"""
        raise AssertionError("excluded tool must never execute")

    _register_tool_surface_profile()
    hostile = AIMessage(
        content="",
        tool_calls=[{"name": "task", "args": {"description": "boom"}, "id": "call-t"}],
    )
    spy = _SpyChatOpenAI(responses=[hostile, AIMessage(content="rejected")])
    agent = create_deep_agent(model=spy, tools=[task], checkpointer=InMemorySaver())
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "exclusion-check"}},
    )
    rejected = [m for m in _tool_messages(result) if m.name == "task"]
    assert rejected
    assert all(m.status == "error" for m in rejected)
    assert all("not available" in str(m.content) for m in rejected)
