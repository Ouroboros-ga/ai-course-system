"""T4 自主安装/试跑/修复循环（N3/SR5 核心）。

行为契约（任务书 T4）：
- 脚本化模型驱动真实图走"读 README→安装→缺包→查错→修复→重跑"，
  调用正式 Adapter（HttpSandboxBackend）＋原生文件/execute 工具；
  假容器只仿 shell 语义（命令→退出码/输出），不断言 prompt；
- 审批次数恒 1；排错不消耗新批准；
- 主聊天（General/Research Ask/Auto）工具面不受实验图污染：全局 openai
  profile 不动，实验图走实例级装配；Ask 下 hostile execute 被拒。

脚本化模型只证明循环协议；真实 LLM 是否选对修复属 T7。
"""

import re

import httpx
import pytest
from langchain_core.messages import AIMessage

from nexus import approvals
from nexus import experiment_runs as runs_module
from nexus import proposals as proposals_module


@pytest.fixture(autouse=True)
def _clean_stores():
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()
    yield
    approvals.clear_memory_store()
    proposals_module.clear_memory_store()
    runs_module.clear_memory_store()


class _ScriptedContainer:
    """假容器：只仿 shell 语义。缺包→装包→重跑通过；记录全部交互。"""

    def __init__(self):
        self.files = {
            "/workspace/README.md": "# fixture\npip install -r requirements.txt\n",
            "/workspace/requirements.txt": "fakepkg\n",
            "/workspace/train.py": "import fakepkg\nprint('loss=0.5')\n",
        }
        self.installed = set()
        self.executions: list[str] = []
        self.uploads: list[str] = []
        self.operation_posts: list[dict] = []

    def _run(self, command):
        self.executions.append(command)
        if command.startswith("pip install fakepkg"):
            self.installed.add("fakepkg")
            return 0, "Successfully installed fakepkg"
        if command.startswith("pip install"):
            return 0, "Requirement already satisfied"
        if "train.py" in command:
            if "fakepkg" not in self.installed:
                return 1, ("Traceback (most recent call last):\n"
                           "ModuleNotFoundError: No module named 'fakepkg'")
            return 0, "loss=0.5"
        if command.startswith("cat "):
            path = command[4:].strip().split()[0]
            if path in self.files:
                return 0, self.files[path]
            return 1, f"cat: {path}: No such file"
        return 0, ""

    def responder(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        def _body():
            try:
                return dict(_json.loads(request.content.decode() or "{}"))
            except Exception:
                return {}

        path = request.url.path
        if request.method == "PUT" and "/sandboxes/" in path:
            return httpx.Response(200, json={"sandbox_id": "sbx-t4",
                                             "status": "ready"})
        if request.method == "POST" and path.endswith("/operations"):
            body = _body()
            op_id = str(body.get("operation_id", ""))
            self.operation_posts.append(body)
            exit_code, output = self._run(str(body.get("command", "")))
            return httpx.Response(200, json={
                "operation_id": op_id, "status": "succeeded",
                "exit_code": exit_code, "output_tail": output,
                "output_truncated": False})
        if request.method == "GET" and "/operations/" in path:
            return httpx.Response(200, json={
                "operation_id": path.rsplit("/", 1)[-1], "status": "succeeded",
                "exit_code": 0, "output_tail": "", "output_truncated": False})
        if request.method == "PUT" and "/files/" in path:
            fpath = "/" + path.split("/files/", 1)[-1]
            self.uploads.append(fpath)
            content = _body().get("content", "")
            if isinstance(content, str):
                self.files[fpath] = content
            return httpx.Response(200, json={"path": fpath, "bytes": 5})
        if request.method == "GET" and path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "POST" and path.endswith("/cancel"):
            return httpx.Response(200, json={"status": "cancelled"})
        if request.method == "GET" and "/sandboxes/" in path:
            return httpx.Response(200, json={"sandbox_id": "sbx-t4",
                                             "status": "ready"})
        return httpx.Response(404, json={"detail": "unknown"})


def _tool_call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id}


