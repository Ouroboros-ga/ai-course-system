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
        # F4：固定仓库位（与 _ready_run 的 deadbeef… 对齐则复用跳过；
        # None＋空工作区则走克隆，由 clone_files 落盘）。
        self.repo_sha: str | None = "deadbeef1234567890"
        self.clone_files: dict[str, str] = {}
        self.builds: dict[str, dict] = {}

    def _run(self, command):
        self.executions.append(command)
        if command.startswith("git -C /workspace rev-parse HEAD"):
            if self.repo_sha:
                return 0, self.repo_sha + "\n"
            return 128, "fatal: not a git repository"
        if command.startswith("git init"):
            self.repo_sha = "deadbeef1234567890"
            self.files.update(dict(self.clone_files))
            return 0, ""
        if command.startswith("ls -a /workspace"):
            names = sorted(
                path.rsplit("/", 1)[-1] for path in self.files
                if path.startswith("/workspace/"))
            return 0, "\n".join([".", ".."] + names)
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
        if request.method == "PUT" and "/files/" in path:
            # 文件上传先于 ensure 分支判定（否则被 ensure 吞掉，无法验证内容
            # 真的到达容器）。
            fpath = "/" + path.split("/files/", 1)[-1]
            self.uploads.append(fpath)
            try:
                self.files[fpath] = request.content.decode("utf-8")
            except UnicodeDecodeError:
                self.files[fpath] = ""
            return httpx.Response(200, json={"path": fpath,
                                             "bytes": len(request.content)})
        if request.method == "PUT" and "/sandboxes/" in path and "/files/" not in path \
                and "/builds" not in path:
            body = _body()
            if body.get("image"):
                # F4：镜像迁移（新容器；旧工作区状态由调用方重准备）。
                return httpx.Response(200, json={
                    "sandbox_id": "sbx-migrated", "status": "ready",
                    "image": body["image"],
                    "image_digest": "sha256:migrated"})
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
        if request.method == "POST" and path.endswith("/builds"):
            if not getattr(self, "builder_configured", True):
                return httpx.Response(501, json={
                    "detail": "BUILDER_NOT_CONFIGURED：构建器未配置。"})
            body = _body()
            build_id = f"bld-{len(self.builds) + 1:04d}"
            self.builds[build_id] = dict(body)
            return httpx.Response(200, json={"build_id": build_id,
                                             "status": "running"})
        if request.method == "GET" and "/builds/" in path:
            build_id = path.rsplit("/", 1)[-1]
            scripted = getattr(self, "build_result", None) or {
                "status": "succeeded",
                "build_image": "registry.local/proj:deadbeef",
                "exec_image": "registry.local/proj-exec:deadbeef",
                "log_tail": "Successfully built", "detail": ""}
            return httpx.Response(200, json={"build_id": build_id, **scripted})
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


def _ready_run(user_id: str, session_id: str | None = None) -> dict:
    """建一个已批准＋已核销、可直接执行的 run（License verified＋修订固定）。"""
    session_id = session_id or f"s-{user_id}"
    proposal = proposals_module.create_proposal(
        user_id=user_id, session_id=session_id, preset=None,
        kind="autonomous_experiment", scope={
            "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
            "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
            "network_profile": "pypi-allowed",
            "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                          "wall_time_s": 1800},
            "mode": "smoke", "allow_environment_repair": True},
        license_info={"spdx": "MIT", "status": "verified"})
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id=user_id,
        expected_version=proposal["version"])
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, user_id, "approved")
    approvals.consume_approval(aid, user_id=user_id, session_id=session_id,
                               preset={})
    return runs_module.create_or_get_run(
        run_id=aid, owner=user_id, session_id=session_id,
        proposal_id=proposal["proposal_id"], proposal_version=1,
        scope_hash=proposal["scope_hash"], approval_id=aid)


