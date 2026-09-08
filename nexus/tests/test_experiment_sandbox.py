"""T1-a 契约测试：原生文件工具经 FakeTransport 进入控制服务契约。

任务书 T1 要求：原生 write/edit/read/grep 产生的实际命令全部进入
FakeTransport；传输超时后同 operation_id 查询，不生成新命令；生产执行路径
禁止回落宿主 subprocess。全部离线（httpx.MockTransport），零真实容器/网络。

注意边界：FakeTransport 只实现控制服务 HTTP 契约（operations/files 端点＋
内存文件存根）；容器内真实语义（隔离/取消/回收）属 T1-b 真实容器验证，
不在此冒充。
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from nexus.experiment_contracts import (
    ExperimentScope,
    Resources,
    SandboxResult,
)
from nexus.experiment_sandbox import (
    ExperimentSandboxError,
    HttpSandboxBackend,
)


class _FakeControlService:
    """最小控制服务替身：ensure/operations/files 端点＋内存文件存根。

    operation 终端结果按 scripts 队列 scripted（缺省 succeeded 空输出）；
    GET operation 返回最近提交态（query_scripts 可预置 running 序列）。
    """

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.ensure_calls: list[str] = []
        self.ensure_bodies: list[dict] = []
        self.operation_posts: list[dict] = []
        self.operation_queries: list[str] = []
        self.file_puts: list[tuple[str, bytes]] = []
        self.file_gets: list[str] = []
        self.cancel_calls: list[str] = []
        self.scripts: list[dict] = []
        self.query_scripts: list[dict] = []
        self.submitted: dict[str, dict] = {}

    def _scripted_result(self, operation_id: str) -> dict:
        if self.scripts:
            custom = dict(self.scripts.pop(0))
            custom.setdefault("operation_id", operation_id)
            custom.setdefault("status", "succeeded")
            custom.setdefault("exit_code", 0)
            custom.setdefault("output_tail", "")
            custom.setdefault("output_truncated", False)
            return custom
        return {"operation_id": operation_id, "status": "succeeded",
                "exit_code": 0, "output_tail": "", "output_truncated": False}

    def responder(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "PUT" and "/files" not in path:
            self.ensure_calls.append(path)
            self.ensure_bodies.append(json.loads(request.content or b"{}"))
            return httpx.Response(200, json={"sandbox_id": "sb-test",
                                             "status": "ready"})
        if request.method == "POST" and path.endswith("/operations"):
            body = json.loads(request.content or b"{}")
            self.operation_posts.append(body)
            result = self._scripted_result(str(body.get("operation_id", "")))
            self.submitted[result["operation_id"]] = result
            return httpx.Response(200, json=result)
        if request.method == "GET" and "/operations/" in path:
            operation_id = path.rsplit("/", 1)[-1]
            self.operation_queries.append(operation_id)
            if self.query_scripts:
                result = dict(self.query_scripts.pop(0))
                result.setdefault("operation_id", operation_id)
                self.submitted[operation_id] = result
                return httpx.Response(200, json=result)
            known = self.submitted.get(operation_id)
            if known is None:
                return httpx.Response(404, json={"detail": "unknown operation"})
            return httpx.Response(200, json=known)
        if request.method == "PUT" and "/files/" in path:
            file_path = "/" + path.split("/files/", 1)[1]
            self.files[file_path] = bytes(request.content or b"")
            self.file_puts.append((file_path, bytes(request.content or b"")))
            return httpx.Response(200, json={})
        if request.method == "GET" and "/files/" in path:
            file_path = "/" + path.split("/files/", 1)[1]
            self.file_gets.append(file_path)
            if file_path not in self.files:
                return httpx.Response(404, json={"detail": "file_not_found"})
            return httpx.Response(200, content=self.files[file_path])
        if request.method == "POST" and path.endswith("/cancel"):
            self.cancel_calls.append(path)
            return httpx.Response(200, json={"status": "cancelled"})
        raise AssertionError(f"未声明的控制面调用（不得静默放行）：{request.method} {path}")


def _backend(service: _FakeControlService, **kwargs) -> HttpSandboxBackend:
    transport = httpx.MockTransport(service.responder)
    return HttpSandboxBackend(run_id="run-t1", base_url="http://control.test",
                              token="tok", transport=transport, **kwargs)


def test_task_book_fixture_native_tools_funnel_through_transport():
    """任务书 T1 夹具等价：原生 write/edit/execute 的实际命令全部进入传输层。

    服务端脚本语义属 deepagents 已发布代码（版本已锁定），此处不断言；
    断言路由（命令/文件进入 FakeTransport）与结果映射。
    """
    service = _FakeControlService()
    service.scripts.append({"output_tail": "", "exit_code": 0})  # write 预检
    service.scripts.append({"output_tail": '{"count": 1}'})  # edit 内联脚本回执
    service.scripts.append({"output_tail": "after"})  # cat 回显（scripted）
    backend = _backend(service)

    written = backend.write("/workspace/probe.txt", "before")
    assert written.error is None, written
    assert service.files["/workspace/probe.txt"] == b"before"

    edited = backend.edit("/workspace/probe.txt", "before", "after")
    assert edited.error is None, edited

    result = backend.execute("cat /workspace/probe.txt")
    assert result.exit_code == 0
    assert "after" in result.output

    commands = [p["command"] for p in service.operation_posts]
    assert len(commands) == 3, "write 预检/edit/ cat 各一次 operation 提交"
    assert any("/workspace/probe.txt" in c for c in commands)
    assert commands[-1] == "cat /workspace/probe.txt"
    assert service.file_puts == [("/workspace/probe.txt", b"before")]
    assert backend.last_operation_id.startswith("run-t1-op-")


def test_ensure_payload_carries_scope_hash_and_resources():
    """A2/A4：ensure 携带授权 scope_hash 与已确认 resources（§2 契约）。"""
    service = _FakeControlService()
    resources = {"cpu": 1.0, "memory_mb": 1024, "disk_mb": 2048,
                 "wall_time_s": 600}
    backend = _backend(service, scope_hash="a" * 32, resources=resources)
    backend.execute("echo hi")
    assert service.ensure_bodies == [{"scope_hash": "a" * 32,
                                      "resources": resources}]


def test_read_and_grep_funnel_through_transport():
    """T1 点名：原生 read/grep 的实际命令同样进入 FakeTransport。"""
    service = _FakeControlService()
    service.scripts.extend([{"output_tail": "hello"},
                            {"output_tail": "match"}])
    backend = _backend(service)
    backend.read("/workspace/probe.txt")
    backend.grep("after", "/workspace")
    commands = [p["command"] for p in service.operation_posts]
    assert len(commands) == 2, "read/grep 各产生一次 operation 提交"
    # read 的路径在远端脚本里是 base64 常量（deepagents 已发布实现）；
    # grep 的 pattern/路径是字面量。
    encoded = base64.b64encode(b"/workspace/probe.txt").decode()
    assert any(encoded in c for c in commands), "read 的实际路径进入传输层"
    assert any("after" in c and "/workspace" in c for c in commands)


def test_client_rejects_path_outside_workspace():
    """A2：客户端侧路径限定任务工作区，越界直接拒绝、不上传。"""
    service = _FakeControlService()
    backend = _backend(service)
    result = backend.write("/etc/passwd", "x")
    assert result.error and "工作区" in result.error
    assert service.file_puts == [], "越界路径不得进入文件传输"


async def test_execute_timeout_returns_tail_without_resubmit():
    """传输超时后同 operation_id 查询，不生成新命令（任务书 T1 明确行为）。"""
    service = _FakeControlService()
    service.scripts.append({"status": "running", "exit_code": None,
                            "output_tail": "still going"})
    service.query_scripts.extend([
        {"status": "running", "output_tail": "still going"},
        {"status": "running", "output_tail": "still going"},
    ])
    backend = _backend(service, poll_interval_s=0.01)

    result = backend.execute("sleep 60", timeout=1)
    assert result.exit_code is None, "超时无确定退出码"
    assert "still going" in result.output
    assert result.truncated is True
    operation_id = backend.last_operation_id
    assert operation_id, "调用方凭此 id 续查"
    assert len(service.operation_posts) == 1, "超时不得重发命令"
    assert service.operation_queries, "超时前至少查询过一次"

    service.query_scripts.append({"status": "succeeded", "exit_code": 0,
                                  "output_tail": "done"})
    resumed = await backend.query_operation(operation_id)
    assert resumed["status"] == "succeeded"
    assert resumed["exit_code"] == 0


async def test_async_execute_and_upload_paths():
    service = _FakeControlService()
    backend = _backend(service, poll_interval_s=0.01)
    result = await backend.aexecute("echo async-hi")
    assert result.exit_code == 0
    uploads = await backend.aupload_files([("/workspace/a.txt", b"hi")])
    assert uploads[0].error is None
    assert service.files["/workspace/a.txt"] == b"hi"
    downloads = await backend.adownload_files(["/workspace/a.txt", "/workspace/missing"])
    assert downloads[0].content == b"hi"
    assert downloads[1].error == "file_not_found"


def test_unconfigured_raises_without_fallback():
    """未配置即抛，不回落宿主执行；模块源码禁 subprocess。"""
    backend = HttpSandboxBackend(run_id="run-x")
    with pytest.raises(ExperimentSandboxError) as exc:
        backend.execute("echo never")
    assert exc.value.code == "SANDBOX_NOT_CONFIGURED"
    uploads = backend.upload_files([("/workspace/a.txt", b"x")])
    assert uploads[0].error is not None
    assert "SANDBOX_NOT_CONFIGURED" in uploads[0].error
    import ast
    import pathlib

    path = (pathlib.Path(__file__).resolve().parent.parent
            / "src" / "nexus" / "experiment_sandbox.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    # 禁的是本地执行原语的真实引用，不是注释文字（AST 级断言不怕注释误伤）。
    assert "subprocess" not in imported
    assert "multiprocessing" not in imported


def test_path_traversal_rejected_client_side():
    service = _FakeControlService()
    backend = _backend(service)
    bad = backend.upload_files([("/workspace/../escape.txt", b"x")])
    assert bad[0].error is not None and "父目录" in bad[0].error
    relative = backend.upload_files([("relative.txt", b"x")])
    assert "绝对路径" in (relative[0].error or "")
    assert service.ensure_calls == [], "拒绝发生在传输之前"
    missing = backend.download_files(["/workspace/nope"])
    assert missing[0].error == "file_not_found"


async def test_cancel_and_status_passthrough():
    service = _FakeControlService()
    backend = _backend(service)
    result = await backend.cancel()
    assert service.cancel_calls, "取消必须到达控制服务"
    assert result["status"] == "cancelled"


def test_contract_models_validate_and_reject():
    import pydantic

    scope = ExperimentScope(
        objective="配置并试跑", repo_url="https://github.com/org/repo",
        repo_revision="abc123", source_refs=[], data_refs=[],
        network_profile="pypi-allowlist",
        resources=Resources(cpu=2.0, memory_mb=4096, disk_mb=10240,
                            wall_time_s=1800),
        mode="smoke",
    )
    assert scope.allow_environment_repair is True
    with pytest.raises(pydantic.ValidationError):
        Resources(cpu=0, memory_mb=1, disk_mb=1, wall_time_s=1)
    with pytest.raises(pydantic.ValidationError):
        ExperimentScope(**{**scope.model_dump(), "mode": "yolo"})
    ok = SandboxResult(operation_id="op-1", status="running")
    assert ok.exit_code is None