def _scripted_model():
    """按固定剧本发工具调用：读→装→跑（败）→修→跑（成）。"""
    from langchain_openai import ChatOpenAI
    from pydantic import PrivateAttr

    from nexus.experiment_agent import _ExperimentChatOpenAI

    script = [
        AIMessage(content="", tool_calls=[
            _tool_call("write_file", {"file_path": "/workspace/probe.txt",
                                      "content": "probe"}, "c0")]),
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "cat /workspace/README.md"}, "c1")]),
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "pip install -r requirements.txt"}, "c2")]),
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "python train.py"}, "c3")]),
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "pip install fakepkg"}, "c4")]),
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "python train.py"}, "c5")]),
        AIMessage(content="修复完成：补装 fakepkg 后 train.py 退出码 0，loss=0.5。"),
    ]

    class _Scripted(_ExperimentChatOpenAI):
        _script: list = PrivateAttr(default_factory=list)
        _bound: list = PrivateAttr(default_factory=list)

        def __init__(self):
            super().__init__(model="deepseek-chat", api_key="spy-key-not-real",
                             base_url="https://api.deepseek.com/v1")
            self._script = list(script)

        def bind_tools(self, tools, **kwargs):
            self._bound = sorted(getattr(t, "name", str(t)) for t in tools)
            return self

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            from langchain_core.outputs import ChatGeneration, ChatResult

            response = self._script.pop(0) if self._script else AIMessage(content="done")
            return ChatResult(generations=[ChatGeneration(message=response)])

    return _Scripted()