def _scripted_model(script=None):
    """按剧本发工具调用（默认：读→装→跑（败）→修→跑（成））。"""
    from langchain_openai import ChatOpenAI
    from pydantic import PrivateAttr

    from nexus.experiment_agent import _ExperimentChatOpenAI

    if script is None:
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
                "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
                "network_profile": "pypi-allowed",
                "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                              "wall_time_s": 1800},
                "mode": "smoke", "allow_environment_repair": True},
            license_info={"spdx": "MIT", "status": "verified"})
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
        fail_idx = [i for i, (k, n, c) in enumerate(tool_events)
                    if k == "result" and n == "execute" and "ModuleNotFoundError" in c]
        ok_idx = [i for i, (k, n, c) in enumerate(tool_events)
                  if k == "result" and n == "execute" and "exit code 0" in c]
        # 时序断言：失败必须发生在（最后一次）成功之前，而非"各出现过一次"。
        result.observed_failure_before_repair = (
            bool(fail_idx) and bool(ok_idx) and min(fail_idx) < max(ok_idx))
        last_codes = re.findall(r"exit code (\d+)", " | ".join(
            c for k, n, c in tool_events if k == "result" and n == "execute"))
        result.final_exit_code = int(last_codes[-1]) if last_codes else None
        # 原生文件工具经正式 Adapter 进沙箱：模型发起 write_file 且内容实际
        # 到达容器（PUT /files 记录为证），不是"只发起了调用"。
        result.used_framework_file_tools = (
            any(k == "call" and n == "write_file" for k, n, _c in tool_events)
            and bool(self.container.uploads))
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


def test_terminal_status_never_overwrites_cancelled():
    """T5-1：取消优先——已终态 run 的终态落盘是空操作，不互相覆盖。"""
    from nexus import experiment_agent as agent_module

    run = runs_module.create_or_get_run(
        run_id="t5-guard-1", owner="u1", session_id="s1",
        proposal_id="pp1", proposal_version=1,
        scope_hash="h" * 32, approval_id="apv1")
    assert run["status"] == "running"
    # running → failed 正常落盘。
    agent_module.set_terminal_status("t5-guard-1", "failed", "boom")
    assert runs_module.get_run("t5-guard-1")["status"] == "failed"
    # failed 后再落 cancelled/succeeded 都不得覆盖。
    agent_module.set_terminal_status("t5-guard-1", "cancelled", "late cancel")
    agent_module.set_terminal_status("t5-guard-1", "succeeded", "late success")
    assert runs_module.get_run("t5-guard-1")["status"] == "failed"
    # 取消路径：cancelled 后图的 failed 收尾不得覆盖（线上实证 bug）。
    run2 = runs_module.create_or_get_run(
        run_id="t5-guard-2", owner="u1", session_id="s1",
        proposal_id="pp1", proposal_version=1,
        scope_hash="h" * 32, approval_id="apv2")
    assert run2["status"] == "running"
    runs_module.request_cancel("t5-guard-2", "u1")
    agent_module.set_terminal_status("t5-guard-2", "failed", "实验图异常：Rerun")
    assert runs_module.get_run("t5-guard-2")["status"] == "cancelled"


def test_file_tool_summary_and_exit():
    """原生文件工具摘要/退出码映射（attempt 记录用）。"""
    from nexus import experiment_agent as agent_module
    from langchain_core.messages import ToolMessage

    assert agent_module.file_tool_summary(
        "write_file", {"file_path": "/workspace/a.txt"}) == "write_file /workspace/a.txt"
    assert agent_module.file_tool_summary("grep", {"pattern": "x"}) == "grep x"
    assert agent_module.file_tool_summary("execute", {}) == "execute"
    assert agent_module.file_tool_exit(
        ToolMessage(name="write_file", content="ok", tool_call_id="c",
                    status="success")) == 0
    assert agent_module.file_tool_exit(
        ToolMessage(name="read_file", content="nope", tool_call_id="c",
                    status="error")) == 1


async def test_bound_run_records_file_tool_attempts():
    """T5-1：生产记录覆盖原生文件工具（与 control operation 1:1 对账）。

    脚本化模型走真实 execute_bound_run＋真 Adapter＋假容器：write_file 与
    execute 调用全部落为 attempt，且每个 attempt 都有真实 operation_id。
    """
    import httpx
    from langgraph.checkpoint.memory import InMemorySaver

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    proposal = proposals_module.create_proposal(
        user_id="u-t4", session_id="s-t4", preset=None,
        kind="autonomous_experiment", scope={
            "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
            "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
            "network_profile": "pypi-allowed",
            "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                          "wall_time_s": 1800},
            "mode": "smoke", "allow_environment_repair": True},
        license_info={"spdx": "MIT", "status": "verified"})
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id="u-t4", expected_version=1)
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, "u-t4", "approved")
    approvals.consume_approval(aid, user_id="u-t4", session_id="s-t4", preset={})
    run = runs_module.create_or_get_run(
        run_id=aid, owner="u-t4", session_id="s-t4",
        proposal_id=proposal["proposal_id"], proposal_version=1,
        scope_hash=proposal["scope_hash"], approval_id=aid)
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-t4", session_id="s-t4",
        backend=backend, model=_scripted_model(), checkpointer=InMemorySaver())
    assert result["status"] == "succeeded"
    stored = runs_module.get_run(run["run_id"])
    commands = [a["actual_command"] for a in stored["attempts"]]
    # 路由 ls＋脚本 6 次工具调用（write_file＋5 execute）全部记录。
    assert stored["attempt_no"] >= 7
    assert any(c.startswith("write_file /workspace/probe.txt") for c in commands)
    assert sum("pip install fakepkg" in c for c in commands) == 1
    assert sum("python train.py" in c for c in commands) == 2
    # 每个 attempt 都有真实 operation_id（可与控制服务对账）。
    op_ids = [a["operation_id"] for a in stored["attempts"]]
    assert all(op_id.startswith(run["run_id"] + "-op-") for op_id in op_ids)
    posted = [p["operation_id"] for p in container.operation_posts]
    assert set(op_ids) <= set(posted)


async def test_file_tool_tail_does_not_fake_success():
    """A1 回归：末次工具是成功的文件工具时，run 与报告都不得判成功。

    剧本：execute 失败（缺包）→ read_file 成功收尾。文件工具只作对账
    attempt，不参与终态判定（否则"读一次文件"就把失败伪装成成功）。
    """
    import httpx
    from langgraph.checkpoint.memory import InMemorySaver

    from nexus import experiment_agent as agent_module
    from nexus import experiment_report as report_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    proposal = proposals_module.create_proposal(
        user_id="u-a1", session_id="s-a1", preset=None,
        kind="autonomous_experiment", scope={
            "objective": "配置并试跑", "repo_url": "https://github.com/example/r",
            "repo_revision": "deadbeef1234567890", "source_refs": [], "data_refs": [],
            "network_profile": "pypi-allowed",
            "resources": {"cpu": 1.0, "memory_mb": 2048, "disk_mb": 5120,
                          "wall_time_s": 1800},
            "mode": "smoke", "allow_environment_repair": True},
        license_info={"spdx": "MIT", "status": "verified"})
    req = proposals_module.request_approval_for_proposal(
        proposal["proposal_id"], user_id="u-a1",
        expected_version=proposal["version"])
    aid = req["approval"]["approval_id"]
    approvals.decide_approval(aid, "u-a1", "approved")
    approvals.consume_approval(aid, user_id="u-a1", session_id="s-a1", preset={})
    run = runs_module.create_or_get_run(
        run_id=aid, owner="u-a1", session_id="s-a1",
        proposal_id=proposal["proposal_id"], proposal_version=1,
        scope_hash=proposal["scope_hash"], approval_id=aid)
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    script = [
        AIMessage(content="", tool_calls=[
            _tool_call("execute", {"command": "python train.py"}, "c0")]),
        AIMessage(content="", tool_calls=[
            _tool_call("read_file", {"file_path": "/workspace/train.py"}, "c1")]),
        AIMessage(content="查看文件后停止。"),
    ]
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-a1", session_id="s-a1",
        backend=backend, model=_scripted_model(script), checkpointer=InMemorySaver())
    assert result["status"] == "failed", "文件工具收尾不得把失败 run 判成成功"
    stored = runs_module.get_run(run["run_id"])
    kinds = [str((a.get("config_changes") or {}).get("kind") or "")
             for a in stored["attempts"]]
    assert "file_tool" in kinds, "文件工具仍须落 attempt（对账语义不变）"
    report = report_module.build_experiment_report(
        run=stored, scope=proposal["scope"],
        license_info={"spdx": "MIT", "status": "verified"})
    assert report["execution_succeeded"] is False
    assert report["metric_verdict"] == "not_evaluated"