class _Flow:
    """任务书示例形态夹具：真审批＋真 run＋真 Adapter＋脚本化模型。"""

    def __init__(self, container):
        self.container = container
        self.user_id = "u-t4"
        self.session_id = "s-t4"

    async def run(self, script="missing_dependency_then_fix"):
        from langgraph.checkpoint.memory import InMemorySaver

        from nexus import experiment_agent as agent_module
        from nexus.experiment_sandbox import HttpSandboxBackend

        assert script == "missing_dependency_then_fix"
        proposal = proposals_module.create_proposal(
            user_id=self.user_id, session_id=self.session_id, preset=None,
            kind="autonomous_experiment", scope={
                "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
                "repo_revision": "abc", "source_refs": [], "data_refs": [],
                "network_profile": "pypi-allowed",
                "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                              "wall_time_s": 1800},
                "mode": "smoke", "allow_environment_repair": True})
        req = proposals_module.request_approval_for_proposal(
            proposal["proposal_id"], user_id=self.user_id,
            expected_version=proposal["version"])
        aid = req["approval"]["approval_id"]
        approvals.decide_approval(aid, self.user_id, "approved")
        consumed = approvals.consume_approval(
            aid, user_id=self.user_id, session_id=self.session_id, preset={})
        run = runs_module.create_or_get_run(
            run_id=aid, owner=self.user_id, session_id=self.session_id,
            proposal_id=proposal["proposal_id"], proposal_version=1,
            scope_hash=proposal["scope_hash"], approval_id=aid)
        transport = httpx.MockTransport(self.container.responder)
        backend = HttpSandboxBackend(
            run_id=run["run_id"], base_url="http://control.test",
            token="t", transport=transport)
        agent = agent_module.build_experiment_agent(
            backend, InMemorySaver(), _scripted_model())
        tool_events = []
        final_text = ""
        async for stream_mode, payload in agent.astream(
                {"messages": [{"role": "user", "content": "配置并试跑，缺包自行修复"}]},
                {"configurable": {"thread_id": f"exp-{run['run_id']}"}},
                stream_mode=["updates"]):
            for _node, delta in (payload or {}).items():
                for msg in (delta.get("messages") or []) if isinstance(delta, dict) else []:
                    if isinstance(msg, AIMessage):
                        for call in msg.tool_calls or []:
                            tool_events.append(("call", call.get("name"), call.get("args")))
                    else:
                        name = getattr(msg, "name", "")
                        if name:
                            tool_events.append(("result", name, str(msg.content)[:2000]))
                state = None
        state = await agent.aget_state(
            {"configurable": {"thread_id": f"exp-{run['run_id']}"}})
        for msg in reversed(state.values.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                final_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                break
        # 落盘 attempt（执行器语义：完成的 operation 才记，不重放）。
        for kind, name, content in tool_events:
            if kind == "result" and name == "execute":
                match = re.search(r"exit code (\d+)", content)
                runs_module.record_attempt(
                    run["run_id"],
                    actual_command=_last_command(tool_events, content),
                    exit_code=int(match.group(1)) if match else None,
                    log_ref=content[:500])

        class _Result:
            pass

        result = _Result()
        result.tool_events = tool_events
        result.executions = [c for k, n, c in tool_events
                             if k == "call" and n == "execute"]
        failures = [c for k, n, c in tool_events
                    if k == "result" and n == "execute" and "ModuleNotFoundError" in c]
        successes = [c for k, n, c in tool_events
                     if k == "result" and n == "execute" and "exit code 0" in c]
        result.observed_failure_before_repair = bool(failures) and bool(successes)
        last_codes = re.findall(r"exit code (\d+)", " | ".join(
            c for k, n, c in tool_events if k == "result" and n == "execute"))
        result.final_exit_code = int(last_codes[-1]) if last_codes else None
        # 原生文件工具经正式 Adapter 进沙箱：write_file 调用成功（内容经
        # execute  funnel 或 upload 传输，容器侧 operation_posts 为证）。
        result.used_framework_file_tools = any(
            k == "call" and n == "write_file" for k, n, _c in tool_events)
        result.final_text = final_text
        result.proposal_id = proposal["proposal_id"]
        result.run_id = run["run_id"]
        result.user_id = self.user_id
        return result

    def approval_count(self, result):
        return len([a for a in approvals.list_approvals(
            user_id=result.user_id, status=None)
            if a.get("proposal_id") == result.proposal_id])


def _last_command(tool_events, content):
    """回找该结果对应的最近一次 execute 调用命令（仅测试归因用）。"""
    current = ""
    for kind, name, payload in tool_events:
        if kind == "call" and name == "execute":
            current = (payload or {}).get("command", "")
        if kind == "result" and payload == content:
            return current
    return current


@pytest.fixture()
def experiment_flow():
    return _Flow(_ScriptedContainer())


async def test_repair_loop_uses_real_tools(experiment_flow):
    result = await experiment_flow.run(script="missing_dependency_then_fix")
    assert experiment_flow.approval_count(result) == 1
    assert len(result.executions) >= 3
    assert result.observed_failure_before_repair
    assert result.final_exit_code == 0
    assert result.used_framework_file_tools


async def test_experiment_graph_does_not_pollute_main_surfaces():
    """实验图实例隔离：全局 openai profile 不动；主面无 execute。"""
    from nexus.agent import _tools_for_mode

    assert "execute" not in {t.name for t in _tools_for_mode("research", "auto")}
    assert "execute" not in {t.name for t in _tools_for_mode("research", "ask")}
    assert "execute" not in {t.name for t in _tools_for_mode("general", "auto")}
    # 实验图经独立 provider 键装配，原生 execute 可见。
    from langgraph.checkpoint.memory import InMemorySaver

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    backend = HttpSandboxBackend(
        run_id="probe", base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    agent = agent_module.build_experiment_agent(
        backend, InMemorySaver(), _scripted_model())
    registry = set(agent.nodes["tools"].bound.tools_by_name.keys())
    assert "execute" in registry
    assert "write_file" in registry
    assert "task" not in registry


async def test_ask_hostile_execute_rejected(monkeypatch):
    """Ask 主图敌意 execute 调用被拒（error ToolMessage），无沙箱副作用。"""
    from langchain_core.messages import ToolMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_openai import ChatOpenAI
    from pydantic import PrivateAttr

    import nexus.agent as agent_module

    monkeypatch.setenv("NEXUS_DEEPSEEK_API_KEY", "dummy-key-for-hostile-exp")

    class _Spy(ChatOpenAI):
        _responses: list = PrivateAttr(default_factory=list)

        def __init__(self, responses):
            super().__init__(model="deepseek-chat", api_key="spy-key-not-real",
                             base_url="https://api.deepseek.com/v1")
            self._responses = list(responses)

        def bind_tools(self, tools, **kwargs):
            return self

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            response = self._responses.pop(0) if self._responses else AIMessage(content="ok")
            return ChatResult(generations=[ChatGeneration(message=response)])

    hostile = AIMessage(content="", tool_calls=[
        {"name": "execute", "args": {"command": "rm -rf /"}, "id": "call-x"}])
    monkeypatch.setattr(agent_module, "build_llm",
                        lambda model=None: _Spy([hostile, AIMessage(content="done")]))
    agent = agent_module.build_agent(mode="research", execution_mode="ask")
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"configurable": {"thread_id": "hostile-exp-check"}})
    errors = [m for m in result["messages"]
              if isinstance(m, ToolMessage) and m.status == "error"]
    assert {m.name for m in errors} >= {"execute"}
    assert "rm -rf" not in str(result.get("files", ""))