def test_operation_attribution_exact_for_sequential_calls():
    """T5-1：顺序调用下 attempt→operation 精确 1:1（并行批量不冒充）。

   用 FakeBackend 的提交日志回放：顺序结果全部精确命中；已被认领的
    不重复发放（并行错位时返回空串，不给错 id）。
    """
    from nexus import experiment_agent as agent_module

    class _FakeBackend:
        submitted_ops = [
            ("r-op-0001", "ls -a /workspace"),
            ("r-op-0002", "cat /workspace/README.md"),
            ("r-op-0003", "pip install fakepkg"),
        ]
        last_operation_id = "r-op-0003"

    used: set[str] = set()
    assert agent_module.attribute_operation(
        _FakeBackend, "cat /workspace/README.md", used) == "r-op-0002"
    assert agent_module.attribute_operation(
        _FakeBackend, "pip install fakepkg", used) == "r-op-0003"
    # funnel 脚本（命令文本对不上 tool 参数）回退最近未认领。
    assert agent_module.attribute_operation(
        _FakeBackend, "write_file /workspace/a.txt", used) == "r-op-0001"
    # 全部认领后不再发放（宁缺毋错）。
    assert agent_module.attribute_operation(
        _FakeBackend, "echo hi", used) == ""


async def test_bound_run_cancel_before_start_stays_cancelled():
    """取消旗在启动前已置位：直接 cancelled，不提交任何 operation。"""
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    run = runs_module.create_or_get_run(
        run_id="t5-early-cancel", owner="u1", session_id="s1",
        proposal_id="pp1", proposal_version=1,
        scope_hash="h" * 32, approval_id="apv-ec")
    runs_module.request_cancel("t5-early-cancel", "u1")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u1", session_id="s1",
        backend=backend, model=_scripted_model())
    assert result["status"] == "cancelled"
    assert container.operation_posts == []
    assert runs_module.get_run(run["run_id"])["status"] == "cancelled"


async def test_repo2docker_route_fails_closed_not_delivered():
    """T4：命中 repo2docker 声明 → ROUTE_NOT_DELIVERED，不假装已集成。

    F4：构建器未交付时控制面 501 BUILDER_NOT_CONFIGURED，执行核仍以
    ROUTE_NOT_DELIVERED 失败（T7-B 口径不变），不偷换基础路线。
    """
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    container.files["/workspace/environment.yml"] = "name: fixture\n"
    container.builder_configured = False
    run = _ready_run("u-r2d")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-r2d", session_id="s-u-r2d",
        backend=backend, model=_scripted_model())
    assert result["status"] == "failed"
    assert result["code"] == "ROUTE_NOT_DELIVERED"
    stored = runs_module.get_run(run["run_id"])
    assert stored["attempts"][0]["config_changes"]["route"] == "repo2docker"
    allowed_prefixes = ("ls -a /workspace", "git -C /workspace rev-parse HEAD")
    assert all(any(p["command"].startswith(prefix) for prefix in allowed_prefixes)
               for p in container.operation_posts), \
        "构建器未交付：除路由探测与修订核对（只读）外不得执行任何命令"


async def test_single_executor_lock_dedupes_concurrent_entry():
    """T4：同 run 并发进入只有一个执行者，另一个返回 deduped 且不落状态。"""
    from nexus import experiment_agent as agent_module

    run = _ready_run("u-lock")
    lock = await agent_module._lock_for(run["run_id"])
    async with lock:
        result = await agent_module.execute_bound_run(
            run_id=run["run_id"], owner="u-lock", session_id="s-u-lock")
    assert result["deduped"] is True
    assert runs_module.get_run(run["run_id"])["status"] == "running"


async def test_control_not_configured_fails_run_not_silent_running(monkeypatch):
    """T4：控制服务未配置 → run 落 failed（SANDBOX_NOT_CONFIGURED），不静默 running。"""
    from nexus import experiment_agent as agent_module
    from nexus.config import get_settings

    monkeypatch.setattr(get_settings(), "repro_control_url", "")
    run = _ready_run("u-nocfg")
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-nocfg", session_id="s-u-nocfg")
    assert result["status"] == "failed"
    assert result["code"] == "SANDBOX_NOT_CONFIGURED"
    stored = runs_module.get_run(run["run_id"])
    assert stored["status"] == "failed"
    assert "SANDBOX_NOT_CONFIGURED" in stored["detail"]


def test_select_environment_route_markers():
    """F4：目录感知选路（.binder 目录可检出；Dockerfile 优先；pip 系走基础容器）。"""
    from nexus import experiment_agent as agent_module

    r2d = agent_module.select_environment_route(["README.md", ".binder", "train.py"])
    assert r2d["route"] == "repo2docker"
    assert "binder/" in r2d["markers"]
    docker = agent_module.select_environment_route(["Dockerfile", "requirements.txt"])
    assert docker["route"] == "repo2docker"
    assert docker["markers"][0] == "Dockerfile"
    base = agent_module.select_environment_route(["requirements.txt", "train.py"])
    assert base["route"] == "base_container"
    empty = agent_module.select_environment_route([])
    assert empty["route"] == "base_container"


async def test_pinned_repo_clone_then_route_and_run():
    """F4：空工作区先克隆固定 SHA，再按真实文件选路并执行。"""
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    container.files = {}
    container.repo_sha = None
    container.clone_files = {
        "/workspace/README.md": "# fixture\n",
        "/workspace/requirements.txt": "fakepkg\n",
        "/workspace/train.py": "import fakepkg\nprint('loss=0.5')\n",
    }
    run = _ready_run("u-clone")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-clone", session_id="s-u-clone",
        backend=backend, model=_scripted_model())
    assert result["status"] == "succeeded"
    stored = runs_module.get_run(run["run_id"])
    kinds = [str((a.get("config_changes") or {}).get("stage") or "")
             for a in stored["attempts"]]
    assert "repo_prepare" in kinds, "克隆落 environment attempt，可审计"
    assert container.repo_sha == "deadbeef1234567890"


async def test_pinned_repo_mismatch_fails_without_wipe():
    """F4：工作区已有内容但修订对不上 → 失败，不删除。"""
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    container.repo_sha = "cafef00d" * 2
    run = _ready_run("u-mismatch")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-mismatch", session_id="s-u-mismatch",
        backend=backend, model=_scripted_model())
    assert result["status"] == "failed"
    assert result["code"] == "REPO_STATE_MISMATCH"
    assert not any("rm -rf" in (p.get("command") or "") for p in container.operation_posts)


async def test_repo2docker_build_success_migrates_and_runs():
    """F4：构建成功 → 双镜像落盘 → 迁移执行镜像 → 重准备 → 图继续。"""
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    container.files = {}
    container.repo_sha = None
    container.clone_files = {
        "/workspace/README.md": "# fixture\n",
        "/workspace/environment.yml": "name: fixture\n",
        "/workspace/requirements.txt": "fakepkg\n",
        "/workspace/train.py": "import fakepkg\nprint('loss=0.5')\n",
    }
    run = _ready_run("u-r2dok")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-r2dok", session_id="s-u-r2dok",
        backend=backend, model=_scripted_model())
    assert result["status"] == "succeeded"
    stored = runs_module.get_run(run["run_id"])
    builds = [a for a in stored["attempts"]
              if str(a.get("actual_command") or "").startswith("repo2docker build")]
    assert builds and builds[0]["exit_code"] == 0
    assert builds[0]["config_changes"]["exec_image"] == "registry.local/proj-exec:deadbeef"
    from nexus import experiment_report as report_module

    report = report_module.build_experiment_report(
        run=stored, scope={"objective": "x", "repo_url": "https://github.com/example/r",
                           "repo_revision": "deadbeef1234567890", "source_refs": [],
                           "data_refs": [], "network_profile": "p", "resources": {},
                           "mode": "smoke"})
    assert report["recipe"]["exec_image"] == "registry.local/proj-exec:deadbeef"
    assert report["recipe"]["build_image"] == "registry.local/proj:deadbeef"


async def test_repo2docker_build_failure_no_silent_fallback():
    """F4：构建失败 → BUILD_FAILED，不偷换基础路线记成功。"""
    import httpx

    from nexus import experiment_agent as agent_module
    from nexus.experiment_sandbox import HttpSandboxBackend

    container = _ScriptedContainer()
    container.files = {}
    container.repo_sha = None
    container.clone_files = {"/workspace/environment.yml": "name: fixture\n"}
    container.build_result = {"status": "failed", "build_image": "",
                              "exec_image": "", "log_tail": "conda boom",
                              "detail": "solve failed"}
    run = _ready_run("u-r2dfail")
    backend = HttpSandboxBackend(
        run_id=run["run_id"], base_url="http://control.test", token="t",
        transport=httpx.MockTransport(container.responder))
    result = await agent_module.execute_bound_run(
        run_id=run["run_id"], owner="u-r2dfail", session_id="s-u-r2dfail",
        backend=backend, model=_scripted_model())
    assert result["status"] == "failed"
    assert result["code"] == "BUILD_FAILED"
    posted = [str(p.get("command") or "") for p in container.operation_posts]
    assert not any("pip install" in command for command in posted), \
        "构建失败不得回退基础容器安装"
